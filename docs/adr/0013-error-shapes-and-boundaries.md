# ADR-0013: Error Shapes and Error Boundaries — an Operation Declares Its Errors, a Process Catches Them

**Status:** Accepted

**Date:** 2026-10-31

**Source:** milestone M014/S04; backlog U7; research:
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) §3.3;
spike: [`tests/test_spike_error_boundary.py`](../../tests/test_spike_error_boundary.py)

## Context

[ADR-0012](./0012-operation-implementation.md) gave an operation an implementation and
said what happens when that implementation fails: the instance fails, the way an
`LLMError` fails it. Every failure is terminal. It left error shapes and BPMN error
boundary events to U7.

So, today:

- **An operation cannot say how it fails.** It has a `seam:acceptsShape` and a
  `seam:returnsShape` and nothing for its error responses. A generated route answers a
  failure with whatever FastAPI produces. A client cannot rely on the body, and SHACL
  cannot check it.
- **A process cannot route a failure.** BPMN has the construct: an error boundary event
  attached to a task, with its own outgoing flow. The expense tutorial needs it at
  "Notify Manager": if the notification cannot be sent, the expense should go down an
  escalation path instead of failing outright. But nothing lifts the boundary into the
  graph, the worker does not know it, and the viewer cannot show which operation error
  it catches.

[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) (problem details for HTTP APIs)
already standardises the error body: `application/problem+json`, with the members
`type`, `title`, `status`, `detail` and `instance`, plus any extension members.
[ADR-0007](./0007-execution-strategy.md) rule 1 still holds: routing a failure is
process logic, so it lives in the BPMN, and the generated code only passes the error
along.

### Spike findings

The spike (`tests/test_spike_error_boundary.py`, kept as a regression test) runs an
inline BPMN with an error boundary event on a plain `bpmn:serviceTask`, through the
engine's own `GraphBoundParser` and `make_serializer`, stepped the way the worker steps
it. SpiffWorkflow 3.2.0 behaves as follows:

1. **An exception does not reach a boundary.** A `WorkflowTaskException`, or
   `task.error()`, puts the task in `ERROR` and leaves the boundary event `WAITING`.
   Spiff never maps an exception to an error event. The worker must throw the error
   itself.
2. **The worker throws an `ErrorEventDefinition` from the STARTED task.** A plain
   service task stays `STARTED` while the worker runs its handler (ADR-0007, spike
   finding 2), and its boundary events are `WAITING` all that time.
   `ErrorEventDefinition(name, code).throw(task)` makes a boundary whose `bpmn:error`
   has that `errorCode` `READY`. Spiff matches on the code alone (`name` is ignored).
   A boundary whose `errorEventDefinition` has no `errorRef` catches every code.
3. **A code no boundary declares changes nothing.** The task stays `STARTED` and every
   boundary stays `WAITING`, so the worker can tell that the throw was not caught and
   fail the instance as it does today.
4. **Running the boundary cancels the task.** After a matching throw the attached task
   is still `STARTED`. It becomes `CANCELLED` only when the `READY` boundary runs. The
   worker's loop picks a STARTED task before a READY one, so after a caught throw the
   worker must run the boundary next and must not `complete()` the cancelled task.
5. **The thrown task's data flows down the error path.** The throw copies the task's
   data into the boundary event and its successors. The happy-path successors are never
   reached, and the process completes through the error path's end event.
6. **Serialization holds.** A workflow serialized with `make_serializer()` while the
   task is STARTED and its boundary WAITING deserializes and still routes the throw.

## Decision

### An operation declares its errors with Hydra

An operation names each error it can raise as a `hydra:Status`, through Hydra's own
`hydra:possibleStatus`. The status carries its HTTP code in `hydra:statusCode`. One new
term, **`comm:errorCode`**, a string literal, makes it an error the runtime and the
process can name. It is the code an implementation raises and that a `bpmn:error`'s
`errorCode` matches. The body of the error response is the status's
**`seam:returnsShape`**: the existing seam predicate, now also allowed on a
`hydra:Status`, which means "the response with this status has this shape". All three
triples except the last are comm-layer facts and live in the comm model's graph. The
status-to-shape edge crosses into the data layer, so it is a seam and lives in
`<urn:seams:graph:seams>` ([ADR-0001](./0001-named-graph-partitioning.md)).

### An error shape is a SHACL shape over problem+json

The error shape is an ordinary `sh:NodeShape`. Its properties use five new `comm:`
properties, one for each RFC 9457 member, so the shape's field names (the `sh:path`
local names that `seams_runtime.contracts` validates) are exactly the JSON member
names:

