# Lesson 3 · The program that writes the program

*Code generation and domain-specific languages, from CASE and round-trip engineering to
language workbenches, low-code and language models. The newest generator has the oldest
problem.*

## Outcomes

After this lesson you can:

- Describe the four generations of code generators and the one problem they all worked
  around: part of the program is not in the model.
- Name the standard workarounds (protected regions, the Generation Gap pattern, partial
  classes, "generate 80%") and say what each one gives up.
- Regenerate a SemanticSeams example, read a generated file beside its template and its
  trace, and explain what a line-level trace is for.

## The story

### Generators are older than they look

A compiler is a generator, and so is yacc (1975), which writes a parser from a grammar. The
Lisp macro writes code at compile time from a description of the code wanted. These early
generators had two properties the later ones lost. Their input was complete: the grammar
said everything the parser needed. And nobody edited the output: you regenerated, every
build, and the generated file was never the thing you owned.

The history of application generators is the history of giving up those two properties,
one at a time, and of the devices invented to cope.

### CASE and round-trip engineering

Computer-aided software engineering tools of the 1980s, such as Texas Instruments'
Information Engineering Facility, generated whole applications from diagrams and a data
dictionary, in COBOL, for the mainframe. They worked when the application fitted the
tool's idea of an application, and the market for them collapsed in the mid-1990s when
it stopped fitting: client-server, then the web, moved faster than the generators.

Rational Rose and its contemporaries tried the other direction too. Round-trip engineering
promised that you could generate class skeletons from a diagram, fill in the method bodies
by hand, and reverse-engineer the diagram from the code when the code changed. In practice
each direction lost something. The forward trip knew nothing about the bodies, so it
guarded them with marker comments and hoped nobody moved them. The reverse trip recovered
structure but not intent, so the diagram slowly became a picture of the code rather than a
model of the system, and the first careless regeneration overwrote a week of work. The
phrase "round trip" survives mostly as a warning.

### The workarounds

The problem under round trip is simple to state and hard to solve: part of the program is
not in the model, and that part has to live somewhere. Three workarounds became standard,
and each is worth knowing by name, because they recur in every generator since.

**Protected regions.** The generator leaves marked blocks in its output that it promises
not to touch on regeneration. The programmer writes inside the markers. The cost: the
markers are a contract enforced by convention, generated and hand-written code sit in one
file, and a change to the template around the markers can still break what is inside them.
Acceleo and the Eclipse Modeling Framework shipped this.

**The Generation Gap.** John Vlissides's pattern (1996): the generator writes a base class
it owns entirely, and the programmer writes a subclass that overrides what it needs. The
two never share a file. The cost: a class hierarchy whose only purpose is separating
authorship, and a hand-written layer that must know the generated layer's names.

**Partial classes.** C# 2.0 (2005) let one class be spread over several files, so the
generated half and the hand-written half could be one type without sharing a file. The
cost: the language had to change to make it work, and the hand-written half is still coupled
to names the generator chose.

Behind all three sits the rule that Thomas Stahl and Markus Völter made explicit in 2006:
**never modify generated code.** Generate what you can, keep it separate, regenerate
freely, and write the rest by hand in a place the generator never visits. The 80/20 rule
of generation, that a generator covers four fifths of the code and the remaining fifth is
where the work is, comes from the same book.

### Model-driven generation and the narrow-domain finding

The Model-Driven Architecture of lesson 1 brought its own generators: transformation
languages (ATL, 2005; QVT, 2008) for model-to-model, template languages (Acceleo, Xpand)
for model-to-text, and the openArchitectureWare toolchain that became Xtext. Steven Kelly
and Juha-Pekka Tolvanen's *Domain-Specific Modeling* (2008) made the strongest case for
full generation and backed it with industrial examples, Nokia's phone software among them.
Their condition was strict: a language built for one domain, by the team that owned the
domain, with the generator written by the same people. Generate 100% from a narrow language,
or generate a skeleton from a general one; there was no comfortable middle.

