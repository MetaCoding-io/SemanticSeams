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
`shapes`, `operations`, `channels`, `lifecycles`, `policies`) read every model
of a layer at once. `model.sparql` and `model.question` run read-only SPARQL.

`ModelGraph.store_plan()` resolves which store the runtime keeps its rows in
(ADR-0011) from `deploy:storeKind`, `deploy:connectsTo` and `seam:storedIn`,
returning a `StorePlan` (`kind`, `store`, `container`, `key`, `declared`). A
model that declares no store gets embedded SQLite (`declared=False`). A
missing or duplicated store kind, an unsupported kind, a PostgreSQL store
with no connecting binding, a written shape not stored in the store, or more
than one store raises `ResolutionError` naming the subject and predicate.

The full API, views, SPARQL and model-hash reference is
[The seams library](../../docs/reference/seams-library.md) on the docs site.
