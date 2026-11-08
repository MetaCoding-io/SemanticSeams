# Lesson 11 · Same model, same bytes

*Determinism, versioned generators and vocabularies, environments and generated compose
files, scenarios as tests, and data that outlives the application. The answer to the fourth
and sixth failures.*

## Outcomes

After this lesson you can:

- State what "same model, same bytes" requires of a generator and show it with one command
  and an empty diff.
- Explain how a vocabulary is versioned, how a model declares the versions it is written
  for, and what happens on load when they differ.
- Deploy the expense app with generated compose files for two environments, check its
  running containers against the model, and move its data into a second store with no code
  change.

## The story

### Same model, same bytes

Principle 6 is the shortest rule in the project and the one the most machinery depends on.
Every collection is sorted explicitly, never left to graph or dictionary order. No output
carries a timestamp, an absolute path or a host name. The model is identified by its
content hash, which covers the TriG file and every native payload, and every generated
file records it: a comment in a template, a constant in a route module, a variable in a
compose file. The runtime compares that hash with the model it is given and refuses to
start a module generated from a different one, so a stale module cannot run against a new
decision table by accident. You saw the consequence in lesson 7, when lowering a
threshold changed nothing in the generated code but the hash lines, and in lesson 3, when
regenerating an unchanged model produced an empty diff. That empty diff is what makes a
golden test meaningful and a pull request readable, and it is the first half of trust.

The lock file is where determinism becomes a record. `seams.lock` is sorted-key JSON
with a trailing newline, so the same model and generators give the same bytes, and it
holds for every output the generator that wrote it, the generator's version, the model
hash, the file's hash and the model elements it came from. `seams generate` runs every
generator in memory and writes files only if all of them succeed. `seams check` writes
nothing and reports every way the committed outputs can disagree with the model: a missing
output, a stale one, a hand-edited one whose bytes match neither the lock nor the
generator, an orphan the lock no longer lists, a lock that is out of date, and a flagged
lock from a lenient run. Continuous integration runs it on every example, which is how a
hand edit to a generated file fails before it reaches the main branch.

### Generators with versions and preconditions

[ADR-0016](../../docs/adr/0016-generator-protocol.md) makes a generator an object rather
than a function: a name, a version recorded per output in the lock, an extract step that
reads the model into a frozen view and does every check and computation, a render step
that turns the view into files and touches no model, the model elements each file comes
from, and the shapes the model must conform to before the generator runs. A generator from
another package registers under one entry-point group and runs the same way, lists in the
same project file and is locked with its own version, so `seams check` can report its
outputs as stale or hand-edited too. The registry refuses an entry point that does not
load, or loads the wrong thing, or repeats a name, with a message naming the distribution.

One amendment is worth noticing because it is determinism being honest with itself. The
Dockerfile generator needs the workspace members from the root project file, which is not
a model fact. Rather than hard-code them or hide the dependency, a generator that reads a
file beyond the model names it, so that every tool that regenerates in a scratch copy,
the write-back and the copilot, copies that file too. The output is the same for the same
model and the same declared inputs, and the rule says so.

### Versions for the vocabulary itself

Lesson 4's test for F4 was to rename one element and ask what else changed.
[ADR-0021](../../docs/adr/0021-vocabulary-versions.md) applies that test to the language
the models are written in. Each vocabulary declares a version IRI, major and minor, with
no patch level: a change either leaves existing models valid or it does not. A model
declares the versions it was written for by importing them in its manifest graph, which is
why every chapter of the tutorial has you write those `owl:imports` lines. Loading a model
checks them: the same version proceeds, a newer one is refused, an older one is migrated
in memory by one small SPARQL Update step per version boundary, and `seams migrate` writes
the migration into the files through the one write path, keeping the comments. A term is
deprecated at warning level before it is removed, so a model gets told before it breaks.
The idea comes from the generator-kit note's reading of Boersma on versioning a DSL, and
it is what let the vocabularies grow from 1.0 to the versions you imported in the lab
without stranding a single example.

`seams diff` applies the same classification to the model. Between two models, or two
git revisions of one, it classifies each shape and contract change as compatible or
breaking: a shape added is compatible, a required property added is breaking, a datatype
changed is breaking, a rename recorded with an alias is compatible. `seams plan` writes
the same analysis as a Markdown change plan, breaking changes first, and continuous
integration posts one on every pull request that changes a model. In the lab you run the
diff between your chapter 7 and chapter 8 files, then remove a required field and run it
again.

### Environments are facts, and compose files are projections

Chapter 8 is where the model deploys, and [ADR-0015](../../docs/adr/0015-environments.md)
records how the project got there. Before it, the compose generator wrote one
production-shaped file, and three hand-written override files made the result run on a
laptop. The decision inventories every line of those overrides and finds each one a home: a
development fact, a generator rule derived from facts the model already states, or a
correction to a shared fact the model had wrong. Nothing was left without one, and the
overrides were deleted. A model now declares two environments, and a container states a
fact for one of them through an override node that names the environment and carries the
replacement, using the same predicates a container uses. In the lab the API's development
override swaps a published image for a local build, and a secret reference for a secret
file; the store's swaps a secret for a plain value. The generator writes one compose file
per environment, each header naming its environment and the model hash, and the chapter's
own description of the result is the one to quote: the development environment, generated,
with nothing written by hand.

Two commands close the loop with the running system. `seams status` reads each container's
health endpoint and reports it as current, behind by so many model changes, ahead or
unreachable, against the lock's history in git. `seams secrets` lists every configuration
key and secret the model names for an environment, checks that each exists as a file, an
entry in the project's `.env` or a Docker secret, and prints present, missing or unchecked
without ever reading a value. In the lab the production run reports two missing and exits
with an error, which is the point: the model knows what production needs before production
does.