The empirical studies lesson 1 cited found the same thing from the outside. Model-driven
engineering succeeded as a collection of small languages with owned generators, and failed
as UML-everything with a vendor's generator. A generator you do not own is a generator you
cannot fix, and a language that models everything models nothing precisely enough to
generate from.

### Language workbenches and projectional editing

Charles Simonyi's intentional programming (1995) proposed editing the program's intent in a
structured editor and projecting it as text, diagrams or tables, with the parser removed
from the loop. Martin Fowler's 2005 essay "Language Workbenches: The Killer-App for
Domain-Specific Languages?" named the tool category. JetBrains MPS (begun 2003, open-sourced
2009) is the projectional editor that shipped; Xtext (2006) and Spoofax (2010) are the
textual workbenches. All of them give you a language, an editor, constraints and a generator
from one definition.

Projectional editing solves the parsing problem and keeps the notation and the structure
apart, which is what "diagrams are views" needs. It did not solve two others. A projected
model lives in the tool's own format, so diff, merge and version control went back to being
the tool's problem, and the tool's problem was rarely solved well. And it is still a model
of one language: a workbench gives you one DSL at a time, not the joins between several.

Meinte Boersma's *Building User-Friendly DSLs* (2025) is the current synthesis, and the
SemanticSeams research notes read it closely. A DSL has four aspects, structure, notation,
meaning and constraints, and a generator is written by first writing the output you want by
hand, then teaching the generator to produce it. Terence Parr's *Language Implementation
Patterns* (2010) supplies the discipline for the generator itself: compute everything in a
model-walking step, and keep the templates free of logic. Both rules are in the project's
principles, and you will see them in the lab.

### Web generators and low-code

The web brought a generation of generators aimed at one kind of application. WebML (2000)
and the WebRatio tool built on it generated data-intensive web applications from a model of
pages, units and links; WebML became IFML. OutSystems (2001), Mendix (2005) and the platforms
Forrester named "low-code" in 2014 generated or interpreted business applications from
visual models, with a script block for whatever the model could not say. Ruby on Rails
(2004) made scaffolding a verb: generate the model, controller and views for a resource,
then edit them, and never run the generator on that resource again.

Interface generators took the complete-input path instead. Protocol Buffers (open-sourced
2008), OpenAPI and GraphQL generate clients and servers from a contract, and nobody edits
the output, because the contract is complete for what the generator produces. They work for
the reason yacc worked. They also generate only the edge of a system, and leave the middle
to be written.

The pattern across all of these is the one Stahl and Völter named: generate the structure,
let people write the behaviour, and then struggle at upgrade time to bring the two back
together. Low-code platforms made the struggle a business model. The model and the script
blocks lived in the vendor's store, in the vendor's format, and the generated application
ran on the vendor's runtime.

### Language models as generators

Large language models are generators of a new kind. Their input is incomplete by design, a
prompt, and their output is different every time. "Vibe coding", the phrase Andrej Karpathy
gave the practice in February 2025, is generation with no model at all: describe, accept,
describe again. BESSER, Jordi Cabot's open-source low-code platform (2023), proposes the
inverse, "vibe modelling": the language model proposes the model, a person validates it,
and deterministic generators produce the code.

Every question this lesson has raised returns with the new generator, unchanged. What is
the source of truth, the prompt or the output? What happens when you regenerate: does the
hand edit survive, or the new draft win? How do you verify output you did not write and
cannot reproduce? The language model is the most capable generator yet built and the least
trustworthy, and the workarounds of the 1990s, keep the generated and the owned apart and
never edit what you did not write, are what the field is rediscovering. Lesson 9 shows the
project's answer, and lesson 12 what it has not answered yet.

## Read in the repo

- [`examples/chat-app/generated/chat_api.py`](../../examples/chat-app/generated/chat_api.py)
  and its sidecar
  [`chat_api.py.trace.json`](../../examples/chat-app/generated/chat_api.py.trace.json). A
  generated file, and for each of its lines the template line and the model elements behind
  it ([ADR-0019](../../docs/adr/0019-generation-trace.md)).
