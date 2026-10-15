# Design note: render IFML as IFML, not as RDF

*Status: design proposal, 2026-10-15. Companion to
[reveal modes](2026-10-15-reveal-modes.md). A before/after mock of the chat
interface in proper IFML notation is published as the artifact "Chat Interface
in IFML".*

## The problem

The viewer's IFML renderer is the same vis-network node-link code as the C4
renderer: every subject in the model graph becomes a box, every predicate an
arrow. A page is a node with three "contains" arrows, a data flow is a node
with "flow source" and "flow target" arrows, and a parameter is a box the
same shape as a page. It is a faithful picture of the triples and a poor
picture of the interface. Anyone who has used WebRatio, IFMLEdit.org or the
OMG spec expects the notation, and the notation is what makes an interaction
model readable at a glance: you see pages as boxes, content inside them,
events on the edges, and arrows for what happens when the user acts.

## The notation (from the OMG / WebRatio quick reference card)

| Concept | Drawn as |
|---|---|
| View container | Rectangle with a title bar holding the name; nested containers drawn inside. Markers before the name: `[L]` landmark, `[XOR]` mutually exclusive children, `[D]` default child. Examples also use `[H]` home, `[Modal]`, `[Modeless]`. |
| View component | Rounded rectangle, stereotype above the name in guillemets: «List», «Details», «Form». A «DataBinding» strip names the data it shows. |
| View component part | Rows inside the component: «SimpleField» name, «SelectionField» name, etc. (form fields, list columns). |
| Event | Small circle on the border of the component or container, label beside it. White fill for user events, black for system and action-completion events. |
| Action | Hexagon, outside the containers, with its own completion event on its border. |
| Navigation flow | Solid arrow from an event to the target element. |
| Data flow | Dashed arrow between elements; parameters only, no navigation. |
| Parameter binding group | Parallelogram note «ParamBindingGroup» with `source → target` lines, joined to the flow by a dashed line. |
| Activation expression | Note with the condition in square brackets, attached to the element it gates. |
| Module | Rectangle with input and output ports (out of scope for v1). |

Sources: the quick reference card on ifml.org (WebRatio and OMG, 2014), the
bookstore worked example on ifml.org, and the shape sources of IFMLEdit.org.

## Why this is a good fit, not just a nicer picture

IFML already has slots for exactly the things the seams carry. Rendering the
notation means the seams stop being inspector rows and become part of the
diagram:

| Seam | IFML construct it fills |
|---|---|
| `seam:reads` → shape | «DataBinding» strip on the component (green dot) |
| `seam:writes` → shape, on a «Form» | «SimpleField» rows derived from the shape's `sh:property` paths, plus the binding strip. This is SHACL-driven form generation made visible on the diagram before any UI is generated. |
| `seam:triggers` → process | The «Action» hexagon with its completion event (violet dot). The hexagon is not stored in the graph; it is how the seam renders, and clicking it is the descent to the BPMN model. |
| `seam:visibleWhen` → state | «ActivationExpression» note `[state = composing]` (teal dot). IFML's own conditional-rendering construct, which the project outline already identified as the right home for this. |
| `seam:governedBy` → policy | A second activation-style note, or a lock glyph on the event (open question). |

And the notation makes model problems visible that the node-link view hides.
On the chat example, two appear immediately: the `Select Conversation` event
has no navigation flow leaving it, and the `list_to_thread` data flow binds
`selected conversation` to `message input`, the form's parameter, where the
thread's parameter was almost certainly intended. Both are worth fixing in
the example, and both are the kind of thing a SHACL shape over the IFML
vocabulary could flag.

## What the vocabulary already has, and what rendering derives

The `ifml:` vocabulary covers containers, the three component stereotypes,
events, navigation and data flows, parameters and bindings, and the three
container markers. It deliberately omits Actions, ViewComponentParts and
ActivationExpressions. None of those need adding for the notation:

- **Action** is derived from `seam:triggers`: one hexagon per triggered
  process, placed outside the container, labelled with the process label.
