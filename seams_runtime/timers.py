"""Timers (ADR-0037): expression checks, due times, the clock and the scheduler.

Spiff parses BPMN timer events but fires one only when something refreshes
it after its due time, reading the host's clock. This module decides when
each timer is due and claims every firing in the shared store, so a firing
runs once however many runtimes share that store.

**Expressions (section 2).** ``check_timer`` reads one lifted timer
(``seams.TimerEvent``, from ``Process.timer_events()``) and parses its body,
which must be one quoted ISO 8601 string literal:

- ``bpmn:timeDate``: a date-time with ``Z`` or an offset;
- ``bpmn:timeDuration``: a positive ``PnYnMnDTnHnMnS`` or ``PnW`` of whole numbers;
- ``bpmn:timeCycle``: ``R[n]/<date-time>/<duration>``, only on a
  proc:TimerStartEvent or a non-interrupting boundary.

Anything else raises ``ResolutionError(<event>, bpmn:timeDate | bpmn:timeDuration
| bpmn:timeCycle, <detail>)``, for example ``cycle has no start date-time:
'R/P1D'``. A ``bpmn:timeDuration`` on a timer start is refused too: its firing
would count from when a runtime started. ``resolve_timers`` checks every
timer of every process; ``Runtime.load`` calls it before any store is opened,
and ``seams check`` reports the same refusals as ``timer`` findings.

**Due times (section 4)** are UTC, rounded up to the second and written
``YYYY-MM-DDTHH:MM:SSZ`` (``format_due``), so they sort as text. A timer start
fires at its date-time, or at its cycle's start plus whole multiples of the
duration (``Timer.start_firing``). A timer catch's due time is fixed once,
when the instance reaches it (``Timer.catch_due``): the worker writes it into
the Spiff task and into the store's timer rows with the checkpoint.

**The clock** is injected. ``SystemClock`` is the system's UTC time plus an
optional offset; ``clock_from_env`` reads the offset, an ISO 8601 duration,
from ``SEAMS_CLOCK_OFFSET`` (decision D065: a development setting the
generated compose never writes).

**The scheduler** (``Scheduler``) runs ``tick`` every ``interval`` seconds:

- for each timer start whose latest due firing is newer than the store's last
  one, it inserts the firing row ``(event, due)`` and starts and checkpoints
  the instance, correlation key the due time, in one ``store.transaction()``.
  A conflicting insert means another runtime has the firing: nothing runs.
  Missed cycle firings fire only the latest;
- for each due catch row it takes a lease, loads the waiting instance, marks
  the Spiff timer task fired and refreshes it, then deletes the row and writes
  the checkpoint in one transaction, only while it still holds the lease. A
  runtime whose lease lapsed rolls back and runs nothing.

It logs ``timer fire <event> due <due> instance <id>``, ``timer claimed
elsewhere <event> due <due>`` (debug) and ``timer missed <event> N
firing(s)``, and emits the spans ``seams.timer.claim`` and
``seams.timer.fire`` (``Telemetry.timer_span``).
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import os
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .errors import ResolutionError

log = logging.getLogger(__name__)

CLOCK_OFFSET_ENV = "SEAMS_CLOCK_OFFSET"
DEFAULT_INTERVAL = 1.0  # seconds between scheduler ticks
DEFAULT_LEASE = 60.0  # seconds a runtime holds a due catch row while it wakes the instance

_DATE_TIME = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
_OFFSET = r"(?:Z|[+-]\d{2}:\d{2})"
_DURATION = re.compile(r"P(?:(\d+)W|(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)")
_QUOTED = re.compile(r'"([^"\\]*)"|\'([^\'\\]*)\'')
_REPEAT = re.compile(r"R(\d*)")


# ── durations ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Duration:
    """An ISO 8601 duration of whole numbers. Years and months are calendar
    steps (``after`` keeps the day of the month, clamped to the month's last)."""

    years: int = 0
    months: int = 0
    weeks: int = 0
    days: int = 0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0

    @property
    def calendar_months(self) -> int:
        return self.years * 12 + self.months

    @property
    def fixed(self) -> timedelta:
        """The part that is a fixed length of time (everything but years and months)."""
        return timedelta(weeks=self.weeks, days=self.days, hours=self.hours, minutes=self.minutes, seconds=self.seconds)

    def times(self, k: int) -> Duration:
        return Duration(*(k * v for v in self._values()))

    def after(self, start: datetime) -> datetime:
        """``start`` plus this duration."""
        moved = start
        if self.calendar_months:
            y, m = divmod(start.month - 1 + self.calendar_months, 12)
            year, month = start.year + y, m + 1
            moved = start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))
        return moved + self.fixed

    @property
    def is_zero(self) -> bool:
        return not any(self._values())

    def _values(self) -> tuple[int, ...]:
        return (self.years, self.months, self.weeks, self.days, self.hours, self.minutes, self.seconds)


