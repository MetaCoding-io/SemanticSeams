# Lesson 1 · Drawing software

*From flowcharts to model-based systems engineering. The notations that survived had an
engine.*

## Outcomes

After this lesson you can:

- Place the main software notations of the last seventy years on a timeline, and say for
  each one what question it answered and for whom.
- Explain why UML "failed socially" while BPMN, DMN and the relational schema did not, in
  terms of one property: whether a machine executed the model.
- Walk the four-notation descent in the SemanticSeams viewer and name, for each notation
  you pass through, what executes it.

## The story

### Pictures before programs

The first diagrams of software predate the first stored-program computers. Herman
Goldstine and John von Neumann drew flow diagrams in 1947 to plan the programs of a machine
that did not yet exist, and for the next three decades the flowchart was how a program was
designed, reviewed and documented before it was coded. It worked because it answered one
question, "what happens next", for one audience, the programmer, and because the mapping
from boxes to statements was direct enough that a careful person could keep the two in
step by hand.

Structured methods in the 1970s added diagrams for the things flowcharts could not say.
Michael Jackson's structured programming (1975) drew the structure of the data a program
consumed and derived the program's structure from it. Tom DeMarco's structured analysis
(1978) drew data flows between processes and stores. Peter Chen's entity-relationship
model (1976) drew the data itself. David Harel's statecharts (1987) drew the lifecycle of
a thing, with nesting and concurrency, in a notation small enough to be executed.

Two of these outlived the others, and the reason is worth noticing. The entity-relationship
diagram survived because a database schema could be generated from it, and the schema was
then the thing that ran. The statechart survived because Harel's semantics were precise
enough for a tool to execute the diagram directly, and tools did. Data-flow diagrams, by
contrast, described a system without ever being the system, and when the code moved on the
diagram stayed where it was.

### The method wars and UML

The object-oriented 1990s produced a notation per author: Grady Booch's method, James
Rumbaugh's Object Modeling Technique, Ivar Jacobson's use cases. The three merged their
notations at Rational Software, and the Object Management Group adopted the result as the
Unified Modeling Language in 1997. UML 2.0 (2005) had fourteen diagram types, a metamodel
defined in the Meta-Object Facility, and an interchange format, XMI. Rational Rose sold
round-trip engineering: draw a class diagram, generate the class skeletons, edit the code,
reverse-engineer the diagram back.

Martin Fowler described, in 2003, three ways people actually used UML: as a *sketch* on a
whiteboard, as a *blueprint* handed to programmers, and as a *programming language* from
which the system was generated. Only the sketch became common. Marian Petre's interviews
with practitioners (2013) found UML used selectively and informally, if at all, and the
tools that promised blueprints and generation sat unused. Alex Bell's "Death by UML
Fever" (2004) catalogued what happened on projects that tried harder: diagrams multiplied,
drifted from the code within weeks, and were maintained for their own sake. The
SemanticSeams project outline sums this up in three words, "UML failed socially", and the
word *socially* is exact. The notation was not wrong. It was never the thing that ran, so
nobody was paid to keep it true.

### Model-Driven Architecture

The Object Management Group's answer, in 2001, was Model-Driven Architecture. A
platform-independent model would be transformed into platform-specific models, and those
into code, by transformations written in a standard language (QVT, 2008). Executable UML
(Mellor and Balcer, 2002) and later the Foundational UML subset (2011) gave action
semantics to a part of the language so that models could run. The ambition was that the
model would be the asset and the code a derived artifact.

It worked in places, and the places are instructive. Empirical studies of model-driven
engineering in industry (Hutchinson, Whittle and Rouncefield, 2011 and 2014) found success
where teams used small, domain-specific languages with generators they owned, and failure
where they tried to model everything in UML and generate from a general-purpose tool.
Interchange through XMI was lossy between vendors. Generated code covered part of the
system, and the rest was written by hand and then fought with every regeneration. The model
was rarely complete enough to run, so the code became the truth again. Lesson 3 returns to
the generation half of this story, and lesson 4 to the failures.

### Systems engineering takes the model seriously

Where software engineering drifted back to code, systems engineering kept going. SysML
(2007), a UML profile for systems, became the notation of model-based systems engineering
in aerospace, automotive and defence, where the system is not software and the model is
the only place the whole thing exists. The ambition is the "digital thread": one model
from requirements through design to verification, with every artifact traced to it.

The critique from inside that community is that the thread was often a thread of diagram
files, and that a diagram file is still a picture. SysML v2, adopted by the Object
Management Group in July 2025 and published that September, answers it directly. It has a
textual notation, a standard API with projects, commits and branches, and no diagram types
in the UML sense. It has *view definitions*: a query over one model plus a rendering. The
SemanticSeams research note on SysML v2 puts it plainly: this is "diagrams are views"
stated by a standards body. Lesson 12 comes back to what the project takes from it.

### The process stack: models with engines

While UML was failing socially, a different family of models was quietly succeeding, for
the reason the entity-relationship diagram had. The Business Process Model and Notation
started outside the Object Management Group (2004), moved inside it, and in version 2.0
(2011) gained an execution semantics and an XML interchange format precise enough that an
engine could run the diagram. The Decision Model and Notation (2015) did the same for
decision tables, which business people had been drawing since the late 1950s: a DMN table
is a pure function from inputs to outputs with a declared hit policy, and an engine
evaluates it. The Case Management Model and Notation (2014) covered the unstructured
remainder. The Interaction Flow Modeling Language (2013) modelled the user interface, with
hooks in its metamodel for referencing an external action model and an external data
model.

