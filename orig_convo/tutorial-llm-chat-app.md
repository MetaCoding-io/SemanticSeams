# Tutorial spec: Build an LLM Chat App from One Model

*Status: specification. This document is written as the tutorial will read, with
[CAPABILITY] annotations marking what must exist for each step to work. The
capability list at the end IS the development roadmap: milestones are defined
as "tutorial works through step N." The finished model
(`examples/chat-app/`) replaces checkout.ttl as the product acceptance test.*

**What you build:** a chat application — conversation list, message composer,
LLM-backed responses — modeled entirely as a graph. At the end you have
deployable artifacts (`docker compose up` and chat) plus a clickable,
queryable map of your own app.

**Why a chat app:** it is the app every builder makes first; it is small but
genuinely exercises all five pillars (screens, workflow, an external API,
data with a lifecycle, deployment with a secret); and the external LLM
provider demonstrates system boundaries honestly.

---

## Step 1 — Model your data (Data contract)

Write two shapes: `Conversation` (title, created) and `Message` (role,
content, timestamp, status, belongs-to-conversation). Plain SHACL, ~30 lines
of Turtle, presented in the tutorial as "this is your schema file."

> [CAPABILITY: viewer renders a ShapeGraph view from SHACL — nodes, properties,
> datatypes, cardinalities. Requires the membership fix (seam:inModel or graph
> scoping) so the view knows what belongs to the data model.]

## Step 2 — Give Message a lifecycle

A message isn't just data; it moves: `pending → streaming → complete`, with
`failed` reachable from the first two. Ten triples.

> [CAPABILITY: statechart renderer (shared node-link renderer + elkjs).]

## Step 3 — Model your screens (Screens & interactions)

One chat page: a conversation List, a message-history List, a composer Form
with a **Send** event. The tutorial explains the IFML-inspired vocabulary in
product words only.

> [CAPABILITY: IFML renderer — boxes-in-boxes, events as border circles,
> flows as arrows. The single custom renderer build.]

## Step 4 — Model the workflow

**Send** triggers `handle_message`: receive input → persist user message
(writes Message, fires `pending`) → call the LLM (service task invoking the
provider operation) → persist assistant message (fires `complete`; on error,
`failed`) → return the updated history fragment. Authored in any BPMN
modeler; element IDs match the fragment IRIs in the index file the tutorial
provides.

> [CAPABILITY: bpmn-js NavigatedViewer embedding; payload fetch endpoint with
> defined resolution semantics (ADR-0003); index↔payload lint so a renamed
> element ID fails loudly, not silently.]

## Step 5 — Model the communication

Two of your own operations — `POST /messages` returning a **UI fragment**,
`QUERY /conversations/{id}` returning **data** (JSON-LD) — plus the external
provider: an `arch:System` you don't own, exposing one operation whose
accepted/returned shapes you declare. The htmx "two kinds of API" idea made
concrete; the provider's API key appears only as a `deploy:secretRef`.

> [CAPABILITY: none new — exercises comm/Hydra vocabulary and the
> mediaKind semantics clarified in the review triage.]

## Step 6 — Model architecture and deployment

Three containers: `chat_app` (FastAPI + htmx), `store` (triplestore),
and the external provider system. Artifact references, one secret binding,
replicas, startup ordering, placement into a `local` environment.

> [CAPABILITY: architecture renderer (shared node-link renderer, different
> styling); deploy: vocabulary as shipped.]

## Step 7 — Browse and ask

The payoff for comprehension: full descent (architecture → chat page → Send →
workflow → data contract) with breadcrumbs, plus three canned queries as
buttons, not SPARQL: **"What writes Message?"**, **"What breaks if the
provider is down?"**, **"What can move a message out of streaming?"**
Model-health panel shows warnings (a service task with no operation, an
operation with no shapes, a payload that doesn't resolve).

> [CAPABILITY: describe-node inspector with defined JSON-LD contract
> (ADR-0004); navigation resolution rule for multi-hop paths like
> event → process → model (ADR-0005); canned query catalog (docs/queries/*.rq);
> model-health shapes (ontology/shapes/) surfaced in the UI.]

## Step 8 — Generate and run

The payoff for building: three generators walk the graph and emit
(1) htmx page templates from the interaction model, (2) a FastAPI scaffold
whose handlers validate against the declared shapes and dispatch the
workflow's service calls via the generic graph-literate worker, (3) a
docker-compose file from the deploy: module — secrets referenced, never
inlined. `docker compose up`. Chat with it. Then change the model (add a
"regenerate response" event) and regenerate.

> [CAPABILITY: the three generators. Largest single work item after the
> viewer; scoped tightly to what the tutorial app needs — no general-purpose
> codegen ambitions in v1. BPMN interpretation stays out: the generated
> scaffold hard-wires the tutorial's linear flow; a real engine arrives
> post-v1.]

---

## Capability → milestone mapping

- **M1 — The descent** (steps 1–4 browsable, 6 viewable): membership edge +
  named-graph partitioning, shared node-link renderer, IFML renderer,
  bpmn-js embedding, payload resolution, breadcrumbs. *Demo: click from
  architecture to a live BPMN diagram of your chat app.*
- **M2 — Trust and questions** (step 7): seam-validation shapes + model-health
  panel, inspector contract, canned query catalog, friendly-label layer,
  executable acceptance test in CI (pytest: parse all TTL, pySHACL validate,
  assert the three queries' expected rows).
- **M3 — The payoff** (step 8): the three generators, generic worker stub,
  compose output, tutorial text finalized end-to-end.

Ordering rationale: M1 makes the idea legible, M2 makes it trustworthy,
M3 makes it valuable to the persona. The tutorial text is written
incrementally alongside each milestone — if a step is awkward to *write*,
the design is wrong, and we find out early.
