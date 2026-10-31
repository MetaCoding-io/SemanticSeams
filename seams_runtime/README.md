# seams_runtime

A generic, graph-literate worker for seams models ([ADR-0007](../docs/adr/0007-execution-strategy.md), D013).
It loads a seams TriG model and executes its BPMN processes and DMN decisions in
SpiffWorkflow. It also validates payloads against SHACL shapes, guards lifecycle
transitions and enforces `seam:governedBy` policies. Every dispatch decision comes from
graph facts. No handler is keyed on a bpmn id.

Install: `uv sync --all-packages` at the repository root (a uv workspace; this member's
dependencies are in `seams_runtime/pyproject.toml`). The runtime image installs the same
locked versions from `uv.lock`.

## Version

`seams_runtime.__version__` (in `seams_runtime/__init__.py`) is the runtime's version.
This member is never installed (D033), so `importlib.metadata` cannot read it; keep it
equal to `[project].version` in `seams_runtime/pyproject.toml`
(`tests/test_versions.py` checks). `GET /healthz` reports it as `runtime_version`.

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
| `Runtime.load(trig_path, model_hash=None, *, allow_hash_mismatch=False, db_path=None, authenticator=None, evaluator=None, llm_transport=None, llm_base_url=None, templates_dir=None, store=None, telemetry=None, handlers=None, http_transport=None, http_base_url=None)` | Loads the model (`SEAMS_MODEL`, if set, replaces `trig_path`). Raises `ModelHashMismatch` when `model_hash` differs from the model on disk (TriG plus every `seam:renderPayload`), unless the mismatch is allowed. Resolves every invoked operation's implementation and imports the Python handlers (see [Operation implementations](#operation-implementations)); `runtime.implementations` maps each operation IRI to `(Implementation or None, callable or None)`. Resolves every lifted error boundary against the BPMN XML (see [Error boundaries](#error-boundaries)); `runtime.boundaries` maps `(task IRI, errorCode)` to its `seams.ErrorBoundary`. Then opens the store the model declares (see [Store selection](#store-selection)) and keeps the resolved `StorePlan` as `runtime.store_plan`. `store=` injects a backend instead (the plan is still resolved, and a kind that differs from the declared one logs a WARNING). `telemetry=` injects a `Telemetry` (tests use one on a local `TracerProvider`); by default `tracer_from_env()` builds it, see [Tracing](#tracing-opentelemetry). |
| `runtime.policy(":user_send_policy")` | A FastAPI dependency. It authenticates the request and evaluates the ODRL policy, answering 401 (no identity) or 403 (denied) with `PolicyDenied.to_dict()`. |
| `runtime.validate(":MessageShape", payload)` | Closed-world SHACL validation. Returns the normalised dict or raises `ContractViolation` (422). In form input an empty field counts as absent. |
| `await runtime.start_process(":send_message_process", payload, correlation_key=...)` | Re-validates the payload against the `seam:acceptsShape` of the operation that the process's triggering event `seam:submitsTo`, checkpoints a new instance and runs the worker as an asyncio task. Returns an `Instance` at once. `await instance.wait()` returns the result dict: status, lifecycle, history, variables, entities, trace and error. |
| `await runtime.start_subscribed(":payout_process", correlation_key, current, status)` | Starts a channel-started process ([ADR-0010](../docs/adr/0010-channel-started-processes.md)): its start event, a `proc:MessageCatchEvent`, `seam:subscribesTo` a channel. The instance gets the correlation key and a copy of `current` (entities by shape IRI, ids kept) and `status` (status by shape IRI). Nothing is re-validated. It is checkpointed before its worker task runs. Rule 6a calls this for you; a process that is not channel-started raises `ResolutionError(process, seam:subscribesTo)`. |
| `await runtime.resume(instance_id)` | Continues a checkpointed instance, for example after a restart. |
| `runtime.write(":ExpenseShape", payload)` | For an operation that triggers no process (D026): validates the payload like `validate`, sets the initial lifecycle status when the shape has `seam:lifecycle` (unless the payload names one), stores it as a new entity with a fresh uuid4 id and no correlation key (a shape with an `:id` path gets that id there before validation, replacing any the payload sent, so a required `:id` does not reject a form), and returns the stored row, the same form `query` returns. A `ContractViolation` (422) stores nothing. |
| `runtime.problem(operation, error)` | The `application/problem+json` response for an `OperationError` raised while serving `operation` (ADR-0013); a generated route module's `problem_handler` calls it. `contracts.problem_body` builds the body: `title` from the status's `rdfs:label`, `status` from its `hydra:statusCode`, then `detail` and the error's extension members, validated (closed-world, as `validate`) against the status's `seam:returnsShape`. The response has that status code. A code the operation does not declare (`ResolutionError(operation, comm:errorCode)`), a route with no declared errors (`operation` None), or a body that violates the error shape (`ContractViolation` whose `operation` is the status) is a server fault: 500 with `{"detail": fault.to_dict()}`, logged at ERROR. |
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
`OperationError(code, detail=None, **extensions)` is not a model fault: code serving an
operation raises it for one of the operation's declared `comm:errorCode`s (ADR-0013).
`title` and `status` come from the model and cannot be passed (`ValueError`). Raised
while a generated route runs, the module's `problem_handler` answers it with
`runtime.problem`. Raised by a Python handler while the worker runs a process, it is
routed to an error boundary (see [Error boundaries](#error-boundaries)).

`ModelGraph`, `model_hash` and `ResolutionError` come from the `seams` library
([packages/seams](../packages/seams/README.md), D034) and are re-exported here, as are
the namespaces and resolver results in `seams_runtime.model`. `RuntimeModelError` is an
alias of `seams.SeamsError`, so that one handler and the worker's `isinstance` checks
also catch every `ResolutionError` a resolver raises.

`ModelGraph` is a facade whose resolvers delegate to the seams views
(`model.processes`, `operations`, `channels`, `lifecycles`, `policies`, `interfaces`,
`architecture`, `shapes` and `decisions`, D036). The worker, runtime, fragment renderer,
lifecycle guard and policy hook ask it, or the view elements it hands back
(`task_element`, `shape`, `page`, `component`), and never read raw triples.

## Verification harness

`seams_runtime.verify` is what the `tests` generator's output runs on
([ADR-0014](../docs/adr/0014-scenarios-and-derived-tests.md)). The generated files
hold the model's data and call these, so they stay thin:

| Call | What it does |
|---|---|
| `serve(model, routes, templates, db)` | A context manager giving `(TestClient, Runtime)` for the host app (`host.build_app`) of the route module `routes`, with `SEAMS_STORE_OVERRIDE=sqlite` on `db` and no dev user or seed; it restores the environment on exit. |
| `run_scenario(client, runtime, scenario, timeout=10.0)` | Sends the `Scenario`'s start `Request` as its party, then each `Step`'s request after checking the step's task is open for the scenario's key, waiting after each until the instance is waiting, complete or failed. Returns a `Run` (`status`, `error`, the `entity_shape` entity's stored `state` label, and `reached`, the trace's element IRIs). A non-200 answer, a task that is not open, a path variable other than the correlation key, or a run that does not settle raises `ScenarioError` (an `AssertionError`) naming the scenario and step. |
| `attempt(client, runtime, target, party, timeout=10.0)` | Reaches a `Target` (a permission's target): runs its `Scenario`'s start and the steps before step `at` (`at=0`: the start itself is the target) and checks the target step's task is open, or, with no scenario, sends `request` at once with every path variable set to `key`. Then sends the target request as `party` (None: no identity headers). Returns an `Attempt`: HTTP `status`, the JSON `detail` (the `PolicyDenied` problem on 401/403), the body `text`, and `unchanged`, whether every instance's status and every open task are as before the request. A 200 is settled first. |
| `identity(party)` | The headers a party acts with: its local name as `X-Forwarded-User` and as its one `X-Forwarded-Groups` role, which `RoleEvaluator` admits for a permission assigned to it. |
| `load_model(path, expected_hash)` | The `ModelGraph`, or `ModelHashMismatch` (an `AssertionError`, "regenerate") when the model no longer hashes to the hash the generated file embeds. |
| `decide(engine, decision, inputs)` | `Engine.decide`: the decision's DMN table evaluated on `inputs` (field local name to lexical value) outside any process, with the same input typing (`evaluate_inputs`) and the same Spiff DMN engine a business-rule task uses. Returns `{DMN output name: value}`. |
| `value(lexical, datatype)` | The Python value of a literal, to compare an expected output with. |
| `shape_conforms(model, shape, node)` | `(conforms, report text)`: pyshacl on the node's description against the shape's description with an added `sh:targetNode`, so no other shape takes part. |

## Store

`seams_runtime.store` holds process state, entities and open user tasks in three
tables: `workflow_state`, `entities` and `user_tasks`. `Store` is a `typing.Protocol`
(runtime-checkable) with two backends, both exported from `seams_runtime`:

| Backend | `kind` | `location` | Notes |
|---|---|---|---|
| `SQLiteStore(path, timeout=30.0)` | `"sqlite"` | the file path (`.path` is kept) | Embedded stdlib sqlite3 in WAL mode. `Runtime.load` builds one at `db_path`, `SEAMS_DB` or `./seams.sqlite`. |
| `PostgresStore(url, *, schema=None, connect_timeout=10)` | `"postgresql"` | the URL with its password replaced by `***` (plus ` (schema …)`) | psycopg 3. `data` is jsonb and the timestamps are double precision. A `seq bigserial` column replaces SQLite's rowid as the tie-breaker for ordering and is never returned. Upserts use `ON CONFLICT`. `schema=` creates that schema if needed and sets `search_path` to it on every connection (the tests use one per test). Table creation takes an advisory lock, so runtimes that start together on one database do not collide. |

Both backends return the same rows. `data` comes back decoded with its keys sorted.
`query` applies its data filters in Python on both backends, so the results match. Every
operation opens and closes its own connection, and every statement is parameterised.

| Method | What it does |
|---|---|
| `save_state(instance_id, process, state, *, correlation_key=None, status=None)` | Inserts or replaces the instance's serialized workflow and stamps `updated`. |
| `load_state(instance_id)` | The serialized workflow. A missing instance raises `LookupError` naming the store's `location`. |
| `get_instance(instance_id)` / `list_instances(correlation_key=None)` | Instance metadata without the state: `instance_id`, `process`, `correlation_key`, `status`, `updated`. The list is oldest update first and can filter by correlation key. |
| `put_entity(id, shape, data, *, correlation_key=None, instance_id=None, status=None)` | Inserts or updates an entity and returns the stored row. An update keeps the original `created`. |
| `get_entity(id)` | The row (`id`, `shape`, `correlation_key`, `instance_id`, `data`, `status`, `created`), or `None`. |
| `query(shape, **filters)` | Entities of `shape`, oldest first. `correlation_key=` matches the column; any other filter must equal that top-level key of `data`. |
| `replace_user_tasks(instance_id, rows)` | Makes `rows` the instance's open user tasks. A task that was already open keeps its `created`, and an empty list clears the instance. On PostgreSQL an advisory lock per instance serialises concurrent replacements. |
| `list_user_tasks()` / `get_user_task(task, correlation_key)` | Every open user task, oldest first. `get_user_task` returns the newest open row of the task for that key, or `None`. |

`seams_runtime.store.redact(url)` replaces the password in a URL, in a `password` query
parameter or in a libpq `password=` keyword string with `***`. `location`, `repr()` and
the store's log lines use it. When a connection fails, the error is logged with the
redacted location and psycopg's `OperationalError` propagates. After `connect_timeout`
seconds, an unreachable server fails instead of hanging.

The tests run the store contract (`tests/test_runtime_store.py`) on both backends.
The postgres run needs `SEAMS_TEST_POSTGRES_URL`, for example
`postgresql://postgres:pw@localhost:5433/postgres` against
`docker run -d -e POSTGRES_PASSWORD=pw -p 5433:5432 postgres:16`. Without it the run
skips, unless `SEAMS_REQUIRE_POSTGRES=1` turns the skip into a failure. The runtime
tests (worker, fragments, write, user tasks, channel start) run on both backends
through the same `make_store` fixture.

### Store selection

`Runtime.load` picks the backend from three graph facts (ADR-0011), which
`ModelGraph.store_plan()` in the seams library resolves: the `deploy:storeKind` of the
store container, the runtime container's `deploy:binding` that `deploy:connectsTo` it,
and `seam:storedIn` on the written shapes. In order:

1. `store=` given: that backend is used.
2. `SEAMS_STORE_OVERRIDE=sqlite`: embedded SQLite at `db_path`, `SEAMS_DB` or
   `./seams.sqlite`, with a WARNING naming the declared store. Any other non-empty
   value raises `ValueError`.
3. `deploy:PostgreSQL`: `PostgresStore` at the URL in the environment variable the
   binding's `deploy:key` names (`DB_URL` for the chat app), else in the file
   `<key>_FILE` names (stripped, for Docker secrets). Neither set raises
   `ResolutionError(<runtime container>, deploy:connectsTo)` naming both variables.
4. `deploy:SQLite`, or no store declared: embedded SQLite as in 2, without a warning.

The plan is resolved first in every case, so a model with a missing or unsupported
fact fails at load with `ResolutionError` naming the subject and predicate, even under
the override. The INFO load line names the kind, the declared store, container, key
and the redacted `location`; the URL itself is never logged.

## Host

`python -m seams_runtime.host --routes /app/chat_api.py --host 0.0.0.0 --port 8000`
(or `python -m seams_runtime`) serves a generated route module with uvicorn.
`build_app(routes_path)` imports the module from its path, which runs `Runtime.load`.
It includes `module.router` and adds:

- a `RuntimeModelError` handler that answers `{"detail": exc.to_dict()}` with `exc.http_status`;
- the module's `problem_handler` as the `OperationError` handler, when the module defines one
  (it routes an operation that declares error statuses, ADR-0013): the declared
  `application/problem+json` response from `runtime.problem`;
- `GET /healthz`, which returns `{"status": "ok", "model_hash": ..., "runtime_version": ..., "store": {"kind": ..., "declared": ..., "container": ..., "override": ...}}`.
  `kind` is the backend in use (`sqlite` or `postgresql`), `declared` the local name of
  the declared `deploy:storeKind` (`null` when the model declares none), `container` the
  store container IRI (or `null`), and `override` is true when the backend is not the
  declared kind or an override chose it. The connection string never appears.
  `seams status` compares the reported `model_hash` with the current model's hash
  to say whether a running container is current, behind or ahead;
- every page of `model.interfaces.served_pages()` at its own `ifml:path`, rendered by
  `render_page`. Only correlation-key query parameters such as `?conversation=` reach
  the template. The landmark comes first, then by IRI each other `ifml:ViewContainer`
  with an `ifml:path` that holds no form a user task is `seam:completedOn`. Task-form
  screens are reached through `GET /tasks` instead;
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
3. `seam:invokes op`: the worker dispatches on op's `seam:implementedBy` kind, resolved
   at load (see [Operation implementations](#operation-implementations)). An in-process
   op (the container that `seam:exposes` it also `seam:executes` the process) that
   declares none is served by the runtime itself and needs no call. A
   `comm:LLMCompletion` gets an OpenAI-compatible streaming POST to op's `comm:path`.
   Each delta is published on the channel the invoking task itself `seam:publishesTo`
   (none if it declares none; D046), with the correlation key as scope and the
   `comm:eventName` as event name, and the trace row records `streamed: {channel, event}`
   beside `tokens`. The assembled reply is validated against `seam:returnsShape`. The
   request `model` is the most recent decision's single output. A `comm:PythonHandler`
   calls its handler, and a `comm:HTTPEndpoint` POSTs the entity as JSON; either result
   is validated against `seam:returnsShape` and becomes the current entity of that shape.
   3a. A declared error the invoke raised goes down the error boundary that catches it,
   see [Error boundaries](#error-boundaries); then rules 4 and 5 are skipped.
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
   error is recorded (with `operation` and `implementation`, the kind, when it was
   raised while invoking), the instance's scope is closed on every channel an element of the
   process `seam:publishesTo` (D046), and the instance is marked failed.
   When Spiff wrapped a model error (a `ResolutionError` raised inside a business-rule
   task arrives as a `WorkflowTaskException`), the model error is the one recorded.
8. After each element, the workflow is checkpointed into the store (SQLite or
   PostgreSQL, whichever `Runtime.load` selected). The checkpoint also
   replaces the instance's rows in the `user_tasks` table with its open user tasks, so
   the rows are empty once it completes or fails.
9. User tasks are not run by the loop. The instance ends `waiting` on them, and the log
   names them. `complete_task` finishes one with the person's payload, applying rules
   1 and 3 to 6 to it with the completing identity as the trace row's `by`.

## Operation implementations

[ADR-0012](../docs/adr/0012-operation-implementation.md): an operation says what serves
it with `seam:implementedBy`, an implementation node whose `rdf:type` is its kind. The
worker dispatches on the kind and records it in the trace row as `implementation`:

| `implementation` | When | What runs | Other row keys |
|---|---|---|---|
| `runtime` | an in-process operation with no `seam:implementedBy` | nothing: the runtime serves it (its `seam:acceptsShape` was validated at `start_process`) | none |
| `LLMCompletion` | a remote operation | the streaming completion call of rule 3 | `path`, `model`, `tokens`, `streamed` |
| `PythonHandler` | an in-process operation | the function `comm:handler` names in the handlers package | `handler` (the dotted path) |
| `HTTPEndpoint` | a remote operation | `POST` of the entity as JSON to the bound container at op's `comm:path` | `path` |

The OpenTelemetry element span carries `implementation` and `handler` as
`seams.implementation` and `seams.handler`.

**The handlers package** is a directory with an `__init__.py`: `handlers=` on
`Runtime.load`, else `SEAMS_HANDLERS`, else `handlers/` beside the model file. The runtime
imports it under one package name derived from its absolute path
(`seams_handlers_<hash>`) and resolves every `comm:handler` inside it:
`"notify.notify_manager"` is `notify_manager` in `handlers/notify.py`, and a single
segment is an attribute of `__init__.py`. Every segment must be an identifier, and the
first names a module of the package, so `"os.system"` looks for `handlers/os.py`, never
the standard library. The package is imported only when some operation declares a
`comm:PythonHandler`.

**The handler signature:**

```python
def notify_manager(entity: dict) -> dict: ...        # or: async def
```

The argument is the current entity of op's `seam:acceptsShape` as a plain dict: no `id`,
and no `status` when the shape has a `seam:lifecycle` (statuses are the runtime's). An
`async def` is awaited on the event loop. A plain function runs in a worker thread
(`asyncio.to_thread`), so it cannot block the loop. The returned dict is validated
against op's `seam:returnsShape` and becomes the current entity of that shape, which the
task's `seam:writes` then persists. An operation with no `seam:returnsShape` must return
`None`. A handler never sees the store, the bus, statuses or secrets.

**A worked example** is chapter 9 of the expense tutorial
([docs/tutorials/expenses/09-hand-written-code.md](../docs/tutorials/expenses/09-hand-written-code.md)):
`examples/expenses/chapter-09/handlers/notify.py` is the owned `notify.notify_manager`
behind the approval process's Notify Manager task, and `tests/test_expense_handler.py`
runs it in process.

**HTTP endpoints** use the base URL in the environment variable the executing
container's `deploy:binding` with `deploy:serviceOf` the exposing container names, as the
LLM call does; `http_base_url=` overrides it and `http_transport=` injects an httpx
transport (tests). A 2xx JSON object is validated against `seam:returnsShape`; with no
returnsShape the body is ignored.

**Load-time errors.** `Runtime.load` (and `Runtime(...)`, through
`resolve_implementations`) resolves every operation a process `seam:invokes` before any
store is opened or request served. Each model fault raises `ResolutionError(subject,
predicate)`:

| Case | `subject` | `predicate` |
|---|---|---|
| a remote operation with no `seam:implementedBy`, or several | the operation | `seam:implementedBy` |
| no kind, several, or one outside the three | the implementation | `rdf:type` |
| a `comm:PythonHandler` on a remote operation; an LLM or HTTP kind on an in-process one, or with no `deploy:serviceOf` binding from the executing container | the operation | `seam:exposes` |
| no `comm:handler`, several, or one that is not a dotted path of identifiers | the implementation | `comm:handler` |
| no handlers package, a module (or the package) that fails to import, a missing attribute, or one that is not callable | the implementation | `comm:handler` |

The shapes (`seamsh:ImplementedByShape`, `ImplementationKindShape`, `PythonHandlerShape`,
`RemoteImplementationShape`) catch the declaration faults before the runtime does. The
kind-versus-where agreement and everything about the handlers package (whether it
exists, imports, and holds a callable) are runtime-only: they depend on files outside
the model. An import that fails inside a handler module is reported with the original
exception chained as `__cause__`, so the traceback still points at the line.

**Run-time errors** are not model faults. A handler that raises, or returns `None` for
an operation with a returnsShape, a non-dict, or anything but `None` without one, is a
`HandlerError` (500, with `operation`, `handler`, `reason`). An HTTP call with no base
URL, a connection error or timeout, a non-2xx status, a body that is not JSON or not an
object is an `EndpointError` (502, with `url`, `reason`). A result that fails
`seam:returnsShape` is a `ContractViolation` naming the operation. Each fails the
instance as an `LLMError` does (rule 7), and the recorded error adds `operation` and
`implementation` (the kind).

## Error boundaries

[ADR-0013](../docs/adr/0013-error-shapes-and-boundaries.md): a `bpmn:boundaryEvent`
with an `errorEventDefinition`, attached to a service task that `seam:invokes` an
operation, is lifted as a `proc:ErrorBoundaryEvent` that `seam:catches` one of the
operation's error statuses (`hydra:possibleStatus` with a `comm:errorCode`).

**At load** (`resolve_boundaries`, before the store opens) every process's
`Process.error_boundaries()` joins each lifted boundary to the XML. `runtime.boundaries`
maps `(task IRI, errorCode)` to the `seams.ErrorBoundary`. Each disagreement raises
`ResolutionError` naming the boundary:

| Fault | Predicate |
|---|---|
| an error boundary on an invoking task that is not lifted (the message says whether the operation declares its code) | `seam:catches` |
| a lifted boundary that catches no status, or several | `seam:catches` |
| it catches a status that is not an error of the operation its task invokes | `seam:catches` |
| its `bpmn:error`'s `errorCode` differs from the status's `comm:errorCode` | `seam:catches` |
| it is lifted but attached to a task that invokes nothing, or no error boundary in the XML has its id | `seam:catches` |
| two boundaries on one task catch the same code | `seam:catches` |
| a catch-all (no `errorRef`) on an invoking task | `bpmn:errorEventDefinition` |
| an `errorRef` that names no `bpmn:error`, or a `bpmn:error` without an `errorCode` | `bpmn:errorRef` / `bpmn:errorCode` |
| an `attachedToRef` that names no flow node (subject `<file>#<boundary id>`) | `bpmn:attachedToRef` |

A boundary on a task that invokes nothing is ordinary BPMN and is not checked.

**At run time** a declared error is a Python handler's
`OperationError(code, detail=None, **extensions)` (the `HandlerError`'s cause), or a
non-2xx `application/problem+json` object answer from a `comm:HTTPEndpoint` whose HTTP
status is the `hydra:statusCode` of exactly one of the operation's errors (its `detail`
and members other than `title` and `status` carry over). The worker builds the body with
`contracts.problem_body` and records `error: {code, status, operation}` (`status` is the
`hydra:Status` IRI) in the task's trace row. When a boundary on that task catches the
code:

- the body becomes the current entity of the error shape, so a task on the error path
  can `seam:reads` or `seam:writes` it;
- the row records `boundary` (its IRI); the task's `seam:writes` and `seam:fires` are
  not applied and the task is not completed;
- the engine throws the code from the STARTED task (Spiff never routes an exception
  itself), and the loop runs the READY boundary before any STARTED task. Its row
  records `caught` (the code); running it cancels the task, and the process goes on
  down the boundary's flow. A checkpoint between the throw and the boundary resumes
  at the boundary.

With no boundary, the `HandlerError` or `EndpointError` fails the instance as before,
and the recorded error adds `code` and `status`. A code the operation does not declare
fails it with `ResolutionError(operation, comm:errorCode)` (and `code`), and a body that
violates the error shape with a `ContractViolation` whose `operation` is the status.
Any other exception, or any other non-2xx answer, fails the instance unchanged.

## Environment

| Variable | Meaning |
|---|---|
| `SEAMS_MODEL` | TriG file `load` reads. When set and non-empty it takes precedence over the `trig_path` argument. The generated compose file sets it to the bind-mounted model, for example `/model/chat-app.trig`. |
| `SEAMS_DB` | Embedded SQLite file for workflow state and entities, used when the model declares no store or a `deploy:SQLite` store, or under `SEAMS_STORE_OVERRIDE=sqlite`. The default is `seams.sqlite`. `db_path=` overrides it. |
| `SEAMS_STORE_OVERRIDE` | `sqlite` forces embedded SQLite whatever store the model declares, logging a WARNING; `/healthz` reports `override: true`. Any other non-empty value fails at load. Meant for tests and local runs. |
| `<key>` / `<key>_FILE` | For a `deploy:PostgreSQL` store, the connection URL, or a file holding it. `<key>` is the `deploy:key` of the runtime container's binding that `deploy:connectsTo` the store, for example `DB_URL` / `DB_URL_FILE`. `<key>` wins when both are set. |
| `SEAMS_DEV_USER` | Opt-in static identity for local runs. Without it, the `X-Forwarded-User` header is required (fail closed, D014). |
| `SEAMS_DEV_ROLES` | Comma-separated roles of the `SEAMS_DEV_USER` identity, for example `employee,manager`. Ignored without `SEAMS_DEV_USER`. With the header authenticator, the roles come from the `X-Forwarded-Groups` header instead. |
| `SEAMS_ALLOW_HASH_MISMATCH` | When set to `1`, `load` warns on a hash mismatch instead of refusing the model. |
| `SEAMS_TEMPLATES` | Directory of the generated htmx partials `render_fragment` reads. The default is `./templates`. `templates_dir=` overrides it. |
| `SEAMS_ROUTES` | Route module the host serves when `--routes` is not given. The default is `/app/chat_api.py`. |
| `SEAMS_HANDLERS` | The handlers package directory (ADR-0012). The default is `handlers/` beside the model file. `handlers=` overrides it. |
| `SEAMS_SEED` | Optional seed JSON the host writes into the store on startup. |
| `LLM_GATEWAY_URL` | Base URL of `:llm_gateway`. The name comes from `:chat_api`'s `deploy:binding` with `deploy:serviceOf :llm_gateway`. `llm_base_url=` overrides it (`http_base_url=` for a `comm:HTTPEndpoint`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Turns on OpenTelemetry spans (see [Tracing](#tracing-opentelemetry)). Unset or empty, tracing is off. |
| `OTEL_SERVICE_NAME` | The `service.name` resource of the spans. The default is `seams-runtime`. |

## Tracing (OpenTelemetry)

The runtime can emit OpenTelemetry spans whose attributes are graph element IRIs
(`seams_runtime/telemetry.py`, decision D049). It is off by default: with
`OTEL_EXPORTER_OTLP_ENDPOINT` unset or empty, `tracer_from_env()` returns a no-op
`Telemetry` and nothing imports opentelemetry.

With the endpoint set, the `otel` extra must be installed. In this workspace that is

```sh
uv sync --all-packages --extra otel
```

(the extra pulls in `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http`; a
plain `uv sync --all-packages` removes them again). When the extra is missing, `load`
logs one WARNING (`OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-sdk is not
installed; install the seams_runtime otel extra`) and runs without tracing. Otherwise it
logs an INFO line naming the endpoint and exports in batches over OTLP/HTTP. The exporter
reads the standard `OTEL_EXPORTER_OTLP_*` variables (headers, timeout, a separate
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`). The runtime uses its own `TracerProvider` and
never sets the global one.

| Span | Name | Attributes |
|---|---|---|
| Instance: one per worker run. A resumed instance or a user-task completion is another instance span with the same instance id. | the process's local name, for example `send_message_process` | `seams.process.iri`, `seams.instance.id`, `seams.correlation_key`. A failed instance has status ERROR described by the error type, plus `seams.error.type` and `seams.error.message`. |
| Element: a child of the instance span for each BPMN element, one per trace row | the bpmn id, for example `invoke_llm` | The instance attributes, `seams.element.iri` and `bpmn.id`, and, when the trace row has them, `seams.fires`, `seams.decision`, `seams.invokes`, `seams.container`, `seams.channel` (from `streamed` or `published`), `seams.status` and `seams.by`; for a declared error, `seams.error.code`, `seams.error.status` and `seams.boundary` on the raising task and `seams.caught` on the boundary. An element that raises records the exception and has status ERROR. |

The attributes are read from the finished trace row when the span ends. The trace rows
in the checkpointed workflow stay the record of a run: `seams sequence :event --trace
<instance>` renders them, not the spans.

## Deferred

- ODRL constraints, duties and prohibitions. The default `RoleEvaluator` now checks role
  assignees as well as identity ids, but still only permission presence and assignee. A
  full evaluator can be plugged in as a `PolicyEvaluator`.
- One store per model. A model whose runtime containers connect to different stores fails at load.
