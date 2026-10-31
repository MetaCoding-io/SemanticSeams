# Research note: a generator kit and a domain IDE, read against two books

*Status: proposal, 2026-10-30. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Generator kit and domain IDE" section). Written against `main`
at `f80503b`, after M010 to M016 were planned; revised 2026-10-31 after M010 (L1 to L6)
merged. It builds on the
[library note](2026-10-29-seams-python-library.md) (L1 to L6) and the
[artifact management note](2026-10-29-artifact-management.md) (A1 to A9) and does not
repeat them.*

## The question

Can we help users write their own generators, and can we go further and give them a
domain IDE: an editor in which someone who is not a developer changes the model and sees
the application change? **Yes to both, in that order.** M010 has since shipped
the `seams` library and a "Write your own generator" guide, so the generator side is the
rest of the packaging: registration, a test kit and a scaffold. The IDE side is four layers on top of the
viewer, and the books identify two things that have to come before any of them: every
fault a generator can hit must be a shape violation first, and models need a vocabulary
version so the editor can migrate them. Editing is still a v1 non-goal (backlog P2 item
13), so the IDE half is a plan for after v1, not a request to change that.

## Sources

- Meinte Boersma, *Building User-Friendly DSLs* (Manning, 2025). This is the main source.
  The book builds a browser-based "Domain IDE" with a projectional editor, a code
  generator, constraints and versioning for a car-rental pricing DSL. Page numbers below
  are the printed ones. Everything is paraphrased; nothing is quoted.
- Terence Parr, *Language Implementation Patterns* (Pragmatic Bookshelf, 2010). Cited by
  chapter, pattern and printed page, also paraphrased. Its parsing chapters (2–3) do not
  apply to us; its tree, symbol, type and translation chapters (4–8, 11–12) do.

## Boersma's vocabulary, in our terms

Boersma splits a DSL into four aspects: structure, notation, meaning and constraints
(front matter and section 1.4, pp. 19–25). Each already has a home here.

| Boersma | SemanticSeams | Where |
|---|---|---|
| DSL content, the AST | The TriG model: one named graph per diagram plus the seams graph | `examples/*/*.trig`, [ADR-0001](../adr/0001-named-graph-partitioning.md) |
| Structure: concepts, properties, types | The layer vocabularies | `ontology/*.ttl` |
| Constraints and issues | The seam shapes and the model-health badge | `ontology/shapes/seam-shapes.ttl`, the viewer |
| Notation, projection | The viewer's renderers: ELK cards, IFML on diagram-js, bpmn-js, dmn-js | `viewer/` |
| Meaning | Generated templates, routes and compose, plus the interpreted BPMN and DMN | `seams_gen`, `seams_runtime`, [ADR-0007](../adr/0007-execution-strategy.md) |
| Repository behind the IDE | Git | |
| Build system, code generator | `python -m seams_gen`, later `seams generate` | A1 |
| Runtime | The generated app on `seams_runtime` | |
| Reference implementation | The hand-written golden outputs, then the expense tutorial | `docs/generation/golden/` (G2), `examples/expenses/` |
| Record type: maps to tables, classes and forms (pp. 10–11) | A `sh:NodeShape`: it gives form fields, request validation and, with U9, storage | `seams_gen/htmx.py`, `seams_runtime` |
| Metamodel (pp. 406–410) | The vocabularies plus the shapes | `ontology/` |

Three differences matter later:

- **We have an explicit metamodel and Boersma does not.** He leaves it out because
  content must stay lenient while it is being edited, and a metamodel is about
  strictness (pp. 409–410). SHACL avoids that conflict: the shapes report on a graph
  without stopping it from being stored. That is the behaviour he asks for.
- **We interpret part of the meaning.** He generates everything and mentions
  interpretation only as the road not taken (p. 15, p. 200). ADR-0007 interprets BPMN and
  DMN and generates the rest, so his generator chapters apply to `seams_gen` and not to
  the process engine.
