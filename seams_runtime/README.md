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

If `SEAMS_MODEL` is set and non-empty, `load` reads that file instead of `trig_path`,
and logs which path it used and where it came from. The hash check still applies, so a
`SEAMS_MODEL` pointing at a different model raises `ModelHashMismatch` unless the
mismatch is allowed. A missing model file raises `FileNotFoundError` naming the path
(and `SEAMS_MODEL` when that chose it).

| Call | What it does |
|---|---|
| `Runtime.load(trig_path, model_hash=None, *, allow_hash_mismatch=False, db_path=None, authenticator=None, evaluator=None, llm_transport=None, llm_base_url=None, templates_dir=None)` | Loads the model (`SEAMS_MODEL`, if set, replaces `trig_path`). Raises `ModelHashMismatch` when `model_hash` differs from the model on disk (TriG plus every `seam:renderPayload`), unless the mismatch is allowed. |
| `runtime.policy(":user_send_policy")` | A FastAPI dependency. It authenticates the request and evaluates the ODRL policy, answering 401 (no identity) or 403 (denied) with `PolicyDenied.to_dict()`. |
| `runtime.validate(":MessageShape", payload)` | Closed-world SHACL validation. Returns the normalised dict or raises `ContractViolation` (422). In form input an empty field counts as absent. |
| `await runtime.start_process(":send_message_process", payload, correlation_key=...)` | Re-validates the payload against the `seam:acceptsShape` of the operation that the process's triggering event `seam:submitsTo`, checkpoints a new instance and runs the worker as an asyncio task. Returns an `Instance` at once. `await instance.wait()` returns the result dict: status, lifecycle, history, variables, entities, trace and error. |
| `await runtime.start_subscribed(":payout_process", correlation_key, current, status)` | Starts a channel-started process ([ADR-0010](../docs/adr/0010-channel-started-processes.md)): its start event, a `proc:MessageCatchEvent`, `seam:subscribesTo` a channel. The instance gets the correlation key and a copy of `current` (entities by shape IRI, ids kept) and `status` (status by shape IRI). Nothing is re-validated. It is checkpointed before its worker task runs. Rule 6a calls this for you; a process that is not channel-started raises `ResolutionError(process, seam:subscribesTo)`. |
| `await runtime.resume(instance_id)` | Continues a checkpointed instance, for example after a restart. |
| `runtime.write(":ExpenseShape", payload)` | For an operation that triggers no process (D026): validates the payload like `validate`, sets the initial lifecycle status when the shape has `seam:lifecycle` (unless the payload names one), stores it as a new entity with a fresh uuid4 id and no correlation key (a shape with an `:id` path gets that id there before validation, replacing any the payload sent, so a required `:id` does not reject a form), and returns the stored row, the same form `query` returns. A `ContractViolation` (422) stores nothing. |
| `runtime.user_tasks(identity, process=None)` | The open BPMN user tasks `identity` may complete (ADR-0009), oldest first, optionally for one process. Each is a dict: `instance`, `task` (IRI), `bpmn_id`, `label`, `process`, `correlation_key`, `form` (the `seam:completedOn` form), `partial` (its htmx partial name), `screen` (the `ifml:path` of the page that contains the form) and `entity` (the newest stored entity of the task's `seam:reads` shape for that key, flattened). A task is listed only when every `seam:governedBy` policy of the task permits the identity, evaluated with the task IRI as the `odrl:target`. An ungoverned task is open to any identity. `None` raises `PolicyDenied` (401). |
| `await runtime.complete_task(task, payload, correlation_key, identity)` | Completes the open user task of the instance with that correlation key. In order: the task's policies (401 for no identity, 403 denied), the open `user_tasks` row (`TaskNotOpen`, 409), and the payload against the task's output shape, which is the form's `seam:writes` (`ContractViolation`, 422). A failure at any step changes nothing. The worker then makes the payload the current entity of that shape, merges it into the task data so gateways can route on it, applies the task's `seam:fires`, `seam:invokes` and `seam:writes` with `"by": identity.id` on its trace row, and continues the instance. Returns the `Instance`. Concurrent completions of one task complete it once. |
| `PolicyHook(model, authenticator=None, evaluator=None)` | The policy hook behind `runtime.policy` and `runtime.task_policy`. The default authenticator is `HeaderAuthenticator`: the proxy-set `X-Forwarded-User` header is the identity id, and the comma-separated `X-Forwarded-Groups` header gives its roles (stripped, empty items ignored, none when absent). The default evaluator is `RoleEvaluator` (D028): a permission must target the operation with an `odrl:action`; no assignee or an `odrl:PartyCollection` admits any identity, and a specific party admits an identity whose id or any role equals the party IRI or its local name. A denial names the identity, its roles and the assignees. `PresenceEvaluator`, the id-only v1 evaluator, is still exported. |
| `runtime.task_policy(task)` | A FastAPI dependency for a completion route. It authenticates the request (401) and checks the task's policies (403), answering with `PolicyDenied.to_dict()`, and yields the `Identity`. |
| `runtime.query(":MessageShape", conversation="c1")` | Persisted entities of a shape. A filter named after a `proc:correlationKey` parameter label matches the correlation key. |
| `runtime.subscribe(":stream_events", scope)` | An async iterator of SSE frames for one channel scope: the backlog first, then live frames. |
| `runtime.render_fragment("message_thread.html", messages, **params)` | An `HTMLResponse` rendering an htmx partial from the templates dir (D017). The name is a `seam:rendersComponent` target's local name, or that plus `_item` for the one-item partial. It is resolved against the graph before any file is read, and an unknown name raises `ResolutionError`. The component's `seam:reads` shape `:MessageShape` binds `messages` (a list) or `message` (one item). Store entity rows are flattened to their payload plus `id` and `status`. A component with `seam:visibleWhen` also gets `message_state`: the last item's status, else the lifecycle's initial state label. Extra keyword params are merged last. |
| `runtime.render_page(page=None, **params)` | An `HTMLResponse` rendering `<page local name>.html` (default: the single `ifml:ViewContainer` with `ifml:isLandmark true`). Each `ifml:contains` component that `seam:reads` a shape is bound by the `render_fragment` rule (`conversations`, `messages`, `message_state`). A component whose `ifml:hasParameter` labels include a `proc:correlationKey` label reads only that key's entities. The key comes from `params` (for example `conversation="c1"`), or else it is the smallest id among the unscoped components' entities. It is also bound under its label. `runtime.page_context(...)` returns the dict without rendering. |

Errors (`seams_runtime.errors`, plus `LLMError` in `llm.py`) carry `http_status` and
serialise with `to_dict()`. `TaskNotOpen` (409, with `task` and `correlation_key`)
means no open user task matches: it was already completed, never reached, or the
correlation key is unknown. A generated app maps `RuntimeModelError` to a JSON response
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
- each of `ModelGraph.secondary_pages()` at its own `ifml:path`, rendered the same way.
  A secondary page is an `ifml:ViewContainer` with an `ifml:path` that is not the
  landmark and holds no form a user task is `seam:completedOn`. Task-form screens are
  reached through `GET /tasks` instead;
- a startup seed from the JSON file named by `SEAMS_SEED`, in the form
  `{"<shape curie>": [{"id": ..., ...payload}]}`. Every item passes `runtime.validate`
  before any is written. A field named after a correlation-key label that is not a
  `sh:path` of the shape becomes the correlation key. Ids that are already stored are
  skipped, so seeding is idempotent. A bad item fails startup with a `ContractViolation`
  whose `focus` is `<file>#<shape>[<index>] id '<id>'`.

- `GET /tasks`, the task inbox (ADR-0009). It authenticates the request with
  `runtime.hook.authenticate` and lists `runtime.user_tasks(identity)`: the open user
  tasks the identity may complete, oldest first. Each task is rendered with its
  generated form partial (the row's `partial`, for example `approve_form.html`, given
  `task=row`), so the form posts to the generated completion route. A request that
  accepts `application/json` gets `{"identity": ..., "tasks": [...rows]}` instead. With
  no identity the answer is a 401 `PolicyDenied`. A model without user tasks gets an
  empty inbox.

host.py names no model term. The page, its path and its blocks, and each task's form
partial, all come from the graph.

## Dispatch rules

The worker (`worker.py`) applies these rules to each BPMN element:

1. `seam:fires T`: before dispatch, `LifecycleGuard.check` verifies that T leaves the
   current status of the shape whose `seam:lifecycle` owns T.
2. Business-rule tasks: the dec:input variables are filled from the current entity of the
   shape the task `seam:reads`. Validated form values are strings, so an input whose DMN
   `inputExpression` has `typeRef="number"` becomes a `Decimal` first and compares
   numerically with entries such as `<= 100`; a value that is not a number fails with a
   `ResolutionError` naming the decision. After the run, each dec:output value is copied
   into its `dec:processVariable`, which a following `bpmn:exclusiveGateway` can test in
   a condition such as `route == "manager"` (Spiff's Python expression engine). A table
   that matches no rule produces no output and fails with a `ResolutionError`; an output
   no outgoing condition accepts fails the instance at the gateway. The expense
   tutorial's chapter 5 (`examples/expenses/chapter-05/`) routes this way.
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
   6a. Then every channel-started process subscribed to that channel starts
   ([ADR-0010](../docs/adr/0010-channel-started-processes.md)): its start event is a
   `proc:MessageCatchEvent` that `seam:subscribesTo` the channel. It gets the
   publisher's correlation key and a copy of its current entities and statuses, is
   checkpointed, and runs as its own asyncio task. The publisher's trace row records
   `started: [{process, instance}]`. A subscriber that fails, or cannot start (recorded
   in that row with `instance: null` and its `error`), never fails the publisher.
7. Exceptions: the lifecycle's `"error"` exit is applied (status becomes `failed`), the
   error is recorded, the channel scope is closed and the instance is marked failed.
   When Spiff wrapped a model error (a `ResolutionError` raised inside a business-rule
   task arrives as a `WorkflowTaskException`), the model error is the one recorded.
8. After each element, the workflow is checkpointed into SQLite. The checkpoint also
   replaces the instance's rows in the `user_tasks` table with its open user tasks, so
   the rows are empty once it completes or fails.
9. User tasks are not run by the loop. The instance ends `waiting` on them, and the log
   names them. `complete_task` finishes one with the person's payload, applying rules
   1 and 3 to 6 to it with the completing identity as the trace row's `by`.

## Environment

| Variable | Meaning |
|---|---|
| `SEAMS_MODEL` | TriG file `load` reads. When set and non-empty it takes precedence over the `trig_path` argument. The generated compose file sets it to the bind-mounted model, for example `/model/chat-app.trig`. |
| `SEAMS_DB` | SQLite file for workflow state and entities. The default is `seams.sqlite`. `db_path=` overrides it. |
| `SEAMS_DEV_USER` | Opt-in static identity for local runs. Without it, the `X-Forwarded-User` header is required (fail closed, D014). |
| `SEAMS_DEV_ROLES` | Comma-separated roles of the `SEAMS_DEV_USER` identity, for example `employee,manager`. Ignored without `SEAMS_DEV_USER`. With the header authenticator, the roles come from the `X-Forwarded-Groups` header instead. |
| `SEAMS_ALLOW_HASH_MISMATCH` | When set to `1`, `load` warns on a hash mismatch instead of refusing the model. |
| `SEAMS_TEMPLATES` | Directory of the generated htmx partials `render_fragment` reads. The default is `./templates`. `templates_dir=` overrides it. |
| `SEAMS_ROUTES` | Route module the host serves when `--routes` is not given. The default is `/app/chat_api.py`. |
| `SEAMS_SEED` | Optional seed JSON the host writes into the store on startup. |
| `LLM_GATEWAY_URL` | Base URL of `:llm_gateway`. The name comes from `:chat_api`'s `deploy:binding` with `deploy:serviceOf :llm_gateway`. `llm_base_url=` overrides it. |

## Deferred

- ODRL constraints, duties and prohibitions. The default `RoleEvaluator` now checks role
  assignees as well as identity ids, but still only permission presence and assignee. A
  full evaluator can be plugged in as a `PolicyEvaluator`.
- Postgres. The v1 store is stdlib sqlite3.
