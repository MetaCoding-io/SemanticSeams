# The seams library

`seams` is the Python library that reads Semantic Seams models without executing
them. Its import name is `seams`; its distribution name is `semanticseams`
([packages/seams/pyproject.toml](../../packages/seams/pyproject.toml)). Its only
dependencies are rdflib and lxml, so importing it never pulls in SpiffWorkflow,
FastAPI or `seams_runtime`, and the package is strictly type-checked
(`uv run pyright`).

v1 is a uv workspace member only and is not published to PyPI (D031). Install
it with the rest of the workspace:

```sh
uv sync --all-packages
```

The generators in `seams_gen`, the viewer and `seams_runtime` all read models
through it.

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
  - `compact(term)`: the inverse of `curie`. It returns `prefix:local` for
    the longest bound namespace the IRI starts with (ties broken by prefix),
    where `local` is the last fragment or segment, so a BPMN element
    `<…approval_bpmn#approve_expense>` shows as `:approve_expense`. An IRI no
    namespace matches comes back as `<iri>`. `compact(term, whole=True)`
    keeps everything after the namespace (`:approval_bpmn#approve_expense`),
    which `curie` expands back to the same IRI.
  - `label(iri, strict=True)`: the single `rdfs:label`, where the default
    falls back to the local name. None or several raise
    `ResolutionError(iri, rdfs:label)` ("expected exactly one, found none"),
    the rule the generators use.
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
  `DEPLOY`, `IFML`, `ARCH`, `DASH` (`dash:` editors), plus `local_name(iri)`.
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
  `ModelGraph` is a **transitional facade over the views**: every resolver
  reads through `model.processes`, `operations`, `channels`, `lifecycles`,
  `policies`, `interfaces`, `architecture`, `shapes` and `decisions` (only
  `shape_graph()` copies triples, for SHACL). `task_element(task)`,
  `shape(iri)`, `page(iri)` and `component(iri)` hand back the interned view
  element, and `has_lifecycle(shape)`, `governing_policies(element)` and
  `rendered_components()` answer the runtime's yes/no and list questions;
  `Lifecycle.transitions` lists the machine's state:hasTransition IRIs.
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
- **View collections.** `model.architecture` is an `Architecture` and
  `model.interfaces` an `Interfaces`: objects with the list methods below.
  `model.processes` is a `Processes` and `model.lifecycles` a `Lifecycles`,
  both a `Many` with extra lookups. `model.operations`, `model.channels`,
  `model.shapes`, `model.decisions` and `model.policies` are plain `Many`s.
- **`model.architecture`** has `systems()`, `containers()`,
  `deployment_nodes()` and `environments()`.
  - `System.containers` (the `arch:Container`s it `arch:contains`).
  - `Container` has `technology`, `exposes` and `consumes` (a
    `Many[Operation | Channel]`), `executes`, `deployed_to`, `depends_on`
    (C4 `arch:dependsOn`) and `systems`. `service_bindings` is a read-only
    mapping from `deploy:key` to `deploy:serviceOf`, sorted by key.
  - Its `deploy:` facts are frozen dataclasses: `artifact` (an `Artifact`
    with `reference` and `version`, or None), `ports` (`Port`:
    `container_port`, `published_port`), `volumes` (`Volume`: `name`,
    `mount_path`), `healthcheck` (`Healthcheck`: `probe`, `interval`, or
    None), `replicas`, `deploy_depends_on` (start order) and `bindings`
    (`Binding`: `key`, `kinds`, `value`, `secret_ref`, `secret_name`,
    `service_of`, by key). They sit on blank nodes, so a missing or
    duplicated value raises `ResolutionError(container, predicate)`.
  - `DeploymentNode` has `hosts` and `environments`; `Environment` has
    `nodes`.
- **`model.operations`** and **`model.channels`**:
  - `Operation` has `method`, `path`, `accepts`, `returns`, `media_kind`,
    `request_media_type`, `exposed_by`, `consumed_by`, `governed_by`,
    `renders` (the components it `seam:rendersComponent`) and
    `submitted_by` (the events that `seam:submitsTo` it).
    `path` is a `PathTemplate` (`template`, `mappings`: `PathMapping`s
    with `variable`, `property` and `property_iri`, sorted by variable,
    `variables`). `accepts` and `returns` are a `Shape` or None.
  - `Channel` has `transport`, `event_name`, `path`, `accepts`,
    `exposed_by`, `consumed_by`, `published_by` and `subscribed_by`.
- **`model.shapes`**: a `Shape` has these members:
  - `fields()`: a `Many[Field]` sorted by `sh:order` (fields without one
    last), then by path IRI. A `Field` has `path`, `name`, `label`,
    `datatype`, `min_count`, `max_count`, `order`, `required`,
    `max_length` (`sh:maxLength`), `editor` (`dash:editor`, e.g.
    `DASH.TextAreaEditor`) and `options` (the `sh:in` values, in list
    order).
  - `lifecycle`, `read_by` and `written_by`.
