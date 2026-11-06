"""Timers in the runtime (ADR-0037 sections 2 and 4, M030/S02 T02).

``seams_runtime.timers`` parses each lifted timer's ISO 8601 expression and
refuses every other body, computes due times in UTC, reads time from an
injected clock and runs the scheduler: a timer start is claimed by inserting
its firing row in the transaction that starts and checkpoints the instance,
and a timer catch by a lease on its row, deleted only while the lease holds.

The model is the scratch chapter 9 of tests/test_timer_vocabulary.py: the
overdue-approval reminder (a non-interrupting PT48H boundary timer on Approve
Expense) and a digest process started by a daily cycle that then waits an
hour on an intermediate timer catch. Its event subprocess is left out: Spiff
refuses a subprocess with no end event, and the runtime parses the BPMN.
Time is a ``Stepped`` clock the tests move, so nothing waits.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from seams_cli.check import check_timers

from seams_runtime import ResolutionError, Runtime, SQLiteStore, Telemetry
from seams_runtime.model import SEAM
from seams_runtime.policy import Identity
from seams_runtime.runtime import check_timer_store
from seams_runtime.timers import (
    CLOCK_OFFSET_ENV,
    Duration,
    Timer,
    clock_from_env,
    format_due,
    format_due_floor,
    parse_expression,
)
from tests.test_timer_vocabulary import (
    API,
    APPROVAL,
    APPROVE,
    CHAPTER_09,
    DIGEST,
    DIGEST_XML,
    DURATION,
    REMINDER,
    TICK,
    checkpoint,
)

SETTLE = "https://example.org/expenses/digest_bpmn#settle"
EXPENSE = {"description": "Team lunch", "amount": "250.00", "date": "2026-10-01"}
MANAGER = Identity("bob", frozenset({"manager"}))
CYCLE = '<bpmn:timeCycle xsi:type="bpmn:tFormalExpression">"R/2026-11-09T08:00:00Z/P1D"</bpmn:timeCycle>'
NO_SUBPROCESS = (DIGEST_XML[DIGEST_XML.index("    <bpmn:subProcess") : DIGEST_XML.index("  </bpmn:process>")], "")
SCHEDULES = " ;\n        seam:schedules :digest_process ."


class Stepped:
    """A clock the test moves."""

    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at

    def step(self, **delta) -> None:
        self.at += timedelta(**delta)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("SEAMS_MODEL", "SEAMS_HANDLERS", "SEAMS_STORE_OVERRIDE", CLOCK_OFFSET_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clock() -> Stepped:
    return Stepped(datetime(2026, 11, 9, 7, 0, tzinfo=UTC))


def model(tmp_path: Path, *, trig_edits=(), bpmn_edits=(), digest_edits=()) -> Path:
    """The scratch chapter 9 with the reminder and the digest, then the edits."""
    return checkpoint(
        tmp_path, trig_edits=trig_edits, bpmn_edits=bpmn_edits, digest_edits=(NO_SUBPROCESS, *digest_edits)
    )


def load(trig: Path, store, clock, **kwargs) -> Runtime:
    return Runtime.load(trig, store=store, clock=clock, **kwargs)


def reminders(trig: Path, store, clock) -> Runtime:
    """A runtime whose scheduler leaves the digest's daily start alone."""
    rt = load(trig, store, clock)
    rt.scheduler.starts = []
    return rt


def refused(trig: Path, tmp_path: Path) -> ResolutionError:
    with pytest.raises(ResolutionError) as err:
        Runtime.load(trig, store=SQLiteStore(tmp_path / "seams.sqlite"))
    return err.value


async def submit(rt: Runtime, key: str = "e1") -> dict:
    inst = await rt.start_process(APPROVAL, EXPENSE, key)
    result = await inst.wait()
    assert result["status"] == "waiting", result
    return result


async def drain(instances) -> list[dict]:
    return [await i.wait() for i in instances]


def processes(rt: Runtime, process: str) -> list[dict]:
    return [r for r in rt.store.list_instances() if r["process"] == process]


def rows(rt: Runtime, kind: str) -> list[dict]:
    return [r for r in rt.store.list_timers() if r["kind"] == kind]


