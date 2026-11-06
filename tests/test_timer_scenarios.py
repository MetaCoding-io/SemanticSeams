"""Scenarios and coverage over a timer (M030/S02 T04, ADR-0037).

Chapters 9 to 11 ship the overdue-approval reminder: a non-interrupting PT48H boundary
timer on Approve Expense that runs to a "Reminded" end and leaves the task open. The
scenario :manager_reminded covers it.

- ``seams.coverage`` credits a walk through a timer boundary without a verify:failure.
  The task the walk leaves through the timer is one no step completes, and no step's
  task may follow the timer, since a run fires the timers only after its last step.
- ``seams_runtime.verify.run_scenario`` fires, once each and in due order, the timer
  catches the waiting instance is armed with once the steps are done. It fires them
  through a ``Scheduler`` whose clock stands at each due time, so the run needs no wall
  clock and no SEAMS_CLOCK_OFFSET.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import seams
from seams_cli.project import load_project, resolve_model

from seams_runtime.verify import FAILED, WAITING, Request, Scenario, Step, run_scenario, serve
from tests.test_timer_vocabulary import APPROVAL, APPROVE, CHAPTER_09, REMINDER, untimed

EX = "https://example.org/expenses/"
REMINDED = EX + "approval_bpmn#reminder_end"
GENERATED = CHAPTER_09 / "generated"
EMPLOYEE, MANAGER = EX + "employee", EX + "manager"
EXPENSE = (("amount", "200.00"), ("date", "2026-10-01"), ("description", "Train to Leeds"))


def _reminder_paths(model):
    return [p for p in seams.process_paths(model, APPROVAL) if REMINDER in {str(i) for i in p.iris}]


def _scenario_iris(path) -> list[str]:
    return [str(s.iri) for s in path.scenarios]


# ── coverage ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("chapter", ["chapter-09", "chapter-10", "chapter-11"])
def test_the_reminder_path_is_run_by_manager_reminded_alone(chapter):
    model = seams.load(resolve_model(load_project(CHAPTER_09.parent / chapter)))
    (path,) = _reminder_paths(model)
    assert [n.bpmn_id for n in path.nodes][-3:] == ["approve_expense", "overdue_reminder", "reminder_end"]
    assert _scenario_iris(path) == [EX + "manager_reminded"]


def test_chapter_9_leaves_no_path_unrun():
    assert seams.unexercised_paths(seams.load(CHAPTER_09 / "expenses.trig")) == ()


def test_the_untimed_copy_has_no_reminder_path(tmp_path):
    assert _reminder_paths(seams.load(untimed(tmp_path))) == []


def _edited(tmp_path: Path, old: str, new: str, bpmn_edit: tuple[str, str] | None = None):
    trig = CHAPTER_09 / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    app = tmp_path / "chapter-09"
    app.mkdir()
    for f in CHAPTER_09.iterdir():
        if f.is_file():
            (app / f.name).write_bytes(f.read_bytes())
    (app / "expenses.trig").write_text(text.replace(old, new), encoding="utf-8")
    if bpmn_edit is not None:
        bpmn = (app / "approval.bpmn").read_text(encoding="utf-8")
        assert bpmn.count(bpmn_edit[0]) == 1, bpmn_edit[0]
        (app / "approval.bpmn").write_text(bpmn.replace(*bpmn_edit), encoding="utf-8")
    return seams.load(app / "expenses.trig")


REMINDED_END = "        verify:expectEndEvent <https://example.org/expenses/approval_bpmn#reminder_end> ."
STEPPED = (
    "        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#approve_expense> ;\n"
    "                        verify:actor :manager ;\n"
    '                        verify:given [ verify:field :decision ; verify:value "approved" ] ] ) ;\n'
)


def test_a_step_on_the_task_the_timer_leaves_is_not_this_run(tmp_path):
    # Completing Approve Expense would cancel the reminder: the run is the approved one.
    model = _edited(tmp_path, REMINDED_END, STEPPED + REMINDED_END)
    (path,) = _reminder_paths(model)
    assert _scenario_iris(path) == []


def test_an_end_the_reminder_never_reaches_is_not_its_run(tmp_path):
    model = _edited(tmp_path, REMINDED_END, REMINDED_END.replace("reminder_end", "rejected_end"))
    (path,) = _reminder_paths(model)
    assert _scenario_iris(path) == []


def test_a_failure_the_reminder_walk_never_meets_is_not_its_run(tmp_path):
    model = _edited(
        tmp_path,
        REMINDED_END,
        "        verify:failure [ verify:operation :notify_manager_op ; verify:status :notify_failed ] ;\n"
        + REMINDED_END,
    )
    (path,) = _reminder_paths(model)
    # The walk invokes notify_manager_op but leaves it normally, not through its error boundary.
    assert _scenario_iris(path) == []


def test_a_step_after_the_timer_is_not_credited(tmp_path):
    # The reminder escalates to finance: a step on Finance Approve Expense would have to
    # run after the timer, but a run fires its timers only once the steps are done.
    finance = (
        "        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#finance_approve_expense> ;\n"
        "                        verify:actor :finance ;\n"
        '                        verify:given [ verify:field :decision ; verify:value "rejected" ] ] ) ;\n'
    )
    model = _edited(
        tmp_path,
        REMINDED_END,
        finance + REMINDED_END.replace("reminder_end", "rejected_end"),
        (
            'sourceRef="overdue_reminder" targetRef="reminder_end"',
            'sourceRef="overdue_reminder" targetRef="finance_approve_expense"',
        ),
    )
    escalated = [p for p in _reminder_paths(model) if p.end.bpmn_id == "rejected_end"]
    assert len(escalated) == 1 and "finance_approve_expense" in escalated[0].bpmn_ids
    assert _scenario_iris(escalated[0]) == []


# ── the run ──────────────────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_path):
    routes, templates = GENERATED / "expense_api.py", GENERATED / "templates"
    with serve(CHAPTER_09 / "expenses.trig", routes, templates, tmp_path / "s.sqlite") as served:
        yield served


def _scenario(key: str, steps=()) -> Scenario:
    return Scenario(
        iri=EX + key,
        process=APPROVAL,
        key_variable="expense",
        key=key,
        start=Request("POST", "/expenses/{expense}", EMPLOYEE, EXPENSE),
        steps=steps,
        entity_shape=EX + "ExpenseShape",
    )


def test_the_run_fires_the_reminder_and_leaves_the_task_open(app):
    client, runtime = app
    run = run_scenario(client, runtime, _scenario("reminded"))
    assert run.status == WAITING and run.error is None
    assert run.state == "submitted"
    assert run.reached[-2:] == (REMINDER, REMINDED)
    open_tasks = [r["task"] for r in runtime.store.list_user_tasks() if r["correlation_key"] == "reminded"]
    assert open_tasks == [APPROVE]
    # fired once: nothing is armed any more, though the task stays open
    assert [t for t in runtime.store.list_timers() if t["kind"] == "catch"] == []


def test_the_fired_row_carries_its_due_time(app):
    client, runtime = app
    run_scenario(client, runtime, _scenario("due"))
    (row,) = [i for i in runtime.store.list_instances(correlation_key="due")]
    workflow = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"]))
    (fired,) = [r for r in workflow.data["seams"]["trace"] if r["iri"] == REMINDER]
    assert fired["timer"].endswith("Z") and len(fired["timer"]) == len("2026-11-11T07:00:00Z")


def test_a_run_whose_step_completes_the_task_fires_nothing(app):
    client, runtime = app
    step = Step(APPROVE, Request("POST", "/expenses/{expense}/approval", MANAGER, (("decision", "approved"),)))
    run = run_scenario(client, runtime, _scenario("approved", (step,)))
    assert run.status != FAILED, run.error
    assert run.state == "approved"
    assert REMINDER not in run.reached and REMINDED not in run.reached
