# Lesson 12 · What is still open

*Domain profiles, bounded contexts, SysML v2 interchange, drafted generators, the model as
a context layer for coding agents, and the backlog's honest list. The scorecard, filled
in.*

## Outcomes

After this lesson you can:

- Read the project's backlog and research notes well enough to say which open items bear on
  which scorecard row, and which are new ground the six failures do not cover.
- Explain what a domain profile is, what a bounded context adds above a system, and what
  the project takes from SysML v2 and from domain-driven design without lifting either
  into RDF.
- Repeat lesson 4's written exercise for SemanticSeams itself, with evidence for every row.

## The story

### A record that keeps revising itself

Every earlier lesson pointed at a decision record as evidence. This one points at the
documents that come before a decision, because the frontier of the project is written
down in them. The research notes in `docs/research/` are records, not drafts: each states
a question, gives a short answer, lists what it proposes as backlog rows, and then grows a
dated revision note each time a decision answers part of it, so that the note still says
what was believed when it was written and what became of it. The backlog is the same shape.
Every item has an identifier, a size, its dependencies, the vocabulary it would change and a
status cell that is rewritten when the work lands, and its triage rule is stated at the top:
does the item move the tutorial persona toward `docker compose up`, can it ship alone, and
what does it force the vocabulary to decide.

That matters for a course, because the frontier moves while the course stands still. When
the first draft of this lesson was written, the strategic layer of domain-driven design,
timers and more than one replica were all open. By the time the lesson was finished, all
three had landed, with nine new decision records behind them. So read this lesson as a
snapshot with its date on it, check the backlog's status cells against what it says, and
treat every disagreement as the repository being right.

### Profiles: a method as shapes

The project outline promised, in its earliest pages, that an architecture method could be
a pluggable profile: a vocabulary of component kinds plus a library of shapes over the
model, so that "we follow this method" becomes a claim a validator checks.
[ADR-0018](../../docs/adr/0018-domain-profiles.md) built the mechanism. A profile is a
directory beside the model with one `profile.ttl` that declares a `seam:Profile`; the model
attaches it with one triple in the seams graph, `seam:conformsTo`. The profile is resolved
by its IRI, loaded into its own graph, and is not part of the model, so the model hash and
the lock do not change when one is attached. It may name the classes the editor's palette
offers, the generators the live preview runs, and a shapes file that is merged into the
health check. The rule that makes it a profile rather than a cage is the one lesson 6 met
already: out-of-profile classes are flagged, never refused. A hand edit that introduces one
is still written; the palette only restricts what the editor suggests.

The outline expected Löwy's IDesign to be the first method so encoded, and that is still a
backlog row. The first method to ship was domain-driven design, in
[ADR-0033](../../docs/adr/0033-ddd-profile.md), and it is worth seeing what a method looks
like once it is shapes. Five rules, each a `sh:sparql` constraint at violation level:
every write is governed by a policy; every lifecycle transition is fired by some task;
every access across a context boundary is translated; a shape is written from one context
only; and an aggregate has one lifecycle, one store and one correlation key. Three of those
restate gates and coverage queries the project already had, and a parity test pins the
restatement, so a project that attaches the profile drops the separate gates. The
profile also labels things without typing them: an `sh:Info` shape whose conforming nodes
are shown as a pill, Aggregate, Command, Domain event, with no `rdf:type` triple added to
the model. `seams check` resolves the attached profile and fails on its violations.

[ADR-0036](../../docs/adr/0036-cross-aggregate-invariants.md) then added the second kind of
rule a method needs, one about data rather than model. "An expense is paid once" cannot be
enforced at write time without a lock across aggregates, so it is stated as a profile
shape at warning level with a SPARQL constraint, and the runtime lifts the stored entities
to RDF through their shapes, validates them, and reports the findings in its log and in the
viewer's data-health view. Chapter 11 pays an expense twice and shows the warning, without
having refused the second payment. A method, in this project, is a set of shapes the
validator runs and a set of labels the viewer shows. It is never a mode the tool switches
into.

