# Lesson 6 · Shapes before generation

*SHACL on the business data and on the model itself. A model that passes the shapes must
generate.*

## Outcomes

After this lesson you can:

- Explain how one SHACL shape does triple duty as validation, form and API contract, and
  how the generated app, the runtime and the viewer all read the same shape.
- State the parity rule, every generator fault is a shape violation first, and say what it
  buys the person authoring a model.
- Generate a FastAPI route module and htmx templates from your model, send it invalid
  input, and read the problem+json response back to the shape that refused it.

## The story

### One shape, read three ways

Chapter 2 of the tutorial has you write a dozen lines of SHACL: an `ExpenseShape` with
four properties, each with a datatype, a cardinality and an order, and one with a lower
bound, `sh:minInclusive 0.01` on the amount. Chapter 3 then generates an application from
it, and the point of this lesson is to watch how many things those dozen lines turn out
to be.

They are the **validation**. Every write the runtime performs is checked against the shape
before anything is stored, and a payload that fails is answered with a 422 whose body
names the shape, the path and the constraint that rejected it. In the lab you will send
an empty description and a negative amount and read back a `MinCountConstraintComponent`
on `description` and a `MinInclusiveConstraintComponent` on `amount`. The chapter's own
summary is the sentence to remember: every rule the API enforced is a line of the shape,
and none of it is in the generated code.

They are the **form**. The htmx generator lays a form's inputs out in `sh:order`, picks an
input type from the datatype, turns an `sh:in` list into a drop-down, and binds each
`ifml:Parameter` to the property it is `ifml:boundTo`. The `id` property, which the
runtime assigns, is never asked for, because the model says the runtime sets it. Change the
order of two fields in the shape and regenerate, and the form follows; nothing in a
template was touched, because the template holds text and the extract step computed the
order from the graph.

They are the **contract**. An operation declares the shape it `seam:acceptsShape` and the
one it `seam:returnsShape`, so the request body of the submit operation and the fragment
it renders are both described by the same resource the form was built from. Later
lessons add two more readings without adding a line: the JSON-LD context the generated
API serves is derived from the shape, and the package that teaches SemPKM about the data
is written from the same shapes. One statement, read five ways, and never restated.

<Diagram name="shapes-five-ways" caption="One shape, read five ways. The expense shape is the runtime's validation, the generated form, the operation contract, the JSON-LD context and the SemPKM package, with nothing restated. Below it, the shapes over the model itself drive the viewer's health badge, and a model that passes them must generate." />

### Rejecting, not inferring

Lesson 2 drew the line between a vocabulary that infers and a shape that rejects, and
this is where the project puts the line to work. The shapes are evaluated by pySHACL in
the worker, at the call boundary, which [ADR-0007](../../docs/adr/0007-execution-strategy.md)
lists beside BPMN and DMN as a thing to *interpret* rather than generate. The generated
route handler does not validate anything; it hands the payload to the runtime, and the
runtime refuses or writes. That is rule one of the execution decision applied to data: a
generated handler that contained an `if` about the amount would be a bug in the
generator, because the fact lives in the shape.

The practical consequence is the one the chapter demonstrates. A rule changes in the
model, the app is regenerated, and the diff is nothing but the model-hash lines, because
the rule was never in the code.

### Shapes over the model itself

The second use of SHACL is the one that answers the first review. The seams are
constrained by shapes in [`ontology/shapes/seam-shapes.ttl`](../../ontology/shapes/seam-shapes.ttl),
not by `rdfs:domain` and `rdfs:range`, because a range infers a type onto a violator and
a shape rejects it. The file reads as a list of rules about what a well-formed model is,
in sections that follow the ontology: every `seam:Model` has exactly one notation, and it
is one of the known ones; every seam predicate declares exactly one reveal mode; `triggers`
starts at an `ifml:Event`; `detailedBy` ends at a `seam:Model`; a BPMN model carries its
payload; a user task is completed on at most one form; a context owns exactly one
ontology. The viewer's health badge is this validation, run on every page load, and chapter
2 has you break it on purpose. Delete the one triple that says the data model's notation
is a shape graph, restart the viewer, and the badge turns red, reports one violation, and
names the model and the rule that rejected it. The chapter's phrasing is the method in one
line: a broken seam shows up the moment you look at the model, not when something
downstream fails.

The shapes also carry the project's methodology. The IDesign and DDD profiles of lesson 12
are shape libraries over the model, attached by `seam:conformsTo`, so "we follow this
method" becomes something a validator checks rather than something a review meeting
asserts.

### A model that passes the shapes must generate