def tasks(row: dict) -> list[str]:
    return [t["task"] for t in row["trace"]]


# ── section 2: expressions ───────────────────────────────────────────────────

ACCEPTED = [
    ("timeDate", '"2026-12-01T09:00:00Z"', datetime(2026, 12, 1, 9, tzinfo=UTC), None, None),
    ("timeDate", "'2026-12-01T10:00:00+01:00'", datetime(2026, 12, 1, 9, tzinfo=UTC), None, None),
    ("timeDuration", '"PT48H"', None, Duration(hours=48), None),
    ("timeDuration", ' "P2W" ', None, Duration(weeks=2), None),
    ("timeDuration", '"P1Y2M3DT4H5M6S"', None, Duration(1, 2, 0, 3, 4, 5, 6), None),
    ("timeCycle", '"R/2026-11-09T08:00:00Z/P1D"', datetime(2026, 11, 9, 8, tzinfo=UTC), Duration(days=1), None),
    ("timeCycle", '"R5/2026-11-09T08:00:00Z/PT12H"', datetime(2026, 11, 9, 8, tzinfo=UTC), Duration(hours=12), 5),
]


@pytest.mark.parametrize(("kind", "body", "at", "duration", "repetitions"), ACCEPTED)
def test_accepted_expressions_parse_as_written(kind, body, at, duration, repetitions):
    e = parse_expression(TICK, kind, body)
    assert (e.kind, e.text, e.at, e.duration, e.repetitions) == (kind, body.strip()[1:-1], at, duration, repetitions)


REFUSED = [
    ("timeDuration", "  ", "expression is empty"),
    ("timeDuration", "PT48H", "expression is not one quoted ISO 8601 string literal: 'PT48H'"),
    ("timeDuration", "reminder_delay", "expression is not one quoted ISO 8601 string literal: 'reminder_delay'"),
    ("timeDuration", '"PT1H" + "PT1H"', 'expression is not one quoted ISO 8601 string literal: \'"PT1H" + "PT1H"\''),
    ("timeDuration", '"PT0S"', "duration is zero: 'PT0S'"),
    ("timeDuration", '"-P1D"', "not a positive ISO 8601 duration PnYnMnDTnHnMnS or PnW: '-P1D'"),
    ("timeDuration", '"P1W2D"', "not a positive ISO 8601 duration PnYnMnDTnHnMnS or PnW: 'P1W2D'"),
    ("timeDuration", '"PT"', "not a positive ISO 8601 duration PnYnMnDTnHnMnS or PnW: 'PT'"),
    ("timeDuration", '"PT1.5H"', "not a positive ISO 8601 duration PnYnMnDTnHnMnS or PnW: 'PT1.5H'"),
    (
        "timeDate",
        '"2026-12-01T09:00:00"',
        "date-time has no offset, so it would depend on the host's time zone: '2026-12-01T09:00:00'",
    ),
    ("timeDate", '"tomorrow"', "not an ISO 8601 date-time: 'tomorrow'"),
    ("timeCycle", '"R/P1D"', "cycle has no start date-time: 'R/P1D'"),
    ("timeCycle", '"0 8 * * *"', "cycle is not a repeating interval R[n]/<date-time>/<duration>: '0 8 * * *'"),
    (
        "timeCycle",
        '"R/2026-11-09T08:00:00Z/2026-11-10T08:00:00Z"',
        "cycle is a <start>/<end> interval, not a start and a duration: 'R/2026-11-09T08:00:00Z/2026-11-10T08:00:00Z'",
    ),
    (
        "timeCycle",
        '"R/P1D/2026-11-10T08:00:00Z"',
        "cycle has no start date-time, only <duration>/<end>: 'R/P1D/2026-11-10T08:00:00Z'",
    ),
    ("timeCycle", '"R0/2026-11-09T08:00:00Z/P1D"', "cycle repeats zero times: 'R0/2026-11-09T08:00:00Z/P1D'"),
    (
        "timeCycle",
        '"R/2026-11-09T08:00:00/P1D"',
        "date-time has no offset, so it would depend on the host's time zone: '2026-11-09T08:00:00'",
    ),
]


