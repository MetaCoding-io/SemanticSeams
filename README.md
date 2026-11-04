# SemanticSeams

*A zoomable, multi-notation application graph. One RDF graph is the source of truth; diagrams are views.*

A [MetaCoding](https://metacoding.io) project · [project page](https://metacoding-io.github.io/SemanticSeams/) · [docs](https://metacoding-io.github.io/SemanticSeams/docs/) · [tutorial](docs/tutorial.md) · [expense tutorial](docs/tutorials/expenses/index.md) · [seams library](docs/reference/seams-library.md) · [write your own generator](docs/guide/write-your-own-generator.md) · [project outline](docs/project-outline.md) · [decisions](docs/adr/) · [backlog](docs/backlog.md) · [design and coding principles](docs/project/principles.md)

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
  vendor/   gistCore14.0.0.ttl — the pinned gist upper ontology a seam:Ontology model imports (ADR-0022; CC BY 4.0)
examples/   checkout.ttl    — worked example exercising every non-reserved seam edge; the ontology smoke test
packages/   seams/          — the read-only `seams` model library (rdflib + lxml only): loader, typed views per layer, BPMN flow walks and DMN tables (lxml), SPARQL helpers, model hash, payloads, and ModelGraph (the resolver facade over the views)
seams_edit/ the model's one write path (ADR-0017): quad patches applied by editing the TriG text in place, so comments and layout survive, BPMN/DMN payload saves and id renames, with undo
tests/      executable acceptance test: parse everything, validate against the shapes, assert the canned queries' rows
site/       the public project page (GitHub Pages, no build step)
viewer/     the multi-layer browser (FastAPI + htmx + bpmn-js/dmn-js); read-only unless SEAMS_EDIT=1 turns on edit mode (forms from shapes, the BPMN/DMN modelers with id renames that move seam edges, IFML editing on its diagram, saves through seams_edit, a live preview that re-runs the generators in lenient mode, in memory, and domain profiles attached by seam:conformsTo that narrow the palette, health and preview, ADR-0018); its generation view (/generation/{iri}) joins model, template and output line by line through the trace sidecars, and in edit mode writes an edited output line back to the one model literal behind it when regenerating reproduces the edit, and turns adding or removing a form input into an ifml:Parameter patch (with a sh:property for a new path) on the same rule
```

Notes on deliberate omissions: there is no BPMN/DMN ontology here. Native XML serializations are stored as `seam:renderPayload` and rendered by bpmn-js/dmn-js; only seam-participating elements get IRIs, using **BPMN element IDs as IRI fragments** (`:order_bpmn#persist_task`), which makes a stock bpmn-js viewer a full participant in the graph via its `element.click` event. Fragment naming serves renderer dispatch only — membership is data: every lifted element carries `seam:inModel`, the edge cross-layer SPARQL actually traverses. The thin `proc:`/`dec:` index vocabulary types only these seam-participating elements. The data layer needs no vocabulary of its own — SHACL *is* the vocabulary for the shapes. What the data *is* can be said too, as an optional `seam:Ontology` model graph whose OWL classes extend [gist](https://github.com/semanticarts/gist), imported by version IRI and resolved offline against the pinned copy in `ontology/vendor/` ([ADR-0022](docs/adr/0022-ontology-notation.md)); the expense tutorial's chapter 9 declares one, and the viewer draws it as a class view.

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
regenerate the code from the chat-app model, `docker compose -f compose.development.yaml up --build`
(a compose file generated from the model's `:development` environment, ADR-0015), open
http://localhost:8080 and chat with an LLM (OpenAI, any OpenAI-compatible server, or the
gateway's built-in stub). CI runs the same stack end to end.

[`docs/tutorials/expenses/`](docs/tutorials/expenses/index.md) is the slower track: build
an expense approval app yourself, one layer per chapter, from an empty TriG file to the
whole system under `docker compose up`. All ten chapters (architecture, data, screens,
process, rules, lifecycle, permissions, growing up with an asynchronous payout, a
hand-written service task with an error path it catches, and the expenses moved into a
SemPKM store) are written; CI checks each chapter's checkpoint model in `examples/expenses/` and runs
chapter 9 under docker compose.

## Generators

Each app keeps a `seams.toml` project file next to its model naming the generators and
their output directories; `seams generate --project examples/chat-app` (installed by
`uv sync --all-packages`) runs them all and rewrites the committed chat-app outputs and
`examples/chat-app/seams.lock`, which records each output's generator version, file hash
and source model elements. Each output also gets an `<output>.trace.json` naming the
template line and model elements behind every line
([ADR-0019](docs/adr/0019-generation-trace.md)). Generators are `seams_gen.protocol.Generator` objects found
through the `seams.generators` entry-point group, so one from another package runs the same
way, may name SHACL shapes the model must pass first, and is locked with its own version
([ADR-0016](docs/adr/0016-generator-protocol.md),
[write your own](docs/guide/write-your-own-generator.md#register-it-with-seams-generate)).
`seams generate --lenient` previews a model that still breaks a generator: it writes what
the generators produce and records each precondition or generator fault in a `faults`
list in `seams.lock`, which flags the lock (D057).
Such a generator's tests import `seams_gen.testing`, the kit the built-ins use: golden
comparison, a determinism check, output checkers per file type and the shape parity check
([test it](docs/guide/write-your-own-generator.md#test-it)).
`seams new-generator NAME --reference FILE` starts one from a hand-written output file, with a
golden test that passes as generated ([start from a reference output](docs/guide/write-your-own-generator.md#start-from-a-reference-output)).
`seams draft-generator NAME --reference FILE` has an LLM command draft that package's
template and extract step, and writes it only when its golden test passes
([ADR-0029](docs/adr/0029-llm-drafted-generators.md)).
`seams check` writes nothing: it validates the model against the SHACL shapes,
runs the project's gate queries, checks decisions statically and fails on any stale,
missing, hand-edited or orphaned output and on a `flagged` lock (one with `faults`); model review findings (lifecycle labels copied
into `sh:in`, shapes without a target class, undeclared paths) print as `review` warnings
and do not fail it, and so do `sh:Warning` shape results (a deprecated vocabulary term) and
a `vocabulary-migrated` line per migration step. CI runs it for every example through the composite action in
`.github/actions/seams-check`, and `.pre-commit-hooks.yaml` offers it as a pre-commit hook.
Each vocabulary carries an `owl:versionIRI` (`MAJOR.MINOR`, all at 1.0 today), and a model
`owl:imports` the versions it is written for in its manifest graph, as every example does
([ADR-0021](docs/adr/0021-vocabulary-versions.md)). `seams.load` loads a model on the
shipped versions as written, refuses a newer one and migrates an older one in memory with
the SPARQL Update steps in `ontology/migrations/`; `seams migrate` writes that migration
into the model's files through `seams_edit`.
`seams status` reads each running runtime container's `/healthz` and reports it as current,
behind, ahead or unreachable compared with the current model.
`seams secrets` lists every configuration key and secret of each `arch:Environment` from the
model and checks that each exists (a secret file on disk, a key in the project's `.env`, a
`docker secret ls` name) without reading a value; any missing one exits 1, and
`--write-example` writes the project's `.env.example`.
`seams sequence <event>` derives an IFML event's Mermaid sequence diagrams from the graph,
one per gateway path, with a `%% gap:` line for every arrow the model cannot place.
The viewer shows them per event (its Sequences section and `GET /sequence/{event}`), and
the docs embed the golden diagrams, rendered with Mermaid.
`seams sequence <event> --trace RUN` draws the as-executed counterpart from a recorded
run's trace rows (a trace JSON file or an instance id in the runtime's SQLite store), on
the same lifelines, with a `%% gap:` line for every row the model cannot place.
`seams diff OLD NEW` classifies each shape and operation-contract change between two
model versions as compatible or breaking, and exits 1 when any change is breaking.
`seams plan OLD NEW` turns those changes and the elements each layer adds and removes into
a Markdown change plan (release notes), between paths or git `REF:PATH` specs; on a pull
request that changes a model, CI's `change-plan` job posts it to the job summary through
the composite action in `.github/actions/seams-plan`. `seams coverage` lists, by IRI, the
BPMN paths no scenario runs, the transitions nothing fires and the permissions without a
deny test, and exits 1 on any; `coverage = ["paths"]` in `seams.toml` and the
`docs/queries/coverage/` gates make `seams check` fail on them. The `tests` generator turns the
model's `verify:` scenarios, decision examples and shape examples, and every ODRL
permission per party, into pytest files under `generated/tests`
([ADR-0014](docs/adr/0014-scenarios-and-derived-tests.md)). The `smoke` generator writes one
pytest per operation that calls it on its path against a running app (`SEAMS_SMOKE_BASE_URL`)
and checks the answer against `seam:returnsShape`; CI's `tutorial-e2e` job runs chapter 9's
against the compose stack. The `acceptance` generator writes pytest files that check
hand-written handlers against the model: their types, results, legal transitions and
decision branches. The `jsonld` generator writes a JSON-LD 1.1 context per shape with a
`sh:targetClass`, mapping each field's name to its property and each category label to its
member IRI, and the generated API serves it at `GET /contexts/<shape>.jsonld` with a
`Link` header on the routes that return that shape, so a JSON-LD client reads the same
payloads as RDF ([ADR-0024](docs/adr/0024-json-ld-context.md)). The `mentalmodel` generator
writes a SemPKM Mental Model from the ontology model, the target-classed shapes and the IFML
lists and details views, which SemPKM installs as its forms and tables
([ADR-0026](docs/adr/0026-mental-model.md)). The
runtime can also emit OpenTelemetry spans carrying element IRIs; tracing is off unless
`OTEL_EXPORTER_OTLP_ENDPOINT` is set and the `seams_runtime` `otel` extra is installed
(see [`seams_runtime/README.md`](seams_runtime/README.md)).
`seams context TASK` prints the model facts and BPMN and DMN fragments a service task's
code depends on, each hashed, with a context hash over them (`--json` for the manifest).
`seams propose TASK` sends a draft prompt for that task to an LLM command and writes the
handler only when its acceptance tests pass.
`seams suggest` asks the same LLM command for a model change, such as moving a gateway's
inline condition into a DMN decision, checks it in a scratch copy and keeps it pending with
a diff until `seams suggest --accept ID` writes it
([ADR-0028](docs/adr/0028-copilot-suggestions.md)).
The project file, the commands, the lockfile, the action and the hook are described in the
[seams CLI reference](docs/reference/seams-cli.md).

To run a single generator, `python -m seams_gen htmx examples/chat-app/chat-app.trig --out build/`
generates the chat page's Jinja2/htmx template from the IFML model and the seams it
touches. The output matches the golden in `docs/generation/golden/` byte for byte. The
rendering rules, each keyed on a graph fact, are in [`seams_gen/README.md`](seams_gen/README.md).

`python -m seams_gen.complexity examples/chat-app/chat-app.trig` measures a model's
size (models per notation, most-reached elements, seam edges) and prints PASS or FAIL
against thresholds; the chat app fails by design.

`python -m seams_gen.stubs <model.trig>` writes a stub for each `comm:PythonHandler`
whose module is missing from the model's `handlers/` package, and never overwrites a file
there: hand-written handlers are owned code
([ADR-0012](docs/adr/0012-operation-implementation.md)). Each stub is typed from its
operation's shapes, names the task, decision and transition behind it, and has a
`.trace.json` sidecar linking its lines to the model.

## v1: the viewer

Read-only, navigable, notation-switching browser over a hand-authored model. Stack:

- **Fuseki** — model store; one named graph per `seam:Model`
- **FastAPI** — three endpoints: describe node (JSON-LD, triples + seam edges), fetch render payload, SPARQL passthrough (HTTP QUERY, RFC 10008)
- **htmx shell** — every click is `hx-get /view/{iri}`; server dispatches on `seam:notation`
- **Layer mode** — `GET /layers` stacks the six layers as oblique planes, draws the cross-layer seams between them and traces an element's seams on hover
- **Renderers** — bpmn-js `NavigatedViewer` and dmn-js (read-only) for process/decision layers; a shared node-link renderer (elkjs layout, SVG cards) for architecture, shape graphs and ontology class views; IFML notation on diagram-js (server-computed layout, ELK ports for events); vis-network for statecharts

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

The vendored [gist](https://github.com/semanticarts/gist) ontology in
[`ontology/vendor/`](ontology/vendor/README.md) is © Semantic Arts under CC BY 4.0.
