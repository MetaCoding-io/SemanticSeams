# Backlog: viewer and generation

*Living document. Triaged 2026-10-19 from the three research notes of
2026-10-15 ([EventCatalog Levels](research/2026-10-15-eventcatalog-levels.md),
[reveal modes](research/2026-10-15-reveal-modes.md),
[IFML notation](research/2026-10-15-ifml-notation.md)) and the product brief's
milestones (M1 descent, M2 trust, M3 payoff). Twenty steps across the notes
collapse to twelve items once duplicates are merged.*

## How this was triaged

Three questions per item: does it move the tutorial persona closer to
`docker compose up` or to understanding the model on the way there; can it
ship on its own; and what does it force the vocabulary to decide. Priority
is P0 (do next), P1 (do after P0 lands), P2 (parked, with the reason).
Size is S (a day or two), M (a week), L (more, or needs a decision first).

The guiding call: **the UI work is bounded so it does not eat M3.** The brief
says the persona's payoff is generation, not browsing. The P0 set below is the
smallest set that makes the descent legible and gives every later renderer
one visual language; everything that is a second renderer, a second mode, or
editing waits.

## P0: one visual language, legible descent

| # | Item | Merges | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|---|
| 1 | **Node card with seam dots and colour-by-layer tokens** in the existing templates. Type pill, label, description, one dot per outgoing seam coloured by target layer. | Levels 3, 8 · Reveal 1 | S | none | none; `rdfs:label`, `rdfs:comment`, `arch:technology`, `deploy:version` already exist | done (M006/S01) |
| 2 | **C4 renderer on ELK with nested containment.** Replace vis-network; containment as nesting; deterministic positions; levels L1–L3 as class filters; rolled-up L1 edges from a canned query with an acceptance test. | Levels 1, 2, 7 · Reveal 2 | M | 1 | a viewer-side level config, not a seam predicate (design rule 2) | done (M006/S02) |
| 3 | **IFML rendered as IFML, server-side SVG.** Containers as boxes, components with stereotypes and «DataBinding», events as border circles, flows, binding groups; Action hexagons from `seam:triggers`, fields from the written shape, activation notes from `seam:visibleWhen`; seam dots on all of them. | IFML 2, 3 | M | 1 | none to add; derivations only. Decide whether fields come only from SHACL (recommended) | done (M006/S05) |
| 4 | **Level and lens state in the URL**, remembered per notation; level cards written as questions beside the Questions catalog, greyed out when empty. | Levels 5, 6 | S | 2 | none | done (M006/S03) |
| 5 | **Legend with live counts and click-to-hide**, with edge contraction through hidden types. | Levels 4 | S | 2 | none | done (M006/S04) |
| 6 | **Inspector as a right-hand panel.** Also fixes the wheel-over-canvas scroll trap. | walkthrough finding | S | 1 | none | done (M006/S01) |

Ship order: 1, 6, 2, 4, 5, 3. Items 1 and 6 are template-only and can land in
one PR. Item 3 can start in parallel with 2 because it does not share the
layout engine.

*All six shipped in M006 (One Visual Language), completed 2026-10-28. Item 2's
renderer choice is recorded in [ADR-0008](adr/0008-node-link-renderer.md).*

## P1: the differentiators, once the base is consistent

| # | Item | Merges | Size | Depends on | Why not P0 | Status |
|---|---|---|---|---|---|---|
| 7 | **Per-predicate reveal setting** (`open` / `nest` / `layer`) replacing the boolean `seam:navigational`; Relations panel; nest for `presents` and `executes` gives L4. | Reveal 3 · Levels 1 (L4) · open question 1 | M | 2, 3 | Changes an ADR-0005 annotation. Nest needs ELK compound layout, so it waits for 2 | done (M007/S02) |
| 8 | **Tint bpmn-js and dmn-js and add overlay badges**, so process and decision views join the language and show their seams. | Reveal 5 | S | 1 | Cheap, but only reads as consistent once 1 and 2 define the language | done (M007/S01) |
| 9 | **ShapeGraph renderer** using the same card; the data layer has no view at all today. | Reveal 6 | M | 1, 2 | Needed for the descent to bottom out somewhere other than an inspector; after 2 because it reuses the ELK renderer | done (M007/S03) |
| 10 | **IFML on diagram-js with ELK ports for events**, geometry carried over from 3. | IFML 4 | M | 3 | Only worth it once pan, zoom and overlays are needed on the IFML view, and as the base for editing | done (M007/S04) |

