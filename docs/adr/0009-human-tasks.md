# ADR-0009: Human Tasks — a User Task Points at the Form It Is Completed On

**Status:** Accepted

**Date:** 2026-10-29

**Source:** [backlog](../backlog.md) item E4 (human tasks); decision D027; milestone M009/S04

## Context

The expense tutorial needs a manager to approve an expense. In BPMN that is a
`bpmn:userTask`: the process stops and waits until a person does the work. The
runtime cannot run one today. Spiff marks user tasks manual, the worker
(`seams_runtime/worker.py`) skips manual tasks, and an instance stops in the
`waiting` state with nothing that lists or completes the task.

To list and complete a user task, the model has to say three things the graph does
not say yet:

- **Where** a person does the task: which screen and which form.
- **Who** may do it.
- **What** completing it writes.

Design rule 2 says a new seam predicate must earn a query. The question here is
"which screens must a person visit to finish this process?". Without an edge from the
task to its screen, nothing in the graph answers it.

## Decision

Add one seam predicate, **`seam:completedOn`**: `proc:UserTask -> ifml:Form`, at most
one per task. It reads "the task is completed on this form". It is the mirror of
`seam:triggers`: an event starts a process, and a user task waits for a form. Like
`seam:triggers`, its reveal mode is `seam:Open`, so clicking it in the viewer opens the
form's interaction model.

`seamsh:CompletedOnShape` in `ontology/shapes/seam-shapes.ttl` checks that the subject
is a `proc:UserTask` and that the predicate has at most one value, an `ifml:Form`.

### The screen, the operation and the output follow from the form

Nothing else is added. The rest follows from facts the graph already has:

- **The screen** is the `ifml:ViewContainer` that `ifml:contains` the form.
- **The completion operation** is the one the form's single event `seam:submitsTo`.
  That event has no `seam:triggers`, because the process is already running and waiting.
- **The output** is the shape the form `seam:writes`, which is the task's own
  `seam:writes` shape. The completion operation `seam:acceptsShape` it.

### Authorization

The task's `seam:governedBy` policies decide who may complete it. The
`PolicyEvaluator` evaluates each policy with the **task IRI as the `odrl:target`**, the
same way it evaluates a route's policy with the operation IRI. This keeps the rule
on the task, where the BPMN modeller puts it, and not on whichever operation the form
happens to call.

- A governed task can be listed and completed only by an identity the evaluator accepts
  for every governing policy. Anyone else gets 403.
- An **ungoverned task is open to any authenticated identity**.
- With **no identity**, listing or completing a task fails with 401, governed or not.

### Runtime contract

T02 of M009/S04 builds this:

- The `Store` gains a `user_tasks` table: one row per open user task, with the instance
  id, the task IRI, the BPMN id, the process, the correlation key, and the time it
  opened. The form is not stored, because it follows from the task. Every worker
  checkpoint replaces the instance's rows with its open user tasks, so a row appears
  when an instance stops on a user task and is gone once the task completes.
- `Runtime.user_tasks(identity)` lists the open tasks that identity may complete.
- `Runtime.complete_task(task, payload, correlation_key, identity)` applies the policy,
  finds the open task of the instance with that correlation key (the key is in the
  completion route's path), validates the payload against the task's output shape,
  writes the shape, completes the Spiff task and resumes the worker. A task that is not open (already completed, or
  unknown) raises `TaskNotOpen`, which the host answers with 409.
- The trace row of a completed user task carries `"by"`: the identity that completed it.

### Generator and host contract

T03 of M009/S04 builds this:

- The FastAPI generator emits a **completion handler** for the operation a
  `seam:completedOn` form's event submits to. It depends on
  `runtime.task_policy("<task>")` for the identity, awaits
  `runtime.complete_task("<task>", form, correlation_key=<key>, identity=identity)`
  (which validates), then queries and renders the fragment like any operation
  (pattern P007: no branching in generated code). The correlation-key label must be a
  path variable of the operation.
- The htmx generator emits the **form partial** `<form local name>.html` from the
  form's bound parameters (an `sh:in` field is a `<select>`), with the key filled from
  `task.correlation_key`, so the inbox can render it per task.
- The runtime host serves **`GET /tasks`**, an inbox that lists
  `Runtime.user_tasks(identity)` and renders each open task with its form partial
  (the row's `partial`, given `task=row`), so the task is completed in place; JSON
  when the request accepts `application/json`, 401 without an identity.

### The earned query

`docs/queries/screens-to-finish-process.rq` takes `?process` as its focus and returns
`?task ?form ?screen ?policy` for each user task of the process. `?policy` is
optional, because an ungoverned task has none. Tasks reach the process through the BPMN
model it `seam:detailedBy` (`seam:detailedBy/^seam:inModel`), the same hop
`what-writes-shape.rq` uses.

The research note's second question, "which roles can complete this approval?", is
one more hop: task `seam:governedBy` policy, then `odrl:permission/odrl:assignee`. It is
noted here and covered by a test. It is not shipped as its own query.

The query is not yet a viewer button. M009/S06 adds the fourth catalog query (the
compliance question), and the Questions catalog in `viewer/queries.py` takes both then.

## Alternatives Considered

- **(a) `proc:UserTask -> ifml:Form` (`seam:completedOn`). Chosen.** A form is the
  smallest IFML element that both collects input and has an event that submits it. The
  screen, the operation and the output shape all follow from it, so the generators have
  exactly one place to start.
- **(b) `proc:UserTask -> ifml:ViewContainer`.** Rejected: it is ambiguous when a page
  holds several forms. The generator could not tell which form completes the task.
- **(c) `proc:UserTask -> the whole IFML interaction model`.** Rejected: too coarse to
  generate from. It names an application, not a screen.
- **(d) `ifml:Event -> proc:UserTask`, mirroring `seam:triggers`.** Rejected: the
  milestone wants the task to point at its screen. The BPMN modeller owns the task and
  should be able to say where it is done without editing the interaction model. The
  event direction also suggests the event starts something, which it does not.

## Consequences

- **Positive:** One predicate answers "where is this done" and "which screens finish
  this process". The screen, the operation and the output shape are derived from it, so
  they cannot disagree with it.
- **Positive:** Authorization stays on the task, where a BPMN modeller sets it, and
  uses the existing `PolicyEvaluator` protocol. S06's role evaluator plugs in unchanged.
  (2026-10-29: it has landed as `RoleEvaluator` in M009/S06, and is now the default.)
- **Negative:** The rule "the form's one event submits to the completion operation" is
  an invariant the shapes do not check yet. A form with two events is accepted by SHACL
  and refused by the generator.
- **Negative:** `seam:completedOn` has no equivalent in the checkout example. The
  acceptance test that every seam predicate is exercised also reads the human-task
  fixture, `tests/fixtures/human_task/approval.trig`.
- **Follow-up:** Branching on the decision ("approved" or "rejected") belongs in the
  BPMN as a gateway, or in a DMN table, not in the task or its form.
