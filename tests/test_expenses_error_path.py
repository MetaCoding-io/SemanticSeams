"""Expense tutorial chapter 9: the notify task's error path (ADR-0013, M014/S04 T04).

:notify_manager_op declares one error, :notify_failed (hydra:Status 502,
comm:errorCode "notify-failed", body :NotifyProblemShape). The handler raises
it when the message is longer than a text message holds. An error boundary on
Notify Manager in approval.bpmn, lifted as a proc:ErrorBoundaryEvent that
seam:catches :notify_failed, routes the expense to finance's approval task
instead of failing the instance. The trace rows and spans record the code, the
status and the boundary taken, and the viewer draws the boundary on its task
with a seam badge that navigates to the status.
"""

from __future__ import annotations

import importlib.util
from urllib.parse import quote

import pytest
from expense_app import chapter_dir, copy_checkpoint, serve, status, trace, until
from fastapi.testclient import TestClient

from seams_runtime import OperationError, ResolutionError, Runtime
from seams_runtime.store import SQLiteStore
from seams_runtime.telemetry import element_attributes
from viewer import app as viewer_app
from viewer import validation

CHAPTER = "chapter-09"
EX = "https://example.org/expenses/"
BPMN = EX + "approval_bpmn#"
NOTIFY, BOUNDARY = BPMN + "notify_manager", BPMN + "notify_failed_boundary"
NOTIFY_OP, NOTIFY_FAILED = EX + "notify_manager_op", EX + "notify_failed"
PROBLEM_SHAPE = EX + "NotifyProblemShape"
DATE = "2026-10-01"
ALICE = {"X-Forwarded-User": "alice", "X-Forwarded-Groups": "employee"}
BOB = {"X-Forwarded-User": "bob", "X-Forwarded-Groups": "manager"}
CAROL = {"X-Forwarded-User": "carol", "X-Forwarded-Groups": "finance"}
SUFFIX = f" (250.00, {DATE}) is waiting for your approval."


def description(message_length: int) -> str:
    """A description whose notification message, at 250.00, is ``message_length`` characters."""
    return "x" * (message_length - len(SUFFIX))


def notify_module():
    spec = importlib.util.spec_from_file_location("ch9_notify", chapter_dir(CHAPTER) / "handlers" / "notify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMS_HANDLERS", raising=False)
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def _submit(c, runtime, key, desc):
    r = c.post(f"/expenses/{key}", data={"description": desc, "amount": "250.00", "date": DATE}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, key) in ("waiting", "complete", "failed"))
    assert status(runtime, key) == "waiting", trace(runtime, key)


def _open_tasks(runtime, key) -> set[str]:
    return {t["bpmn_id"] for t in runtime.store.list_user_tasks() if t["correlation_key"] == key}


def _current(runtime, key) -> dict:
    [*_, row] = [
        r for r in runtime.store.list_instances(correlation_key=key) if r["process"] == EX + "approval_process"
    ]
    return runtime.engine.deserialize(runtime.store.load_state(row["instance_id"])).data["seams"]["current"]


# ── the handler ──────────────────────────────────────────────────────────────


def test_the_handler_sends_a_message_that_fits_a_text_message():
    notify = notify_module()
    entity = {"description": description(notify.MAX_MESSAGE), "amount": "250.00", "date": DATE}
    assert len(notify.notify_manager(entity)["message"]) == notify.MAX_MESSAGE


def test_the_handler_raises_the_declared_error_one_character_over():
    notify = notify_module()
    entity = {"description": description(notify.MAX_MESSAGE + 1), "amount": "250.00", "date": DATE}
    with pytest.raises(OperationError) as raised:
        notify.notify_manager(entity)
    assert raised.value.code == "notify-failed"
    assert raised.value.detail == "the message is 161 characters; a text message holds 160"


# ── load: the graph and approval.bpmn agree ─────────────────────────────────


def _load(trig, tmp_path) -> Runtime:
    return Runtime.load(trig, store=SQLiteStore(tmp_path / "seams.sqlite"))


def test_the_runtime_resolves_the_boundary_at_load(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)
    runtime = _load(chapter_dir(CHAPTER) / "expenses.trig", tmp_path)
    [(key, boundary)] = runtime.boundaries.items()
    assert (str(key[0]), key[1]) == (NOTIFY, "notify-failed")
    assert str(boundary.iri) == BOUNDARY
    assert str(boundary.operation.iri) == NOTIFY_OP and str(boundary.status.iri) == NOTIFY_FAILED
    assert boundary.node.bpmn_id == "notify_failed_boundary"


@pytest.mark.parametrize(
    ("file", "old", "new"),
    [
        # the XML's errorCode no longer matches the status's comm:errorCode
        ("approval.bpmn", 'errorCode="notify-failed"', 'errorCode="notify-down"'),
        # the boundary is lifted but catches nothing
        ("expenses.trig", "seam:catches :notify_failed .", "rdfs:comment :notify_failed ."),
    ],
    ids=["code-mismatch", "catches-nothing"],
)
def test_a_boundary_the_graph_and_the_xml_disagree_on_is_a_load_fault(tmp_path, monkeypatch, file, old, new):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)
    copy, _ = copy_checkpoint(CHAPTER, tmp_path, file, old, new)
    with pytest.raises(ResolutionError) as raised:
        _load(copy / "expenses.trig", tmp_path)
    assert raised.value.subject.endswith("notify_failed_boundary")
    assert raised.value.predicate.endswith("catches")


# ── run: the error path ──────────────────────────────────────────────────────