- **We already have a textual notation.** He avoids text because parsing, error
  recovery and language services are expensive (pp. 401–405). Our text notation is TriG,
  and its parser comes free with rdflib, so a projectional editor would be a second
  notation beside text, not a replacement for it.

## What the books say, and what follows

### 1. No reported issues should mean generation works (Boersma ch. 9)

Boersma splits generation into five stages: the generator runs, the output parses, the
output builds, the result runs, and the results make sense. Each can fail (pp. 233–234).
He then states a principle the rest of the chapter serves: if the editor reports no
issues, the generator must finish and the result must run correctly. If issues are
reported, all bets are off (p. 236). He names three ways to handle a fault (pp. 238–240):

- **Impose a constraint**, so the author sees an issue on the element at fault.
- **Handle the faulty content** in the generator: emit a clearly flagged placeholder
  instead of crashing, so a developer can trace it back.
- **Refuse to save** invalid content.

He rejects the third, because content is invalid most of the time while it is being
edited, and an invalid model still has to be shareable in a bug report (p. 236).

**Where we stand.** The generators fail fast: a missing or ambiguous fact raises
`GeneratorError(subject, predicate, detail)` and nothing is written
([`seams_gen/README.md`](../../seams_gen/README.md)). There are about 75 raise sites
across `htmx.py`, `fastapi.py`, `compose.py`, `_views.py` and `fragments.py`. The shapes
file has 40 node shapes, none with a severity other than the default. Nobody has checked
which generator faults the shapes catch first, and at least two they do not:

- The htmx generator requires `ifml:order` on every component of a page
  (`seams_gen/htmx.py`, the `unordered` check). `seamsh:OrderShape` only says a component
  has *at most* one. A page with an unordered component shows *Conforms* in the viewer
  and then fails generation.
- An `ifml:List` without `seam:reads` fails generation ("an ifml:List must read a shape").
  `seamsh:ReadsShape` checks only what a `seam:reads` points at, not that a list has one.

That breaks Boersma's principle with no warning to the author. The fix is a parity rule:
each generator fault is either caught by a shape first or documented as generator-only,
with the reason. A test proves it with one minimal broken model per fault. This is the
cheapest item in the note and the one the IDE depends on most, because the IDE's issue
list *is* the shapes report.

Two smaller points from the same chapter:

- **Severities.** Boersma separates errors from warnings and ramps a deprecation from one
  to the other (p. 287). We use only `sh:Violation`. `sh:Warning` would serve for
  deprecations (section 3) and for advice such as the complexity check's thresholds.
- **A lenient mode for previews.** Fail-fast is right for CI. In an editor preview, the
  second strategy is better: generate with flagged placeholders and list the faults,
  so the author sees the rest of the page while one element is incomplete (p. 239).

### 2. Write the reference first, then derive the generator (Boersma ch. 8; Parr ch. 11–12)

Boersma's method for writing a generator (pp. 201–211):

1. Write a small, working reference implementation by hand, in the target architecture.
   Its domain-specific part must be expressible as model content.
2. Start the generator as a template that returns the reference file verbatim. A run
   with no diff means the generator works.
3. Replace literal pieces with values from the model one at a time, checking for no diff
   after each step.

While writing the reference, leave no room for creativity: similar problems get
identical solutions, because a generator has no imagination (p. 209). Templates should
be well-structured code in their own right, and the generated output is checked with the
same quality tools as hand-written code (p. 229). One fact in the model usually becomes
many details in the output, which he calls fan-out (p. 229). He weighs template engines
against plain string templates: an engine adds syntax and often forces derived values,
such as camel-cased names, to be computed before the template runs (pp. 230–231).

**Where we stand.** G2 was this method: the three chat-app artifacts were written by hand
first, and the generators had to match them byte for byte before they existed. The
`extract_*` / `render_*` split in `seams_gen` is the precomputation Boersma describes, and
Parr argues for the same structure:

- **Understand, then map** (p. 291). A translator should analyse an input phrase fully
  and then pick an output construct for it, rather than swap symbols one for one.
