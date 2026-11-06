"""ADR-0037 (M030/S01): timers and scheduling are decided before the runtime.
The ADR lifts BPMN timer events as proc:TimerStartEvent and proc:TimerCatchEvent with
the expression kept in the XML, accepts only ISO 8601 literals with a fixed offset,
names the scheduling container with seam:schedules, makes each firing run once through
claims in the shared store, and moves seam to 1.6 and proc to 1.1 with no migration."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0037-timers-and-scheduling.md"


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text
    assert "**Date:** 2026-11-06" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences", "Open questions"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))
    assert len(numbers) == 5


@pytest.mark.parametrize(
    "heading",
    [
        "Timer events are lifted as `proc:TimerStartEvent` and `proc:TimerCatchEvent`; the expression stays in the XML",
        "Expressions are ISO 8601 literals with a fixed offset, and anything else is refused",
        "`seam:schedules` names the container that runs a process's timer starts",
        "Each firing runs once: claims in the shared store",
        "Observability, and `seam` 1.6 and `proc` 1.1 as compatible widenings",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


def test_lifting_scope(text: str) -> None:
    section = _section(text, "### 1. Timer events are lifted")
    rows = re.findall(r"^\| `(bpmn:\w+)`[^|]*\| ([^|]+) \| (yes|no)\b", section, re.MULTILINE)
    assert [(element, kind.strip(), scope) for element, kind, scope in rows] == [
        ("bpmn:startEvent", "`proc:TimerStartEvent`", "yes"),
        ("bpmn:intermediateCatchEvent", "`proc:TimerCatchEvent`", "yes"),
        ("bpmn:boundaryEvent", "`proc:TimerCatchEvent`", "yes"),
        ("bpmn:boundaryEvent", "not lifted", "no"),
        ("bpmn:startEvent", "not lifted", "no"),
    ]
    flat = _flat(section)
    assert "attached to a `proc:UserTask`" in flat
    assert "The expression is **not** copied into the graph." in flat
    assert "ResolutionError(<event>, bpmn:timerEventDefinition, <what disagrees>)" in flat
    assert "`_triggered` skips it" in flat
    assert "overdue-approval reminder is a non-interrupting boundary timer" in flat


def test_expressions_are_iso_8601_only(text: str) -> None:
    section = _section(text, "### 2. Expressions are ISO 8601 literals")
    elements = re.findall(r"^\| `(bpmn:\w+)` \|", section, re.MULTILINE)
    assert elements == ["bpmn:timeDate", "bpmn:timeDuration", "bpmn:timeCycle"]
    flat = _flat(section)
    for refused in ["a cron string", "a date-time with no offset", "a cycle with no start (`R/P1D`", "an empty body"]:
        assert refused in flat, refused
    assert "ResolutionError(<event>, bpmn:timeCycle, \"cycle has no start date-time: 'R/P1D'\")" in flat
    assert "`Runtime.load` raises it" in flat
    assert "`seams check` reports the same check" in flat
    assert "The generators never read an expression" in flat


def test_scheduling_seam(text: str) -> None:
    section = _flat(_section(text, "### 3. `seam:schedules` names the container"))
    assert "`arch:Container -> proc:Process`, in the seams graph (ADR-0001)" in section
    assert "must also `seam:executes` the process" in section
    assert "`seamsh:SchedulesShape`" in section
    assert "`seamsh:TimerStartedProcessShape`" in section
    assert "is the object of exactly one `seam:schedules`" in section
    assert "ResolutionError(<process>, seam:schedules, <sorted container IRIs>)" in section
    assert "listed, never derived from `seam:executes`" in section
    assert "seam:schedules/seam:deployedTo" in section
    assert "The compose generator** adds no service and no binding" in section
    assert "capped at one replica (ADR-0015)" in section


def test_single_firing_under_replicas(text: str) -> None:
    section = _flat(_section(text, "### 4. Each firing runs once"))
    assert "`Store.transaction()` (ADR-0035) on SQLite and PostgreSQL" in section
    assert "Due times are computed, not observed." in section
    assert "All due times are UTC." in section
    assert "`(start event IRI, due time)`" in section
    assert "in the same transaction" in section
    assert "A timer catch is claimed by a lease." in section
    assert "only if it still holds the lease" in section
    assert "fires only the latest of them" in section
    assert "The clock is injected." in section
    assert "the generated files carry no timestamp" in section


def test_observability_and_versions(text: str) -> None:
    section = _section(text, "### 5. Observability")
    flat = _flat(section)
    assert "`timer fire <event> due <due> instance <id>`" in flat
    assert "`timer missed <event> N firing(s)`" in flat
    assert "`seams.timer.claim`" in flat
    assert "`seams.timer.fire`" in flat
    assert "no migration files" in flat
    versions = re.findall(r"^\| `(\w+)` \| `([\d.]+)` to `([\d.]+)` \|", section, re.MULTILINE)
    assert versions == [("seam", "1.5", "1.6"), ("proc", "1.0", "1.1")]


@pytest.mark.parametrize(
    "term",
    ["refresh_waiting_tasks()", "SpiffWorkflow 3.2", "M030/S02", "M030/S03", "A10", "chapter 9", "PT48H"],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term.lower() in text.lower(), term


@pytest.mark.parametrize(
    "link",
    [
        "(./0001-named-graph-partitioning.md)",
        "(./0002-iri-identity-and-migration.md)",
        "(./0007-execution-strategy.md)",
        "(./0010-channel-started-processes.md)",
        "(./0015-environments.md)",
        "(./0035-aggregate-transaction-boundary.md)",
        "(../research/2026-10-29-uml-coverage-and-gaps.md)",
        "(../research/2026-10-29-runtime-storage.md)",
    ],
)
def test_adr_links(text: str, link: str) -> None:
    assert link in text


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0037", "Timers and scheduling", "0037-timers-and-scheduling"]' in config
    assert config.index("0036-cross-aggregate-invariants") < config.index("0037-timers-and-scheduling")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "[ADR-0037](./0037-timers-and-scheduling)" in index
    assert index.index("0036-cross-aggregate-invariants") < index.index("0037-timers-and-scheduling")


def test_backlog_notes_the_adr() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| U10 |"))
    assert "[ADR-0037](adr/0037-timers-and-scheduling.md) accepted (M030/S01)" in row