def test_a_message_too_long_to_send_routes_the_expense_to_finance(app):
    c, runtime = app
    _submit(c, runtime, "e-long", description(161))
    rows = trace(runtime, "e-long")
    tasks = [r["task"] for r in rows]
    assert tasks[tasks.index("notify_manager") :] == ["notify_manager", "notify_failed_boundary"]
    by_task = {r["task"]: r for r in rows}
    notify = by_task["notify_manager"]
    assert notify["error"] == {"code": "notify-failed", "status": NOTIFY_FAILED, "operation": NOTIFY_OP}
    assert notify["boundary"] == BOUNDARY
    assert "writes" not in notify
    assert by_task["notify_failed_boundary"]["caught"] == "notify-failed"
    # finance decides instead of the manager, and no notification was stored
    assert _open_tasks(runtime, "e-long") == {"finance_approve_expense"}
    assert runtime.query(":NotificationShape") == []
    [expense] = runtime.query(":ExpenseShape", expense="e-long")
    assert expense["status"] == "submitted"
    # the validated problem+json body is the error shape's current entity
    problem = _current(runtime, "e-long")[PROBLEM_SHAPE]["data"]
    assert problem == {
        "title": "Notification failed",
        "status": 502,
        "detail": "the message is 161 characters; a text message holds 160",
    }


def test_the_spans_record_the_caught_error(app):
    c, runtime = app
    _submit(c, runtime, "e-span", description(200))
    by_task = {r["task"]: r for r in trace(runtime, "e-span")}
    attrs = element_attributes(by_task["notify_manager"])
    assert attrs["seams.error.code"] == "notify-failed"
    assert attrs["seams.error.status"] == NOTIFY_FAILED
    assert attrs["seams.boundary"] == BOUNDARY
    assert element_attributes(by_task["notify_failed_boundary"])["seams.caught"] == "notify-failed"


def test_finance_approves_the_escalated_expense_and_it_goes_on_to_payment(app):
    c, runtime = app
    _submit(c, runtime, "e-esc", description(161))
    # the manager has no open task to decide
    assert c.post("/expenses/e-esc/approval", data={"decision": "approved"}, headers=BOB).status_code != 200
    r = c.post("/expenses/e-esc/finance-approval", data={"decision": "approved"}, headers=CAROL)
    assert r.status_code == 200, r.text
    until(lambda: "pay_expense" in _open_tasks(runtime, "e-esc"))
    tasks = [row["task"] for row in trace(runtime, "e-esc")]
    assert "finance_approve_expense" in tasks and "record_approval" in tasks
    assert "approve_expense" not in tasks
    [expense] = runtime.query(":ExpenseShape", expense="e-esc")
    assert expense["status"] == "approved"


def test_a_message_that_fits_takes_the_happy_path(app):
    c, runtime = app
    _submit(c, runtime, "e-fits", description(160))
    rows = {r["task"]: r for r in trace(runtime, "e-fits")}
    assert "notify_failed_boundary" not in rows
    assert "error" not in rows["notify_manager"] and "boundary" not in rows["notify_manager"]
    assert _open_tasks(runtime, "e-fits") == {"approve_expense"}
    [notification] = runtime.query(":NotificationShape", expense="e-fits")
    assert len(notification["data"]["message"]) == 160


def test_an_undeclared_handler_fault_still_fails_the_instance(app, monkeypatch):
    """Only the declared notify-failed takes the boundary; any other exception
    fails the instance as ADR-0012 says."""
    c, runtime = app
    impl = runtime.implementations
    op = next(k for k in impl if str(k) == NOTIFY_OP)

    def broken(entity):
        raise OperationError("notify-lost", "no such error")

    monkeypatch.setitem(impl, op, (impl[op][0], broken))
    r = c.post("/expenses/e-bad", data={"description": "Taxi", "amount": "250.00", "date": DATE}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, "e-bad") == "failed")
    assert "notify_failed_boundary" not in [row["task"] for row in trace(runtime, "e-bad")]
    assert _open_tasks(runtime, "e-bad") == set()


# ── the viewer ───────────────────────────────────────────────────────────────


@pytest.fixture
def viewer(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    viewer_app.configure(chapter_dir(CHAPTER) / "expenses.trig")
    try:
        yield TestClient(viewer_app.app)
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


def _view(client, iri: str) -> str:
    r = client.get(f"/view/{quote(iri, safe='')}", headers={"hx-request": "true"})
    assert r.status_code == 200, r.text
    return r.text


def test_the_bpmn_view_gives_the_boundary_a_seam_badge(viewer):
    """bpmn-js draws the boundary from approval.bpmn; the fragment maps its
    native id to its IRI and gives it one badge, seam:catches the status."""
    assert viewer_app.payload_element_map(EX + "approval_bpmn")["notify_failed_boundary"] == BOUNDARY
    [badge] = viewer_app.payload_element_seams(EX + "approval_bpmn")["notify_failed_boundary"]
    assert (badge["predicate"], badge["target"], badge["targetLabel"]) == (
        "seam:catches",
        NOTIFY_FAILED,
        "Notification failed",
    )
    html = _view(viewer, EX + "approval_bpmn")
    assert f'"notify_failed_boundary": "{BOUNDARY}"' in html
    assert "seamsDecorateDiagram" in html


def test_the_payload_has_the_boundary_drawn_on_its_task(viewer):
    payload = viewer_app.render_payload_of(EX + "approval_bpmn")
    xml = viewer.get("/payload/" + quote(payload, safe="")).text
    assert 'attachedToRef="notify_manager"' in xml
    assert 'bpmnElement="notify_failed_boundary"' in xml


def test_the_status_shows_the_boundary_that_catches_it(viewer):
    html = _view(viewer, NOTIFY_FAILED)
    assert 'data-predicate="seam:catches"' in html
    assert quote(BOUNDARY, safe="") in html
    assert 'data-predicate="seam:returnsShape"' in html