| Property | Member | Required in an error shape |
|---|---|---|
| `comm:type` | `type` (a URI reference; RFC 9457 defaults it to `about:blank`) | no |
| `comm:title` | `title` (a short summary) | yes |
| `comm:status` | `status` (the HTTP status code) | yes, `xsd:integer` |
| `comm:detail` | `detail` (this occurrence's explanation) | no |
| `comm:instance` | `instance` (a URI reference for this occurrence) | no |

Any other property of the shape is an RFC 9457 extension member, named by its own
`sh:path` as usual. The `status` member's value is never stated in the shape: it is the
status's `hydra:statusCode`, filled in when the body is built, so the code is stated
once (principle 1).

### An error boundary event is lifted when it catches an operation error

The lifting rule follows [ADR-0002](./0002-iri-identity-and-migration.md): a BPMN element
gets an IRI only when it takes part in a seam.

- A `bpmn:boundaryEvent` with an `errorEventDefinition`, `attachedToRef` a service task
  that `seam:invokes` an operation, is lifted. Its IRI is the BPMN model IRI with the
  boundary's `id` as the fragment. It is typed **`proc:ErrorBoundaryEvent`** (a new
  class mirroring that BPMN construct) and is `seam:inModel` the BPMN model.
- One new seam predicate, **`seam:catches`** (reveal mode `seam:Layer`), links it to
  the `hydra:Status` it catches: one of the invoked operation's
  `hydra:possibleStatus`. A lifted boundary catches exactly one error.
- The attachment (`attachedToRef`) and the code (the `bpmn:error` the event's `errorRef`
  names, and its `errorCode`) stay in the native XML. They are not restated in the
  graph. The worker joins the graph to the XML on them and checks they agree, the way
  `dec:payloadElement` joins a decision to its DMN.
- A boundary with no `errorRef` (a catch-all) is not lifted. On a task that invokes an
  operation it is a model fault: Spiff would route codes the operation never declared.

The example below is in one graph for brevity. In a model, `seam:catches` and both
`seam:returnsShape` edges go in the seams graph, and the operation, its status and its
error code go in the comm model's graph.

```turtle
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix comm:  <https://w3id.org/seams/comm#> .
@prefix proc:  <https://w3id.org/seams/proc#> .
@prefix :      <https://example.org/expenses/> .

:notify_manager_op a hydra:Operation ; rdfs:label "Notify Manager" ;
    hydra:possibleStatus :notify_failed .

:notify_failed a hydra:Status ; rdfs:label "Notification failed" ;
    hydra:statusCode 502 ;
    comm:errorCode "notify-failed" ;
    seam:returnsShape :NotifyProblemShape .

:NotifyProblemShape a sh:NodeShape ; rdfs:label "Notify problem" ;
    sh:property [ sh:path comm:title ; sh:datatype xsd:string ; sh:minCount 1 ] ,
                [ sh:path comm:status ; sh:datatype xsd:integer ; sh:minCount 1 ] ,
                [ sh:path comm:detail ; sh:datatype xsd:string ] .

<https://example.org/expenses/approval_bpmn#notify_failed_boundary> a proc:ErrorBoundaryEvent ;
    rdfs:label "Notification failed" ;
    seam:catches :notify_failed .
```

And in `approval.bpmn`, unchanged in kind from any BPMN tool's output:

```xml
<bpmn:error id="notify_failed_error" name="Notification failed" errorCode="notify-failed" />
<bpmn:boundaryEvent id="notify_failed_boundary" attachedToRef="notify_manager">
  <bpmn:errorEventDefinition errorRef="notify_failed_error" />
</bpmn:boundaryEvent>
```

### Shapes

`ontology/shapes/seam-shapes.ttl` checks what the graph alone can show (principle 5):

- `seamsh:ErrorStatusShape`: a subject of `comm:errorCode` is a `hydra:Status` with
  exactly one `comm:errorCode` (a code-like string), exactly one integer
  `hydra:statusCode` from 400 to 599, and exactly one `seam:returnsShape`, which
  conforms to `seamsh:ProblemShapeShape`. It is the object of some operation's
  `hydra:possibleStatus`.
- `seamsh:ProblemShapeShape`: the error shape declares a `comm:status` property with
  `sh:datatype xsd:integer` and a `comm:title` property.
- `seamsh:ErrorCodeUniqueShape`: an operation's error statuses have distinct
  `comm:errorCode`s.
- `seamsh:ReturnsShapeShape` is widened: the subject of `seam:returnsShape` is a
  `hydra:Operation` or a `hydra:Status`.
- `seamsh:CatchesShape`: only a `proc:ErrorBoundaryEvent` `seam:catches`, exactly one
  `hydra:Status` that has a `comm:errorCode`. `seamsh:ErrorBoundaryEventShape`: every
  `proc:ErrorBoundaryEvent` `seam:catches` one.