<Diagram name="facts-to-running" caption="From facts to a running system. The model's environment facts feed the compose generator, which writes one file per environment and records the lock. Docker brings the development file up; seams status compares each container's model hash with the lock's history, and seams secrets checks that the keys production names exist, without reading a value." />

### Where the data lives

The storage decision belongs here too, because it is the model answering a question that
used to live in a connection string. A shape is `seam:storedIn` a store container, the
store has a kind, and the executing container reaches it through a binding that
`seam:connectsTo` it, with the value read from the environment variable the binding names.
Chapter 8 moves the expenses, approvals and payments into PostgreSQL with those three
facts, and the runtime opens the right store from them. The chapter picks a different
variable name from the chat app's on purpose, to show that nothing reads the store from
the key's name. Drop the storage fact for one shape and the host refuses to start, naming
the shape and the predicate. And because `storedIn` ends at a container that is deployed
to a node, the impact question from lesson 8 now answers all the way down to the data:
what breaks if this node goes away, containers, processes and shapes alike.

### Data outlives applications

Principle 9 is the direction the whole third module points: the domain model and its data
are the long-lived asset, and applications are built on them. Chapter 9 gives the expense
model an ontology, a `seam:Ontology` graph that declares what an expense, a payment and an
approval *are*, as classes extending gist, the upper ontology the project pins and imports
by version and never adds to the model. The shapes then target those classes, name their
fields with `sh:name` so an RDF property can change while a form field keeps its name, and
take a status field's options from the lifecycle's states instead of a copied list of
strings. The generated API serves a JSON-LD context per shape, so a payload is the same
graph as JSON. After all of that, the chapter notes, the generated app is the same as
before apart from the hash, because the facts were already there under other names.

Chapter 10 collects on it. [ADR-0025](../../docs/adr/0025-sempkm-store.md) adds a third
store kind, a SemPKM knowledge store reached over HTTP, with the same three facts as
PostgreSQL plus one binding that authenticates to it, which the shapes require to be a
secret. Change one triple, the expense shape's `seam:storedIn`, regenerate, and the
expenses are written to a triplestore as RDF, typed by the model's classes, while the
approvals and payments stay where they were. No generated code changes and no line of
Python changes, and the chapter's summary of the generator is the summary of the module:
it knows nothing about SemPKM; it writes what the model says.
[ADR-0026](../../docs/adr/0026-mental-model.md) then writes the package that teaches SemPKM
about the data, from the same ontology, shapes and interaction views, with nothing restated
and every node carrying the model term it was derived from, so the second tool shows the
same forms and tables the generated app does. And a webhook channel lets a change made in
SemPKM start a process in the app, closing the circle in the other direction. The data now
has two applications over it, and the model is the only thing either of them was built
from.

### The second half of trust

Lesson 6 said the trust story of F6 starts with shapes and lesson 10 added the trace. This
lesson adds the rest: bytes that do not change unless facts do, a lock that records who
wrote what from which model, generators that are versioned and declare what they need, a
vocabulary that is versioned and migrates, a change classifier that says breaking before
a deploy does, a status check against the running system, and tests derived from
scenarios the model states. None of it is a promise about a tool's good behaviour. Each
is a check that runs. The lab is the longest deployment in the course, chapter 8 under
Docker and chapter 10 into a knowledge store, and the two twists ask you to break the
status check and the compatibility check on purpose, so that you have seen each one say no.

## Read in the repo

- [ADR-0016](../../docs/adr/0016-generator-protocol.md) and
  [ADR-0021](../../docs/adr/0021-vocabulary-versions.md).
- [`examples/chat-app/seams.lock`](../../examples/chat-app/seams.lock). Everything the
  lock knows about one project's outputs.
- [Design and coding principles](../../docs/project/principles.md), principles 6, 7 and 9.

## Lab: chapters 8 and 10

- [Chapter 8, Growing up](../../docs/tutorials/expenses/08-growing-up.md): a payouts channel
  and a process started from it, a second decision and lifecycle, the finance console,
  deploy facts, PostgreSQL by `seam:storedIn`, two environments, `docker compose up`. Run
  the complexity check and read the derived diagrams, one per path.
- [Chapter 10, Expenses in SemPKM](../../docs/tutorials/expenses/10-sempkm.md): a SemPKM
  store, the expenses moved into it with no code change, the generated package installed,
  and a webhook channel starting a process.

Two twists:

1. After the stack is up, change one label in the model without regenerating and run
   `seams status`. Then regenerate and restart and run it again.
2. Run `seams diff` between your chapter 7 and chapter 8 files and read the classification.
   Then remove a required field from a shape and run it again.

## Scorecard

- **F4, closed for text, classification and migration.** The model is text in git, a
  change is classified by rule, the vocabulary is versioned and migrated. Merging two
  edits to one TriG file is still a text merge; no model-level merge tool exists.
- **F6, closed.** Deterministic bytes, versioned generators with preconditions, a lock, a
  trace, tests derived from scenarios, and a status check against the running system.
- **F1 and F3, reinforced.** The compose files are projections. Nothing in them is written
  by hand; what a laptop needs and production does not is a `:development` override in the
  model.

## Further reading

- The *Reproducible Builds* project, on why byte-identical output matters and what breaks
  it.
- Dave McComb, *The Data-Centric Revolution*, 2019, for principle 9's argument, and
  Semantic Arts' gist ontology, which the project pins and imports.
- Meinte Boersma, *Building User-Friendly DSLs*, 2025, chapter 10, on versions, migrations
  and deprecation, which the project's generator kit note reads closely.
