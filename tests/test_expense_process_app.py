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

Chapter 5 adds the routing decision table. One served module sends a small,
a mid and a large amount down three paths (auto-approved, manager, finance),
with the decision's output in the trace. Editing a threshold in approval.dmn
and regenerating changes only the model-hash lines of the generated code, and
the regenerated app routes the same amount differently. A table that matches
no rule, or an output no gateway condition accepts, fails the instance with
the error recorded.

Chapter 6 adds the expense lifecycle. Every path leaves the stored expense in
its decided state (auto and approvals: approved; a rejection: rejected), and
the instance's lifecycle history records the sequence (draft, submitted,
decided). The guard's refusal and the seam:visibleWhen block are in
tests/test_expense_lifecycle.py.
"""

import shutil
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from rdflib import Namespace, URIRef

from expense_app import (
    PROCESS_CHAPTERS,
    assert_generated_current,
    chapter_dir,
    commands,
    copy_checkpoint,
    serve,
    serve_directory,
    status,
    trace,
    until,
)
from test_generated_outputs_current import HAND_WRITTEN, committed_files
from viewer import app as viewer_app
from viewer import validation

EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
FINANCE_TASK = EX + "approval_bpmn#finance_approve_expense"
# From chapter 5 the amount routes the approval; 250.00 goes to the manager
# (approve_expense) there, as every submission does in chapter 4.
EXPENSE = {"description": "Train to Leeds", "amount": "250.00", "date": "2026-10-01"}
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
    tasks = [row["task"] for row in trace(runtime, "e1")]
    assert tasks[:2] == ["start", "persist_expense"] and "approve_expense" not in tasks
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


# ── chapter 5: the routing decision table ────────────────────────────────────

CHAPTER_5 = "chapter-05"
SMALL, MID, LARGE = "42.50", "250.00", "5000.00"
# The approval route each path's open task is completed on.
APPROVAL_ROUTES = {"approve_expense": "approval", "finance_approve_expense": "finance-approval"}


def test_chapter_5_is_a_process_chapter():
    assert CHAPTER_5 in PROCESS_CHAPTERS, PROCESS_CHAPTERS


@pytest.fixture
def rules_app(tmp_path, monkeypatch):
    with serve(CHAPTER_5, tmp_path, monkeypatch) as served:
        yield served


def _submit_amount(c, runtime, key, amount, final=("waiting", "complete", "failed")):
    r = c.post(f"/expenses/{key}", data={**EXPENSE, "amount": amount}, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    return until(lambda: status(runtime, key) in final and status(runtime, key))


def _decision(runtime, key) -> dict:
    [row] = [r for r in trace(runtime, key) if r["task"] == "route_expense"]
    assert row["decision"] == EX + "approval_routing"
    return row["outputs"]


def _open_tasks(runtime) -> dict[str, str]:
    """correlation key -> bpmn id of its open user task"""
    return {row["correlation_key"]: row["bpmn_id"] for row in runtime.store.list_user_tasks()}


def test_three_amounts_take_three_paths_through_one_module(rules_app):
    c, runtime = rules_app
    assert _submit_amount(c, runtime, "small", SMALL) == "complete"
    assert _submit_amount(c, runtime, "mid", MID) == "waiting"
    assert _submit_amount(c, runtime, "large", LARGE) == "waiting"

    assert {key: _decision(runtime, key) for key in ("small", "mid", "large")} == {
        "small": {"route": "auto"}, "mid": {"route": "manager"}, "large": {"route": "finance"}}
    assert [r["task"] for r in trace(runtime, "small")] == [
        "start", "persist_expense", "route_expense", "route_gateway", "auto_approved"]
    assert _open_tasks(runtime) == {"mid": "approve_expense", "large": "finance_approve_expense"}
    # every amount was stored by the same process, whatever its path
    assert sorted(e["correlation_key"] for e in runtime.query(":ExpenseShape")) == ["large", "mid", "small"]

    inbox = {row["correlation_key"]: row for row in c.get("/tasks", headers={**APPROVER, **JSON}).json()["tasks"]}
    assert set(inbox) == {"mid", "large"}
    assert (inbox["mid"]["task"], inbox["mid"]["partial"]) == (TASK, "approve_form.html")
    assert (inbox["large"]["task"], inbox["large"]["partial"]) == (FINANCE_TASK, "finance_approve_form.html")
    assert inbox["large"]["screen"] == "/approvals" and inbox["large"]["entity"]["amount"] == LARGE
    html = c.get("/tasks", headers=APPROVER).text
    assert 'hx-post="/expenses/mid/approval"' in html
    assert 'hx-post="/expenses/large/finance-approval"' in html


@pytest.mark.parametrize("key, amount, task", [
    ("mid", MID, "approve_expense"),
    ("large", LARGE, "finance_approve_expense"),
])
def test_completing_the_routed_task_finishes_the_instance(rules_app, key, amount, task):
    c, runtime = rules_app
    assert _submit_amount(c, runtime, key, amount) == "waiting"
    r = c.post(f"/expenses/{key}/{APPROVAL_ROUTES[task]}", data={"decision": "approved"}, headers=APPROVER)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, key) == "complete")
    rows = {row["task"]: row for row in trace(runtime, key)}
    assert rows["route_expense"]["outputs"] == {"route": "manager" if task == "approve_expense" else "finance"}
    assert rows[task]["by"] == "manager"
    [approval] = runtime.query(":ApprovalShape", expense=key)
    assert rows[task]["writes"] == [approval["id"]]
    assert _open_tasks(runtime) == {}


@pytest.mark.parametrize("key, amount, wrong", [
    ("mid", MID, "finance_approve_expense"),
    ("large", LARGE, "approve_expense"),
])
def test_the_other_paths_task_is_not_open(rules_app, key, amount, wrong):
    c, runtime = rules_app
    _submit_amount(c, runtime, key, amount)
    r = c.post(f"/expenses/{key}/{APPROVAL_ROUTES[wrong]}", data={"decision": "approved"}, headers=APPROVER)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["type"] == "TaskNotOpen"
    assert status(runtime, key) == "waiting"


def test_small_amount_has_nothing_to_approve(rules_app):
    c, runtime = rules_app
    _submit_amount(c, runtime, "small", SMALL)
    assert c.get("/tasks", headers={**APPROVER, **JSON}).json()["tasks"] == []
    r = c.post("/expenses/small/approval", data={"decision": "approved"}, headers=APPROVER)
    assert r.status_code == 409, r.text


def test_dmn_model_opens_in_the_viewer(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    try:
        viewer_app.configure(chapter_dir(CHAPTER_5) / "expenses.trig")
        client = TestClient(viewer_app.app)
        r = client.get(f"/view/{quote(EX + 'approval_dmn', safe='')}")
        assert r.status_code == 200, r.text
        assert "approval.dmn" in r.text
        payload = viewer_app.get_graph().value(URIRef(EX + "approval_dmn"), SEAM.renderPayload)
        r = client.get(f"/payload/{quote(str(payload), safe='')}")
        assert r.status_code == 200, r.text
        assert '<decision id="approval_routing"' in r.text and "dmndi:DMNDI" in r.text
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


# ── chapter 5: the threshold lives in the model ──────────────────────────────


def _copy_chapter_5(tmp_path, old: str, new: str):
    """chapter-05 copied to tmp_path with ``old`` replaced by ``new`` (once)
    in approval.dmn, and both generators rerun into the copy's generated/."""
    return copy_checkpoint(CHAPTER_5, tmp_path, "approval.dmn", old, new)