@pytest.mark.parametrize(("kind", "body", "detail"), REFUSED)
def test_every_other_body_is_refused_naming_the_expression_element(kind, body, detail):
    with pytest.raises(ResolutionError) as err:
        parse_expression(TICK, kind, body)
    assert (err.value.subject, err.value.predicate, err.value.detail) == (TICK, f"bpmn:{kind}", detail)


# ── section 2: the load check ────────────────────────────────────────────────


def test_the_runtime_resolves_every_timer_at_load(tmp_path, clock):
    rt = load(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)
    assert {str(k): (t.is_start, t.expression.kind) for k, t in rt.timers.items()} == {
        REMINDER: (False, "timeDuration"),
        TICK: (True, "timeCycle"),
        SETTLE: (False, "timeDuration"),
    }
    assert rt.scheduler is not None and rt.scheduler.clock is clock and rt.worker.clock is clock


def test_a_model_without_timers_gets_no_scheduler(tmp_path):
    rt = Runtime.load(CHAPTER_09 / "expenses.trig", store=SQLiteStore(tmp_path / "seams.sqlite"))
    assert rt.timers == {} and rt.scheduler is None and rt.start_scheduler() is None


def test_a_bad_reminder_expression_stops_the_runtime_before_any_store_opens(tmp_path):
    trig = model(tmp_path, bpmn_edits=(('"PT48H"', "reminder_delay"),))
    with pytest.raises(ResolutionError) as err:
        Runtime.load(trig, db_path=tmp_path / "never.sqlite")
    assert (err.value.subject, err.value.predicate) == (REMINDER, "bpmn:timeDuration")
    assert err.value.detail == "expression is not one quoted ISO 8601 string literal: 'reminder_delay'"
    assert not (tmp_path / "never.sqlite").exists()


def test_a_cycle_on_an_interrupting_boundary_is_refused(tmp_path):
    cycle = DURATION.replace("timeDuration", "timeCycle").replace('"PT48H"', '"R/2026-11-10T00:00:00Z/P1D"')
    err = refused(model(tmp_path, bpmn_edits=((DURATION, cycle), (' cancelActivity="false"', ""))), tmp_path)
    assert (err.subject, err.predicate) == (REMINDER, "bpmn:timeCycle")
    assert err.detail == (
        "a cycle repeats only on a proc:TimerStartEvent or a non-interrupting boundary, "
        "but this is an interrupting boundary: 'R/2026-11-10T00:00:00Z/P1D'"
    )


def test_a_cycle_on_an_intermediate_catch_is_refused(tmp_path):
    settle = '<bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT1H"</bpmn:timeDuration>'
    err = refused(model(tmp_path, digest_edits=((settle, CYCLE),)), tmp_path)
    assert (err.subject, err.predicate) == (SETTLE, "bpmn:timeCycle")
    assert err.detail.endswith("but this is a intermediateCatchEvent: 'R/2026-11-09T08:00:00Z/P1D'")


def test_a_duration_on_a_timer_start_is_refused(tmp_path):
    duration = '<bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT1H"</bpmn:timeDuration>'
    err = refused(model(tmp_path, digest_edits=((CYCLE, duration),)), tmp_path)
    assert (err.subject, err.predicate) == (TICK, "bpmn:timeDuration")
    assert err.detail == (
        "a timer start event fires at instants the model fixes (a timeDate or a timeCycle); "
        "a duration would count from when a runtime started: 'PT1H'"
    )


def test_a_timer_start_nobody_schedules_is_refused(tmp_path):
    err = refused(model(tmp_path, trig_edits=((SCHEDULES, " ."),)), tmp_path)
    assert (err.subject, err.predicate) == (DIGEST, str(SEAM.schedules))
    assert err.detail == "expected one scheduling container, found []"


class _EntityOnlyStore:
    """A store with no timer table (as a SemPKM-only store would be)."""

    kind = "sempkm"
    location = "https://pkm.example"


