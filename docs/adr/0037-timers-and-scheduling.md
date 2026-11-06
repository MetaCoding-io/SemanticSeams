# ADR-0037: Timers and Scheduling — BPMN Timer Events Are Lifted as Index Types, Their ISO 8601 Expressions Stay in the XML, `seam:schedules` Names the Container That Runs a Process's Timer Starts, and the Shared Store Makes Each Firing Run Once

**Status:** Accepted; the first open question is resolved (2026-11-06, M030/S02)

**Date:** 2026-11-06

**Source:** milestone M030/S01; backlog U10 (and A10); research notes
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.6 and
[runtime storage](../research/2026-10-29-runtime-storage.md) ("Not covered"); builds on
[ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0007](./0007-execution-strategy.md),
[ADR-0010](./0010-channel-started-processes.md),
[ADR-0013](./0013-error-shapes-and-boundaries.md),
[ADR-0015](./0015-environments.md) and
[ADR-0035](./0035-aggregate-transaction-boundary.md)

## Context

Section 3.6 of the UML coverage note names the gap: nothing models timers or recurring
jobs, and most applications have them (reminders, cleanups, digests). BPMN already has
the words. A `bpmn:timerEventDefinition` on a start event starts a process on a
schedule; on an intermediate catch event it makes an instance wait; on a boundary event
it fires while the task it is attached to is still open. Each carries one of three
expressions: `bpmn:timeDate`, `bpmn:timeDuration` or `bpmn:timeCycle`.

The runtime cannot run any of them:

- **Nothing starts a process on a schedule.** A process starts from a UI event
  (`seam:triggers`) or a channel (ADR-0010). The FastAPI generator's `_triggered`
  raises `GeneratorError` for a process with neither.
- **Nothing wakes a waiting instance.** SpiffWorkflow 3.2 parses timer definitions
  (`TimeDateEventDefinition`, `DurationTimerEventDefinition`,
  `CycleTimerEventDefinition`), but a timer only fires when something calls the
  workflow's `refresh_waiting_tasks()` after its due time. The worker
  (`seams_runtime/worker.py`) steps an instance until it waits on a user task or ends,
  and nothing calls it again on a clock.
- **Spiff reads the expression as Python.** Its script engine evaluates the body of
  `bpmn:timeDuration` and the rest, so the BPMN must hold a quoted string such as
  `"PT48H"`. A date-time without an offset is read in the host's local time zone, so
  the same model could fire at different instants on different hosts.
- **Replicas would fire twice.** ADR-0015 caps the serving container at one replica
  until A10. Once M030/S03 lifts that cap, every replica that runs a schedule would run
  each firing, unless the replicas agree through the store they share.

## Decision

### 1. Timer events are lifted as `proc:TimerStartEvent` and `proc:TimerCatchEvent`; the expression stays in the XML

A BPMN element with a `bpmn:timerEventDefinition` is lifted into the BPMN model's index
graph like any other element (ADR-0002: its IRI is `<BPMN model>#<bpmn id>`), typed by
where it sits:

| BPMN element | Index type | In scope |
|---|---|---|
| `bpmn:startEvent` of a process | `proc:TimerStartEvent` | yes: a timer-started process |
| `bpmn:intermediateCatchEvent` | `proc:TimerCatchEvent` | yes: the instance waits |
| `bpmn:boundaryEvent` attached to a `proc:UserTask`, interrupting or not | `proc:TimerCatchEvent` | yes: the overdue-approval reminder |
| `bpmn:boundaryEvent` attached to any other task | not lifted | no: a service-call timeout is an error (ADR-0013) |
| `bpmn:startEvent` of an event subprocess | not lifted | no |

The expression is **not** copied into the graph. As with `proc:ErrorBoundaryEvent`
(ADR-0013), the graph says what the element is and the XML says how it behaves:
`Runtime.load` joins the two on the IRI and checks they agree (a `proc:TimerStartEvent`
is a start event with exactly one timer definition, a `proc:TimerCatchEvent` is a
catch or boundary event with one), raising
`ResolutionError(<event>, bpmn:timerEventDefinition, <what disagrees>)` otherwise. A
timer element left unlifted, or lifted with the wrong type, is index-payload drift
(ADR-0006).

A timer-started process has no route: the FastAPI generator's `_triggered` skips it as
it skips a channel-started one, and a process with no `seam:triggers` event, no
subscribed start and no timer start still raises `GeneratorError` naming the process.
The engine interprets the timers (ADR-0007 rule 1); no generated code reads them.

The chapter 9 overdue-approval reminder is a non-interrupting boundary timer on the
approval user task with a `bpmn:timeDuration`; it leaves the task open and runs a
reminder path. That is what M030/S02 builds.

