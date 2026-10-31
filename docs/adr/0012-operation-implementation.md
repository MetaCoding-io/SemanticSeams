# ADR-0012: Operation Implementation — an Operation Says What Implements It

**Status:** Accepted

**Date:** 2026-10-31

**Source:** milestone M014/S01; backlog U6 (and C1, C4, which build on it); research:
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) §3.3

## Context

A BPMN service task `seam:invokes` a comm operation, and the worker runs it. What the
worker then does is fixed in code. `seams_runtime/worker.py` `_invoke` knows one thing
to do with an operation another container serves: build chat messages from the
accepted entity, stream an LLM completion from the container's `deploy:serviceOf`
binding, and validate the joined reply against the operation's `seam:returnsShape`.
An operation served in-process (its container also `seam:executes` the process) does
nothing at all.

So:

- **Nothing in the graph says an operation is an LLM call.** The chat app's
  `:completion_op` is one because it is the only kind the worker knows. An operation
  that pays an expense or sends an email would be sent chat messages too.
- **Hand-written code has no home.** A builder whose service task must run custom code
  or call a payment API has nowhere to put it that the runtime finds and regeneration
  leaves alone. This is the "expressiveness cliff" the research note names, and the
  expense tutorial meets it at "notify the manager" (M014/S03).
- **Principle 8 has no location yet.** It says owned code lives "in its own files,
  behind a generated stub, in the location U6 defines". C1 (stub generator) and C4 (LLM
  draft generator) both write to that location.

