"""The derived event-storm view (backlog B4): ``seams_gen.storm`` reads a
process's timeline from graph facts alone.

The golden is approval_process in the expense tutorial's chapter 10, rendered
as Markdown. Regenerate it deliberately with ``uv run python tests/test_storm.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from seams import local_name

from seams_gen import GeneratorError
from seams_gen.storm import derive, find_process, render

ROOT = Path(__file__).resolve().parent.parent
CH09 = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"
CH10 = ROOT / "examples" / "expenses" / "chapter-10" / "expenses.trig"
GOLDEN = ROOT / "tests" / "golden" / "storm" / "approval_process.md"
EX = "https://example.org/expenses/"


@pytest.fixture(scope="module")
def ch10():
    return seams.load(CH10)


@pytest.fixture(scope="module")
def ch09():
    return seams.load(CH09)


def test_approval_process_matches_the_golden(ch10):
    assert render(derive(ch10, "approval_process")) == GOLDEN.read_text(encoding="utf-8")


def test_render_is_deterministic(ch10):
    assert render(derive(ch10, "approval_process")) == render(derive(seams.load(CH10), "approval_process"))


@pytest.mark.parametrize("name", ["submit_expense", ":submit_expense", EX + "submit_expense", ":approval_process"])
def test_names_resolve_to_approval_process(ch10, name):
    assert find_process(ch10, name).iri == URIRef(EX + "approval_process")
    assert render(derive(ch10, name)) == GOLDEN.read_text(encoding="utf-8")


def test_approval_process_facts(ch10):
    storm = derive(ch10, "approval_process")
    assert [local_name(s.iri) for s in storm.steps][:3] == [
        "submit_expense",
        "persist_expense",
        "route_expense",
    ]
    assert [local_name(e.iri) for e in storm.actors] == ["employee", "manager", "finance", "finance"]
    assert [local_name(e.iri) for e in storm.events] == ["t_submit", "t_approve", "t_pay", "t_reject"]
    assert [local_name(e.iri) for e in storm.decisions] == ["approval_routing"]
    assert [local_name(e.iri) for e in storm.channels] == ["payouts"]
    assert [local_name(e.iri) for e in storm.processes] == ["payout_process"]
    assert "ApprovalShape has no read model: no ifml page or component seam:reads it" in storm.gaps


def test_payout_process_on_chapter_9(ch09):
    storm = derive(ch09, "payout_process")
    assert [s.name for s in storm.steps] == [
        "Payout Requested",
        "Schedule Payout",
        "Choose Payout",
        "Add to Batch",
        "Send Now",
    ]
    assert storm.actors == ()
    (command,) = storm.commands
    assert "on channel `payouts`, published by `approved_end` (Expense Approval)" in command.text
    assert [local_name(e.iri) for e in storm.events] == ["t_schedule", "t_batch", "t_send"]
    assert [local_name(e.iri) for e in storm.decisions] == ["payout_method"]
    assert {local_name(e.iri) for e in storm.aggregates} == {"PaymentShape"}
    assert [local_name(e.iri) for e in storm.read_models] == ["payment_list"]
    assert storm.gaps == ()
    text = render(storm)
    assert text.startswith("# Event storm: Expense Payout\n")
    assert "## Gaps\n\nNone.\n" in text


@pytest.mark.parametrize("name", ["no_such_process", ":no_such_process", "nope:approval_process"])
def test_unknown_name_names_the_argument(ch10, name):
    with pytest.raises(GeneratorError, match=r"no such proc:Process") as err:
        derive(ch10, name)
    assert err.value.subject == name


def test_event_that_triggers_nothing_names_the_argument(ch10):
    with pytest.raises(GeneratorError, match=r"seam:triggers: ifml:Event triggers no proc:Process") as err:
        find_process(ch10, "submit_approval")
    assert err.value.subject == "submit_approval"


if __name__ == "__main__":  # regenerate the golden, deliberately
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(render(derive(seams.load(CH10), "approval_process")), encoding="utf-8")
    sys.exit(0)
