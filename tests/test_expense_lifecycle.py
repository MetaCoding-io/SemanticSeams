"""Expense tutorial chapter 6: the lifecycle guard and the visibleWhen block (M009/S05).

examples/expenses/chapter-06/ gives :ExpenseShape the :expense_lifecycle
statechart (draft, submitted, approved, rejected, paid). Process tasks name
their transition with seam:fires, and the runtime's LifecycleGuard refuses one
the expense's current state does not allow. That happens before the task runs
(worker rule 1), so a refused transition writes nothing. The tests check this
directly on the guard and through the process: in a copy of the checkpoint
whose :record_approval fires :t_pay (approved to paid) instead of :t_approve,
an auto-approved expense fails the instance with the transition named and its
stored status still "submitted".

:awaiting_approval carries seam:visibleWhen :s_submitted. Its generated
partial, served by GET /expenses/{expense}/awaiting-approval, shows the
expense while it waits for a decision and renders nothing once it is decided
(or before it exists).
"""

import pytest

from expense_app import chapter_dir, copy_checkpoint, serve, serve_directory, status, trace, until
from seams_runtime.errors import LifecycleViolation, ResolutionError

CHAPTER = "chapter-06"
EX = "https://example.org/expenses/"
EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
SMALL, MID = "42.50", "250.00"
EMPLOYEE = {"X-Forwarded-User": "employee"}
APPROVER = {"X-Forwarded-User": "manager"}
SECTION = '<section id="awaiting_approval"'

# The chapter page's "provoke a refusal" edit: record_approval fires t_pay.
FIRES_APPROVE = "<https://example.org/expenses/approval_bpmn#record_approval> seam:fires :t_approve ."
FIRES_PAY = "<https://example.org/expenses/approval_bpmn#record_approval> seam:fires :t_pay ."