- [`seams_gen/README.md`](../../seams_gen/README.md), the rules section. Extract computes,
  templates render, output is sorted and carries the model hash. Parr's discipline, stated
  as project rules.
- [A generator kit and a domain IDE, read against two
  books](../../docs/research/2026-10-30-domain-ide-and-generator-kit.md), the section
  "Write the reference first, then derive the generator". Boersma's method as the project
  adopted it.

## Lab: regenerate, trace, and get caught

1. **Regenerate an unchanged model.** From the repository root:

   ```sh
   seams generate --project examples/chat-app
   git status --short
   ```

   Nothing changes. Same model, same bytes. Open
   [`examples/chat-app/seams.lock`](../../examples/chat-app/seams.lock) and find the entry
   for `chat_api.py`: the generator's name and version, the file's hash and the model
   elements it was made from.

2. **Follow one line to its facts.** Open `generated/templates/chat_page.html`, find the
   `<title>` line, and look it up in `chat_page.html.trace.json`. The entry for that line
   names the template line it came from and the model terms behind it, `:chat_page` among
   them. That is where the title came from, and lesson 10 uses the same trace to send an
   edit back.

3. **Change the model, not the code.** In `examples/chat-app/chat-app.trig`, change
   `ifml:title "Chat"@en` to `"My chat"@en`. Regenerate and diff:

   ```sh
   seams generate --project examples/chat-app
   git diff --stat
   ```

   The template output changed, and so did every hash line that records the model, and
   nothing else. Restore the model with `git checkout examples/chat-app/chat-app.trig` and
   regenerate again.

4. **Get caught.** Now do what round-trip engineering did: edit a generated file by hand.
   Change any label in `generated/templates/chat_page.html`, then run the checker:

   ```sh
   seams check --project examples/chat-app
   ```

   It reports the file as `hand-edited`: its bytes match neither the lock nor what the
   model generates. Restore it with `git checkout examples/chat-app/generated`. The
   workarounds of the 1990s guarded the output with marker comments; here the lock knows
   the bytes, and continuous integration runs this check on every example.

## Scorecard

Seeds for [lesson 4](04-why-it-kept-stalling.md):

- **F1, some code cannot be generated.** Protected regions, the Generation Gap and
  partial classes are three answers to one fact, and each mixes authorship or couples the
  hand-written half to generated names.
- **F2, edits never get back.** Round-trip engineering lost intent in one direction and
  bodies in the other. The lab's `hand-edited` report is the first half of an answer:
  knowing that an edit happened. Lesson 10 is the second half.
- **F6, trusting the generator.** A generator you do not own and cannot reproduce is one
  you cannot trust. The lab's unchanged `git status` after regeneration is what
  reproducible means in practice.

## Further reading

- John Vlissides, "Generation Gap", *C++ Report*, 1996; collected in *Pattern Hatching*,
  1998.
- Krzysztof Czarnecki and Ulrich Eisenecker, *Generative Programming: Methods, Tools, and
  Applications*, 2000.
- Thomas Stahl and Markus Völter, *Model-Driven Software Development: Technology,
  Engineering, Management*, 2006. "Never modify generated code."
- Martin Fowler, "Language Workbenches: The Killer-App for Domain Specific Languages?",
  2005.
- Steven Kelly and Juha-Pekka Tolvanen, *Domain-Specific Modeling: Enabling Full Code
  Generation*, 2008.
- Terence Parr, *Language Implementation Patterns*, 2010, chapters 11 and 12.
- Meinte Boersma, *Building User-Friendly DSLs*, 2025.
- Stefano Ceri, Piero Fraternali and Aldo Bongio, "Web Modeling Language (WebML): a
  modeling language for designing Web sites", *Computer Networks*, 2000.
- Jordi Cabot and colleagues, the BESSER project, 2023 onward. "Vibe modelling" as the
  inverse of vibe coding.
