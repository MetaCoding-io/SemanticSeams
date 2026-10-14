# SemanticSeams: Project Outline

*A zoomable, multi-notation application graph. A [MetaCoding](https://metacoding.io) project.*

*Name: **SemanticSeams** (settled — the load-bearing novelty is the cross-notation edges). Namespace: `https://w3id.org/seams/` (w3id registration pending).*

*Status: concept / research phase — July 2026*

---

## 1. Problem statement

Programming remains stuck in text-only representations. UML failed socially; the OMG process stack (BPMN/DMN/CMMN) is excellent but captive to mostly-proprietary platforms; visual programming keeps dying on diff/merge, version control, and the expressiveness cliff. Meanwhile the tools that *do* visualize software each cover exactly one layer:

- C4 tools (Structurizr, IcePanel, LikeC4) give zoomable architecture — but the bottom of the zoom is a link to a repo.
- BPMN modelers (bpmn-js, Camunda, Flowable) give executable process diagrams — disconnected from the UI and data they orchestrate.
- IFML (WebRatio, IFMLEdit.org) models UI interaction — with metamodel hooks for referencing external action and data models that nobody ever wired up.
- SHACL/ontology tooling models data — in its own silo.

**Nobody has unified these into a single navigable, multi-notation model space.** Every piece exists; the whole does not.

## 2. Core idea

**One RDF graph is the single source of truth. Diagrams are views, not artifacts.**

Every element at every layer — a C4 container, an IFML view component, a BPMN task, a DMN decision, a SHACL shape — is a resource with an IRI. Cross-layer relationships are triples. "Zooming in" is not a UI gimmick: it is a graph traversal that switches rendering strategy based on the type of the node you clicked.

The canonical descent:

1. **C4 context/container view** (navigation shell) — click into `client web interface`
2. **IFML surface** — pages, view components, events, interaction flows — click an event's action
3. **BPMN diagram** — the business logic behind that action — click a business-rule task or a data object
4. **DMN decision table** or **RDF/SHACL data-model view** — the decision logic or the shape of the data itself

This is *projectional editing over a knowledge graph*, not "visual programming." Text serializations (Turtle) and diagrams are co-equal projections, which is what defuses the classic visual-programming killers: Turtle diffs are tractable, and the model graph is event-sourced (SemPKM-style), so history and merge live at the model level, not the pixel level.

The second killer feature, arguably bigger than the zoom: **cross-layer SPARQL queries** that no MDE toolchain ever delivered.

- "Show me every UI event that eventually writes to this shape."
- "Show me every UI event reachable by role X that eventually writes to this shape." (compliance/security review)
- "Which BPMN tasks are allowed to fire this state transition?"
- "What breaks if db02 goes away?" (deployment impact analysis / drift detection)

## 3. The five pillars (plus annotations)

Computation decomposes into five concerns, each with a home notation and vocabulary. Authorization is a true fifth pillar — in real systems it is smeared across the other four as an afterthought, which is why it is the perennial source of bugs and audit pain.

| Pillar | Notation(s) | Vocabulary / tooling |
|---|---|---|
| **Process** | BPMN 2.0, plus DMN for decision logic and Harel statecharts (SCXML-ish) for entity lifecycles | Executable via open engines (see §5); rendered via bpmn-js / dmn-js |
| **Data** | RDF / OWL / SHACL | Shapes do triple duty: validation, form generation (SHACL 1.2 UI / DASH), API contracts |
| **Architecture** | C4-style hierarchy plus deployment topology (containers → deployment nodes → environments) | Custom vocabulary; C4 deployment diagrams as prior art; TOSCA if heavyweight needs emerge |
| *Deployment (verb side of architecture)* | `deploy:` module: artifact, configuration (secrets by IRI), resources, replicas, startup ordering, placement policy | Nothing here launches anything: compose files / Ansible inventories / k8s manifests are **generated projections** of the graph. `seam:deployedTo` becomes the resolved output of a placement policy. As-designed vs. as-deployed named graphs make **drift detection a SPARQL diff with semantics** — monitoring (e.g. Zabbix host/VM mapping) feeds the as-deployed graph |
| **Communication** | Hydra (JSON-LD hypermedia) for request/response; channels-as-resources for async | Async events are named-graph payloads whose shape is a SHACL shape on a channel resource (avoids importing the AsyncAPI/JSON-schema world) |
| **UI** | IFML | Rendered to htmx; custom editor on diagram-js |
| *Authorization (5th pillar)* | Policy over resources | WebACL / ACP (Solid), ODRL for rich policy (permissions, prohibitions, duties) |

**Annotation vocabularies** (not layers): non-functional requirements (SLOs, latency budgets attached to components and flows), test specifications (examples attached to decisions and shapes; DMN has built-in test cases), provenance/versioning (nearly free via event-sourced model changes + named graphs; enables as-designed vs. as-deployed snapshots).

**Execution boundary (decided):** the BPMN engine never learns about seams. It executes native XML; a single *generic graph-literate worker* registered for all service tasks resolves each task's fragment IRI, follows `seam:invokes` to the operation and its SHACL contracts, dispatches, validates, and enforces `seam:governedBy` policies at the one choke point every cross-component call transits. The XML stays vendor-extension-free and engine-portable; the graph doubles as the runtime service registry.

**Deliberately deferred:** CMMN (least adopted of the OMG trio; Flowable covers it if case management ever becomes necessary).

### Why these notations map cleanly to the stack

- **IFML → htmx is unusually clean.** ViewContainer = page/fragment; ViewComponent = rendered partial; Event + InteractionFlow = `hx-get`/`hx-post` with `hx-target`/`hx-swap`; parameter bindings = htmx params/vals. IFML was designed pre-SPA around server-rendered state transitions — precisely the model htmx returned to. A 2013 OMG standard and a 2020s hypermedia revival describing the same machine.
- **htmx philosophy of APIs** maps to two API kinds in the graph: operations returning UI fragments (hypermedia) and operations returning pure data (JSON-LD). Both are `comm:` resources; the distinction is a property, not a schema divide.
- **HTTP QUERY is now RFC 10008** (Proposed Standard, June 2026): safe, idempotent, body-carrying — the natural transport for SPARQL and saved graph queries. The stack bet paid off.
- **DMN decisions are pure functions** from inputs to outputs; keeping them out of BPMN gateways is the point of the standard. Decision tables are the single most business-legible artifact in the entire stack. A BPMN business-rule task links to a decision; the decision's inputs/outputs link to SHACL shapes.
- **Statecharts fill BPMN's gap.** BPMN models processes *acting on* things; the lifecycle of a thing (order: draft → submitted → fulfilled → cancelled) is a state machine. Attaching one to a shape also solves IFML's conditional-rendering problem: "render this view when the entity is in state S" becomes a graph edge instead of an if-statement in a template.

## 4. Architecture method as a pluggable profile (Löwy / IDesign)

The bridging ontology stays **method-neutral**. Juval Löwy's IDesign method (*Righting Software*) becomes the first pluggable *profile*:

- His component taxonomy — Clients, Managers, Engines, ResourceAccess, Resources, Utilities — is a typed vocabulary for architecture-layer components.
- His interaction rules — clients don't call engines directly; managers don't call managers except via queued calls; closed layering — are **SHACL shapes applied to the model graph itself**. The same validation machinery that checks business data checks the architecture. "We follow the IDesign method" becomes a machine-verifiable claim.
- Someone else could ship a hexagonal-architecture or DDD profile the same way: a component taxonomy plus a shapes library.

**Project design as projection (later version).** Löwy's argument is that the project network *derives from* the architecture: activities, dependencies, staffing, critical path. Activities are nodes, dependencies edges, duration/effort literals; critical path is a longest-path computation over that subgraph; a Gantt chart is one more projection of the graph, exactly like a BPMN diagram or C4 view. Architecture changes visibly ripple into the schedule. Costs nothing now to reserve a `plan:` module linking activities to the components and shapes they realize.

## 5. Landscape summary (research findings, July 2026)

**BESSER** (Cabot group, Luxembourg; open source): Python-native B-UML metamodel, browser modeling editor whose diagramming engine ships as a reusable npm package (`@besser/wme`), GrapesJS-based no-code GUI editor generating full web apps (docker-compose: backend + frontend + db volume). Direction: "vibe modeling" — LLMs generate models, humans validate, deterministic generators produce code. *Models as the asset*, arrived at from the AI direction. Study for: generator architecture, embeddable editor.

**IFML / WebRatio / IFMLEdit**: OMG standard (2013), WebML heritage. Spec includes MOF metamodel, UML profile, visual syntax, XMI interchange — lifting to RDF/OWL is mechanical. Crucially, the metamodel has *built-in* extension points referencing external action (BPMN) and data models. WebRatio is proprietary and drifting toward enterprise BPM; IFMLEdit.org is the open web editor (generates NodeJS/Cordova/Flutter; maps IFML to Petri nets for executable semantics — study this).

**C4 tooling**: Structurizr (reference implementation, open DSL, one model → many diagrams, interactive rendering); IcePanel/Carbide (commercial interactive zoom); **LikeC4** (open source, MIT: DSL + React viewer with click-to-drill navigation, and — key — user-definable hierarchy rather than C4's fixed four levels). None switch *notation* at the bottom of the zoom. That is this project's novelty.

**BPMN engines post-Camunda-7-EOL**: **Operaton** (community fork of Camunda 7, committed to community ownership), EximeeBPMS (another C7 fork), **Flowable** CE (Apache 2.0; full BPMN + DMN + CMMN), **SpiffWorkflow** (pure-Python BPMN 2.0; SpiffArena adds a web platform). Modeling toolkit: **bpmn-js / dmn-js / diagram-js** from bpmn.io — diagram-js is notation-agnostic and is the plausible base for a custom IFML editor.

**RDF-native app platforms**: **LinkedDataHub** (AtomGraph, Apache 2.0) — applications *are* RDF data, managed via a generic HTTP API, behavior defined by the Linked Data Templates ontology, any SPARQL 1.1 backend. Closest existing thing to "the program is a graph"; the XSLT 3.0/Java stack may not be to taste but the architecture is required reading.

**SHACL-driven UI went standards-track**: W3C **SHACL 1.2 UI** spec (widget selection, label resolution, grouping/ordering; functional forms from plain shapes, richer forms with annotations), building on DASH conventions; RDF/JS SHACL-UI task force standardizing component interfaces; implementations like HERITRACE (shapes drive widget selection; YAML layer for presentation concerns outside SHACL's scope). Fairly described as XForms' spiritual descendant, and it pairs naturally with JSON-LD.

**HTTP QUERY**: RFC 10008, published June 2026, IETF Proposed Standard.

## 6. Proposed stack

- **Model store**: RDF triplestore (Fuseki or similar), event-sourced model changes, named graphs per diagram/model for provenance and as-designed vs. as-deployed snapshots.
- **Navigation shell**: web app; renderer dispatch on `rdf:type` + `seam:notation` of the focused node. bpmn-js for BPMN, dmn-js for decision tables, custom diagram-js surface for IFML, graph visualization for shapes/ontology, C4-style view for architecture.
- **Frontend**: htmx. Generated UIs *and* the tool's own UI.
- **APIs**: JSON-LD everywhere; Hydra for hypermedia description; QUERY (RFC 10008) for reads; SHACL shapes as contracts.
- **Execution**: interpret or generate. SpiffWorkflow (Python) for interpretation; BESSER-style deterministic generators as the alternative path. SHACL 1.2 UI / DASH for form generation.
- **Validation**: SHACL on business data *and* on the model graph (profiles, §4).

## 7. v1 scope

**A read-only, navigable, multi-layer model browser over a hand-authored RDF model of a real system.** No editing, no generation, no execution. The notation-switching descent alone is novel; nothing on the market does it.

Dogfood candidates: the GLMX internal tooling stack (nexus/Authentik/Pulp) or SemPKM itself.

Then, in order: editing (embed the modelers read-write), SHACL-driven form generation, IFML→htmx generation, BPMN interpretation, profiles (IDesign first), project-design projection (Gantt).

---

## 8. Sketch: the seam edges (bridging ontology)

> **Historical sketch.** This section predates the shipped ontologies and is kept
> for the design rationale. The namespaces (`example.org/ns/...`, the `ui:`
> prefix), the "~15 predicates" count, and some domain notes are stale — the
> authoritative, tested vocabulary lives in [`ontology/seam.ttl`](../ontology/seam.ttl)
> (`https://w3id.org/seams/seam#`, currently 25 predicates, including
> `seam:inModel` for membership and `seam:executes` for container→process),
> with constraints in [`ontology/shapes/seam-shapes.ttl`](../ontology/shapes/seam-shapes.ttl).

The bridging ontology's only job is to define the **seams** — the cross-layer predicates everything hangs off. Inside each layer we lean on existing vocabularies (SHACL, ODRL, Hydra, SCXML-ish states). The seams are where the novelty and the value live; the layers are mostly solved.

Namespace conventions used below (illustrative):

```turtle
@prefix seam:  <https://example.org/ns/seam#> .        # the bridging ontology
@prefix arch:  <https://example.org/ns/arch#> .        # C4-ish architecture layer
@prefix ui:    <https://example.org/ns/ifml#> .        # IFML lift
@prefix proc:  <https://example.org/ns/bpmn#> .        # BPMN lift (or reuse an existing BPMN ontology)
@prefix dec:   <https://example.org/ns/dmn#> .         # DMN lift
@prefix state: <https://example.org/ns/state#> .       # statechart vocabulary
@prefix comm:  <https://example.org/ns/comm#> .        # channels; pairs with hydra:
@prefix plan:  <https://example.org/ns/plan#> .        # project-design module (reserved)
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix odrl:  <http://www.w3.org/ns/odrl/2/> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
```

### 8.1 The navigation backbone

```turtle
# Any element can be detailed by a model in another (or the same) notation.
# This single edge drives the zoom.
seam:detailedBy a rdf:Property ;
    rdfs:comment "Focus element -> model that elaborates it. Traversing this edge is 'zooming in'." .

seam:Model a rdfs:Class .
seam:notation a rdf:Property ;
    rdfs:domain seam:Model ;
    rdfs:comment "Tells the shell which renderer to mount." .

# Controlled values (extensible):
seam:C4 seam:IFML seam:BPMN seam:DMN seam:Statechart seam:ShapeGraph
```

The shell's algorithm is one query: given the focused node, follow `seam:detailedBy`, read `seam:notation`, mount the renderer, scope it to the target model's named graph.

### 8.2 Architecture ↔ everything

```turtle
seam:presents        # arch:Component -> ui model (an IFML Model). "This component's face."
seam:exposes         # arch:Container -> comm:Operation | comm:Channel
seam:consumes        # arch:Container -> comm:Operation | comm:Channel (the dependency edge)
seam:deployedTo      # arch:Container -> arch:DeploymentNode ("what breaks if db02 goes away")
```

### 8.3 UI ↔ process

```turtle
seam:triggers        # ui:Event -> proc:Process | dec:Decision
                     # IFML's own Action-reference extension point, made concrete.
seam:visibleWhen     # ui:ViewComponent -> state:State
                     # conditional rendering as a graph edge, not template logic
```

### 8.4 Process ↔ decisions, communication, data

```turtle
seam:decidedBy       # proc:BusinessRuleTask -> dec:Decision
seam:invokes         # proc:ServiceTask -> comm:Operation
seam:publishesTo     # proc:MessageEvent (throw) -> comm:Channel
seam:subscribesTo    # proc:MessageEvent (catch) -> comm:Channel
seam:reads           # proc:Task | ui:ViewComponent | dec:Decision -> sh:NodeShape
seam:writes          # proc:Task | ui:Event -> sh:NodeShape
```

`seam:reads`/`seam:writes` are the workhorses of impact analysis: property paths over
`(seam:triggers / seam:decidedBy / seam:invokes)* / seam:writes` answer "what can touch this data."

### 8.5 Data ↔ lifecycle

```turtle
seam:lifecycle       # sh:NodeShape -> state:StateMachine
seam:fires           # proc:Task -> state:Transition
                     # inverse view answers: "which tasks may move an Order out of 'submitted'?"
```

### 8.6 Communication contracts

```turtle
seam:acceptsShape    # comm:Operation | comm:Channel -> sh:NodeShape  (request / event payload)
seam:returnsShape    # comm:Operation -> sh:NodeShape                 (response payload)
seam:mediaKind       # comm:Operation -> seam:UIFragment | seam:Data
                     # the htmx two-kinds-of-API distinction as a property, not a schema divide
```

Hydra supplies the operation/link machinery within the layer; the seam predicates only bind operations to shapes and channels to processes.

### 8.7 Authorization (cross-cutting by design)

```turtle
seam:governedBy      # ANY element -> odrl:Policy (or an ACP/WebACL resource)
                     # attachable to a ui:Event, a proc:Task, a comm:Operation,
                     # a sh:NodeShape, or a state:Transition alike
```

One predicate, deliberately broad domain: authorization earns pillar status precisely because it attaches everywhere. The compliance query composes it with the backbone: *events reachable by role X that eventually write shape Y*.

### 8.8 Profiles and planning (reserved seams)

```turtle
seam:conformsTo      # seam:Model | arch element -> seam:Profile
                     # a Profile bundles a component taxonomy + a SHACL shapes library
                     # (IDesign profile: Manager/Engine/ResourceAccess types + interaction-rule shapes)

seam:realizes        # plan:Activity -> ANY element
                     # the single edge the Gantt projection needs; everything else derives
```

### 8.9 Worked micro-example (checkout)

```turtle
:web_ui        a arch:Component ; seam:presents :checkout_ifml ; seam:deployedTo :web01 .
:checkout_ifml a seam:Model ; seam:notation seam:IFML .

:submit_order  a ui:Event ; seam:triggers :order_process ; seam:governedBy :customer_policy .
:order_process a proc:Process ; seam:detailedBy :order_bpmn .
:order_bpmn    a seam:Model ; seam:notation seam:BPMN .

:price_task    a proc:BusinessRuleTask ; seam:decidedBy :pricing_decision .
:persist_task  a proc:Task ; seam:writes :OrderShape ; seam:fires :order_submit_transition .

:OrderShape    a sh:NodeShape ; seam:lifecycle :order_lifecycle ;
               seam:detailedBy :order_shape_graph .
:order_shape_graph a seam:Model ; seam:notation seam:ShapeGraph .
```

Clicking `web_ui` → IFML surface. Clicking `submit_order`'s flow → BPMN. Clicking `price_task` → DMN table. Clicking `persist_task`'s data object → the RDF shape graph. Four notations, one traversal, ~15 predicates.

### Design rules for the seams

1. **Few and generic beats many and precise.** ~15 predicates. Precision lives in the layer vocabularies and in SHACL shapes over the seams themselves (e.g., a shape asserting `seam:decidedBy` only connects business-rule tasks to decisions).
2. **Every seam predicate must earn a query.** If no cross-layer question needs it, it doesn't belong in `seam:`.
3. **Reuse before minting.** Hydra, ODRL, SHACL, and (where a decent BPMN/IFML ontology lift exists) prior art inside layers; `seam:` only where layers meet.
4. **The backbone (`seam:detailedBy` + `seam:notation`) must stay notation-agnostic** so new renderers (Gantt, deployment maps) plug in without ontology changes.