def _committed_chapter_5() -> dict[str, str]:
    generated = chapter_dir(CHAPTER_5) / "generated"
    templates = committed_files(generated / "templates")
    return {**committed_files(generated, HAND_WRITTEN), **{f"templates/{n}": t for n, t in templates.items()}}


MANAGER_UP_TO_1000 = "<text>&lt;= 1000</text>"
MANAGER_UP_TO_200 = "<text>&lt;= 200</text>"


def test_changing_the_threshold_moves_only_the_hash_lines(tmp_path):
    _copy, regenerated = _copy_chapter_5(tmp_path, MANAGER_UP_TO_1000, MANAGER_UP_TO_200)
    committed = _committed_chapter_5()
    assert regenerated.keys() == committed.keys()
    changed = []
    for name in sorted(committed):
        new, old = regenerated[name].splitlines(), committed[name].splitlines()
        assert len(new) == len(old), name
        changed += [(name, a, b) for a, b in zip(old, new) if a != b]
    assert changed, "the model hash covers approval.dmn, so it must change"
    for name, old, new in changed:
        assert "model-hash" in old or "MODEL_HASH" in old, (name, old, new)
        assert "model-hash" in new or "MODEL_HASH" in new, (name, old, new)


def test_the_regenerated_app_routes_the_mid_amount_to_finance(tmp_path, monkeypatch):
    copy, _ = _copy_chapter_5(tmp_path, MANAGER_UP_TO_1000, MANAGER_UP_TO_200)
    with serve_directory(copy, tmp_path, monkeypatch) as (c, runtime):
        assert _submit_amount(c, runtime, "mid", MID) == "waiting"
        assert _decision(runtime, "mid") == {"route": "finance"}
        assert _open_tasks(runtime) == {"mid": "finance_approve_expense"}
        assert _submit_amount(c, runtime, "small", SMALL) == "complete"