### 2. Expressions are ISO 8601 literals with a fixed offset, and anything else is refused

The body of each expression element is one quoted ISO 8601 string literal, so Spiff's
script engine reads it as written and the runtime parses the same text:

| Element | Accepted form | Example |
|---|---|---|
| `bpmn:timeDate` | a date-time with `Z` or an offset | `"2026-12-01T09:00:00Z"` |
| `bpmn:timeDuration` | a positive duration, `PnYnMnDTnHnMnS` or `PnW` | `"PT48H"` |
| `bpmn:timeCycle` | a repeating interval with an explicit start, `R[n]/<date-time>/<duration>` | `"R/2026-11-09T08:00:00Z/P1D"` |

Every other body is refused: a variable or any other Python expression, an unquoted
value, a cron string, a date-time with no offset, a zero or negative duration, a cycle
with no start (`R/P1D`, whose firings would depend on when a container booted), the
`<start>/<end>` and `<duration>/<end>` interval forms, and an empty body. A
`bpmn:timeCycle` is accepted only on a `proc:TimerStartEvent` or a non-interrupting
boundary. The refusal names the fact:
`ResolutionError(<event>, bpmn:timeCycle, "cycle has no start date-time: 'R/P1D'")`,
with the predicate the expression element's own (`bpmn:timeDate`, `bpmn:timeDuration`
or `bpmn:timeCycle`).

`Runtime.load` raises it, so a bad expression stops the runtime before anything runs,
and `seams check` reports the same check through the drift lint (ADR-0006), so it is
found before deployment. The generators never read an expression, so a model that
passes the shapes still generates (principle "shapes before generation").

### 3. `seam:schedules` names the container that runs a process's timer starts

`seam:schedules` is a new seam predicate, `arch:Container -> proc:Process`, in the
seams graph (ADR-0001): the container runs the process's timer start events. The
container must also `seam:executes` the process, since it starts the instance in
process. M030/S02 adds it to the vocabulary and the seam shapes:

- `seamsh:SchedulesShape`: the subject is an `arch:Container` that `seam:executes` the
  object, and the object is a `proc:Process` whose BPMN model holds a
  `proc:TimerStartEvent`.
- `seamsh:TimerStartedProcessShape`: a process whose model holds a
  `proc:TimerStartEvent` is the object of exactly one `seam:schedules`. None, or more
  than one, is a violation, and `ModelGraph.scheduling_container(process)` raises
  `ResolutionError(<process>, seam:schedules, <sorted container IRIs>)` the same way.

The fact is listed, never derived from `seam:executes`: a process may be executed by
more than one container, and the one that keeps time must be a decision. It earns a
query (design rule 2): "which schedules stop if node X dies", through
`seam:schedules/seam:deployedTo`.

Timers inside an instance (`proc:TimerCatchEvent`) need no seam: the instance belongs
to the process, and every container that `seam:executes` the process can wake it once
it is due (section 4).

**The compose generator** adds no service and no binding. A scheduling container
already `seam:executes` a process, so it is a serving container
(`serving_containers`) with the runtime image, and the runtime reads `seam:schedules`
from the mounted model, whose hash it already pins (P006). The generator writes one
comment above the service naming the processes it schedules, sorted by IRI. Until A10
the serving container stays capped at one replica (ADR-0015); section 4 is what lets
M030/S03 lift the cap.

### 4. Each firing runs once: claims in the shared store

Every runtime whose container schedules a process, or executes a process with timer
catch events, runs one scheduler loop. The loops on different replicas never talk to
each other: they agree through the store the instances already share (`seam:storedIn`
resolution, ADR-0011), using `Store.transaction()` (ADR-0035) on SQLite and
PostgreSQL. A SemPKM store holds no workflow state, so a scheduling container needs a
relational store, and `Runtime.load` refuses one without it with
`ResolutionError(<container>, seam:schedules, ...)`.

- **Due times are computed, not observed.** A timer start's firings are the instants
  the expression defines: a `bpmn:timeDate` fires at its date-time, and a
  `bpmn:timeCycle` at its start plus whole multiples of its duration. Neither depends
  on when a container started, so every replica computes the same due times. A timer
  catch's due time is fixed once, when the instance reaches the event (Spiff's
  `event_value`), and is written to the store with the checkpoint, never recomputed.
  All due times are UTC.
- **A timer start is claimed by a firing row.** A firing is the key
  `(start event IRI, due time)`. The replica that inserts that row into the store's
  timer table starts the instance, and checkpoints it, in the same transaction; an
  insert that conflicts means another replica has the firing, and nothing runs. A crash
  before the commit rolls both back, and a crash after it leaves a checkpointed
  instance that `Runtime.resume` continues (ADR-0010). The instance's correlation key
  is the due time, `YYYY-MM-DDTHH:MM:SSZ`, so a firing is found by key.