- **Fields** are derived from the shape a «Form» `seam:writes` (or a «List»
  or «Details» `seam:reads`): one «SimpleField» per `sh:property` path, with
  `sh:datatype` choosing the field kind. A `dash:` or SHACL 1.2 UI annotation
  can refine this later without touching `ifml:`.
- **Activation expression** is derived from `seam:visibleWhen`.
- **Event kind** (user vs system) is derived from whether the event has an
  incoming flow from an action's completion; the vocabulary collapses the
  event taxonomy on purpose.

Two small additions are worth considering: an `ifml:ViewComponentPart` (or
reuse of the SHACL derivation as the only source of fields), and a way to say
which parameter an event exposes. Neither blocks the renderer.

## How to render it

Three options, in rough order of how much they borrow.

**A. Reuse IFMLEdit.org's shapes.** IFMLEdit.org (MIT) draws the notation
with JointJS 2 through its `almost-joint` layer, and has a JSON model format
with import and export. It also ships code generators (NodeJS, Flutter) and
an emulator. The attraction is a complete, standards-faithful notation and,
later, a complete editor. The cost is JointJS 2 (2017-era, MPL-2.0), a
Browserify and Knockout era codebase, and a second diagram framework next to
diagram-js. Verdict: do not embed it, but do write the mapping from our graph
to its JSON format as an exporter. If a model round-trips through IFMLEdit,
it is real IFML, and that is a cheap conformance test for the vocabulary's
correspondence claims.

**B. Build the renderer on diagram-js.** This is what the project outline
planned for the IFML editor, and it is the right call for the viewer too:
diagram-js is the framework under bpmn-js and dmn-js, so pan, zoom, selection,
keyboard, overlays and `element.click` behave identically across process,
decision and interaction views, and the seam dots are overlays exactly as
they will be on BPMN tasks. The notation is five shapes and two edge styles;
the custom renderer is a few hundred lines. The modeling module gives editing
later for free.

**C. Server-side SVG from a Jinja template.** Fastest to the first picture,
no new dependency, consistent with the htmx shell. It gets the POC a proper
IFML view in days. It has no pan or zoom and no editing path, so it is a
stepping stone, not the destination.

Recommendation: C now, B next, with the SVG geometry from C reused as the
diagram-js shapes. A for interchange and validation, never for rendering.

**Layout.** Containers are compound nodes, components are children, and the
events are *ports* on the component: ELK's layered algorithm supports ports
natively, which is precisely the IFML convention of circles on the border.
Direction left to right, actions placed outside the containers in the same
layered flow. The binding and activation notes are small nodes attached by
dashed edges and can be positioned by a simple rule (above the flow's
midpoint, beside the element) rather than by the layout engine.

**Visual language.** The notation is drawn in the interaction layer's colour
and the unified card chrome from the reveal-modes note. Seam dots sit on the
component, the event, the action and the activation note, coloured by target
layer. That keeps the three reveal modes working: an action hexagon opens or
nests the BPMN model, a «DataBinding» strip opens or layers the shape.

## Order of work

1. Fix the two model gaps in `examples/chat-app` that the notation exposes.
2. Server-side SVG IFML renderer (option C), driven by a canned SPARQL
   projection of the model graph plus the seams, with the derivations above.
3. Seam dots and the activation and binding notes as part of that SVG.
4. Port the shapes to a diagram-js renderer with ELK ports for events.
5. IFMLEdit JSON exporter as a conformance check for the vocabulary.
6. Editing, once the modeling module is in.

## Sources

- IFML quick reference card (WebRatio and OMG): https://www.ifml.org/ifml-primer/
- IFML by example, online bookstore: https://www.ifml.org/wp-content/uploads/IFML-Bookstore-Example.pdf
- OMG IFML 1.0: https://www.omg.org/spec/IFML/1.0/
- IFMLEdit.org source (MIT): https://github.com/B3rn475/IFMLEdit.org
- Wikipedia overview and tool list: https://en.wikipedia.org/wiki/Interaction_Flow_Modeling_Language
