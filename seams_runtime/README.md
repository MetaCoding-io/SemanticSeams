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
| `Runtime.load(trig_path, model_hash=None, *, allow_hash_mismatch=False, db_path=None, authenticator=None, evaluator=None, llm_transport=None, llm_base_url=None, templates_dir=None)` | Loads the model. Raises `ModelHashMismatch` when `model_hash` differs from the model on disk (TriG plus every `seam:renderPayload`), unless the mismatch is allowed. |
| `runtime.policy(":user_send_policy")` | A FastAPI dependency. It authenticates the request and evaluates the ODRL policy, answering 401 (no identity) or 403 (denied) with `PolicyDenied.to_dict()`. |
| `runtime.validate(":MessageShape", payload)` | Closed-world SHACL validation. Returns the normalised dict or raises `ContractViolation` (422). In form input an empty field counts as absent. |
| `await runtime.start_process(":send_message_process", payload, correlation_key=...)` | Re-validates the payload against the `seam:acceptsShape` of the operation that the process's triggering event `seam:submitsTo`, checkpoints a new instance and runs the worker as an asyncio task. Returns an `Instance` at once. `await instance.wait()` returns the result dict: status, lifecycle, history, variables, entities, trace and error. |
| `await runtime.resume(instance_id)` | Continues a checkpointed instance, for example after a restart. |
| `runtime.query(":MessageShape", conversation="c1")` | Persisted entities of a shape. A filter named after a `proc:correlationKey` parameter label matches the correlation key. |
| `runtime.subscribe(":stream_events", scope)` | An async iterator of SSE frames for one channel scope: the backlog first, then live frames. |
| `runtime.render_fragment("message_thread.html", messages, **params)` | An `HTMLResponse` rendering an htmx partial from the templates dir (D017). The name is a `seam:rendersComponent` target's local name, or that plus `_item` for the one-item partial. It is resolved against the graph before any file is read, and an unknown name raises `ResolutionError`. The component's `seam:reads` shape `:MessageShape` binds `messages` (a list) or `message` (one item). Store entity rows are flattened to their payload plus `id` and `status`. A component with `seam:visibleWhen` also gets `message_state`: the last item's status, else the lifecycle's initial state label. Extra keyword params are merged last. |
| `runtime.render_page(page=None, **params)` | An `HTMLResponse` rendering `<page local name>.html` (default: the single `ifml:ViewContainer` with `ifml:isLandmark true`). Each `ifml:contains` component that `seam:reads` a shape is bound by the `render_fragment` rule (`conversations`, `messages`, `message_state`). A component whose `ifml:hasParameter` labels include a `proc:correlationKey` label reads only that key's entities. The key comes from `params` (for example `conversation="c1"`), or else it is the smallest id among the unscoped components' entities. It is also bound under its label. `runtime.page_context(...)` returns the dict without rendering. |

Errors (`seams_runtime.errors`, plus `LLMError` in `llm.py`) carry `http_status` and
serialise with `to_dict()`. A generated app maps `RuntimeModelError` to a JSON response
with one exception handler.

## Host

`python -m seams_runtime.host --routes /app/chat_api.py --host 0.0.0.0 --port 8000`
(or `python -m seams_runtime`) serves a generated route module with uvicorn.
`build_app(routes_path)` imports the module from its path, which runs `Runtime.load`.
It includes `module.router` and adds:

- a `RuntimeModelError` handler that answers `{"detail": exc.to_dict()}` with `exc.http_status`;
- `GET /healthz`, which returns `{"status": "ok", "model_hash": ...}`;
- the landmark page at its `ifml:path`, rendered by `render_page`. Only correlation-key
  query parameters such as `?conversation=` reach the template;
- a startup seed from the JSON file named by `SEAMS_SEED`, in the form
  `{"<shape curie>": [{"id": ..., ...payload}]}`. Every item passes `runtime.validate`
  before any is written. A field named after a correlation-key label that is not a
  `sh:path` of the shape becomes the correlation key. Ids that are already stored are
  skipped, so seeding is idempotent. A bad item fails startup with a `ContractViolation`
  whose `focus` is `<file>#<shape>[<index>] id '<id>'`.

host.py names no model term. The page, its path and its blocks all come from the graph.

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
| `SEAMS_TEMPLATES` | Directory of the generated htmx partials `render_fragment` reads. The default is `./templates`. `templates_dir=` overrides it. |
| `SEAMS_ROUTES` | Route module the host serves when `--routes` is not given. The default is `/app/chat_api.py`. |
| `SEAMS_SEED` | Optional seed JSON the host writes into the store on startup. |
| `LLM_GATEWAY_URL` | Base URL of `:llm_gateway`. The name comes from `:chat_api`'s `deploy:binding` with `deploy:serviceOf :llm_gateway`. `llm_base_url=` overrides it. |

## Deferred

- ODRL constraints, duties and prohibitions. The v1 `PresenceEvaluator` checks permission
  presence and assignee only. A full evaluator can be plugged in as a `PolicyEvaluator`.
- Postgres. The v1 store is stdlib sqlite3.
