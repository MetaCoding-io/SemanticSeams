# Lesson 5 · One graph, many views

*Named graphs, IRIs as identity, native payloads kept native, and the seams. The first
lesson in which you write a model.*

## Outcomes

After this lesson you can:

- Explain the four decisions that make one RDF graph hold several notations without
  turning any of them into RDF: one named graph per model plus one for the seams, a
  native element's own id as its IRI fragment, native XML kept as a payload, and
  membership stated as a fact.
- Name the backbone of the seams, `seam:detailedBy` and `seam:notation`, and say how a
  click is resolved from them.
- Write a TriG file with a C4 architecture, a seams graph and a data shape, and see the
  viewer's health badge turn green, then red, then green.

## The story

### Keep the notations, join them

Lesson 1 ended on a corollary: the models that survived are the ones with engines, so a
project that wants one model of a whole application should keep those notations, keep
their engines, and solve the one problem none of them solved, which is joining them. This
lesson is how the joining is done, and the first thing to notice is what the project
refused to do. There is no BPMN ontology in SemanticSeams, and no DMN ontology. Lifting
either standard into RDF element by element is the swamp the research notes keep naming:
you end up with a second copy of the process that drifts from the XML the engine runs,
which is failure F3 reinvented in a new format.

Instead, a process is a `seam:Model` with a `seam:notation` of BPMN, and the model
carries its native XML as a `seam:renderPayload`. The viewer hands that XML to bpmn-js,
the runtime hands it to SpiffWorkflow, and neither of them learns anything about seams.
The graph indexes only the elements that take part in a cross-layer edge: a business-rule
task because a decision is attached to it, a service task because it invokes an operation,
a user task because a form completes it. Those elements get an IRI and a thin type from
the `proc:` vocabulary, and nothing else in the diagram does. The same holds for DMN.
IFML, the architecture, the lifecycles and the deployment facts have no native file to keep
native, so they are written as RDF directly, in small vocabularies the project maintains
and documents against the standards they mirror. Data needs no vocabulary of its own,
because SHACL is one already.

How a payload is found is a decision of its own ([ADR-0003](../../docs/adr/0003-payload-resolution.md)):
a manifest graph maps each payload IRI to a file path, a media type and a checksum, and
the viewer resolves through that graph, never by guessing from the filesystem. A payload
with no manifest entry is a hard error with the IRI in it. Small as it is, this is the
first instance of a pattern you will see in every lesson of this module: nothing is
inferred from context that could instead be stated as a fact and checked.

### One graph per model, one for the seams

The first external review found that the project's example was a single Turtle file with
everything in one graph, and that nothing could say which triples belonged to which model
and which triples were the joins. [ADR-0001](../../docs/adr/0001-named-graph-partitioning.md)
is the answer, and it is the file layout you will write in the lab. A model is one named
graph. The seams, every cross-layer edge in the whole system, live in one more named
graph of their own. The ontologies, the payload manifest and the shapes each have theirs.

Two principles follow from the layout. **Layers stay pure**: a model graph holds only the
triples of its own notation, so the IFML graph is IFML and nothing else, and a renderer
scoped to one graph sees exactly one model. **Seams stay auditable**: "show me every
cross-layer connection in this system" is a query over one graph, not a filter over the
union of everything. The authoring rule is one sentence. A triple whose predicate is in
`seam:` goes in the seams graph; every other triple goes in the graph of the model its
subject belongs to. TriG is Turtle plus a way to write named-graph blocks, which is why
the tutorial writes TriG and why the chat app you read in lesson 2 was one.

### Identity is the element's own id

The second thing the review found was that the project's flagship queries returned no
rows. The BPMN elements had IRIs, but the IRIs were built by a naming convention and
nothing in the graph stated which model an element belonged to, so a property path that
needed to step from a process into its tasks had nowhere to step. The fix had two parts.

[ADR-0002](../../docs/adr/0002-iri-identity-and-migration.md) fixes the identity rules. A
model has a stable base IRI. An element lifted from a native file has the IRI of its model
with the element's own `id` attribute as the fragment, exactly as it appears in the XML, so
`:approval_bpmn#approve_expense` is the task whose BPMN `id` is `approve_expense`. There
are no blank nodes for anything that takes part in a seam or that a query might land on,
because a blank node's identity is local to its graph and a cross-graph query over blank
nodes is a bug waiting to happen. And a rename is a breaking change: either every
reference is updated in the same commit, or an alias is recorded. That sounds strict until
you remember F4 from lesson 4, where a rename in a visual tool changed things nobody could
see. Here a rename is a text diff, and a drift lint ([ADR-0006](../../docs/adr/0006-index-payload-drift-lint.md))
checks that every fragment in the graph exists as an id in the payload and warns about
seam-worthy elements the graph has not lifted.

The second part is a single predicate, `seam:inModel`. Every lifted element states the
model it belongs to. The fragment convention still serves renderer dispatch, but membership
is now data, and data is what a query can walk. The triage of that review says the
predicate "earns all the queries", and lesson 8 will show you why: the path from an event
to the data it can write crosses from a process to that process's tasks through
`seam:inModel`, and without it there is no path.

### The backbone, and what a click does

Three predicates carry the navigation everything else relies on. `seam:detailedBy` joins
an element to the model that elaborates it, and following it is zooming in. `seam:notation`
says which notation that model is in, and therefore which renderer to mount.
`seam:inModel` is membership. The whole descent you walked in lesson 1 is one algorithm
over these three: given the node that was clicked, follow `detailedBy`, read the
notation, mount the renderer, scope it to the target model's named graph.

