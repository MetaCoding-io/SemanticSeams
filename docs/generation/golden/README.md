# Golden generator outputs for the chat app

This directory holds the generator dry run from backlog item **G2**, a
follow-up to [ADR-0007](../../adr/0007-execution-strategy.md). It contains the
three artifacts the generators should produce for `examples/chat-app/`,
written by hand before any generator code exists:

| Artifact | Generated from | Target |
|----------|----------------|--------|
| [`compose.yaml`](compose.yaml) | `deploy:` / `arch:` on the containers | docker-compose for the whole system |
| [`chat_page.html`](chat_page.html) | `ifml:` on `:chat_page` plus the seams it touches | htmx / Jinja2 page |
| `chat_api.py` | `seam:exposes` on `:chat_api` plus the hydra/comm contract | thin FastAPI route module |

They follow ADR-0007: handlers stay thin and the runtime interprets the
BPMN/DMN/SHACL payloads, secrets are passed by reference only, the model is
mounted into the app container, and every file carries a generated-file
header with the model hash.

Each line is marked with where it would come from. The lines the graph cannot
produce are collected in [`gaps.md`](gaps.md), which is the input to M004's
vocabulary slice. `tests/test_golden_outputs.py` checks the markings against
`examples/chat-app/chat-app.trig`, so a generator has a test to pass before it
exists.

The goldens are **expected outputs with markers**. A generator emits the same
content **without** the markers: strip the trailing marker comment (and any
comment that becomes empty) and the rest is the target.

## Marking convention

Every non-blank line of a golden artifact ends with exactly one marker inside
a trailing comment in that file's syntax: `# ...` for Python and YAML,
`{# ... #}` for the Jinja2/htmx page.

| Marker | Meaning |
|--------|---------|
| `[graph: <evidence>]` | The line is producible from the model. The evidence cites the terms it comes from. |
| `[fixed]` | A constant of the generator template that does not depend on the model, such as imports, `services:` or the header line. |
| `[gap: GAP-NN]` | The graph cannot say what this line needs. `GAP-NN` is a row in [`gaps.md`](gaps.md). |

Evidence is a whitespace-separated list of model terms:

- `:local` or `:chat_bpmn#frag` is an IRI under `https://example.org/chat/`.
  It must occur as a subject or object in the dataset.
- `prefix:term` uses one of the trig's prefixes (`seam`, `arch`, `ifml`,
  `deploy`, `hydra`, `comm`, `proc`, `dec`, `state`, `sh`, `rdfs`, `odrl`). It
  must occur as a predicate or as an object, which covers `rdf:type` classes
  and enumeration values such as `seam:UIFragment`.
- `<iri>` is a full IRI, used for terms outside the chat namespace such as
  `deploy:secretRef` targets. It must occur as a subject or object.
- Other words, such as arrows or `a`, are allowed and ignored. A graph marker
  must cite at least one term.

Do not invent model terms. If a line needs a term that is not in the trig, the
line is a gap, and the proposed term goes in the gap table.

## Producibility summary

Counts of non-blank lines per marker. M004 drives the gap column toward zero.

| Artifact | graph | fixed | gap |
|----------|------:|------:|----:|
| compose.yaml | 20 | 7 | 42 |
| chat_page.html | 39 | 18 | 21 |
| chat_api.py | | | |
