# Lesson 6 · Shapes before generation

*SHACL on the business data and on the model itself. A model that passes the shapes must
generate.*

::: info Module B draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module B pull request.
:::

## Outcomes

After this lesson you can:

- Explain how one SHACL shape does triple duty as validation, form and API contract, and
  how the generated app, the runtime and the viewer all read the same shape.
- State the parity rule, every generator fault is a shape violation first, and say what it
  buys the person authoring a model.
- Generate a FastAPI route module and htmx templates from your model, send it invalid
  input, and read the problem+json response back to the shape that refused it.

## The story, in brief

Lesson 2 drew the line between a vocabulary that infers and a shape that rejects. This
lesson is what the project does with shapes. A `sh:NodeShape` with `sh:property`
constraints is the data contract: the runtime validates every write against it and
returns 422 with a problem+json body naming the path that failed
([ADR-0013](../../docs/adr/0013-error-shapes-and-boundaries.md)); the htmx generator reads
the same shape to lay out the form, its field order and its editors; the API's accepted and
returned payloads are declared by `seam:acceptsShape` and `seam:returnsShape`. One statement,
read three ways, and none of them restates it.

The second use of shapes is on the model itself. [`ontology/shapes/seam-shapes.ttl`](../../ontology/shapes/seam-shapes.ttl)
says what a well-formed model is: every model has exactly one notation, `seam:decidedBy`
joins only a business-rule task to a decision, and so on. The viewer's health badge is this
validation, and principle 5 adds the rule that makes it matter: a fault a generator can hit
must be a shape violation first, so that a model which passes the shapes generates. A
parity test enforces the rule, and the generator kit research note explains where it came
from, Boersma's principle that "no reported issues" must mean generation works.

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

1. Submit the form with an amount of zero. Read the 422 body and find the shape path it
   names in your TriG.
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
