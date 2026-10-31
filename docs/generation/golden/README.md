# Golden generator outputs for the chat app

This directory holds the generator dry run from backlog item **G2**, a
follow-up to [ADR-0007](../../adr/0007-execution-strategy.md). It contains the
artifacts the generators should produce for `examples/chat-app/`. The first
three were written by hand before any generator code existed; the compose file
became one file per environment with ADR-0015:

| Artifact | Generated from | Target |
|----------|----------------|--------|
| [`compose.development.yaml`](compose.development.yaml) | `deploy:` / `arch:` on the containers, with their `:development` overrides | docker compose for a laptop run |
| [`compose.production.yaml`](compose.production.yaml) | `deploy:` / `arch:` on the containers, placed on the nodes `:production` contains | docker compose (swarm) for production |
| [`chat_page.html`](chat_page.html) | `ifml:` on `:chat_page` plus the seams it touches | htmx / Jinja2 page |
| [`chat_api.py`](chat_api.py) | `seam:exposes` on `:chat_api` plus the hydra/comm contract | thin FastAPI route module |

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

Each gap row has a `Status`: `open`, `closed (vocabulary)`, `closed (rule)` or
`deferred: <reason>`. When a row closes, the lines that cited it become
`[graph: ...]` markers and the row stays in the table as history. The doc-lint
checks that no golden marker cites a closed row, that every open or deferred
row for a golden file is still cited, and that a deferred row gives a reason.
Rows whose Artifact starts with `runtime` (the ADR-0007 spike gaps) belong to
no golden file and are exempt from the citation check.

## Producibility summary

Counts of non-blank lines per marker, updated as gap rows close. M004 drives the gap column toward zero.

| Artifact | graph | fixed | gap |
|----------|------:|------:|----:|
| compose.development.yaml | 74 | 18 | 0 |
| compose.production.yaml | 81 | 18 | 0 |
| chat_page.html | 61 | 18 | 0 |
| chat_api.py | 33 | 14 | 0 |
| **total** | **249** | **68** | **0** |

**After M004/S02.** All 27 rows are closed: 22 by vocabulary or model
additions and 5 by documented rules (GAP-04, GAP-16, GAP-21, GAP-26 and
GAP-27; GAP-10 and GAP-15 also carry rule halves). No row is deferred, so no golden
line carries a `[gap: ...]` marker and the doc-lint now rejects any `open`
row. One sub-item is handed on rather than modelled: the authentication scheme
behind `:authenticated_user` (GAP-20) belongs to the S03 worker.

**After M004/S04/T01.** GAP-28 (component order within a ViewContainer) was
found while aligning `chat_page.html` with the htmx generator and landed
closed by `ifml:order`. The same alignment (D016) dropped the hand-chosen
`message--<role>` class, which no graph fact supports, in favour of the
shape's `rdfs:label`, and put the message item fields in `sh:order`, which adds
one `role` line.

**After M004/S05.** `chat_api.py` was aligned with the FastAPI route generator
(D017): its endpoint blocks and the `seam:exposes` header list are in IRI order,
and the thread read passes the Details component's path-variable parameter
(`conversation=conversation`, from `ifml:hasParameter :conversation`) to
`render_fragment`. The line counts are unchanged.

**After M016/S02 (ADR-0015).** `compose.yaml` was replaced by one golden per
`arch:Environment`: `compose.development.yaml` and `compose.production.yaml`.
Each has an `# environment:` header line and the project `name:` (the
`arch:System`'s local name). The development file comes from the containers'
`deploy:override`s: built images (`deploy:build`), secrets read from files
(`deploy:secretFile`) and values a host can override (`${KEY:-value}`), with
no placement because `:development` contains no nodes. Both files gain the
generator rules from ADR-0015's inventory, marked `[fixed]` where no model
fact is behind them: the healthcheck timings, the serving container's
`/healthz` probe and the replica-cap comment. No new gap row was needed. The
earlier compose counts (62 graph, 7 fixed) were for the single file.

## Feeding M004

The 28 gaps in [`gaps.md`](gaps.md): GAP-01..GAP-22 from the golden dry run,
GAP-23..GAP-27 from the ADR-0007 spike and GAP-28 from the S04 htmx generator. M004 closes them row by row and
records the outcome in the `Status` column. Grouped by the vocabulary namespace
that would close them (a gap that spans two layers is listed under both):

- **`deploy:`**: container images (GAP-01), ports (GAP-02), volumes (GAP-03),
  placement meaning (GAP-04), secret resolution (GAP-05), non-secret config
  (GAP-06) and readiness (GAP-07). This is the largest group and accounts for
  most of the compose gap lines.
- **`comm:` / `hydra:`**: operation paths (GAP-08), read operations (GAP-11),
  SSE/channel transport (GAP-15) and request encoding (GAP-18).
- **`ifml:`**: event-to-operation binding (GAP-09), swap and trigger (GAP-10),
  form field binding and presentation (GAP-12, GAP-13), the page route and
  title (GAP-17), the response partial (GAP-19) and component order (GAP-28).
- **`seam:`**: event-to-operation binding (GAP-09), state-guard evaluation
  (GAP-16), operation to component (GAP-19), policy on the operation (GAP-20)
  and handler naming (GAP-21).
- **Data shapes (`sh:`)**: the identifier convention (GAP-11), user-entered
  fields and required-ness (GAP-12), field order and widget (GAP-13) and the
  `:status` value set (GAP-14, with `state:`).
- **`proc:`**: the process correlation key (GAP-22), the BPMN message
  reference (GAP-26) and the implementation binding (GAP-27).
- **`dec:`**: the decision-id join (GAP-23), DMN input binding (GAP-24) and
  DMN output key (GAP-25).
- **`odrl:` / `arch:`**: evaluable policy rules and the auth scheme (GAP-20),
  plus the `arch:dependsOn` startup rule (GAP-07) and node selectors (GAP-04).

The generator vocabulary names (`seams_runtime.Runtime` and its
`validate` / `start_process` / `render_fragment` / `subscribe` methods) are
marked `[fixed]`: they belong to the generator and runtime, not to the model.
