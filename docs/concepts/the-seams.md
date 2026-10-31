# The seams

The layers are mostly solved: C4, IFML, BPMN, DMN and SHACL each have a vocabulary or a
native format that works. What no tool has is the joins between them. SemanticSeams
names those joins with a small bridging ontology, `seam:`, and every cross-layer edge in
a model uses one of its predicates. The seams are where the novelty and the value live.

The [seam predicates reference](/reference/seam-predicates) describes every predicate,
generated from [`ontology/seam.ttl`](../../ontology/seam.ttl).

## Four design rules

1. **Few and generic beats many and precise.** Twenty-eight predicates. Precision lives
   in the layer vocabularies and in SHACL shapes over the seams, not in a growing list of
   specialised edges.
2. **Every predicate must earn a cross-layer query.** If no question needs it, it does
   not belong in `seam:`.
3. **Reuse inside layers, mint only where layers meet.** Hydra, SHACL, ODRL and the
   layer vocabularies do the work inside a layer.
4. **The navigation backbone stays notation-agnostic,** so a new renderer, such as a
   Gantt chart or a deployment map, plugs in without an ontology change.

## The backbone

Three predicates carry the navigation every other seam relies on:

- [`seam:detailedBy`](/reference/seam-predicates#seam-detailedby): an element to the
  model that elaborates it. Following it is zooming in.
- [`seam:notation`](/reference/seam-predicates#seam-notation): which notation a model
  is in, and so which renderer the viewer mounts.
- [`seam:inModel`](/reference/seam-predicates#seam-inmodel): an element to the model it
  belongs to. Membership as data is what lets a SPARQL path cross from a process into its
  tasks.

## The joins

The rest group by the layers they join. A few examples:

| Join | Predicates |
|---|---|
| Architecture to everything | `presents` (container to its interface), `executes` (container to the process it runs), `exposes` and `consumes` (operations and channels), `deployedTo` |
| Interface to process | `triggers` (event to process), `completedOn` (user task to the form a person completes it on, [ADR-0009](/adr/0009-human-tasks)), `visibleWhen` (view component to lifecycle state) |
| Process to decisions, communication and data | `decidedBy`, `invokes`, `publishesTo` (a message throw event's completion event, or a service task that streams its invoked operation's deltas onto a channel), `subscribesTo` (a message start event that subscribes to a channel starts its process on each publish, [ADR-0010](/adr/0010-channel-started-processes)), `reads`, `writes` |
| Data to architecture | `storedIn` (shape to the store container that persists its instances, [ADR-0011](/adr/0011-storage-resolution)) |
| Data to lifecycle | `lifecycle` (shape to state machine), `fires` (task to transition) |
| Communication contracts | `acceptsShape`, `returnsShape`, `mediaKind`, `implementedBy` (operation to what serves it: an LLM completion, a Python handler or an HTTP endpoint, [ADR-0012](/adr/0012-operation-implementation)) |
| Authorization | `governedBy`, deliberately attachable to anything |

`reads` and `writes` are the workhorses of impact analysis: a property path through
`triggers`, `decidedBy` and `invokes` ending in `writes` answers "what can touch this
data".

`storedIn` is the only seam that ends at a store. With `deployedTo` it answers "which data
is lost if this node goes away". The store's kind (`deploy:storeKind`) and the binding
that reaches it (`deploy:connectsTo`) are deployment facts, so they live in `deploy:`,
not among the seams.

## How each seam is revealed

Every seam predicate, apart from the administrative `inModel`, `notation` and
`renderPayload`, declares a [`seam:reveal`](/reference/seam-predicates#seam-reveal) mode
in the ontology. The mode tells the viewer what to do with the edge's target:

- **Open** replaces the view with the target's model: `detailedBy`, `triggers`,
  `completedOn`, `decidedBy` and `lifecycle`.
- **Nest** draws the target inside its source: `presents` and `executes`. This is what
  the C4 view's L4 level shows.
- **Layer** overlays the target on the current view. This applies to every other seam.
  Until layer mode is built, these edges appear only in the inspector.

Open and nest seams navigate on click. A model graph can override a predicate's mode
with its own `seam:reveal` triple. The mode is an annotation on the predicate, not a new
seam edge, so the predicate count does not change. See
[ADR-0005](/adr/0005-navigation-resolution) and [the viewer guide](/guide/the-viewer).

## The method applied to itself

Constraints on the seams are not written as `rdfs:domain` and `rdfs:range`, because RDFS
infers a type onto a violator instead of rejecting it. They are
[SHACL shapes](/reference/shapes) over the model graph: `seam:triggers` must start at an
`ifml:Event`, `seam:detailedBy` must end at a `seam:Model`, a BPMN model must carry its
payload. CI validates every example against them and proves they reject broken seams,
and the viewer shows the result on every page.

All seam edges also live in their own named graph, separate from the layer graphs they
join ([ADR-0001](/adr/0001-named-graph-partitioning)), so the seams can be audited on
their own.
