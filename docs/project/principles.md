# Design and coding principles

These are the rules this repository's code follows. They are written for anyone who
changes it, people and coding agents alike: GSD milestones, Claude Code sessions,
reviewers. Each principle says what to do, why, and how it is checked. A principle
with no check yet names the backlog item that adds one.

**Precedence.** An accepted ADR wins over this page, and this page wins over habit. If
a principle here conflicts with an ADR, the ADR is right and this page needs fixing.
If a task seems to need breaking a principle, stop and write the question down, in an
ADR draft or a backlog note, before writing the code.

## Design principles

### 1. The model is the source of truth

Every fact about the application is stated once, in the model. Code, templates, stubs
and drafts read facts from the model; they never restate them.

- No domain literals in generators, templates or runtime code: no page names, field
  names, status strings or paths that the model already holds.
- When a value appears in two places, one of them derives from the other. Today three
  shapes copy their lifecycle's state labels into `sh:in` lists. That is the pattern to
  avoid, and backlog O2 removes it.
- **Check:** golden tests fail on hard-coded output. The generator README's "no domain
  literals in the template" rule. R1 adds a model review for duplicated facts.

### 2. Interpret behaviour, generate structure

BPMN and DMN are executed by the runtime from their native XML; they are not compiled
into code ([ADR-0007](/adr/0007-execution-strategy)). Generators produce structure:
templates, routes and compose files.

- A change to a decision table or a process flow must not require regenerating code.
- **Check:** `test_changing_the_threshold_moves_only_the_hash_lines` in
  `tests/test_expense_process_app.py`. Editing a DMN threshold changes only the
  model-hash lines of the generated code.

### 3. Notations stay native; seams join them

Each notation keeps its own format and its own named graph. Cross-layer facts are
seam edges, and they live only in `<urn:seams:graph:seams>`
([ADR-0001](/adr/0001-named-graph-partitioning)).

- Only BPMN and DMN elements that take part in a seam get an IRI, and that IRI is the
  model IRI with the XML `id` as its fragment ([ADR-0002](/adr/0002-iri-identity-and-migration)).
- Every seam predicate declares a `seam:reveal` mode. Navigation derives from that, never
  from a hard-coded list ([ADR-0005](/adr/0005-navigation-resolution)).
- **Check:** the test suite fails on a `seam:` predicate outside the seams graph, and
  `seamsh:RevealShape` requires a reveal mode.

### 4. Vocabulary is earned

Add a class or predicate only when a concrete question or generated line needs it, and
add the smallest thing that answers it. The backlog's "Vocabulary impact" column records
every addition and why it was needed.

- Prefer an existing term (SHACL, IFML, gist) over a new one.
- **Check:** review. A new term without a backlog row or ADR explaining it is a review
  finding.

### 5. Shapes catch faults before generation

If the model passes the shapes, generation must succeed. Every condition that makes a
generator raise `GeneratorError` is also a shape violation, or is documented as
generator-only with the reason.

- Invalid models can still be saved, shared and viewed; they are flagged, never refused.
- **Check:** today, partial. Two known gaps: `ifml:order` and `seam:reads` on lists. K1
  adds a parity test.

### 6. Same model, same bytes

Generation is deterministic. The same model always produces byte-identical output.

- Sort every collection explicitly; do not rely on graph or dictionary order.
- No timestamps, absolute paths or host names in output. Identify the model by its
  content hash (`model.hash`).
- **Check:** golden tests and the "Generated outputs are current" CI step regenerate the
  committed outputs and fail on any diff.

### 7. Everything generated can say where it came from

Generated files carry a header naming the generator and the model hash, and comments
naming the model facts behind each section.

- Golden outputs mark every line with its evidence (`[graph: …]`, `[fixed]`,
  `[gap: …]`).
- LLM-drafted code is traced by the model context it was given, at file level.
- **Check:** golden marker tests today. T1 adds machine-readable traces, and C3 adds
  context manifests.