<Diagram name="descent" caption="The expense app's descent. Every arrow is one seam predicate in the seams graph; each box is an element in its own notation's named graph, rendered by that notation's own tool." />

[ADR-0005](../../docs/adr/0005-navigation-resolution.md) is the decision that keeps that
algorithm small. The original worry was that a viewer shell would become a growing switch
statement over predicate types, with a special case for each join. The answer was to put
the knowledge in the ontology instead. Every seam predicate declares a *reveal mode*
as an annotation on the predicate itself. **Open** replaces the view with the target's
model: `detailedBy`, `triggers`, `completedOn`, `decidedBy`, `lifecycle`. **Nest** draws
the target inside its source: `presents`, `executes`, `schedules`, which is what the
architecture view shows when you open a container in place. **Layer** is everything else,
drawn as an inspector row on the element's page and as a line between stacked planes in
layer mode. The shell's resolution is then a fixed rule: if the clicked element is
detailed by a renderable model, go there; if not, but an open or nest edge leads to one
that is, take that one hop; otherwise show the inspector. One hop, never more, because
being teleported across three layers is disorienting. When an element is detailed by two
models, which is what happened at the Route to Provider task in lesson 1, the viewer asks
rather than picking silently. Every state is a URL, so every view is a link.

The point to carry forward is the last clause of that ADR: making a predicate navigable, or
not, is an ontology change and nothing else. No viewer code knows the names of the seams.
That is the shape of the whole design, applied to one small decision.

### Four rules for a small vocabulary

The seams are the project's one piece of invented vocabulary, and the project outline set
four rules for keeping it small before any of it was written. Few and generic beats many
and precise: precision lives in the layer vocabularies and in shapes over the seams, not
in a growing list of specialised edges. Every predicate must earn a cross-layer query: if
no question needs it, it does not belong. Reuse inside layers, mint only where layers
meet: Hydra for operations, ODRL for policies, SHACL for data, and the layer vocabularies
for everything within a layer. And the backbone stays notation-agnostic, so a Gantt chart
or a deployment map could plug in as one more renderer without a vocabulary change.

The outline's sketch guessed at about fifteen predicates. The ontology holds 37 at the
time of writing, and the growth is instructive rather than embarrassing, because each one
arrived with the question it answers. `seam:storedIn` came from the sequence-diagram
derivation finding that nothing said which container persisted a shape, which also meant
the impact query could not say which data is lost when a node dies. `seam:completedOn`
came from "which screens must a person visit to finish this process". `seam:catches` came
from the need to see which operation error a boundary event routes. `seam:schedules`, the
newest, came from "which schedules stop if this node goes away". Rule two is a discipline
you can check in the git log.

### What the user never sees

One more decision belongs in this lesson because it shapes everything you are about to
write. The product brief names a principle it calls *RDF invisibility*: the person using
the viewer or the generated application never sees Turtle, IRIs or vocabulary names. The
viewer labels things in product language, Screens and interactions, Workflow, Business
rules, Data contract, Policy, and the Questions you pressed in lesson 2 are buttons, not
SPARQL. The semantic stack is the engine, not the dashboard.

The one sanctioned exception is authoring. Until the editor covers everything, a model is
written as TriG by hand, and the brief frames that as what it is: writing code, which
builders already do. That is what the lab asks of you now. You will write a dozen triples,
in two named graphs plus a seams graph, and watch the viewer draw an architecture from
them with no diagram file anywhere.

## Read in the repo

- [Diagrams are views](../../docs/concepts/diagrams-are-views.md) and
  [The seams](../../docs/concepts/the-seams.md). The two concept pages this lesson is built
  on.
- [ADR-0001](../../docs/adr/0001-named-graph-partitioning.md) and
  [ADR-0002](../../docs/adr/0002-iri-identity-and-migration.md). Why one graph per model,
  and what a rename costs.
- The generated [seam predicates](https://metacoding-io.github.io/SemanticSeams/docs/reference/seam-predicates)
  reference, which cannot drift from `seam.ttl` because it is built from it.

## Lab: chapters 1 and 2

Work through [chapter 1, The architecture](../../docs/tutorials/expenses/01-architecture.md)
and [chapter 2, The data](../../docs/tutorials/expenses/02-data.md) of the expense tutorial
in your working file. Two twists:

1. In chapter 1, start the viewer on your file after writing the architecture graph but
   before the seams graph. The badge is red: every model needs exactly one notation, and
   the seams graph is where that fact lives. Add it and look again. That one triple is a
   seam, and it is the first thing the shapes check.
2. In chapter 2, when the deliberate mistake turns the badge red, read the message before
   fixing it: one violation, the model's IRI, and the rule that rejected it. That is a SHACL
   result over the model, and lesson 6 is about it.

Diff your file against `examples/expenses/chapter-02/expenses.trig` when you are done.

## Scorecard

- **F3, closed.** The diagrams in the viewer are rendered from the graph. Your chapter 1
  architecture has no diagram file; the C4 view is a rendering of three triples.
- **F5, closed in part.** The seams graph you wrote is the join between layers, stated as
  facts. The questions it answers come in lesson 8.
- **F4, opened.** Your model is a text file in git. Lesson 11 is about what else that
  needs.

## Further reading

- W3C, *RDF 1.1 TriG*, 2014, for the named-graph syntax you wrote.
- Simon Brown, *The C4 Model for Visualising Software Architecture*, 2018 onward. The
  architecture notation and why it stops at the repository link.
- The project's [research note on reveal modes](../../docs/research/2026-10-15-reveal-modes.md):
  one visual language, three ways to reveal a relation.
