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

## Derived sequence diagrams

A sequence diagram is never authored. `seams sequence <event>` derives one from the
graph: the actor from the event's governing policy, the lifelines from the containers
that present, expose, store and consume, and the step order from the BPMN sequence
flows. There is one diagram per path through the process's exclusive gateways rather
than one diagram with `alt` blocks. An arrow the deriver cannot place is written into
the diagram as a `%% gap:` line, so the diagram doubles as an audit of the model: a
gap names the fact that is missing. See [the seams CLI](/reference/seams-cli#seams-sequence).
The chat app's send-message event derives to the diagram below, embedded from the
golden file the generator tests pin,
[`docs/generation/sequences/chat-app/send_message.mmd`](../generation/sequences/chat-app/send_message.mmd).
The viewer shows the same diagrams per event under [Sequences](/guide/the-viewer).

<<< @/generation/sequences/chat-app/send_message.mmd{mermaid}

### As executed

The diagram above is *as designed*: what the model says a send-message does. The same
lifelines also draw *as executed*, what one run actually did. The runtime's worker
records a trace row per BPMN element it runs, and `executed` in `seams_gen.sequence`
turns those rows into a diagram: the decision with the value it returned, the LLM call
with the number of deltas it streamed, each transition with the status it reached, and,
for a user task, the identity that completed it as an actor. The two views share the
actor, UI and API lifelines, so they can be read side by side. A row the graph cannot
place, such as an element the process does not have or a channel the model does not
declare, is a `%% gap:` line here too, so a run that drifted from the model shows where.
Below is a run of the chat app's send-message process, from the golden
[`docs/generation/sequences/chat-app/send_message.executed.mmd`](../generation/sequences/chat-app/send_message.executed.mmd).

<<< @/generation/sequences/chat-app/send_message.executed.mmd{mermaid}

To draw a run of your own, give `seams sequence <event>` a trace JSON file or an instance
id from the runtime's SQLite store with `--trace RUN` (see
[the seams CLI](/reference/seams-cli#as-executed-trace)). The runtime can also emit
OpenTelemetry spans that carry the same element IRIs, one per instance and one per
element it runs. They are off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the
`seams_runtime` `otel` extra is installed (see
[seams_runtime/README.md](https://github.com/MetaCoding-io/SemanticSeams/blob/main/seams_runtime/README.md#tracing-opentelemetry)).
The diagram reads the trace rows, not the spans.

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