- **`model.lifecycles`**: one `Lifecycle` per `state:StateMachine`.
  `model.lifecycles.transitions()` lists the transitions of all of them.
  - `Lifecycle` has `initial`, `states()`, `finals()`, `transitions()`,
    `shape` and `shapes` (every shape naming it, by IRI).
  - `Transition` has `from_state`, `to_state` (`State` objects),
    `from_states`, `trigger`, `lifecycle`, `lifecycles` (every machine that
    `state:hasTransition` it) and `fired_by`.
- **`model.policies`**: a `Policy` has `permissions` and `governs`.
  `permissions` holds `Permission` tuples sorted as `ModelGraph.policy`
  sorts them. `governs` lists the operations and tasks that are
  `seam:governedBy` the policy.
- **`model.interfaces`** (IFML) has `models()`, `pages()`, `components()`
  (every element typed with an IFML component class), `events()`, `flows()`,
  `landmark()` and `served_pages()`. Each list covers every IFML model;
  `.where(lambda e: e.in_model(":my_ifml"))` keeps one model's members
  (`Element.in_model(model)` is true for each `seam:inModel` it states).
  - `landmark()` is the one page with `ifml:isLandmark true`. Zero or
    several raise `ResolutionError(model, ifml:isLandmark, "expected one
    ifml:ViewContainer with ifml:isLandmark true, found [...]")`.
  - `served_pages()` lists the pages the generated app serves at their
    `ifml:path`: the landmark first, then by IRI every other page with a
    path that does not host a task form.
  - `InteractionModel` has `pages()` and `presented_by` (the `Container`
    that `seam:presents` it).
  - `Page` has `path`, `title` (`ifml:title`), `is_landmark`, `is_xor`,
    `is_default` (`ifml:isXOR`/`ifml:isDefault` true), `pages()` (the nested
    pages it contains), `parents` (the pages that contain it), `visible_when`
    (lifecycle `State`s, as on `Component`), `interaction_model`, `components()` (by `ifml:order`, then IRI; a
    non-integer order raises `ResolutionError(component, ifml:order)`) and `hosts_task_form` (a part it contains
    is the form a user task is `seam:completedOn`, ADR-0009).
  - `Component` has `kind` (`Form`, `Details`, `List`, `ViewComponent`),
    `types` (its concrete classes among `ifml:List`, `ifml:Details` and
    `ifml:Form`, in that order), `order`, `page`, `screens` (every page that
    contains it), `reads`, `writes`, `parameters()` (labels),
    `parameter_bindings`, `events()`, `data_flows`, `rendered_by` (the
    operations that render it), `visible_when` (the lifecycle `State`s it
    renders in) and `completes` (the user tasks completed on the form).
    `parameter_bindings` holds one `Parameter` (`iri`, `label`, `bound_to`:
    the `sh:path` it is `ifml:boundTo`, or None) per parameter, by IRI.
  - `Event` has `trigger`, `component` (exactly one owner, as a
    `Component`), `owners` (every element that `ifml:hasEvent` it, typed as
    the graph says), `triggers` (a `Process`),
    `triggers_all` (every process it triggers), `governed_by` (a
    `Many[Policy]`), `submits_to` (an `Operation`), `flows`, `navigates_to`
    (a `Page`) and `updates` (the components its navigation flows swap).
  - `Flow` is an `ifml:NavigationFlow` or `ifml:DataFlow`. It has `kind`,
    `source` and `target` (exactly one each), `sources`, `targets`, `swap`
    (`ifml:Replace`, `ifml:Append` or `ifml:Prepend`; a missing one raises
    `ResolutionError(flow, ifml:swap, "expected exactly one, found none")`)
    and `binds`: one `ParameterBinding` (`source`, `target` parameter IRIs)
    per `ifml:binds`, sorted. `event.flows.where(lambda f: f.kind ==
    IFML.NavigationFlow).only()` raises `ResolutionError(event,
    ifml:source)` when there is none or several.
