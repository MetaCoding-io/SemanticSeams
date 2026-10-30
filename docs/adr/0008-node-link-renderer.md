# ADR-0008: Node-Link Renderer — elkjs Layout with Hand-Rolled SVG

**Status:** Accepted

**Date:** 2026-10-28

**Source:** [backlog](../backlog.md) item 2 (C4 renderer on ELK with nested containment); [research note](../research/2026-10-15-eventcatalog-levels.md) §2 (levels and rolled-up edges); decision D009

## Context

The viewer draws its node-link notations (C4, IFML, statechart) with vis-network. M006/S01 gave every node one shared card (layer accent bar, type pill, label, description, seam dots), drawn by hand on the vis-network canvas. Two vis-network limits now block backlog item 2:

- **It cannot nest.** C4 is about containment: a system holds containers, an environment holds deployment nodes. vis-network has no compound nodes, so `arch:contains` is drawn as an edge, and the diagram reads as a flat graph rather than boxes inside boxes.
- **Its layout moves on every load.** The physics simulation settles differently each time. A reader cannot build a mental map, and positions cannot be checked in tests or browser checks.

Backlog item 2 also asks for C4 levels (L1 system context, L2 containers, L3 components and operations) and for L1 edges that roll container dependencies up to the systems that contain them.

## Decision

Use **elkjs** (the JavaScript build of the Eclipse Layout Kernel, loaded from CDN as `elk.bundled.js`) for layout, and draw the result as **hand-rolled SVG** in `viewer/templates/fragment.html`.

