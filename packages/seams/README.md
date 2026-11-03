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

`seams.decision_findings(model)` runs the static decision checks (backlog
K2) and returns a sorted list of `DecisionFinding` (`subject`, `fact`,
`message`): `type_ref_findings` flags a DMN input whose `typeRef` does not
accept the `sh:datatype` of its `dec:fromPath`, and `condition_findings` flags
a BPMN condition that reads a variable no upstream business-rule or user task
sets. `seams check` reports them as `decision` findings.

`seams.review_findings(model)` runs the model review checks (backlog R1) and
returns a sorted list of `ReviewFinding` (`subject`, `fact`, `message`). It
flags four things: a `sh:in` list that copies the `rdfs:label`s of the shape's
`seam:lifecycle` states (subject the shape, fact the `sh:path`, the message
names the state IRIs to use), a `sh:class` that points at a `sh:NodeShape`, a
`sh:NodeShape` with no `sh:targetClass` that is not itself a class (fact
`sh:targetClass`), and a `sh:path` IRI that no `rdf:Property`,
`owl:ObjectProperty`, `owl:DatatypeProperty` or `owl:AnnotationProperty`
declares (subject the path, fact `sh:path`; path expressions are skipped). The
checks are in `seams.review_check`, one function each. A review finding flags
the model; it never refuses it, and the function does not raise.

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

## Context assembly

`seams.context_for(model, task)` (backlog C3, `context.py`) gathers the model
facts the code of a service task depends on. `model` is a `Model` or a
`ModelGraph`; `task` is a BPMN id, CURIE or IRI. It returns a `Manifest`
(`task`, `items`, `context_hash`) whose `items` are `ContextItem`s (`kind`,
`ref`, `hash`, and the hashed `content`) sorted by (kind, ref). Each item is
narrowed to the facts the task uses:

- **task**: the task's own triples: what it reads, writes, fires and invokes.
- **shape**: each shape it reads or writes, with its type, label, comment and
  `sh:` triples down to its property shapes; its `seam:` joins are left out.
- **transition** and **state**: the transition it fires, with its from and to
  states.
- **process**: its process's type, label, comment, `seam:detailedBy` and
  `proc:correlationKey`, with the correlation parameter's type and label.
- **decision**: each decision an upstream business-rule task is
  `seam:decidedBy` whose `dec:processVariable` an incoming gateway condition
  reads, with its inputs and outputs.
- **container**: the container that `seam:executes` the process, narrowed to
  its type, label, `arch:technology` and the `deploy:key` of each binding,
  shared and per override. Binding values, secret references and file paths
  are never read.
- **bpmn**: the task's element, its incoming sequence flows (they carry the
  gateway conditions) and the gateways they come from.
- **dmn**: the `decision` element of each decision above.

A graph item's ref is its IRI and its hash covers its triples, blank nodes
canonicalised, serialised as N-Triples with the lines sorted. An XML item's
ref is the payload's model-relative path, `#` and the element id, and its hash
covers the element's exclusive C14N without its tail. Every hash is
`sha256:<hex>`. `context_hash` is sha256 over the items in (kind, ref) order,
each framed as `kind NUL ref NUL hash \n`, so the same model gives the same
hash and a changed fact changes its item's hash and the context hash. An
unknown task, a task that is not a `proc:ServiceTask` or a missing hop raises
`ResolutionError(subject, predicate, detail)`. `seams context` prints the
manifest as a review report.

The full API, views, SPARQL and model-hash reference is
[The seams library](../../docs/reference/seams-library.md) on the docs site.
