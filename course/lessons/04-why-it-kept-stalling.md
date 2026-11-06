# Lesson 4 · Why it kept stalling

*The six failures that model-based engineering, declarative programming and code
generation shared, with the evidence for each, and the scorecard the rest of the course is
marked against.*

## Outcomes

After this lesson you can:

- State the six failures from memory, give one historical example of each and one test
  that detects it in a tool you are evaluating.
- Say what a fix for each would have to look like, as a requirement rather than a product.
- Read the SemanticSeams project's own first review and recognise four of the six failures
  in a project that had not yet written a line of its viewer.

## The story

### Three histories, one list

Lessons 1 to 3 told three stories: of the notations that were drawn, of the languages that
said what rather than how, and of the generators that wrote the program. Each story had its
own cast and its own decades, and the same few things went wrong in all three. This lesson
collects them. The list is the course's spine from here on: every later lesson ends by
marking which rows it moved, and the [scorecard](../scorecard.md) keeps the running total.

A word on the word *failure*. None of these approaches failed outright. SQL is everywhere.
BPMN engines run banks. Generators write the edge of most systems. The failures below are
the specific places where the promise of "describe once, derive the rest" broke, and where
every generation of tooling has had to make a choice it would rather not make. Knowing them
by name is what lets you evaluate the next tool, including the one this course is about.

### F1 · Some code cannot be generated

**What it looked like.** The CASE generator that produced the whole application until the
application stopped fitting. The 80/20 rule: a generator covers the structure and the last
fifth is where the work is. Protected regions, the Generation Gap, partial classes, each a
way to put the ungenerated fifth somewhere. The low-code script block. Lesson 2's
expressiveness cliff is the cause: every declarative language ends, and what lies past the
edge must be written.

**The symptom.** Generated and hand-written code in one file, or in two files coupled by
names the generator chose. A regeneration that overwrites, or a generator nobody dares run
again. A "customisation layer" larger than the model.

**The test.** Ask where the first `if` about the business lives. If it is in generated
code, the generator is writing behaviour it cannot know, and the next regeneration is a
risk. If it is in a hand-written file the generator never visits, ask how that file is
connected to the model, and whether anything checks the connection.

**What a fix must do.** Decide, per layer, what is interpreted and what is generated, so
that behaviour never needs regenerating. Mark in the model exactly where the hand-written
code begins. Keep generated and owned code in separate files with a declared boundary, and
make something other than a convention check that the owned code still fits.

### F2 · Hand edits never get back into the model

**What it looked like.** Round-trip engineering: forward trips that lost method bodies,
reverse trips that lost intent, and a diagram that became a picture of the code. The
generator abandoned after the first production hotfix went into the output. Model-driven
projects where the model was "updated later", which is never.

**The symptom.** A model that is older than the code. A generated file with a hand edit
that nobody can trace to a decision. Two sources of truth, each wrong about something.

**The test.** Change one line of generated output and ask what should have changed in the
model instead. If the tool cannot answer, every hotfix is a fork.

**What a fix must do.** Record, for every output line, the facts it was made from. Detect a
hand edit by its bytes, not by a marker. Where an edit stands for a change to one fact,
offer to make that change to the model and prove it by regenerating. Where it does not,
refuse and say why, rather than silently accepting a fork.

### F3 · Diagrams are pictures, not models

**What it looked like.** UML in sketch mode, the only mode that survived. Bell's UML fever:
diagrams multiplying and drifting within weeks. Systems engineering's digital thread as a
thread of diagram files. A sequence diagram drawn by hand to explain a feature and never
updated when the feature changed.

**The symptom.** A diagram and the thing it draws disagree, and nothing notices. Two
diagrams of the same system disagree with each other. A layout change is a model change.

**The test.** Delete the diagram file. If information was lost, the diagram was a model
with no other home. If nothing was lost, it was a view, and should have been generated.
Then ask whether two diagrams of the same element share one identifier for it.

**What a fix must do.** Hold the facts once, with stable identity, and render every diagram
from them. Let a native notation keep its native file where an engine needs it, but give
each element that other layers refer to one identifier that both the file and the graph
use. Derive, never author, any diagram whose information is already held.

### F4 · Models do not diff, merge or version

**What it looked like.** Visual programming dying, as the project outline says, "on
diff/merge, version control, and the expressiveness cliff". XMI that did not interchange
between vendors. Projectional editors whose models lived in the tool's store. Rule bases in
a vendor dialect. BPMN engines whose vendor extensions made a process portable in theory.
And the end of Camunda 7's community releases in 2025, with two forks appearing to keep an
open engine alive.

**The symptom.** A model you cannot put in git, review in a pull request, or move to
another tool. A "breaking change" that nothing classifies as breaking. A vocabulary that
changes under existing models with no migration path.

**The test.** Open the model in a text editor and in a second vendor's tool. Then rename
one element and ask what else changed.

**What a fix must do.** Make the model text that diffs line by line and lives in version
control. Keep native notations vendor-extension-free. Version the vocabulary itself, check
the version on load, and ship migrations. Classify a change to the model as compatible or
breaking by rule, not by reading.

### F5 · Every tool draws one layer

**What it looked like.** C4 tools whose bottom of the zoom is a link to a repository. BPMN
modelers that never see the screen that starts the process. IFML's metamodel hooks to
action and data models, which nobody wired. SHACL in its own silo. Lesson 1's conclusion:
the models that survived each survived alone.

