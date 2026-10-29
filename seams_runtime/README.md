# seams_runtime

A generic, graph-literate worker for seams models ([ADR-0007](../docs/adr/0007-execution-strategy.md), D013).
It loads a seams TriG model and executes its BPMN processes and DMN decisions in
SpiffWorkflow. It also validates payloads against SHACL shapes, guards lifecycle
transitions and enforces `seam:governedBy` policies. Every dispatch decision comes from
graph facts. No handler is keyed on a bpmn id.

Install: `pip install -r seams_runtime/requirements.txt`.

## API

```python
from seams_runtime import Runtime

runtime = Runtime.load("/model/chat-app.trig", model_hash=MODEL_HASH)
```

| Call | What it does |
|---|---|
| `Runtime.load(trig_path, model_hash=None, *, allow_hash_mismatch=False, db_path=None, authenticator=None, evaluator=None, llm_transport=None, llm_base_url=None)` | Loads the model. Raises `ModelHashMismatch` when `model_hash` differs from the model on disk (TriG plus every `seam:renderPayload`), unless the mismatch is allowed. |
| `runtime.policy(":user_send_policy")` | A FastAPI dependency. It authenticates the request and evaluates the ODRL policy, answering 401 (no identity) or 403 (denied) with `PolicyDenied.to_dict()`. |
| `runtime.validate(":MessageShape", payload)` | Closed-world SHACL validation. Returns the normalised dict or raises `ContractViolation` (422). In form input an empty field counts as absent. |
| `await runtime.start_process(":send_message_process", payload, correlation_key=...)` | Re-validates the payload against the `seam:acceptsShape` of the operation that the process's triggering event `seam:submitsTo`, checkpoints a new instance and runs the worker as an asyncio task. Returns an `Instance` at once. `await instance.wait()` returns the result dict: status, lifecycle, history, variables, entities, trace and error. |
| `await runtime.resume(instance_id)` | Continues a checkpointed instance, for example after a restart. |
| `runtime.query(":MessageShape", conversation="c1")` | Persisted entities of a shape. A filter named after a `proc:correlationKey` parameter label matches the correlation key. |
| `runtime.subscribe(":stream_events", scope)` | An async iterator of SSE frames for one channel scope: the backlog first, then live frames. |

Errors (`seams_runtime.errors`, plus `LLMError` in `llm.py`) carry `http_status` and
serialise with `to_dict()`. A generated app maps `RuntimeModelError` to a JSON response
with one exception handler.

## Dispatch rules

The worker (`worker.py`) applies these rules to each BPMN element:

1. `seam:fires T`: before dispatch, `LifecycleGuard.check` verifies that T leaves the
   current status of the shape whose `seam:lifecycle` owns T.
2. Business-rule tasks: the dec:input variables are filled from the current entity of the
   shape the task `seam:reads`. After the run, the dec:output values become process
   variables.
3. `seam:invokes op`: when the container that `seam:exposes` op also `seam:executes` the
   process, the call is in-process and needs no remote call. Any other container gets an
   OpenAI-compatible streaming POST to op's `comm:path`. Each delta is published on the
   process's `seam:publishesTo` channel, with the correlation key as scope and the
   `comm:eventName` as event name. The assembled reply is validated against
   `seam:returnsShape`. The request `model` is the most recent decision's single output.
4. `seam:writes Shape`: persists the current entity of that shape.
5. After dispatch: the fired transition is applied and its status is persisted.
6. Message throw events publish a completion event named after the channel's
   `rdfs:label` (GAP-26).
7. Exceptions: the lifecycle's `"error"` exit is applied (status becomes `failed`), the
   error is recorded, the channel scope is closed and the instance is marked failed.
8. After each element, the workflow is checkpointed into SQLite.

## Environment

| Variable | Meaning |
|---|---|
| `SEAMS_DB` | SQLite file for workflow state and entities. The default is `seams.sqlite`. `db_path=` overrides it. |
| `SEAMS_DEV_USER` | Opt-in static identity for local runs. Without it, the `X-Forwarded-User` header is required (fail closed, D014). |
| `SEAMS_ALLOW_HASH_MISMATCH` | When set to `1`, `load` warns on a hash mismatch instead of refusing the model. |
| `LLM_GATEWAY_URL` | Base URL of `:llm_gateway`. The name comes from `:chat_api`'s `deploy:binding` with `deploy:serviceOf :llm_gateway`. `llm_base_url=` overrides it. |

## Deferred

- ODRL constraints, duties and prohibitions. The v1 `PresenceEvaluator` checks permission
  presence and assignee only. A full evaluator can be plugged in as a `PolicyEvaluator`.
- Postgres. The v1 store is stdlib sqlite3.
- `render_fragment`, which the golden `chat_api.py` calls. It comes with the template
  generator in M004/S04 and S05.
