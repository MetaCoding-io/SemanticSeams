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

Keeping the seams in one graph makes "show me every cross-layer connection" a
single-graph query and lets the seams be audited on their own. The test suite enforces
it: a `seam:` predicate other than `seam:inModel` found in a model graph fails CI.

## Rules every model follows

1. **Every model is a `seam:Model`** with an `rdfs:label`, and has exactly one
   `seam:notation`: one of `seam:C4`, `seam:IFML`, `seam:BPMN`, `seam:DMN`,
   `seam:Statechart` or `seam:ShapeGraph`. The notation picks the renderer.
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
- `deploy:storeKind` gives the store its kind, `deploy:PostgreSQL` or `deploy:SQLite`.
  `arch:technology` stays free text for people.
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
  ends with a `verify:expectState`, a `verify:expectEndEvent`, or both.
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
adds three scenarios, five decision examples and a pair of shape examples.

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

## A skeleton

Two models, an architecture with one container and the interface that container
presents, and the seams graph joining them:

```turtle
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
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