def parse_duration(text: str) -> Duration | None:
    """The duration ``text`` writes, or None when it is not ``PnYnMnDTnHnMnS``
    or ``PnW`` (a ``T`` with no time part, or no part at all, is not one)."""
    m = _DURATION.fullmatch(text)
    if m is None:
        return None
    weeks, years, months, days, hours, minutes, seconds = m.groups()
    if all(g is None for g in m.groups()):
        return None
    if "T" in text and hours is None and minutes is None and seconds is None:
        return None
    return Duration(*(int(v) if v is not None else 0 for v in (years, months, weeks, days, hours, minutes, seconds)))


def parse_offset(text: str) -> Duration:
    """``SEAMS_CLOCK_OFFSET``'s ISO 8601 duration; ValueError naming the variable otherwise."""
    duration = parse_duration(text.strip())
    if duration is None:
        raise ValueError(f"{CLOCK_OFFSET_ENV}={text!r} is not an ISO 8601 duration such as 'PT49H'")
    return duration


# ── expressions ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Expression:
    """A parsed timer expression. ``kind`` is ``timeDate``, ``timeDuration`` or
    ``timeCycle`` and ``text`` the literal without its quotes. ``at`` is the
    date-time (a cycle's start), ``duration`` the duration (a cycle's
    interval) and ``repetitions`` a cycle's ``n`` (None when unbounded)."""

    kind: str
    text: str
    at: datetime | None = None
    duration: Duration | None = None
    repetitions: int | None = None


def _date_time(text: str) -> datetime | None:
    """The UTC instant of a date-time with an offset, else None."""
    if re.fullmatch(_DATE_TIME + _OFFSET, text) is None:
        return None
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        return None


def _naive(text: str) -> bool:
    return re.fullmatch(_DATE_TIME, text) is not None


def parse_expression(event: object, kind: str, body: str) -> Expression:
    """Parse the body of the ``kind`` element (``timeDate``, ``timeDuration``
    or ``timeCycle``) of timer ``event``; ResolutionError(event, bpmn:<kind>) otherwise."""
    predicate = f"bpmn:{kind}"

    def refuse(detail: str) -> ResolutionError:
        return ResolutionError(event, predicate, detail)

    stripped = body.strip()
    if not stripped:
        raise refuse("expression is empty")
    quoted = _QUOTED.fullmatch(stripped)
    if quoted is None:
        raise refuse(f"expression is not one quoted ISO 8601 string literal: {stripped!r}")
    text = quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    if kind == "timeDate":
        return Expression(kind, text, at=_parse_at(text, refuse))
    if kind == "timeDuration":
        return Expression(kind, text, duration=_parse_interval(text, refuse))
    if kind != "timeCycle":
        raise refuse(f"not a timer expression element: {kind!r}")
    parts = text.split("/")
    repeat = _REPEAT.fullmatch(parts[0])
    if repeat is None or len(parts) not in (2, 3):
        raise refuse(f"cycle is not a repeating interval R[n]/<date-time>/<duration>: {text!r}")
    if len(parts) == 2:
        if parse_duration(parts[1]) is not None:
            raise refuse(f"cycle has no start date-time: {text!r}")
        raise refuse(f"cycle is not a repeating interval R[n]/<date-time>/<duration>: {text!r}")
    start, interval = parts[1], parts[2]
    if parse_duration(start) is not None:
        raise refuse(f"cycle has no start date-time, only <duration>/<end>: {text!r}")
    if _date_time(interval) is not None or _naive(interval):
        raise refuse(f"cycle is a <start>/<end> interval, not a start and a duration: {text!r}")
    repetitions = int(repeat.group(1)) if repeat.group(1) else None
    if repetitions == 0:
        raise refuse(f"cycle repeats zero times: {text!r}")
    return Expression(
        kind, text, at=_parse_at(start, refuse), duration=_parse_interval(interval, refuse), repetitions=repetitions
    )