@pytest.fixture
def app(tmp_path, monkeypatch):
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def _submit(c, runtime, key, amount):
    r = c.post(f"/expenses/{key}", data={**EXPENSE, "amount": amount}, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    return until(lambda: status(runtime, key) in ("waiting", "complete", "failed") and status(runtime, key))


def _seams_state(runtime, key) -> dict:
    [*_, row] = runtime.store.list_instances(correlation_key=key)
    return runtime.engine.deserialize(runtime.store.load_state(row["instance_id"])).data["seams"]


# ── the guard ────────────────────────────────────────────────────────────────


def test_guard_allows_the_lifecycle_transitions(app):
    _c, runtime = app
    guard = runtime.guard
    assert guard.apply(":ExpenseShape", None, ":t_submit") == "submitted"  # None: the initial draft
    assert guard.apply(":ExpenseShape", "submitted", ":t_approve") == "approved"
    assert guard.apply(":ExpenseShape", "submitted", ":t_reject") == "rejected"
    assert guard.apply(":ExpenseShape", "approved", ":t_pay") == "paid"


@pytest.mark.parametrize("current, transition, required", [
    ("approved", "t_approve", "submitted"),
    ("rejected", "t_approve", "submitted"),
    ("approved", "t_reject", "submitted"),
    ("submitted", "t_pay", "approved"),
    ("submitted", "t_submit", "draft"),
    (None, "t_approve", "submitted"),
])
def test_guard_refuses_an_illegal_transition(app, current, transition, required):
    _c, runtime = app
    with pytest.raises(LifecycleViolation) as refused:
        runtime.guard.check(":ExpenseShape", current, f":{transition}")
    err = refused.value
    assert err.transition == EX + transition
    assert err.current_state == (current or "draft") and err.expected_from == required
    assert transition in str(err) and repr(current or "draft") in str(err)
    assert err.http_status == 409


def test_guard_refuses_a_transition_of_no_lifecycle(app):
    _c, runtime = app
    with pytest.raises(ResolutionError) as refused:
        runtime.guard.check(":ExpenseShape", "submitted", ":s_approved")
    assert "s_approved is not a transition of this lifecycle" in str(refused.value)


# ── the guard in the process ─────────────────────────────────────────────────


@pytest.fixture
def pay_too_early(tmp_path, monkeypatch):
    """chapter-06 with :record_approval firing :t_pay, regenerated and served."""
    copy, _ = copy_checkpoint(CHAPTER, tmp_path, "expenses.trig", FIRES_APPROVE, FIRES_PAY)
    with serve_directory(copy, tmp_path, monkeypatch) as served:
        yield served


def test_the_chapter_has_the_edit_the_page_describes():
    assert (chapter_dir(CHAPTER) / "expenses.trig").read_text(encoding="utf-8").count(FIRES_APPROVE) == 1


def test_an_illegal_transition_fails_the_instance_and_writes_nothing(pay_too_early):
    c, runtime = pay_too_early
    assert _submit(c, runtime, "small", SMALL) == "failed"

    st = _seams_state(runtime, "small")
    error = st["error"]
    assert error["type"] == "LifecycleViolation", error
    assert error["transition"] == EX + "t_pay"
    assert (error["current_state"], error["expected_from"]) == ("submitted", "approved")
    assert "t_pay" in error["message"] and "'submitted'" in error["message"], error

    # refused before record_approval ran: the expense stays submitted
    [expense] = runtime.query(":ExpenseShape", expense="small")
    assert expense["status"] == expense["data"]["status"] == "submitted"
    assert st["history"][EX + "ExpenseShape"] == ["draft", "submitted"]
    assert [row["task"] for row in trace(runtime, "small")] == [
        "start", "persist_expense", "route_expense", "route_gateway"]
    assert runtime.store.list_user_tasks() == []


def test_the_same_edit_refuses_a_manager_approval(pay_too_early):
    c, runtime = pay_too_early
    assert _submit(c, runtime, "mid", MID) == "waiting"
    r = c.post("/expenses/mid/approval", data={"decision": "approved"}, headers=APPROVER)
    assert r.status_code == 200, r.text  # the task completed; the process fails after it
    until(lambda: status(runtime, "mid") == "failed")
    assert _seams_state(runtime, "mid")["error"]["transition"] == EX + "t_pay"
    [expense] = runtime.query(":ExpenseShape", expense="mid")
    assert expense["status"] == "submitted"
    # the rejection path does not fire t_pay, so it still works
    assert _submit(c, runtime, "other", MID) == "waiting"
    c.post("/expenses/other/approval", data={"decision": "rejected"}, headers=APPROVER)
    until(lambda: status(runtime, "other") == "complete")
    assert runtime.query(":ExpenseShape", expense="other")[0]["status"] == "rejected"


# ── seam:visibleWhen ─────────────────────────────────────────────────────────


def _awaiting(c, key) -> str:
    r = c.get(f"/expenses/{key}/awaiting-approval")
    assert r.status_code == 200, r.text
    return r.text


def test_awaiting_approval_shows_only_while_submitted(app):
    c, runtime = app
    assert _submit(c, runtime, "mid", MID) == "waiting"
    html = _awaiting(c, "mid")
    assert SECTION in html and 'data-expense="mid"' in html
    assert '<span class="description">Train to Leeds</span>' in html
    assert '<span class="status">submitted</span>' in html

    c.post("/expenses/mid/approval", data={"decision": "approved"}, headers=APPROVER)
    until(lambda: status(runtime, "mid") == "complete")
    assert runtime.query(":ExpenseShape", expense="mid")[0]["status"] == "approved"
    assert SECTION not in _awaiting(c, "mid")
    assert _awaiting(c, "mid").strip() == ""
    # the unguarded details still show the decided expense
    assert '<span class="status">approved</span>' in c.get("/expenses/mid").text


@pytest.mark.parametrize("key, amount, decision", [
    ("small", SMALL, None),
    ("rejected", MID, "rejected"),
])
def test_awaiting_approval_is_absent_once_decided(app, key, amount, decision):
    c, runtime = app
    _submit(c, runtime, key, amount)
    if decision:
        c.post(f"/expenses/{key}/approval", data={"decision": decision}, headers=APPROVER)
    until(lambda: status(runtime, key) == "complete")
    assert SECTION not in _awaiting(c, key)


def test_awaiting_approval_is_absent_for_an_unknown_expense(app):
    c, _runtime = app
    # no entity: the guard variable is the lifecycle's initial state, draft
    assert SECTION not in _awaiting(c, "nobody")


@pytest.mark.parametrize("state, shown", [
    ("draft", False), ("submitted", True), ("approved", False), ("rejected", False), ("paid", False),
])
def test_the_guard_compares_the_state_label(app, state, shown):
    _c, runtime = app
    expense = {"description": "Train to Leeds", "amount": MID, "date": "2026-10-01", "status": state}
    html = runtime.render_fragment("awaiting_approval.html", [expense], expense="e1").body.decode()
    assert (SECTION in html) is shown