- **A timer catch is claimed by a lease.** The waiting instance's timer row carries a
  holder and a lease expiry. A replica takes a due row only if it is unheld or its
  lease has expired, loads the state, calls `refresh_waiting_tasks()` and runs the
  instance; it deletes the row in the transaction that writes the next checkpoint, and
  only if it still holds the lease, so a replica whose lease lapsed rolls back instead
  of running the timer twice.
- **Missed firings fire once.** If no runtime ran across several due times of a cycle,
  the next loop fires only the latest of them and logs how many it skipped. A
  `bpmn:timeDate` in the past at its first load fires once.
- **The clock is injected.** The scheduler reads time from a clock the runtime is given
  (the system clock by default), so tests step time instead of waiting.

Nothing about time reaches generated output: the generators never read an expression,
due times exist only in the store and the logs, and the generated files carry no
timestamp (principle "same model, same bytes").

### 5. Observability, and `seam` 1.6 and `proc` 1.1 as compatible widenings

The scheduler logs one line per outcome:

- `timer fire <event> due <due> instance <id>` when a replica starts or wakes an
  instance;
- `timer claimed elsewhere <event> due <due>`, at debug level, when an insert conflicts
  or a lease is held;
- `timer missed <event> N firing(s)` when it skips missed cycle firings.

It emits two spans: `seams.timer.claim` around the claim transaction, and
`seams.timer.fire` around the start or wake, each carrying `seams.timer.event`,
`seams.timer.due` and, once it is known, `seams.instance.id`. A fired instance's trace
rows are the worker's, so the reminder shows in the as-designed and as-run sequences
like any other path.

The vocabulary widens, with no migration files (ADR-0021: a minor step only adds):

| Vocabulary | Version | Adds |
|---|---|---|
| `seam` | `1.5` to `1.6` | `seam:schedules` |
| `proc` | `1.0` to `1.1` | `proc:TimerStartEvent`, `proc:TimerCatchEvent` |

## Alternatives considered

- **A separate scheduler container.** Rejected: it would have to execute every
  process it starts, so it would be a second serving container holding instances, and
  it would still need claims once it ran with replicas. `seam:schedules` can name a
  dedicated container later if a model wants one.
- **Deriving the scheduling container from `seam:executes`.** Rejected: a process may
  be executed by more than one container, and which one keeps time would be a hidden
  rule rather than a fact a query can find.
- **Copying the expression into the graph (`proc:timeCycle` and the like).** Rejected:
  the XML already holds it, so a copy is a second source that can drift (ADR-0006).
  The graph types the element, as it does for error boundaries.
- **Cron strings, or Spiff's Python expressions.** Rejected: cron is not BPMN, and an
  expression computed from process data has no due time a replica can compute ahead of
  time, so it cannot be claimed once.
- **A single replica elected leader for all timers.** Rejected: election needs its own
  lease and failover, which the per-firing claim gives for free, and it would make one
  replica special in a model whose replicas are meant to be the same.
- **Firing every missed cycle on recovery.** Rejected: a digest that was down for a
  week would send seven digests at once.

## Consequences

- M030/S02 adds `seam:schedules`, `proc:TimerStartEvent` and `proc:TimerCatchEvent`,
  their shapes, the load checks, the scheduler loop with its timer table on SQLite and
  PostgreSQL, and the chapter 9 reminder (or a later chapter), with its tutorial
  section and the regenerated outputs. `seam` goes to 1.6 and `proc` to 1.1.
- M030/S03 relies on section 4 to lift ADR-0015's one-replica cap for the serving
  container.
- Spiff keeps interpreting the timers. The runtime only computes due times, claims
  them and calls `refresh_waiting_tasks()`.
- A timer-started process has no route and no UI trigger, like a channel-started one.

## Open questions

- **Long durations in an end-to-end run.** A reminder after `"PT48H"` cannot be waited
  for in the compose run. S02 decides between a development clock offset for the
  runtime and a tutorial duration short enough to wait for, without putting a test
  value in the model. *Resolved in M030/S02 (decision D065):* the model keeps `"PT48H"`.
  The runtime's clock takes a development-only offset from `SEAMS_CLOCK_OFFSET`, which
  the compose e2e sets in an override file, and the generated compose never writes it.
  A scenario's run fires the timers its instance waits on once its steps are done
  ([ADR-0014](./0014-scenarios-and-derived-tests.md), amended 2026-11-06), so the
  generated tests need no clock at all.
- **Cancelling a schedule.** Removing a `proc:TimerStartEvent` stops future firings at
  the next load; nothing yet cleans the timer rows of a removed catch event.
