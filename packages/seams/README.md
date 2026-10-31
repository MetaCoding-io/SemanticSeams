# semanticseams

The `seams` library: import name `seams`, distribution name `semanticseams`.

It reads Semantic Seams models without executing them. Its only dependencies
are rdflib and lxml; importing it never pulls in SpiffWorkflow, FastAPI or
`seams_runtime`. The package is strictly type-checked (`uv run pyright`).
v1 is a uv workspace member only and is not published to PyPI; install it
with `uv sync --all-packages`.

```python
import seams

model = seams.load("examples/expenses/chapter-08")  # a .trig file or a directory
model.hash                                          # "sha256:..."
model.interfaces.served_pages().iris()              # (…expenses_page, …payouts_page)
model.processes.element("choose_payout").only().decided_by.decision_id  # "payout_method"
```

`seams.load` reads a TriG file or a directory of them (or `SEAMS_MODEL`), and
the views (`model.architecture`, `interfaces`, `processes`, `decisions`,
`shapes`, `operations`, `channels`, `lifecycles`, `policies`, and the ADR-0014
`scenarios` and `decision_examples`) read every model of a layer at once.
`model.sparql` and `model.question` run read-only SPARQL.

`ModelGraph.store_plan()` resolves which store the runtime keeps its rows in
(ADR-0011) from `deploy:storeKind`, `deploy:connectsTo` and `seam:storedIn`,
returning a `StorePlan` (`kind`, `store`, `container`, `key`, `declared`). A
model that declares no store gets embedded SQLite (`declared=False`). A
missing or duplicated store kind, an unsupported kind, a PostgreSQL store
with no connecting binding, a written shape not stored in the store, or more
than one store raises `ResolutionError` naming the subject and predicate.
`ModelGraph.store_health()` reports the same checks without raising, as a
sorted list of `StoreFinding` (`severity`, `subject`, `predicate`,
`message`): a `Violation` for each resolution error, a `Warning` for a store
container no shape is `seam:storedIn`, and an `Info` when the model declares
no store and the runtime keeps embedded SQLite.
`ModelGraph.replica_health()` adds the replica cap (ADR-0015, backlog A10): a
`Warning` for a serving container that declares more than one
`deploy:replicas` in some environment.

`Container.for_environment(environment)` applies ADR-0015's override rule to
a container's `deploy:override`s and returns a `Deployment` (`artifact`,
`bindings`, `replicas`): an override replaces the shared artifact and replicas
whole, merges bindings by `deploy:key`, and leaves everything it does not state
shared. A malformed override raises `ResolutionError(container, predicate)`.

`Operation.errors` lists the error statuses an operation declares (ADR-0013):
each `hydra:possibleStatus` with a `comm:errorCode`, as a `Status` view
(`status_code` from `hydra:statusCode`, `error_code`, `returns`, the error
shape it `seam:returnsShape`, and `operations`). `Operation.error(code)` is the
one status with that code, else `ResolutionError(operation, comm:errorCode)`.

`ModelGraph.operation_implementation(op)` reads what serves an operation
(ADR-0012) from `seam:implementedBy`, returning an `Implementation` (`iri`,
`kind`, `handler`) or None when the operation declares none. `kind` is one
of `IMPLEMENTATION_KINDS` (`comm:LLMCompletion`, `comm:PythonHandler`,
`comm:HTTPEndpoint`) and `handler` the `comm:handler` dotted path of a
Python handler. Several implementations, a missing, duplicated or unknown
kind, or a handler path that is missing, duplicated or has a segment that is
not a Python identifier raise `ResolutionError` naming the subject and
predicate. The operation view's `implemented_by` lists the nodes.

`seams.coverage` lists what nothing exercises (D054): `unexercised_paths`
(BPMN start-to-end paths no `verify:Scenario` runs, joined in Python because
sequence flows live only in the XML), `unfired_transitions` and
`policies_without_deny` (the `coverage/` canned questions).

The full API, views, SPARQL and model-hash reference is
[The seams library](../../docs/reference/seams-library.md) on the docs site.
