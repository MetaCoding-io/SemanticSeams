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
| 11 | **Layer mode** (stacked planes, hover tracing). | Reveal 4 | Legible only as an overview; the mock proved the idea, the product needs 2 and 7 first. Revisit when there is a second worked example large enough to need it. That example now exists: the expense-approval build-along tutorial's final checkpoint (E1, done in M009/S07) passes the complexity check (E3), and the slice opens by running that check; see the [build-along note](research/2026-10-29-build-along-tutorial.md). The check passed (4 notations with 2+ models, a maximum reach of 6, 115 seam edges), so the reason was cleared and `GET /layers` was built; see [the viewer guide](guide/the-viewer#layer-mode) | done (M008/S03) |
| 12 | **IFMLEdit JSON exporter** as a conformance check. | IFML 5 | Valuable but orthogonal to the persona; do it when the vocabulary's correspondence claims are challenged, or as a weekend item. `python -m seams_gen ifmledit` writes `ifmledit.json` from `model.interfaces`; the `ifml:` terms with no IFMLEdit counterpart are GAP-29 to GAP-35 in [gaps.md](generation/golden/gaps.md) | done (M008/S01) |
| 13 | **Editing** (diagram-js modeling module, embed modelers read-write). | IFML 6 · project outline roadmap | Unparked 2026-10-31: editing is in scope from the outset, replacing the product brief's v1 non-goal ([principle 10](project/principles.md#_10-the-model-is-editable-through-one-write-path)). I1 to I5 are the plan ([note](research/2026-10-30-domain-ide-and-generator-kit.md)); planned as M019, which replaces M008/S04 | done: superseded by I1 to I6, landed as M019 |
| 14 | **Levels for IFML** (container › component › event). | Levels open question 2 | Generalise from C4 only when the IFML view needs it; proper notation (3) removes most of the need. Checked again in M008/S02 (D055): the IFML view now draws real notation on diagram-js with pan and zoom (3, 10), and the largest example IFML model (`examples/expenses/chapter-09/expenses.trig`) has 3 containers and 4 events, so container, component and event levels would draw nearly the same picture. Revisit when a model is too big to read at one zoom (roughly 10+ containers or 30+ events), or when editing (M019) needs a coarser view | re-parked (M008/S02) |

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
| E1 | **Build-along tutorial: an expense approval app**, eight chapters from an empty file to `docker compose up`, with a checkpoint model per chapter validated in CI. Its final model is the second worked example. | L | E2, E4, E5 | done (M009/S03 done: chapters 1 to 3; E4 done in M009/S04; M009/S05 done: chapters 4 to 6, the process, the rules and the lifecycle; M009/S06 done: chapter 7, roles and the fourth canned query; M009/S07 done: chapter 8, the channel-started payout process, the finance console and `docker compose up`; M014/S03 added chapter 9, a hand-written service task) |
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
| U1 | **Derived sequence diagram, as designed**: a function from an IFML event to Mermaid, reading the graph and the BPMN XML for step order. Golden test on the chat app's send-message flow | S | none (U2 and U3 make its output complete) | none; control flow stays in the XML | landed (M013/S02): `seams sequence <event>` and `python -m seams_gen.sequence`, one diagram per gateway path with `%% gap:` lines; goldens in `docs/generation/sequences/`; viewer `/sequence/{event}` and docs embedding (M013/S03) |
| U2 | **Shape-to-store seam**, so the storage lifeline and data-loss impact are derivable; extend `impact-of-node.rq` to reach shapes | S | none | one seam predicate, earned by "which data is lost if this node goes away" | vocabulary and impact query landed (M011/S02): `seam:storedIn` and the `deploy:` store facts, and `impact-of-node.rq` reaches stored shapes; the runtime reads them since S03. Predicate fixed by [ADR-0011](adr/0011-storage-resolution.md) |
| U3 | **Declare the LLM delta stream** in the chat app, so the runtime infers no publish the graph does not state | S | none | none; `seam:publishesTo` subject widened to `proc:ServiceTask` (D046) | landed (M013/S01): `invoke_llm seam:publishesTo :stream_events`, and the runtime publishes only declared channels; `process_channel` removed |
| U4 | **As-executed sequence diagram** from the worker's trace rows, then OpenTelemetry spans carrying element IRIs | M | U1 | none for the diagram; an as-observed named graph later | landed (M013/S04): `seams sequence <event> --trace RUN` renders a recorded run from the worker's trace rows as `<event>.executed.mmd`, on the same lifelines as U1, with `%% gap:` lines for unmapped rows; the runtime emits optional OpenTelemetry spans with element IRIs (`seams_runtime` `otel` extra, on only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set). Later work: the as-observed named graph, with spans or trace rows loaded back as RDF so runs can be queried next to the model |
| U5 | **Scenarios and derived tests**: a small scenario vocabulary, generated DMN, SHACL-example and policy tests, and coverage queries | M | none | the `verify:` scenario and example vocabulary ([ADR-0014](adr/0014-scenarios-and-derived-tests.md)); policy tests add no terms | done (M015/S03): chapter 9 declares scenarios, DMN decision examples and SHACL examples; the `tests` generator turns them, and every ODRL permission per role, into pytest files in `generated/tests`, tracked in seams.lock and run in CI. Done (M015/S04): coverage lists the BPMN paths no scenario runs, the transitions nothing fires and the permissions without a deny test, through `seams.coverage`, `seams coverage`, optional `seams check` gates and three viewer Questions. Done (M026/S01): chapter 9 adds the `:manager_rejected` and `:finance_rejected` scenarios. Done (M026, ADR-0014 amended 2026-11-05, `verify` 1.1): `verify:failure` makes an operation fail with one of its declared errors, and a scenario's run takes in the processes it starts through a channel. Chapter 9's `:notify_failed_approved`, `:notify_failed_rejected`, `:paid_in_batch` and `:paid_now` run the last four paths, and its `seams.toml` sets `coverage = ["paths"]`. |
| U6 | **Operation implementation seam** for hand-written code and external endpoints, so service tasks other than LLM calls have a declared home | M | ADR first | one seam predicate plus a convention for where hand-written code lives | ADR accepted ([ADR-0012](adr/0012-operation-implementation.md), M014/S01); runtime dispatch done (M014/S02): the worker dispatches on `seam:implementedBy` (LLM completion, Python handler, HTTP endpoint), the chat app declares its LLM call, and `python -m seams_gen.stubs` writes a handler stub once and never overwrites it; the expense example's hand-written service task done (M014/S03): [chapter 9](tutorials/expenses/09-hand-written-code.md) adds a Notify Manager task backed by an owned `comm:PythonHandler` in `examples/expenses/chapter-09/handlers/`, the compose generator mounts the handlers package, and CI's checkpoint and compose jobs run against chapter 9 |
| U7 | **Error shapes and boundary events**: error shapes on operations, lifted BPMN error boundary events, runtime support | M | none | `comm:errorCode` and the RFC 9457 members `comm:type`/`title`/`status`/`detail`/`instance`, `proc:ErrorBoundaryEvent`, `seam:catches`; reuses `hydra:possibleStatus`, `hydra:statusCode` and `seam:returnsShape` ([ADR-0013](adr/0013-error-shapes-and-boundaries.md)) | done (M014/S04): ADR-0013, the vocabulary and its SHACL (T01); generated FastAPI routes declare each error status as an `application/problem+json` response and one generated problem handler answers a raised `OperationError` with a body validated against the error shape (T02); the runtime checks each lifted `proc:ErrorBoundaryEvent` against the BPMN at load and routes a declared error a Python handler or HTTP endpoint raises down the boundary that catches it, recording the code, status and boundary in trace rows and spans (T03); [chapter 9](tutorials/expenses/09-hand-written-code.md#when-the-notification-fails) gives Notify Manager a boundary that sends the expense to finance when the message is too long to send, and the viewer draws it with its `seam:catches` badge (T04) |
| U8 | **Shape diff**: classify changes between model versions as compatible or breaking, for stored data and for operation contracts | M | none | none; a query and tooling over two named graphs | done (M015/S01) |

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
| A4 | **Environments from the model**: development and production as `arch:Environment`s, one compose file per environment, so `compose.override.yaml` stops being hand-written | M | ADR first, U9 | environment-specific `deploy:` facts: `deploy:Override`, `deploy:override`, `deploy:environment`, `deploy:build`, `deploy:secretFile`, `deploy:proxies` | done (M016/S02); [ADR-0015](adr/0015-environments.md) accepted (M016/S01): environment-scoped facts are `deploy:override` qualified relations, an override replaces the shared fact of the same predicate (bindings by `deploy:key`), generated replicas are capped at one until A10. S02 added the vocabulary and SHACL, and the compose generator writes `compose.development.yaml` and `compose.production.yaml` for the chat app and expense chapters 8 and 9; every `compose.override.yaml` and `compose.yaml` is gone, and the tutorial end-to-end runs run from the generated development file |
| A5 | **Image build and publish** for containers that run generated code, tagged with the model hash or a release version | M | A4 | none expected | done (M016/S03): the `dockerfile` generator writes `generated/<route module>.Dockerfile` for each project's serving container, with literal app paths and `io.semanticseams.model-hash` / `io.semanticseams.container` labels, and the development `deploy:dockerfile` names it; `docker/runtime.Dockerfile` and the compose build args are gone. The gated `.github/workflows/publish-images.yml` (manual dispatch with a `push` input defaulting to false, or a `v*` tag; never on main or pull requests) builds the chat app's and expenses chapter 9's images from `python -m seams_gen.images` and tags them with the production `deploy:reference`:`deploy:version` and `sha-<model hash>`. The production references name `ghcr.io/metacoding-io/...`; the hand-built gateway image joined the list with A13 |
| A6 | **`seams status`**: read each container's `/healthz` and compare its model hash with the current model | S | A1 | none | done (M012/S04): `seams status [--env]` reads each runtime container's `/healthz` from the endpoints in `seams.toml` and reports it current, behind, ahead or unreachable against the current model, ordering past hashes by the `seams.lock` git history; the chat app and expense chapter 8 declare a `local` environment |
| A7 | **Change plans and release notes** from model diffs, for review, changelogs and pre-deploy plans | M | U8 | none | done (M015/S02): `seams plan OLD NEW` writes a Markdown change plan (breaking and compatible changes, then elements added and removed per layer) between model paths or git `REF:PATH` specs; the `seams-plan` action posts it to the job summary on pull requests that change a model |
| A8 | **Secrets and configuration checklist** per environment, checking existence without reading values, plus an example `.env` | S | A4 | none | done (M016/S04): `seams secrets [--env NAME] [--write-example] [--json]` lists every binding of `Container.for_environment` per `arch:Environment` as `<env> <container> <key> <kind> <verdict> <source>`, never a value. A secret file is present when its path exists, a key named in the project's `.env` is present (only key names are read), and a secret name is looked up in `docker secret ls`; without docker the row is unchecked. Any missing row exits 1. `--write-example` writes a deterministic `.env.example`, committed for the chat app and expense chapter 8 |
| A9 | **Generated smoke tests**: every operation answers on its path and its response validates against `seam:returnsShape` | S | none | none | done (M015/S05): the `smoke` generator writes one pytest per `hydra:Operation` that calls it on its `comm:path` against `SEAMS_SMOKE_BASE_URL` and validates the answer against `seam:returnsShape`, skipping operations whose policy refuses the identity; CI's `tutorial-e2e` job runs chapter 9's against the compose stack |

A1 to A3 belong together and make the generators usable outside this repository. A4 to
A6 make deployment work end to end.

## Not yet scheduled

*Added 2026-10-29 while planning M010 to M016.* Gaps the research notes and the principles gates name but no
milestone covers yet.

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| A10 | **More than one replica**: the chat-app model declares `deploy:replicas 3`, but only one replica works, because process instances and the live-update stream are held in memory. Needs the shared store from U9 and a shared channel for the stream. Until then, M016 caps generated replicas at one. See "Not covered" in the [storage plan](research/2026-10-29-runtime-storage.md) | M | U9, A4 | none expected | proposed |
| U10 | **Scheduled and background work**: lift BPMN timer start events and run recurring jobs (reminders, cleanups, digests), with a seam to the container that runs the schedule. See section 3.6 of the [UML coverage note](research/2026-10-29-uml-coverage-and-gaps.md) | M | ADR first | a seam to the scheduling container | proposed |
| A11 | **The build names the generated Dockerfile**: nothing checks that the development `deploy:dockerfile` names the file the `dockerfile` generator writes (`<app dir>/generated/<route module>.Dockerfile`, relative to `deploy:context`). If the path goes stale, compose builds from another file and no error names the fact. A `GeneratorError` or `seams check` finding on `deploy:dockerfile`, with a shape where SHACL can state it. Found by the M016/S03 principles gate; fits M017 (Honest Checks) alongside K1 | S | A5 | none | done (M027/S01): `extract_dockerfile` in the `dockerfile` generator raises `GeneratorError` on the serving container and `deploy:dockerfile` when the development build's `deploy:dockerfile` is missing or does not name `<app dir>/generated/<route module>.Dockerfile` (compared as normalised POSIX paths), so `seams generate` fails and `seams check` reports it. No shape: the expected path depends on resolving `deploy:context` against the model file's location, so the check is generator-only and listed in the shape and generator parity test |
| A12 | **Workspace members in the generated Dockerfile come from the workspace**: `seams_gen/templates/runtime.Dockerfile.j2` lists each uv workspace member's `pyproject.toml` by hand, so adding or moving a member breaks the image build until the template is edited. Read the members from the root `pyproject.toml` in `extract_dockerfile` instead. Found by the M016/S03 principles gate | S | A5 | none | done (M027/S02): `extract_dockerfile` reads `[tool.uv.workspace].members` from the `pyproject.toml` at the root of the build context and each member's `pyproject.toml`, and the template renders one `COPY` per member (sorted by path) of its `pyproject.toml` and its `[project].readme`. The generated Dockerfiles now copy `seams_edit`, which the hand-written list had missed. A missing or unreadable root or member `pyproject.toml`, an empty member list or a glob member is a `GeneratorError` on the serving container and `deploy:context`. The generator names those files with the new `Generator.inputs` hook (ADR-0016 amendment), so the viewer's write-back and `seams suggest` copy them into their scratch copies |
| A13 | **Publish every image the model builds**: `seams_gen.images` lists only Dockerfiles the `dockerfile` generator writes, so the hand-written `llm-gateway` (built in development from `docker/gateway.Dockerfile`) is never published and its production artifact, `ghcr.io/example/llm-gateway:latest`, names an image nothing produces. List every container whose development override has a `deploy:build`, point the gateway's production artifact at `ghcr.io/metacoding-io/llm-gateway` with a pinned `deploy:version`, and add a revision note to ADR-0015. Found at M016 validation | S | A5 | none | done: `seams_gen.images` lists every container with a development `deploy:build`; the gateway publishes as `ghcr.io/metacoding-io/llm-gateway:0.3.1` |
| A14 | **`xsd:decimal` keys are `Decimal` in handler stubs**: `seams_gen.stubs.PYTHON_TYPES` maps `xsd:decimal` to `float`, so a stub's `TypedDict` types an exact amount (the expense tutorial's `:amount`) as a binary float. Map it to `decimal.Decimal`, import it in the stub only when a key uses it,, and make the runtime hand handlers a `Decimal` for such a field (check what it passes today), so the annotation is true at run time. Update the golden, the chapter-9 sample and the type table in the seams_gen README. Found by the M022/S02 principles gate | S | C1 | none | proposed |

