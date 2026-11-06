"""Timers in the generators (ADR-0037 sections 1 and 3, M030/S02 T03).

The model is the scratch chapter 9 of tests/test_timer_vocabulary.py: the
overdue-approval reminder (a non-interrupting PT48H boundary timer on Approve
Expense) and a digest process started by a daily cycle, which the Expense API
executes and seam:schedules.

- fastapi: a timer-started process has no route, and a process with no way to
  start still raises;
- compose: one ``# schedules:`` comment above the scheduling service, with no
  service or binding of its own;
- sequence: the reminder has its own as-designed path, leaving Approve Expense
  open, and a fired timer row shows in the as-executed diagram;
- no generator reads the timer expression: an expression the runtime refuses
  generates the same bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import seams
import yaml

from seams_gen import GeneratorError
from seams_gen.compose import (
    extract_compose_environments,
    render_compose_environments,
    trace_compose_environments,
)
from seams_gen.fastapi import extract_routes, render_routes
from seams_gen.sequence import derive, executed, render
from tests.test_timer_vocabulary import APPROVAL, APPROVE, CHAPTER_09, DIGEST, DURATION, REMINDER, checkpoint, untimed

SCHEDULES = f"  # schedules: {DIGEST}\n  expense_api:\n"
REMINDER_PATH = "submit_expense--manager--overdue_reminder"
UNREAD = '<bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"not an ISO 8601 duration"</bpmn:timeDuration>'
NO_SCHEDULES = ("    :expense_api seam:executes :digest_process ;\n        seam:schedules :digest_process .\n", "")


def _model(tmp_path: Path, **edits):
    return seams.load(checkpoint(tmp_path, **edits))


@pytest.fixture
def timed(tmp_path):
    return _model(tmp_path)


def _hashless(text: str) -> str:
    """``text`` without the lines that carry the model hash, which any model edit changes."""
    return "\n".join(x for x in text.splitlines() if "model-hash" not in x and "MODEL_HASH" not in x)


def _compose(model) -> dict[str, str]:
    return render_compose_environments(extract_compose_environments(model, model.path.parent))


# ── fastapi: no route for a timer-started process ────────────────────────────


def _routes(model) -> str:
    return "\n".join(render_routes(extract_routes(model)).values())


def test_a_timer_started_process_gets_no_route(timed):
    text = _routes(timed)
    assert "digest" not in text
    assert "approval_process" in text  # the triggered process keeps its route


def test_the_timer_started_routes_match_the_untimed_checkpoint(timed, tmp_path):
    bare = seams.load(untimed(tmp_path))
    assert _hashless(_routes(timed)) == _hashless(_routes(bare))
    # the shipped checkpoint's reminder adds no route either
    assert _hashless(_routes(seams.load(CHAPTER_09 / "expenses.trig"))) == _hashless(_routes(bare))


def test_a_process_with_no_trigger_and_no_timer_start_still_raises(tmp_path):
    model = _model(
        tmp_path,
        trig_edits=[
            (
                "    <https://example.org/expenses/digest_bpmn#tick> a proc:TimerStartEvent ;",
                "    <https://example.org/expenses/digest_bpmn#tick> a proc:ProcessElement ;",
            )
        ],
        digest_edits=[
            (
                '      <bpmn:timerEventDefinition id="tick_def">\n'
                '        <bpmn:timeCycle xsi:type="bpmn:tFormalExpression">"R/2026-11-09T08:00:00Z/P1D"</bpmn:timeCycle>\n'
                "      </bpmn:timerEventDefinition>\n",
                "",
            )
        ],
    )
    with pytest.raises(GeneratorError) as err:
        extract_routes(model)
    assert str(err.value.subject) == DIGEST
    assert str(err.value.predicate) == str(seams.SEAM.triggers)
    assert "no proc:TimerStartEvent (ADR-0037)" in err.value.detail


def test_a_timer_the_graph_does_not_lift_names_the_timer(tmp_path):
    model = _model(
        tmp_path,
        trig_edits=[
            (
                "    <https://example.org/expenses/digest_bpmn#tick> a proc:TimerStartEvent ;",
                "    <https://example.org/expenses/digest_bpmn#tick> a proc:ProcessElement ;",
            )
        ],
    )
    with pytest.raises(GeneratorError) as err:
        extract_routes(model)
    assert str(err.value.subject) == "https://example.org/expenses/digest_bpmn#tick"
    assert str(err.value.predicate) == "bpmn:timerEventDefinition"


# ── compose: the schedules comment ───────────────────────────────────────────


def test_the_scheduling_service_carries_one_schedules_comment(timed):
    files = _compose(timed)
    assert sorted(files) == ["compose.development.yaml", "compose.production.yaml"]
    for text in files.values():
        assert text.count("# schedules:") == 1
        assert SCHEDULES in text


def test_the_comment_adds_no_service_and_no_binding(timed, tmp_path):
    bare = seams.load(untimed(tmp_path))
    for name, text in _compose(timed).items():
        before = yaml.safe_load(_compose(bare)[name])
        after = yaml.safe_load(text)
        assert sorted(after["services"]) == sorted(before["services"])
        assert after["services"]["expense_api"]["environment"].keys() == (
            before["services"]["expense_api"]["environment"].keys()
        )


def test_the_schedules_are_sorted_by_iri(tmp_path):
    """The comment lists every seam:schedules process by IRI. A second one is
    written before the first in the TriG; the shapes would refuse it (the
    approval has no timer start), but the order is the compose generator's."""
    model = _model(
        tmp_path,
        trig_edits=[
            (
                "        seam:schedules :digest_process .\n",
                "        seam:schedules :digest_process , :approval_process .\n",
            )
        ],
    )
    for text in _compose(model).values():
        assert f"  # schedules: {APPROVAL}, {DIGEST}\n  expense_api:\n" in text


