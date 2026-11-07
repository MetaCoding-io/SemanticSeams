# Lesson 8 · Questions no single tool can answer

*The query catalog, rows that continuous integration asserts, and diagrams derived
rather than drawn.*

## Outcomes

After this lesson you can:

- Read each question in the catalog as a property path over the seams and say which join
  it could not be asked without.
- Explain how a question becomes a viewer button, a test with pinned rows and a reference
  page, with one `.rq` file as the source of all three.
- Derive a sequence diagram and an event storm from a model, and argue why neither should
  ever be authored.

## The story

### The second payoff

Lesson 5 joined the notations and lesson 7 ran them. This lesson is the return on that
investment, and the project outline calls it "arguably bigger than the zoom": questions
that span layers become a single query. "Which screens can eventually write this data"
needs the interface layer, the process layer, the decision layer and the data layer at
once, and no tool that draws one layer can hold both ends of it. In SemanticSeams it is a
SPARQL property path through the seams, written once, in one file.

That file does three jobs. The viewer offers the question as a button on every element of
its focus type, labelled in product language, with the results rendered inline and each
value linked to its own view. The test suite runs the same file against every worked
example and asserts the exact rows it returns. The docs site renders the same file on its
query reference page on every build. One source, three uses, and nothing restated: adding
a question is adding a `.rq` file with a free focus variable and a row in the catalog's
table.

Four questions ship as the catalog proper. Which UI events can eventually write this data
shape, and through which task. What breaks, containers, processes and data, if this
deployment node goes away. Which process tasks may move an entity out of this state. Which
screens can each role use to eventually write this data shape, which is the compliance
question you pressed at the end of chapter 7. Three more are coverage questions, asking
what the model declares that nothing exercises, and they return to lesson 11.

### Anatomy of a question

Open `what-writes-shape.rq` again, from lesson 2, and read it now with the seams in mind.
It starts at an `ifml:Event`. Then it repeats, one or more times, any of four hops. The
first is `seam:triggers`, then `seam:detailedBy`, then the inverse of `seam:inModel`: from
the event to the process it triggers, from the process to the BPMN model that details it,
and from that model to every element that belongs to it. That last inverse step is the
one the first review found missing, and it is why membership had to become data. The
second and third hops are `seam:decidedBy` and `seam:invokes`, down into a decision or an
operation. The fourth is the asynchronous one: `seam:publishesTo` a channel, the inverse
of `seam:subscribesTo` into the message start event that listens on it, `seam:inModel` up
to that process's model and its inverse down into the elements of the subscribed process.
Wherever the path ends, the last triple asks whether that element `seam:writes` the
shape.

Two things about the path are worth noticing. The first is a comment in the query itself:
control flow stays in the BPMN XML, so once the path is inside a process it treats every
element of that model as reachable. The query calls that "the honest approximation of
downstream in that process", and it is an example of the project saying exactly what a
derived answer does and does not know. The second is the free variable. The shape is left
unbound, the viewer binds it to whatever you are looking at, and the same file answers for
every shape in every model.

The impact question works the same way in the other direction, from a deployment node
through `seam:deployedTo` to the containers on it, through `seam:executes` to their
processes and through `seam:storedIn` to the shapes whose instances live there. That last
hop is the one lesson 5 mentioned: before `seam:storedIn` existed the question could name
containers and processes but not data, and the predicate was minted to close that gap.

### Rows that cannot silently vanish

The project's original sin, from lesson 4, was a flagship query that returned no rows and
nothing that noticed. The acceptance test is the permanent answer. For every question and
every worked example it asserts the exact rows, and a change to the ontology, an example
or a query that breaks a traversal fails continuous integration instead of returning an
empty table that looks like "nothing to report". When you add a question in the lab, you
will pin its rows the same way, and from then on the question is a contract.

Gates invert the idea. A gate is a `SELECT` that must return no rows: every UI event that
can write data with no policy governing it, every cross-context call with no translating
operation. A project lists the gates it wants in its `seams.toml`, and `seams check`
runs them and reports every row as a problem. The coverage questions are gates of the
same shape, and one of them cannot be SPARQL at all: "which start-to-end paths through this
process does no scenario exercise" needs the sequence flows, which live only in the BPMN
XML by the execution decision of lesson 7, so `seams coverage` walks them in Python and
joins the paths with the scenarios. The project says so rather than pretending the graph
holds what it does not.

### Derive, never author

The second half of this lesson begins with the question every developer asks when they
first see the project: where are the sequence diagrams? The research note that answers it
went through all fourteen UML diagram types one by one, with one test for each: is the
information already in the graph, and if so, who would read the diagram? Class diagrams
are the shape graph, drawn in class-diagram style. Deployment diagrams are the `deploy:`
facts. Activity diagrams are superseded by BPMN, state machines by the statecharts, use
cases by the compliance query drawn as a picture. For every one of the fourteen the
verdict was either "already covered by a pillar notation" or "derive", and the note's
conclusion is the strongest statement of F3 in the repository: authoring any of them by
hand would create a second source of truth for facts the graph already holds, which is
exactly the drift the product brief promises to end.

