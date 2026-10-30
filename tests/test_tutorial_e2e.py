"""docs/tutorial.md end to end against the live docker compose stack (M004/S07/T06).

Runs only with SEAMS_E2E=1 (CI's tutorial-e2e job); the normal suite stays
docker-free. With SEAMS_E2E=1 nothing skips: a missing docker CLI or a stack
that does not come up healthy is a failure.

The stack is the generated compose.yaml merged with compose.override.yaml,
with the gateway forced into stub mode (LLM_GATEWAY_STUB=1), so the reply is
the gateway's deterministic "Stub reply to: <content>". The flow is the
tutorial's "open http://localhost:8080 and chat": load the landmark page,
post the compose form, read the token stream, see the thread update.
On any failure the module prints ``docker compose logs``; teardown always
runs ``docker compose down -v`` and checks no container is left.
"""

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8080"
KEY_FILE = ROOT / ".secrets" / "llm_api_key"
UP_TIMEOUT = 300  # seconds: image builds plus healthchecks on a cold runner
STREAM_TIMEOUT = 30
POLL_TIMEOUT = 30
MESSAGE_SHAPE = "https://example.org/chat/MessageShape"
MESSAGE_DB = "https://example.org/chat/message_db"
# docker compose arguments for a psql query against the declared store
# (docs/tutorial.md shows the same command; tests/test_tutorial_doc.py checks)
PSQL = ("exec", "-T", "message_db", "psql", "-U", "postgres", "-d", "chat", "-tAc")

pytestmark = pytest.mark.skipif(os.environ.get("SEAMS_E2E") != "1", reason="live docker compose test; set SEAMS_E2E=1")


def _compose(*args, timeout=120, check=True) -> subprocess.CompletedProcess:
    env = {**os.environ, "LLM_GATEWAY_STUB": "1"}
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, env=env, timeout=timeout, check=check, capture_output=True, text=True
    )


def landed_sql(marker: str) -> str:
    """The query docs/tutorial.md's "See where it landed" step runs: the
    shape of each stored entity whose data mentions ``marker``. ``marker`` is
    a hex uuid fragment, so it needs no quoting."""
    return f"SELECT shape FROM entities WHERE data::text LIKE '%{marker}%'"


def _psql(sql: str) -> subprocess.CompletedProcess:
    return _compose(*PSQL, sql, check=False)


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
    # Stub mode: an empty key file satisfies the llm_api_key secret.
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.touch()
    failed_before = request.session.testsfailed
    try:
        try:
            _compose("up", "-d", "--build", "--wait", timeout=UP_TIMEOUT)
        except subprocess.CalledProcessError as exc:
            pytest.fail(
                f"docker compose up failed ({exc.returncode}):\n{exc.stdout}\n{exc.stderr}\n"
                f"--- docker compose logs ---\n{_logs()}"
            )
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"docker compose up did not finish within {UP_TIMEOUT}s\n--- docker compose logs ---\n{_logs()}"
            )
        with httpx.Client(base_url=BASE, timeout=10) as client:
            yield client
        if request.session.testsfailed > failed_before:
            _show(request, f"--- docker compose logs ---\n{_logs()}")
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=180)
        left = _compose("ps", "-a", "-q", check=False).stdout.strip()
        assert not left, f"docker compose down -v left containers: {left}"


@pytest.fixture(scope="module")
def page(stack) -> str:
    r = stack.get("/")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    return r.text


@pytest.fixture(scope="module")
def messages_url(page) -> str:
    m = re.search(r'<form id="compose_form"[^>]*?hx-post="([^"]+)"', page, re.S)
    assert m, "the landmark page has no compose form with an hx-post URL"
    return m.group(1)


@pytest.fixture(scope="module")
def sent(stack, messages_url) -> str:
    """Post the compose form once; return the content sent."""
    content = f"hello {uuid.uuid4().hex[:8]}"
    r = stack.post(messages_url, data={"content": content})
    assert r.status_code == 200, r.text
    assert '<li class="message">' in r.text and f"<p>{content}</p>" in r.text, r.text
    return content


def test_page_lists_seeded_conversations_and_the_compose_form(page, messages_url):
    for title in ("Welcome", "Scratch pad"):
        assert title in page
    assert 'id="compose_form"' in page and 'name="content"' in page
    assert re.fullmatch(r"/conversations/[^/]+/messages", messages_url), messages_url


def test_token_stream_carries_the_reply(stack, messages_url, sent):
    stream_url = messages_url.rsplit("/", 1)[0] + "/stream"
    deadline = time.monotonic() + STREAM_TIMEOUT
    event = None
    with stack.stream("GET", stream_url, timeout=httpx.Timeout(10, read=STREAM_TIMEOUT)) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                if event == "token":
                    break
            if time.monotonic() > deadline:
                break
    assert event == "token", f"no token event on {stream_url} within {STREAM_TIMEOUT}s"


def test_thread_shows_the_message_and_the_stub_reply(stack, messages_url, sent):
    reply = f"Stub reply to: {sent}"
    deadline = time.monotonic() + POLL_TIMEOUT
    body = ""
    while time.monotonic() < deadline:
        r = stack.get(messages_url)
        assert r.status_code == 200, r.text
        body = r.text
        if f"<p>{sent}</p>" in body and f"<p>{reply}</p>" in body:
            return
        time.sleep(0.5)
    pytest.fail(f"thread at {messages_url} never showed {sent!r} and {reply!r}:\n{body}")


def test_empty_content_is_rejected(stack, messages_url):
    r = stack.post(messages_url, data={"content": ""})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["type"] == "ContractViolation"


def test_the_sent_message_lands_in_the_message_store(stack, sent):
    """The model says MessageShape seam:storedIn :message_db, a PostgreSQL
    store chat_api connectsTo: the row is in message_db, not a SQLite file."""
    marker = sent.rsplit(" ", 1)[1]
    deadline = time.monotonic() + POLL_TIMEOUT
    out = None
    while time.monotonic() < deadline:
        out = _psql(landed_sql(marker))
        if out.returncode == 0 and MESSAGE_SHAPE in out.stdout.split():
            return
        time.sleep(0.5)
    pytest.fail(f"no {MESSAGE_SHAPE} row mentioning {marker!r} in message_db: {out}")


def test_healthz_reports_the_declared_postgres_store(stack):
    r = stack.get("/healthz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["store"] == {"kind": "postgresql", "declared": "PostgreSQL", "container": MESSAGE_DB, "override": False}
