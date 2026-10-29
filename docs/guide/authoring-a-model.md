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
layer, so it only appears in the inspector.
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

The chat app scores 0 / 3 / 58 and fails by design, since it is a one-model-per-layer
quick start. The expense-approval tutorial's final model is the one meant to pass.

The exit code is 0 on pass, 1 on fail, and 2 when the file is missing, unreadable or not
valid TriG (the message goes to stderr). The check loads only the TriG, not the ontology
files. The source queries are in `docs/queries/complexity/` in the repository.

## View it

The viewer loads one model, chosen by `SEAMS_MODEL`. Keep the BPMN and DMN files your
`seam:renderPayload` values name beside the TriG file, then start the viewer:

```sh
SEAMS_MODEL=path/to/model.trig python3 -m uvicorn viewer.app:app --port 8000
```

The root view is your model's C4 `seam:Model`. If the file has none, or more than one,
set `SEAMS_VIEWER_ROOT` to the IRI the viewer should open at. See
[Getting started](/guide/getting-started#open-the-viewer) for a tour of the views.
