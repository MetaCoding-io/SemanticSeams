"""Human tasks end to end, in process (M009/S04 T04, ADR-0009, D027).

Both generators run on the approval fixture into tmp_path, and
seams_runtime.host serves the generated route module with SEAMS_MODEL,
SEAMS_TEMPLATES and SEAMS_DB pointing at the fixture and tmp_path, as
tests/test_expense_chapter3_app.py does for chapter 3. An employee submits an
expense; the instance waits on the approve_expense user task; the task
appears in the manager's GET /tasks inbox (and nobody else's) rendered with
its generated form; the manager completes it through the generated
completion route, and the instance finishes.
"""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen.__main__ import main  # noqa: E402
from seams_runtime.host import build_app  # noqa: E402

TRIG = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
EXPENSE = {"description": "Train to Leeds", "amount": "42.50"}
EMPLOYEE = {"X-Forwarded-User": "employee"}
MANAGER = {"X-Forwarded-User": "manager"}
JSON = {"Accept": "application/json"}


def _until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {predicate.__doc__ or predicate}")


def _status(runtime, key):
    """the instance's stored status"""
    rows = runtime.store.list_instances(correlation_key=key)
    return rows[-1]["status"] if rows else None


@pytest.fixture
def client(tmp_path, monkeypatch):
    assert main(["fastapi", str(TRIG), "--out", str(tmp_path / "gen")]) == 0
    assert main(["htmx", str(TRIG), "--out", str(tmp_path / "templates")]) == 0
    monkeypatch.setenv("SEAMS_MODEL", str(TRIG))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(tmp_path / "templates"))
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "seams.sqlite"))
    monkeypatch.delenv("SEAMS_DEV_USER", raising=False)
    monkeypatch.delenv("SEAMS_SEED", raising=False)
    app = build_app(tmp_path / "gen" / "expense_api.py")
    with TestClient(app) as c:
        yield c, app.state.runtime


def _submit(c, runtime, key="e1"):
    r = c.post(f"/expenses/{key}", data=EXPENSE, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    _until(lambda: _status(runtime, key) == "waiting")


def test_task_waits_appears_in_the_inbox_and_completes(client):
    c, runtime = client
    _submit(c, runtime)

    # the manager's inbox shows the task with its generated form and key
    r = c.get("/tasks", headers=MANAGER)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.startswith("<!doctype html>")
    assert '<main id="tasks" data-identity="manager">' in r.text
    assert r.text.count('<article class="task"') == 1
    assert 'data-task=":approval_bpmn#approve_expense"' in r.text and 'data-expense="e1"' in r.text
    assert '<form id="approve_form_e1"' in r.text and 'hx-post="/expenses/e1/approval"' in r.text
    assert '<option value="approved">approved</option>' in r.text
    assert '<dd class="description">Train to Leeds</dd>' in r.text

    [row] = c.get("/tasks", headers={**MANAGER, **JSON}).json()["tasks"]
    assert row["task"] == TASK and row["correlation_key"] == "e1"
    assert row["partial"] == "approve_form.html" and row["entity"]["status"] == "submitted"

    # the wrong person is refused before anything changes
    r = c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=EMPLOYEE)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["type"] == "PolicyDenied"
    # an invalid decision is a 422 naming the path, and nothing is stored
    r = c.post("/expenses/e1/approval", data={"decision": "maybe"}, headers=MANAGER)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation" and [x["path"] for x in detail["results"]] == ["decision"]
    assert runtime.query(":ApprovalShape") == []
    assert _status(runtime, "e1") == "waiting"

    # the manager completes it through the generated route
    r = c.post("/expenses/e1/approval", data={"decision": "approved", "comment": "fine"}, headers=MANAGER)
    assert r.status_code == 200, r.text
    assert '<section id="expense_details"' in r.text and 'data-expense="e1"' in r.text
    assert '<span class="description">Train to Leeds</span>' in r.text
    _until(lambda: _status(runtime, "e1") == "complete")
    [approval] = runtime.query(":ApprovalShape", expense="e1")
    assert approval["data"]["decision"] == "approved" and approval["data"]["comment"] == "fine"

    # the inbox is empty and the task cannot be completed twice
    r = c.get("/tasks", headers=MANAGER)
    assert r.status_code == 200 and '<article class="task"' not in r.text
    assert '<p class="empty">No open tasks.</p>' in r.text
    assert c.get("/tasks", headers={**MANAGER, **JSON}).json()["tasks"] == []
    r = c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=MANAGER)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["type"] == "TaskNotOpen"
    assert len(runtime.query(":ApprovalShape")) == 1


def test_inbox_is_per_identity(client):
    c, runtime = client
    _submit(c, runtime, "e1")
    _submit(c, runtime, "e2")

    assert [t["correlation_key"] for t in c.get("/tasks", headers={**MANAGER, **JSON}).json()["tasks"]] \
        == ["e1", "e2"]
    assert c.get("/tasks", headers=MANAGER).text.count('<article class="task"') == 2

    r = c.get("/tasks", headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    assert '<article class="task"' not in r.text and "No open tasks." in r.text
    assert c.get("/tasks", headers={**EMPLOYEE, **JSON}).json() == {"identity": "employee", "tasks": []}


@pytest.mark.parametrize("headers", [{}, JSON], ids=["html", "json"])
def test_inbox_without_identity_is_401(client, headers):
    c, runtime = client
    _submit(c, runtime)
    r = c.get("/tasks", headers=headers)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["type"] == "PolicyDenied"


def test_inbox_escapes_the_identity(client):
    c, _runtime = client
    r = c.get("/tasks", headers={"X-Forwarded-User": '<b>"x"</b>'})
    assert r.status_code == 200, r.text
    assert "<b>" not in r.text and "&lt;b&gt;&quot;x&quot;&lt;/b&gt;" in r.text


def test_dev_user_sees_the_inbox_without_a_header(tmp_path, monkeypatch, client):
    c, runtime = client
    _submit(c, runtime)
    monkeypatch.setenv("SEAMS_DEV_USER", "manager")
    app = build_app(tmp_path / "gen" / "expense_api.py")
    with TestClient(app) as dev:
        [row] = dev.get("/tasks", headers=JSON).json()["tasks"]
        assert row["correlation_key"] == "e1"