Two checks need the BPMN XML, so they are made at load and not by the shapes. That the
boundary is attached to a task invoking an operation whose `hydra:possibleStatus` is
the caught status, and that the event's `bpmn:error` `errorCode` equals the status's
`comm:errorCode`. Each fails with
`ResolutionError(<boundary IRI>, seam:catches, …)`. A catch-all boundary on an invoking
task fails with `ResolutionError(<boundary IRI>, bpmn:errorEventDefinition, …)`.

### Raising an error

- **`comm:PythonHandler`:** an owned handler raises
  `seams_runtime.errors.OperationError(code, detail=None, **extensions)`. `code` is a
  `comm:errorCode` of the operation, and `detail` and the extensions become problem
  members. Any other exception keeps ADR-0012's meaning: the instance fails.
- **`comm:HTTPEndpoint`:** a non-2xx `application/problem+json` answer is the declared
  error whose `hydra:statusCode` equals the response's status, when exactly one of the
  operation's errors has that code. Any other non-2xx answer fails the instance as
  today.
- **`comm:LLMCompletion`** declares no codes; its failures are unchanged.

The worker builds the problem body: `title` from the status's `rdfs:label`, `status`
from `hydra:statusCode`, `detail` and extensions from the raised error. It validates
the body against the status's `seam:returnsShape`. A body that does not conform is a
`ContractViolation` naming the status, and the instance fails. A code the operation
does not declare also fails the instance, with the code recorded in the error.

### Routing an error

When the invoking task has a lifted boundary that `seam:catches` the raised status, the
worker does what the spike proved. It throws `ErrorEventDefinition(name, code)` from
the STARTED task, with the boundary's `bpmn:error` `errorCode`. It does not apply the
task's `seam:fires` transition or persist its `seam:writes`. The problem body becomes
the current entity of the error shape, so a task on the error path can `seam:reads` it.
The worker then runs the boundary, which cancels the task, and steps on down the error
path. With no matching boundary, the instance fails as it does today, and its error
records the code and the status.

### Generated routes

A generated route for an operation with error statuses declares each one as an
`application/problem+json` response. One generated exception handler turns a declared
error into a response with the status's `hydra:statusCode` and the validated body. The
route handler stays validate, start, render, with no branching (ADR-0007 rule 1).

### Observability

The invoking task's trace row records `row["error"] = {"code", "status", "operation"}`,
and `row["boundary"]` (the boundary's IRI) when a boundary caught it. The boundary's own
row records `row["caught"]` (the code). The OpenTelemetry element spans read these from
the rows, as they read every other row field.

### Viewer

A lifted boundary is a graph element like any other. The BPMN renderer draws it on its
task with seam dots, and its `seam:catches` edge navigates to the operation's error
status (ADR-0005).

## Alternatives Considered

- **`comm:errorShape` on the operation, with `comm:status` and `comm:errorCode` beside
  it** (the slice plan's first sketch). Rejected: an operation with two errors could not
  say which shape goes with which status. Hydra already has `hydra:possibleStatus` and
  `hydra:statusCode` (principle 4), and an operation-to-shape link is a cross-layer
  fact, which belongs in a seam predicate (principle 3), and `seam:returnsShape` already
  is one.
- **A new `seam:errorShape`.** Rejected: `seam:returnsShape` on a status says exactly
  "the body of this response has this shape", and every existing reader of it is keyed
  on an operation subject, so widening it changes nothing they see.
- **Problem members under app-namespace paths (`:title`, `:status`).** Rejected: the
  shapes could not tell an error shape from any other, and every app would restate the
  RFC's member names.
- **The error code only in the BPMN XML.** Rejected: an HTTP route has errors with no
  process at all, so the operation's contract must name its codes itself. The XML keeps
  its `errorCode` because Spiff routes on it, and the load check keeps the two equal.
- **Rely on Spiff to route exceptions.** Not possible: spike finding 1.
- **Lift every boundary event.** Rejected: ADR-0002 lifts only seam-bearing elements, and
  a boundary that catches no operation error joins no other layer.

## Consequences

- **T01** (this ADR) adds `comm:errorCode`, `comm:type`, `comm:title`, `comm:status`,
  `comm:detail`, `comm:instance`, `proc:ErrorBoundaryEvent` and `seam:catches`, with the
  shapes above.
- **T02** emits the problem+json response models and exception handler from
  `hydra:possibleStatus`, and adds the body validator to `seams_runtime.contracts`.
- **T03** resolves lifted boundaries at `Runtime.load` under the checks above, adds
  `OperationError`, and routes raised errors as described, recording them in the trace.
- **T04** adds the boundary on "Notify Manager" in expense chapter 9 and draws boundary
  events in the viewer.
- Models without `hydra:possibleStatus` or boundaries are unaffected.
