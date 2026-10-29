# The seams

The layers are mostly solved: C4, IFML, BPMN, DMN and SHACL each have a vocabulary or a
native format that works. What no tool has is the joins between them. SemanticSeams
names those joins with a small bridging ontology, `seam:`, and every cross-layer edge in
a model uses one of its predicates. The seams are where the novelty and the value live.

The [seam predicates reference](/reference/seam-predicates) describes every predicate,
generated from [`ontology/seam.ttl`](../../ontology/seam.ttl).

## Four design rules

1. **Few and generic beats many and precise.** Twenty-five predicates. Precision lives
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
| Interface to process | `triggers` (event to process), `visibleWhen` (view component to lifecycle state) |
| Process to decisions, communication and data | `decidedBy`, `invokes`, `publishesTo`, `subscribesTo`, `reads`, `writes` |
| Data to lifecycle | `lifecycle` (shape to state machine), `fires` (task to transition) |
| Communication contracts | `acceptsShape`, `returnsShape`, `mediaKind` |
| Authorization | `governedBy`, deliberately attachable to anything |

`reads` and `writes` are the workhorses of impact analysis: a property path through
`triggers`, `decidedBy` and `invokes` ending in `writes` answers "what can touch this
data".

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