### Bounded contexts and the strategic layer

The research note on domain-driven design made a finding that sets up the whole of module
D: the tactical patterns were already in the graph under other names. An aggregate root is
a shape with a lifecycle, an identifier and a store; a command is a POST operation reached
by an event; a domain event is a transition or a channel publish; a saga is a
channel-started process. The expense tutorial was a DDD model with two aggregates and two
sagas, written without the words. What the graph lacked was the layer above the system:
nothing owned a language.

Four decisions supplied it, in the two milestones that ran while this course was being
written. [ADR-0030](../../docs/adr/0030-domains-and-bounded-contexts.md) adds an
`arch:Domain`, classified as core, supporting or generic, that contains systems and
bounded contexts, and an `arch:BoundedContext` that owns exactly one ontology and the model
graphs written in its language. [ADR-0032](../../docs/adr/0032-context-map-relationships.md)
adds the context map: a relationship between two contexts with an upstream, the side whose
change can break the other, and one of five types, customer-supplier, conformist,
anti-corruption layer, published language or shared kernel, with at most one relationship
per pair. A read or write across contexts is untranslated unless the element is a
translating operation, the downstream is conformist, or the pair shares a kernel, and the
untranslated ones are the rows of a gate. [ADR-0031](../../docs/adr/0031-lifecycle-on-the-class.md)
moves the lifecycle onto the class, so two shapes of one class cannot name two state
machines, and lets a transition publish to a channel, which is what makes a transition a
domain event in more than name. [ADR-0035](../../docs/adr/0035-aggregate-transaction-boundary.md)
names an aggregate's member shapes with `seam:aggregateMember`, never derived, so that the
runtime can commit them in one transaction and roll all of them back when one fails.

Chapter 11 of the tutorial is where you can see the layer built, and it is the lab this
lesson would have if it had one. Finance wants to own payouts, so the model splits into two
files loaded as one dataset: the expense context keeps the architecture, its own models and
the seams graph; the finance context takes the payout process, the payout decision, the
payment lifecycle, the vendor process and the finance console, along with a finance
ontology imported by version IRI. The expense domain is supporting and the finance domain is
core. The relationship between them is conformist, and the chapter shows that switching it
to customer-supplier makes the check fail, because an untranslated access appears. The Pay
Expense task moves out of the approval process into the payout process, so a payment is
written only from the finance side, and the chapter's line for the result is the strategic
layer in one sentence: the payouts channel becomes the one line between them.
[ADR-0034](../../docs/adr/0034-context-mapper-interchange.md) closes the loop with the tool
DDD practitioners already use: `seams cml export` writes the contexts and their map in the
Context Mapper language, and `seams cml import` reads one back, adding facts through the one
write path, never removing any, and flagging on its error stream every construct it cannot
carry rather than guessing.

### Time and scale

Two things the tutorial could not do until this month were run on a schedule and run on
more than one machine. Both are instructive because each is a fact the graph had no way to
hold, and each got exactly the fact it needed.

[ADR-0037](../../docs/adr/0037-timers-and-scheduling.md) lifts BPMN timers the way lesson 5
lifted everything else. A timer start event is a `proc:TimerStartEvent`, which starts a
process nobody clicks and for which the generator writes no route. A timer inside an
instance, or on a user task, is a `proc:TimerCatchEvent`; chapter 9's reminder, a
non-interrupting boundary on the approval task that fires after 48 hours and leaves the task
open, is one. The expression stays in the XML, as an error boundary's code does, and only
quoted ISO 8601 literals with a fixed offset are accepted, because the engine would
otherwise read a timer expression as Python. One new seam, `seam:schedules`, names the one
container that runs a process's timer starts, listed rather than derived from `executes`
because a process may run in several containers and the one that keeps time is a decision.
The firing is claimed by inserting a row keyed by the start event and its due time in the
same transaction that starts the instance, so when two replicas wake at the same moment one
of them finds the row taken and logs that the timer was claimed elsewhere.