`proc.ttl`'s implementation rule (gaps.md GAP-27) answers *where* an operation is
served: by the `arch:Container` that `seam:exposes` it, at its `comm:path`, or
in-process when that container executes the process. It does not answer *what* serves
it. [ADR-0007](./0007-execution-strategy.md) stands: generated code holds no business
logic (rule 1), generated files are disposable (rule 4, whose "hand-written extension
module" this ADR places), and the runtime resolves everything it needs from the graph
at load time (rule 2).

## Decision

### One seam predicate and a kind vocabulary

**`seam:implementedBy`** — `hydra:Operation` → an implementation node. It is the only
new seam predicate (reveal mode `seam:Layer`: the implementation is code, not a model
the viewer can open). The node's `rdf:type` is its kind, one of three `comm:` classes:

| Kind | What the runtime does | Extra facts |
|---|---|---|
| `comm:LLMCompletion` | Today's `_invoke`, made explicit: chat messages from the accepted entity, a streamed completion from the serving container at the operation's `comm:path`, deltas published on the task's `seam:publishesTo` channel, the joined reply validated against `seam:returnsShape` | none |
| `comm:PythonHandler` | Calls a hand-written function in the handlers package, in the runtime's process | `comm:handler`: a dotted-path literal, relative to the handlers package |
| `comm:HTTPEndpoint` | POSTs the accepted entity as JSON to the serving container and validates the JSON response against `seam:returnsShape` | none: the base URL comes from the existing `deploy:serviceOf` binding, the path from the operation's `comm:path` template |

The kind is a class, not a string, so SHACL can check it (principle 9) and no second
predicate is needed (principle 4). The predicate sits on the operation, not the service
task: the operation is the contract (`seam:acceptsShape`, `seam:returnsShape`), and
every task that invokes it gets the same implementation. Each operation has at most one
`seam:implementedBy`.

The where-rule of GAP-27 still holds, and the kinds must agree with it:

- `comm:PythonHandler` runs in the runtime, so the operation must be served in-process
  (its exposing container `seam:executes` the invoking process).
- `comm:LLMCompletion` and `comm:HTTPEndpoint` reach another container, so the
  executing container must have a `deploy:serviceOf` binding to the container that
  `seam:exposes` the operation. Secret values stay out of the graph (ADR-0011's binding
  rule).

An in-process operation with no `seam:implementedBy` keeps today's meaning: the runtime
itself serves it (its `seam:acceptsShape` was validated at `start_process`, and the
task's `seam:writes` persists the entity). Every operation invoked across containers
must declare its implementation; the runtime no longer guesses LLM.

One implementation of each kind:

```turtle
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix comm:  <https://w3id.org/seams/comm#> .
@prefix :      <https://example.org/expenses/> .

:completion_op a hydra:Operation ; rdfs:label "LLM Completion" ;
    seam:implementedBy :completion_impl .
:completion_impl a comm:LLMCompletion ; rdfs:label "LLM completion" .

:notify_manager_op a hydra:Operation ; rdfs:label "Notify Manager" ;
    seam:implementedBy :notify_manager_impl .
:notify_manager_impl a comm:PythonHandler ; rdfs:label "notify manager handler" ;
    comm:handler "notify.notify_manager" .

:pay_expense_op a hydra:Operation ; rdfs:label "Pay Expense" ;
    seam:implementedBy :pay_expense_impl .
:pay_expense_impl a comm:HTTPEndpoint ; rdfs:label "payments API" .
```

### Where hand-written code lives

Python handlers live in one **handlers package**, a directory with an `__init__.py`.
`SEAMS_HANDLERS` names it; by default it is `handlers/` beside the model file
(`<app>/handlers`, for example `examples/expenses/chapter-09/handlers`). The runtime
imports it under one package name and resolves every `comm:handler` relative to it:
`"notify.notify_manager"` is the function `notify_manager` in `handlers/notify.py`.

A handler path is only ever resolved inside that package. Each segment must be a Python
identifier, so a leading dot, `..`, a slash or an absolute module such as `os.system`
cannot name code outside it. A model therefore cannot make the runtime import arbitrary
code; it can only pick a function the application's owner put in the package (the
Security principle: handlers are owned code, reviewed like any contribution).

### The handler call

```python
def notify_manager(entity: dict) -> dict: ...        # or: async def
```

- **In:** one positional argument, the current entity of the operation's
  `seam:acceptsShape`, as the plain payload dict the shapes validated (no `id` or
  `status` added).
- **Out:** a dict, validated by `runtime.validate` against the operation's
  `seam:returnsShape`. It becomes the current entity of that shape, so the task's
  `seam:writes` persists it exactly as it persists an LLM reply today. An operation with
  no `seam:returnsShape` must return `None`.
- An `async def` handler is awaited; a plain function runs in a worker thread so it
  cannot block the event loop.
- A handler never sees the store, the bus, lifecycle statuses or secrets. Lifecycle
  transitions stay `seam:fires` facts on the task (ADR-0007 rule 1); the handler only
  computes.

### Loading and the error contract

Resolution happens at `Runtime.load`, before any request is served, for every operation
a service task `seam:invokes`. A Python handler is imported and checked to be callable
then, not on first use. Each model fault raises `seams.errors.ResolutionError(subject,
predicate)` naming the fact ("Errors name the fact"):

| Case | `subject` | `predicate` |
|---|---|---|
| an operation invoked across containers with no `seam:implementedBy` | the operation | `seam:implementedBy` |
| more than one `seam:implementedBy` | the operation | `seam:implementedBy` |
| an implementation with no kind, several kinds, or a kind not in the vocabulary | the implementation | `rdf:type` |
| a kind that disagrees with where the operation is served (a Python handler on a remote operation; an LLM or HTTP kind on an in-process one, or with no `deploy:serviceOf` binding) | the operation | `seam:exposes` |
| a `comm:PythonHandler` with no `comm:handler`, or several | the implementation | `comm:handler` |
| a handler path outside the package (a segment that is not an identifier), a module that does not import, a missing attribute, or one that is not callable | the implementation | `comm:handler` |
| no handlers package at `SEAMS_HANDLERS` or the default, while some operation needs one | the implementation | `comm:handler` |

An import that fails inside the handler's own module is reported with the original
exception chained, so the traceback still points at the line.

Faults at run time are not model faults and are not `ResolutionError`s: a handler that
raises, an HTTP endpoint that times out or answers non-2xx or non-JSON, and a result
that fails `seam:returnsShape` (`ContractViolation`, naming the operation) all fail the
instance the way an `LLMError` does today. The instance's error records the operation
and the implementation kind. Error shapes and BPMN error boundary events are U7's
(M014/S04), not this ADR's.

### Observability

The worker's step row for an invoking task records the kind as `row["implementation"]`:
`"LLMCompletion"`, `"PythonHandler"`, `"HTTPEndpoint"`, or `"runtime"` for an
in-process operation with no `seam:implementedBy`. A Python handler's row also records
`row["handler"]` (the dotted path), and an HTTP or LLM row keeps `row["path"]`. The
trace, the result dict and the OpenTelemetry element span therefore say what ran.

### Regeneration rule

Principle 8 applied to the handlers package:

- A generator may emit a **handler stub once**: when a `comm:PythonHandler`'s module or
  function is absent, it writes a deterministic stub module (generated-file header with
  the model hash and the operation's IRI, the call signature, accepted and returned
  shape names, a body that raises `NotImplementedError`). From then on the file is
  owned code.
- A generator **never overwrites** a file in the handlers package and never writes
  into one that exists. A handler whose module exists but lacks the function is
  reported, not patched. C4's LLM drafts follow the same rule: they propose a diff.
- Generated directories stay excluded from ruff (`extend-exclude` in `pyproject.toml`);
  the handlers package is **not** excluded, so owned code goes through ruff and the
  tests like any other code.
- The committed-outputs CI check covers generated directories only; the handlers
  package is not regenerated in CI.

### Migration

- **Chat app (M014/S02):** `:completion_op` gains `seam:implementedBy` a
  `comm:LLMCompletion` node. Its behaviour does not change. `:send_message_op` is
  in-process and declares nothing. Without the declaration the chat app would fail at
  load with `ResolutionError(:completion_op, seam:implementedBy)`, which is the intent:
  the LLM call is declared, not assumed.
- **Expense tutorial (M014/S03):** a non-LLM service task with a `comm:PythonHandler`
  and its owned handler, in a new chapter checkpoint.
- `proc.ttl`'s GAP-27 rule gains a sentence: what serves the operation is its
  `seam:implementedBy`.

## Alternatives Considered

- **Keep inferring LLM for remote operations.** Rejected: it is the cliff itself, and a
  default nobody stated is a fact missing from the model (principle 1).
- **A Python dotted path straight on the operation (`comm:handler` on the
  operation).** Rejected: it gives no place for the other kinds, and SHACL cannot tell a
  handler from an endpoint.
- **Arbitrary importable paths.** Rejected: a model would choose which code the runtime
  imports, and owned code would have no single location for stubs, drafts and ruff.
- **The predicate on the service task.** Rejected: two tasks invoking one operation
  would state its implementation twice, and the operation is where the contract lives.
- **A `seam:implementationKind` string or a second predicate.** Rejected: the node's
  type already is the kind, checkable by SHACL, with no extra vocabulary (principle 4).
- **Generated handlers re-created on every run.** Rejected: it would overwrite owned
  code (principle 8, ADR-0007 rule 4).

## Consequences

- **S02** adds `seam:implementedBy`, the three `comm:` kind classes and `comm:handler`
  to the ontologies with their SHACL, declares the chat app's LLM call, and replaces
  `_invoke`'s LLM-only path with dispatch on the kind under the error contract above,
  recording `row["implementation"]`.
- **S03** adds the stub emission and the expense tutorial's Python handler.
- **C1** (M022/S02) enriches the stub (data classes from the shapes, docstrings naming
  the decision and transition) and **C4** (M022/S04) writes its drafts only to the
  handlers package.
- Every model whose remote operation relied on the LLM default must add one
  `seam:implementedBy` edge.