*Added 2026-11-02 from the [domain-driven design note](research/2026-11-02-domain-driven-design.md).
DDD's tactical patterns are already in the graph under other names; these items add the
strategic layer it lacks, a derived event-storm view, and DDD as the second profile.*

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| B1 | **Domains and bounded contexts in `arch:`**: a domain that `arch:contains` systems, with a core, supporting or generic classification; a bounded context as the owner of an ontology and the named graphs that use it. Earns "core operations with no handler and no scenario" and the per-context questions below. [ADR-0022](adr/0022-ontology-notation.md) decided where the ontology lives (one per model, shared by import later) and left the context's ownership of a shared ontology to B1 | M | O1, K6; ADR first | a domain class with a classification, and a context boundary, in `arch:` | proposed |
| B2 | **Context map facts and queries**: one relationship type per pair of contexts (customer-supplier, conformist, anti-corruption layer, published language, shared kernel); U8's shape diff scoped per downstream context; a gate for cross-context calls with no translating operation | M | B1, U8 | a relationship fact between contexts; no seam predicate | proposed |
| B3 | **Lifecycle on the class, states as events**: `seam:lifecycle` targets the class once O2 lands, with a shape's lifecycle derived through `sh:targetClass`; a transition is a domain event with an IRI, publishable on a channel without a copied label | M | O1, O2 | widens `seam:lifecycle`'s subject | proposed |
| B4 | **Derived event-storm view**: `seams storm <process>`, a timeline per process from the graph (actor, command, aggregate, transitions, decisions, channels, started processes, read models), with a golden test on the expense tutorial, then a viewer section; the bounded context canvas as a second derived view | S | none for the storm; B1 for the canvas | none | proposed |
| B5 | **DDD profile**: a shapes library attached by `seam:conformsTo` (one correlation key, lifecycle and store per aggregate; no shape written from two contexts; cross-context calls translated unless declared conformist; bundles today's ungoverned-writes and unfired-transitions gates), as the second profile after IDesign; Context Mapper import and export | L | I5, B1, B2 | extends `seam:Profile` | proposed |

## From the research notes, triaged 2026-11-05

*Added after M026. Each row is a gap one of the research notes names that had no
backlog row yet. The X rows are sized and ordered, and the Suggested sequence (item 10)
schedules all of them except X10, which stays parked.*

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| E6 | **Tutorial chapter 11, a second bounded context**: payouts move out of the expense context into a finance context with its own ontology and model graphs, loaded in the same dataset as the expense context. This answers the [DDD note](research/2026-11-02-domain-driven-design.md)'s "one context per TriG file?" and the [build-along note](research/2026-10-29-build-along-tutorial.md)'s "a separate payments model owned by finance", and gives B2 and B5 a worked example | M | B1 | none beyond B1 | proposed |
| X1 | **As-observed named graph**: the worker's trace rows (or OpenTelemetry spans with element IRIs) loaded as a named graph, so that timing, conformance checks and dead-model detection ("elements no request ever reached") become queries. The later work U4 left open. [UML note §3.5](research/2026-10-29-uml-coverage-and-gaps.md) | M | U4; ADR first | a named-graph kind for observations, kept outside the model graphs | proposed |
| X2 | **Non-functional requirements**: SLOs and latency budgets on operations and processes, checked against X1's observations. [UML note §3.7](research/2026-10-29-uml-coverage-and-gaps.md) | M | X1 | an annotation vocabulary, unbuilt until now | proposed |
| X3 | **Data classification**: mark shape properties as personal data, so "which screens show personal data to which roles" is a query and a viewer Question. Candidate vocabulary: W3C DPV rather than a new term. [UML note §3.7](research/2026-10-29-uml-coverage-and-gaps.md) | S | none | one annotation on `sh:property`, preferably reused | proposed |
| X4 | **External systems and inbound webhooks**: a convention for third-party APIs (`arch:System` marked external, its operations external) and for inbound webhooks in general, of which O6's SemPKM webhook is one case. [UML note §3.7](research/2026-10-29-uml-coverage-and-gaps.md) | M | U6, O6; ADR first | an external marker on systems and operations | proposed |
| X5 | **Stored-data migrations from the shape diff**: when U8 classifies a stored shape change as breaking, generate a migration or refuse the deploy, by store kind. [UML note §3.4](research/2026-10-29-uml-coverage-and-gaps.md); a candidate task for C4 drafts in the [LLM note](research/2026-10-31-llm-generator.md) | M | U8, U9; ADR first | none expected | proposed |
| X6 | **Cross-aggregate invariants**: `sh:sparql` rules across instances, at `sh:Warning`, with a reader for them (a runtime report and a data-health view), since nothing reads a warning on instance data today. [DDD note §2.4](research/2026-11-02-domain-driven-design.md) | M | O4, B5 | none; plain SHACL | proposed |
| X7 | **Transactional boundary of an aggregate**: state which entities a process must change together, so `Runtime.write` can commit them as one. [DDD note §2.4](research/2026-11-02-domain-driven-design.md) | M | B1, B3; ADR first | one fact per aggregate, probably in the DDD profile | proposed |
| X8 | **Rationale links**: ADRs and decisions name the elements they decide, so the inspector can say why an element exists. [UML note §3.7](research/2026-10-29-uml-coverage-and-gaps.md) | S | none | none if `dcterms:references` serves | proposed |
| X9 | **Interchange exports**: the C4 layer as Structurizr DSL and LikeC4, and derived sequence and storm views as PlantUML beside Mermaid. Context Mapper stays with B5. [UML note §3.7](research/2026-10-29-uml-coverage-and-gaps.md) | S | none | none | proposed |
| X10 | **Imports from OpenAPI, SQL DDL and compose files**: the enterprise persona's entry point, drafting a model that is flagged, not refused | L | X9 | none | parked: a v1 non-goal in the product brief; revisit after X9 and the storm import (X12) show what an import has to carry |
| X11 | **Pinned providers and cached drafts**: `seams propose`, `suggest` and `draft-generator` record the provider and model, and cache a response by context hash so that a re-run is free and reproducible; decide whether to reuse SemPKM's copilot connection. Open questions in the [LLM](research/2026-10-31-llm-generator.md) and [data-centric](research/2026-10-31-data-centric-model-and-copilot.md) notes | S | C4, C5 | none | proposed |
| X12 | **Event-storm import**: read a big-picture storm into a model skeleton that is flagged, not refused, for missing paths and routes. Open question in the [DDD note](research/2026-11-02-domain-driven-design.md) | M | B4, I2 | none | proposed |
| X13 | **Static completeness and overlap for `UNIQUE` DMN tables**: report gaps and overlapping rules at check time instead of at run time. Open question in the [generator kit note](research/2026-10-30-domain-ide-and-generator-kit.md) | S | K2 | none | proposed |

Not taken up: LionWeb interoperability (watch only, as the generator kit note suggests)
and levels for IFML (item 14, re-parked with its threshold).

## Generator kit and domain IDE

*Added 2026-10-30 from the [generator kit and domain IDE note](research/2026-10-30-domain-ide-and-generator-kit.md),
which reads Boersma's* Building User-Friendly DSLs *and Parr's* Language Implementation
Patterns *against the repository. Planned 2026-10-31 as M017 to M025; see the Suggested sequence.* M010 gave users the
library and a generator guide; nothing yet registers their generators or packages the
reference-first method G2 used. The kit items do that. The IDE items refine P2 item 13 (Editing), which
was unparked on 2026-10-31: editing is in scope from the outset. K1 and K2 stand alone and are worth
doing first: today a model can show *Conforms* in the viewer and still fail generation. T1 to T5 come from the
[generation trace note](research/2026-10-31-generation-trace.md): tracing each generated line back to its
template and model, a view of it, and write-back in tiers. T1 to T3 need no editing, so
they can ship before the write path does. C1 to C5 come from the
[LLM generator note](research/2026-10-31-llm-generator.md): code the templates cannot
write, drafted by an LLM behind a deterministic stub and tests from the model, accepted
once, then owned and traced by its model context. O1 to O6 and R1 to R3 come from
the [data-centric note](research/2026-10-31-data-centric-model-and-copilot.md): an ontology
layer anchored in gist, SemPKM as the default RDF store, and a model copilot. R1 needs
nothing else and can start now.

| # | Item | Size | Depends on | Vocabulary impact | Status |
|---|---|---|---|---|---|
| K1 | **Shapes catch every generator fault first**: a parity test with one minimal broken model per `GeneratorError` condition; each fault gets a shape or is listed as generator-only with the reason. Starts with `ifml:order` on page components and `seam:reads` on `ifml:List`, which the generator requires and the shapes do not | S | none | shapes only | done (M017/S01) |
| K2 | **Static checks for decisions**: DMN `typeRef` agrees with the `sh:datatype` of the input's `dec:fromPath`; gateway condition variables are upstream `dec:processVariable`s | S | none | shapes or SPARQL checks only | done (M017/S02) |
| K3 | **Generator protocol and discovery**: name, version, precondition shapes, `extract` and `render`; a `seams.generators` entry-point group so `seams generate` runs it and the lockfile records it; a lenient mode with flagged output for previews | M | L2, A1, A2 | none | done (M018/S01 and S02) |
| K4 | **Generator test kit**: public golden comparison with the hash placeholder, determinism check, output checkers per file type, the K1 parity helper | S | K3 | none | done (M018/S03) |
| K5 | **Scaffold and guide**: `seams new-generator` from a reference output (verbatim template, passing golden test); a section in the L6 guide on the reference-first method and logic-free templates | S | K3, K4, L6 | none | done (M018/S04) |
| K6 | **Vocabulary versions and migrations**: a version IRI per vocabulary, the target version in each model, a load check (same, newer, older), SPARQL Update migrations per step, deprecation as `owl:deprecated` plus a warning-level shape | M | ADR first, L2; shares classification with U8 | version facts; first use of `sh:Warning` | done (M023/S02): every vocabulary carries `owl:versionIRI` and `owl:versionInfo` 1.0; a model `owl:imports` the versions it targets in `<urn:seams:graph:manifest>`, and every example and tutorial checkpoint declares them; `seams.load` loads the same version, refuses a newer one and migrates an older one in memory with `ontology/migrations/<vocabulary>/<from>-to-<to>.ru`, listing the steps in `Model.migrations`; `sh:Warning` results are advisory in `seams check`, generation, the runtime and the viewer, and `seams check` adds a `vocabulary-migrated` warning per step; a test pairs each `owl:deprecated` term with one warning shape; the compatible and breaking verdicts live in `seams_cli.classification`, and a gate fails a breaking ontology change without a major bump and its step file; `seams migrate` writes the migration through `seams_edit` ([ADR-0021](adr/0021-vocabulary-versions.md), [guide](guide/authoring-a-model.md#vocabulary-versions)) |
| K7 | **Shape for a List's one event**: the htmx generator refuses an `ifml:List` without exactly one `ifml:hasEvent` ("expected exactly one, found none"), but no shape requires it, so a List added on the IFML diagram passes the shapes and does not generate. Add the shape, or list the fault as generator-only with the reason, and extend K1's parity test. Found in M019 validation | S | K1 | shapes only | proposed |
| I1 | **Write path**: edits as quad patches with undo; a decision on comments and serialisation for TriG files the IDE writes (rdflib drops comments, and the examples rely on them) | M | ADR first, L2, P2 item 13 unparked | none | ADR accepted (M019/S01): [ADR-0017](adr/0017-write-path-and-editor.md) edits the TriG text in place through a new `seams_edit` package, and editing is a viewer mode; writer done (M019/S02): `seams_edit` applies a patch by editing the TriG text at the triple level, routes it to the file that declares each graph, writes all files or none, and undoes it byte for byte; a round-trip test over every example checks one-line diffs, comments kept and undo |
| I2 | **Forms from shapes**: edit one element through a form derived from the shapes that target its class; save invalid models and flag them | M | I1, K1 | none | done (M019/S03): with `SEAMS_EDIT=1` the viewer shows an Edit control on every element some shape targets; the form is built from the seam shapes and the model's own shapes (every SHACL target kind), each save is a `seams_edit` patch, a value that breaks the shapes is saved and the health badge flags it, and Undo restores the bytes ([guide](guide/the-viewer.md#edit-mode)) |
| I3 | **Live checks and preview**: re-run the shapes and the generators in lenient mode after each save; show the generated page beside the model | M | I2, K3 | none | done (M019/S05): in edit mode a preview pane beside the view re-runs the `seams.toml` project's generators on the edited model in lenient mode, in memory (nothing is written), lists each output with its text, and flags lenient faults by generator, subject and predicate; a form save refreshes it out of band with the health badge, and a BPMN or DMN save or Undo reloads it ([guide](guide/the-viewer.md#live-preview)) |
| I4 | **BPMN and DMN round-trip**: modelers in place of viewers, an ID rename that rewrites the seams graph (ADR-0002), a model-health check that lifted IRIs exist in the XML | M | I1 | none | done (M019/S04): with `SEAMS_EDIT=1` BPMN and DMN views open in the bpmn-js and dmn-js modelers, Save writes the XML through `seams_edit.save_payload`, an id rename (`seams_edit.rename_id`) rewrites the XML references and every quad naming the old lifted IRI in one undoable edit (ADR-0002), and the health badge lists lifted IRIs whose fragment is no id in the XML ([guide](guide/the-viewer.md#edit-mode)) |
| I5 | **Domain profiles**: a package of vocabulary, shapes, generators, palette and labels, attached by the reserved `seam:conformsTo`, restricting what the editor offers | L | ADR first, I2, K3 | extends `seam:Profile` | done (M019/S06): [ADR-0018](adr/0018-domain-profiles.md) makes a profile a `profiles/<name>/profile.ttl` package beside the model, attached by `seam:conformsTo`, with `seam:offersClass`, `seam:usesGenerator`, `seam:profileShapes` and SKOS or RDFS labels; in edit mode the viewer's palette offers only the profile's classes under its labels, health runs the profile's shapes and flags (never refuses) out-of-profile classes, the preview runs only the profile's generators, and a profile that does not resolve is a health fact naming the subject, predicate and detail ([guide](guide/the-viewer.md#domain-profiles)) |
| I6 | **IFML editing on the diagram**: the diagram-js modeling module on the IFML view (create, connect, move and delete containers, components, events and flows), each change a patch through the write path, properties edited through I2's forms | M | I1, I2, item 10 | none | done (M019/S07): in edit mode the IFML view is a diagram-js modeler with a palette and a context pad; creating a container, component or event, connecting an event with a navigation flow, dropping a container or component into another container, deleting an element with what it owns and the flows that touch it, and removing a form's field are each one `seams_edit` patch through `POST /edit/ifml/{model}`, undoable, redrawn from the model, and shown in the live preview; selecting an element opens its I2 form, and a refused op names the subject, predicate and reason ([guide](guide/the-viewer.md#ifml-editing)) |
| T1 | **Trace capture**: template origins by sentinel render, model origins through Jinja2 `finalize` with origin-carrying values, a sidecar trace per output, A2 provenance derived from it, and a test comparing traces with golden markers. [Note](research/2026-10-31-generation-trace.md) | M | K3; A2 for storage | none | done (M020/S01): [ADR-0019](adr/0019-generation-trace.md); `seams generate` writes a line-level `<output>.trace.json` beside each output of the htmx, FastAPI, compose and Dockerfile generators, locks it, and takes the lock `sources` from the trace terms; view objects name their `iri` and `origins`, and `tests/test_generation_trace.py` checks that the traces name every model element the golden markers cite. Open question: the `chat_api.py` golden explains the message-thread route's whole-component partial by `:select_to_thread ifml:swap ifml:Replace`, a flow the route generator never reads; should the fragment rule read the GET's incoming navigation flows, or should the golden stop citing it? |
| T2 | **Logic out of templates**: move the 43 of 213 template expressions that filter, concatenate or branch into `extract`, goldens unchanged; value-level traces need it, and K5 recommends it | S | none | none | done (M017/S03) |
| T3 | **Generation view**: model, template and output panes joined by trace lines, a fan-out view, and a "Generated" section in the element inspector ([mockup](research/2026-10-31-generation-trace.md)) | M | T1 | none | done (M020/S02): `/generation/{iri}` in the viewer draws the three panes from the `seams.lock` outputs and their trace sidecars, highlights the lines a click links, lists the element's fan-out across every output, and names a missing or malformed sidecar in a notice; the element inspector's Generated section lists the outputs citing the element and opens the view |
| T4 | **Write-back of single-literal values**: edit a label, title or path in the output, apply a one-triple patch after regenerating reproduces the edit, and show effects beyond the page first | M | T1, I1 | none | done (M021/S01): in edit mode the generation view's output pane edits a line; `viewer/writeback.py` takes the one literal of the line's trace terms written over the changed span (none or several is a refusal listing the candidates), drafts a one-triple replace patch, regenerates a temporary copy of the model with it and refuses unless the output equals the edit, and lists every other output line the patch changes; apply checks again and writes through `seams_edit`, undoably ([guide](guide/the-viewer.md#write-back-from-output)) |
| T5 | **Structural edit proposals**: drafted model patches accepted only when regeneration reproduces the edit; start with adding and removing form fields | M | T4 | none | done (M021/S02): in edit mode the generation view's **Edit output** text area takes a whole edited output; `viewer/structural.py` requires one changed block that adds or removes one named form control inside one traced `ifml:Form` with `seam:writes`, drafts the `ifml:Parameter` patch (plus a blank-node `sh:property` and `rdf:Property` for a path new to the written shape, its values copied from the control), accepts it only when regenerating reproduces the edited block, lists the lines it changes elsewhere, and applies through `seams_edit`, undoably ([guide](guide/the-viewer.md#structural-edits-adding-or-removing-a-form-input)) |
| C1 | **Implementation stub generator**: per service task, a deterministic, traced stub with data classes from the read and written shapes, the signature, and a docstring naming the decision and transition. [Note](research/2026-10-31-llm-generator.md) | S | U6 (ADR first), T1 | none | done (M022/S02): `python -m seams_gen.stubs` writes each `comm:PythonHandler` module once with a `TypedDict` per accepted and returned shape (an xsd type table, `NotRequired` without `sh:minCount`), a signature using them, docstring lines naming the invoking service task, its deciding decision and fired transition from `seams.context_for`, a `# context-hash:` header line, and a write-once `<module>.trace.json` sidecar (ADR-0019) linking each line to its model IRIs ([tutorial](tutorials/expenses/09-hand-written-code.md#write-the-stub-once)) |
| C2 | **Acceptance tests from the model**: shape conformance, legal-transition state, decision-branch scenarios, and a type check against the stub | M | U5, A9, C1 | none | done (M022/S03): the `acceptance` generator writes, per handlers module, `generated/acceptance/test_<module>.py` checking the hand-written body's types against the stub, its result per valid example against `seam:returnsShape` or `hydra:possibleStatus`, the lifecycle guard of the fired transition and the decision routing, in process through `seams_runtime.verify` ([tutorial](tutorials/expenses/09-hand-written-code.md#acceptance-tests-for-your-handler)) |
| C3 | **Context assembly**: per-kind rules narrowed to the facts used, canonical hashing of each element and native file, and a manifest with a context hash; useful as a review report before any LLM is involved | S | none | none | done (M022/S01): `seams.context_for(model, task)` returns a `Manifest` of hashed `ContextItem`s (the task, its shapes, transition and states, process, upstream decision, the container narrowed to its technology and binding keys, and the BPMN and DMN fragments) with a context hash, and `seams context TASK [--json]` prints it ([reference](reference/seams-library.md#context-assembly), [guide](guide/authoring-a-model.md#what-a-task-depends-on-seams-context)) |
| C4 | **LLM draft generator**: provider-agnostic call, versioned prompt templates, writes only to the U6 location, `seams propose`, accepted only when C2's tests pass; model text quoted as data, binding names but never values, never run in CI | M | C1 to C3, K3, U6 | none | done (M022/S04): `seams propose TASK` fills the versioned template `draft-v1` from the context manifest, stub and acceptance tests (model text in DATA fences, bindings named only), sends it to the provider command of `[propose] provider` or `--provider`, caches the response in `.seams/drafts/` by context hash, template and provider, and writes the handlers module only when its acceptance tests pass in a scratch copy ([ADR-0020](adr/0020-llm-drafts.md), [tutorial](tutorials/expenses/09-hand-written-code.md#draft-it-with-an-llm-optional)) |
| C5 | **Drafts in the lockfile, `seams check` and the generation view**: an `llm-draft` record, staleness from the context hash, hand-edit detection, and the draft node in T3 ([mockup](research/2026-10-31-llm-generator.md)) | S | A1, A2, T3, C3 | none | done (M022/S05): `seams propose` records each accepted draft in `seams.lock`, `seams check` reports `draft-stale` and `draft-hand-edited`, and the generation view lists each draft with its state ([guide](guide/the-viewer.md#generation-view)) |
| O1 | **Ontology notation**: `seam:Ontology` model graphs, gist imports, a class view in the viewer, and model-health checks for imports and versions. [Note](research/2026-10-31-data-centric-model-and-copilot.md). Decided in [ADR-0022](adr/0022-ontology-notation.md): one ontology per model now, shared by import once B1 lands; gist 14.0.0 vendored and pinned | M | ADR-0022; K6 for versions | a notation value | done (M023/S03): `seam:Ontology` is a notation value in seam 1.1; gistCore 14.0.0 is vendored unchanged under `ontology/vendor/` and an ontology's `owl:imports` resolve offline by version IRI, raising `ResolutionError(ontology, owl:imports)` on an unknown import or another version; two shapes require each ontology class to have a label and a model; `seams.load` lists the classes, labels, definitions and superclasses in `model.ontologies`; the viewer draws a class view on the shape-graph card renderer and the health panel lists import status and undeclared superclasses, which `seams check` reports as advisory `ontology-superclass` findings; chapter 9 of the expense tutorial adds an ontology anchored in gist ([ADR-0022](adr/0022-ontology-notation.md), [guide](guide/authoring-a-model.md#an-ontology-model)) |
| O2 | **Shapes target classes; states as categories**: `sh:targetClass`, `sh:name` for field names, lifecycle state IRIs as category members replacing copied `sh:in` lists, and form flattening for `sh:node` with fixed values ([gist example](research/examples/expense-gist.trig)) | M | O1 | none; plain SHACL | done (M023/S04): decided in [ADR-0023](adr/0023-shapes-target-classes.md), seam 1.2; a form shape names its class with `sh:targetClass` and a field's wire name with `sh:name` (falling back to the path's local name); a category field is `sh:class` of a `gist:Category` subclass whose members are lifecycle state IRIs, or `sh:in` of IRIs, and its options are the members' labels in lifecycle order, so the wire value stays the label; `sh:node` to a shape with one free `sh:path` and the rest `sh:hasValue` flattens into one field; the typed view exposes `Field.name`, category options, flattened fields and `Shape.target_class`, raising `ResolutionError` for an empty category or an ambiguous `sh:node`, and four seam shapes check the same faults; generators and the runtime contract read the typed view, so chapter 9 of the expense tutorial, migrated to the new notation, generates the same files and gives the same 422 results ([guide](guide/authoring-a-model.md#shapes-that-target-classes)) |
| O3 | **JSON-LD context generator** for API payloads, from the ontology and shapes | S | O1, O2 | none | done (M023/S05): decided in [ADR-0024](adr/0024-json-ld-context.md); the `jsonld` generator writes one JSON-LD 1.1 context per shape with a `sh:targetClass`: each `Field.name` mapped to its `sh:path` and typed by its `sh:datatype`, category fields as property-scoped `@vocab` terms mapping labels to member IRIs (the wire value stays the label), flattened `sh:node` and reference fields mapped to `null`; the generated API serves each at `GET /contexts/<shape>.jsonld` with a `json-ld#context` `Link` header on the routes returning that shape; chapter 9 of the expense tutorial runs it ([guide](guide/authoring-a-model.md#the-json-ld-context-of-a-shape)) |
| O4 | **SemPKM storage backend** behind U9's interface: validate, then `POST /api/commands`; read through scoped SPARQL; the compose generator adds SemPKM's services when the model names it. Decided in U9's ADR, alongside SQLite and PostgreSQL | M | U9, O2 | a store-kind value | done (M024/S02): decided in [ADR-0025](adr/0025-sempkm-store.md) (M024/S01), a third store kind for domain data, never the default; `deploy:SemPKM` and `deploy:authenticatesTo` with their shapes, and the store plan resolving a SemPKM store beside the relational one (T01); `SemPKMStore` writing each entity in one atomic `POST /api/commands` under the IRI SemPKM mints and reading through scoped SPARQL, behind a split store that keeps process state relational, with 503/502 problem+json and `/healthz` (T02); the compose generator emitting SemPKM's services from the model (T03); [chapter 10](tutorials/expenses/10-sempkm.md) stores and reads the tutorial's expenses through SemPKM (T04) |
| O5 | **Mental Model generator**: `manifest.yaml`, ontology, shapes, and views from IFML, as a package SemPKM installs | M | O1, O2, K3 | none | done (M024/S03): decided in [ADR-0026](adr/0026-mental-model.md) (T01); the `mentalmodel` generator writes `manifest.yaml` from the ontology model's facts and the ontology, target-classed shapes and one table view per IFML list or details view as JSON-LD in SemPKM's namespace, with fact-naming faults (T02); [chapter 10](tutorials/expenses/10-sempkm.md) writes one, which SemPKM's archive validator accepts, and a `SEAMS_E2E` test installs it into the chapter's SemPKM (T03). Open: SemPKM's development image reads its repository config from `/app/config/rdf4j/sempkm-repo.ttl`, which no model fact mounts, so the chapter's `expense_pkm` service does not start from that image |
| O6 | **SemPKM webhooks as a channel**, so `object.changed` can start a BPMN process through `seam:subscribesTo` | S | O4, ADR-0010 | a channel transport value | done (M024/S04): decided in [ADR-0027](adr/0027-sempkm-webhook-channel.md) (T01): SemPKM signs nothing, so the runtime reads each event back with the ADR-0025 service token and trusts no field of the body; `comm:SemPKMWebhook` with its shape and `ModelGraph.webhook_channel` raising each section 10 fault (T02); the receiver behind a generated `POST` route at the channel's `comm:path`, which starts each subscribed process once per (process, event, object) keyed by the object's IRI, answering 400, 422, 502 and 503 as problem+json (T03); [chapter 10](tutorials/expenses/10-sempkm.md) keeps vendors in SemPKM, and a changed vendor starts the vendor review process (T04). Open (ADR-0027 section 11): SemPKM's SSRF guard refuses compose-network targets, deliveries are not retried, and webhooks are registered by hand in SemPKM's admin pages |
| R1 | **Model review checks**: lifecycle labels repeated in `sh:in` (found three times today), `sh:class` pointing at a shape, shapes without a target class, undeclared paths, T2's computing expressions, and literals in drafts that repeat model facts; reported by `seams check` and the health badge | S | none | none | done (M017/S04) |
| R2 | **Copilot suggestions**: LLM-proposed model patches (move logic into DMN, merge shapes into a class, gist anchors), each accepted after validation, regeneration and review | M | R1, T5, C4 | none | done (M025/S01): decided in [ADR-0028](adr/0028-copilot-suggestions.md) (T01), reusing C4's provider command; `seams_cli.suggest` parses a `condition-to-dmn` JSON answer against the model and builds the change deterministically (`dec:Decision` facts shaped like the process's existing decision, a business-rule task before the gateway, conditions over its output variable, payload text edited with the layout kept), then checks it in a scratch copy through `seams_edit` against the shapes, the decision checks and every generator (T02); `seams suggest` fills the versioned template `suggest-v1` with each gateway whose conditions read a name no upstream decision outputs, caches a passing answer by model hash, template and provider, stores it pending in `.seams/suggestions/<id>/` with one unified diff per file, and writes it only on `--accept`, which refuses a stale model hash (T03) ([guide](guide/authoring-a-model.md#copilot-suggestions-optional), [reference](reference/seams-cli.md#seams-suggest)). Open: merging shapes into a class and gist anchors are later kinds (ADR-0028) |
| R3 | **Generators that write generators**: an LLM drafts a template and `extract` step from a reference output, accepted when the golden test passes | M | K5, C4 | none | done (M025/S02): decided in [ADR-0029](adr/0029-llm-drafted-generators.md) (T01), reusing C4's provider command; `seams_cli.draft_generator` fills the versioned template `draft-generator-v1` with the reference, the model's names and the scaffolded package module as quoted data, reads one `{extract, template, golden}` JSON answer, refuses template logic and restated model labels, runs the scaffold's four tests in a scratch copy with the answer in place (`new_generator.scaffold` now takes the extract step), and caches an accepted answer in `.seams/generator-drafts/` (T02); `seams draft-generator NAME --reference FILE` prints the prompt hash and cache state and writes the package only on acceptance (T03) ([guide](guide/write-your-own-generator.md#draft-it-with-an-llm-optional), [reference](reference/seams-cli.md#seams-draft-generator)) |

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
   item's parking reason is checked again first. Item 13's no longer holds: editing was
   brought into scope on 2026-10-31, and S04 was skipped in favour of M019. *Item 12 done,
   M008/S01: `python -m seams_gen ifmledit` exports the IFML layer as IFMLEdit.org JSON,
   and the seven `ifml:` term groups IFMLEdit cannot hold are deferred rows GAP-29 to
   GAP-35.* *Item 14 re-parked, M008/S02 (D055): the largest example IFML model has 3 containers and 4 events, so levels would draw nearly the same picture; revisit at roughly 10+ containers or 30+ events, or when editing (M019) needs a coarser view.* *Item 11 done, M008/S03: the E3 complexity check passes on the finished expense
   app (`python -m seams_gen.complexity examples/expenses/chapter-08/expenses.trig`), so
   `GET /layers` draws the model as six stacked planes with hover tracing of seams.*
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
     OpenTelemetry spans. Depends on M010 and M011. *U3 done, M013/S01: `invoke_llm`
     declares `seam:publishesTo :stream_events`, and the runtime publishes deltas only on
     declared channels. U1 done, M013/S02: `seams sequence <event>` and
     `python -m seams_gen.sequence` derive one Mermaid diagram per exclusive-gateway path,
     with a `%% gap:` line for every arrow the model cannot place; the goldens are in
     `docs/generation/sequences/`. S03 landed: the viewer's `GET /sequence/{event}` and its
     Sequences section render them with Mermaid, and the concept page, the tutorial and
     expenses chapter 8 embed the goldens by snippet import. U4 done, M013/S04:
     `seams sequence <event> --trace RUN` renders a recorded run from the worker's trace
     rows on the same lifelines, and the runtime emits optional OpenTelemetry spans with
     element IRIs when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the `otel` extra is
     installed. The as-observed named graph stays as later work. M013 landed.*
   - **M014, Hand-Written Code and Failure Paths** (U6, U7): an ADR and runtime dispatch for
     operation implementations, a hand-written service task in the expense example, error
     shapes and error boundary events. Depends on M010 and M012, because hand-written code
     has to survive `seams generate`. *U6's ADR (ADR-0012, M014/S01), runtime dispatch with the
     write-once handler stub generator (M014/S02) and the expense tutorial's chapter 9, a
     hand-written service task (M014/S03), are done. U7 done, M014/S04: ADR-0013 error
     shapes as problem+json on `hydra:possibleStatus`, generated problem+json responses,
     lifted error boundary events the runtime routes to, and chapter 9's Notify Manager
     error path to finance.*
   - **M015, Change Safety and Verification** (U8, A7, U5, A9): shape and contract diff,
     change plans, scenarios with derived tests and coverage queries, and generated smoke
     tests. Depends on M010 and M012. *U8 done, M015/S01: `seams diff OLD NEW` classifies
     shape and operation-contract changes as compatible or breaking. A7 done, M015/S02:
     `seams plan OLD NEW` writes change plans and release notes, and CI's `change-plan`
     job posts one to the job summary for each pull request that changes a model. U5 partially
     done, M015/S03: the `verify:` vocabulary (ADR-0014) states scenarios and examples, and the
     `tests` generator derives scenario, decision, shape-example and per-role policy tests
     that CI runs. U5 done, M015/S04: coverage reports (`seams coverage`, `seams check` gates and
     viewer Questions) list the BPMN paths no scenario runs, the transitions nothing fires and the
     permissions without a deny test. A9 done, M015/S05: the `smoke` generator writes tests that call
     every operation on its path and validate the answer against `seam:returnsShape`, and the
     `tutorial-e2e` job runs chapter 9's against the compose stack. All four M015 items are done.*
   - **M016, Deploy from the Model** (A4, A5, A8): an ADR on environments, one compose file
     per environment, image build and publish, and a secrets checklist. Depends on M011 and
     M012. *ADR-0015 accepted, M016/S01. A4 done, M016/S02: `deploy:override` facts per
     `arch:Environment`, one generated `compose.<environment>.yaml` per environment, and no
     hand-written compose override left. A5 done, M016/S03: a generated Dockerfile per
     serving container replaces `docker/runtime.Dockerfile`, and a gated workflow publishes
     the images tagged with the production version and the model hash (the registry owner
     is still open). A8 done, M016/S04: `seams secrets` checks each environment's
     configuration keys and secrets exist without reading a value, and writes a
     `.env.example`. All three M016 items are done.*

   The `seams` command (`generate`, `check`, `status`, `sequence` and the later subcommands) lives in its
   own workspace package, so the library keeps only rdflib and lxml as dependencies (D030).
   M008 runs after M016 (D032).
9. The kit, IDE, trace, LLM-generator, data and copilot items as M017 to M025, planned
   2026-10-31. Editing is in scope from the outset
   ([principle 10](project/principles.md#_10-the-model-is-editable-through-one-write-path)),
   so M019 replaces M008/S04. Every slice is a sketch, refined when it starts, and each
   milestone that needs a decision opens with its ADR.
   - **M017, Honest Checks** (K1, K2, T2, R1): shapes catch every generator fault, static
     decision checks, logic out of templates, and model review checks. No dependencies.
     *K1 done, M017/S01: `tests/test_shape_generator_parity.py` gives every
     `raise GeneratorError` in `seams_gen` a parity case (a broken example the shapes flag
     and the generator rejects) or a `GENERATOR_ONLY` entry with its reason, and its
     inventory fails on an unlisted or stale raise site. New shapes require `ifml:order` on
     page components and `seam:reads` on an `ifml:List`.
     K2 done, M017/S02: `seams.decision_findings` checks each DMN input's `typeRef`
     against the `sh:datatype` of its `dec:fromPath` and each gateway condition's
     variables against what upstream tasks set; `seams check` reports them as
     `decision` findings.
     T2 done, M017/S03: the htmx, FastAPI, compose and tests generators compute every
     join, filter and compound condition in `extract`, goldens unchanged, and
     `tests/test_template_logic.py` fails on any template tag that is not a prepared
     value or a plain loop or branch over one.
     R1 done, M017/S04: `seams.review_findings` flags lifecycle labels copied into
     `sh:in`, `sh:class` pointing at a shape, shapes without `sh:targetClass` and
     undeclared `sh:path` IRIs; `seams check` prints them as advisory `review` lines
     that leave the exit status alone, and the viewer health badge counts them as
     warnings. The row's checks for T2's computing expressions and for draft literals
     that repeat model facts are not built yet.*
   - **M018, Generator Kit** (K3, K4, K5): the generator protocol and entry points, lenient
     mode, the public test kit, and `seams new-generator`. Depends on M012 and M017.
     *K3 done, M018/S01 and S02 ([ADR-0016](adr/0016-generator-protocol.md)): a generator
     is a `seams_gen.protocol.Generator` (name, version, help, precondition shapes,
     `extract`, `render`, `sources`), found through the `seams.generators` entry-point
     group; the seven built-ins are registered there from `semanticseams-cli` (D056).
     `seams generate` runs a generator from another distribution, checks precondition
     shapes strictly (exit 2, nothing written) and records each output's own generator
     version in `seams.lock`. `seams generate --lenient` (S02, D057) collects
     precondition and generator faults instead of raising, writes what it can and records
     the faults in a `faults` list in `seams.lock`; `seams check` reports such a lock as
     `flagged` (exit 1), so CI rejects it. Strict mode stays the default.
     K4 done, M018/S03: `seams_gen.testing` is the public test kit, with the golden
     comparison and its `sha256:<model-hash>` placeholder, `assert_deterministic`,
     `check_output` per file type and the K1 parity helper `assert_shapes_catch`; the
     built-in and parity tests use it, and `tests/test_generator_kit_third_party.py`
     tests a generator defined in the test with it alone.
     K5 done, M018/S04: `seams new-generator NAME --reference FILE` turns a reference
     output into a generator package (entry point, `Generator`, the reference verbatim as
     its template, a golden marked `[fixed]` line by line and a kit-based test that passes
     as generated), and the generator guide's "Start from a reference output" section
     walks the loop from literal to view-model field with logic-free templates; the guide
     test runs that walkthrough as written. M018 is done.*
   - **M019, Editing the Model** (I1 to I6): an ADR on the write path and comments, the
     write path with a round-trip test, forms from shapes, the BPMN and DMN modelers with
     ID renames, live checks and preview, domain profiles, and IFML editing on its diagram. Depends on M017 (K1) and
     M018 (K3 for the preview).
     *I1's ADR done, M019/S01 ([ADR-0017](adr/0017-write-path-and-editor.md)): a patch
     edits the source TriG text at the triple level so comments and layout survive, the
     write path is a new `seams_edit` package outside the read-only `seams` library, and
     editing is a viewer mode that is off by default.* *The writer done, M019/S02:
     `seams_edit` holds the patch value, the TriG text writer, file apply and undo; a
     round-trip test over every example shows an empty patch keeps the bytes, a one-quad
     edit is a one-line diff with every comment kept, and undo restores the bytes.* *Forms
     from shapes done, M019/S03: the viewer's edit mode (`SEAMS_EDIT=1`) builds a form
     from the shapes that target an element, saves each change through `seams_edit`,
     flags rather than refuses a value that breaks the shapes, and undoes the session's
     edits.* *The BPMN and DMN round-trip done, M019/S04: in edit mode BPMN and DMN open
     in the bpmn.io modelers, saving writes the XML through `seams_edit`, an id rename
     moves every seam edge of the lifted IRI in the same undoable edit (ADR-0002), and
     model health flags lifted IRIs missing from the XML.* *Live checks and preview done,
     M019/S05: after each save the health badge re-runs the shapes and a pane beside the
     view re-runs the project's generators in lenient mode, in memory, flagging their
     faults.* *Domain profiles done, M019/S06
     ([ADR-0018](adr/0018-domain-profiles.md)): a model attached to a profile by
     `seam:conformsTo` gets a palette of the profile's classes under its labels, health
     with the profile's shapes and out-of-profile classes flagged, and a preview of only
     the profile's generators.* *IFML editing done, M019/S07: in edit mode the IFML view is
     a diagram-js modeler whose create, connect, move, delete and remove-field gestures
     are each one undoable `seams_edit` patch, redrawn from the model and shown in the
     live preview.*
   - **M020, Generation Trace** (T1, T3): trace capture and the generation view. Depends
     on M018. *Trace capture done, M020/S01: a line-level `<output>.trace.json` beside each
     generated file, recorded in `seams.lock` with the lock sources taken from it, and
     checked against the golden markers.* *Generation view done, M020/S02: the viewer's
     `/generation/{iri}` joins model, template and output line by line through the traces,
     with the element's fan-out and a Generated section in the inspector.*
   - **M021, Write-Back from Output** (T4, T5). Depends on M019 and M020. *Write-back of
     single literals done, M021/S01: in edit mode an edited line in the generation view's
     output pane becomes a one-triple patch to the one literal behind it, applied only
     when regenerating with it reproduces the edit, after the other lines it changes are
     shown.* *Structural edits done, M021/S02: adding or removing a form input in the
     whole output becomes an `ifml:Parameter` patch, with a `sh:property` for a new path,
     applied only when regenerating reproduces the edited block.*
   - **M022, Code the Templates Cannot Write** (C3, C1, C2, C4, C5). Depends on M014 (U6),
     M015 (U5, A9) and M020. *Context assembly done, M022/S01: `seams context` lists, for a
     service task, the model facts and native file fragments its code depends on, each
     hashed, with a context hash.* *Implementation stubs done, M022/S02: handler stubs are
     typed from their shapes, name their task, decision and transition, record the context
     hash and come with a trace sidecar.* *Acceptance tests done, M022/S03: generated
     tests check a hand-written handler's types, results, legal transitions and decision
     branches against the model; chapter 9's notify handler passes them in CI.* *LLM drafts done, M022/S04: `seams
     propose` drafts a handler body through a provider command and writes it only when
     the acceptance tests pass.* *Drafts in the lockfile done, M022/S05: accepted drafts
     are recorded in `seams.lock`, `seams check` reports them stale or hand-edited, and
     the generation view shows each with its state.*
   - **M023, Data-Centric Model** (K6, O1, O2, O3): vocabulary versions first, so they land
     before O2's first change that is not widening. Depends on M018. *Vocabulary versions
     decided, M023/S01: ADR-0021 gives each vocabulary an `owl:versionIRI`, has a model
     `owl:imports` the versions it targets, and specifies the load check, SPARQL Update
     migrations per major step and `sh:Warning` deprecations.* *Vocabulary versions done,
     M023/S02: the load check, in-memory migrations, warning-level deprecations, the
     ontology breaking-change gate and `seams migrate`; the examples declare their versions.*
     *Ontology notation done, M023/S03: ADR-0022's `seam:Ontology` graphs import a vendored, pinned
     gist offline, the viewer shows them as a class view, and `seams check` and the health panel
     report import and version faults; the expense tutorial's chapter 9 has an ontology.*
     *Shapes target classes done, M023/S04: ADR-0023's `sh:targetClass`, `sh:name`, category states and
     `sh:node` flattening are read by the typed view, the generators and the runtime; chapter 9's shapes
     use them and its generated files are unchanged.* *JSON-LD context done, M023/S05:
     ADR-0024's `jsonld` generator writes a context per target-classed shape, and the
     generated API serves it with a `json-ld#context` `Link` header; chapter 9 runs it.*
   - **M024, SemPKM** (O4, O5, O6), opening with an ADR on SemPKM as a store. Depends on
     M011 and M023. *ADR done, M024/S01: [ADR-0025](adr/0025-sempkm-store.md) places SemPKM
     beside SQLite and PostgreSQL as `deploy:SemPKM`, for domain data only; embedded SQLite
     stays the default.* *Store done, M024/S02: `SemPKMStore` writes each entity in one
     `POST /api/commands` and reads through scoped SPARQL, the compose generator emits
     SemPKM's services from the model, and [chapter 10](tutorials/expenses/10-sempkm.md)
     stores the tutorial's expenses in SemPKM.* *Mental Model done, M024/S03:
     [ADR-0026](adr/0026-mental-model.md)'s `mentalmodel` generator writes the SemPKM package
     (manifest, ontology, shapes and views) from the model, and chapter 10 emits one.* *Webhooks done,
     M024/S04: [ADR-0027](adr/0027-sempkm-webhook-channel.md)'s `comm:SemPKMWebhook` channel
     lets a change made in SemPKM start a subscribed process, and chapter 10's changed vendor
     starts a review.*
   - **M025, Model Copilot** (R2, R3). Depends on M021 and M022. *Suggestions done, M025/S01:
     [ADR-0028](adr/0028-copilot-suggestions.md)'s `seams suggest` asks the provider command for
     a `condition-to-dmn` change, builds and checks it in a scratch copy, and keeps it pending
     with a diff until `--accept` writes it through `seams_edit`. Generators that write
     generators done, M025/S02: [ADR-0029](adr/0029-llm-drafted-generators.md)'s
     `seams draft-generator` has the provider draft a generator's template and extract step
     from a reference output and writes the package only when its golden test passes.*
10. The remaining items as M027 to M033, planned 2026-11-05 after M026 (U5's last paths)
    landed. DDD comes before the runtime work because it extends the model itself.
    - **M027, Honest Edges** (A11, A12, A14, K7, X13, X11): small, independent fixes.
      *Dockerfile path check done, M027/S01: a stale or missing `deploy:dockerfile` is a
      `GeneratorError` on `deploy:dockerfile` (A11). Workspace members done, M027/S02: the
      generated Dockerfile copies the members `[tool.uv.workspace]` names, read from the
      build context's root `pyproject.toml` (A12); generators declare such files beyond
      the model with `Generator.inputs` (ADR-0016 amendment).*
    - **M028, Event Storm and Bounded Contexts** (B4, B1, B3, E6): the storm view first,
      then B1's ADR and vocabulary, lifecycle on the class, and chapter 11.
    - **M029, Context Maps and the DDD Profile** (B2, B5, X7, X6). Depends on M028.
    - **M030, Time and Scale** (U10, A10): timer start events, then replicas with a
      shared stream channel.
    - **M031, Data Care** (X3, X4, X5): classification, external systems, migrations.
    - **M032, Observed Behaviour** (X1, X2). Depends on M030, since the observations
      should come from more than one replica.
    - **M033, Interchange** (X9, X8, X12). Depends on M028.
    X10 stays parked.
