# Lesson 8 · Questions no single tool can answer

*The query catalog, rows that continuous integration asserts, and diagrams derived
rather than drawn.*

::: info Module B draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module B pull request.
:::

## Outcomes

After this lesson you can:

- Read each question in the catalog as a property path over the seams and say which join
  it could not be asked without.
- Explain how a question becomes a viewer button, a test with pinned rows and a reference
  page, with one `.rq` file as the source of all three.
- Derive a sequence diagram and an event storm from a model, and argue why neither should
  ever be authored.

## The story, in brief

Lesson 1's thesis was that notations with engines survive. Lesson 5 joined the survivors.
This lesson is the payoff the project outline called "arguably bigger than the zoom": the
questions. "Which screens can eventually write this data" is one SPARQL property path from
an IFML event through `seam:triggers`, into the process's elements, through decisions and
invocations and across a channel into a subscribing process, to whatever `seam:writes` the
shape. "What breaks if this node goes away" is another. Each lives in
[`docs/queries/`](../../docs/queries/README.md) as one file, which the viewer offers as a
button in product language, continuous integration runs against every example with exact
expected rows, and the docs site renders as a reference page. A question that returns zero
rows is the project's original sin, from the first review, and the acceptance test exists
so that it can never happen silently again. Gate queries invert the idea: a `SELECT` that
must return no rows, such as "every UI event that can write data with no policy governing
it", which `seams check` runs for a project and fails on any row.

The second half of the lesson is the UML coverage note's conclusion. Every UML diagram is
either covered by a pillar notation or derivable from seams that exist, and authoring one
would create a second source of truth. So the sequence diagram is derived: `seams sequence`
walks an IFML event's path through the graph, one Mermaid diagram per gateway path, with a
`%% gap:` line for every arrow the model cannot place, and `--trace` draws the as-executed
counterpart from a recorded run. The event storm is derived the same way by `seams storm`.
A gap in a derived diagram is a model audit, not a drawing problem.

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
