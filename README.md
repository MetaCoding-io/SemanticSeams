# SemanticSeams

*A zoomable, multi-notation application graph. One RDF graph is the source of truth; diagrams are views.*

A [MetaCoding](https://metacoding.io) project · [project page](https://metacoding-io.github.io/SemanticSeams/) · [docs](https://metacoding-io.github.io/SemanticSeams/docs/) · [tutorial](docs/tutorial.md) · [expense tutorial](docs/tutorials/expenses/index.md) · [seams library](docs/reference/seams-library.md) · [write your own generator](docs/guide/write-your-own-generator.md) · [project outline](docs/project-outline.md) · [decisions](docs/adr/) · [backlog](docs/backlog.md)

**The pitch, in one paragraph.** Every tool that draws software draws one layer: C4 tools stop at the repository link, BPMN modelers never see the UI that fires a process, IFML never wired up its hooks to data, and SHACL lives in its own silo. SemanticSeams puts every element of every layer in one RDF graph, as a resource with an IRI, and treats each diagram as a view over it. Click a C4 container and land on its IFML interaction model; click a UI event and land on the BPMN process it triggers; click a business-rule task and land on the DMN table; click a data object and land on the SHACL shape. The cross-layer edges are the *seams*, a small bridging ontology of 28 predicates, and because the whole system is one graph, the questions no single-notation tool can answer become SPARQL.

Click into a C4-style architecture component and land on an IFML interaction model. Click a UI event and land on the BPMN process it triggers. Click a business-rule task and land on a DMN decision table; click a data object and land on the RDF/SHACL shape graph. Four notations, one traversal — driven by 28 bridging predicates (the *seams*), not by tool integration glue.

Because everything shares one graph, you also get cross-layer queries no single-notation tool can answer:

- *Show me every UI event reachable by role X that eventually writes to this shape.*
- *Which BPMN tasks are allowed to fire this state transition?*
- *What breaks if db01 goes away?*

Full motivation, landscape survey, and design: [`docs/project-outline.md`](docs/project-outline.md).

## Layout

```
docs/       the docs site (VitePress; reference pages generated from ontology/ and docs/queries/),
            project outline (vision, pillars, landscape, stack, seam design rules)
  queries/  canned cross-layer queries (*.rq) — the query catalog the viewer's buttons and CI both drive
ontology/   seam.ttl        — the bridging ontology (the load-bearing part)
            arch.ttl        — minimal C4-style architecture vocabulary
            ifml.ttl        — IFML-inspired interaction vocabulary (documented correspondence + deviations vs OMG IFML)
            proc.ttl        — process/decision index types (NOT a BPMN ontology; see file header)
            state-comm.ttl  — statechart lifecycle + communication (channels; Hydra fills the rest)
            deploy.ttl      — deployment stub: artifact/config/placement; desired-state half of a GitOps loop
  shapes/   seam-shapes.ttl — SHACL constraints on the seams themselves (the project's own methodology, applied to itself)
examples/   checkout.ttl    — worked example exercising every non-reserved seam edge; the ontology smoke test
packages/   seams/          — the read-only `seams` model library (rdflib + lxml only): loader, typed views per layer, BPMN flow walks and DMN tables (lxml), SPARQL helpers, model hash, payloads, and ModelGraph (the resolver facade over the views)
tests/      executable acceptance test: parse everything, validate against the shapes, assert the canned queries' rows
site/       the public project page (GitHub Pages, no build step)
viewer/     the read-only multi-layer browser (FastAPI + htmx + bpmn-js/dmn-js)
```

Notes on deliberate omissions: there is no BPMN/DMN ontology here. Native XML serializations are stored as `seam:renderPayload` and rendered by bpmn-js/dmn-js; only seam-participating elements get IRIs, using **BPMN element IDs as IRI fragments** (`:order_bpmn#persist_task`), which makes a stock bpmn-js viewer a full participant in the graph via its `element.click` event. Fragment naming serves renderer dispatch only — membership is data: every lifted element carries `seam:inModel`, the edge cross-layer SPARQL actually traverses. The thin `proc:`/`dec:` index vocabulary types only these seam-participating elements. The data layer needs no vocabulary at all — SHACL *is* the vocabulary.

## Tests

Install [uv](https://docs.astral.sh/uv/), then sync the workspace from the committed
`uv.lock` and run the suite:

```
uv sync --all-packages
source .venv/bin/activate
pytest
```

The suite (also run in CI) parses every Turtle file, validates the example against `ontology/shapes/seam-shapes.ttl`, proves the shapes reject invalid seams, checks every non-reserved seam predicate is exercised, and asserts exact expected rows for the canned queries in `docs/queries/` — so the flagship cross-layer traversals can never silently regress to zero rows.

## Tutorial

[`docs/tutorial.md`](docs/tutorial.md) goes from a clean checkout to a running chat app:
regenerate the code from the chat-app model, `docker compose up --build`, open
http://localhost:8080 and chat with an LLM (OpenAI, any OpenAI-compatible server, or the
gateway's built-in stub). CI runs the same stack end to end.

[`docs/tutorials/expenses/`](docs/tutorials/expenses/index.md) is the slower track: build
an expense approval app yourself, one layer per chapter, from an empty TriG file to the
whole system under `docker compose up`. All eight chapters (architecture, data, screens,
process, rules, lifecycle, permissions, and growing up with an asynchronous payout) are
written; CI checks each chapter's checkpoint model in `examples/expenses/` and runs the
last one under docker compose.

## Generators

Each app keeps a `seams.toml` project file next to its model naming the generators and
their output directories; `seams generate --project examples/chat-app` (installed by
`uv sync --all-packages`) runs them all and rewrites the committed chat-app outputs and
`examples/chat-app/seams.lock`, which records each output's generator version, file hash
and source model elements. `seams check` writes nothing: it validates the model against the SHACL shapes,
runs the project's gate queries and fails on any stale, missing, hand-edited or orphaned
output. CI runs it for every example through the composite action in
`.github/actions/seams-check`, and `.pre-commit-hooks.yaml` offers it as a pre-commit hook.
`seams status` reads each running runtime container's `/healthz` and reports it as current,
behind, ahead or unreachable compared with the current model.
`seams sequence <event>` derives an IFML event's Mermaid sequence diagrams from the graph,
one per gateway path, with a `%% gap:` line for every arrow the model cannot place.
The viewer shows them per event (its Sequences section and `GET /sequence/{event}`), and
the docs embed the golden diagrams, rendered with Mermaid.
The project file, the commands, the lockfile, the action and the hook are described in the
[seams CLI reference](docs/reference/seams-cli.md).

To run a single generator, `python -m seams_gen htmx examples/chat-app/chat-app.trig --out build/`
generates the chat page's Jinja2/htmx template from the IFML model and the seams it
touches. The output matches the golden in `docs/generation/golden/` byte for byte. The
rendering rules, each keyed on a graph fact, are in [`seams_gen/README.md`](seams_gen/README.md).

`python -m seams_gen.complexity examples/chat-app/chat-app.trig` measures a model's
size (models per notation, most-reached elements, seam edges) and prints PASS or FAIL
against thresholds; the chat app fails by design.

## v1: the viewer

Read-only, navigable, notation-switching browser over a hand-authored model. Stack:

- **Fuseki** — model store; one named graph per `seam:Model`
- **FastAPI** — three endpoints: describe node (JSON-LD, triples + seam edges), fetch render payload, SPARQL passthrough (HTTP QUERY, RFC 10008)
- **htmx shell** — every click is `hx-get /view/{iri}`; server dispatches on `seam:notation`
- **Renderers** — bpmn-js `NavigatedViewer` and dmn-js (read-only) for process/decision layers; a shared node-link renderer (elkjs layout, SVG cards) for architecture and shape graphs; IFML notation on diagram-js (server-computed layout, ELK ports for events); vis-network for statecharts

Milestone 1: load `examples/checkout.ttl` + a hand-drawn `order_process.bpmn`, and complete the descent arch → IFML → BPMN → DMN/shape-graph purely by clicking.

## Roadmap (after v1)

Editing (embed modelers read-write) → SHACL-driven form generation → IFML→htmx generation → BPMN interpretation (SpiffWorkflow) → deployment generation (compose/Ansible from deploy: + drift detection as named-graph SPARQL diff) → methodology profiles as SHACL-shapes-over-the-model (IDesign first) → project-design projection (activities/Gantt derived from architecture, Löwy-style).

## Status

Concept and proof-of-concept (July–September 2026): the bridging ontology, the SHACL
shapes over it, two worked examples (a checkout flow and a chat app), the canned
cross-layer queries, and a read-only viewer that completes the architecture → UI →
process → decision descent by clicking. See the [project outline](docs/project-outline.md)
for the design and the [ADRs](docs/adr/) for the decisions taken so far.

## Related

- [semantic-stack](https://github.com/MetaCoding-io/semantic-stack) — the Docker stack
  (Fuseki, QLever, RDF4J, OntoRefine, YASGUI, WebVOWL, Blueprint and more) this project
  is developed against.
- [MetaCoding](https://metacoding.io) — the data-centric consultancy behind both.

## License

[Apache-2.0](LICENSE). Copyright © 2026 MetaCoding.
