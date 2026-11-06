# Lesson 9 · Code the templates cannot write

*A stub written once and then owned, errors declared in the model, and a language model
that drafts behind the stub while tests derived from the model decide. The project's answer
to the first failure, past the cliff.*

::: info Module C draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module C pull request.
:::

## Outcomes

After this lesson you can:

- Locate the expressiveness cliff in a SemanticSeams model exactly: the operation that is
  `seam:implementedBy` a Python handler, and nothing else.
- Explain the stub-once-then-owned rule and what the generator does and does not do to a
  handler on regeneration.
- Write a service-task handler, declare the error it can raise and the boundary event that
  catches it, run the acceptance tests the model derives for it, and, optionally, have a
  language model draft it under the same tests.

## The story, in brief

Lesson 2 said the problem is not that declarative languages end but that nobody marks where.
[ADR-0012](../../docs/adr/0012-operation-implementation.md) marks it. An operation is
`seam:implementedBy` one of three things: an LLM completion, an HTTP endpoint, or a Python
handler. For a handler, the generator writes a stub once, typed from the shapes the
operation accepts and returns, with a docstring that names the invoking task, its decision
and the transition it fires, and a context hash of the model facts the code depends on. Then
the file is owned. `seams generate` never touches it again; `seams check` says when the
facts behind it have changed. [ADR-0013](../../docs/adr/0013-error-shapes-and-boundaries.md)
adds the failure half: an operation declares the problem+json errors it can return, and a
BPMN boundary event `seam:catches` one, so the failure path is in the diagram, not in a
`try` block the model cannot see.

Then the language model, under [ADR-0020](../../docs/adr/0020-llm-drafts.md). `seams
propose` builds a prompt from the same context the stub cites, with every model fact quoted
as data and never as instruction, sends it to whatever provider command the project names,
and caches the answer by context hash. The draft is written into the handlers package only
when the acceptance tests the `acceptance` generator derived from the model pass in a
scratch copy: a type check against the stub, shape conformance per valid example, the
transition guard, the decision's routing. An accepted draft is recorded in the lock and then
owned like anything hand-written. Principle 8 states the rule the whole design serves:
generated code and owned code never mix, and continuous integration never calls a language
model.

## Read in the repo

- [ADR-0012](../../docs/adr/0012-operation-implementation.md) and
  [ADR-0020](../../docs/adr/0020-llm-drafts.md).
- [An LLM generator for the code templates cannot
  write](../../docs/research/2026-10-31-llm-generator.md). The argument, and its revision
  notes recording C1 to C5 as they shipped.
- The prompt template itself,
  [`draft-v1.txt`](../../packages/seams-cli/src/seams_cli/prompts/draft-v1.txt). Notice how
  the model's facts are quoted.

## Lab: chapter 9

Work through [chapter 9, Hand-written code](../../docs/tutorials/expenses/09-hand-written-code.md):
the Notify Manager service task, the operation and its implementation, the stub, the
handler, and the error path. Then:

1. Run `seams generate` again and confirm the handler is untouched. Run `seams check` and
   read what it says about the stub's context hash.
2. Change the shape the handler accepts, by adding a required field, and run the
   acceptance tests. Read the failure: it is the model telling the owned code it has
   drifted.
3. Optional, with a provider command: run `seams propose` for the task as the chapter
   shows, read the draft before you accept it, and find its record in `seams.lock`. Without
   a provider, read the prompt template and write down what the language model is and is
   not allowed to see.

Diff against `examples/expenses/chapter-09/expenses.trig` and
[`examples/expenses/chapter-09/handlers/`](../../examples/expenses/chapter-09/handlers/)
when done.

## Scorecard

- **F1, closed.** The cliff is one predicate. The hand-written code sits behind a generated
  stub in its own file, the generator never visits it, and a change to the facts it depends
  on is reported rather than overwritten.
- **F6, moved.** The language model is a generator whose output is admitted only by tests
  the model derived, and never in continuous integration.
- **F2, framed.** The owned code knows its facts by hash. Lesson 10 is about edits in the
  other direction.

## Further reading

- Thomas Stahl and Markus Völter, *Model-Driven Software Development*, 2006, on the
  separation of generated and manual code, which this lesson implements with a predicate
  instead of a convention.
- IETF, *RFC 9457*, problem details, the error contract.
- The project's [domain vocabulary as spec note](../../docs/research/2026-11-03-domain-vocabulary-as-spec.md),
  on what a coding agent should be given from the model, and what it must never be the
  source of.