## P2: parked, with the reason

Scheduled as M008, after M016. Each slice first checks whether its reason for
being parked still holds, and may end by parking the item again here with an
updated reason.

| # | Item | Merges | Reason | Status |
|---|---|---|---|---|
| 11 | **Layer mode** (stacked planes, hover tracing). | Reveal 4 | Legible only as an overview; the mock proved the idea, the product needs 2 and 7 first. Revisit when there is a second worked example large enough to need it. That example now exists: the expense-approval build-along tutorial's final checkpoint (E1, done in M009/S07) passes the complexity check (E3), and the slice opens by running that check; see the [build-along note](research/2026-10-29-build-along-tutorial.md) | planned (M008/S03) |
| 12 | **IFMLEdit JSON exporter** as a conformance check. | IFML 5 | Valuable but orthogonal to the persona; do it when the vocabulary's correspondence claims are challenged, or as a weekend item | planned (M008/S01) |
| 13 | **Editing** (diagram-js modeling module, embed modelers read-write). | IFML 6 · project outline roadmap | Explicit v1 non-goal in the product brief | planned (M008/S04) |
| 14 | **Levels for IFML** (container › component › event). | Levels open question 2 | Generalise from C4 only when the IFML view needs it; proper notation (3) removes most of the need | planned (M008/S02) |

Resolved open questions from the Levels note: L4 is a preset of reveal
choices, not a separate level (item 7, delivered in M007/S02: L4 applies nest
mode to `presents` and `executes`); rollup queries live in
`docs/queries/` with acceptance tests (item 2).

## Examples and tutorials

*Added 2026-10-29 from the [build-along tutorial note](research/2026-10-29-build-along-tutorial.md).
Scheduled as M009, after M007 and before M008.* The chat app cannot make layer mode (item 11) necessary: it has exactly
one model per notation, so the descent already shows everything. A second tutorial in
which the reader builds an expense approval app from an empty file, one layer per
chapter, would both give the docs a build-it-yourself track and produce the second
worked example item 11 waits for.

| # | Item | Size | Depends on | Status |
|---|---|---|---|---|
| E1 | **Build-along tutorial: an expense approval app**, eight chapters from an empty file to `docker compose up`, with a checkpoint model per chapter validated in CI. Its final model is the second worked example. | L | E2, E4, E5 | done (M009/S03 done: chapters 1 to 3; E4 done in M009/S04; M009/S05 done: chapters 4 to 6, the process, the rules and the lifecycle; M009/S06 done: chapter 7, roles and the fourth canned query; M009/S07 done: chapter 8, the channel-started payout process, the finance console and `docker compose up`) |
| E2 | **Configurable model path** across the runtime, `compose.yaml`, `docker/runtime.Dockerfile` and the viewer, which all name `examples/chat-app/` today. Useful on its own. | S | none | done (M009/S01) |
| E3 | **Complexity check**: three SPARQL queries (models per notation, elements reached from the most models, seam-edge count) with thresholds, so item 11's first step is a measurement. The chat app scores 0 notations with 2+ models and a maximum reach of 3. | S | none | done (M009/S02) |
| E4 | **Human tasks**: an ADR on how a BPMN user task points at the screen where it is done, then runtime support for listing and completing user tasks. The worker used to skip manual tasks; it now waits on them. | M | ADR first | done (M009/S04) |
| E5 | **Role policy evaluator** behind the existing `PolicyEvaluator` protocol, for the tutorial's employee, manager and finance roles, plus the outline's compliance question as a fourth canned query. | S | none | done (M009/S06) |

## Library: a read-only Python model library

*Added 2026-10-29 from the [library note](research/2026-10-29-seams-python-library.md).
Scheduled as M010.* The generation work produced a real fact layer, `ModelGraph` in
`seams_runtime/model.py`, but it is bundled with the runtime's dependencies, has no
public surface, keeps one-of-each accessors that M009's multi-model expense example had to
work around, and reads the native BPMN and DMN only for their IDs. The viewer and the docs generator read the graph with their own code,
and IFML is interpreted twice. A small read-only library, `seams`, would give every
consumer and every user-written generator one typed, multi-model view of the graph
joined with the native files. It is built as a **uv workspace** with a committed
lockfile, `pyproject.toml` packaging, ruff and a type checker.