### 8. Generated code and owned code never mix

Generated files are never edited by hand. Code a person or an LLM writes lives in its
own files, behind a generated stub, in the location U6 defines.

- An LLM draft is accepted once, after its model-derived tests pass, and is then owned
  like hand-written code. Regeneration proposes a diff; it never overwrites.
- CI never calls an LLM.
- **Check:** the regeneration step in CI, and ruff's exclusion of generated directories.
  C5 adds staleness and hand-edit detection.

### 9. Data outlives applications

The direction is data-centric: the domain model and its data are the long-lived asset,
and applications are built on them.

- Declare what things are. Shapes target classes (`sh:targetClass`). Properties are
  declared once. Classes are anchored in gist where the fit is honest.
- Use IRIs for categories such as states, outcomes and kinds, not strings.
- Do not add a store, column or payload field that bypasses the shapes.
- RDF storage, with SemPKM as the intended default for deployments, is the direction for
  instance data (O4).
- **Check:** R1's model review. Until O1 and O2 land, this is a review rule.

### 10. Read-only until editing is reopened

The viewer and the `seams` library are read-only. Editing is a v1 non-goal (backlog P2
item 13). The I-series items are the plan if that changes.

- **Check:** review. The `seams` library has no write API.

### 11. Decisions are written down

- An architectural choice gets an ADR in `docs/adr/`.
- An exploration gets a research note in `docs/research/`.
- Planned work gets a backlog row in `docs/backlog.md`.
- Research notes and accepted ADRs are records. Add a dated revision note rather than
  rewriting what they said.

## Coding principles

### Tooling

- The repository is a **uv workspace**. Install with `uv sync --locked --all-packages`,
  and run everything through `uv run`. Do not use `pip install`, requirements files or
  unpinned installs. `uv.lock` is committed.
- Python 3.12 (`.python-version`). The `seams` library is checked with strict pyright.

### Gates before every push

Run what CI runs, for the parts you touched:

```sh
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest -q
```

When you touch a generator, a template or `examples/chat-app/chat-app.trig`, regenerate
the committed outputs and confirm they are what you intend. CI fails if regeneration
changes anything you did not commit:

```sh
trig=examples/chat-app/chat-app.trig
uv run python -m seams_gen fastapi "$trig" --out examples/chat-app/generated
uv run python -m seams_gen htmx "$trig" --out examples/chat-app/generated/templates
uv run python -m seams_gen compose "$trig" --out .
git status --short -- examples/chat-app/generated compose.yaml
```

When you touch `docs/`, build the site: `cd docs && uv run npm run build`.

When you touch the runtime, the generators or the compose setup, run the end-to-end
tests. They need Docker:

```sh
SEAMS_E2E=1 uv run pytest -q tests/test_tutorial_e2e.py tests/test_expense_e2e.py
```

Never skip, mark as expected to fail, or delete a test to get green. Fix the cause, or
stop and report it.

### Package boundaries

| Package | Owns | Must not |
|---|---|---|
| `packages/seams` | Loading, hashing, payload resolution, typed read-only views, joins with native BPMN and DMN | Depend on anything beyond rdflib and lxml; write; execute |
| `seams_gen` | Generators: `extract` from views, then `render` | Query the graph around the views; hold domain literals |
| `seams_runtime` | Execution: the engine, worker, store, policy | Re-implement model reading that `seams` provides |
| `viewer` | Read-only rendering and navigation | Write to the model |

- Import only public names across packages. A leading underscore means private to its
  module.
- Prefer extending a `seams` view over writing SPARQL in a caller. When SPARQL is right,
  put the query in `docs/queries/` and run it by name.

### Errors name the fact

- A model fault raises an error that names the subject, the predicate and what is
  wrong: `GeneratorError` in generators, `ResolutionError` in the library. Never use a
  bare `ValueError` or `KeyError` for a model problem.
- On a model fault, write nothing. CLI exit codes follow the generator README: 2 for a
  model fault, 1 for a file that cannot be read or written.