def test_the_committed_module_refuses_the_edited_model(tmp_path, monkeypatch):
    copy, _ = _copy_chapter_5(tmp_path, MANAGER_UP_TO_1000, MANAGER_UP_TO_200)
    shutil.copy(chapter_dir(CHAPTER_5) / "generated" / "expense_api.py", copy / "generated" / "expense_api.py")
    from seams_runtime import ModelHashMismatch
    with pytest.raises(ModelHashMismatch):
        with serve_directory(copy, tmp_path, monkeypatch):
            pass


# ── chapter 5: failure modes ─────────────────────────────────────────────────


def _failed_error(c, runtime, key, amount) -> dict:
    assert _submit_amount(c, runtime, key, amount) == "failed"
    [row] = runtime.store.list_instances(correlation_key=key)
    error = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"])).data["seams"]["error"]
    assert _open_tasks(runtime) == {}
    return error


def test_a_table_that_matches_no_rule_fails_the_instance(tmp_path, monkeypatch):
    # Without the catch-all finance rule, a large amount matches nothing.
    rule = """      <rule id="rule_finance">
        <inputEntry id="rule_finance_amount"><text>-</text></inputEntry>
        <outputEntry id="rule_finance_out"><text>"finance"</text></outputEntry>
      </rule>
"""
    copy, _ = _copy_chapter_5(tmp_path, rule, "")
    with serve_directory(copy, tmp_path, monkeypatch) as (c, runtime):
        error = _failed_error(c, runtime, "large", LARGE)
        assert error["type"] == "ResolutionError", error
        assert "'approval_routing' produced no 'Route'" in error["message"], error
        assert _submit_amount(c, runtime, "mid", MID) == "waiting"


def test_an_output_no_gateway_condition_accepts_fails_the_instance(tmp_path, monkeypatch):
    copy, _ = _copy_chapter_5(tmp_path, '<text>"finance"</text>', '<text>"board"</text>')
    with serve_directory(copy, tmp_path, monkeypatch) as (c, runtime):
        error = _failed_error(c, runtime, "large", LARGE)
        assert "route_gateway" in error["message"] or "Route?" in error["message"], error
        assert _decision(runtime, "large") == {"route": "board"}


# ── chapter 6: the lifecycle ─────────────────────────────────────────────────

CHAPTER_6 = "chapter-06"
EXPENSE_SHAPE = EX + "ExpenseShape"


def test_chapter_6_is_a_process_chapter():
    assert CHAPTER_6 in PROCESS_CHAPTERS, PROCESS_CHAPTERS