[ADR-0038](../../docs/adr/0038-shared-stream-channel.md) is why that mattered.
The chat app had declared three replicas since its first model, and the compose generator
had capped it at one, with a comment saying so, because two pieces of state lived in the
runtime's process: the live-update stream and the launched instances. The decision follows
the store. On PostgreSQL the stream becomes a listen-and-notify channel with every frame
also written to a table, so a frame is either stored and announced or neither; on SQLite it
stays in process, and asking for more than one replica on a SQLite store is a generator
error. Instances resume from the store on any replica, and the user-task row is the
cross-replica claim. The cap is gone, and the end-to-end test now runs the chat app on three
replicas. Notice what did not happen: no new deployment fact. The bus kind follows the store
kind the model already states, because the project's reflex is to derive from facts it has
before it mints one it does not.

### SysML v2: export, borrow, do not lift

Lesson 1 ended its history at SysML v2, and the project's note on it is a model of how to
read a neighbouring standard. The questions were three: does it offer diagrams a user here
should author, can it be generated from the graph, and does it cover ground the project has
not thought about. The answers: no, because its views are queries plus renderings, which is
what this project already does; yes, and the textual notation is worth more than Mermaid
because one file covers every layer and opens in the SysML tools; and yes, in eight places,
of which requirements with their satisfaction and verification links, concerns and
stakeholders, allocation as a single relationship, variation points, individuals and
snapshots for the as-deployed and as-executed graphs, and parametric constraints for
non-functional budgets are the ones that matter. The note's closing rule is the one to
remember from lesson 5: do not lift the metamodel into RDF, and do not wait for an RDF
standard. Five backlog rows carry the work, an exporter, a requirements vocabulary, a
coverage table, a snapshot vocabulary and a model API shaped like the standard's own, and
all five are proposed and unscheduled. That is a frontier in the plain sense: mapped,
costed, not yet walked.

### Drafted generators, and what the project is for

Lesson 9 let a language model draft a handler under tests the model derived.
[ADR-0029](../../docs/adr/0029-llm-drafted-generators.md) applies the same discipline one
level up, to the generators themselves. `seams draft-generator` hands the provider command
a reference output, the model's element names and the scaffold's module, all as quoted
data, and the answer must be one JSON object holding an extract step, a template and a
golden. The three are assembled into the scaffold a new generator starts from, in a scratch
directory, and the package is kept only when the scaffold's four tests pass there: the
golden matches, the output is deterministic, it parses, and the sources name the files.
Two further checks are the project's rules made mechanical: the template may restate no
model label from the reference, and it may hold no logic, only names and loops. What is
written is then an ordinary owned generator, and continuous integration never calls the
provider.

The research note that reviewed the product from a systems-engineering seat says what all
of this adds up to. Its verdict on the present is blunt: the authoring experience is the
weakest part, and "the engine is ahead of the dashboard". Its ten interface proposals,
from sentence editing in place of IRI boxes to a storm board as the blank page, a questions
cockpit as the landing page, a role lens, a scenario player and the diff drawn on the
canvas, are all proposed and none built, and the note's one bet is to do two of them before
any further generator or vocabulary work. Its verdict on the future is the sentence this
course has been working toward. When language models write most code, the model is the
specification that constrains them and the oracle that tests their output, and the product
is "the governed context layer for agentic coding", with the digital thread that MBSE tools
promised and application developers never had. The domain-vocabulary note makes the same
point from the other end: a glossary handed to a coding agent must be a projection of the
model, never its source, because a prose glossary maintained beside a model is drift by
construction. Its two rows, a glossary generator and a check that hand-written specs use
only terms the model declares, are proposed too.

### The honest list