def test_a_scheduling_container_without_a_relational_store_is_refused(tmp_path):
    with pytest.raises(ResolutionError) as err:
        Runtime.load(model(tmp_path), store=_EntityOnlyStore())
    assert (err.value.subject, err.value.predicate) == (API, str(SEAM.schedules))
    assert err.value.detail == (
        f"schedules {DIGEST}, but the runtime's store https://pkm.example (sempkm) keeps no timer claims; "
        "a timer firing is claimed in a SQLite or PostgreSQL store"
    )


def test_timer_catches_without_a_relational_store_are_refused(tmp_path, clock):
    rt = load(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)
    catches = {k: t for k, t in rt.timers.items() if not t.is_start}
    with pytest.raises(ResolutionError) as err:
        check_timer_store(rt.model, catches, _EntityOnlyStore())
    assert (err.value.subject, err.value.predicate) == (APPROVAL, str(SEAM.executes))
    assert err.value.detail == (
        f"its timer {REMINDER} waits in the store, but the runtime's store https://pkm.example (sempkm) "
        "keeps no timer claims; use a SQLite or PostgreSQL store"
    )


def test_seams_check_reports_the_same_refusal(tmp_path):
    trig = model(tmp_path, digest_edits=((CYCLE, CYCLE.replace('"R/2026-11-09T08:00:00Z/P1D"', '"R/P1D"')),))
    assert [(f.kind, f.detail) for f in check_timers(trig)] == [
        ("timer", f"{TICK} bpmn:timeCycle cycle has no start date-time: 'R/P1D'"),
    ]


def test_seams_check_finds_nothing_in_a_sound_model(tmp_path):
    assert check_timers(model(tmp_path)) == []
    assert check_timers(CHAPTER_09 / "expenses.trig") == []


# ── section 4: due times ─────────────────────────────────────────────────────


def _timer(kind: str, body: str, *, start: bool = True) -> Timer:
    return Timer(TICK, DIGEST, "tick", start, True, parse_expression(TICK, kind, body))


def test_due_times_are_utc_rounded_up_to_the_second():
    assert format_due(datetime(2026, 11, 9, 9, 0, 0, 1, tzinfo=UTC)) == "2026-11-09T09:00:01Z"
    assert format_due(datetime.fromisoformat("2026-11-09T10:00:00+01:00")) == "2026-11-09T09:00:00Z"
    assert format_due_floor(datetime(2026, 11, 9, 9, 0, 0, 999, tzinfo=UTC)) == "2026-11-09T09:00:00Z"


def test_calendar_months_keep_the_day_clamped_to_the_month():
    jan31 = datetime(2026, 1, 31, 9, tzinfo=UTC)
    assert Duration(months=1).after(jan31) == datetime(2026, 2, 28, 9, tzinfo=UTC)
    assert Duration(months=1).times(2).after(jan31) == datetime(2026, 3, 31, 9, tzinfo=UTC)
    assert Duration(years=1, days=1).after(jan31) == datetime(2027, 2, 1, 9, tzinfo=UTC)


def test_a_cycle_fires_its_latest_due_time_and_counts_the_missed_ones():
    daily = _timer("timeCycle", '"R/2026-11-09T08:00:00Z/P1D"')
    at = datetime(2026, 11, 9, 8, tzinfo=UTC)
    assert daily.start_firing(None, at - timedelta(seconds=1)) is None
    assert daily.start_firing(None, at) == (at, 0)
    assert daily.start_firing(at, at + timedelta(hours=23)) is None
    assert daily.start_firing(at, at + timedelta(days=3, hours=1)) == (at + timedelta(days=3), 2)
    assert daily.start_firing(None, at + timedelta(days=3, hours=1)) == (at + timedelta(days=3), 3)


def test_a_bounded_cycle_stops_after_its_repetitions():
    twice = _timer("timeCycle", '"R2/2026-11-09T08:00:00Z/P1D"')
    second = datetime(2026, 11, 10, 8, tzinfo=UTC)
    assert twice.start_firing(None, datetime(2026, 12, 1, tzinfo=UTC)) == (second, 1)
    assert twice.start_firing(second, datetime(2026, 12, 1, tzinfo=UTC)) is None


