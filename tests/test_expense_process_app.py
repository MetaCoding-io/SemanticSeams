"""Expense tutorial process chapters (4 onward), in process (M009/S05).

Each examples/expenses/chapter-NN/ from chapter 4 commits the code generated
from its checkpoint. For every such chapter: the committed route module and
templates equal a fresh generator run and the generated README names the
commands; the BPMN model opens in the viewer with its diagram; and the
committed app, served by seams_runtime.host on a temp store, runs the
approval process. An employee submits an expense, the instance waits on the
approve_expense user task, the task is in an identity's GET /tasks inbox with
its generated form, and completing it through the generated route finishes
the instance. An invalid approval is a 422 that changes nothing, and the inbox
without an identity is a 401.
"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from rdflib import Namespace, URIRef

from expense_app import (
    PROCESS_CHAPTERS,
    assert_generated_current,
    chapter_dir,
    commands,
    serve,
    status,
    trace,
    until,
)
from viewer import app as viewer_app
from viewer import validation

EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
EXPENSE = {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"}
EMPLOYEE = {"X-Forwarded-User": "employee"}
APPROVER = {"X-Forwarded-User": "manager"}
JSON = {"Accept": "application/json"}
SEAM = Namespace("https://w3id.org/seams/seam#")

chapters = pytest.mark.parametrize("chapter", PROCESS_CHAPTERS)


def test_chapter_4_is_a_process_chapter():
    assert PROCESS_CHAPTERS[:1] == ["chapter-04"], PROCESS_CHAPTERS


# ── generated output ─────────────────────────────────────────────────────────


@chapters
@pytest.mark.parametrize("generator", ["fastapi", "htmx"])
def test_generated_output_is_current(chapter, generator, tmp_path):
    assert_generated_current(chapter, tmp_path, generator)


@chapters
def test_generated_readme_names_the_regenerate_commands(chapter):
    readme = (chapter_dir(chapter) / "generated" / "README.md").read_text(encoding="utf-8")
    assert "Do not edit" in readme
    for command in commands(chapter).values():
        assert command in readme


@chapters
def test_seed_is_empty(chapter):
    assert (chapter_dir(chapter) / "seed.json").read_text(encoding="utf-8").strip() == "{}"


@chapters
def test_bpmn_model_opens_in_the_viewer(chapter, monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    try:
        viewer_app.configure(chapter_dir(chapter) / "expenses.trig")
        client = TestClient(viewer_app.app)
        r = client.get(f"/view/{quote(EX + 'approval_bpmn', safe='')}")
        assert r.status_code == 200, r.text
        assert "approval.bpmn" in r.text
        payload = viewer_app.get_graph().value(URIRef(EX + "approval_bpmn"), SEAM.renderPayload)
        assert str(payload).endswith("/approval.bpmn"), payload
        r = client.get(f"/payload/{quote(str(payload), safe='')}")
        assert r.status_code == 200, r.text
        assert 'bpmn:userTask id="approve_expense"' in r.text
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


# ── the app, in process ──────────────────────────────────────────────────────


@pytest.fixture
def app(request, tmp_path, monkeypatch):
    with serve(request.param, tmp_path, monkeypatch) as served:
        yield served


process_apps = pytest.mark.parametrize("app", PROCESS_CHAPTERS, indirect=True)


def _submit(c, runtime, key="e1"):
    r = c.post(f"/expenses/{key}", data=EXPENSE, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    assert '<span class="description">Train to Leeds</span>' in r.text
    until(lambda: status(runtime, key) == "waiting")


@process_apps
def test_submitting_starts_the_process_and_waits_for_approval(app):
    c, runtime = app
    _submit(c, runtime)
    [stored] = runtime.query(":ExpenseShape", expense="e1")
    assert stored["data"]["description"] == "Train to Leeds"
    assert stored["correlation_key"] == "e1" and stored["instance_id"]
    assert [row["task"] for row in trace(runtime, "e1")] == ["start", "persist_expense"]
    # a missing seam:completedOn would leave no user_tasks row
    [row] = runtime.store.list_user_tasks()
    assert row["task"] == TASK and row["correlation_key"] == "e1"

    r = c.get("/expenses/e1")
    assert r.status_code == 200, r.text
    assert 'data-expense="e1"' in r.text and '<span class="description">Train to Leeds</span>' in r.text


@process_apps
def test_the_task_is_in_the_inbox_with_its_form(app):
    c, runtime = app
    _submit(c, runtime)

    [row] = c.get("/tasks", headers={**APPROVER, **JSON}).json()["tasks"]
    assert row["task"] == TASK and row["correlation_key"] == "e1"
    assert row["partial"] == "approve_form.html" and row["screen"] == "/approvals"
    assert row["entity"]["description"] == "Train to Leeds"

    r = c.get("/tasks", headers=APPROVER)
    assert r.status_code == 200, r.text
    assert r.text.startswith("<!doctype html>")
    assert r.text.count('<article class="task"') == 1
    assert '<form id="approve_form_e1"' in r.text and 'hx-post="/expenses/e1/approval"' in r.text
    assert '<option value="approved">approved</option>' in r.text
    assert '<option value="rejected">rejected</option>' in r.text
    assert '<dd class="description">Train to Leeds</dd>' in r.text

    # no policy yet (chapter 7): any authenticated identity sees the task
    assert len(c.get("/tasks", headers={**EMPLOYEE, **JSON}).json()["tasks"]) == 1


@process_apps
def test_approving_finishes_the_instance(app):
    c, runtime = app
    _submit(c, runtime)

    r = c.post("/expenses/e1/approval", data={"decision": "approved", "comment": "fine"}, headers=APPROVER)
    assert r.status_code == 200, r.text
    assert '<section id="expense_details"' in r.text and 'data-expense="e1"' in r.text
    until(lambda: status(runtime, "e1") == "complete")

    [approval] = runtime.query(":ApprovalShape", expense="e1")
    assert approval["data"] == {"decision": "approved", "comment": "fine"}
    rows = {row["task"]: row for row in trace(runtime, "e1")}
    assert rows["approve_expense"]["by"] == "manager"
    assert rows["approve_expense"]["writes"] == [approval["id"]]

    assert c.get("/tasks", headers={**APPROVER, **JSON}).json()["tasks"] == []
    assert '<p class="empty">No open tasks.</p>' in c.get("/tasks", headers=APPROVER).text
    r = c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=APPROVER)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["type"] == "TaskNotOpen"


@process_apps
@pytest.mark.parametrize("data, paths", [
    ({"decision": "maybe"}, ["decision"]),
    ({}, ["decision"]),
    ({"decision": "approved", "comment": "x" * 501}, ["comment"]),
], ids=["not-in-list", "missing", "comment-too-long"])
def test_invalid_approval_is_rejected_and_changes_nothing(app, data, paths):
    c, runtime = app
    _submit(c, runtime)
    r = c.post("/expenses/e1/approval", data=data, headers=APPROVER)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation"
    assert sorted(x["path"] for x in detail["results"]) == paths
    assert runtime.query(":ApprovalShape") == []
    assert status(runtime, "e1") == "waiting"
    assert len(c.get("/tasks", headers={**APPROVER, **JSON}).json()["tasks"]) == 1


@process_apps
def test_invalid_expense_starts_no_process(app):
    c, runtime = app
    r = c.post("/expenses/e1", data={**EXPENSE, "amount": "-5"}, headers=EMPLOYEE)
    assert r.status_code == 422, r.text
    assert [x["path"] for x in r.json()["detail"]["results"]] == ["amount"]
    assert runtime.store.list_instances() == [] and runtime.query(":ExpenseShape") == []


@process_apps
@pytest.mark.parametrize("headers", [{}, JSON], ids=["html", "json"])
def test_inbox_without_identity_is_401(app, headers):
    c, runtime = app
    _submit(c, runtime)
    r = c.get("/tasks", headers=headers)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["type"] == "PolicyDenied"


@process_apps
def test_completing_without_identity_is_401(app):
    c, runtime = app
    _submit(c, runtime)
    r = c.post("/expenses/e1/approval", data={"decision": "approved"})
    assert r.status_code == 401, r.text
    assert status(runtime, "e1") == "waiting"
