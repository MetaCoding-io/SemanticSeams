"""The finished expense app end to end against the live docker compose stack (M009/S07/T03).

Runs only with SEAMS_E2E=1 (CI's tutorial-e2e job); the normal suite stays
docker-free. With SEAMS_E2E=1 nothing skips: a missing docker CLI or a stack
that does not come up healthy is a failure.

The stack is examples/expenses/chapter-08's generated compose.yaml merged with
its hand-written compose.override.yaml (project seams-expenses, so it never
collides with the chat app's stack). Caddy passes X-Forwarded-User and
X-Forwarded-Groups through to the runtime's HeaderAuthenticator, so each
request says who makes it. The flow is the tutorial's: the employee submits,
the manager approves through the generated form route, finance pays, and the
channel-started payout process (ADR-0010) runs on its own until the finance
console's /payouts page shows the payment in its final state and the expense
paid. On any failure the module prints ``docker compose logs``; teardown
always runs ``docker compose down -v`` and checks no container is left.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "examples" / "expenses" / "chapter-08"
FILES = ["-f", str(APP / "compose.yaml"), "-f", str(APP / "compose.override.yaml")]
PROJECT = "seams-expenses"
BASE = "http://localhost:8080"
UP_TIMEOUT = 300  # seconds: image build plus healthchecks on a cold runner
POLL_TIMEOUT = 30

EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
PAYMENT = {"reference": "PAY-0042", "paid_on": "2026-10-05"}

pytestmark = pytest.mark.skipif(os.environ.get("SEAMS_E2E") != "1",
                                reason="live docker compose test; set SEAMS_E2E=1")


def person(name: str, *roles: str) -> dict[str, str]:
    return {"X-Forwarded-User": name, "X-Forwarded-Groups": ",".join(roles)}


ALICE = person("alice", "employee")
BOB = person("bob", "manager")
CAROL = person("carol", "finance")


def _compose(*args, timeout=120, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "-p", PROJECT, *FILES, *args], cwd=ROOT,
                          timeout=timeout, check=check, capture_output=True, text=True)


def _logs() -> str:
    try:
        return _compose("logs", "--no-color", check=False).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(docker compose logs failed: {exc})"


def _show(request, text: str) -> None:
    # bypass capture so the logs reach the console even from a passing teardown
    capture = request.config.pluginmanager.getplugin("capturemanager")
    with capture.global_and_fixture_disabled():
        print(text)


@pytest.fixture(scope="module")
def stack(request):
    if shutil.which("docker") is None:
        pytest.fail("SEAMS_E2E=1 but the docker CLI is not on PATH")
    failed_before = request.session.testsfailed
    try:
        try:
            _compose("up", "-d", "--build", "--wait", timeout=UP_TIMEOUT)
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"docker compose up failed ({exc.returncode}):\n{exc.stdout}\n{exc.stderr}\n"
                        f"--- docker compose logs ---\n{_logs()}")
        except subprocess.TimeoutExpired:
            pytest.fail(f"docker compose up did not finish within {UP_TIMEOUT}s\n"
                        f"--- docker compose logs ---\n{_logs()}")
        with httpx.Client(base_url=BASE, timeout=10) as client:
            yield client
        if request.session.testsfailed > failed_before:
            _show(request, f"--- docker compose logs ---\n{_logs()}")
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=180)
        left = _compose("ps", "-a", "-q", check=False).stdout.strip()
        assert not left, f"docker compose down -v left containers: {left}"


def _post_when_open(client, path, data, headers) -> httpx.Response:
    """POST a task form, retrying while the task is not open yet (409): the
    process reaches the user task asynchronously after the previous step."""
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        r = client.post(path, data=data, headers=headers)
        if r.status_code != 409 or time.monotonic() > deadline:
            return r
        time.sleep(0.5)


def _until_page_shows(client, path, *needles) -> str:
    deadline = time.monotonic() + POLL_TIMEOUT
    body = ""
    while time.monotonic() < deadline:
        r = client.get(path)
        assert r.status_code == 200, r.text
        body = r.text
        if all(n in body for n in needles):
            return body
        time.sleep(0.5)
    pytest.fail(f"{path} never showed {needles!r}:\n{body}")


def test_landmark_page_has_the_submit_form(stack):
    r = stack.get("/")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert '<main id="expenses_page" data-seam=":expenses_page">' in r.text
    assert 'hx-post="/expenses/' in r.text


def test_submit_approve_pay_runs_the_payout(stack):
    key = f"e2e-{uuid.uuid4().hex[:8]}"
    r = stack.post(f"/expenses/{key}", data={**EXPENSE, "amount": "250.00"}, headers=ALICE)
    assert r.status_code == 200, r.text

    r = _post_when_open(stack, f"/expenses/{key}/approval", {"decision": "approved"}, BOB)
    assert r.status_code == 200, r.text
    r = _post_when_open(stack, f"/expenses/{key}/payment", PAYMENT, CAROL)
    assert r.status_code == 200, r.text

    # Nobody drives the payout: the paid end event publishes on :payouts and
    # the runtime starts the payout process, which batches an amount up to 500.
    body = _until_page_shows(stack, "/payouts", '<span class="reference">PAY-0042</span>',
                             '<span class="status">batched</span>',
                             '<span class="description">Train to Leeds</span>',
                             '<span class="status">paid</span>')
    assert body.lstrip().startswith("<!doctype html>")
    assert '<main id="payouts_page" data-seam=":payouts_page">' in body


def test_invalid_submit_is_rejected(stack):
    r = stack.post(f"/expenses/bad-{uuid.uuid4().hex[:8]}",
                   data={**EXPENSE, "amount": "not a number"}, headers=ALICE)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["type"] == "ContractViolation"


def test_submit_without_an_identity_is_unauthorised(stack):
    r = stack.post(f"/expenses/anon-{uuid.uuid4().hex[:8]}", data={**EXPENSE, "amount": "250.00"})
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["type"] == "PolicyDenied"