- **`model.processes`**: one `Process` per `proc:Process`, by IRI.
  - `Process` has `bpmn_model` (the model it is `seam:detailedBy`),
    `bpmn_models` (all of them, by IRI),
    `bpmn_path`, `bpmn_process_ids` (read from the BPMN XML),
    `executed_by`, `triggered_by`, `triggering_operations` (the operations
    its triggering events `seam:submitsTo`), `invoked_operations` (what it
    or an element of its BPMN model `seam:invokes`), `correlation_key`,
    `correlation_parameter`, `correlation_parameters`, `channel_starts`
    (each `MessageStart`: a message start event and the `Channel` it
    `seam:subscribesTo`), `elements()` and `element_iri(bpmn_id)`.
  - A `ProcessElement` is a task or event whose IRI is
    `<bpmn_model>#<bpmn id>`. It has `bpmn_id`, `kind` (`UserTask`,
    `ServiceTask`, ...), `types` (its `proc:` classes), `process`, `invokes`, `reads`, `writes`, `fires`,
    `decided_by`, `completed_on` (a `Component`), `publishes_to` and
    `subscribes_to`.
  - `model.processes.for_bpmn_process(pid)` lists the processes whose BPMN
    file declares `bpmn:process` `pid`. `model.processes.element(bpmn_id)`
    lists the elements with that id across every BPMN model. Call
    `.only()` on either; an id used in two BPMN models raises.
  - `elements()` lists what the graph states, by IRI. `nodes()` walks the
    BPMN XML in flow order instead: every flow node of every `bpmn:process`
    in `bpmn_path` (processes in document order), lifted into the graph or
    not, so start and end events and gateways are included. `tasks()` and
    `gateways()` filter that walk and `lanes()` lists the `Lane`s (`id`,
    `name`, `node_ids`). Each is built once.
  - A `FlowNode` has `iri` (`element_iri(bpmn_id)`), `node` (the
    `seams.bpmn.BpmnNode`), `process`, `element` (the same `ProcessElement`
    object as `elements()`, or None when the graph does not type the IRI),
    `bpmn_id`, `tag` (`userTask`, `exclusiveGateway`, `startEvent`, ...),
    `name`, `lane`, `incoming`, `outgoing` and `paths` (`SequenceFlow`s
    with `id`, `name`, `source`, `target` and `condition`), `kind`, the
    element's edges (`invokes`, `decided_by`, `completed_on`, `fires`;
    `reads`, `writes`, `publishes_to`, `subscribes_to`), which are None or
    empty when unlifted, and `starts_from` (the `Channel` of
    `channel_starts` whose event it is).

  ```python
  approval = model.processes.for_bpmn_process("approval_process").only()
  for gw in approval.gateways():
      print(gw.bpmn_id, [(f.name, f.target, f.condition) for f in gw.paths])
  # route_gateway [("auto", "record_approval", 'route == "auto"'), …]
  ```

  `seams.bpmn` (`parse_bpmn`) and `seams.dmn` (`parse_dmn`,
  `decision_table`) are the lxml-only parsers behind these joins; they
  read any BPMN or DMN namespace version and raise `ResolutionError` naming
  the element and attribute (`bpmn:targetRef`, `dmn:decisionTable`, ...)
  that failed.
- **`model.decisions`**: each `dec:Decision` a task is `seam:decidedBy`.
  It has `decision_id`, `dmn_model`, `dmn_path`, `inputs` and `outputs`
  (`InputBinding` and `OutputBinding`, as `ModelGraph.decision_binding`
  returns them), `reads` and `decides_for`.
  - `Decision.table` is the DMN decision table, read from `dmn_path` with
    lxml by `seams.dmn` (parsed once per file): a `DecisionTable` with
    `decision_id`, `decision_name`, `table_id`, `hit_policy` (`UNIQUE` when
    the file states none), `aggregation`, `inputs` (`TableInput`: `id`,
    `label`, `expression`, `type_ref`), `outputs` (`TableOutput`: `id`,
    `label`, `name`, `type_ref`) and `rules` (`Rule`: `id`, `inputs` and
    `outputs` as the entry texts, `description`), all in document order.
  - A decision without a `decisionTable`, or a rule whose entries do not
    match the table's inputs or outputs, raises `ResolutionError` naming
    `dmn:decisionTable`, `dmn:inputEntry` or `dmn:outputEntry`.

  ```python
  table = model.processes.element("route_expense").only().decided_by.table
  [(r.id, r.inputs, r.outputs) for r in table.rules]  # [("rule_auto", ("<= 100",), ('"auto"',)), …]
  ```

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

## Errors

Every error the library raises for a model problem is a `SeamsError`.

- `SeamsError` is the base class. It carries `http_status` (500) and
  `to_dict()`, a JSON-safe dict with `type`, `message` and `http_status`
  plus the error's own fields, so a route handler can return it as a
  response body.
- `ResolutionError(subject, predicate, detail="")` is raised when a graph hop
  is missing, duplicated or points nowhere. It is also a `LookupError`. Its
  `subject` and `predicate` are the IRI strings it is about, and its message
  reads `cannot resolve <subject>: missing <predicate> (<detail>)`:

  ```python
  try:
      model.lifecycles.only()
  except seams.ResolutionError as err:
      err.predicate  # "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
      err.detail     # "expected exactly one, found [...]"
  ```

Loading itself raises the standard errors: `FileNotFoundError` for a missing
file or a directory without `*.trig`, and `ValueError` when no path is given
and `SEAMS_MODEL` is unset or empty.
