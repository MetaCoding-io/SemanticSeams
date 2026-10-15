# Design note: one visual language, three ways to reveal a relation

*Status: design proposal, 2026-10-15. Follows
[the EventCatalog Levels note](2026-10-15-eventcatalog-levels.md). An
interactive mock of everything below exists as a published artifact
("SemanticSeams Reveal Modes"); it uses the real `examples/chat-app` model.*

## The problem, stated from the walkthrough

The viewer's cross-layer mechanics work, but it *feels* disjointed because
every view looks like a different product: a vis-network physics graph for
C4, the same graph with other colours for IFML and statecharts, bpmn-js for
process, dmn-js for decisions, and nothing for data. The user learns a new
visual grammar on every click, and the one thing that should be constant,
the seam they just crossed, is invisible.

Two decisions fix this. The first is a single visual language that every
renderer shares. The second is to make "how do I get from here to there" a
user choice with three options, instead of the one hard-wired option
(replace the whole view) the shell has now.

## 1. One visual language

**Colour encodes layer, nothing else.** Six hues, one per pillar:
architecture, interaction, process, decision, data, lifecycle. Every node,
plane, breadcrumb, legend entry, level card and seam line uses the colour of
the layer it belongs to. The payoff is that a cross-layer relation is *any
line whose two ends differ in colour*. Seams become visible without a legend
entry for "seam".

**One node card.** Type pill (from the `rdf:type` label), label, one-line
description (`rdfs:comment`, `arch:technology`, `deploy:version`), and a row
of small coloured dots in a corner, one per outgoing seam, coloured by the
target layer. The dots are the affordance the viewer currently lacks: at a
glance you can see that this container presents a UI (amber dot) and executes
a process (violet dot), and that this task writes data (green) and fires a
transition (teal). Clicking a dot reveals that relation in whichever way its
predicate is set to (section 2).

**One layout engine for the node-link notations.** C4, IFML, statechart and
shape graph all move to a deterministic layered layout (ELK) with nesting for
containment. Containment is drawn as nesting, never as a "contains" edge.
Positions are stable across loads, and a level change or an in-place expansion
animates from the old positions to the new ones so the mental map survives.

**bpmn-js and dmn-js keep their notation, inside the same chrome.** Their
value is the notation itself, so they are not replaced. They are tinted to
the process and decision layer colours, and the seam-participating elements
get the same coloured-dot badges through the bpmn-js overlay API, so a
business-rule task shows its rose dot for `decidedBy` exactly as a card would.

**One chrome around every view.** Title chip with the model name and
notation, the level and reveal controls, a legend with live counts and
click-to-hide, search, and the inspector as a right-hand panel rather than
below the canvas (which also fixes the scroll trap, since the wheel over the
canvas belongs to the canvas).

## 2. Three ways to reveal a relation

A seam edge from element A to element B can be revealed in three ways, and
all three are projections of the same two things: the layer-internal graph of
B's model, and the seam edge itself.

| Mode | What happens on click | Analogy | Best for |
|---|---|---|---|
| **Open** (descent) | The view is replaced by B's model in its own notation; a breadcrumb records the hop and the predicate | The viewer today; a hyperlink | Reading one diagram properly; the canonical arch → UI → process → decision descent |
| **Nest** (containment) | B's model is drawn inside A's card, scaled down; neighbours are pushed aside; a second click collapses it | EventCatalog's L1 → L2; a tree outliner | Staying oriented in the architecture while peeking inside one thing; levels as presets |
| **Layer** (stack) | Every layer sits on its own plane, stacked; the seam is drawn as a line between planes; hovering an element traces all of its seams | An exploded assembly drawing; the classic layered-architecture poster | Seeing how much crosses between layers; impact tracing; the "wow" overview |

The design claim is **one layout, three placements**. Lay out B's model
once. Put it on the full canvas (Open), inside A's card (Nest), or on the
plane below A's (Layer). Because the geometry is shared, switching between
modes can animate: a nested model "lifting out" to full size is the Open
transition, and a plane "flattening" to the canvas is how the stack hands off
to Open. The transitions are what will make the three modes feel like one
tool rather than three.