What the graph still cannot hold is listed in the backlog's final section, and it is short
enough to read in full. Observed behaviour as its own named graph, so that timing and dead
elements become queries. Service-level objectives checked against those observations. Data
classification, so that "which screens show personal data to which roles" is a question.
A convention for external systems and inbound webhooks beyond the one SemPKM case.
Migrations of stored data generated from the shape diff. Rationale links from a decision
record to the elements it decides. Interchange exports to the C4 and sequence tools people
already use. An event-storm import. Imports from existing API, schema and compose files,
parked as a non-goal until the exports show what an import must carry. And a model-level
merge, which the project does not list because its answer today is text and git, and that
answer is honest about its limits. Three milestones carry most of these, data care,
observed behaviour and interchange, and all three are planned and unstarted.

None of these reopens a scorecard row. Each is a kind of fact the graph does not yet hold,
and the pattern of the last month says how it will be added: a research note that asks
what the question is, a vocabulary term that earns it, shapes that check it, a view that
derives from it, and a chapter that makes you write it.

### The scorecard, filled in

Lesson 4 asked you to test a tool you had used against six failures, and the scorecard has
been marked lesson by lesson since. Read it now as a whole. Code that cannot be generated
has a marked place, a typed stub, tests the model derives, and a language model allowed
behind the stub but never past the tests. Hand edits reach the model through a trace,
for literals and form fields, and are refused with a reason otherwise. Diagrams are drawn
from the graph, and the ones that used to be authored by hand are derived with their gaps
printed. Models are text in git with versioned vocabularies, migrations and a change
classifier, and still no merge beyond text. Every layer is one graph, joined by a small
vocabulary whose every term earned a question, now with a strategic layer above the system.
And the generator is trusted because its bytes do not change unless facts do, its
preconditions are shapes, its outputs are locked and traced, and nothing nondeterministic
decides what ships.

Two of those rows say "in part", and the course is better for saying so. The lab asks you
to write the same assessment yourself, with a file, a decision record or a test behind
every claim, and then to say what the project should do next. The backlog's triage rule
is the standard your answer will be read against, and a pull request against it is how the
answer is given.

## Read in the repo

- [`docs/backlog.md`](../../docs/backlog.md), the "Not yet scheduled" section and the
  suggested sequence at the end, where M031 to M033 are planned and unstarted.
- [Chapter 11, A second bounded context](../../docs/tutorials/expenses/11-bounded-contexts.md),
  and [ADR-0033](../../docs/adr/0033-ddd-profile.md), the DDD profile's five rules.
- [Product review and UI ideas](../../docs/research/2026-11-03-product-review-and-ui-ideas.md),
  written from a model-based systems engineering persona.
- [Domain-driven design, read against the graph](../../docs/research/2026-11-02-domain-driven-design.md)
  and [SysML v2, read against the graph](../../docs/research/2026-11-02-sysml-v2.md), the
  short answers.

## Lab: the exercise, again

Repeat [lesson 4's written exercise](04-why-it-kept-stalling.md#lab-a-written-exercise) for
SemanticSeams. For each of the six rows: does the failure apply, what does the project do
about it, and what did that choice cost? Point every claim at a file, a decision record or a
test you touched in a lab. Where the [scorecard](../scorecard.md) says "closed in part",
find the backlog item and say whether you agree with its priority.

Then write one paragraph on what the project should do next, and why. If you want it
considered, the backlog's triage rule is stated at its top; open a pull request against
`docs/backlog.md` in its format.

## Scorecard

Filled in. The [scorecard page](../scorecard.md) is the course's summary; your exercise is
your own. Where they disagree, one of them is wrong, and the repository decides which.

## Further reading

- Juval Löwy, *Righting Software*, 2019, for the IDesign method the outline's first profile would encode.
- Eric Evans, *Domain-Driven Design*, 2003, part IV, strategic design, for bounded contexts
  and context maps.
- Object Management Group, *SysML v2*, 2025, part 1, section on view definitions.
- The project's [EventCatalog levels](../../docs/research/2026-10-15-eventcatalog-levels.md)
  and [reveal modes](../../docs/research/2026-10-15-reveal-modes.md) notes, for how the
  viewer will show more without showing everything.