- ELK's `layered` algorithm with `elk.hierarchyHandling: INCLUDE_CHILDREN` lays out compound nodes. `arch:contains` becomes nesting through a `parent` field on each node and is never drawn as an edge.
- Input nodes and edges are sorted server-side, and ELK runs with a fixed random seed, so the same model gives the same positions on every load.
- Each SVG node group carries `data-iri`, `data-layer` and `data-parent`, and the ELK result is exposed as `container.seamsLayout` (the counterpart of S01's `container.seamsNetwork`) for browser checks.

### Levels are viewer configuration

C4 levels are **viewer configuration** in `viewer/levels.py`, not seam predicates (design rule 2: the graph states facts about the system, not how a view slices them). A level is a set of node classes plus the edge rules it adds. The level is chosen server-side through a `?level=` query parameter on `/view`, which defaults to L2 and falls back to L2 with a warning for unknown values.

### L1 edges come from a canned query

System-to-system edges at L1 come from `docs/queries/c4-l1-rollup.rq`, which rolls container-level `arch:dependsOn` and `seam:deployedTo` up to the systems and environments that contain the endpoints. It is SPARQL with an acceptance test in `tests/test_acceptance.py`, not JavaScript. It is a projection query for the view, not a Questions-catalog entry, and is not listed in `viewer/queries.py`.

**Amendment (M007/S02, decision D021):** a fourth level, L4 "Seams", is L3 plus the targets of nest-mode seams. Each seam predicate declares a reveal mode in `ontology/seam.ttl` ([ADR-0005](./0005-navigation-resolution.md) as amended), and at L4 the target of every nest-mode seam from a visible node — today the IFML model a container `seam:presents` and the process it `seam:executes` — becomes a compound node with that node as its `parent` and a `nestedVia` field naming the predicate. Its model's top-level members (those no other member contains) are nested inside it as cards in that model's layer colour. Nested-model edges are not drawn. This is the same flat-nodes-with-parent model and ELK `INCLUDE_CHILDREN` layout as the other levels; no new renderer.

### Legend and hiding

The C4 view has a legend with one entry per node type (the node's `type` qname) and its count at the current level. Clicking an entry toggles that type in a `?hide=` query parameter, so a filtered view is a shareable URL, like `?level=`. Hiding is server-side in `viewer/legend.py` (decision D010). A hidden node with a visible ancestor is collapsed into that ancestor. A hidden node with no visible ancestor is contracted, so its visible predecessors connect to its visible successors. Rerouted edges carry kind `contracted` and are drawn dashed. The level toggle and legend links carry `hide`; descent links do not.

### IFML

M006/S05 draws IFML as IFML, not as a node-link graph (decision D011). `viewer/ifml.py` derives the IFML elements from the graph (containers with `[L]`/`[XOR]`/`[D]` markers, «List»/«Details»/«Form» components with «DataBinding» strips and «SimpleField» rows from the bound SHACL shape, events on component borders, Process Action hexagons, navigation/data/action flows, «ParamBindingGroup» and activation notes) and works out integer geometry in Python. `viewer/templates/ifml.html` only draws that dict as SVG. There is no client-side layout and no ELK for IFML, so the picture is deterministic and pytest can check both geometry and markup. Clicks delegate through `window.seamsNavigate` like every other renderer. The statechart stays on vis-network with the S01 card. The follow-up, if IFML needs editing or richer pan and zoom, is diagram-js with ELK ports for events.

**Amendment (M007/S04, decision D023):** that follow-up is done. The geometry still comes from Python: `ifml_diagram()` is unchanged, and `ifml_elk_graph()` in `viewer/ifml.py` carries it as an ELK graph with the `fixed` algorithm, where containers nest their components, actions and notes are root nodes, events are `FIXED_POS` ports on their owner's east border, and flows are edges whose one section follows the Python points. The client runs ELK over that graph, so the layout is the same as the M006/S05 SVG, and diagram-js draws the result with a small custom renderer (`window.seamsRenderIfml` in `page.html`). Events are shapes attached to their owner. The canvas pans by drag (MoveCanvas) and zooms with the +, − and fit buttons; there is no scroll zoom and no wheel listener. Seam badges are diagram-js overlays added by the same `seamsDecorateDiagram` helper as bpmn-js and dmn-js, and clicking any element or badge goes through `window.seamsNavigate`. diagram-js is loaded as ES modules from esm.sh. Compound nodes and the root set `elk.nodeSize.fixedGraphSize`, because ELK's `fixed` algorithm otherwise shrinks them to their children (fixed in M007/S05).

**Amendment (M010/S06):** `viewer/ifml.py` no longer reads the graph itself. It derives the IFML elements from the seams library's `model.interfaces` view, the same view the htmx generator reads, so IFML has one interpretation: pages, components (`Component.types` gives the stereotype), events and their owners, flows and parameter bindings, and `seam:visibleWhen` guards on pages and components, scoped to the drawn model with `Element.in_model`. A flow without exactly one source and target, a binding without both parameters, or a form field without an IRI `sh:path` now raises `ResolutionError` instead of being skipped. The geometry and the ELK graph are unchanged.

### Shape graphs

M007/S03 gives the data layer a view on the same ELK card renderer (decision D022). The renderer script moved out of the C4 branch into a shared partial, `viewer/templates/elk-canvas.html`, included with a canvas id and a label for its aria-label and error messages. `viewer/shapegraph.py` turns a `seam:ShapeGraph` model into frames (node shapes), cards (property shapes) and `sh:class`/`sh:node` edges. Two optional node fields serve it, and C4 ignores them when absent: `navigateTo` (a property card opens its target shape, or its own shape) and `focused` (a self-landing shape, such as ConversationShape, is highlighted in its model's graph).

## Alternatives Considered

- **(a) elkjs + hand-rolled SVG — chosen.**
  - The project outline already names elkjs.
  - The S01 card is already drawn by hand, so porting it to SVG costs little.
  - SVG nodes are DOM elements with `data-iri`. They survive htmx swaps, take ordinary click handlers, and can be asserted in tests and browser checks; canvas pixels cannot.
  - S05 puts IFML events on component borders. Those are ELK ports, which this renderer can draw directly.
  - With sorted input, ELK layered is deterministic.
- **(b) Cytoscape.js with cytoscape-elk.** Has compound nodes and an ELK adapter. Rejected: nodes are canvas-drawn, so the S01 card needs a further plugin (html labels) and is not DOM; border ports for IFML events are not native; the plugin chain is three libraries where (a) needs one.
- **(c) React Flow + ELK.** Good interaction model. Rejected: it brings React into an htmx shell that has no build step.

## Consequences

- **Positive:** Containment reads as nesting, and positions are stable across loads, so a reader keeps a mental map and tests can compare layouts.
- **Positive:** The renderer is plain DOM, so htmx navigation, `data-iri` hooks and the shared card all carry over.
- **Positive:** Levels and the L1 rollup are server-side and tested in pytest; the level is in the URL from the start.
- **Negative:** The project owns pan and zoom. v1 is drag to pan plus +, − and fit buttons. There is no wheel listener, so the diagram never traps page scroll.
- **Negative:** Several renderers live side by side for a while: C4 on elkjs + SVG, IFML on diagram-js over a fixed ELK layout (M007/S04, see "IFML" above), and the statechart still on vis-network.
- **Follow-up (done, M007/S04):** backlog item 10 moved the IFML drawing onto diagram-js and kept the Python geometry, carried as a fixed ELK layout with ports for events. diagram-js is also the base if IFML editing is wanted later.
