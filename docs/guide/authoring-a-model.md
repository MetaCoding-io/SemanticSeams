# Authoring a model

A SemanticSeams model is a TriG file: Turtle with named graphs. Each diagram is one named
graph, and the edges between diagrams live in one more. This page sets out the
conventions a model has to follow to be navigable in the viewer and to pass the
[seam shapes](/reference/shapes), then gives a small skeleton to start from.

The two worked examples are the best reference:
[`examples/chat-app/chat-app.trig`](../../examples/chat-app/chat-app.trig), which the
viewer loads, and [`examples/checkout.trig`](../../examples/checkout.trig).

## Graphs

[ADR-0001](/adr/0001-named-graph-partitioning) fixes the partitioning.

| Graph | Holds |
|---|---|
| `<urn:seams:graph:model:{id}>`, one per model | The layer-internal triples of one diagram: its elements, their labels, and the layer's own predicates (`arch:contains`, `ifml:hasEvent`, `state:from` and so on). |
| `<urn:seams:graph:seams>` | Every cross-layer edge: all `seam:` predicates except `seam:inModel`, including `seam:notation` and `seam:renderPayload`. |
| `<urn:seams:graph:manifest>` | Facts about the model's files: the vocabulary versions the model is written for ([below](#vocabulary-versions)). |

Keeping the seams in one graph makes "show me every cross-layer connection" a
single-graph query and lets the seams be audited on their own. The test suite enforces
it: a `seam:` predicate other than `seam:inModel` found in a model graph fails CI.

## Rules every model follows