- **Build an output model first** (section 11.3, pp. 295–297). Walk the input, build a
  nested tree of output objects, and only then emit text, so the output order does not
  have to follow the input walk. He also advises against rewriting the input tree as a
  translation step unless the change is simple (p. 296).
- **Keep logic out of templates** (p. 323). Of the template engines he lists, only
  StringTemplate enforces this strictly: computation stays in code and templates hold
  output text. That is what lets one model drive several templates.
- **Retarget by swapping templates** (section 12.7, p. 347). One input model and one
  traversal can produce a different language when given a different template group.

Our templates are close to that but looser. They loop and branch, which StringTemplate
also allows, but they also join lists, lowercase method names, concatenate strings and
compare list lengths (`seams_gen/templates/`). Strict separation would move those into
`extract`. The rule we do enforce, no domain literals in templates, is narrower. The
generator guide should recommend Parr's stricter form for user generators, because it is
what makes a template set swappable.

**What follows for users.** M010 gave users the reading side: the `seams` library and
the [Write your own generator](../guide/write-your-own-generator.md) guide, whose example
generator runs in CI. The guide covers loading, walking the views, joining BPMN and DMN,
and deterministic output. It does not yet teach the reference-first method, golden tests
or keeping logic out of templates, and nothing registers a user's generator. A user
writing a generator still needs:

- a way to register a generator so `seams generate` (A1) finds it and the lockfile (A2)
  records its name and version;
- a test kit: golden comparison with the model-hash placeholder (`seams_gen/golden.py`
  today), a determinism check (generate twice, compare), and output checkers per file
  type (Python compiles and passes ruff, compose passes `docker compose config`,
  templates parse);
- a scaffold that starts from a reference output, as in step 2: a template that returns
  the file verbatim and a golden test that passes on day one;
- a section in that guide on the three-step method and Parr's logic-free templates.

Fan-out is also the argument for A2 recording source elements per output: when one fact
touches ten files, a reviewer needs the reverse index.

Boersma also mentions using an LLM to draft a template from example content, and treats
the result as a half-finished product that needs tests, refactoring and documentation
before it can be trusted (p. 231). The scaffold and the golden test give exactly that
check, so an LLM-assisted "draft a generator from this reference output" is plausible
later. It is not proposed here.

### 3. Versions, migrations and deprecation (Boersma ch. 10)

Boersma stores a version ID with the content and checks it on every load (pp. 282–284):

- same version: proceed;
- newer than the tool: refuse to load;
- older than the tool: run migrations, then proceed.

He sorts changes to the language's structure into two kinds (pp. 284–285). *Widening*
changes, such as a new property or concept, leave existing content valid. *Modifying*
changes, such as a changed type, a removal, a rename or a restructuring, need a
migration: a small transformation with a "from" and a "to" version, one step at a time
(p. 286). A removal is preceded by deprecation: a constraint that flags every use and
says what is deprecated, why, when it goes and what to write instead, at warning level
first and error level later (pp. 286–287).

**Where we stand.** The model hash identifies a model's *content* (ADR-0007 rule 2). The
vocabulary has no version: `ontology/seam.ttl` declares an `owl:Ontology` with no
`owl:versionIRI`, and a model does not say which vocabulary version it was written for.
Every vocabulary addition so far has been widening, which is why this has not hurt. The
first rename will.

**What follows.**

- A version IRI on each vocabulary, and a statement in each model of the version it
  targets.
- The load check above in `seams.load`, so the viewer, runtime, generators and IDE all
  refuse or migrate the same way.
- Migrations as SPARQL Update files, one per version step, run by a `seams migrate`
  command.
- Deprecations as `owl:deprecated` on the term, plus a shape at `sh:Warning` that later
  becomes `sh:Violation`.

U8's compatible-versus-breaking shape diff is the same widening-versus-modifying
distinction, applied to a user's domain shapes rather than to our vocabulary. The two
should share the classification code.

Boersma's coupling chart (pp. 276–283) sorts code into three kinds:

- *language-specific* code, which depends on the vocabulary;
- *language-generic* code, a framework that works for any vocabulary;
- *unrelated* code, which has nothing to do with the language.

