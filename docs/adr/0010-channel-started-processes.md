# ADR-0010: Channel-Started Processes — a Message Start Event Subscribes to a Channel

**Status:** Accepted

**Date:** 2026-10-29

**Source:** decision D029; milestone M009/S07 (tutorial chapter 8, "Growing up")

## Context

Chapter 8 of the expense tutorial pays an approved expense. The payout is a second
process: it has its own DMN decision and its own payment lifecycle, and nobody clicks
a button to start it. It should start when the approval process says "pay this", and
it should run on its own, so a slow payout never holds up the approval.

The runtime could not do that:

- `ChannelBus` (`seams_runtime/channels.py`) only fans events out to SSE subscribers.
  When worker rule 6 publishes a message throw event's completion event, a browser may
  hear it, but no process does.
- `ModelGraph.triggering_operation` and the FastAPI generator's `_triggered` require
  every process a container `seam:executes` to be started by a UI event
  (`seam:triggers` plus `seam:submitsTo`). A process with no UI trigger was a
  `GeneratorError`.

The vocabulary already had the words. `proc:MessageCatchEvent` mirrors a BPMN
message catch or start event, and `seam:subscribesTo` joins it to a `comm:Channel`.
Nothing read either of them.

## Decision

Give `seam:subscribesTo` its first consumer. No predicate or class is added.

### Which processes are channel-started

A process is **channel-started** when an element of its BPMN model (an IRI with the
prefix `<model>#`, where the process `seam:detailedBy <model>`) is:

- a `proc:MessageCatchEvent`,
- that `seam:subscribesTo` a `comm:Channel`,
- and is a `bpmn:startEvent` of the process's BPMN payload.

In the BPMN file the start event carries a `bpmn:messageEventDefinition`, as a BPMN
message start event should. No `messageRef` is needed: the graph names the channel.
A plain `bpmn:startEvent` also works, but loses that hint for BPMN readers.

`ModelGraph` answers three questions, from graph facts only:

| Resolver | Answer |
|---|---|
| `subscribed_processes(channel)` | the channel-started processes subscribed to the channel, sorted by IRI |
| `start_channel(process)` | the process's start event and its channel. None, or more than one, raises `ResolutionError(process, seam:subscribesTo)` |
| `is_channel_started(process)` | True or False. More than one subscribed start raises, as above |

A `proc:MessageCatchEvent` that subscribes but is not a start event (an intermediate
catch) does not make its process channel-started, and nothing dispatches it yet.

### What the runtime does

When worker rule 6 publishes a message throw event on channel C, the runtime starts
every channel-started process subscribed to C (worker rule 6a):

- **Correlation key:** the publisher's.
- **Start state:** a copy of the publisher's `current` entities (entity ids kept) and
  `status` map. The new instance's lifecycle history starts at the copied statuses.
  Because the ids are kept, a subscriber that `seam:writes` the same shape updates the
  same stored entity, which then names the subscriber as its instance.
- **The start message:** Spiff leaves a message start event waiting.
  `Engine.deliver_start` runs Spiff's internal start and delivers an empty message, so
  the start event is ready and the worker steps it like any other element.
- **Its own task:** the instance runs as its own asyncio task, through the same
  machinery as `start_process` (`new_state`, `Engine.new_workflow`, a checkpoint, the
  worker task, `Runtime.instances`). It is checkpointed **before** it runs, so
  `Runtime.resume` can continue it after a restart.
- **Ordering:** the start happens after the publisher's element has completed. The
  publisher's trace row records `started: [{process, instance}]`.
- **Failure isolation:** a subscriber that fails while it runs (for example a
  `LifecycleViolation` on the copied status) fails on its own instance. One that cannot
  start at all (an ambiguous subscription, a missing payload) is logged and recorded
  in the publisher's row as `{process, instance: null, error}`. Neither fails the
  publisher.

`Runtime.start_subscribed(process, correlation_key, current, status)` is the same start,
callable directly (tests use it to stop a subscriber and resume it).

The payload is **not re-validated**. There is no operation whose `seam:acceptsShape`
could check it. The entities were validated when the publisher stored them.

`triggering_operation` and `start_process` are unchanged for UI-triggered processes.

### What the generators do

The FastAPI generator's `_triggered` skips a channel-started process: it has no route.
A process with neither a `seam:triggers` event nor a subscribed start still raises
`GeneratorError` naming the process. The htmx and compose generators need no change:
a container that `seam:executes` any process is serving (`serving_containers`), and
the subscriber runs inside it.

### The query the predicate earns

Design rule 2 says a seam predicate must earn a query. `seam:subscribesTo` now answers
"which processes does this process start?":

```sparql
PREFIX seam: <https://w3id.org/seams/seam#>
PREFIX proc: <https://w3id.org/seams/proc#>
PREFIX comm: <https://w3id.org/seams/comm#>

SELECT ?process ?channel ?started WHERE {
  ?process seam:detailedBy/^seam:inModel ?throw .
  ?throw seam:publishesTo ?channel .
  ?channel a comm:Channel .
  ?catch a proc:MessageCatchEvent ; seam:subscribesTo ?channel ; seam:inModel ?model .
  ?started seam:detailedBy ?model .
}
```

`tests/test_channel_start.py` runs it against its fixture. It is not yet a catalog
query or a viewer button.

## Alternatives Considered

- **(a) A message start event that subscribes to a channel. Chosen.** It uses the
  vocabulary as written, keeps dispatch graph-driven (ADR-0007 rule 1), and reuses the
  publish hook worker rule 6 already has.
- **(b) A "Run payout" button.** Rejected: `seam:subscribesTo` would stay unused, and the
  second process would run only when a person remembered to click.
- **(c) Call the payout as a BPMN call activity.** Rejected: the payout would run
  inside the approval instance, so a slow or failing payout would hold up or fail the
  approval, and the two processes could not be deployed apart later.

## Consequences

- **Positive:** One process can start another from the model alone, and the second
  runs, fails and resumes on its own.
- **Positive:** `seam:subscribesTo` and `proc:MessageCatchEvent` now have a consumer, so
  the chapter-8 model exercises them.
- **Limit:** the bus is in-process, so the publisher and the subscriber run in the same
  runtime. A cross-container broker (a separate worker container) is deferred.
- **Limit:** no message payload schema beyond the copied entities.
- **Limit:** no timer starts, and no intermediate message catch events.
- **Negative:** a subscriber's write of a copied entity moves the stored entity's
  instance to the subscriber. Queries by correlation key are unaffected.