def test_a_monthly_cycle_steps_by_calendar_month():
    monthly = _timer("timeCycle", '"R/2026-01-31T08:00:00Z/P1M"')
    assert monthly.start_firing(None, datetime(2026, 3, 30, tzinfo=UTC)) == (datetime(2026, 2, 28, 8, tzinfo=UTC), 1)


def test_a_past_time_date_fires_once():
    once = _timer("timeDate", '"2026-11-01T00:00:00Z"')
    at = datetime(2026, 11, 1, tzinfo=UTC)
    assert once.start_firing(None, datetime(2026, 11, 9, tzinfo=UTC)) == (at, 0)
    assert once.start_firing(at, datetime(2026, 11, 10, tzinfo=UTC)) is None


def test_a_catch_is_due_from_when_the_instance_reached_it():
    reached = datetime(2026, 11, 9, 7, 30, tzinfo=UTC)
    assert _timer("timeDuration", '"PT48H"', start=False).catch_due(reached) == reached + timedelta(hours=48)
    assert _timer("timeDate", '"2026-12-01T00:00:00Z"', start=False).catch_due(reached) == datetime(
        2026, 12, 1, tzinfo=UTC
    )
    cycle = _timer("timeCycle", '"R2/2026-11-09T08:00:00Z/P1D"', start=False)
    assert cycle.catch_due(reached) == datetime(2026, 11, 9, 8, tzinfo=UTC)
    assert cycle.catch_due(datetime(2026, 11, 20, tzinfo=UTC)) is None


# ── the clock ────────────────────────────────────────────────────────────────


def test_the_default_clock_is_the_system_clock(monkeypatch):
    before = datetime.now(UTC)
    now = clock_from_env({}).now()
    assert before <= now <= datetime.now(UTC)


def test_the_clock_offset_runs_the_clock_ahead():
    clock = clock_from_env({CLOCK_OFFSET_ENV: "PT49H"})
    assert clock.offset == Duration(hours=49)
    ahead = clock.now() - datetime.now(UTC)
    assert timedelta(hours=48, minutes=59) < ahead <= timedelta(hours=49)


@pytest.mark.parametrize("value", ["49h", "-PT49H", "PT0.5H"])
def test_a_bad_clock_offset_names_the_variable(value):
    with pytest.raises(ValueError, match=CLOCK_OFFSET_ENV):
        clock_from_env({CLOCK_OFFSET_ENV: value})


def test_runtime_load_reads_the_clock_offset(tmp_path, monkeypatch):
    monkeypatch.setenv(CLOCK_OFFSET_ENV, "P3D")
    rt = Runtime.load(model(tmp_path), store=SQLiteStore(tmp_path / "seams.sqlite"))
    assert rt.clock.offset == Duration(days=3)


# ── the reminder: a non-interrupting boundary keeps the task open ───────────