### The choice is per predicate, with a global default

The ADR-0005 annotation `seam:navigational true|false` becomes a three-valued
default per predicate, and the legend's Relations panel lets the user change
it. Suggested defaults, which the mock ships with:

| Predicate | Default | Why |
|---|---|---|
| `presents`, `executes` | nest | A container "opening up" to show its UI or process is the most legible version of the EventCatalog L2 move |
| `triggers`, `decidedBy`, `lifecycle`, `detailedBy` | open | These are the descent; the target deserves the whole canvas |
| `reads`, `writes`, `invokes`, `publishesTo`, `fires`, `visibleWhen`, `acceptsShape` | layer | Many-to-one edges onto a shape, operation or state; nesting the same shape into six tasks would be noise, and opening it loses the question "who else touches this" |

This keeps the annotation in the ontology small (one enum where there was one
boolean) and puts the per-user override in viewer state, carried in the URL
like the level. Nothing is added to the seam vocabulary that does not earn a
query, in keeping with the design rules.

### Levels become presets of reveal choices

EventCatalog's levels map onto this cleanly: a level is a named preset of
which types are visible and which predicates are nested.

| Level | Visible | Nested | Answers |
|---|---|---|---|
| L1 Context | systems, persons, environments; rolled-up edges (e.g. "deployed to ×4") | none | who uses this, what runs where |
| L2 Containers | + containers, components, deployment nodes inside their parents | `arch:contains` | what is inside, what depends on what |
| L3 Contracts | + operations and channels; exposes, consumes, publishes/subscribes | as L2 | which contracts carry the dependencies |
| L4 Seams | as L3 | + `presents`, `executes` | where this diagram hands off to UI and process |

L4 is the handoff between the two zoom axes. Beyond it the user is in Open
mode in another notation, which is the project's differentiator.

## 3. What the mock shows, and what it does not

The mock renders the chat-app model as a single SVG from a small data table
(nodes, groups, within-layer edges, seams) with hand-placed positions. It has
the three modes, the four levels, the per-predicate reveal choice, a legend
with counts and click-to-hide, hover tracing in the stack, breadcrumbs that
record the predicate crossed, and entrance animations. It does not have a
layout engine, orthogonal edge routing, search, or the real bpmn-js and dmn-js
renderers; the process and decision layers are drawn in the unified card style
so the colour system can be judged on its own.

Findings from building it:

- **Nest is the mode that most needs a real layout engine.** Pushing
  neighbours aside by hand works for one expansion; two expansions in the
  same row already need ELK's compound-node layout.
- **Layer mode is legible only as an overview.** At six planes the labels are
  small, and the mode earns its place through hover tracing and through the
  plane title opening the layer flat. It should be built as a cheap oblique
  projection of the same 2D layouts, not as WebGL; true 3D adds occlusion and
  camera handling for no gain in a diagram whose text must stay readable.
- **The dots on cards are the single highest-value element.** They work in
  all three modes, they make descendable elements obvious, and they tell you
  which layer you will land in before you click.
- **Colour-by-layer makes bpmn-js the odd one out** unless it is tinted. That
  is a few CSS rules on `.djs-element` strokes and the overlay badges; worth
  doing early so the process view stops looking imported.

## 4. Suggested order of work

1. Node card + seam dots + colour-by-layer tokens in the existing templates
   (template-only change, immediately visible).
2. Replace vis-network with ELK layout and nested containment for the C4
   view; levels L1–L3 as class filters with edge rollup from a canned query.
3. Per-predicate reveal setting (`open` / `nest` / `layer`) as an ontology
   annotation replacing `seam:navigational`, with the Relations panel and the
   URL carrying overrides. Nest for `presents` and `executes` gives L4.
4. Layer mode as an oblique projection of the per-layer ELK layouts, with
   hover tracing; plane title opens the layer.
5. Tint bpmn-js and dmn-js and add overlay badges, so the foreign notations
   join the language.
6. A ShapeGraph renderer, which the data layer still lacks, using the same
   card.

Each step is independently shippable, and the first two already address most
of what felt disjointed in the walkthrough.