1. **Every model is a `seam:Model`** with an `rdfs:label`, and has exactly one
   `seam:notation`: one of `seam:C4`, `seam:IFML`, `seam:BPMN`, `seam:DMN`,
   `seam:Statechart`, `seam:ShapeGraph` or `seam:Ontology`
   ([below](#an-ontology-model)). The notation picks the renderer.
   A `seam:ShapeGraph` model draws each `sh:NodeShape` member as a frame and each
   `sh:property` that has an `sh:path` as a card inside it, labelled from
   `sh:datatype`, `sh:minCount`/`sh:maxCount` and `sh:in`, ordered by `sh:order`.
   An `sh:class` or `sh:node` pointing at another node shape in the same model
   draws an edge.
2. **Every element states its model** with `seam:inModel`. Membership is data, so SPARQL
   can walk from a model to its elements; the viewer uses it to decide what to draw.
3. **BPMN and DMN models carry a `seam:renderPayload`**, a path to the native XML
   relative to the TriG file. The shapes reject a BPMN or DMN model without one.
4. **Only seam-participating BPMN and DMN elements get an IRI**, and that IRI is the
   model IRI with the element's XML `id` as its fragment, for example
   `<https://example.org/chat/chat_bpmn#persist_user_msg>`
   ([ADR-0002](/adr/0002-iri-identity-and-migration)). That is what lets a click in
   bpmn-js resolve to a node in the graph.
5. **Every element has an `rdfs:label`.** The viewer never shows a raw IRI where a label
   exists.
6. **Seams follow the shapes.** For example, `seam:triggers` starts at an
   `ifml:Event`, and `seam:detailedBy` ends at a `seam:Model`. The
   [shapes reference](/reference/shapes) lists every constraint, and the
   [seam predicates reference](/reference/seam-predicates) describes each predicate's
   intended source and target.
7. **Pages are complete enough to generate.** Every component of a page (an
   `ifml:ViewContainer` with an `ifml:path`) has exactly one `ifml:order`, and every
   `ifml:List` names the shape it shows with `seam:reads` and has exactly one
   `ifml:hasEvent`, the event its rows raise. The generators need all three, and the
   shapes flag a missing one in `seams check` and the viewer's SHACL health panel.
8. **Decisions agree with their data.** A DMN input's `typeRef` matches the
   `sh:datatype` of the shape property its `dec:fromPath` names (`number` for the
   numeric XSD types, `string`, `boolean`, `date`), and every variable a BPMN gateway
   condition reads is set upstream in the same process: a `dec:processVariable` or
   `dec:variable` of an upstream business-rule task's decision, or a field of the shape
   an upstream user task writes. `seams check` reports a break as a `decision` finding
   naming the decision or sequence flow and the fact.
9. **Each fact is stated once, and stated.** A `sh:in` list should not copy the
   `rdfs:label`s of a lifecycle's states (use the state IRIs), a `sh:class` names a
   class rather than a `sh:NodeShape`, each node shape has a `sh:targetClass`, and every
   `sh:path` IRI is declared a property (`rdf:Property`, `owl:ObjectProperty`,
   `owl:DatatypeProperty` or `owl:AnnotationProperty`). `seams check` prints a break as
   a `review` line and the viewer's health badge counts it as a warning; neither refuses
   the model, and `seams check` still exits 0 when review lines are all it finds.

::: tip Adding a seam predicate
A model only uses the seam predicates that already exist. If you extend
`ontology/seam.ttl` with a new one, give it a `seam:reveal` of `seam:Open`, `seam:Nest`
or `seam:Layer`, and add it to the `seamsh:RevealShape` target list in
`ontology/shapes/seam-shapes.ttl`. Open and nest predicates navigate on click
([ADR-0005](/adr/0005-navigation-resolution)). A predicate without a mode counts as
layer, so it only appears in the inspector. Then use it at least once in
`examples/checkout.trig`: the acceptance suite fails on a declared seam predicate that
no example exercises.
:::

### Saving a form without a process

A form can store what it submits before the model has any BPMN process. Give the
form `seam:writes S` and an `ifml:hasEvent` whose event `seam:submitsTo` a POST
`hydra:Operation` with `seam:acceptsShape S`, and do not give that event a
`seam:triggers`. The container that `seam:exposes` the operation is then routed, and
its generated handler calls `runtime.write`, which validates the input against `S` (a 422
naming the failing paths) and stores it as a new entity. If `S` has an `:id` property the
runtime fills it with the new entity's id first, so the form does not ask for it. The
entity starts in the lifecycle's initial state when `S` has a `seam:lifecycle`
(decision D026). Once the event `seam:triggers` a process, the
handler starts the process instead and the worker does the persisting.

### Where the data is stored

Three facts say where a model's data lives ([ADR-0011](/adr/0011-storage-resolution)):

- `seam:storedIn` goes from a `sh:NodeShape` to the store `arch:Container` that persists
  its instances.
- `deploy:storeKind` gives the store its kind, `deploy:PostgreSQL`, `deploy:SQLite` or
  `deploy:SemPKM` (see [A SemPKM store](#a-sempkm-store)). `arch:technology` stays free
  text for people.
- `deploy:connectsTo` on a `deploy:binding` names the store whose connection string the
  binding carries. The value still comes from `deploy:secretRef` and `deploy:secretName`
  (or `deploy:value` for a dev URL), and the runtime will read the environment variable
  named by the binding's `deploy:key`, whatever it is called.

```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/chat/> .

:MessageShape a sh:NodeShape ; rdfs:label "Message" ;
    seam:storedIn :message_db .

:message_db a arch:Container ; rdfs:label "Message Store" ;
    arch:technology "PostgreSQL" ;
    deploy:storeKind deploy:PostgreSQL .

:chat_api a arch:Container ; rdfs:label "Chat API" ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "DB_URL" ;
                         deploy:secretRef <https://secrets.example.org/chat/prod/db-url> ;
                         deploy:secretName "chat-prod-db-url" ;
                         deploy:connectsTo :message_db ] ] .
```

Process state follows the container that runs the process. Process instances, worker
rows and the process's entities live in the store that the container which
`seam:executes` the process connects to. So each shape the model writes must be
`seam:storedIn` that same store, and an executing container connects to at most one
store. A model that declares no store keeps embedded SQLite, with the file path taken
from `SEAMS_DB`.

The SHACL shapes check these facts. Only a shape is `seam:storedIn`, and only in one
`arch:Container`. Every store that a shape is stored in or a binding connects to has a
`deploy:storeKind`, and has only one, from the supported set. A binding connects to at
most one container.

The runtime reads the same facts when the model loads and opens that store
([ADR-0011](/adr/0011-storage-resolution)). For `deploy:PostgreSQL` it takes the
connection string from the environment variable the binding's `deploy:key` names, or
from the file `<key>_FILE` names, so the chat app reads `DB_URL` or `DB_URL_FILE`. For
`deploy:SQLite`, or no store at all, it uses the `SEAMS_DB` file. A fact that is missing
or wrong stops `Runtime.load` with a `ResolutionError` naming the subject and predicate:

| Problem | Subject | Predicate |
|---|---|---|
| a store with no `deploy:storeKind`, more than one, or one not supported | the store | `deploy:storeKind` |
| a PostgreSQL store no executing container connects to | the container | `deploy:connectsTo` |
| a container connecting to more than one store | the container | `deploy:connectsTo` |
| a written shape with no `seam:storedIn`, or stored elsewhere | the shape | `seam:storedIn` |
| a PostgreSQL store whose connection string is in neither `<key>` nor `<key>_FILE` | the connecting container | `deploy:connectsTo` |

The viewer's [model-health badge](/guide/the-viewer#the-parts-of-the-page) runs the
same checks before anything loads, so you see a store problem while you author the
model rather than when the runtime starts. Each row of the table above shows as a
violation. A store container that no shape is `seam:storedIn` shows as a warning:
this is how the chat app's old mismatch looks, where a PostgreSQL Message Store was
declared while the runtime kept writing to embedded SQLite. A model with no store gets
a note that the runtime keeps embedded SQLite.

`GET /healthz` reports the store the runtime opened as
`{"kind", "declared", "container", "override"}`. For a run without a database, such as
a test or a quick local check, `SEAMS_STORE_OVERRIDE=sqlite` keeps embedded SQLite at
`SEAMS_DB` whatever the model declares. The runtime logs a warning and `/healthz` reports
`"override": true`, so the substitution is never silent.

#### A SemPKM store

A store can also be a SemPKM instance, `deploy:storeKind deploy:SemPKM`
([ADR-0025](/adr/0025-sempkm-store)). It holds the domain data only: the entities of the
shapes `seam:storedIn` it, as RDF objects other apps can browse and query. Process
instances, worker rows and user tasks stay in the relational store the executing
container connects to, or in embedded SQLite at `SEAMS_DB` when it connects to none. So
an executing container connects to at most one relational store and at most one SemPKM
store, and each written shape is stored in one of the two. SemPKM is never the default.

The executing container reaches the SemPKM store through two bindings. One
`deploy:connectsTo` it and carries its base URL, which may be a plain `deploy:value`. The
other `deploy:authenticatesTo` it and carries the service token, so its value must be a
secret: a `deploy:secretRef` with its `deploy:secretName`, or a `deploy:secretFile` in a
development override. The predicate tells the two apart, never the key name.

```turtle
:ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
    sh:targetClass :Expense ;
    seam:storedIn :expense_store .

:expense_store a arch:Container ; rdfs:label "Expense Store" ;
    deploy:storeKind deploy:SemPKM .

:expense_api a arch:Container ; rdfs:label "Expense API" ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "SEMPKM_URL" ;
                         deploy:value "http://expense-store:8000" ;
                         deploy:connectsTo :expense_store ] ,
                       [ deploy:key "SEMPKM_TOKEN" ;
                         deploy:secretRef <https://secrets.example.org/expenses/prod/sempkm-token> ;
                         deploy:secretName "expenses-prod-sempkm-token" ;
                         deploy:authenticatesTo :expense_store ] ] .
```

SemPKM types each object it stores, so a shape stored in it needs a `sh:targetClass`, and
so does the `sh:node` shape of each nested field, which SemPKM keeps as its own object
joined to the parent by an edge. SemPKM bundles gist 14.0.0, so a model that names a
SemPKM store imports no other gistCore version. The SHACL shapes check that a token
binding takes its value from a secret and authenticates to a `deploy:SemPKM` store. The
model load adds these rows to the table above:

| Problem | Subject | Predicate |
|---|---|---|
| a SemPKM store no executing container connects to | the container | `deploy:connectsTo` |
| a SemPKM store with no token binding, more than one, or one whose value is not a secret | the container | `deploy:authenticatesTo` |
| a container connecting to two SemPKM stores, or two relational stores | the container | `deploy:connectsTo` |
| a shape stored in a SemPKM store with no `sh:targetClass` | the shape | `sh:targetClass` |
| a nested field of such a shape whose `sh:node` shape has no `sh:targetClass` | the nested shape | `sh:targetClass` |
| a model naming a SemPKM store that imports a gistCore other than 14.0.0 | the ontology | `owl:imports` |

The model-health badge shows a note when a SemPKM store has no relational store beside
it, saying that process state stays in embedded SQLite.

At run time the runtime reads the base URL and the token from the variables the two
bindings' keys name, or from `<key>_FILE`. SemPKM mints each entity's IRI, and the
entity keeps it as its id. A `/healthz` answer adds `"sempkm": {"kind": "SemPKM",
"container": ..., "reachable": ...}`. When SemPKM is unreachable, times out, fails or
refuses the token, a write answers 503 with a problem+json body naming the store
container. An answer without an IRI is a 502. Either way nothing is kept, so the
request can be retried. A refused token is logged with the scope the call needs
(`commands:execute` or `sparql:read`); the token itself never is.
`SEAMS_STORE_OVERRIDE=sqlite` keeps these entities in embedded SQLite for local runs.

### Environments and overrides

Each place the system runs is an `arch:Environment`: the chat app and expense chapters 8
and 9 declare `:development` and `:production`
([ADR-0015](/adr/0015-environments)). State a container's deploy facts once, for every
environment. Where one environment needs something different, add a `deploy:override`
that names the environment and carries only the facts that differ:

```turtle
:expense_api a arch:Container ; rdfs:label "Expense API" ;
    deploy:artifact [ a deploy:Artifact ;
                      deploy:reference "ghcr.io/metacoding-io/expense-api" ;
                      deploy:version "0.8.0" ] ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "DATABASE_URL" ;
                         deploy:secretRef <https://secrets.example.org/expenses/prod/database-url> ;
                         deploy:secretName "expenses-prod-database-url" ;
                         deploy:connectsTo :expense_db ] ] ;
    # Development builds the image from this checkout and reads the
    # connection string from a file. Same store, same key.
    deploy:override [ a deploy:Override ;
        deploy:environment :development ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "seams/expense-api" ;
                          deploy:version "local" ;
                          deploy:build [ a deploy:Build ;
                                         deploy:context "../../.." ;
                                         deploy:dockerfile "examples/expenses/chapter-09/generated/expense_api.Dockerfile" ] ] ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "DATABASE_URL" ;
                             deploy:secretFile "../../../docker/local-secrets/expense_database_url" ;
                             deploy:connectsTo :expense_db ] ] ] .

:development a arch:Environment ; rdfs:label "Development" .
:production  a arch:Environment ; rdfs:label "Production" ;
    arch:contains :app01 .
```

The rule for an environment:

- `deploy:artifact` and `deploy:replicas` in an override replace the shared fact whole.
- Bindings merge by `deploy:key`: an override binding replaces the shared binding with
  the same key, and the other shared bindings stay.
- A container with no override for the environment, or an override without the
  predicate, keeps the shared fact.

The SHACL shapes check that an override carries only `deploy:artifact`,
`deploy:configuration` and `deploy:replicas`; that a container has at most one override
per environment; that `deploy:environment` names an `arch:Environment`; that an
override binding with `deploy:connectsTo` names the same store as the shared binding
with its key (an environment never moves the data); and that a binding has
`deploy:secretFile` or `deploy:secretRef`, not both.

The compose generator writes one `compose.<local name>.yaml` per environment, sorted by
IRI, so a local run is `docker compose -f compose.development.yaml up`. An artifact with a
`deploy:build` becomes a compose `build:`, a `deploy:secretFile` becomes a compose file
secret, and `deploy:value` keeps an overridable `${KEY:-value}` default in development
only. Placement constraints appear only in the environment that `arch:contains` the
node. `deploy:proxies` on a code-free container (the chat UI and the employee portal are
Caddy) makes it a reverse proxy to the named container. Name the `seams.toml`
environments after the same local names, so `seams status --env development` reads the
stack that `compose.development.yaml` starts. Before `compose up`, `seams secrets --env production` checks that
every binding's secret file, `.env` key or docker secret exists without reading a value,
and `seams secrets --write-example` writes a `.env.example` with the keys to fill in
(see the [CLI reference](../reference/seams-cli.md)).

The serving container's build file is generated as well. List the `dockerfile` generator
in `seams.toml` and it writes `generated/<route module>.Dockerfile` (here
`expense_api.Dockerfile`) from the container's development `deploy:build`, with the app
directory, route module and seed data as literal paths and the model hash and container
IRI as image labels. Point the development `deploy:dockerfile` at that file, relative to
the context; compose passes no build args. If it is missing or names another file,
`seams generate` and `seams check` fail with a `GeneratorError` on `deploy:dockerfile`.
The image copies each uv workspace member's `pyproject.toml` (and its readme) so that
`uv sync --locked` sees the whole workspace; the generator reads the members from
`[tool.uv.workspace]` in the `pyproject.toml` at the root of the build context, and a
missing root or member `pyproject.toml` is a `GeneratorError` on `deploy:context`.

Production names images by `deploy:reference` and `deploy:version`. The gated
`.github/workflows/publish-images.yml` workflow builds each project's generated
Dockerfile, and the hand-written Dockerfile of any other container whose development
`deploy:artifact` has a `deploy:build` (the chat app's LLM gateway), and tags the image `<reference>:<version>` and `<reference>:sha-<model hash>`
(the first 12 hex digits). It runs only by hand (`workflow_dispatch`, which pushes only
when its `push` input is set) or on a `v*` tag, never on a push to main or a pull
request. `python -m seams_gen.images PROJECT...` prints the list it builds, as JSON.

The generated serving container runs one replica until the runtime can share state
(backlog A10). A larger `deploy:replicas` stays in the model, shows as a warning in the
viewer's model health, and as a comment in the generated file.

### Human tasks

A `proc:UserTask` is work a person does while the process waits. Give the task
`seam:completedOn F`, where `F` is the one `ifml:Form` the person completes it on
([ADR-0009](/adr/0009-human-tasks)). The rest follows from facts you already write:

- The **screen** is the `ifml:ViewContainer` that `ifml:contains F`.
- `F` has one `ifml:hasEvent` whose event `seam:submitsTo` the completion operation.
  That event has no `seam:triggers`: the process is already running.
- `F` `seam:writes` the task's output shape, the same shape the task `seam:writes`
  and the completion operation `seam:acceptsShape`.

The task's `seam:governedBy` policies say who may complete it. Each is evaluated with
the task IRI as the `odrl:target`, so the permission names the task, not an operation.
A task with no policy is open to any authenticated identity, and with no identity the
call fails with 401. `docs/queries/screens-to-finish-process.rq` lists, for a process,
each user task with its form, screen and policy. Chapter 4 of the expense tutorial,
[The process](/tutorials/expenses/04-process), builds one step by step (checkpoint
`examples/expenses/chapter-04/expenses.trig`, with no policy yet), and
`tests/fixtures/human_task/approval.trig` is a small complete example with a policy.

A person finds their open tasks at `GET /tasks`, the inbox `seams_runtime.host` serves
next to the landmark page. It lists only the tasks whose policies permit the request's
identity, each rendered with the form partial the htmx generator makes for `F`. The
person submits that form to the generated completion route, which checks the policies
again, validates the payload against the output shape and lets the process continue.
A task already completed answers 409. The identity comes from the `X-Forwarded-User`
header your proxy sets, and its roles from the comma-separated `X-Forwarded-Groups`
header. For a local run, set `SEAMS_DEV_USER` to the person you want to act as and
`SEAMS_DEV_ROLES` to their roles, for example `SEAMS_DEV_USER=bob SEAMS_DEV_ROLES=manager`.
Without an identity, the inbox answers 401. A permission whose `odrl:assignee` is an
`odrl:Party` admits an identity whose id or any role matches the party's IRI or local
name, so a role is modelled as an `odrl:Party`. A permission with no assignee, or an
`odrl:PartyCollection` assignee, admits any identity. A refused identity gets a 403
that names its roles and the policy. Chapter 7 of the expense tutorial,
[People and permissions](/tutorials/expenses/07-permissions), adds employee, manager
and finance roles this way (checkpoint `examples/expenses/chapter-07/expenses.trig`).

### Decisions and routing

A `proc:BusinessRuleTask` evaluates a DMN decision table. Give the task
`seam:decidedBy D` and `seam:reads S`, and give the `dec:Decision` `D` its
`dec:payloadElement` (the DMN decision id), a `dec:input` per table input (its
`dec:variable` is the input expression's text, its `dec:fromPath` the property of `S`
that fills it) and a `dec:output` per output column (`dec:variable` is the column's
label, `dec:processVariable` the name the rest of the process sees). An input whose
DMN `inputExpression` has `typeRef="number"` is compared as a number, although form
values arrive as strings. To route on the result, follow the task with a
`bpmn:exclusiveGateway` whose outgoing flows carry conditions on the process
variable, such as `route == "manager"`. The routing then lives in the DMN and BPMN
files, so changing a threshold changes no generated code. A table that matches no rule,
or an output that no condition accepts, fails the instance. Chapter 5 of the expense
tutorial, [The rules](/tutorials/expenses/05-rules), builds one (checkpoint
`examples/expenses/chapter-05/`).

### Operation implementation

A `proc:ServiceTask` `seam:invokes` an operation, and the operation says what serves it
with `seam:implementedBy` ([ADR-0012](/adr/0012-operation-implementation)). The
implementation node's `rdf:type` is its kind:

| Kind | What runs | Where the operation must be served |
|---|---|---|
| `comm:LLMCompletion` | a streamed chat completion from the serving container, at the operation's `comm:path` | in another container, reached through a `deploy:serviceOf` binding |
| `comm:PythonHandler` | a function in the handlers package, named by `comm:handler` | in-process: the exposing container `seam:executes` the process |
| `comm:HTTPEndpoint` | a JSON POST to the serving container, at the operation's `comm:path` | in another container, reached through a `deploy:serviceOf` binding |

```turtle
:completion_op a hydra:Operation ; rdfs:label "LLM Completion" ;
    seam:implementedBy :completion_impl .
:completion_impl a comm:LLMCompletion ; rdfs:label "LLM completion" .

:notify_manager_op a hydra:Operation ; rdfs:label "Notify Manager" ;
    seam:implementedBy :notify_manager_impl .
:notify_manager_impl a comm:PythonHandler ; rdfs:label "notify manager handler" ;
    comm:handler "notify.notify_manager" .
```

Put the `seam:implementedBy` edge in the seams graph. An operation has at most one
implementation, and the node has exactly one of the three kinds. A
`comm:PythonHandler`'s `comm:handler` is a dotted path of Python identifiers relative to
the handlers package (`handlers/` beside the model, or `SEAMS_HANDLERS`):
`"notify.notify_manager"` is the function `notify_manager` in `handlers/notify.py`. A
path with a slash, a leading dot or `..` is a violation, so a model cannot point at code
outside the package. An operation invoked across containers must declare its
implementation; an in-process operation with none is served by the runtime itself, as
the chat app's `:send_message_op` is. The shapes in `seam-shapes.ttl` check each of
these rules, and `ModelGraph.operation_implementation(op)` reads the implementation,
raising `ResolutionError` naming the fact when one is broken.

`Runtime.load` checks the rest before it serves a request: that the kind agrees with
where the operation is served, and that each handler imports and is callable. A handler
takes the accepted entity as a dict and returns a dict of the operation's
`seam:returnsShape` (or `None` when it has none); `async def` handlers are awaited. The
trace row of the invoking task records the kind as `implementation` (`"runtime"` when
the runtime serves the operation itself). The
[`seams_runtime` README](../../seams_runtime/README.md#operation-implementations)
lists every load and run-time error.

### Errors and error boundaries

An operation declares how it fails with `hydra:possibleStatus`
([ADR-0013](/adr/0013-error-shapes-and-boundaries)). Each `hydra:Status` that carries a
`comm:errorCode` is an error: its `hydra:statusCode` is the HTTP status and its
`seam:returnsShape` is the shape of the `application/problem+json` body, whose property
paths are the RFC 9457 members (`comm:type`, `comm:title`, `comm:status`,
`comm:detail`, `comm:instance`).

```turtle
:notify_manager_op seam:implementedBy :notify_manager_impl ;
    hydra:possibleStatus :notify_failed .
:notify_failed a hydra:Status ; rdfs:label "Notification failed" ;
    hydra:statusCode 502 ;
    comm:errorCode "notify-failed" ;
    seam:returnsShape :NotifyProblemShape .
```

A Python handler raises `OperationError("notify-failed", detail)`; an HTTP endpoint
answers with the declared status and a problem+json body. Generated FastAPI routes list
each error status as a problem+json response, and the generated problem handler turns a
raised `OperationError` into that status with a body checked against the shape.

To catch the error in a process, draw an error boundary event on the service task in
the BPMN, with an `errorEventDefinition` whose error has the same code, lift it as a
`proc:ErrorBoundaryEvent` and give it `seam:catches` the status in the seams graph:

```turtle
<https://example.org/expenses/approval_bpmn#notify_failed_boundary>
    seam:catches :notify_failed .
```

The boundary's `attachedToRef` and error code stay in the BPMN; `Runtime.load` checks
them against the graph. When the task raises a caught error, the worker runs the
boundary's flow instead of failing the instance, and the trace row records the code,
status and boundary. An error nothing catches fails the instance as before. Chapter 9
of the expense tutorial,
[When the notification fails](/tutorials/expenses/09-hand-written-code#when-the-notification-fails),
builds one, and the
[`seams_runtime` README](../../seams_runtime/README.md#error-boundaries) lists the
checks.

### Scenarios and examples

A model can also say what the app should do with a given input, in the `verify:`
vocabulary ([ADR-0014](/adr/0014-scenarios-and-derived-tests)). The `tests` generator
turns each statement into a test. All of it goes in the seams graph, next to the
policies.

- A **`verify:Scenario`** starts a process a UI event `seam:triggers`, as one
  `verify:actor`, with `verify:given` field values. Its `verify:step` list completes
  user tasks in order, each as a named party with the form it is submitted with. It
  ends with a `verify:expectState`, a `verify:expectEndEvent`, or both. The run takes in
  every process it starts through a channel, so it may expect a state or end event of
  one of those. A `verify:failure` (a `verify:operation` and one of its errors as
  `verify:status`) makes that operation fail whenever the run invokes it, so the run
  takes the error boundary that catches the status.
- A **`verify:DecisionExample`** gives a value for every `dec:input` of a decision and
  the `verify:expectOutput` it must return, named by the output's `dec:variable`.
- **`verify:validExample`** and **`verify:invalidExample`** point a `sh:NodeShape` at
  an untyped node it must accept or reject.

```turtle
:manager_approved a verify:Scenario ;
    verify:process :approval_process ;
    verify:actor :employee ;
    verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                 [ verify:field :amount ; verify:value 200.00 ] ,
                 [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
    verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#approve_expense> ;
                    verify:actor :manager ;
                    verify:given [ verify:field :decision ; verify:value "approved" ] ] ) ;
    verify:expectState :s_approved .

:routes_up_to_1000_to_manager a verify:DecisionExample ;
    verify:decision :approval_routing ;
    verify:given [ verify:field :amount ; verify:value 1000.00 ] ;
    verify:expectOutput [ dec:variable "Route" ; verify:value "manager" ] .
```

Scenarios, decision examples and example nodes are IRIs: the generated test's name is
their local name, so a failing test names the model fact that broke. Pick values at a
rule's limit (1000.00 for a `<= 1000` rule), so moving a threshold breaks a named
test. The shapes in `ontology/shapes/seam-shapes.ttl` check every statement (see
[Validate it](#validate-it)), for example that a decision example gives exactly the
decision's inputs. Chapter 9 of the expense tutorial,
[Say what it should do](/tutorials/expenses/09-hand-written-code#say-what-it-should-do),
adds nine scenarios, five decision examples and a pair of shape examples.

The `smoke` generator (backlog A9) uses the same examples against a running app: it
writes one test per `hydra:Operation`, filling the path and body from the first
`verify:validExample` of the operation's shapes, and checks the answer against
`seam:returnsShape`. An operation with no example to fill it with is skipped, so give
each accepted shape a valid example.

To get the tests, list the generator in the app's `seams.toml` and run
`seams generate`:

```toml
[[generators]]
name = "tests"
out = "generated/tests"
```

It writes `test_scenarios.py`, `test_decisions.py` and `test_shape_examples.py`, one
test per statement, named `test_scenario_manager_approved`,
`test_decision_routes_up_to_1000_to_manager` and so on. A scenario test runs the app
in-process on a temporary store and acts as each party. It also writes
`test_policies.py` from the ODRL policies you already have, with no extra statements:
for each permission, the assignee may reach the target, every other `odrl:Party` is
refused with 403 (`test_policy_manager_approval_policy_approve_expense_denies_finance`),
and a request with no identity gets 401. A target is reached the way a scenario
reaches it, so give each governed operation and user task a scenario. Run them with
`pytest generated/tests`. The [seams_gen README](../../seams_gen/README.md#tests-rendering-rules)
gives the rules.

To see what the scenarios leave out, run
[`seams coverage`](/reference/seams-cli#seams-coverage). It lists, by IRI, every
start-to-end BPMN path no scenario runs, every transition nothing `seam:fires` and every
permission with no deny test; the viewer asks the same three under **Questions** on a
BPMN view, a statechart and a policy. A scenario runs a path when its steps are exactly
the path's user tasks, in order, up to what it expects. A path through an error
boundary needs a scenario that fails the operation the boundary catches. A path of a
process started through a channel needs a scenario whose run starts it and that expects
something on that path. Put `coverage = ["paths"]` and
the two `docs/queries/coverage/` gates in `seams.toml` to make `seams check` fail on a
gap.

## An ontology model

The shapes say what one form, list or request carries. An ontology model says what the
things are, apart from any screen: the classes `Expense`, `Payment` and `Approval`, and
what each one is a kind of. A model can declare one, as a model graph whose `seam:Model`
is also the `owl:Ontology`, with `seam:notation seam:Ontology` in the seams graph
([ADR-0022](/adr/0022-ontology-notation)):

```trig
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix gist: <https://w3id.org/semanticarts/ns/ontology/gist/> .

<urn:seams:graph:model:expense_ontology> {
    :expense_ontology a seam:Model , owl:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .

    :Expense a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Expense" ;
        skos:definition "Money an employee spent on the company's behalf and asks to have reimbursed." ;
        seam:inModel :expense_ontology .
}

<urn:seams:graph:seams> {
    :expense_ontology seam:notation seam:Ontology .
}
```

- **One version IRI.** The ontology IRI is the model IRI and never changes; its one
  `owl:versionIRI` (the ontology IRI, a slash and `MAJOR.MINOR`) moves when the classes
  change. The shapes refuse an ontology model that is not an `owl:Ontology` or has no
  version IRI, or a class without an `rdfs:label` and `seam:inModel`.
- **Anchor classes in gist.** [gist](https://github.com/semanticarts/gist) is a small
  upper ontology; SemanticSeams vendors gistCore 14.0.0 in
  [`ontology/vendor/`](../../ontology/vendor/README.md).
  Make each class an `rdfs:subClassOf` a gist class (`gist:Transaction`,
  `gist:Determination`, `gist:Category`), and give it a `skos:definition`.
- **Import a version, offline.** `owl:imports` names gist's version IRI, never the bare
  `…/gistCore`. `seams.load` resolves each import against the files in
  `ontology/vendor/` without the network, and refuses a model whose import no file
  declares, or names another gist version:
  `cannot resolve <https://example.org/expenses/expense_ontology>: missing owl:imports
  (imports gistCore14.1.0; the vendored version is gistCore14.0.0)`. Vocabulary
  versions are not imported here; they belong in the [manifest graph](#vocabulary-versions).
- **The imported ontology stays out of the model.** gist is read to check the import and
  to label superclasses; it is not added to the model's graphs, so the model hash,
  generation and the runtime are the same as without it. A superclass declared neither
  in the ontology nor in gist (a mistyped `gist:Transation`) is a warning in
  `seams check` and the viewer's health panel.

The viewer draws an ontology model as a class view: a card per class with its
definition, an edge to each superclass, and gist's classes as read-only cards. The
health panel lists each import and whether it resolved
([the viewer](/guide/the-viewer)). Chapter 9 of the expense tutorial declares its
ontology this way, and its shapes target the classes, as the next section shows.

## Shapes that target classes

A shape says which class it describes, what each field is called on the wire, and where
a field's options come from ([ADR-0023](/adr/0023-shapes-target-classes)). The notation
needs `seam` 1.2 in the [manifest graph](#vocabulary-versions):

```trig
:ApprovalOutcome a owl:Class ; rdfs:subClassOf gist:Category ;
    rdfs:label "Approval outcome" ; seam:inModel :expense_ontology .
:outcome_approved a :ApprovalOutcome ; rdfs:label "approved" ; seam:inModel :expense_ontology .
:outcome_rejected a :ApprovalOutcome ; rdfs:label "rejected" ; seam:inModel :expense_ontology .

:ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ;
    sh:targetClass :Approval ;
    sh:property [ sh:path :decision ; sh:name "decision" ; sh:class :ApprovalOutcome ;
                  sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
    seam:inModel :expense_data .
```

- **`sh:targetClass`** names one class of an ontology model. The shapes allow at most
  one.
- **`sh:name`** is the field's name in forms, payloads, 422 results and handler stubs.
  Without it, the name is the path's local name, as before. Use it when the RDF property
  and the wire name differ: chapter 9's `PaymentShape` has `sh:path :paidOn ; sh:name
  "paid_on"`. Names match `^[A-Za-z_][A-Za-z0-9_]*$` and are unique within a shape.
- **Categories.** A field with `sh:class C`, where `C` is an `rdfs:subClassOf
  gist:Category`, or with an `sh:in` of IRIs, offers the members. Each member needs
  exactly one `rdfs:label`, and that label is the value a form sends and a payload
  carries. If the members are a lifecycle's states (type each state `a state:State ,
  :ExpenseState`), the options come in lifecycle order from the initial state;
  otherwise by IRI. A category with no members is refused. Do not copy the state labels
  into a string `sh:in`: a renamed or added state then reaches the form by itself.
- **Flattening.** An `sh:node` to a shape with exactly one free property, all others
  fixed by `sh:hasValue`, reads as one field: the free property's value under the outer
  field's name. A nested shape with two free properties is refused.

`seams check` and the viewer's health panel report each break with the shape, the field
and the predicate; the typed shape view raises the same fault as a `ResolutionError`
when a generator reads the field. Chapter 9's
generated forms, routes and tests are the same in this notation as with string lists;
only the model hash moves. `seams diff` reads fields the same way, by name and wire value,
so moving chapter 8's shapes to this notation is no change.

### The JSON-LD context of a shape

With a target class, a shape also says what its payloads mean as RDF. Add the `jsonld`
generator to `seams.toml`:

```toml
[[generators]]
name = "jsonld"
out = "generated/contexts"
```

It writes `<shape>.jsonld`, a JSON-LD 1.1 context, for each shape with a
`sh:targetClass` ([ADR-0024](/adr/0024-json-ld-context)), and the fastapi generator
serves the same text at `GET /contexts/<shape>.jsonld`. Each field's `sh:name` maps to
its `sh:path`, typed by its `sh:datatype`. A category field maps each member's label to
the member's IRI, so `"status": "submitted"` reads as `:status :s_submitted` while the
payload still carries the label. A flattened `sh:node` field and a reference to another
entity map to `null`: the context leaves them out rather than state a triple the shape
would reject. Every route that returns the shape sends
`Link: </contexts/ExpenseShape.jsonld>; rel="http://www.w3.org/ns/json-ld#context"`.

Shapes without a target class, such as request and problem shapes, get no context. A
category label must be usable as a JSON-LD term (not empty, not starting with `@`, no
`:`), and the target class's local name must not also be a field name; the generator
refuses either with a `GeneratorError` naming the member or the shape.

## Vocabulary versions

Each vocabulary in `ontology/` has a version IRI, its ontology IRI plus `MAJOR.MINOR`
(`<https://w3id.org/seams/seam/1.2>`). A model says which versions it is written for in
the manifest graph: the graph's own IRI is an `owl:Ontology` that `owl:imports` the
version IRI of each SemanticSeams vocabulary the model uses
([ADR-0021](/adr/0021-vocabulary-versions)):

```trig
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<urn:seams:graph:manifest> {
    <urn:seams:graph:manifest> a owl:Ontology ;
        owl:imports <https://w3id.org/seams/arch/1.0> ,
                    <https://w3id.org/seams/seam/1.2> .
}
```

Every example and tutorial checkpoint declares its versions this way, and a test checks
that each one imports exactly the vocabularies it uses. `dec:`, `hydra:`, `odrl:` and other
namespaces that have no file in `ontology/` are not declared. The rules:

- **No declaration means 1.0.** A model written before versions existed, or one that
  leaves a vocabulary out, targets that vocabulary's 1.0.
- **Declarations agree.** In a directory model several files may declare, but two
  versions of one vocabulary are an error, and so is a version that was never
  published (`seam/1.7`).
- **Same, newer, older.** Every tool loads through `seams.load`, which compares each
  declared version with the shipped one. The same major (and a minor no higher than the
  shipped one) loads as written. A newer version is refused:
  `targets seam 2.1; this tool supports seam up to 2.0`. An older major is migrated in
  memory with the SPARQL Update steps in `ontology/migrations/<vocabulary>/`, so the
  viewer, the generators and the runtime all see the current terms, and
  [`seams check`](/reference/seams-cli#seams-check) prints a `vocabulary-migrated`
  warning per step.
- **`seams migrate` writes the migration.** It applies the same steps to your files as
  one patch through the editor's write path, comments and layout kept, and rewrites the
  declaration to the shipped versions. Run it, review the diff and commit it; a second
  run does nothing. See [`seams migrate`](/reference/seams-cli#seams-migrate).
- **Deprecated terms warn.** A term marked `owl:deprecated` in its vocabulary has an
  `sh:Warning` shape: `seams check`, generation and the viewer's health panel list its
  uses as warnings and never fail on them. Replace the term before the major that
  removes it.

## A skeleton

Two models, an architecture with one container and the interface that container
presents, the seams graph joining them, and the manifest graph naming the vocabulary
versions:

```turtle
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix ifml: <https://w3id.org/seams/ifml#> .
@prefix :     <https://example.org/notes/> .

<urn:seams:graph:model:notes_architecture> {
    :notes_architecture a seam:Model ; rdfs:label "Notes Architecture" .

    :notes_system a arch:System ; rdfs:label "Notes" ;
        arch:contains :notes_ui ;
        seam:inModel :notes_architecture .

    :notes_ui a arch:Container ; rdfs:label "Notes Web Interface" ;
        seam:inModel :notes_architecture .
}

<urn:seams:graph:model:notes_ifml> {
    :notes_ifml a seam:Model , ifml:InteractionModel ; rdfs:label "Notes Interface" ;
        ifml:contains :notes_page .

    :notes_page a ifml:ViewContainer ; rdfs:label "Notes Page" ;
        seam:inModel :notes_ifml .
}

<urn:seams:graph:seams> {
    :notes_ui seam:presents :notes_ifml .

    :notes_architecture seam:notation seam:C4 .
    :notes_ifml seam:notation seam:IFML .
}

<urn:seams:graph:manifest> {
    <urn:seams:graph:manifest> a owl:Ontology ;
        owl:imports <https://w3id.org/seams/arch/1.0> ,
                    <https://w3id.org/seams/ifml/1.0> ,
                    <https://w3id.org/seams/seam/1.2> .
}
```

Adding a process means a third model graph with `seam:notation seam:BPMN` and a
`seam:renderPayload <notes_process.bpmn>`, an `ifml:Event` on the page, and a
`seam:triggers` edge from the event to the process in the seams graph. The chat app does
exactly that.

## Validate it

The shapes need the ontology files merged into the data, because `sh:class` checks
subclass closure from triples in the graph. This is what the test suite does for the
examples:

```python
from glob import glob
from pyshacl import validate
from rdflib import Dataset, Graph

data = Graph()
for path in glob("ontology/*.ttl"):
    data.parse(path, format="turtle")

model = Dataset()
model.parse("my-model.trig", format="trig")
for s, p, o, _ in model.quads((None, None, None, None)):
    data.add((s, p, o))

conforms, _, report = validate(data, shacl_graph="ontology/shapes/seam-shapes.ttl", inference="none")
print(report)
```

## Check its complexity

A model can be valid and still too small to need cross-layer tooling. The complexity
check measures that:

```sh
python -m seams_gen.complexity path/to/model.trig
```

It runs three SPARQL queries against the model and prints three numbers:

- **Models per notation**: how many `seam:Model` graphs use each notation. A notation
  with two or more models is one where a reader has to move between models of the same
  kind.
- **Most-reached elements**: the five elements reached by `seam:` edges from the most
  distinct models. A high count means one element ties many models together.
- **Cross-layer seam edges**: the number of `seam:` triples, leaving out the
  bookkeeping predicates `seam:inModel`, `seam:notation` and `seam:renderPayload`.

It then prints `PASS` or `FAIL`, with one line per failed threshold giving the actual
value and the required one.

| Measure | Threshold |
|---|---|
| Notations with 2+ models | at least 3 |
| Most models one element is reached from | at least 5 |
| Cross-layer seam edges | reported, not gated |

Edges are reported but not gated: one large model can have many edges and still be
fully visible by descent, so the edge count alone does not say the model needs more
than the viewer already gives you.

The chat app scores 0 / 3 / 60 and fails by design, since it is a one-model-per-layer
quick start. The expense-approval tutorial's final model,
`examples/expenses/chapter-08/expenses.trig`, passes with 4 / 6 / 115:

- BPMN, DMN, IFML and statechart each have two models: the approval and payout
  processes, the routing and payout-method decisions, the expense and finance-console
  interfaces, and the expense and payment lifecycles.
- `:ExpenseShape` is reached from six models: the expense interface, both processes,
  both decisions and the finance console.
- It has 115 cross-layer seam edges, four of them the storage facts of
  [ADR-0011](/adr/0011-storage-resolution) (`seam:storedIn` from three shapes and the
  store's `seam:deployedTo`).

The exit code is 0 on pass, 1 on fail, and 2 when the file is missing, unreadable or not
valid TriG (the message goes to stderr). The check loads only the TriG, not the ontology
files. The source queries are in `docs/queries/complexity/` in the repository.

## Checking a change with seams diff

Before you change a model that already has stored data or callers, compare the old
version with the new one:

```sh
seams diff old/expenses.trig expenses.trig
```

Both arguments are a TriG file or a directory of them; a git worktree or a copy of the
previous commit works as the old side. Each change to a SHACL shape or an operation
contract (`seam:acceptsShape`, `seam:returnsShape`) prints as
`<verdict> <kind> <subject> <detail>`. Going from expenses chapter 8 to chapter 9 adds the
notification shapes and operations, all compatible:

```
compatible shape-added :NotificationShape -
compatible shape-added :NotifyProblemShape -
compatible operation-added :notify_failed -
compatible operation-added :notify_manager_op -
```

The command exits 1, with `seams diff: N breaking, M compatible` on stderr, when any change
is breaking: a removed shape, property or operation, a new required property
(`sh:minCount` above 0), a changed `sh:datatype` or `sh:class`, a tighter count, or an
operation that now accepts or returns another shape. Adding an optional property, a shape
or an operation, or loosening a count, is compatible. To rename a shape without breaking
it, give it the new IRI and state `:NewShape owl:sameAs :OldShape` in the new model
([ADR-0002](/adr/0002-iri-identity-and-migration)). `--json` prints the same changes with
full IRIs and their `data`/`contract` scopes, for a CI step or a release note. The full
rules are in the [seams CLI reference](/reference/seams-cli#seams-diff).

For release notes, `seams plan` writes the same changes as Markdown, breaking ones first,
followed by the elements each layer adds and removes. Either side can be a git ref and a
path, so you do not need a copy of the old model:

```sh
seams plan main:expenses.trig expenses.trig --output CHANGES.md
```

It exits like `seams diff`. See the [seams CLI reference](/reference/seams-cli#seams-plan).

## What a task depends on: seams context

Before you write or review the code behind a service task, list the model facts that
code depends on. For Send Now in expenses chapter 9:

```sh
seams context send_now --project examples/expenses/chapter-09
```

```
task https://example.org/expenses/payout_bpmn#send_now
bpmn payout.bpmn#flow_now sha256:58e4ac37…
bpmn payout.bpmn#method_gateway sha256:b69e98b9…
bpmn payout.bpmn#send_now sha256:f734f7d6…
container https://example.org/expenses/expense_api sha256:254b0a1d…
decision https://example.org/expenses/payout_method sha256:3cf9c21d…
dmn payout.dmn#payout_method sha256:82801fbd…
process https://example.org/expenses/payout_process sha256:2fe4d2bc…
shape https://example.org/expenses/PaymentShape sha256:a10f90b3…
state https://example.org/expenses/s_scheduled sha256:f13d65dd…
state https://example.org/expenses/s_sent sha256:fa182a32…
task https://example.org/expenses/payout_bpmn#send_now sha256:309cbe92…
transition https://example.org/expenses/t_send sha256:2ba638b6…
context sha256:39ee1a2f…
```

(Hashes are shortened here; the command prints them in full.) Each line is one fact the
task uses: the task itself, the shape it writes, the transition it fires with its from
and to states, its process and correlation key, the payout decision whose output the
incoming gateway condition reads, the container that runs it, narrowed to its
technology and binding names, and the BPMN and DMN fragments. Binding values are never
read. Every item is hashed canonically, so saving the same model again changes nothing,
while changing a fact, say a `sh:datatype` on `PaymentShape`, changes that item's hash
and the context hash. Keep the output beside a hand-written implementation and compare
it after a model change to see which facts moved. `--json` prints the same as JSON. See
the [seams CLI reference](/reference/seams-cli#seams-context).

## Copilot suggestions (optional)

A gateway whose outgoing conditions compute over a form field, such as
`amount <= 2000`, keeps a business rule in the BPMN file. `seams suggest` asks an LLM
command to move that rule into a DMN decision, checks the change, and keeps it pending
until you accept it ([ADR-0028](/adr/0028-copilot-suggestions)). The provider is the
same command `seams propose` uses, `[propose] provider` in `seams.toml` or `--provider`:

```sh
seams suggest --project my-project --provider "my-llm --model some-model"
```

The LLM only proposes a JSON answer: the gateway, a decision id and name, its inputs,
its rules and one condition per outgoing flow. Deterministic code turns the answer into
the change: `dec:Decision` facts shaped like the model's existing decision, a
business-rule task before the gateway, and conditions over the decision's output
variable. The change is written into a scratch copy, which must pass the seam shapes,
the decision checks and every generator. A passing suggestion prints its id, one
`changed <file>` line per file, `validated pass` and `generated pass`, and is stored in
`.seams/suggestions/<id>/` (gitignored). A rejected one prints
`rejected <kind> <subject> <predicate> <detail>` and stores nothing.

Review it before accepting. Each changed file has a unified diff beside
`suggestion.json`:

```sh
seams suggest --project my-project --list
cat my-project/.seams/suggestions/<id>/*.diff
seams suggest --project my-project --accept <id>
```

`--accept` takes the id or a unique prefix of it. It refuses a suggestion made for an
older model (ask again), checks the change once more and writes it through `seams_edit`,
the TriG files and the payloads together or not at all. Nothing in the model changes
before that step, and `seams suggest` never runs in CI. The output lines and exit codes
are in the [seams CLI reference](/reference/seams-cli#seams-suggest).

## View it

The viewer loads one model, chosen by `SEAMS_MODEL`. Keep the BPMN and DMN files your
`seam:renderPayload` values name beside the TriG file, then start the viewer:

```sh
SEAMS_MODEL=path/to/model.trig python3 -m uvicorn viewer.app:app --port 8000
```

`SEAMS_MODEL` may also name a directory: its TriG files load together as one model, and
payload paths resolve against the directory.

The root view is your model's C4 `seam:Model`. If the file has none, or more than one,
set `SEAMS_VIEWER_ROOT` to the IRI the viewer should open at. See
[Getting started](/guide/getting-started#open-the-viewer) for a tour of the views.

To edit the model within a domain's own terms, attach it to a domain profile with one
triple in the seams graph, and keep the profile in `profiles/<name>/profile.ttl` beside
the model:

```turtle
:my_architecture seam:conformsTo <https://example.org/profiles/expense> .
```

The viewer's edit mode then offers only the profile's classes under its labels, runs its
shapes in health and previews only its generators. A profile never changes what
`seams generate` builds. See [Domain profiles](/guide/the-viewer#domain-profiles) and
[ADR-0018](/adr/0018-domain-profiles).