Structure is coupled to almost everything. That sorting gives the kit its boundary:

- the `seams` library, the generator protocol and the test kit are language-generic;
- a user's generator, and our own, are language-specific.

If the kit's core never names an `ifml:` or `proc:` term, a domain profile (section 4)
can add vocabulary without changing the kit.

### 4. Projection and editing (Boersma ch. 1, 4–6, 15.1)

Boersma's Domain IDE (section 1.2, pp. 4–14) is a browser app with three parts:

- an editor that shows content in its notation and lets the author change it only in
  ways that make sense;
- surrounding chrome for navigating sections and adding or deleting items;
- a backend that stores the content and feeds a build system.

The build can be triggered from a button in the IDE, from CI or from the command line
(p. 201). The editor is a projection: a function from content to DOM, re-run whenever the
content changes (pp. 74–75, 102–103). What is selected or being edited is kept apart from
the content itself (pp. 100–102). Guidance comes from the structure:

- a fixed set of choices becomes a drop-down (p. 8);
- a reference becomes a list of the things it can point at (section 5.4, p. 117);
- a missing value becomes a placeholder that invites input (p. 404);
- issues appear on the element they concern (pp. 240–241).

Edits come in three kinds: a value changes, an object is added or removed, or an object
moves within a list. Recording them as they happen gives autosave, undo and, with
conflict detection, real-time collaboration (pp. 275–276). Plain text merges are not
structure-aware, so they can produce content that no longer fits the structure (p. 275).

**Where we stand.** The viewer is already the projection, read-only and server-rendered,
one htmx request per click. Git is the repository. The CLI and CI are the build
triggers. What is missing is everything that writes.

**The four layers**, in the order they depend on each other:

1. **Forms from shapes.** To edit an element, render a form from the shapes that target
   its class: `sh:in` becomes a select, `sh:class` a picker listing the instances of that
   class, `sh:minCount 1` a required field, and a missing value a placeholder. This is
   the derivation the htmx generator already does for a user's domain shapes (`_fields`
   in `seams_gen/htmx.py`), applied to the vocabulary's own shapes. Each save re-runs the
   shapes and shows the issues on the element. Invalid models save; they are only
   flagged.
2. **Live checks and preview.** After each save, run the generators in the lenient mode
   from section 1 and show the generated page beside the model. This is Boersma's build
   button. The A6 model-hash comparison tells the author when the running app is behind
   the model.
3. **Diagram round-trip for BPMN and DMN.** bpmn-js and dmn-js both ship modelers, not
   only viewers, so editing the native XML is mostly a matter of swapping components and
   writing the XML back to its `seam:renderPayload`. The hard part is identity. Under
   [ADR-0002](../adr/0002-iri-identity-and-migration.md) an element's XML `id` is its
   IRI's fragment, so renaming an ID in the modeler cuts every seam attached to it. The
   modeler needs a rename that rewrites the seams graph in the same save, which is
   Boersma's rename refactoring (p. 285). The model-health badge also needs a check that
   every lifted IRI still names an element in the XML.
   `tests/test_viewer_payload.py` checks this for the chat app only; no check runs it
   on a user's model. IFML and C4 edits are graph edits, such as adding a component or a
   seam. Layout stays computed on the server, so no geometry is stored.