**The symptom.** A question that spans layers has no tool to ask it of: "which screens can
write this data", "what breaks if this server goes away", "which tasks move an order out of
this state". The answer, if anyone has it, is in a spreadsheet maintained by hand.

**The test.** Ask the cross-layer question. If the answer requires opening three tools and
a spreadsheet, the layers are not joined.

**What a fix must do.** Put every layer's elements in one graph with one identity scheme,
and name the joins between layers as first-class, queryable facts. Keep the join vocabulary
small, and require each join to earn a question that could not be asked without it.

### F6 · Nobody trusts the generator

**What it looked like.** The rule engine whose ordering had to be debugged by reading the
engine's mind. The generator that produced different bytes from the same model, so that
every diff was noise. The vendor generator nobody could fix. The language model that
produces plausible code nobody can reproduce or verify. Lesson 2's spreadsheet, by contrast,
earned trust by showing every value.

**The symptom.** Generated output nobody reads and nobody checks in. Golden tests that fail
on timestamps. A generator whose preconditions are discovered by stack trace. A draft from
a language model accepted because it looks right.

**The test.** Run the generator twice on the same model and diff. Then ask what happens
when the model is wrong: does the generator refuse before writing, with a reason that names
the fact, or does it write something broken?

**What a fix must do.** Same model, same bytes. Validate the model before generating, and
make a model that passes the validation one that generates. Version the generators and
lock the versions beside the outputs. Trace every line. Derive tests from the model and run
them on anything a person or a language model writes. Never let a nondeterministic step
decide what ships.

### Two things that are not on the list

The expressiveness cliff is not a failure; it is why F1 exists, and a tool that claims to
have no cliff is making a claim about the size of its hatch. The social cost of a new
notation is not a failure either; it is a constraint. People will not learn Turtle to use
an application, and the project outline's answer, a principle it calls "RDF invisibility",
is that they should never have to. The [scorecard](../scorecard.md) explains why neither is
scored.

### The project's own first review

In July 2026, when SemanticSeams was an outline, an ontology and one worked example, two
automated reviewers, one running Claude Code and one running Codex, read the repository.
The triage of their findings is committed, and it is the best single document for this
lesson, because it shows four of the six failures in a project that was designed to avoid
them.

The flagship cross-layer queries returned zero rows. The BPMN elements had been given IRIs
as fragments of their model's IRI, which told the renderer what to draw, but nothing in the
graph said which model an element belonged to, so the property path had nothing to walk.
That is F5: the joins were named but not stated as facts. The seam ontology constrained its
joins with `rdfs:domain` and `rdfs:range`, which infer and do not reject, so there were no
constraints at all. That is F6: the model could be wrong and nothing would say so. There
were no named graphs, so a model and its seams had no boundary, and the identity of an
element across a rename was undefined. That is F3 and F4.

The decisions in the triage became the project's first six decision records and its first
test suite: a membership fact for every lifted element, a shapes file over the model itself,
an executable acceptance test that validates every example and asserts the rows of every
canned query, one named graph per model plus one for the seams, and rules for identity and
for how a click is resolved. Read it with the six failures beside you. Then notice the last
section: "Rejected: none outright."

## Read in the repo

- [`orig_convo/review-triage.md`](../../orig_convo/review-triage.md). The whole document.
  Mark each accepted item with the failure it answers.
- [`orig_convo/product-brief.md`](../../orig_convo/product-brief.md). Who the project is
  for, the job to be done, and the "RDF invisibility" principle. Written in answer to the
  reviewers' first question.
- [Design and coding principles](../../docs/project/principles.md), the eleven design
  principles. Each is a fix for one of the six rows, stated as a rule. You will meet them one
  at a time in modules B and C.

## Lab: a written exercise

No code this time. Take one tool you have used that promised to derive something from a
description: an ORM, an OpenAPI generator, a BPM suite, a low-code platform, a framework's
scaffolding, a UML tool, a language model in your editor. For each of the six rows, write
two or three sentences:

1. Did the failure apply? Apply the row's test.
2. What did the tool do about it, if anything?
3. What did that choice cost you?

Then write one paragraph answering the "what executes it" question from lesson 1's lab about
the same tool. Keep the page. Lesson 12 asks you to do the same exercise for SemanticSeams,
with the scorecard filled in.

## Scorecard

This lesson defines the [scorecard](../scorecard.md). Every row is open at this point in
the course. Lessons 5 to 11 close them, or say how far they get.

## Further reading

- Jon Whittle, John Hutchinson and Mark Rouncefield, "The State of Practice in Model-Driven
  Engineering", *IEEE Software*, 2014. The empirical account of F1, F2 and F6 in industry.
- Bran Selic, "The Pragmatics of Model-Driven Development", *IEEE Software*, 2003. An
  insider's list of what a model-driven tool must get right.
- Martin Fowler, "UmlMode", 2003, and Alex E. Bell, "Death by UML Fever", 2004, for F3.
- Thomas Stahl and Markus Völter, *Model-Driven Software Development*, 2006, on separating
  generated from hand-written code, for F1 and F2.
- Marco Brambilla, Jordi Cabot and Manuel Wimmer, *Model-Driven Software Engineering in
  Practice*, second edition, 2017, chapter 10, on model versioning and interchange, for F4.
- SemanticSeams, [project outline](../../docs/project-outline.md), section 1, for the
  project's own statement of F3, F4 and F5.
