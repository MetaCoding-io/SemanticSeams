# Diagrams are views

Every tool that draws software draws one layer. C4 tools give zoomable architecture,
and the bottom of the zoom is a link to a repository. BPMN modelers draw executable
processes, disconnected from the screens that start them and the data they change. IFML
models user interaction, and its metamodel has hooks for external process and data
models that nobody wired up. SHACL describes data in a silo of its own.

SemanticSeams starts from the other end. **One RDF graph is the single source of truth,
and every diagram is a view over it.** Each element of each layer, whether a C4
container, an IFML view component, a BPMN task, a DMN decision or a SHACL shape, is a
resource with an IRI. The relationships between layers are triples like any other.

## Zooming in changes the notation

Because everything is one graph, zooming in is a traversal, not a feature of a drawing
tool. Clicking a node follows an edge, and the viewer mounts whichever renderer the
target model's notation calls for. The canonical descent crosses four notations:

1. The **C4** architecture view, the navigation shell. Click a container.
2. Its **IFML** surface: pages, components, events, flows. Click an event.
3. The **BPMN** process behind it. Click a business-rule task or a data object.
4. The **DMN** decision table, or the **SHACL** shape of the data.

No other tool switches notation at the bottom of the zoom. That is the project's novel
part, and [Using the viewer](/guide/the-viewer) shows it working.

## Layers and their notations

| Layer | Notation | How it is held |
|---|---|---|
| Architecture | C4-style containers and deployment | The [`arch:`](/reference/vocabularies#arch) vocabulary |
| Interaction | IFML | The [`ifml:`](/reference/vocabularies#ifml) vocabulary, documented against OMG IFML |
| Process | BPMN 2.0 | Native XML, rendered by bpmn-js; only seam-participating elements are lifted, typed by [`proc:`](/reference/vocabularies#proc) |
| Decision | DMN | Native XML, rendered by dmn-js |
| Lifecycle | Harel statecharts | The [`state:`](/reference/vocabularies#state) vocabulary |
| Data | RDF and SHACL | SHACL shapes are the vocabulary |
| Communication | Operations and channels | Hydra, plus [`comm:`](/reference/vocabularies#comm) for channels |
| Deployment | Artifacts, configuration, placement | The [`deploy:`](/reference/vocabularies#deploy) vocabulary |

There is deliberately no BPMN or DMN ontology. Those standards already have excellent
XML formats and renderers, so the XML stays the source and the graph indexes only the
elements that take part in a cross-layer edge.

## Why one graph pays

Two things fall out of the single graph that no toolchain of separate modelers offers:

- **Navigation across notations,** described above.
- **Questions across layers.** "Which screens can eventually write this data?" is one
  SPARQL property path through the seams. See
  [Cross-layer queries](/concepts/cross-layer-queries).

Text and diagrams are co-equal projections of the graph, which is what keeps the classic
objections to visual programming at bay: Turtle diffs and merges like code, and the
diagrams are drawn from it rather than stored beside it.

The [project outline](/project-outline) sets out the full motivation, the landscape and
the design.