def test_no_schedules_no_comment(tmp_path):
    for text in _compose(_model(tmp_path, trig_edits=[NO_SCHEDULES])).values():
        assert "# schedules:" not in text


def test_the_comment_traces_to_the_scheduled_process(timed):
    files = extract_compose_environments(timed, timed.path.parent)
    for name, trace in trace_compose_environments(files).items():
        text = render_compose_environments(files)[name]
        line = text.splitlines().index(SCHEDULES.splitlines()[0]) + 1
        (traced,) = [t for t in trace.lines if t.line == line]
        assert DIGEST in traced.terms, (name, traced)


# ── sequence: the reminder path ──────────────────────────────────────────────


def test_the_reminder_has_its_own_as_designed_path(timed):
    names = [d.name for d in derive(timed, ":submit_expense")]
    assert names == [
        "submit_expense--auto",
        "submit_expense--manager--approved",
        "submit_expense--manager--rejected",
        REMINDER_PATH,
        "submit_expense--finance--approved",
        "submit_expense--finance--rejected",
    ]


def test_the_reminder_path_leaves_the_approval_open(timed):
    (d,) = [d for d in derive(timed, ":submit_expense") if d.name == REMINDER_PATH]
    text = render(d)
    assert d.gaps == ()
    assert "%% path: manager, overdue_reminder" in text
    assert "Note over expense_api: Approve Expense: Approval overdue fires, Approve Expense stays open" in text
    assert "complete approve_expense" not in text  # nobody completed the task on this path
    (note,) = [m for m in d.messages if "Approval overdue fires" in m.line]
    assert {str(t) for t in note.terms} >= {REMINDER, APPROVE}


def test_an_interrupting_reminder_cancels_the_task(tmp_path):
    model = _model(
        tmp_path,
        bpmn_edits=[('attachedToRef="approve_expense" cancelActivity="false"', 'attachedToRef="approve_expense"')],
    )
    (d,) = [d for d in derive(model, ":submit_expense") if d.name == REMINDER_PATH]
    assert "Approval overdue fires, cancels Approve Expense" in render(d)


def test_the_approval_paths_are_unchanged_by_the_reminder(timed, tmp_path):
    bare = {d.name: render(d) for d in derive(seams.load(untimed(tmp_path)), ":submit_expense")}
    timed_paths = {d.name: render(d) for d in derive(timed, ":submit_expense") if d.name != REMINDER_PATH}
    assert timed_paths == bare


def test_a_fired_timer_row_shows_in_the_executed_diagram(timed):
    rows = [
        {"task": "persist_expense", "iri": "https://example.org/expenses/approval_bpmn#persist_expense"},
        {"task": "overdue_reminder", "iri": REMINDER, "timer": "2026-11-11T07:00:00Z"},
    ]
    d = executed(timed, ":submit_expense", rows, run="r1")
    assert "Note over expense_api: overdue_reminder timer fires (due 2026-11-11T07:00:00Z)" in render(d)
    assert not [g for g in d.gaps if "overdue_reminder" in g]


# ── never read an expression ─────────────────────────────────────────────────


def test_no_generator_reads_the_expression(tmp_path):
    timed = _model(tmp_path / "a")
    unread = _model(tmp_path / "b", bpmn_edits=[(DURATION, UNREAD)])
    assert _hashless(_routes(unread)) == _hashless(_routes(timed))
    for name, text in _compose(unread).items():
        assert _hashless(text) == _hashless(_compose(timed)[name])
    assert [render(d) for d in derive(unread, ":submit_expense")] == [
        render(d) for d in derive(timed, ":submit_expense")
    ]