@pytest.fixture
def lifecycle_app(tmp_path, monkeypatch):
    with serve(CHAPTER_6, tmp_path, monkeypatch) as served:
        yield served


def _history(runtime, key) -> list[str]:
    """The expense's lifecycle states, in order, from the instance checkpoint."""
    [*_, row] = runtime.store.list_instances(correlation_key=key)
    wf = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"]))
    return wf.data["seams"]["history"][EXPENSE_SHAPE]


def _stored_status(runtime, key) -> str:
    [expense] = runtime.query(":ExpenseShape", expense=key)
    assert expense["data"]["status"] == expense["status"], expense
    return expense["status"]


@pytest.mark.parametrize("amount, task, decision, final, recorder", [
    (SMALL, None, None, "approved", "record_approval"),
    (MID, "approve_expense", "approved", "approved", "record_approval"),
    (MID, "approve_expense", "rejected", "rejected", "record_rejection"),
    (LARGE, "finance_approve_expense", "approved", "approved", "record_approval"),
    (LARGE, "finance_approve_expense", "rejected", "rejected", "record_rejection"),
], ids=["auto", "manager-approves", "manager-rejects", "finance-approves", "finance-rejects"])
def test_each_path_leaves_the_expense_in_its_decided_state(lifecycle_app, amount, task, decision,
                                                            final, recorder):
    c, runtime = lifecycle_app
    if task is None:
        assert _submit_amount(c, runtime, "e1", amount) == "complete"
    else:
        assert _submit_amount(c, runtime, "e1", amount) == "waiting"
        # waiting on a person: the expense is submitted, not yet decided
        assert _stored_status(runtime, "e1") == "submitted"
        r = c.post(f"/expenses/e1/{APPROVAL_ROUTES[task]}", data={"decision": decision}, headers=APPROVER)
        assert r.status_code == 200, r.text
        until(lambda: status(runtime, "e1") == "complete")

    assert _stored_status(runtime, "e1") == final
    assert _history(runtime, "e1") == ["draft", "submitted", final]
    rows = {row["task"]: row for row in trace(runtime, "e1")}
    assert rows["persist_expense"]["fires"] == EX + "t_submit"
    assert rows["persist_expense"]["status"] == "submitted"
    assert rows[recorder]["fires"] == EX + ("t_approve" if final == "approved" else "t_reject")
    assert rows[recorder]["status"] == final
    other = {"record_approval", "record_rejection"} - {recorder}
    assert not other & rows.keys()
    if task is not None:
        assert "decision_gateway" in rows and rows[task]["by"] == "manager"


def test_three_amounts_reach_their_states_in_one_app(lifecycle_app):
    c, runtime = lifecycle_app
    _submit_amount(c, runtime, "small", SMALL)
    _submit_amount(c, runtime, "mid", MID)
    _submit_amount(c, runtime, "large", LARGE)
    assert {key: _stored_status(runtime, key) for key in ("small", "mid", "large")} == {
        "small": "approved", "mid": "submitted", "large": "submitted"}
    c.post("/expenses/mid/approval", data={"decision": "rejected"}, headers=APPROVER)
    c.post("/expenses/large/finance-approval", data={"decision": "approved"}, headers=APPROVER)
    until(lambda: status(runtime, "mid") == status(runtime, "large") == "complete")
    assert {key: _stored_status(runtime, key) for key in ("small", "mid", "large")} == {
        "small": "approved", "mid": "rejected", "large": "approved"}


def test_lifecycle_model_opens_in_the_viewer(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    try:
        viewer_app.configure(chapter_dir(CHAPTER_6) / "expenses.trig")
        r = TestClient(viewer_app.app).get(f"/view/{quote(EX + 'expense_lifecycle', safe='')}")
        assert r.status_code == 200, r.text
        for state in ("draft", "submitted", "approved", "rejected", "paid"):
            assert state in r.text, state
    finally:
        viewer_app.configure(original)
        validation._clear_cache()