def test_reaching_the_reminder_writes_its_due_time_with_the_checkpoint(tmp_path, clock):
    rt = reminders(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        result = await submit(rt)
        [row] = rows(rt, "catch")
        assert (row["event"], row["due"], row["instance_id"]) == (REMINDER, "2026-11-11T07:00:00Z", result["instance"])
        assert row["holder"] is None
        state = rt.engine.deserialize(rt.store.load_state(result["instance"])).data["seams"]
        assert state["timers"] == {row["task_id"]: {"event": REMINDER, "due": "2026-11-11T07:00:00Z"}}
        clock.step(hours=47, minutes=59)
        assert await rt.scheduler.tick() == []

    asyncio.run(main())


def test_the_reminder_fires_and_the_approval_stays_open(tmp_path, clock, caplog):
    rt = reminders(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        await submit(rt)
        clock.step(hours=49)
        with caplog.at_level(logging.INFO, logger="seams_runtime.timers"):
            [woken] = await drain(await rt.scheduler.tick())
        assert woken["status"] == "waiting"
        assert tasks(woken)[-2:] == ["overdue_reminder", "reminder_end"]
        assert woken["trace"][-2]["timer"] == "2026-11-11T07:00:00Z"
        assert [t["bpmn_id"] for t in rt.store.list_user_tasks()] == ["approve_expense"]
        assert rows(rt, "catch") == []
        assert f"timer fire {REMINDER} due 2026-11-11T07:00:00Z instance {woken['instance']}" in caplog.text
        clock.step(hours=49)
        assert await rt.scheduler.tick() == []  # a duration fires once
        done = await (await rt.complete_task(APPROVE, {"decision": "approved"}, "e1", MANAGER)).wait()
        assert done["status"] in ("waiting", "complete") and "overdue_reminder" in tasks(done)

    asyncio.run(main())


def test_approving_in_time_drops_the_reminder(tmp_path, clock):
    rt = reminders(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        await submit(rt)
        await (await rt.complete_task(APPROVE, {"decision": "approved"}, "e1", MANAGER)).wait()
        assert rows(rt, "catch") == []
        clock.step(hours=49)
        assert await rt.scheduler.tick() == []

    asyncio.run(main())


def test_an_interrupting_reminder_closes_the_task(tmp_path, clock):
    rt = reminders(
        model(tmp_path, bpmn_edits=((' cancelActivity="false"', ""),)), SQLiteStore(tmp_path / "s.sqlite"), clock
    )

    async def main():
        await submit(rt)
        clock.step(hours=49)
        [woken] = await drain(await rt.scheduler.tick())
        assert woken["status"] == "complete" and tasks(woken)[-2:] == ["overdue_reminder", "reminder_end"]
        assert rt.store.list_user_tasks() == []

    asyncio.run(main())


def test_a_cycle_reminder_repeats_until_spent_and_the_task_stays_open(tmp_path, clock, caplog):
    cycle = DURATION.replace("timeDuration", "timeCycle").replace('"PT48H"', '"R3/2026-11-10T00:00:00Z/P1D"')
    rt = reminders(model(tmp_path, bpmn_edits=((DURATION, cycle),)), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        await submit(rt)
        assert [r["due"] for r in rows(rt, "catch")] == ["2026-11-10T00:00:00Z"]
        clock.step(hours=17)
        await drain(await rt.scheduler.tick())
        assert [r["due"] for r in rows(rt, "catch")] == ["2026-11-11T00:00:00Z"]
        clock.step(days=2, hours=2)  # 2026-11-12T02:00: the second firing was missed
        with caplog.at_level(logging.INFO, logger="seams_runtime.worker"):
            [woken] = await drain(await rt.scheduler.tick())
        assert f"timer missed {REMINDER} 1 firing(s)" in caplog.text
        assert [r["timer"] for r in woken["trace"] if r["task"] == "overdue_reminder"] == [
            "2026-11-10T00:00:00Z",
            "2026-11-12T00:00:00Z",
        ]
        assert [r["due"] for r in rows(rt, "catch")] == []  # R3: the 10th, the 12th (the 11th skipped), spent
        assert [t["bpmn_id"] for t in rt.store.list_user_tasks()] == ["approve_expense"]
        clock.step(days=5)
        assert await rt.scheduler.tick() == []

    asyncio.run(main())


# ── the digest: a timer start and a timer catch ──────────────────────────────


def test_a_timer_start_fires_with_the_due_time_as_its_correlation_key(tmp_path, clock, caplog):
    rt = load(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        assert await rt.scheduler.tick() == []
        clock.step(hours=1)  # 2026-11-09T08:00:00Z
        with caplog.at_level(logging.INFO, logger="seams_runtime.timers"):
            [started] = await drain(await rt.scheduler.tick())
        assert (started["correlation_key"], started["status"]) == ("2026-11-09T08:00:00Z", "waiting")
        assert started["trace"][0] == {"task": "tick", "iri": TICK, "timer": "2026-11-09T08:00:00Z"}
        assert f"timer fire {TICK} due 2026-11-09T08:00:00Z instance {started['instance']}" in caplog.text
        assert "timer missed" not in caplog.text
        [firing] = rows(rt, "start")
        assert (firing["event"], firing["due"], firing["instance_id"]) == (
            TICK,
            "2026-11-09T08:00:00Z",
            started["instance"],
        )
        [settle] = rows(rt, "catch")
        assert (settle["event"], settle["due"]) == (SETTLE, "2026-11-09T09:00:00Z")
        clock.step(hours=1)
        [settled] = await drain(await rt.scheduler.tick())
        assert settled["status"] == "complete" and tasks(settled) == ["tick", "settle"]
        assert rows(rt, "catch") == []

    asyncio.run(main())


def test_missed_cycle_firings_fire_only_the_latest(tmp_path, clock, caplog):
    rt = load(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock)

    async def main():
        await drain(await rt.scheduler.tick())
        clock.step(days=3, hours=2)  # 2026-11-12T09:00: four due times passed
        with caplog.at_level(logging.INFO, logger="seams_runtime.timers"):
            [started] = await drain(await rt.scheduler.tick())
        assert started["correlation_key"] == "2026-11-12T08:00:00Z"
        assert f"timer missed {TICK} 3 firing(s)" in caplog.text
        assert await rt.scheduler.tick() == []  # the settle catch is due at 10:00; no new start
        assert [r["due"] for r in rows(rt, "start")] == ["2026-11-12T08:00:00Z"]
        clock.step(days=1)
        caplog.clear()
        fired = await drain(await rt.scheduler.tick())
        assert "2026-11-13T08:00:00Z" in [r["correlation_key"] for r in fired]
        assert "timer missed" not in caplog.text
        assert [r["due"] for r in rows(rt, "start")] == ["2026-11-13T08:00:00Z"]  # only the latest firing is kept
        assert len(processes(rt, DIGEST)) == 2

    asyncio.run(main())


# ── section 4: claims under two runtimes sharing one store ──────────────────


def test_two_runtimes_on_one_store_fire_each_start_once(make_store, tmp_path, clock, caplog):
    trig = model(tmp_path)
    a, b = load(trig, make_store("shared"), clock), load(trig, make_store("shared"), clock)

    async def main():
        clock.step(hours=1)
        first = await a.scheduler.tick()
        assert await b.scheduler.tick() == []  # b reads a's firing and owes none
        # b read the last firing before a committed: its insert conflicts and nothing runs
        stale = b.store.last_firing
        b.store.last_firing = lambda event: None
        with caplog.at_level(logging.DEBUG, logger="seams_runtime.timers"):
            assert await b.scheduler.tick() == []
        b.store.last_firing = stale
        assert f"timer claimed elsewhere {TICK} due 2026-11-09T08:00:00Z" in caplog.text
        await drain(first)
        assert len(first) == 1 and len(processes(a, DIGEST)) == 1 and len(rows(a, "start")) == 1

    asyncio.run(main())


def test_a_waiting_instance_is_woken_once_by_either_runtime(make_store, tmp_path, clock):
    trig = model(tmp_path)
    a, b = reminders(trig, make_store("shared"), clock), reminders(trig, make_store("shared"), clock)

    async def main():
        await submit(a)
        clock.step(hours=49)
        woken = await b.scheduler.tick() + await a.scheduler.tick()
        [result] = await drain(woken)
        assert tasks(result).count("overdue_reminder") == 1
        assert result["instance"] in b.instances  # b loaded the checkpoint a wrote and woke it

    asyncio.run(main())


def test_an_expired_lease_passes_the_timer_on_and_the_lapsed_runtime_rolls_back(make_store, tmp_path, clock, caplog):
    trig = model(tmp_path)
    a, b = reminders(trig, make_store("shared"), clock), reminders(trig, make_store("shared"), clock)

    async def main():
        await submit(a)
        clock.step(hours=49)
        now = clock.now()
        [row] = a.store.due_timers(format_due_floor(now), now.timestamp())
        assert a.scheduler.claim(row, now)
        with caplog.at_level(logging.DEBUG, logger="seams_runtime.timers"):
            assert not b.scheduler.claim(row, now)  # a's lease holds
            assert b.store.due_timers(format_due_floor(now), now.timestamp()) == []
            clock.step(seconds=a.scheduler.lease + 1)
            later = clock.now()
            assert b.scheduler.claim(row, later)  # a's lease expired
            assert await a.scheduler.wake(row) is None  # a rolls back: it runs nothing
        assert f"timer claimed elsewhere {REMINDER} due 2026-11-11T07:00:00Z (lease lapsed)" in caplog.text
        [result] = await drain([await b.scheduler.wake(row)])
        assert tasks(result).count("overdue_reminder") == 1
        assert rows(b, "catch") == []
        state = b.engine.deserialize(b.store.load_state(result["instance"])).data["seams"]
        assert [r["task"] for r in state["trace"]].count("overdue_reminder") == 1

    asyncio.run(main())


# ── the store's timer table, on both backends ───────────────────────────────


def test_a_firing_row_is_claimed_once_and_only_the_latest_is_kept(make_store):
    s = make_store()
    assert s.claim_firing(TICK, "2026-11-09T08:00:00Z", "i1")
    assert not s.claim_firing(TICK, "2026-11-09T08:00:00Z", "i2")
    assert s.last_firing(TICK) == "2026-11-09T08:00:00Z"
    assert s.claim_firing(TICK, "2026-11-10T08:00:00Z", "i3")
    assert [(r["due"], r["instance_id"]) for r in s.list_timers()] == [("2026-11-10T08:00:00Z", "i3")]
    assert s.last_firing("https://example.org/other#tick") is None


def test_a_firing_claim_rolls_back_with_its_transaction(make_store):
    s = make_store()
    with pytest.raises(RuntimeError), s.transaction():
        assert s.claim_firing(TICK, "2026-11-09T08:00:00Z", "i1")
        raise RuntimeError("the start failed")
    assert s.list_timers() == []
    assert s.claim_firing(TICK, "2026-11-09T08:00:00Z", "i1")


def test_catch_rows_are_leased_released_and_replaced(make_store):
    s = make_store()
    s.replace_timers("i1", [{"event": REMINDER, "due": "2026-11-11T07:00:00Z", "task_id": "t1"}])
    [row] = s.due_timers("2026-11-11T07:00:00Z", 100.0)
    assert (row["kind"], row["instance_id"], row["holder"]) == ("catch", "i1", None)
    assert s.due_timers("2026-11-11T06:59:59Z", 100.0) == []
    assert s.lease_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "a", 160.0, 100.0)
    assert not s.lease_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "b", 170.0, 110.0)
    assert s.due_timers("2026-11-11T07:00:00Z", 110.0) == []
    s.replace_timers("i1", [{"event": REMINDER, "due": "2026-11-11T07:00:00Z", "task_id": "t1"}])
    assert s.list_timers()[0]["holder"] == "a"  # a row that stays keeps its lease
    assert not s.release_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "b", 110.0)
    assert not s.release_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "a", 161.0)  # lapsed
    assert s.lease_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "b", 230.0, 170.0)
    assert s.release_timer(REMINDER, "2026-11-11T07:00:00Z", "t1", "b", 200.0)
    assert s.list_timers() == []
    s.replace_timers("i1", [{"event": SETTLE, "due": "2026-11-09T09:00:00Z", "task_id": "t2"}])
    s.replace_timers("i1", [])
    assert s.list_timers() == []


# ── section 5: spans ─────────────────────────────────────────────────────────


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield Telemetry(provider.get_tracer("test")), exporter
    provider.shutdown()


def test_claim_and_fire_spans_carry_the_event_due_and_instance(tmp_path, clock, spans):
    telemetry, exporter = spans
    rt = load(model(tmp_path), SQLiteStore(tmp_path / "seams.sqlite"), clock, telemetry=telemetry)

    async def main():
        clock.step(hours=1)
        [started] = await drain(await rt.scheduler.tick())
        return started

    started = asyncio.run(main())
    by_name = {s.name: dict(s.attributes or {}) for s in exporter.get_finished_spans()}
    expected = {
        "seams.timer.event": TICK,
        "seams.timer.due": "2026-11-09T08:00:00Z",
        "seams.instance.id": started["instance"],
    }
    assert by_name["seams.timer.claim"] == expected
    assert by_name["seams.timer.fire"] == expected
    assert by_name["tick"]["seams.timer.due"] == "2026-11-09T08:00:00Z"