### Collections, not singletons

Views return collections. Where a caller needs exactly one, call `.only()`, which
raises `ResolutionError` on none or several. Never take "the first" silently: M009's
second process, decision and page showed what that costs.

### Templates hold text, not logic

- Generators are `extract` (graph to a frozen view model) then `render` (view model to
  text). All computation happens in `extract`: names, joins, conditions, formatting.
- Templates loop over prepared values and emit text. Filters, string concatenation and
  inline conditions inside a template are a smell. T2 moves the 43 that exist today.
- Templates use the `[[ ]]` and `[% %]` delimiters, so the Jinja2 they emit stays plain
  text.

### Tests

- Generator output is tested byte for byte against goldens (`golden_target`).
- Fix a bug by first writing a test that fails because of it.
- The examples are fixtures. `examples/chat-app` and every
  `examples/expenses/chapter-NN` checkpoint must conform to the shapes. Tests run against
  the chat app and chapter 8.
- A test asserts the behaviour a reader would expect, not an implementation detail that
  happens to hold.

### Generated and derived files

- **Never hand-edit:**
  - committed generated outputs (`examples/**/generated`, the root `compose.yaml`);
  - golden outputs, except deliberately, with their markers;
  - the reference pages generated by `docs/scripts/generate.py`.

  Change the source and regenerate.
- **Keep the documentation honest.** When behaviour changes, update the guide page that
  describes it (`docs/guide/`) and the package README in the same change.

### Model files

Model files follow the [authoring guide](/guide/authoring-a-model):

- every element has an `rdfs:label` and a `seam:inModel`;
- seam predicates live only in the seams graph;
- each BPMN and DMN model has a `seam:renderPayload`.

Comments in TriG explain why, not what. Keep every tutorial checkpoint valid when you
change one, because the chapters build on each other.

### Security

- No secret values in models, prompts, logs or generated files. Models name secrets with
  `deploy:secretRef`.
- Model text that reaches an LLM prompt is quoted as data, never treated as
  instructions.
- Generated code and LLM drafts run inside the application, so review them like any
  other contribution.

### Commits and pull requests

- **One concern per change.** Keep a refactor apart from a behaviour change.
- **Commit messages explain why.** The diff already shows what changed.
- **No third-party copyrighted material in the repository.** Cite books by page and
  paraphrase them.
- **Keep pull requests reviewable.** A pull request that touches generators says which
  goldens changed and why.

## For coding agents

These add to everything above when a GSD milestone or a Claude session does the work.

- **Read before changing.** Read the ADRs and the package README that govern a module
  before editing it. `seams_gen/README.md` states each generator's rules line by line.
- **Do not invent vocabulary,** IRIs or file locations. If the model lacks a fact the
  code needs, that is a vocabulary question for a backlog row or ADR, not a constant in
  code.
- **Verify claims against the code.** Counts, file names and behaviour in docs and
  commit messages must be checked, not recalled.
- **Prefer the smallest change that keeps every gate green.** Do not widen a task to
  fix unrelated things; note them in the backlog instead.
- **When a principle and a task conflict, ask** before writing code. A short written
  question is cheaper than a reverted milestone.

## Review checklist

A short list to paste into a pull request or a review prompt:

- [ ] No domain literal in code or templates that the model already states.
- [ ] New or changed model facts have shapes; a generator fault has a matching shape.
- [ ] Output is deterministic; collections are sorted; goldens updated deliberately.
- [ ] Committed generated outputs regenerated; nothing hand-edited.
- [ ] Cross-package imports use public names; `seams` gained no dependency.
- [ ] Errors name subject, predicate and detail.
- [ ] Logic lives in `extract`, not in templates.
- [ ] Tests added or updated; none skipped; ruff, pyright, pytest and the docs build pass.
- [ ] Vocabulary additions have a backlog row or ADR.
- [ ] Docs and README describe the new behaviour.