def _parse_at(text: str, refuse) -> datetime:
    at = _date_time(text)
    if at is not None:
        return at
    if _naive(text):
        raise refuse(f"date-time has no offset, so it would depend on the host's time zone: {text!r}")
    raise refuse(f"not an ISO 8601 date-time: {text!r}")


def _parse_interval(text: str, refuse) -> Duration:
    duration = parse_duration(text)
    if duration is None:
        raise refuse(f"not a positive ISO 8601 duration PnYnMnDTnHnMnS or PnW: {text!r}")
    if duration.is_zero:
        raise refuse(f"duration is zero: {text!r}")
    return duration


# ── timers and due times ─────────────────────────────────────────────────────


def format_due(at: datetime) -> str:
    """``at`` in UTC, rounded up to the second, as ``YYYY-MM-DDTHH:MM:SSZ``."""
    at = at.astimezone(UTC)
    if at.microsecond:
        at = at.replace(microsecond=0) + timedelta(seconds=1)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_due(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass(frozen=True)
class Timer:
    """A checked timer event: ``event`` its IRI, ``process`` its process,
    ``bpmn_id`` its id in the BPMN, ``is_start`` for a proc:TimerStartEvent and
    ``interrupting`` its ``cancelActivity``."""

    event: object
    process: object
    bpmn_id: str
    is_start: bool
    interrupting: bool
    expression: Expression

    @property
    def is_cycle(self) -> bool:
        return self.expression.kind == "timeCycle"

    def occurrence(self, k: int) -> datetime:
        """A cycle's ``k``-th due time (0 is its start)."""
        e = self.expression
        assert e.at is not None and e.duration is not None
        return e.duration.times(k).after(e.at)

    def latest_index(self, at: datetime) -> int | None:
        """The index of a cycle's last due time at or before ``at``, else None."""
        e = self.expression
        assert e.at is not None and e.duration is not None
        if at < e.at:
            return None
        if e.duration.calendar_months:
            k = ((at.year - e.at.year) * 12 + at.month - e.at.month) // e.duration.calendar_months
            k = max(k, 0)
        else:
            k = int((at - e.at) // e.duration.fixed)
        while k > 0 and self.occurrence(k) > at:
            k -= 1
        while self.occurrence(k + 1) <= at:
            k += 1
        if e.repetitions is not None:
            k = min(k, e.repetitions - 1)
        return k

    def start_firing(self, last: datetime | None, now: datetime) -> tuple[datetime, int] | None:
        """The firing a timer start owes at ``now`` and how many earlier due
        times it skips, given the ``last`` due time the store recorded; None
        when it owes none. A timeDate fires once, even if it was already past
        when the runtime first loaded it."""
        e = self.expression
        if e.kind == "timeDate":
            assert e.at is not None
            if e.at <= now and (last is None or last < e.at):
                return e.at, 0
            return None
        k = self.latest_index(now)
        if k is None:
            return None
        done = None if last is None else self.latest_index(last)
        if done is not None and done >= k:
            return None
        return self.occurrence(k), k - (0 if done is None else done + 1)

    def catch_due(self, reached: datetime) -> datetime | None:
        """A catch's due time when the instance reaches it at ``reached``: the
        date-time, ``reached`` plus the duration, or the cycle's next due time
        at or after ``reached`` (None once the cycle is spent)."""
        e = self.expression
        if e.kind == "timeDate":
            return e.at
        assert e.duration is not None
        if e.kind == "timeDuration":
            return e.duration.after(reached)
        k = self.latest_index(reached)
        k = 0 if k is None else (k if self.occurrence(k) == reached else k + 1)
        if e.repetitions is not None and k >= e.repetitions:
            return None
        return self.occurrence(k)

    def cycle_after(self, due: datetime, now: datetime) -> tuple[datetime, int, datetime | None]:
        """For a cycle catch whose row is due at ``due``, fired at ``now``: the
        latest due time it fires (the one at or before ``now``), how many
        earlier ones it skips, and its next due time (None once spent)."""
        k = self.latest_index(now)
        first = self.latest_index(due)
        assert k is not None and first is not None
        nxt = k + 1
        e = self.expression
        following = None if e.repetitions is not None and nxt >= e.repetitions else self.occurrence(nxt)
        return self.occurrence(k), k - first, following


def check_timer(timer) -> Timer:
    """The ``Timer`` of a ``seams.TimerEvent``; ResolutionError(event,
    bpmn:<expression>) for a body section 2 refuses or a misplaced one."""
    expression = parse_expression(timer.iri, timer.expression, timer.body)
    if timer.is_start and expression.kind == "timeDuration":
        raise ResolutionError(
            timer.iri,
            timer.expression_predicate,
            "a timer start event fires at instants the model fixes (a timeDate or a timeCycle); "
            f"a duration would count from when a runtime started: {expression.text!r}",
        )
    if expression.kind == "timeCycle" and not timer.is_start and timer.interrupting:
        where = "an interrupting boundary" if timer.attached_to is not None else f"a {timer.node.node.tag}"
        raise ResolutionError(
            timer.iri,
            timer.expression_predicate,
            "a cycle repeats only on a proc:TimerStartEvent or a non-interrupting boundary, "
            f"but this is {where}: {expression.text!r}",
        )
    return Timer(timer.iri, timer.node.process.iri, timer.node.bpmn_id, timer.is_start, timer.interrupting, expression)


def resolve_timers(model) -> dict:
    """``{event IRI: Timer}`` for every lifted timer of every process, checked
    against the BPMN XML (``Process.timer_events()``) and section 2. A timer
    start's process must have one scheduling container
    (``ModelGraph.scheduling_container``). Any fault raises ``ResolutionError``."""
    resolved: dict = {}
    for process in sorted(model.processes, key=lambda p: str(p.iri)):
        for event in process.timer_events():
            timer = check_timer(event)
            if timer.is_start:
                model.scheduling_container(process.iri)
            resolved[event.iri] = timer
            log.info(
                "timer %s (%s) %s %r",
                event.iri,
                "start" if timer.is_start else "catch",
                timer.expression.kind,
                timer.expression.text,
            )
    return resolved


def timer_findings(model) -> list[ResolutionError]:
    """The refusal ``resolve_timers`` would raise for each process, one per
    process at most, for ``seams check``."""
    found: list[ResolutionError] = []
    for process in sorted(model.processes, key=lambda p: str(p.iri)):
        try:
            for event in process.timer_events():
                check_timer(event)
                if event.is_start:
                    model.scheduling_container(process.iri)
        except ResolutionError as err:
            found.append(err)
    return found


# ── the clock ────────────────────────────────────────────────────────────────


class Clock(Protocol):
    def now(self) -> datetime:
        """The current instant, timezone-aware."""
        ...


class SystemClock:
    """The system's UTC time plus ``offset`` (None: none)."""

    def __init__(self, offset: Duration | None = None):
        self.offset = offset

    def now(self) -> datetime:
        now = datetime.now(UTC)
        return now if self.offset is None else self.offset.after(now)

    def __repr__(self) -> str:
        return f"SystemClock(offset={self.offset!r})"


def clock_from_env(environ=None) -> SystemClock:
    """The system clock, offset by ``SEAMS_CLOCK_OFFSET`` when it is set."""
    env = os.environ if environ is None else environ
    text = env.get(CLOCK_OFFSET_ENV)
    if not text:
        return SystemClock()
    offset = parse_offset(text)
    log.warning("%s=%s: the runtime's clock runs ahead of the system clock (development only)", CLOCK_OFFSET_ENV, text)
    return SystemClock(offset)


# ── the scheduler ────────────────────────────────────────────────────────────


class LeaseLost(Exception):
    """The runtime's lease on a due catch row lapsed before it could commit."""


class Scheduler:
    """The scheduler loop of one ``Runtime`` (module docstring). ``holder``
    names this runtime in the leases it takes."""

    def __init__(self, runtime, timers: dict, clock: Clock, *, interval=DEFAULT_INTERVAL, lease=DEFAULT_LEASE):
        self.runtime = runtime
        self.timers = timers
        self.starts = sorted((t for t in timers.values() if t.is_start), key=lambda t: str(t.event))
        self.clock = clock
        self.interval = interval
        self.lease = lease
        self.holder = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.task: asyncio.Task | None = None

    def __repr__(self) -> str:
        return f"Scheduler({len(self.starts)} start(s), {len(self.timers) - len(self.starts)} catch(es), {self.holder})"

    @property
    def store(self):
        return self.runtime.store

    @property
    def telemetry(self):
        return self.runtime.telemetry

    # ── the loop ──

    def start(self) -> asyncio.Task:
        """Run ``tick`` every ``interval`` seconds on the running loop (once)."""
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self._loop(), name="seams-scheduler")
            log.info("scheduler %s started, every %ss", self.holder, self.interval)
        return self.task

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - a store outage must not stop the loop; the next tick retries
                log.exception("scheduler %s: tick failed", self.holder)
            await asyncio.sleep(self.interval)

    async def tick(self) -> list:
        """One pass: every timer start firing owed now, then every due catch.
        Returns the instances this runtime started or woke."""
        now = self.clock.now()
        fired = []
        for timer in self.starts:
            instance = self.fire_start(timer, now)
            if instance is not None:
                fired.append(instance)
        for row in self.store.due_timers(format_due_floor(now), now.timestamp()):
            if self.claim(row, now):
                instance = await self.wake(row)
                if instance is not None:
                    fired.append(instance)
        return fired

    # ── timer starts ──

    def fire_start(self, timer: Timer, now: datetime):
        """Start the firing ``timer`` owes at ``now``, if this runtime claims it."""
        last = self.store.last_firing(str(timer.event))
        owed = timer.start_firing(None if last is None else parse_due(last), now)
        if owed is None:
            return None
        at, skipped = owed
        due = format_due(at)
        runtime = self.runtime
        instance = None
        with self.telemetry.timer_span("seams.timer.claim", timer.event, due) as span:
            with self.store.transaction():
                instance_id = str(uuid.uuid4())
                if self.store.claim_firing(str(timer.event), due, instance_id):
                    instance = runtime.new_timer_instance(timer, due, instance_id)
                    span.instance(instance.id)
        if instance is None:
            log.debug("timer claimed elsewhere %s due %s", timer.event, due)
            return None
        if skipped:
            log.info("timer missed %s %d firing(s)", timer.event, skipped)
        with self.telemetry.timer_span("seams.timer.fire", timer.event, due) as span:
            span.instance(instance.id)
            log.info("timer fire %s due %s instance %s", timer.event, due, instance.id)
            return runtime._launch(instance)

    # ── timer catches ──

    def claim(self, row: dict, now: datetime) -> bool:
        """Take the lease on a due catch row; False when another runtime holds it."""
        with self.telemetry.timer_span("seams.timer.claim", row["event"], row["due"]) as span:
            span.instance(row["instance_id"])
            with self.store.transaction():
                taken = self.store.lease_timer(
                    row["event"], row["due"], row["task_id"], self.holder, now.timestamp() + self.lease, now.timestamp()
                )
        if not taken:
            log.debug("timer claimed elsewhere %s due %s", row["event"], row["due"])
        return taken

    async def wake(self, row: dict):
        """Fire a due catch row this runtime leased: refresh the Spiff timer
        task and checkpoint in the transaction that deletes the row while the
        lease still holds, then run the instance. None when the lease lapsed
        or the instance no longer waits on the timer."""
        runtime = self.runtime
        event, due = row["event"], row["due"]
        with self.telemetry.timer_span("seams.timer.fire", event, due) as span:
            span.instance(row["instance_id"])
            instance = await runtime._waiting_instance(row["instance_id"])
            timer = self.timers.get(runtime.model.curie(event))
            try:
                with self.store.transaction():
                    if not self.store.release_timer(
                        event, due, row["task_id"], self.holder, self.clock.now().timestamp()
                    ):
                        raise LeaseLost(event)
                    task = runtime.engine.waiting_timer(instance.workflow, row["task_id"])
                    if task is None or timer is None:
                        log.info("timer %s due %s: instance %s no longer waits on it", event, due, instance.id)
                        return None
                    runtime.worker.fire_timer(instance, task, timer, due, self.clock.now())
                    runtime.worker._checkpoint(instance, "running")
            except LeaseLost:
                log.debug("timer claimed elsewhere %s due %s (lease lapsed)", event, due)
                return None
            except Exception:
                runtime.instances.pop(instance.id, None)  # the next use reloads the last checkpoint
                raise
            log.info("timer fire %s due %s instance %s", event, due, instance.id)
            return runtime._launch(instance)


def format_due_floor(at: datetime) -> str:
    """``at`` in UTC, rounded down to the second: rows due at or before it are due."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
