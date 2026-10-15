# Research note: EventCatalog "Levels" (Oct 2026) and what SemanticSeams can take from it

*Status: research / design input, no implementation. 2026-10-15.*

## Source

David Boyne announced a "Levels" feature for the EventCatalog visualiser on
2026-10-15 ([tweet](https://x.com/boyney123/status/2110649195728126408)). The
attached media is an 11.5-second animated GIF (1280×720) of the visualiser
switching between L1, L2 and L3 on an "Ordering" domain diagram. EventCatalog's
own write-up is
[One diagram, three levels of detail](https://www.eventcatalog.dev/blog/eventcatalog-v5-diagram-levels);
the feature overview is on their
[visualization page](https://www.eventcatalog.dev/features/visualization).
The visualiser ships as a standalone React component, `@eventcatalog/visualiser`
([GitHub](https://github.com/event-catalog/eventcatalog)).

The GIF and extracted frames are kept out of the repository (they are the
author's media); this note describes them.

## What the GIF shows, frame by frame

**Layout.** Two panes. Left: an explanatory panel with one card per level, the
active card highlighted. Right: the canvas, with a title chip top-left
(`Ordering (v1.0.0)`), a `Search nodes…` box top-right, a dotted-grid
background, an **L1 / L2 / L3 segmented toggle bottom-centre**, and a **legend
bottom-right whose type counts change with the level**.

**The three level cards, verbatim.** The wording matters: each level is
described as a *question the reader is asking*, not as a list of node types.

| Level | Card title | Card text |
|---|---|---|
| L1 | Domains, systems and actors | "The context: who uses your systems, which domain each one belongs to, and how they relate to the rest of the business." |
| L2 | Services and data stores | "Open the systems up to see the services inside them and the data they own, without the noise of every message." |
| L3 | Messages and channels | "Add the commands, events and channels flowing between services, down to who subscribes to what." |

**L1 (frames 0–2, 9–11).** The `Ordering` domain is a tinted container box
holding two **System** nodes (`Checkout System`, `Order Management System`).
The `Shopper` **Actor** sits outside the domain with a labelled edge
(`confirms checkout`). Two sibling domains (`Payments`, `Fulfilment`) sit to
the right as collapsed boxes, joined by labelled edges (`invokes Authorize
Payment`, `publishes events`, `creates orders via`). Each system node carries a
coloured type pill (`SYSTEM`), a version tag, a one-line description, and
**two small count badges** (e.g. "2" data, "4" messages) that signal there is
collapsed detail inside. Legend: Domains (3), Actors (1), Systems (2).

**L2 (frames 3–5, 8).** The two systems **expand in place** into nested
containers showing their **Service** nodes (`Checkout API`, `Checkout
Orchestrator`, `Order Service`) and one **Data** node (`Order Database`,
"PostgreSQL · orders"). Internal edges appear (`invokes`, `reads and writes`).
The actor edge **re-anchors from the system boundary to the specific service**
it actually talks to (`Checkout API`); the cross-domain edges re-anchor to the
expanded system boundary. The count badges disappear because the detail is now
visible. Legend adds Services (3), Data (1).

**L3 (frames 6–7).** Everything from L2 stays, and **Command**, **Event** and
**Channel** nodes are inserted *between* services (`Checkout Cart`, `Create
Order`, `Order Created`, `order-events`) with edges `accepts`, `invokes`,
`publishes`, `routes to`. Legend adds Commands (2), Events (1), Channels (1).

**Transitions.** Switching levels animates: leaving nodes fade, the layout
re-flows, but the actor, the domain frame and the sibling domains keep their
places. Layout is automatic with orthogonal edges and per-edge connection
points; labels sit on the edge.

**Visual language.** Every node shows the same four things: a coloured
type pill top-left (colour matches the legend), a label with a version tag,
a one-line description, and a small owner/namespace line
(`ordering-platform`). Containment is drawn as **nesting**, never as an edge.

**From the blog post (not visible in the GIF).**
- L1 = "Domains, systems and the relationships between them"; L2 = "The
  services and data stores inside them, and how they connect"; L3 =
  "Everything in L2, plus the messages and channels". Levels are cumulative.
- The rationale: "Different people ask different questions of the same
  architecture." Earlier versions split views across pages, "so you had to know
  which one to open." They explicitly cite the C4 model (context, then
  containers).
- **Clicking a legend entry hides that type.** When messages/channels are
  hidden, "the nodes on either side stay connected" — i.e. edges are contracted
  through the hidden node, not dropped.
- A level that does not apply to a diagram is greyed out.
- **The level is in the URL**, so shared links open at that level, and the
  chosen level is remembered per kind of diagram.
- Cross-domain highlighting works at whichever level you are viewing.

## How this relates to SemanticSeams

The two tools zoom along **different axes**, and the comparison is clarifying.

| | EventCatalog Levels | SemanticSeams descent (`seam:detailedBy`) |
|---|---|---|
| What changes when you "zoom" | Which element *types* are visible in one diagram, one notation | Which *model and notation* you are looking at |
| Mechanism | Filter + in-place expand/collapse | Graph traversal + renderer switch |
| Where it stops | Messages and channels (their L3) | DMN tables and SHACL shapes |
| Metamodel | Fixed: Domain › System › Service › Message/Channel | Ontology: `arch:` + `comm:` + `ifml:` + `proc:` + … |
| Defined where | Hard-coded in the React component | Nowhere yet; the C4 renderer dumps every member of the model |

EventCatalog's L3 (services, data stores, commands/events, channels, who
subscribes to what) is almost exactly SemanticSeams' **architecture layer plus
`comm:` plus the `seam:exposes` / `seam:consumes` / `seam:publishesTo` /
`seam:subscribesTo` edges**. Their deepest level ends precisely where
SemanticSeams' notation-switching descent *begins* (IFML, BPMN, DMN, shapes).
So the two are complementary: Levels is the **zoom within the architecture
layer** that SemanticSeams currently lacks, and the descent is the **zoom
across layers** that EventCatalog does not have. SemanticSeams needs both,
and the first makes the second usable: today a click on the C4 view replaces
the whole view, so there is no way to "open up" a system without leaving the
architecture diagram.

Concretely, in the current viewer (`viewer/app.py`, `c4_graph_data`):
- `arch:contains` is drawn as an **edge**, not as nesting. The chat-app example
  has `chat_system contains chat_ui, chat_api, …` and `prod contains web01, …`,
  which vis-network renders as a star of "contains" arrows. EventCatalog's
  nesting is the obviously better projection of the same triples.
- Everything in the model graph is rendered at once: System, Containers,
  Environment and DeploymentNodes in one physics layout. There is no L1.
- A node that carries `seam:detailedBy`, `seam:presents` or `seam:executes`
  looks identical to one that does not. ADR-0005 says click = descend or
  inspect, but the user cannot tell which before clicking. EventCatalog's
  count badges are the affordance we are missing.
- Levels would be free data-wise: they are a partition of classes, and every
  element already carries `rdf:type` and `seam:inModel`.

## What to take (prioritised)

### 1. Levels as declared view definitions, not renderer code

A level is a set of classes to show (cumulative) plus a rule for what happens
to edges through hidden nodes. That is a *view definition over the graph*,
which is exactly the project thesis ("diagrams are views"). Define the levels
for the C4 notation as data the viewer reads, rather than as branches in the
renderer. A first cut that mirrors EventCatalog but uses our vocabulary:

| Level | Shows | Answers |
|---|---|---|
| L1 Context | `arch:System`, `arch:Person`, `arch:Environment`; summary edges between them | Who uses this, what does it talk to |
| L2 Containers | + `arch:Container`, `arch:Component`, `arch:DeploymentNode` nested inside their parent; `arch:dependsOn`, `seam:deployedTo` | What is inside, what runs where, what depends on what |
| L3 Contracts | + `comm:Endpoint`, `comm:Channel`, operations; `seam:exposes`, `seam:consumes`, `seam:publishesTo`, `seam:subscribesTo` | Which operations and channels carry the dependencies |
| L4 Seams (ours only) | + ghosted portals to other notations: the IFML model each container `seam:presents`, the processes it `seam:executes`, the shapes its operations accept/return | Where does this diagram hand off to UI, process, decision and data models |

L4 is the one EventCatalog cannot have and is the natural bridge between the
two zoom axes: at L4 the cross-layer nodes appear as small "portal" nodes, and
clicking one is the descent of ADR-0005. L1–L3 are the pre-descent zoom.

Design-rule check: this does **not** belong in `seam:` (rule 2, "every seam
predicate must earn a query"). It is viewer configuration. Either a small
`view:` vocabulary (level → ordered list of classes, per notation), or a plain
config file in the viewer. Recommendation: start with viewer config; promote
to a vocabulary only if a second consumer (e.g. the MCP/agent surface, or a
static exporter) needs it.

### 2. Edge contraction and rolled-up edge labels

EventCatalog's L1 edges (`invokes Authorize Payment`, `publishes events`) are
**summaries of hidden L3 detail**, and hiding a message type keeps its
neighbours connected. In SPARQL terms this is a property path through the
hidden class: `?a seam:publishesTo/^seam:subscribesTo ?b` yields a
container-to-container edge labelled from the channel it passed through.
The same rollup gives L1 its system-to-system edges from container-level
`arch:dependsOn`. This is a concrete, testable projection rule and belongs in
the canned-query layer next to the existing `.rq` files, not in JavaScript.

### 3. The "there is more beneath" affordance

Give every node that has collapsed children **or** a `seam:detailedBy` /
`seam:presents` / `seam:executes` target a badge: a count for collapsed
containment, a notation glyph (BPMN, IFML, DMN, shapes) for a descent. This
closes the ADR-0005 legibility gap at almost no cost and is the single most
valuable borrowing for the current POC.

### 4. Legend with live counts and click-to-hide

Node `group` is already the first `rdf:type`. A legend listing types with
counts for the current level, click to hide (with edge contraction from §2),
is cheap and is what makes the level toggle feel trustworthy: the numbers
tell you what you are not seeing.

### 5. Levels as questions, in the sidebar, next to the Questions catalog

The explanatory cards are good product writing: each level is a question. The
viewer already has a per-view "Questions" section (the canned-query catalog
with applicability by `rdf:type`). Put level cards in the same place and in
the same voice, and grey out a level when the model has nothing at that level,
exactly as EventCatalog does and exactly as `applicable_queries` already does
for questions.

### 6. State in the URL

`/view/{iri}?path=…` is already deep-linkable (ADR-0005 §7). Add `level=` (or
`lens=`) so a shared link opens at the same level, and remember the last
level per notation. Trivial, and consistent with the existing contract.

### 7. Nesting, stable layout, animated transitions

This is the one item with a real technology cost. vis-network does not do
compound (nested) nodes well, and physics layouts move everything on each
change. EventCatalog preserves the mental map: the actor and domain frames stay
put while a system expands in place, and leaving nodes fade. Options:

- **Cytoscape.js** with compound nodes + an ELK or fcose layout. Framework-free,
  works with htmx swaps, compound nodes are first-class.
- **ELK (elkjs) + hand-rolled SVG**. The project outline already names elkjs
  for the shared node-link renderer; ELK's hierarchical layout gives the nested
  boxes and orthogonal edges seen in the GIF. More work, full control, no
  React.
- **React Flow + ELK** is what the EventCatalog component appears to use. Best
  polish, but it would drag React into an htmx shell.

Recommendation: Cytoscape.js for the POC (compound nodes solve nesting today),
with ELK as the layout engine so a later move to a custom SVG renderer keeps
the same geometry. Decide this in an ADR rather than in a template edit; it
replaces the renderer for three notations (C4, IFML, statechart).

### 8. A consistent node card

Type pill (from the `rdf:type` label), label, version, one-line description,
owner. We have `rdfs:label`, `arch:technology`, `arch:description` /
`rdfs:comment`, `deploy:version` on the artifact. Render them. The type pill
colour doubles as the legend colour. This is pure template work and makes the
diagram read as a product rather than a debug view.

## What not to copy

- **Fixed three levels baked into the component.** We have an ontology; the
  levels should be data. But keep the *number* small and the *names* human:
  three or four named levels with a sentence each is what makes it legible.
  Do not expose "choose any subset of 25 classes" as the primary UI; that is
  the legend's job, not the level toggle's.
- **One notation.** Their levels never change notation. Ours must stop at the
  seam and hand off to the descent, which is the differentiator. L4 above is
  the handoff, not a replacement for it.
- **Force-directed "architecture graph".** EventCatalog also has a separate
  D3 force-directed whole-catalog graph (opt-in, v4.5+). It is the thing we
  already have with vis-network, and it is the view they are moving *away*
  from with Levels. Treat our current C4 renderer as the same dead end.

## The viewer as it stands today (walkthrough, 2026-10-15)

To ground the comparison, the viewer was run locally against
`examples/chat-app` (uvicorn, headless Chromium at 1440×900) and driven through
the full descent. Observations, in the order a first-time user meets them:

- **The descent works end to end.** Root C4 → click the Chat Web Interface
  container → IFML model (via `seam:presents`) → click the Send Message event →
  BPMN diagram (via `seam:triggers` plus the one-hop `seam:detailedBy`) → click
  the Route to Provider task → disambiguation between the DMN model and the data
  model → DMN. Breadcrumbs record the trail and click back correctly. The SHACL
  health panel reads "Conforms" throughout.
- **Questions land well.** On `db01` the single applicable question, "What
  breaks if this node goes away?", answers inline with four linked rows,
  including the Send Message process, in about 5 ms. On the `composing` state
  the answer names the task, the transition and the target state. This is the
  feature that already feels unlike anything else, and it is currently only
  reachable from leaf elements that have no renderer.
- **The C4 view is the weak point**, exactly where EventCatalog's Levels are
  strong. Containment is drawn as "contains" arrows, so the system and its
  four containers form a star next to a second star for the production
  environment and its three nodes. Nothing distinguishes a container that
  can be descended into from one that cannot. The physics layout settles
  differently on every load, and the mouse wheel over the canvas zooms the
  diagram instead of scrolling the page, which traps the inspector below it.
- **IFML reads as a generic graph.** Pages, components, events, parameters and
  flows all get the same box shape with a different colour; the flow
  `list_to_thread` appears as a node with "flow source" and "flow target" edges,
  which is the RDF showing through rather than IFML's notation.
- **BPMN and DMN are the best-looking views**, because bpmn-js and dmn-js bring
  their notation with them. The DMN DRD overlaps dmn-js's own title overlay with
  the first input node, and the decision table itself is one click further in.
- **The data layer has no view.** Navigating to a shape resolves straight to
  the "Chat Data Model" and shows "No renderer yet for notation shapegraph".
- **No type legend, no counts, no descriptions on nodes, no search.** Every
  item in the EventCatalog node card (type pill, version, description, owner)
  is absent even though the data for most of it is in the graph.

Net: the cross-layer mechanics (resolution, disambiguation, breadcrumbs,
questions) are solid and are the differentiator. The within-layer presentation
is where the EventCatalog borrowings in the previous section apply, and the C4
view should be the first renderer to receive them.

## Open questions for the design

1. Is L4 (seam portals) a level, or an overlay toggle orthogonal to L1–L3?
   Argument for overlay: you may want "show me the processes" at L2
   (container level) as readily as at L3.
2. Does IFML get its own level set (ViewContainer › ViewComponent › Event /
   Parameter / Flow)? The same mechanism applies; the question is whether to
   ship one notation first or generalise from the start. Recommendation: C4
   first, generalise when IFML needs it.
3. Where does the rollup query live so that the same L1 edges appear in the
   viewer, in a static export and in any agent-facing surface? (Suggests the
   `docs/queries/` catalog, with an acceptance test asserting the rolled-up
   rows, as the existing three queries already do.)

## Sources

- Tweet: https://x.com/boyney123/status/2110649195728126408 (media
  `https://video.twimg.com/tweet_video/HUqH_IMXMAAIVMs.mp4`)
- EventCatalog blog, "One diagram, three levels of detail":
  https://www.eventcatalog.dev/blog/eventcatalog-v5-diagram-levels
- EventCatalog visualization feature page:
  https://www.eventcatalog.dev/features/visualization
- EventCatalog changelog (v4.5.0 architecture graph beta, v4.10.0 embeddable
  graph): https://www.eventcatalog.dev/changelog
- EventCatalog repository (visualiser as `@eventcatalog/visualiser`):
  https://github.com/event-catalog/eventcatalog