| # | Item | Size | Depends on | Status |
|---|---|---|---|---|
| L1 | **uv workspace and modern tooling**: a `pyproject.toml` per package, a committed `uv.lock`, `.python-version`, ruff; CI, the docs workflow and the Dockerfiles install with uv; the four requirements files removed. No code changes. | S | none | done (M010/S01) |
| L2 | **Extract the core into `seams`**: the loader (file or directory, honouring `SEAMS_MODEL` as E2 made the runtime and viewer do), hash, payload resolution, namespaces and errors, depending only on rdflib and lxml. The runtime re-exports `ModelGraph` on top of it; the generators import only the public API. | M | L1 | done (M010/S02) |
| L3 | **Typed views over the graph** per layer, with collections and `.only()` instead of one-of-each accessors, replacing the per-caller workarounds M009 added for multiple models. | M | L2 | done (M010/S03) |
| L4 | **Native joins**: BPMN walked in flow order, including unlifted elements; DMN tables with inputs, outputs and rules. | M | L3 | done (M010/S04) |
| L5 | **Port the consumers**: the generators, then the viewer (one IFML interpretation), then the docs reference generator, with golden outputs unchanged. | M | L3, L4 | done (M010/S05: generators and the runtime's ModelGraph read through seams views, goldens byte-identical; M010/S06: viewer loads with seams.load, viewer/ifml.py reads model.interfaces so IFML has one interpretation, docs generator uses seams) |
| L6 | **Docs**: an API reference page and a "Write your own generator" guide. | S | L3 | done (M010/S07: docs/reference/seams-library.md, docs/guide/write-your-own-generator.md, guide generator executed by tests/test_generator_guide.py on chat-app and expenses chapter-08) |

## Derived views and model gaps

*Added 2026-10-29 from the [UML coverage note](research/2026-10-29-uml-coverage-and-gaps.md).
Scheduled across M011 (U2, U9), M013 (U1, U3, U4), M014 (U6, U7) and M015 (U5, U8).* The note finds that no UML notation needs authoring:
each UML diagram is covered by a pillar or derivable from existing seams. The sequence
diagram is the one worth building, as a derived view. The other items close gaps that the
derivation exposed, or that a builder meets after launch.

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| U1 | **Derived sequence diagram, as designed**: a function from an IFML event to Mermaid, reading the graph and the BPMN XML for step order. Golden test on the chat app's send-message flow | S | none (U2 and U3 make its output complete) | none; control flow stays in the XML | landed (M013/S02): `seams sequence <event>` and `python -m seams_gen.sequence`, one diagram per gateway path with `%% gap:` lines; goldens in `docs/generation/sequences/` |
| U2 | **Shape-to-store seam**, so the storage lifeline and data-loss impact are derivable; extend `impact-of-node.rq` to reach shapes | S | none | one seam predicate, earned by "which data is lost if this node goes away" | vocabulary and impact query landed (M011/S02): `seam:storedIn` and the `deploy:` store facts, and `impact-of-node.rq` reaches stored shapes; the runtime reads them since S03. Predicate fixed by [ADR-0011](adr/0011-storage-resolution.md) |
| U3 | **Declare the LLM delta stream** in the chat app, so the runtime infers no publish the graph does not state | S | none | none; `seam:publishesTo` subject widened to `proc:ServiceTask` (D046) | landed (M013/S01): `invoke_llm seam:publishesTo :stream_events`, and the runtime publishes only declared channels; `process_channel` removed |
| U4 | **As-executed sequence diagram** from the worker's trace rows, then OpenTelemetry spans carrying element IRIs | M | U1 | none for the diagram; an as-observed named graph later | planned (M013/S04) |
| U5 | **Scenarios and derived tests**: a small scenario vocabulary, generated DMN, SHACL-example and policy tests, and coverage queries | M | none | a scenario/verification annotation vocabulary | planned (M015/S03, S04) |
| U6 | **Operation implementation seam** for hand-written code and external endpoints, so service tasks other than LLM calls have a declared home | M | ADR first | one seam predicate plus a convention for where hand-written code lives | planned (M014/S01 to S03); M009 shipped without a non-LLM service task, so M014/S03 adds one to the expense example |
| U7 | **Error shapes and boundary events**: error shapes on operations, lifted BPMN error boundary events, runtime support | M | none | `comm:`/`proc:` additions | planned (M014/S04) |
| U8 | **Shape diff**: classify changes between model versions as compatible or breaking, for stored data and for operation contracts | M | none | none; a query and tooling over two named graphs | planned (M015/S01) |

| U9 | **The runtime stores data where the model says**: storage backends behind one interface (embedded SQLite, PostgreSQL), chosen at load from graph facts, with model-health checks for unresolved or unused stores. Fixes the chat app writing to SQLite while its model declares a Postgres message store. [Plan](research/2026-10-29-runtime-storage.md) | M | ADR first, U2 | `seam:storedIn`, `deploy:storeKind` (controlled `deploy:StoreKind` values) and `deploy:connectsTo` | done (M011): [ADR-0011](adr/0011-storage-resolution.md) accepted (S01); vocabulary, SHACL, the chat-app and expenses chapter-08 store facts, the `storedIn` hop in `impact-of-node.rq` and the viewer's `storedIn` edge done (S02); runtime backends done (S03): `Runtime.load` opens SQLite or PostgreSQL from the facts, `/healthz` reports the store, the compose stacks run on their declared PostgreSQL and CI runs the store tests against a PostgreSQL service; model-health checks and end-to-end store assertions done (S04): `ModelGraph.store_health()` feeds the viewer's health panel, which fails on a written shape with no supported store, warns on a store no shape is stored in and notes the embedded-SQLite default, and the tutorial and expenses end-to-end tests assert the written row lands in the declared PostgreSQL and that `/healthz` reports it; agreed 2026-10-29 to fix the runtime and keep ADR-0007 |

U1 to U3 can land together. U9 subsumes U2's vocabulary work, so the two are best done
as one piece.

## Artifact management and deployment

*Added 2026-10-29 from the [artifact management note](research/2026-10-29-artifact-management.md).
Scheduled across M012 (A1, A2, A3, A6), M015 (A7, A9) and M016 (A4, A5, A8).* The generators exist; the workflow around them does
not. These items extend the model-hash chain that is already in place (stamped outputs, a
runtime that refuses a different model, `/healthz` reporting the hash) into a record of
what was generated, checks a user can reuse, and a deployment that can be compared with
the model.

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| A1 | **Project file and `seams` CLI**: one file names the model, generators, output paths and environments; `seams generate` runs them all, `seams check` validates the model and confirms outputs are current | M | E2 | none | done (M012/S01: seams.toml and `seams generate`; M012/S03: `seams check` validates the shapes, runs the project's gates and fails on stale, missing, hand-edited or orphaned outputs or an out-of-date lock, writing nothing) |
| A2 | **Lockfile of generated files**: model hash, generator and version, file hash and source elements per output; orphan cleanup and hand-edit detection | S | A1 | none; generators and runtime gain versions | done (M012/S02): `seams generate` writes a deterministic `seams.lock` per project recording each output's generator, version, model hash, sha256 and source IRIs; it deletes unchanged orphans, reports hand-edited and deleted outputs, and every example commits its lock. `seams_gen` and `seams_runtime` carry `__version__`, and `/healthz` reports `runtime_version` |
| A3 | **Reusable CI action and pre-commit hook**: shape validation, regenerate-and-diff, canned queries as gates | S | A1 | none | done (M012/S03): the composite action `.github/actions/seams-check` runs `seams check` per project and replaces CI's regenerate-and-diff step; `.pre-commit-hooks.yaml` defines the `seams-check` hook; `docs/queries/gates/ungoverned-writes.rq` is the first gate |
| A4 | **Environments from the model**: development and production as `arch:Environment`s, one compose file per environment, so `compose.override.yaml` stops being hand-written | M | ADR first, U9 | environment-specific `deploy:` facts | planned (M016/S01, S02) |
| A5 | **Image build and publish** for containers that run generated code, tagged with the model hash or a release version | M | A4 | none expected | planned (M016/S03) |
| A6 | **`seams status`**: read each container's `/healthz` and compare its model hash with the current model | S | A1 | none | done (M012/S04): `seams status [--env]` reads each runtime container's `/healthz` from the endpoints in `seams.toml` and reports it current, behind, ahead or unreachable against the current model, ordering past hashes by the `seams.lock` git history; the chat app and expense chapter 8 declare a `local` environment |
| A7 | **Change plans and release notes** from model diffs, for review, changelogs and pre-deploy plans | M | U8 | none | planned (M015/S02) |
| A8 | **Secrets and configuration checklist** per environment, checking existence without reading values, plus an example `.env` | S | A4 | none | planned (M016/S04) |
| A9 | **Generated smoke tests**: every operation answers on its path and its response validates against `seam:returnsShape` | S | none | none | planned (M015/S05) |

A1 to A3 belong together and make the generators usable outside this repository. A4 to
A6 make deployment work end to end.

## Not yet scheduled

*Added 2026-10-29 while planning M010 to M016.* Two gaps the research notes name but no
milestone covers.

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| A10 | **More than one replica**: the chat-app model declares `deploy:replicas 3`, but only one replica works, because process instances and the live-update stream are held in memory. Needs the shared store from U9 and a shared channel for the stream. Until then, M016 caps generated replicas at one. See "Not covered" in the [storage plan](research/2026-10-29-runtime-storage.md) | M | U9, A4 | none expected | proposed |
| U10 | **Scheduled and background work**: lift BPMN timer start events and run recurring jobs (reminders, cleanups, digests), with a seam to the container that runs the schedule. See section 3.6 of the [UML coverage note](research/2026-10-29-uml-coverage-and-gaps.md) | M | ADR first | a seam to the scheduling container | proposed |

## Generation: what is planned, what is not

**Planned already.** The product brief puts generation on the critical path
and defines milestone M3 as three generators for the chat-app tutorial:
htmx templates from the interaction model, a FastAPI scaffold whose handlers
validate against the declared shapes and dispatch through the generic
graph-literate worker, and a docker-compose file from `deploy:`. The brief
scopes them to what the tutorial needs, with the process flow hard-wired and
BPMN interpretation deferred past v1. The outline separately decided the
execution boundary (the engine never learns about seams; one worker resolves
`seam:invokes` and enforces `seam:governedBy`) and left "interpret or
generate" open.

**Not planned.** The hybrid is a decision, not a plan: interpret where a real
engine exists (BPMN and DMN through SpiffWorkflow, SHACL validation through
pySHACL at request time), generate only where none exists (templates, route
scaffold, compose). It changes M3 in one place: the process is run by an
engine from the start instead of being hard-wired, which is the smaller
amount of work and keeps the generated scaffold free of workflow logic. It
also makes the worker from the execution-boundary decision a v1 deliverable
rather than a stub.

**What to do about it.** Two items, neither large:

| # | Item | Size | Output |
|---|---|---|---|
| G1 | **ADR-0007, execution strategy.** Record the hybrid: interpret BPMN/DMN with SpiffWorkflow, validate with pySHACL, generate templates, routes and compose. Amend M3 accordingly. | S | Accepted after the M004/S01 spike: [ADR-0007](adr/0007-execution-strategy.md). Its Spike Findings resolve all four open items: parser-hook decision binding, streaming, SQLite state and licence. |
| G2 | **Golden-output dry run.** Hand-write the three target artifacts for the chat app (the htmx page, the FastAPI module, the compose file), then walk the model and mark every line the graph can and cannot produce. The cannot list becomes the vocabulary additions (operation paths, event-to-operation binding, form fields or their SHACL derivation, SSE and channel transport, artifacts for the other three containers, ports) and the generators get a test to pass before they exist. | M | [`docs/generation/golden/`](generation/golden/) plus a [gap table](generation/golden/gaps.md) (done: 22 gaps, plus 5 from the ADR-0007 spike; all closed in M004/S02) |

G2 is a documentation exercise that can run in parallel with P0 and should,
because its gap list will change the vocabulary before the renderers harden
around it. The generators themselves come after G2 and are M3.

## Suggested sequence

*Revised 2026-10-28: the generators now come straight after P0, ahead of P1.
The earlier order put P1 first, which contradicted the guiding call above that
UI work must not eat M3.*

1. P0 items 1 and 6 (one PR). *Done, M006/S01.*
2. P0 item 2 and G2 in parallel. *Done, M006/S02 and S06.*
3. P0 items 4, 5, 3. *Done, M006/S03, S04, S05.*
4. M3 (tracked as M004, The Payoff), opening with the ADR-0007 spike (its open items).
   *Spike done, M004/S01: it held, and ADR-0007 is Accepted.* *Vocabulary additions
   done, M004/S02: every row of G2's gap list and the spike's findings (GAP-01..GAP-27)
   is closed.* *Runtime worker done, M004/S03: [`seams_runtime`](../seams_runtime/README.md)
   runs the send-message process end to end from graph facts.* *Generators done,
   M004/S04, S05, S06: htmx templates, the FastAPI route module and the compose
   file, each passing the golden outputs.* *Tutorial done, M004/S07:
   [`docs/tutorial.md`](tutorial.md) runs end to end in CI.*
5. P1 items 8, 7, 9, 10 as M007, The Differentiators (S01 to S04, in that order). *Item 8 done, M007/S01.* *Item 7 done, M007/S02.* *Item 9 done, M007/S03.* *Item 10 done, M007/S04: P1 items 7 to 10 are all done (M007).*
6. The build-along tutorial, E2, E3, E4, E5 and E1, as M009 (S01 to S07), after
   M007. Its final model is the second worked example that item 11 waits for.
   *E2 done, M009/S01: `SEAMS_MODEL` chooses the model for the runtime, the compose
   stack and the viewer.* *E3 done, M009/S02: `python -m seams_gen.complexity` measures
   models per notation, maximum reach and seam edges against thresholds.* *E1 chapters
   1 to 3 done, M009/S03: the [expense tutorial](tutorials/expenses/index.md) goes from an
   empty file to a generated form that rejects invalid input, and CI checks every chapter's
   checkpoint in `examples/expenses/`.* *E4 done, M009/S04: [ADR-0009](adr/0009-human-tasks.md)
   points a user task at its form with `seam:completedOn`, the runtime lists and completes
   user tasks under their policies, the generators emit the completion form and route, and
   the host serves a `/tasks` inbox.* *E1 chapters 4 to 6 done, M009/S05: the
   [expense tutorial](tutorials/expenses/index.md) adds the approval process with a manager
   task, DMN routing by amount and the expense lifecycle, with checkpoints in
   `examples/expenses/chapter-04` to `chapter-06`.* *E5 and E1 chapter 7 done, M009/S06:
   the runtime's `RoleEvaluator` admits identities by their `X-Forwarded-Groups` roles (or
   `SEAMS_DEV_ROLES`), the viewer's fourth canned query names the screens each role can use
   that eventually write a shape, and [chapter 7](tutorials/expenses/07-permissions.md) adds
   the employee, manager and finance policies and a payment task.* *E1 done, M009/S07:
   [chapter 8](tutorials/expenses/08-growing-up.md) adds a payout process that
   [ADR-0010](adr/0010-channel-started-processes.md) starts from a channel, with its own
   decision and payment lifecycle, a finance console and a `docker compose up` run in CI.
   Its checkpoint passes `python -m seams_gen.complexity` (4 notations with two models,
   a maximum reach of 6), so it is the second worked example item 11 waits for.*
7. P2 items 12, 14, 11, 13 as M008, Beyond v1 (S01 to S04), after M016 (moved behind
   M010 to M016 on 2026-10-29). Each
   item's parking reason is checked again first: editing is a v1 non-goal in the
   product brief. *Next:* layer mode (S03) opens by running the E3 complexity
   measurement on the finished expense app,
   `python -m seams_gen.complexity examples/expenses/chapter-08/expenses.trig`.
8. The library, model-gap and artifact items as M010 to M016, planned 2026-10-29. Each
   milestone depends on the ones it builds on, and every slice is a sketch that is refined
   when it starts.
   - **M010, Modern Tooling and the seams Library** (L1 to L6): uv workspace, the
     read-only `seams` library, typed views, native BPMN and DMN joins, and every consumer
     ported with golden outputs unchanged. *L1 done, M010/S01: the repository is a uv
     workspace with a committed `uv.lock`; CI, the docs workflow and both Dockerfiles
     install with `uv sync --locked`, ruff and pyright run in CI, and the four
     requirements files are gone. L2 done, M010/S02: `seams` holds the loader (file or
     directory, honouring `SEAMS_MODEL`), the hash, payload resolution, namespaces, errors
     and the transitional `ModelGraph`; `seams_runtime` re-exports them, and `seams_gen` no
     longer imports the runtime. L3 done, M010/S03: typed, read-only views per layer
     (`model.architecture`, `interfaces`, `processes`, `decisions`, `shapes`,
     `operations`, `channels`, `lifecycles`, `policies`) with `.only()`, plus
     `model.sparql` and `model.question`; the engine's task IRIs and the served pages
     come from the views, so several BPMN models need no workaround. L4 done, M010/S04:
     `seams.bpmn` and `seams.dmn` read the payload XML with lxml; `Process.nodes()`,
     `tasks()`, `gateways()` and `lanes()` walk each BPMN file in flow order, including
     unlifted events and gateways with their paths, joined to the graph elements (user tasks
     carry their `completedOn` form, message start events their channel), and
     `Decision.table` gives hit policy, inputs, outputs and rules. M010/S05: the htmx,
     routes and compose generators, `seams_gen.fragments` and the runtime's `ModelGraph`
     read the model only through seams views (D036); `seams_gen/facts.py` is gone,
     `extract_page` is built on `model.interfaces`, and every committed generated output
     for chat-app and the expenses chapters 3 to 8 is byte-identical. M010/S06: the viewer
     loads its model with `seams.load` (a TriG file or a directory), `viewer/ifml.py`
     derives the IFML diagram from `model.interfaces`, the view the htmx generator reads,
     so IFML has one interpretation, and `docs/scripts/generate.py` reads namespaces and
     the question catalog through seams; L5 is done. M010/S07: the seams API reference
     moved onto the docs site (docs/reference/seams-library.md) and a "Write your own
     generator" guide whose generator CI runs on chat-app and expenses chapter-08; L6 is
     done, and M010 is complete pending validation.*
   - **M011, Data Where the Model Says** (U2, U9): an ADR on storage resolution (ADR-0011 accepted), the
     shape-to-store seam, SQLite and PostgreSQL backends chosen from the graph, and
     model-health checks. Depends on M010. *S01 done: ADR-0011 accepted. S02 done:
     `seam:storedIn`, `deploy:StoreKind` and `deploy:storeKind` in the ontology and
     SHACL, the chat app and expenses chapter 8 declare their stores, and
     `impact-of-node.rq` reaches the stored shapes. S03 done: `Runtime.load` opens the
     declared store (SQLite or PostgreSQL) and `/healthz` reports it; S04 done: the
     viewer's model-health panel checks storage and both end-to-end suites assert the
     written row lands in the declared PostgreSQL. M011 landed.*
   - **M012, Generate and Check Anywhere** (A1, A2, A3, A6): project file, `seams generate`
     and `seams check`, the generated-file lockfile, a reusable CI action and pre-commit
     hook, and `seams status`. Depends on M010. *A1 generate done, M012/S01: the chat app
     and every expenses chapter have a seams.toml, `seams generate`
     rewrites their committed outputs byte-for-byte, and CI, the tutorials and the
     generated READMEs regenerate through it. A2 done, M012/S02: every project commits a
     `seams.lock`; `seams generate` deletes unchanged orphans and reports hand edits. A1
     check and A3 done, M012/S03: `seams check` validates shapes, runs gate queries and
     checks output freshness; CI runs it for every example through
     `.github/actions/seams-check`, and `.pre-commit-hooks.yaml` defines the hook. A6 done,
     M012/S04: `seams status` compares each running runtime container's `/healthz` model
     hash with the current model, using the `seams.lock` history for behind and ahead.
     M012 landed.*
   - **M013, Derived Sequence Diagrams** (U3, U1, U4): the declared delta stream, the
     as-designed deriver, viewer and docs embedding, and the as-executed sequence with
     OpenTelemetry spans. Depends on M010 and M011.
   - **M014, Hand-Written Code and Failure Paths** (U6, U7): an ADR and runtime dispatch for
     operation implementations, a hand-written service task in the expense example, error
     shapes and error boundary events. Depends on M010 and M012, because hand-written code
     has to survive `seams generate`.
   - **M015, Change Safety and Verification** (U8, A7, U5, A9): shape and contract diff,
     change plans, scenarios with derived tests and coverage queries, and generated smoke
     tests. Depends on M010 and M012.
   - **M016, Deploy from the Model** (A4, A5, A8): an ADR on environments, one compose file
     per environment, image build and publish, and a secrets checklist. Depends on M011 and
     M012.

   The `seams` command (`generate`, `check`, `status` and the later subcommands) lives in its
   own workspace package, so the library keeps only rdflib and lxml as dependencies (D030).
   M008 runs after M016 (D032).