These models lived because engines ran them: Activiti, jBPM, Camunda, Flowable, and in
Python, SpiffWorkflow. They also became captive to those engines. Vendor extensions
crept into the XML; a process modelled in one tool did not always run in another; and
when Camunda ended community releases of Camunda 7 in 2025, two forks appeared to keep the
engine alive. IFML's hooks to action and data models were, as the project outline notes,
never wired up by anyone. Each surviving model sat in its own silo, with its own engine,
its own editor and its own file.

### The thesis

Put the timeline side by side and one property separates the notations that lived from the
ones that became documentation: **a machine executed the model.** The schema ran. The
statechart ran. The BPMN and the DMN ran. The class diagram, the sequence diagram and the
data-flow diagram described something that ran, and were abandoned the moment the
description cost more than it returned.

That thesis has a corollary that the rest of this course rests on. If the models that
survive are the ones with engines, then a project that wants one model of a whole
application should not invent a new notation and a new engine. It should keep the surviving
notations, keep their engines, and solve the problem none of them solved: joining them.
Lesson 5 is about the joins.

## Read in the repo

- [`docs/project-outline.md`](../../docs/project-outline.md), sections 1 and 5. The problem
  statement and the landscape survey, written in July 2026 before any code existed. Notice
  which tools it names and what each one stops at.
- [SysML v2, read against the graph](../../docs/research/2026-11-02-sysml-v2.md), the
  "Short answer" section. A standards body arriving at the same conclusion from the other
  direction.
- [UML coverage, derived diagrams, and what a builder still
  lacks](../../docs/research/2026-10-29-uml-coverage-and-gaps.md), section 1. All fourteen
  UML diagram types, each marked as covered by a pillar notation or derivable from the
  graph, and the argument that authoring them would create a second source of truth.

## Lab: the descent

Nothing is written in this lab. You walk the canonical descent in the viewer and, at each
notation, answer one question: *what executes this?*

1. Start the viewer on the chat app, as in [Before the first lesson](../setup.md), and open
   <http://localhost:8000>. You are on the C4 architecture view.
2. Click **Chat Web Interface**. You are on an IFML interaction model: pages, components,
   events, flows. Note the renderer changed.
3. Click **Send Message**. You are on a BPMN process, drawn by bpmn-js from the native XML.
4. Click **Route to Provider**. The viewer asks which of two models to open. Choose the DMN
   model and open its decision table, drawn by dmn-js.
5. Go back and choose the data model instead. You are on a SHACL shape graph.

Now fill in this table from what you saw and from [What runs where](../../docs/tutorial.md#8-what-runs-where)
in the quick start:

| Notation | What executes it in a running SemanticSeams app | Generated or interpreted? |
|---|---|---|
| C4 architecture and deployment | | |
| IFML interaction | | |
| BPMN process | | |
| DMN decision | | |
| SHACL shape | | |

[Using the viewer](../../docs/guide/the-viewer.md#the-descent) walks the same descent with
screenshots if you get lost. Keep your table: lesson 7 explains the pattern in the right-hand
column, and lesson 4 asks you to apply the "what executes it" question to a tool you have
used.

## Scorecard

The scorecard is introduced in [lesson 4](04-why-it-kept-stalling.md). This lesson seeds
three of its rows:

- **F3, diagrams are pictures.** Fowler's sketch mode and Bell's UML fever are the
  historical evidence. A diagram nothing executes drifts.
- **F4, vendor capture.** The process stack survived by having engines, and became captive
  to them.
- **F5, one tool per layer.** C4 tools stop at the repository link, BPMN modelers never
  see the screen that starts the process, IFML's hooks were never wired, SHACL sits alone.

## Further reading

- Herman H. Goldstine and John von Neumann, *Planning and Coding of Problems for an
  Electronic Computing Instrument*, 1947. The first flow diagrams.
- David Harel, "Statecharts: A Visual Formalism for Complex Systems", *Science of Computer
  Programming*, 1987.
- Martin Fowler, "UmlMode", bliki, 2003. Sketch, blueprint, programming language.
- Alex E. Bell, "Death by UML Fever", *ACM Queue*, 2004.
- Marian Petre, "UML in Practice", *ICSE*, 2013.
- John Hutchinson, Jon Whittle, Mark Rouncefield and Steinar Kristoffersen, "Empirical
  Assessment of MDE in Industry", *ICSE*, 2011; Jon Whittle, John Hutchinson and Mark
  Rouncefield, "The State of Practice in Model-Driven Engineering", *IEEE Software*, 2014.
- Object Management Group, *MDA Guide*, version 1.0.1, 2003; *BPMN 2.0*, 2011; *DMN 1.0*,
  2015; *IFML 1.0*, 2015; *SysML v2*, 2025.
- Marco Brambilla, Jordi Cabot and Manuel Wimmer, *Model-Driven Software Engineering in
  Practice*, second edition, 2017. The standard textbook, and a fair account of what
  worked.