So the sequence diagram is derived. `seams sequence <event>` walks from an IFML event
through the graph: the actor comes from the policy that governs the event, the lifelines
from the containers that present, expose, store and consume, the messages from
`seam:submitsTo`, `seam:invokes` and `seam:publishesTo`, the payloads on each arrow from
the accepted and returned shapes, and the step order from the BPMN sequence flows, read
from the XML the way the runtime reads them. Where a process has exclusive gateways the
deriver writes one diagram per path rather than one diagram full of `alt` blocks, which is
why chapter 8's approval process yields five diagrams for one event. And where the graph
cannot place an arrow, the diagram says so, as a `%% gap:` line naming the missing fact.
A gap is not a drawing problem. It is a model audit, and the first derivation of the chat
app found two: nothing said which container stored a shape, and nothing said where the
LLM's delta stream was published. Both became facts.

The same lifelines draw a second diagram, *as executed*. The runtime's worker records a
trace row per BPMN element it runs, and `seams sequence <event> --trace RUN` turns those
rows into a diagram of what one instance actually did: the decision with the value it
returned, each transition with the state it reached, the identity that completed a user
task. A row the graph cannot place is a gap here too, so a run that drifted from the
model shows where. As designed and as executed share the actor, interface and API
lifelines, which is what makes them readable side by side.

The event storm is derived the same way, with no vocabulary of its own. Every sticky-note
colour of the workshop format has a home in facts the graph already holds: actors from
lanes and policy assignees, commands from the events that trigger a process and the forms
that complete its tasks, aggregates from the shapes a step writes, domain events from the
transitions it fires, decisions, channels, started processes and read models. `seams storm <process>`
prints the timeline, and a fact the view expects and cannot find is listed as a gap rather
than dropped.

### What a diagram is now

Step back and the module's four lessons make one claim. A diagram is a query bound to a
renderer. The architecture view is a query over the C4 facts. The BPMN diagram is the
native file, found through a manifest and rendered by the standard's own tool. The
sequence diagram and the event storm are queries over several layers at once, with their
gaps printed. The questions under the viewer's buttons are queries with the rendering
left out. SysML v2 reached the same conclusion from the systems-engineering side, as
lesson 1 noted, and calls them view definitions. Here they are files in a directory, with
their rows pinned by a test.

That is the whole answer to F3 and F5. A diagram that is derived cannot drift from what
it draws, because it is drawn from it every time. A question that spans four layers is one
file, because the four layers are one graph. The lab asks you to add both: a question of
your own, pinned, and a derived diagram of your own model, with its gaps read as the
to-do list they are.

## Read in the repo

- [`docs/queries/README.md`](../../docs/queries/README.md). The catalog, the gates, the
  coverage queries and the complexity measures.
- [`tests/test_acceptance.py`](../../tests/test_acceptance.py), the `what_writes_shape`
  tests. The exact rows, pinned.
- [UML coverage, derived diagrams, and what a builder still
  lacks](../../docs/research/2026-10-29-uml-coverage-and-gaps.md), sections 1 and 2.

## Lab: ask a new question, and derive two diagrams

1. **Derive.** On your chapter 7 file, derive the sequence diagrams for the submit event
   and the event storm for the approval process, and read every `gap:` line:

   ```sh
   seams sequence :submit_expense --model work/expenses.trig
   seams storm :approval_process --model work/expenses.trig
   ```

   The exact event and process names are in your file; the chapter 8 text shows the
   command on the checkpoint. Each gap is a fact the model does not state. Decide for each
   whether it is a fact worth adding.

2. **Ask.** Write a question the catalog does not have. A good first one: *which decision
   tables does a given role's screen eventually reach?* Model it on
   `screens-by-role-writing-shape.rq`, which was itself added this way. Follow that query
   through the repository to see what adding one touches: the `.rq` file and its row in the
   catalog's README, the copy the `seams` library bundles (a test compares the two byte for
   byte), the pinned rows in `tests/test_acceptance.py`, and the entry in
   `viewer/queries.py` that gives it a label and a focus type.

3. **Pin.** Run your question against the chat app and chapter 7, write its expected rows
   into the test, and run the suite. Then rebuild the docs locally (`cd docs && uv run npm
   run build`) and find your question on the generated query reference page.

## Scorecard

- **F5, closed.** The questions are the proof that the joins are facts. Your new question
  used only predicates that already existed; if it had needed a new one, that predicate
  would have earned its place by the second design rule.
- **F3, closed.** The sequence diagram and the event storm are derived from the graph and
  cannot drift from it. Where they are incomplete, they say so.
- **F6, moved.** Pinned rows in continuous integration are how a question stays true.

## Further reading

- W3C, *SPARQL 1.1 Query Language*, 2013, section 9, property paths.
- Alberto Brandolini, *Introducing EventStorming*, for the workshop the derived storm
  reproduces, and the project's [DDD research note](../../docs/research/2026-11-02-domain-driven-design.md),
  section 4, on deriving it.
- The project's [EventCatalog levels note](../../docs/research/2026-10-15-eventcatalog-levels.md):
  each level is a question the reader is asking.
