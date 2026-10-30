# semanticseams

The `seams` library: import name `seams`, distribution name `semanticseams`.

It reads Semantic Seams models without executing them. Its only dependencies
are rdflib and lxml; importing it never pulls in SpiffWorkflow, FastAPI or
`seams_runtime`. The package is strictly type-checked (`uv run pyright`).

## API

```python
import seams

model = seams.load("examples/chat-app/chat-app.trig")
model.hash        # "sha256:..."
model.payloads()  # [("chat_process.bpmn", Path(...)), ("routing.dmn", Path(...))]
```

- `seams.load(path=None) -> Model` loads a model.
  - A **file** is parsed as TriG; payloads resolve against its directory.
  - A **directory** loads every `*.trig` directly inside it (not recursive,
    sorted by file name) into one Dataset; payloads resolve against the
    directory. A directory with no `*.trig` raises `FileNotFoundError`.
  - Without a path, the `SEAMS_MODEL` environment variable names the model.
    An explicit path always wins; an unset or empty variable raises
    `ValueError`.
- `Model` exposes `path`, `base_dir`, `files` (the TriG files loaded), `ds`
  (the merged rdflib `Dataset`, `default_union=True`), `subject`, `curie(term)`,
  `label(iri)`, `payload_path(model_iri)` and:
  - `hash`: computed once per instance.
  - `payloads()`: `(relative posix path, absolute path)` for every
    `seam:renderPayload`, sorted by relative path. A missing payload raises
    `ResolutionError`.
- `seams.model_hash(path)` and `seams.payload_path(payload_iri, base_dir)` are
  module-level helpers.
- Errors: `SeamsError` (base; `http_status`, `to_dict()`) and
  `ResolutionError(subject, predicate, detail="")`, also a `LookupError`,
  raised when a graph hop is missing.
- Namespaces: `SEAM`, `COMM`, `DEC`, `PROC`, `STATE`, `HYDRA`, `ODRL`,
  `DEPLOY`, `IFML`, `ARCH`, plus `local_name(iri)`.
- `ModelGraph(path, dataset=None)` (and `ModelGraph.load(path)`) is a `Model`
  plus the one-of-each resolvers the runtime and the generators share, such as
  `landmark_page()`, `secondary_pages()`, `triggering_operation(process)`,
  `is_channel_started(process)`, `decision_binding(task)`,
  `implementing_container(operation)`, `lifecycle_for(shape)`, `policy(policy)`
  and `shape_graph()`. Each answers from graph facts and raises
  `ResolutionError` naming the subject and predicate when a hop is missing.
  Results are frozen dataclasses (`Transition`, `DecisionBinding`, `Container`,
  `OperationPath`, `ChannelBinding`, `ChannelStart`, `ProcessFacts`,
  `Lifecycle`, `PolicyFacts` and the rest), and `dmn_decision_ids`,
  `dmn_input_types` and `bpmn_start_event_ids` read the payload XML.
  `ModelGraph` is **transitional**: the views below supersede it.
  `seams_runtime` re-exports it unchanged. Three of its result types share a
  name with a view class (`Container`, `Lifecycle`, `Transition`): import
  those from `seams.graph` (or `seams_runtime.model`); the top-level names
  are the view classes.

## Views

The views read every model of a layer at once. Several BPMN, IFML or
statechart models in one graph are the normal case, not an error.

```python
model = seams.load("examples/expenses/chapter-08")
api = model.architecture.containers().by_iri(":expense_api")
api.executes.iris()                    # (…approval_process, …payout_process)
op = model.operations.by_iri(":submit_expense_op")
op.exposed_by.only() is api            # True: one object per IRI and model
op.governed_by.only().permissions      # (Permission(target=…, action=odrl:use, …),)
model.lifecycles.only()                # ResolutionError: two state machines
```

- **`Many[T]`** is an immutable tuple, always built in a documented order
  (by `str(iri)` unless the view says otherwise). It remembers the
  `subject` and `predicate` it was read from: the model and `rdf:type` for
  a layer's list, the element and the edge predicate for an edge.
  - `.only()` returns the single item. It raises
    `ResolutionError(subject, predicate, "expected exactly one, found [...]")`
    for zero items or more than one.
  - `.by_iri(iri_or_curie)` returns the item with that IRI, and raises
    `ResolutionError` when it is absent.
  - `.where(pred)` filters the items and keeps the same subject and
    predicate. `.iris()` returns the IRIs.
- **`Element`** is the frozen dataclass every view item extends. Its fields
  are `iri`, `label` (rdfs:label, else the local name) and `model` (the
  `seam:Model` it is `seam:inModel`, or None). It also has these properties:
  - `raw`: the rdflib node.
  - `edges`: every outgoing `seam:` triple as `(predicate, object)`, sorted.
  - `graph`: the Dataset.

  Elements compare and hash by type and IRI, and assigning to one raises
  `FrozenInstanceError`. A per-model registry (`model.views`) builds each
  view once and interns each element, so a cross-layer edge and the layer's
  own list return the same object. An edge to a node of a type no view
  covers yet returns a plain `Element`.
- **`model.architecture`** has `systems()`, `containers()`,
  `deployment_nodes()` and `environments()`.
  - `System.containers`.
  - `Container` has `technology`, `exposes` and `consumes` (a
    `Many[Operation | Channel]`), `executes`, `deployed_to`, `depends_on`
    and `systems`. `service_bindings` is a read-only mapping from
    `deploy:key` to `deploy:serviceOf`, sorted by key.
  - `DeploymentNode` has `hosts` and `environments`; `Environment` has
    `nodes`.
- **`model.operations`** and **`model.channels`**:
  - `Operation` has `method`, `path`, `accepts`, `returns`, `media_kind`,
    `request_media_type`, `exposed_by`, `consumed_by` and `governed_by`.
    `path` is a `PathTemplate` (`template`, `mappings` sorted by variable,
    `variables`). `accepts` and `returns` are a `Shape` or None.
  - `Channel` has `transport`, `event_name`, `path`, `accepts`,
    `exposed_by`, `consumed_by`, `published_by` and `subscribed_by`.
- **`model.shapes`**: a `Shape` has these members:
  - `fields()`: a `Many[Field]` sorted by `sh:order` (fields without one
    last), then by path IRI. A `Field` has `path`, `name`, `label`,
    `datatype`, `min_count`, `max_count`, `order` and `required`.
  - `lifecycle`, `read_by` and `written_by`.
- **`model.lifecycles`**: one `Lifecycle` per `state:StateMachine`.
  `model.lifecycles.transitions()` lists the transitions of all of them.
  - `Lifecycle` has `initial`, `states()`, `finals()`, `transitions()` and
    `shape`.
  - `Transition` has `from_state`, `to_state` (`State` objects), `trigger`,
    `lifecycle` and `fired_by`.
- **`model.policies`**: a `Policy` has `permissions` and `governs`.
  `permissions` holds `Permission` tuples sorted as `ModelGraph.policy`
  sorts them. `governs` lists the operations and tasks that are
  `seam:governedBy` the policy.

Single-valued edges (`accepts`, `lifecycle`, `shape`) return None when the
fact is absent. When the graph states the fact twice, they raise
`ResolutionError` naming the element and the predicate.

## The model hash

`"sha256:<hex>"`, where each payload is framed as relative path, NUL, decimal
length, bytes, sorted by relative path:

- **File:** the TriG bytes, then the framed payloads. This is byte-identical
  to the hash embedded in generated code (`model-hash:` headers).
- **Directory:** each TriG file framed the same way (its name, sorted by
  name), then the framed payloads.

Editing or renaming the model or any payload changes the hash.