Principle 5 is the rule that turns the badge from a nicety into a promise: if the model
passes the shapes, generation succeeds. Every condition that makes a generator raise a
`GeneratorError` is also a shape violation, or is listed as generator-only with the reason
the shapes cannot state it. A test enforces the rule by inventory. For each raise site in
the generators there must be a parity case, a deliberately broken example that the shapes
flag and the generator rejects, or an entry in a list of exceptions with its reason, and
the test fails on a raise site with neither.

The idea comes from the generator-kit research note's reading of Boersma: in a domain IDE,
"no reported issues" must mean generation works, or the author learns about the fault from
a stack trace in a tool they do not own. The note found the project breaking that rule in
several places, and the fix was not to catch more exceptions but to write more shapes,
with the section header you will see in the file, "IFML structure the generators rely on".
The exceptions that remain are honest about why they are exceptions: a path that depends
on where the model file sits on disk, for instance, is not a fact SHACL can see.

Two corollaries. A model that fails the shapes is flagged, never refused: it can still be
saved, viewed and shared, and the badge says what is wrong. And when a model does break a
generator, `seams generate --lenient` writes what it can and records each fault in the
lock, so the viewer's live preview can show a half-finished model without pretending it is
whole.

### Errors are declared too

One more kind of fact belongs in this lesson, because it is where most generated APIs go
vague. [ADR-0013](../../docs/adr/0013-error-shapes-and-boundaries.md) makes an operation
declare each error it can raise, as a Hydra status with an HTTP code and an error code, and
makes the body of that error a shape over problem details, the RFC 9457 members `title`,
`status`, `detail` and the rest, each a property of an ordinary `sh:NodeShape`. The
validation that checks a success body checks an error body the same way. And because the
error is a fact with an IRI, a BPMN boundary event can `seam:catches` it, which is how a
failure crosses from the communication layer into the process layer. Lesson 9 shows that
path in the tutorial, when a notification that cannot be sent takes the expense to finance
instead of failing the instance.

### What this buys

Put the pieces together and the trust story of F6 starts here. The badge tells the author
before generation whether the model is sound. The parity test guarantees that "sound"
means "generates". The same shapes that refuse bad data at the boundary build the form
that collects it and describe the contract that carries it, so there is no second copy of
the rules to drift. Lesson 10 adds the trace, so that every generated line can say which
fact it came from, and lesson 11 adds determinism, so that the same model always gives the
same bytes. The lab is chapter 3: generate the first screens, break the contract on
purpose, and read the refusal.

## Read in the repo

- [`ontology/shapes/seam-shapes.ttl`](../../ontology/shapes/seam-shapes.ttl). Read the
  banner comments; each section is one rule about the model.
- [ADR-0013](../../docs/adr/0013-error-shapes-and-boundaries.md). What an error is, where
  it is declared, and how a BPMN boundary event catches one.
- [Design and coding principles](../../docs/project/principles.md), principle 5, "Shapes
  catch faults before generation", and the parity rule.

## Lab: chapter 3

Work through [chapter 3, The screens](../../docs/tutorials/expenses/03-screens.md). You add an
IFML page with a list and a form, two operations, generate the app and run it in process.
Three twists:

1. Send the chapter's invalid request, an empty description and an amount of minus five,
   and read the 422 body: two results, each naming a path and the constraint that rejected
   it. Find both constraints in your TriG.
2. Change the shape's `sh:order` for two fields and regenerate. The form's field order
   follows; nothing in a template was edited.
3. Remove `sh:maxCount 1` from a property and run `seams check`. If the shapes over the
   model do not object, ask what the generated form does with a multi-valued field, and
   whether that is a shape rule or a generator rule. The answer is in the parity
   inventory.

Diff against `examples/expenses/chapter-03/expenses.trig` when done.

## Scorecard

- **F6, opened.** The health badge and `seams check` are the first half of trust: the
  model is validated before anything is generated, and a model that passes generates.
  Determinism and the trace, the second half, come in lessons 10 and 11.
- **F1, framed.** The generated form holds no validation logic. The shape does. The first
  `if` about the business is nowhere in the output.

## Further reading

- W3C, *SHACL: Shapes Constraint Language*, 2017, and the *SHACL 1.2 User Interface*
  draft, for shapes that drive forms.
- Holger Knublauch, the DASH shapes vocabulary, for the editor hints the generated forms
  use.
- IETF, *RFC 9457: Problem Details for HTTP APIs*, 2023, the error format the runtime
  returns.
- The project's [generator kit research note](../../docs/research/2026-10-30-domain-ide-and-generator-kit.md),
  section "No reported issues should mean generation works".
