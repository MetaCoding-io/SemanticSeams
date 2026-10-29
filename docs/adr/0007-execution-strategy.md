# ADR-0007: Execution Strategy — Interpret Where an Engine Exists, Generate Where None Does

**Status:** Accepted

**Date:** 2026-10-28

**Accepted:** 2026-10-28, after the M004/S01 spike (see [Spike Findings](#spike-findings))

**Source:** [backlog](../backlog.md) item G1; project outline §3 (execution boundary) and §6 ("interpret or generate"); product brief M3; tutorial step 8

## Context

The project outline decided the **execution boundary**: the BPMN engine never learns about seams, executes native vendor-extension-free XML, and a single generic graph-literate worker resolves each service task's fragment IRI, follows `seam:invokes` to the operation and its SHACL contracts, dispatches, validates, and enforces `seam:governedBy`. It left open *how* the application runs: **interpret** the model at runtime, or **generate** code from it.

Milestone M3 (product brief, tutorial step 8) then defined three generators for the chat-app tutorial — htmx templates from the interaction model, a FastAPI scaffold, a docker-compose file from `deploy:` — and kept BPMN interpretation out of v1: "the generated scaffold hard-wires the tutorial's linear flow." The worker is a stub.

Hard-wiring the flow has three problems:

- **The diagram stops being the truth.** The BPMN the viewer shows and the order the code executes are two copies of the same fact. The first edit to one silently diverges from the other, which is exactly the failure the project exists to prevent.
- **Regeneration fights hand edits.** Workflow logic in generated code invites hand changes, which the next regeneration overwrites.
- **It is more work, not less.** A generator that emits correct sequencing, error paths and message events re-implements part of a BPMN engine. SpiffWorkflow already is one, in Python, and runs DMN.

At the same time, not every layer has an engine. Nothing mature interprets IFML into a running htmx UI, Docker reads files rather than graphs, and FastAPI needs route declarations to exist as code.

## Decision

### Per-layer strategy

| Layer | Strategy | Mechanism |
|---|---|---|
| Process (BPMN) | **Interpret** | SpiffWorkflow runs the native payload unchanged |
| Decision (DMN) | **Interpret** | SpiffWorkflow's DMN engine evaluates the native payload |
| Data contracts (SHACL) | **Interpret** | pySHACL in the worker validates request and response payloads against `seam:acceptsShape` / `seam:returnsShape` at the call boundary |
| Lifecycle (statechart) | **Interpret** | The worker checks a task's `seam:fires` transition against the entity's current state before dispatch; no engine needed |
| Authorization | **Interpret** | The worker enforces `seam:governedBy` at the same choke point (v1: presence check and a pluggable evaluator; ODRL evaluation post-v1) |
| UI (IFML) | **Generate** | Jinja/htmx templates: container → page, component → partial, event + flow → `hx-get`/`hx-post` with target and swap |
| API (comm / Hydra operations) | **Generate** | A FastAPI route module whose handlers are thin: hand the payload to the runtime, start or advance a process instance, return |
| Deployment (`deploy:`) | **Generate** | docker-compose from artifacts, configuration, replicas, dependencies; secrets by reference only |

### Rules

1. **Generated code holds no business logic.** No workflow order, no decision rules, no validation rules, no state guards. Those live in the payloads and the graph and are executed by the runtime. A generated handler that contains an `if` about the domain is a bug in the generator.
2. **The graph is the runtime service registry.** The running application loads the same model graph the viewer shows. The worker resolves tasks, operations, shapes, transitions and policies from it at runtime. Generated artifacts record the content hash of the model they were generated from, and the runtime refuses to start against a different hash unless told to.
3. **Native XML stays vendor-extension-free** (reaffirms the outline). Engine wiring that BPMN tools usually carry in extension attributes — which decision a business-rule task evaluates, which operation a service task calls — comes from `seam:decidedBy` and `seam:invokes`, resolved by the worker. Standard BPMN attributes are fine: the chat process's `isExecutable` flips to `true`.
4. **Generated files are disposable.** Each carries a generated-file header with the source model hash, is never hand-edited, and is regenerated in CI. Customisation goes through generator templates or a hand-written extension module that generated code imports when present.
5. **Generation is deterministic.** The same model produces byte-identical output, so generated files diff cleanly and golden-output tests are meaningful.

### Amendment to M3

M3 keeps its three generators and their tutorial scope. Two things change:

- The generated scaffold **does not hard-wire the flow**. The send-message endpoint starts a SpiffWorkflow instance of `chat_process.bpmn`; the business-rule task evaluates `routing.dmn` through the same engine.
- The generic worker moves **from stub to v1 deliverable**: task resolution, SHACL validation at the boundary, lifecycle guard, policy hook.

The tutorial text in `orig_convo/` is the original brief and is left as written; this ADR supersedes its "BPMN interpretation stays out" note.

## Alternatives Considered

- **Generate everything (current M3 text).** Simplest to explain. Rejected for the three problems in Context; it also makes the BPMN diagram documentation rather than executable model.
- **Interpret everything, including IFML.** A generic htmx renderer reading the interaction model at request time (LinkedDataHub-style) is attractive and stays a candidate post-v1. Rejected for v1: no existing engine, it is the larger build, and generated templates are inspectable and diffable for the tutorial persona. Compose must be generated regardless.
- **A JVM engine (Operaton, Flowable).** Mature, and Flowable covers CMMN. Rejected for v1: a second runtime stack beside a Python model toolchain, for a tutorial whose process has five tasks.

## Open Items (resolved by the spike; see Spike Findings)

*Original text, kept for history. It was written as "spike before M3 work starts".*

1. **Decision resolution without extensions.** Confirm SpiffWorkflow can be told which DMN decision a business-rule task evaluates from outside the XML (a custom task spec or parser hook fed by `seam:decidedBy`). Fallback if not: the build step writes the extension attribute into a *derived copy* of the payload for the engine, never into the source payload, and the drift lint (ADR-0006) checks the copy.
2. **Streaming.** `invoke_llm` streams tokens over SSE; a service task is synchronous from the engine's view. Proposed: the worker completes the task when the stream ends and publishes stream events to the `stream.events` channel the model already declares. Validate in the spike.
3. **Process state.** SpiffWorkflow serialises workflow state to JSON. v1 stores it in the app's own database (SQLite in the tutorial); the as-deployed graph does not hold runtime state.
4. **Licence.** Check SpiffWorkflow's licence (LGPL-3.0 at the time of writing) at adoption; use as an unmodified library dependency is compatible with an Apache-2.0 project.

## Spike Findings

Evidence: [`spikes/adr0007/spike.py`](../../spikes/adr0007/spike.py) (throwaway, run with `.venv/bin/python spikes/adr0007/spike.py [--long]`) and [`tests/test_adr0007_spike.py`](../../tests/test_adr0007_spike.py) (20 tests, part of the CI suite). The spike runs the real `examples/chat-app/chat_process.bpmn` and `routing.dmn` in SpiffWorkflow 3.2.0, wired from `chat-app.trig`. The four open items, in order:

1. **Decision resolution without extensions: holds, using a parser hook. The derived-copy fallback is not needed.** `GraphBoundBusinessRuleTaskParser` subclasses `SpiffWorkflow.bpmn.parser.TaskParser.TaskParser` and is registered for `bpmn:businessRuleTask` in `OVERRIDE_PARSER_CLASSES` on a subclass of `SpiffWorkflow.dmn.parser.BpmnDmnParser.BpmnDmnParser`. Its `get_decision_ref` must be a **classmethod**, because `BpmnDmnParser._find_dependencies` calls it on the class. It resolves the task's fragment IRI through `seam:decidedBy` → `seam:inModel` → `seam:renderPayload`, and the DMN file the parser loads is the graph-resolved path. The task spec is a vendor-neutral `BusinessRuleTask(BusinessRuleTaskMixin, BpmnSpecMixin)`. Both payloads are parsed from disk untouched. Tests show that pointing `seam:decidedBy` elsewhere in the graph changes the binding. A task with a missing hop (no `seam:decidedBy`, or no `seam:renderPayload`) fails with an error that names the task IRI and the missing predicate. Short messages route to `default-provider`. A user message over 4000 characters routes to `long-context-provider`. Since the fallback was not adopted, there is no derived copy for the drift lint (ADR-0006) to check.
2. **Streaming: holds.** Spiff's stock `ServiceTask` returns `None` from its run hook, which leaves the task `STARTED`. The worker picks up started service tasks, dispatches them by bpmn id, and calls `task.complete()` only when the handler returns. `invoke_llm` publishes each simulated token, in order, to the `comm:Channel` that `stream_complete_event` `seam:publishesTo` (`stream.events`, resolved from the graph). Every token event records the task as still `STARTED`, so the task completes only after the last token. The stream-complete throw event is then published on the same channel. Keeping the stock spec means the worker, not a custom spec, owns completion, which matches this ADR's worker model.
3. **Process state: holds.** After `route_to_provider`, `BpmnWorkflowSerializer` serialises the workflow to JSON, which is stored in a stdlib SQLite table `workflow_state(instance_id TEXT PRIMARY KEY, state TEXT)`. The in-memory workflow is dropped, restored from that row in a fresh driver with no parser, and run to the end event. The final data matches an uninterrupted run. Spiff 3.2's `DEFAULT_CONFIG` needs two extra converters: `BaseBusinessRuleTaskConverter` for the business-rule spec, and `BpmnTaskSpecConverter` for the plain bpmn `ServiceTask`. Without the second, serialisation fails with "ServiceTask is not JSON serializable". The S03 worker must register both.
4. **Licence: compatible.** `pip show SpiffWorkflow` reports Version 3.2.0, License `lGPLv3`, author Sartography, classifier "OSI Approved :: GNU Library or Lesser General Public License (LGPL)". The project uses it as an unmodified library dependency (`SpiffWorkflow>=3.0` in `requirements-dev.txt`), and that is compatible with an Apache-2.0 project. Re-check if we ever vendor or patch it.

### Payload edits

- `chat_process.bpmn`: `isExecutable="false"` → `isExecutable="true"`, the standard attribute sanctioned by rule 3. This is the only edit.
- `routing.dmn`: none. Its `<output>` has no `name`, and Spiff 3.2 falls back to the `label` (`Provider`). Spiff also handles the FEEL `-` wildcard natively as "no input specification".
- No vendor namespace (`camunda`, `spiffworkflow`, `zeebe`) appears in either payload. A test pins this, and another checks that the file bytes are identical before and after a run.

### Vocabulary gaps for S02

- **Decision-id join.** `:routing_decision` is not a fragment IRI of `routing.dmn`, so the worker joins on the IRI's local name (`routing_decision`) and checks that the DMN declares that id. This is a convention, not a graph fact. S02 should mint the decision as a fragment IRI of the payload, as BPMN task IRIs already are, or add a `seam:payloadElement` link.
- **DMN input binding.** The DMN inputs `message_role` and `message_length` have no graph binding to `MessageShape` paths. The spike's `persist_user_msg` handler derives them by hand. S02 needs a way to bind a decision input to a shape path or expression.
- **DMN output key.** The result key is the output label (`Provider`) because the output has no `name`. Either the vocabulary records which output feeds the process variable, or the payload adds the standard `name` attribute.
- **Message reference.** `stream_complete_event`'s `messageEventDefinition` has no `messageRef`, so Spiff names the event after the element ("Stream Complete"). The link to the channel exists only in the graph (`seam:publishesTo`).
- **Implementation binding.** Service-task handlers are keyed on bpmn id and only cross-checked against `seam:invokes` / `seam:fires`. The graph says *what* a task invokes, but not which runtime implementation serves that operation. The S03 worker needs that binding.

*Follow-up (M004/S02):* all five are closed as [gaps.md](../generation/golden/gaps.md) GAP-23..GAP-27 (`dec:payloadElement`, `dec:input`, `dec:output`, and the message-name and implementation rules in `ontology/proc.ttl`); the process correlation key is GAP-22 (`proc:correlationKey`).

## Consequences

- **Positive:** The BPMN and DMN the viewer shows are the code that runs. Editing the diagram changes behaviour without regenerating anything.
- **Positive:** Generated code shrinks to declarations — templates, routes, compose — which are easy to diff, test and regenerate.
- **Positive:** Validation, lifecycle and authorization are enforced in one place, the worker, which is the choke point the execution-boundary decision already designed.
- **Positive:** The canned cross-layer queries describe the running system, not just the design, because the runtime reads the same graph.
- **Negative:** A runtime dependency on SpiffWorkflow, and on the graph being shipped with the app: the compose generator must mount the model into the app container.
- **Negative:** Two places to debug — generated code and engine state — instead of one. The model hash in rule 2 and engine-state inspection in the viewer (post-v1) mitigate this.
- **Negative:** The worker becomes real code on the critical path of M3 rather than a stub.
- **Follow-up:** The golden-output dry run (backlog item G2) should be written against this strategy: the hand-written FastAPI module it produces is thin handlers plus runtime calls, and its gap list feeds the vocabulary before the generators are built.
