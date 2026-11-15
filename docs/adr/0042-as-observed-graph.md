# ADR-0042: The As-Observed Named Graph — Recorded Runs, From Trace Rows or OTLP JSON Spans, Load as an `obs:` Graph Outside the Model and Its Hash, and Two Questions Join It With the Model: Which Elements No Run Reached, and Which Steps Reached Nothing the Model Declares

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M032/S01; backlog X1 (the work U4 left open); research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.5;
builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0007](./0007-execution-strategy.md),
[ADR-0013](./0013-error-shapes-and-boundaries.md),
[ADR-0019](./0019-generation-trace.md),
[ADR-0021](./0021-vocabulary-versions.md) and
[ADR-0037](./0037-timers-and-scheduling.md); decision D049 (OpenTelemetry spans whose
attributes are element IRIs)

## Context

The worker records what each process instance did. Two records exist today:

- **Trace rows.** `workflow.data["seams"]["trace"]` holds one dict per BPMN element the
  instance reached, in order: `task` (the BPMN id), `iri` (the element's IRI, ADR-0002)
  and, when the element did them, `fires`, `decision`, `invokes`, `container`,
  `implementation`, `handler`, `status`, `by`, `boundary`, `caught`, `timer`,
  `published`/`streamed` (with a `channel`) and `error` (with `code` and `status`). The
  instance result returns them under `trace` with the `instance` id and the
  `correlation_key`. `seams_gen.sequence.read_trace` reads them from a result file, a
  bare list of rows, or an instance's `workflow_state` checkpoint in the SQLite store,
  and `seams sequence --trace` draws them.
- **Spans.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set (D049), `seams_runtime.telemetry`
  exports one instance span per `Worker.run` (`seams.process.iri`, `seams.instance.id`,
  `seams.correlation_key`) and one child span per element carrying those three plus
  `seams.element.iri`, `bpmn.id` and one `seams.*` attribute per row key
  (`_ROW_ATTRIBUTES`, `seams.channel`, `seams.error.code`, `seams.error.status`).

Neither can be asked a question alongside the model. The UML note's section 3.5 points
out that the IRIs already join them: a row's `iri` is the model's IRI for the element.
Backlog X1 asks to load the records as a named graph so that dead-model detection
("elements no request ever reached") and conformance checks become queries, and says the
ADR comes first, because the graph must be a new kind: one kept outside the model graphs.

What must not change:

- **The model is the source of truth** and is read-only to every reader
  (`packages/seams`). Observations are not facts about the application; they are one
  deployment's history, and two deployments of one model observe different things.
- **Same model, same bytes, same hash.** `Model.hash` frames the TriG files and the
  payloads (`seams.loader`); generated modules embed it (P006) and the runtime refuses a
  mismatch. Loading observations must leave it alone.
- **Partitioning** (ADR-0001): one named graph per model plus the seams graph, and the
  manifest graph of ADR-0021.

## Decision

### 1. The `obs:` vocabulary

A new vocabulary, `ontology/obs.ttl`, at
`https://w3id.org/seams/obs#` (prefix `obs:`, ontology IRI `https://w3id.org/seams/obs`,
version `https://w3id.org/seams/obs/1.0` per ADR-0021). It has two classes:

- **`obs:Run`**: one process instance, with `obs:instance` (the instance id, a string),
  `obs:process` (the process IRI, when the source carries it), `obs:correlationKey`
  (when the source has one) and one `obs:step` per step.
- **`obs:Step`**: one BPMN element the run reached, with `obs:index` (its position in
  the run, from 0, an `xsd:integer`) and `obs:reached` (the element's IRI). The other row
  keys map one to one:

| Trace row key | Span attribute | Property | Object |
|---|---|---|---|
| `iri` | `seams.element.iri` | `obs:reached` | IRI |
| `task` | `bpmn.id` | `obs:bpmnId` | string |
| `fires` | `seams.fires` | `obs:fires` | IRI |
| `decision` | `seams.decision` | `obs:decision` | IRI |
| `invokes` | `seams.invokes` | `obs:invokes` | IRI |
| `container` | `seams.container` | `obs:container` | IRI |
| `implementation` | `seams.implementation` | `obs:implementation` | string |
| `handler` | `seams.handler` | `obs:handler` | string |
| `status` | `seams.status` | `obs:status` | string |
| `by` | `seams.by` | `obs:by` | string |
| `boundary` | `seams.boundary` | `obs:boundary` | IRI |
| `caught` | `seams.caught` | `obs:caught` | string |
| `timer` | `seams.timer.due` | `obs:timer` | string |
| `published.channel`, `streamed.channel` | `seams.channel` | `obs:channel` | IRI |
| `error.code` | `seams.error.code` | `obs:errorCode` | string |
| `error.status` | `seams.error.status` | `obs:errorStatus` | IRI |

A key the table does not list (`outputs`, `started`, `failed`, `path`, `model`,
`tokens` and the error's `operation`) is not carried: each is either a payload value or
derivable from the model. Adding one later is a compatible widening of `obs` (ADR-0021).
The vocabulary's terms appear only in as-observed graphs; no model uses them, and no
seam shape constrains them.

### 2. The graph: one per load, outside the model and its hash

- **Its IRI is `urn:seams:observed:<hex>`**, where `<hex>` is the SHA-256 of the
  canonical input: the runs sorted by instance id, each with its rows in trace order,
  written as JSON with sorted keys. The same recorded runs give the same graph IRI and
  the same triples, whichever order they were loaded in.
- **Subjects are IRIs, not blank nodes**, so that the serialization is stable: a run is
  `urn:seams:observed:run:<instance>` and its step `n` is
  `urn:seams:observed:run:<instance>:step:<n>`, the instance id percent-encoded.
- **It is never one of the model's graphs.** The loader returns an `rdflib` graph of its
  own; it is not added to `Model.dataset`, not written into any model file and not
  passed to the seam shapes. `Model.hash` reads only the model's files and payloads, so
  it is the same before and after a load, and a test asserts it.
- **Same input, same bytes.** Serialised, the graph's triples are sorted; it holds no
  timestamp and no path. The source a run was read from names it only when the source
  has no instance id (section 3).

### 3. The sources

Each source becomes `(run id, rows)` pairs; the graph is built from the pairs.

- **Trace rows**, read with `seams_gen.sequence.read_trace`: an instance result file (run
  id `instance`, correlation key `correlation_key`), a bare list of rows (run id: the
  source as the user named it) or an instance id in the store (`--db`).
- **OTLP JSON span files**: the OTLP/JSON encoding of an export request
  (`resourceSpans[].scopeSpans[].spans[]`, attributes as `{key, value}` with
  `stringValue`), which a collector's file exporter writes. An element span is a span
  with `bpmn.id` or `seams.element.iri`; every other span (instance, aggregate commit,
  data health, timer claim and fire) is not a step. Element spans are grouped into runs
  by `seams.instance.id`, and ordered by `startTimeUnixNano`, then span id. A run's
  `obs:process` and `obs:correlationKey` come from `seams.process.iri` and
  `seams.correlation_key`. The `seams.*` attributes map back to row keys by the table in
  section 1, so a span file and the trace rows of the same run give the same steps.
- **Malformed input is refused** with `ResolutionError(subject, predicate, detail)`
  naming the row or span: a row that is not an object, a value of the wrong JSON type, an
  element span with no `seams.instance.id`, a file that is not OTLP JSON. Nothing is
  returned on failure.
- **An unmapped step is kept**, not dropped: a row or element span with no element IRI
  becomes a step with no `obs:reached`, and the conformance question reports it.

### 4. The two questions

Both join the model with one as-observed graph, evaluated over a union that is built for
the query and discarded; `Model.dataset` is not mutated.

BPMN flow nodes live in the BPMN XML, not in the graph (ADR-0007): only the nodes a seam
names are lifted. The questions' element universe is therefore every flow node of every
process the model's BPMN payloads declare, by its ADR-0002 IRI (the BPMN model's IRI, `#`,
the node id), as `seams.bpmn` parses them, given to the query as bindings.

- **Dead model** (`dead-model`): the flow nodes of the model's processes that no step
  of the graph reached, sorted by IRI, with their process. A process none of whose nodes
  any step reached is reported whole, as its nodes. It answers "what did no run reach";
  it does not say the element is wrong, only that these runs never exercised it.
- **Conformance** (`conformance`): the steps the model does not explain, sorted by run
  and index, each with a reason: the step has no `obs:reached` (unmapped); its
  `obs:reached` is not a flow node of the model; or its run's `obs:process` is not a
  process of the model. An empty answer means every recorded step reached an element the
  model declares.

The questions are SPARQL files under `packages/seams/src/seams/queries/observed/`, run
by `seams.observed_question(model, graph, name)`. The CLI (`seams observed`) and the
viewer's Questions panel ask them; neither writes the graph anywhere.

## Alternatives considered

- **A named graph inside the model's dataset.** Rejected: every reader of the dataset
  (the seam shapes, the generators, the viewer's model views) would see observations as
  model facts, and a model file that held them would change its hash with every run.
- **Blank-node runs and steps.** Rejected: blank-node labels are not stable across
  loads, so the serialization would change for the same input.
- **Reading spans from a tracing backend's API** (Jaeger, Tempo). Rejected for now: each
  backend has its own API; the OTLP JSON a collector's file exporter writes is the one
  format every backend accepts, and is a file a test can hold.
- **Recording timing.** Trace rows have no times; spans do. Durations and latency are
  X2's subject (non-functional requirements checked against observations), and are
  left to it.
- **Lifting every BPMN node into the model graph** so that the questions need no XML.
  Rejected: ADR-0007 lifts only the nodes a seam names, and the questions can read the
  rest from the payloads as `seams.coverage` already does.

## Consequences

- `packages/seams` gains `seams.observed` (S01/T02): `observed_graph(runs)`,
  `spans_to_runs(otlp_json)` and `observed_question(model, graph, name)`, with the two
  queries, rdflib only and pyright-strict.
- `seams observed` asks the questions from the CLI (S01/T03); the viewer answers them in
  its Questions panel when observations are configured (S01/T04).
- The expense tutorial's chapter 9 e2e runs load as an as-observed graph and answer both
  questions (S01/T05).
- `ontology/` gains `obs.ttl` at 1.0, and the layer vocabularies reference page lists
  it.

## Open questions

- **Timing and latency** (X2): answered by ADR-0043 (`obs:duration`, see the revision
  notes).
- **Several deployments.** One graph per load; comparing two deployments' observations
  is a later question.
- **Processes started by a channel** (ADR-0010): a run started by a publish is its own
  run; linking it to the run that published is not recorded here.

## Revision notes

- **2026-11-15 (M032/S02, [ADR-0043](./0043-latency-budgets.md)):** the timing open
  question is answered. `obs` moves to 1.1 with `obs:duration`: an element span's
  `endTimeUnixNano` minus its `startTimeUnixNano`, in milliseconds, as an `xsd:decimal`.
  Trace rows have no times, so their steps carry none, and no start or end time is
  recorded. Latency budgets (`nfr:LatencyBudget`, a model fact) are checked against it.
