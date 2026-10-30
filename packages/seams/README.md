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
  `landmark_page()`, `task_iri(bpmn_id)`, `triggering_operation(process)`,
  `is_channel_started(process)`, `decision_binding(task)`,
  `implementing_container(operation)`, `lifecycle_for(shape)`, `policy(policy)`
  and `shape_graph()`. Each answers from graph facts and raises
  `ResolutionError` naming the subject and predicate when a hop is missing.
  `landmark_page()` and `task_iri()` are view-backed: `landmark_page()` is
  `model.interfaces.landmark()`, and `task_iri()` resolves through
  `model.processes` across any number of BPMN models (the graph element with
  that id, else the one BPMN file declaring it; an id in several models
  raises). The pages an app serves are `model.interfaces.served_pages()`.
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
model.interfaces.served_pages().iris() # (…expenses_page, …payouts_page)
payout = model.processes.for_bpmn_process("payout_process").only()
payout.channel_starts.only().channel   # Channel(iri=…payouts, …)
model.processes.element("choose_payout").only().decided_by.decision_id  # "payout_method"
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
- **`model.interfaces`** (IFML) has `models()`, `pages()`, `landmark()`
  and `served_pages()`.
  - `landmark()` is the one page with `ifml:isLandmark true`. Zero or
    several raise `ResolutionError(model, ifml:isLandmark, "expected one
    ifml:ViewContainer with ifml:isLandmark true, found [...]")`.
  - `served_pages()` lists the pages the generated app serves at their
    `ifml:path`: the landmark first, then by IRI every other page with a
    path that does not host a task form.
  - `InteractionModel` has `pages()` and `presented_by` (the `Container`
    that `seam:presents` it).
  - `Page` has `path`, `is_landmark`, `interaction_model`, `components()`
    (by `ifml:order`, then IRI) and `hosts_task_form` (a part it contains
    is the form a user task is `seam:completedOn`, ADR-0009).
  - `Component` has `kind` (`Form`, `Details`, `List`, `ViewComponent`),
    `page`, `reads`, `writes`, `parameters()` (labels), `events()`,
    `visible_when` (the lifecycle `State`s it renders in) and `completes`
    (the user tasks completed on the form).
  - `Event` has `trigger`, `component`, `triggers` (a `Process`),
    `submits_to` (an `Operation`), `navigates_to` (a `Page`) and `updates`
    (the components its navigation flows swap).
- **`model.processes`**: one `Process` per `proc:Process`, by IRI.
  - `Process` has `bpmn_model` (the model it is `seam:detailedBy`),
    `bpmn_path`, `bpmn_process_ids` (read from the BPMN XML),
    `executed_by`, `triggered_by`, `correlation_key`, `channel_starts`
    (each `MessageStart`: a message start event and the `Channel` it
    `seam:subscribesTo`), `elements()` and `element_iri(bpmn_id)`.
  - A `ProcessElement` is a task or event whose IRI is
    `<bpmn_model>#<bpmn id>`. It has `bpmn_id`, `kind` (`UserTask`,
    `ServiceTask`, ...), `process`, `invokes`, `reads`, `writes`, `fires`,
    `decided_by`, `completed_on` (a `Component`), `publishes_to` and
    `subscribes_to`.
  - `model.processes.for_bpmn_process(pid)` lists the processes whose BPMN
    file declares `bpmn:process` `pid`. `model.processes.element(bpmn_id)`
    lists the elements with that id across every BPMN model. Call
    `.only()` on either; an id used in two BPMN models raises.
  - Element ids are listed as the graph states them, not in flow order.
    S04 adds the flow order read from the BPMN XML.
- **`model.decisions`**: each `dec:Decision` a task is `seam:decidedBy`.
  It has `decision_id`, `dmn_model`, `dmn_path`, `inputs` and `outputs`
  (`InputBinding` and `OutputBinding`, as `ModelGraph.decision_binding`
  returns them), `reads` and `decides_for`. S04 adds the DMN table
  (hit policy and rules).

Single-valued edges (`accepts`, `lifecycle`, `shape`) return None when the
fact is absent. When the graph states the fact twice, they raise
`ResolutionError` naming the element and the predicate.

## SPARQL and canned questions

```python
model = seams.load("examples/chat-app/chat-app.trig")
model.sparql("SELECT ?p WHERE { ?p a ifml:ViewContainer }")  # [{"p": URIRef(…chat_page)}]
model.question("impact-of-node", node=":db01")              # [{"impacted": URIRef(…chat_api)}, …]
seams.question_names()  # ["c4-l1-rollup", "impact-of-node", …]
```

- `model.sparql(query, **bindings)` runs a read-only SELECT against
  `model.ds` with `seams.PREFIXES` declared (`seam`, `comm`, `dec`, `proc`,
  `state`, `hydra`, `odrl`, `deploy`, `ifml`, `arch`, `rdf`, `rdfs`, `sh`,
  `xsd`), so it needs no PREFIX lines. It returns a list of dict rows
  (variable name to rdflib term; unbound variables are absent), in the
  query's `ORDER BY` order when it has one, else sorted by the rows' string
  values.
  - Each keyword binds the variable of that name through `initBindings`,
    never by string interpolation. URIRefs and Literals pass through, a
    `str` containing `:` is expanded with `model.curie` (`":db01"`, a full
    IRI), and any other value becomes a Literal.
  - An update (`INSERT`, `DELETE`, `LOAD`, `DROP`, ...) raises `ValueError`
    before anything runs. So does a non-SELECT query; use
    `seams.sparql.sparql(model, query)` for the raw rdflib `Result` of an
    ASK or CONSTRUCT.
- `model.question(name, **bindings)` runs one of the canned questions in
  `docs/queries/`, which ship as package data (`seams/queries/*.rq`,
  byte-identical copies; `tests/test_seams_query.py` guards the drift).
  `seams.question_names()` lists them and `seams.load_question(name)`
  returns the text. An unknown name raises `KeyError` listing the
  available ones; a name is never turned into a path unchecked.

## The model hash

`"sha256:<hex>"`, where each payload is framed as relative path, NUL, decimal
length, bytes, sorted by relative path:

- **File:** the TriG bytes, then the framed payloads. This is byte-identical
  to the hash embedded in generated code (`model-hash:` headers).
- **Directory:** each TriG file framed the same way (its name, sorted by
  name), then the framed payloads.

Editing or renaming the model or any payload changes the hash.