4. **Domain profiles.** `seam:Profile` and `seam:conformsTo` are already reserved in
   `ontology/seam.ttl`: a profile is "a component taxonomy plus a SHACL shapes library
   validating the model graph itself". Extend that to a package with four parts:
   - extra vocabulary and shapes;
   - the generators the profile needs;
   - the palette of classes the editor offers when adding an element (the restricted
     construct menu of Boersma's fig. 1.6, p. 8);
   - optionally, labels in the domain's own words.

   This layer is what makes the IDE a *domain* IDE: an expense team edits expenses,
   approvals and payout rules, not `proc:UserTask`s.

Two prerequisites sit under all four layers:

- **Writing TriG back without losing what people wrote.** Parr lists the need to keep
  comments and formatting among the things that make a translator hard (p. 290), and
  writing a model back after an edit is that kind of translation. rdflib drops comments
  and reorders triples when it serialises. The examples rely on comments: the chat app has 61
  comment lines in 434, and the expense tutorial's chapter 8 has 173 in 799. Options:
  - edit the TriG text in place at the triple level;
  - move the explanation into `rdfs:comment` triples;
  - accept a canonical, sorted serialisation for files the IDE owns, which also keeps
    git diffs line-local.

  This needs a decision before layer 1.
- **Edits as quad patches.** Record each edit as the quads it adds and removes. That
  covers all three of Boersma's edit kinds and gives undo and autosave. RDF Patch is an
  existing format for it. Git stays the asynchronous collaboration path. Real-time
  collaboration is out of scope.

### 5. Expressions, types and scopes (Boersma ch. 11–14; Parr ch. 6–8)

Boersma models expressions as structure, so the projection can handle precedence and the
type checker can reason about them (ch. 11–13). Our expressions are strings inside the
native XML:

- BPMN gateway conditions such as `route == "manager"`;
- DMN input expressions and rule cells.

ADR-0007 keeps them there, and nothing here argues for lifting them. Two cheap static
checks still follow, from Boersma's type-checking constraints (section 13.2, p. 355) and
from Parr's chapters on symbols and scopes (ch. 6, pp. 146–161) and static typing
(ch. 8, Pattern 22, Enforcing Static Type Safety, p. 216). Parr notes that some languages
check the same rule both before and during execution (p. 196). That is the arrangement
here: the engine keeps its run-time check, and a static check reports the fault earlier.

- **Type agreement.** A DMN input whose `typeRef` is `number` should read a property
  whose `sh:datatype` is numeric. Today the engine coerces the value at run time and
  fails the instance when it cannot (`seams_runtime/engine.py`).
- **Scope.** Each variable a gateway condition names should be the
  `dec:processVariable` of a decision output upstream of the gateway. A typo today
  surfaces only when an instance takes that path.

Boersma's execution-model questions (pp. 386–387) ask:

- whether rules can contradict each other;
- whether order matters;
- whether one rule's result feeds another's condition.

For decision tables, DMN answers these with hit policies. A table that matches no rule
fails the instance at run time
([authoring guide](../guide/authoring-a-model.md#decisions-and-routing)). A static
completeness and overlap check for `UNIQUE` tables is possible but harder, and is left
as an open question.

### 6. Where this sits among existing tools (Boersma 15.4; Parr ch. 4–5)

Boersma surveys the tools built for this job (pp. 411–422):

- language workbenches, with MPS as his worked example; he judges code generation its
  weakest point (p. 421);
- EMF and Ecore, which play the role our RDFS vocabularies and SHACL shapes play;
- Blockly;
- Freon, a framework for projectional editors on the web;
- LionWeb, a set of protocols and a serialisation format for language tools on the web.
  He is one of its founders.

None of these replaces what we have. LionWeb is worth watching: an export of a model to
its serialisation format would let LionWeb-based editors open it. His warning against
adding constructs because they please the language designer rather than the domain
expert (pp. 409–410) is the rule our backlog's "Vocabulary impact" column already
enforces.

Parr's tree chapters give the kit two ways to read a model:

- **Two kinds of tree** (ch. 4). A *homogeneous* tree uses one node type for everything
  (Pattern 9, p. 109); a *normalized heterogeneous* one has a type per construct but
  keeps a uniform list of children, which keeps generic walkers easy to write
  (Pattern 10, p. 111). The rdflib dataset behind `seams.load` is homogeneous. The
  typed views M010 added per layer are a heterogeneous view over it, and the kit should
  keep both.
- **Two ways to walk them** (ch. 5). Parr separates *how a walk proceeds* from *what it
  looks for* (section 5.4, p. 125). A *tree pattern matcher* fires on patterns wherever
  the walk finds them (Pattern 15, p. 138); an *external tree visitor* keeps one task's
  whole walk in one place, in an order it chooses (Pattern 13, p. 131). SPARQL is our
  pattern matcher, for "find every X with Y". The views' walk of a BPMN process in flow
  order (`tasks()`) is a visitor, for "walk this in order". The generator guide should say when to use
  which.

## Proposal

### Generator kit (K)

| # | Item | Builds on |
|---|---|---|
| K1 | **Shapes catch every generator fault first.** A parity test feeds one minimal broken model per `GeneratorError` condition to both the shapes and the generator. Each fault gets a shape, or is listed as generator-only with the reason. Start with `ifml:order` on page components and `seam:reads` on `ifml:List`. | none |
| K2 | **Static checks for decisions.** DMN `typeRef` agrees with the `sh:datatype` of the input's `dec:fromPath`; gateway condition variables are upstream `dec:processVariable`s. | none |
| K3 | **Generator protocol and discovery.** A generator has a name, a version, its precondition shapes, and `extract` and `render` steps. It is registered under a `seams.generators` entry-point group, so `seams generate` runs it and the lockfile records it. A lenient mode collects faults and emits flagged output, for previews only. | L2, A1, A2 |
| K4 | **Generator test kit.** Golden comparison with the hash placeholder (moved from `seams_gen/golden.py`), a determinism check, output checkers per file type, and the K1 parity helper, all public. | K3 |
| K5 | **Scaffold and guide.** `seams new-generator` from a reference output: a verbatim template and a passing golden test. The L6 guide gains a section on Boersma's three-step method and Parr's logic-free templates. | K3, K4, L6 |
| K6 | **Vocabulary versions and migrations.** A version IRI per vocabulary, the target version stated in each model, the load check in the shared library, SPARQL Update migrations per step, and deprecations as `owl:deprecated` plus a warning-level shape. ADR first. | L2; shares classification with U8 |

### Domain IDE (I)

| # | Item | Builds on |
|---|---|---|
| I1 | **Write path.** Edits as quad patches with undo, and a decision on comments and serialisation for files the IDE writes. ADR first. | L2 |
| I2 | **Forms from shapes.** Edit one element through a form derived from the shapes that target its class; save invalid models and flag them. | I1, K1 |
| I3 | **Live checks and preview.** Re-run the shapes and the generators in lenient mode after each save, and show the generated page beside the model. | I2, K3 |
| I4 | **BPMN and DMN round-trip.** Modelers in place of viewers, an ID rename that rewrites the seams graph, and a model-health check that lifted IRIs exist in the XML. | I1 |
| I5 | **Domain profiles.** A profile package (vocabulary, shapes, generators, palette, labels) attached by `seam:conformsTo`, which restricts what the editor offers. ADR first. | I2, K3 |

K1 and K2 stand alone and make the existing tools more honest today. K3 to K5 build on
M010, now done, and M012, which delivers the CLI and lockfile they extend. K6 should land before
the first vocabulary change that is not widening.

The I items refine backlog P2 item 13, **Editing**. That item is parked because editing
is an explicit v1 non-goal in the product brief, and M008/S04 checks that reason again.
Nothing here overrides that. The I items are what that slice would plan if the reason no
longer holds: I4 is item 13's "embed modelers read-write", and I1 to I3 and I5 are what
it needs around it. They come after the kit in any case, because the preview needs
registered generators and a lenient mode.

## Open questions

- **Comments.** Should the IDE edit TriG text in place, or should the examples move
  their explanations into `rdfs:comment` triples? The first keeps hand-written files
  intact. The second makes the explanation part of the model, where the viewer could
  show it.
- **Where the IDE lives.** Is it a mode of the viewer, which already has the renderers,
  the routes and the health badge, or a separate app? The viewer's read-only guarantee
  is a feature for people who only browse.
- **Decision-table checks.** Is a static completeness and overlap check for `UNIQUE` DMN
  tables worth its cost, or is the run-time failure, plus U5's derived tests, enough?
- **LionWeb.** Is interoperability with LionWeb-based editors a goal, or only something
  to watch?
