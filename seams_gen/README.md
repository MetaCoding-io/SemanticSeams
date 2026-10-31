# seams_gen

Generators that turn a seams model into code (M004, D016). A generator reads graph
facts only: it holds no chat-app names and no domain logic, sorts every collection
explicitly, and stamps its output with the model hash. Its output must equal the
marker-stripped golden in [`docs/generation/golden/`](../docs/generation/golden/README.md)
byte for byte. The generators read the model only through the typed views of the
[`seams`](../packages/seams/README.md) library (`model.architecture`, `model.interfaces`,
`model.operations` and the rest), with `model.compact` for curies, never raw triples (D036);
none of them imports `seams_runtime`. `seams_gen/_views.py` is the one bridge: it turns a
view's `ResolutionError` into a `GeneratorError` naming the same subject and predicate.
A custom generator reads the model through `seams` the same way; the
[Write your own generator](../docs/guide/write-your-own-generator.md) guide builds one.

## Version

`seams_gen.__version__` (in `seams_gen/__init__.py`) is the generators' version, which
`seams generate` records per output in `seams.lock`. This member is never installed
(D033), so `importlib.metadata` cannot read it; keep it equal to `[project].version` in
`seams_gen/pyproject.toml` (`tests/test_versions.py` checks).

## Usage

Install with `uv sync --all-packages` at the repository root, then run the commands below
in the activated `.venv` (or prefix them with `uv run`).

```
python -m seams_gen htmx examples/chat-app/chat-app.trig --out build/
# -> build/chat_page.html, build/conversation_list.html, build/message_thread.html,
#    build/message_thread_item.html   (each path written is printed on stdout, sorted)
python -m seams_gen fastapi examples/chat-app/chat-app.trig --out build/
# -> build/chat_api.py
python -m seams_gen compose examples/chat-app/chat-app.trig --out .
# -> ./compose.yaml   (bind-mount sources are relative to --out, so `docker compose up` works there)
```

### From a project file

`seams generate` runs every generator an app's `seams.toml` names, each into its own
output directory, and writes nothing unless all of them succeed:

```
seams generate --project examples/chat-app
```

The project file and the command are in
[packages/seams-cli/README.md](../packages/seams-cli/README.md) and
[docs/reference/seams-cli.md](../docs/reference/seams-cli.md).

**Committed outputs.** The chat-app outputs are committed at stable paths for the
docker images and `docker compose up`: `examples/chat-app/generated/chat_api.py`,
`examples/chat-app/generated/templates/*.html` and the root `compose.yaml`
([generated/README.md](../examples/chat-app/generated/README.md) lists the regenerate
command). `tests/test_generated_outputs_current.py` regenerates each and requires the
same file set, byte for byte, failing with a diff and the command to run; CI also runs
`seams check` for the chat app and each expenses chapter (through
`.github/actions/seams-check`) and fails on any missing, stale, hand-edited or orphaned
output or an out-of-date `seams.lock`.

```python
from seams_gen import generate_page, generate_fragments, fragment_for, extract_page, GeneratorError
html = generate_page("examples/chat-app/chat-app.trig")
partials = generate_fragments("examples/chat-app/chat-app.trig")  # {file name: text}
from seams_gen import generate_routes, extract_routes, render_routes
routes_py = generate_routes("examples/chat-app/chat-app.trig")    # chat_api.py text
from seams_gen import generate_compose, extract_compose, render_compose
compose_yaml = generate_compose("examples/chat-app/chat-app.trig", base_dir=".")
```

| Generator | Writes | From |
|---|---|---|
| `htmx` | `<out>/<page local name>.html`, a Jinja2/htmx template (UTF-8, `\n` newlines) | the landmark `ifml:ViewContainer` and the seam, shape, comm and lifecycle facts it touches |
| `htmx` (fragments) | `<out>/<component>.html` and `<out>/<component>_item.html` partials, one per name the fragment rule gives | each operation the presenting container `seam:consumes` that `seam:rendersComponent` a page component |
| `htmx` (task forms) | `<out>/<form local name>.html`, one partial per form a user task is completed on, plus the partials its completion route renders on the form's screen | each `ifml:Form` a `proc:UserTask` `seam:completedOn` (ADR-0009, D027) |
| `htmx` (other served pages) | `<out>/<page local name>.html` and its partials, built like the landmark page but without task forms | each page of `model.interfaces.served_pages()` after the landmark: an `ifml:ViewContainer` with an `ifml:path` that is not the landmark and holds no task form, from any `ifml:InteractionModel` its container `seam:presents`. The expense tutorial's `:payouts_page` (chapter 8) is one. A partial two pages would render differently is a `GeneratorError` |
| `fastapi` | `<out>/<container local name>.py`, a thin FastAPI route module | the one serving `arch:Container` (it `seam:executes` a `proc:Process`, or `seam:exposes` an operation an `ifml:Event` `seam:submitsTo`), and what it `seam:exposes` |
| `compose` | `<out>/compose.yaml`, a docker compose file whose bind-mount sources are relative to `<out>` | the `arch:Container`s of the one `arch:System`, their `deploy:` facts, `seam:deployedTo` and the serving-container rule |

Each generator is one subcommand in `GENERATORS` in `__main__.py`, called as
`generate(trig, out)`; `htmx`, `fastapi` and `compose` (S06) are registered the same
way, and only `compose` uses `out`.

**Errors.** A missing or ambiguous required fact raises `GeneratorError(subject,
predicate, detail)`. Its message names the subject IRI and the predicate, so the model
author can find the fact to fix. The CLI prints that message to stderr and exits **2**.
A model file that cannot be read, or an output directory that cannot be written, exits
**1**. Nothing is written when generation fails.

## The golden-target rule

`golden_target(path, model_hash)` (`golden.py`) is the expected output: the golden with
every trailing `[graph: …]`, `[fixed]` or `[gap: GAP-NN]` marker removed (a comment
that held only a marker is dropped with the whitespace before it), each line
right-stripped, and `sha256:<model-hash>` replaced by the real hash. The marker
conventions are in [docs/generation/golden/README.md](../docs/generation/golden/README.md).
`tests/test_htmx_generator.py` asserts `generate_page(trig) == golden_target(golden, hash)`
and prints a unified diff on mismatch.

## htmx rendering rules

Every rule is keyed on a graph fact. Fixed text (doctype, the htmx CDN script, closing
tags) lives in `templates/htmx_page.html.j2`; everything else comes from the `PageModel`
that `extract_page` builds. `extract_page` is the IFML interpretation: it reads the model
only through `model.interfaces` and the views its elements link to (`model.shapes`,
`model.operations`, `model.channels`, `model.processes`, `model.lifecycles`), with
`model.compact` for curies, never raw triples (D036). `seams_gen/_views.py` turns a view's
`ResolutionError` into a `GeneratorError` naming the same subject and predicate, with the
"expected exactly one, found none" wording.

| Output | Graph fact |
|---|---|
| The page | The one `ifml:ViewContainer` with `ifml:isLandmark true` (none or several: error on the `ifml:InteractionModel`). `<main id>` is its local name; `<title>` is its `ifml:title`; the route comment is its `ifml:path`. |
| Header | `{# Generated by the seams htmx generator from the <trig stem> model. Do not edit. #}` then `{# model-hash: sha256:… #}` (`seams.model_hash`: TriG plus every `seam:renderPayload`). |
| Component order | Components the page `ifml:contains`, ascending by `ifml:order` (a component without one is an error). Each is a `{% block <local name> %}`. |
| `ifml:List` | `<nav aria-label="rdfs:label"><ul>`, looping `{% for item in <shape>s %}` where `<shape>` is the read shape's local name lowercased minus `Shape`. Each item shows the first `sh:order`ed datatype property that is not an identifier used by the link. |
| `ifml:Details` | `<section aria-label="rdfs:label"><ol id="<component>_items">`, looping with the singular shape name (`{% for message in messages %}`); `<li class>` is the shape's `rdfs:label` lowercased. Each `ifml:hasParameter` becomes a `data-<name>` attribute. |
| Field elements | The read shape's datatype `sh:property`s by `sh:order`: `dash:editor dash:TextAreaEditor` → `<p>`; `sh:datatype xsd:dateTime` → `<time datetime>`; anything else (including `sh:in` enumerations) → `<span class="<path>">`. Object-valued (`sh:class`) properties are not rendered. |
| Swap → target | The `ifml:NavigationFlow` from the event: `ifml:swap ifml:Replace` → `hx-swap="outerHTML"`, `hx-target="#<target>"`; `ifml:Append` → `beforeend`, `#<target>_items`; `ifml:Prepend` → `afterbegin`, `#<target>_items` (the rule on `ifml:swap` in `ontology/ifml.ttl`). |
| List link | The `GET` operation that `seam:rendersComponent` the flow target gives `hx-get`: its `comm:path` `hydra:template`, each `{variable}` filled as `{{ item.<hydra:property local name> }}`. `hx-trigger` is the event's `ifml:trigger`. |
| `hx-vals` | Each `ifml:ParameterBinding` of an `ifml:DataFlow` from the List to the flow target: `"<targetParameter label>": "{{ item.<mapped property> }}"`. The parameter must be a path variable of the read operation. |
| SSE placement | A `comm:Channel` with `comm:transport comm:SSE` that the presenting container `seam:consumes` adds the htmx sse extension script to `<head>`, and a `<div hx-ext="sse">` inside the component whose `seam:reads` equals the channel's `seam:acceptsShape`: `sse-connect` from its `comm:path`, `sse-swap` from `comm:eventName`, `hx-swap="beforeend"` (the channel rule), and a comment naming the delta publisher: of the elements that `seam:publishesTo` the channel, the one that `seam:invokes` an operation, else the sole publisher (exactly one is required). |
| `seam:visibleWhen` guard | `{% if <shape>_state == "<state rdfs:label>" %}` around the component, or `{% if <shape>_state in ("<label>", ...) %}` with the labels sorted when `seam:visibleWhen` has several states. `<shape>` is the read shape's local name lowercased minus `Shape` (the rule on `seam:visibleWhen` in `ontology/seam.ttl`). Every state must be a `state:hasState` of the shape's `seam:lifecycle`. This is the only conditional a generated page contains. |
| `ifml:Form` | `<form aria-label="rdfs:label">`; the one event that `seam:submitsTo` an operation gives `hx-<hydra:method>` and the path (each variable must be a page `ifml:Parameter`). A `proc:correlationKey` variable that no component reading a shape on the page carries as a parameter (the form starts a new process instance, so `Runtime.page_context` binds nothing to it) stays literal (`/expenses/{expense}`), and an `hx-on::config-request` handler replaces it with a fresh random key on every submit. The operation must be one the presenting container `seam:consumes`. Target and swap follow that event's NavigationFlow. The button text is the event's `rdfs:label`. Comments cite `seam:triggers`, `seam:governedBy` and `seam:mediaKind`. |
| Form inputs | Only for parameters `ifml:boundTo` a datatype `sh:path` of the written shape: `<label>`, then `<textarea>` for `dash:TextAreaEditor`, `<input type="datetime-local">` for `xsd:dateTime`, `<input type="text">` otherwise; `maxlength` from `sh:maxLength`, `required` from `sh:minCount ≥ 1`. Unbound properties are named in a comment as set by the runtime. |

Every collection is sorted explicitly: components by `ifml:order`, fields by `sh:order`,
everything else by IRI, never by graph iteration order.

## Fragments

A `seam:UIFragment` response renders a partial, and its name is one shared rule
(`fragment_for` in `fragments.py`, GAP-19 in
[gaps.md](../docs/generation/golden/gaps.md), decision D017). The FastAPI route
generator calls the same helper, so a route can never name a partial that was not
generated. `fragment_for(model, operation)` takes any `seams.Model` (a `ModelGraph`
included) and an operation IRI or `Operation` view, and reads `model.operations`
(`renders`, `submitted_by`) and `model.interfaces` (`Event.flows`, `Component.types`);
anything else raises `TypeError`.

- The operation's one `seam:rendersComponent` target C names the component. None or
  several raise `GeneratorError(operation, seam:rendersComponent)`.
- If some `ifml:Event` that `seam:submitsTo` the operation has an `ifml:NavigationFlow`
  to C with `ifml:swap ifml:Append` or `ifml:Prepend`, the partial is one item:
  `<C local name>_item.html` (kind `item`). C must be an `ifml:Details`.
- Otherwise it is the whole component: `<C local name>.html` (kind `component`).

`generate_fragments` / `render_fragments(page)` emit one file per name. Operations
that render the same name are listed together, and an operation whose component is
not on the page is skipped. Each file starts with the page's two header lines (the
generated notice and the model hash), then
`{# <kind> partial of <component type> <component>, rendered by <operations> #}`. The
body is the page's own lines. A component partial is everything strictly between
`{% block C %}` and its `{% endblock %}`. An item partial is the `<li …>` … `</li>`
lines of the Details `{% for %}` loop, keeping their indentation. For the chat app
that gives `conversation_list.html` (`:list_conversations_op`), `message_thread.html`
(`:message_thread_op`) and `message_thread_item.html` (`:send_message_op`, through
the `:send_to_thread` Append flow).

The partials are the same template files the page uses, not slices of its output.
`htmx_page.html.j2` includes `htmx_component.html.j2` as each block body, and that
includes `htmx_item.html.j2` inside the Details loop. `htmx_fragment.html.j2` writes
the header and includes one of the two.

## Task forms

`render_task_forms(page)` / `generate_task_forms(trig)` emit, for each `ifml:Form` that a
`proc:UserTask` `seam:completedOn` (ADR-0009), the partial `<form local name>.html` that
the host's task inbox renders once per open task, with `task` bound to a
`Runtime.user_tasks` row. `python -m seams_gen htmx` writes them alongside the page and
fragments (`templates/htmx_task_form.html.j2`). Forms are sorted by IRI.

| Output | Graph fact |
|---|---|
| Header | The page's two header lines, then `{# task form partial of ifml:Form :f: <task> seam:completedOn :f #}`. The task is written `prefix:rest` (`:approval_bpmn#approve_expense`), which `seams.ModelGraph.curie` expands back to the task IRI. |
| `<article class="task">` | `aria-label` and `<h2>` are the task's `rdfs:label`; `data-task` is the task; `data-<key>="{{ task.correlation_key }}"` where `<key>` is the `rdfs:label` of the `proc:correlationKey` of the process whose `seam:detailedBy` BPMN model holds the task (its IRI is `<model>#<id>`, or it is `seam:inModel` the model; not exactly one process: error on `seam:detailedBy`). |
| Entity | When the task `seam:reads` a shape: `{% if task.entity %}<dl class="<shape label lowercased>">` with a `<dt>`/`<dd class="<path>">{{ task.entity.<path> }}</dd>` per datatype property, by `sh:order`. |
| `<form>` | The form's one submitting event (as on the page): `hx-<method>` is the operation's `hydra:template` with the correlation-key variable filled from `{{ task.correlation_key }}`. Any other path variable, or a template without the key, raises `GeneratorError(process, proc:correlationKey)`. `hx-target="closest article"` (an inbox holds several tasks, so no page id is targeted); `hx-swap` is the event's `ifml:NavigationFlow` swap. Element ids end in `_{{ task.correlation_key }}`. |
| Fields | The datatype properties of the shape the form `seam:writes` that an `ifml:hasParameter` is `ifml:boundTo`, by `sh:order`. An `sh:in` enumeration is a `<select>` with one `<option>` per value in list order (`required` with `sh:minCount 1`); anything else is the page's `<input>` / `<textarea>` rule. Unbound properties get the page's "set by the runtime" comment. |
| Screen partials | Each component on the form's screen (the `ifml:ViewContainer` that `ifml:contains` it) that an operation the presenter consumes `seam:rendersComponent` gets its fragment as above, so the completion route's partial exists (`expense_details.html` in the fixture). |
| Errors | A form two user tasks are completed on raises on `seam:completedOn`; a completion target that is not an `ifml:Form` raises on `seam:completedOn`; a form with no `seam:writes` raises on `seam:writes`. |

## FastAPI rendering rules

`extract_routes(model)` builds a frozen `RoutesModel`; `render_routes` renders it
through `templates/fastapi_routes.py.j2` (the same `[% %]` / `[[ ]]` / `[# #]`
environment as htmx, `StrictUndefined`, no domain literals). `generate_routes(trig)`
returns the single module's text. It reads `model.architecture` (`Container.exposes`,
`executes`, `systems`), `model.processes` (`Process.triggering_operations`,
`channel_starts`, `invoked_operations`, `correlation_parameter`), `model.operations` and
`model.channels` (`path`, `accepts`, `returns`, `submitted_by`, `governed_by`) and
`model.interfaces` (the submitting `ifml:Form`, the user tasks it `completes`, component
parameters). Handlers hold no domain logic (ADR-0007 rule 1):
the generated module has no `if`, conditional expression, `match` or loop; the template's
branches only choose a layout from graph facts. Everything is sorted by IRI.

| Output | Graph fact |
|---|---|
| Container | Each serving `arch:Container` gives `<local name>.py` (`serving_containers`, D026): one that `seam:executes` a `proc:Process`, or that `seam:exposes` a `hydra:Operation` some `ifml:Event` `seam:submitsTo`. An operation that only a task `seam:invokes` (the chat app's `:completion_op` on `:llm_gateway`) does not make its container serving. None raises `GeneratorError(<model file>, seam:executes)`; `generate_routes` and the CLI also require exactly one. |
| Header | `# Generated by the seams FastAPI generator from the <trig stem> model. Do not edit.`, `# model-hash: sha256:…` (`seams.model_hash`), `# Route module for :c, from :system arch:contains :c` (the one `arch:System` that `arch:contains` it) and `# :c seam:exposes …` (its exposed elements by IRI). |
| Not-routed comment | One line per operation that the executed process, or an element of its BPMN model (`<seam:detailedBy model>#…`), `seam:invokes` and another container `seam:exposes`: `# :op is not routed here: :other seam:exposes :op`. |
| `Runtime.load` | `"/model/<trig file name>"` with `model_hash=MODEL_HASH` (ADR-0007 rule 2). |
| Endpoints | Each element the container `seam:exposes`, by IRI: a `hydra:Operation` or a `comm:Channel` (anything else: error on `rdf:type`). The handler name is the local name minus a trailing `_op` (GAP-21). |
| Decorator | `@router.<hydra:method lower>` (GET/POST/PUT/PATCH/DELETE); the path is the `comm:path` `hydra:template` (missing: error on `comm:path`). The operation must have `seam:mediaKind seam:UIFragment` (else error on `seam:mediaKind`) and gets `response_class=HTMLResponse`. Each `seam:governedBy` policy adds `Depends(runtime.policy("<curie>"))` to `dependencies=[…]`; with dependencies the decorator is multi-line, without them single-line. |
| Signature | Each template variable as `<var>: str`, then `request: Request` when the operation has a `comm:requestMediaType`, then, for a Complete step, `identity: Identity = Depends(runtime.task_policy("<task>"))` (401 without an identity, 403 unless every `seam:governedBy` policy of the task permits it). `Identity` is imported only by a module with a Complete step. |
| Request body | `application/x-www-form-urlencoded` → `form = await request.form()`; `application/json` → `body = await request.json()`; any other media type raises `GeneratorError(op, comm:requestMediaType)`. |
| Validate | `seam:acceptsShape S` → `<s> = runtime.validate("<S curie>", form)`, where `<s>` is S's local name lowercased minus `Shape`, plus `_payload` when that name is also a path variable (so the payload never shadows the correlation key). It needs a request body. A handler with a Write or Complete step has no separate validate line: `runtime.write` and `runtime.complete_task` validate. |
| Start | When the operation is the triggering operation of a process the container executes (`Process.triggering_operations`: an event `seam:submitsTo` it and `seam:triggers` the process), `await runtime.start_process("<process>", <s>, correlation_key=<label>)`. The `proc:correlationKey` parameter's `rdfs:label` must be a path variable, else `GeneratorError(process, proc:correlationKey)`. A channel-started process ([ADR-0010](../docs/adr/0010-channel-started-processes.md): its start event, a `proc:MessageCatchEvent`, `seam:subscribesTo` a channel) gets no route; the runtime starts it when the channel is published on. An executed process with neither a `seam:triggers` event nor a subscribed start is `GeneratorError(process, seam:triggers)`. |
| Write | When no process is triggered by the operation, it has `seam:acceptsShape S`, and an event of an `ifml:Form` that `seam:writes S` (`ifml:hasEvent`) `seam:submitsTo` it (D026), `<s> = runtime.write("<S curie>", form)` in place of the validate line and before the return, so the item partial renders the stored entity. `runtime.write` validates the form itself because it first assigns the entity's `:id`, which the form never sends. Any other untriggered operation gets no write step. |
| Complete | When an event of an `ifml:Form` that a `proc:UserTask` `seam:completedOn` `seam:submitsTo` the operation (ADR-0009), `await runtime.complete_task("<task>", form, correlation_key=<key>, identity=identity)` in place of Start or Write. `<key>` is the `proc:correlationKey` label of the process whose BPMN model holds the task and must be a path variable, else `GeneratorError(process, proc:correlationKey)`. It needs a request body (error on `comm:requestMediaType`); an operation that also triggers a process, or whose forms complete several tasks, raises on `seam:submitsTo`. The serving-container rule covers the container through `seam:executes`. |
| Query | A `GET` (or an operation with a Complete step) with `seam:returnsShape S` → `<s>s = runtime.query("<S curie>", <var>=<var> …)`, one keyword per path variable. |
| Return | `runtime.render_fragment("<name>", …)` with the name from `fragment_for` (GAP-19). An item partial passes the validated `<s>` (`seam:returnsShape` must equal `seam:acceptsShape`); a component partial passes the query list `<s>s` plus `<p>=<p>` for each `ifml:hasParameter` of the component whose `rdfs:label` is a path variable. POST and other non-GET methods use the multi-line layout, GET the single-line one. |
| SSE channel | `comm:transport comm:SSE` → `@router.get(path)`, `async def <name>(<var>: str) -> StreamingResponse`, `events = runtime.subscribe("<curie>", scope=<var>)` with the single path variable, and `StreamingResponse(events, media_type="text/event-stream")`. Any other transport raises `GeneratorError(channel, comm:transport)`; not exactly one path variable raises on `comm:path`. |

## Compose rendering rules

`extract_compose(model, base_dir)` builds a frozen `ComposeModel`; `render_compose`
renders it through `templates/compose.yaml.j2` (same environment, no domain literals).
`generate_compose(trig, base_dir=None)` defaults `base_dir` to the working directory;
the CLI passes `--out` (D018). The bind-mount sources and `SEAMS_MODEL` follow the TriG
path it is given, so a model under another path or stem mounts and names that file; the
runtime reads `SEAMS_MODEL` in preference to the path in the generated route module (see
[seams_runtime/README.md](../seams_runtime/README.md)). Every value is pre-rendered as a YAML scalar: plain when
`yaml.safe_load` reads it back as the same string, otherwise JSON double-quoted.
It reads `model.architecture`: `System.containers` and each `Container`'s `artifact`,
`ports`, `deploy_depends_on`, `bindings`, `volumes`, `healthcheck`, `replicas` and
`deployed_to`. Ports, volumes and bindings are blank nodes, so their errors name the
container.

| Output | Graph fact |
|---|---|
| Header | `# Generated by the seams compose generator from the <trig stem> model. Do not edit.` then `# model-hash: sha256:…` (`seams.model_hash`). |
| Services | The `arch:Container`s that the one `arch:System` `arch:contains`, by IRI, named by local name (none or several systems: `GeneratorError(<model file>, arch:contains)`). Keys in the order `image`, `ports`, `expose`, `depends_on`, `environment`, `secrets`, `volumes`, `healthcheck`, `deploy`. |
| `image` | The one `deploy:artifact`: `<deploy:reference>:<deploy:version>` (missing: error on the container and `deploy:artifact`). |
| `ports` / `expose` | Each `deploy:port`: with `deploy:publishedPort` → `ports: - "pub:cont"`; without → `expose: - "cont"`. |
| `depends_on` | The `deploy:dependsOn` local names, sorted (not `arch:dependsOn`); a target outside the system is an error. |
| `environment` | For the serving container (the FastAPI rule above; at most one, else `GeneratorError(<model file>, seam:executes)`), first `SEAMS_MODEL: /model/<trig name>` and `SEAMS_MODEL_HASH`. Then each `deploy:configuration`/`deploy:binding` by `deploy:key`: `deploy:value` → `KEY: value`; `deploy:secretRef` → `KEY_FILE: /run/secrets/<key lower>`; `deploy:serviceOf S` → `KEY: http://<S>:<S's single deploy:containerPort>`. None or several of the three: error on the container and `deploy:binding`, naming the key. |
| `secrets` | Each `deploy:secretRef` binding adds `<key lower>` to the service and a top-level `<key lower>: {name: <deploy:secretName>, external: true}` (missing `deploy:secretName`: error on the container, naming the key). |
| `volumes` | For the serving container, read-only model binds first: `./<trig relative to --out>:/model/<trig name>:ro`, then each `seam:renderPayload` as `./<payload relative to --out>:/model/<path relative to the trig dir>:ro`, sorted. Then each named `deploy:volume` as `<volumeName>:<mountPath>`, with a top-level `<volumeName>: {}`. |
| `healthcheck` | `deploy:healthcheck`: `test: ["CMD-SHELL", "<deploy:probe>"]`, `interval: <deploy:interval>`. |
| `deploy` | `replicas` from `deploy:replicas`; `placement.constraints: - node.labels.seams.node == <rdfs:label>` of the one `seam:deployedTo` node (no label: error on the node and `rdfs:label`). |
| Top level | `secrets:` and `volumes:` after `services:`, sorted, omitted when empty. |

## Source elements

`seams_gen.sources.output_sources(name, trig, out)` returns, for generator `name`,
`{relative file name: IRIs}` with exactly the file names the generator writes for the
same model. Each tuple holds the full IRIs of the model elements the file comes from,
sorted and de-duplicated; `seams generate` records them in `seams.lock` (D043). They
are read through the generators' own extract functions and the seams views, so a
missing or ambiguous fact raises the generator's `GeneratorError`.

| Generator | File | Source elements |
|---|---|---|
| `htmx` | `<page>.html` | the `ifml:ViewContainer` and each of its components |
| `htmx` | fragment partial | the component it renders and each operation that `seam:rendersComponent` it; a partial two pages share lists the union |
| `htmx` | task form partial | the `ifml:Form`, the `proc:UserTask` `seam:completedOn` it, the shape the form `seam:writes` and the shape the task `seam:reads` (if any) |
| `fastapi` | `<container>.py` | the serving container, each `proc:Process` it `seam:executes` and the operation or channel of each endpoint |
| `compose` | `compose.yaml` | the `arch:System` and each `arch:Container` it `arch:contains` |

## Complexity check

```
python -m seams_gen.complexity examples/chat-app/chat-app.trig
```

Runs the three queries in [`docs/queries/complexity/`](../docs/queries/complexity/)
against any model (backlog E3, D025) and prints the models per notation, the five
elements reached from the most distinct models and the cross-layer seam edge count,
then `PASS` or `FAIL` with one line per failed threshold (actual vs required).

| Measure | Threshold | Chat app | Expenses, chapter 8 |
|---|---|---|---|
| Notations with 2+ models | at least 3 (`MIN_MULTI_MODEL_NOTATIONS`) | 0 | 4 (BPMN, DMN, IFML, statechart) |
| Most models one element is reached from | at least 5 (`MIN_MAX_REACH`) | 3 | 6 (`:ExpenseShape`) |
| Cross-layer seam edges | reported, not gated | 60 | 115 |

The chat app fails by design: it is a one-model-per-layer quick start. The
expense tutorial's final checkpoint, `examples/expenses/chapter-08/expenses.trig`,
is the passing worked example.

**Exit codes.** 0 pass, 1 fail, 2 when the model file is missing, unreadable or not
valid TriG (the message goes to stderr).

**Model only.** `load_model(trig)` loads through `seams.load`: still TriG only, as the
union of its graphs. It never loads `ontology/*.ttl`: the ontology's `seam:reveal`
annotations are `seam:` triples too and would raise the chat app's edge count from 60
to 86. `most-reached.rq` ends in `LIMIT 5`, but SPARQL orders ties arbitrarily, so
`measure` drops the limit, sorts by count descending then IRI, and takes the top five.

```python
from seams_gen.complexity import load_model, measure
r = measure(load_model("examples/checkout.trig"))
r.multi_model_notations, r.max_reach, r.edges, r.failures   # 1, 4, 37, [...]
```

## Sequence diagrams

```
python -m seams_gen.sequence examples/chat-app/chat-app.trig :send_message --out build/sequences
# -> build/sequences/send_message.mmd
python -m seams_gen.sequence examples/expenses/chapter-08/expenses.trig :submit_expense --out build/sequences
# -> build/sequences/submit_expense--auto.mmd, submit_expense--manager--approved.mmd, ...
```

`seams_gen.sequence` (backlog U1, R008, D047) derives as-designed Mermaid sequence
diagrams for one IFML event (a CURIE, local name or full IRI). It is not a `GENERATORS`
entry, because it needs an event as well as a model; `seams sequence <event>` runs the
same deriver from a project file ([seams CLI](../docs/reference/seams-cli.md#seams-sequence)).
Every arrow comes from a graph fact read through the `seams` views, and the step order
comes from the sequence flows of the BPMN process the event triggers. The executing
container (API below) is the one that `seam:exposes` the operation the event submits to
and `seam:executes` the triggered process.

| Graph fact | Diagram element |
|---|---|
| `odrl:assignee` of a `seam:governedBy` policy of the event | `actor`; the first arrow, `<event> (policy: <policy>)`, goes to the UI |
| the container that `seam:presents` the event's interaction model | the UI lifeline |
| `seam:submitsTo` | `UI->>API: <METHOD> <operation> [<accepted shape>]`, then `Note over API: start <process>` |
| `seam:writes` + `seam:storedIn` | `API->>STORE: <task> writes <shape>`, once per store container |
| `seam:fires` | `Note over API: <transition>` |
| `seam:rendersComponent` of the submitted operation | `API-->>UI: <component> fragment`, after the node that invokes that operation |
| `seam:decidedBy` | `API->>API: <task> (DMN <decision>)` |
| `seam:invokes` an operation another container `seam:exposes` | `API->>C: <task>, <operation> [<accepted>]` and `C-->>API: <operation> returns [<returned>]` |
| `seam:publishesTo` from a task | `API-->>X: <channel> (<comm:eventName> deltas)` per `seam:consumes` container |
| `seam:publishesTo` from a throw or end event | `API-->>X: <channel> (<label> event)` per consumer |
| a channel a message start event `seam:subscribesTo` | `API-->>C: <channel> starts <process>` (the walk does not enter it) |
| a user task's policy assignee and `seam:completedOn` form | `<actor>->>UI: <task> on <form>`, then `UI->>API: complete <task> [<output shape>]` |
| an exclusive gateway branch | `Note over API: <gateway>: <flow>` |
| `seam:reads` | nothing |

**One diagram per path.** The walk forks at every exclusive gateway with more than one
outgoing flow, in BPMN document order, so there are no `alt`, `opt` or `par` blocks. A
single-path event is named `<event>`; otherwise the name joins the chosen flow labels,
`<event>--<flow>--...`, and the header reads `%% path: manager, approved`. A flow met
twice on one path ends that path with the gap `loop at <flow>`. A parallel or inclusive
gateway is a gap and follows only its first flow.

**Gaps.** Every arrow the deriver cannot place is a gap, never a silent omission. It is
rendered in the diagram header as `%% gap: <detail>` (for example
`%% gap: MessageShape written by persist_user_msg has no seam:storedIn`), and the command
prints it on stderr as `gap <diagram name>: <detail>`. Each diagram also records
`%% derived from <event IRI>` and `%% path: <labels or single>`. Gaps are a model audit,
so the exit code stays 0; a GeneratorError (including an unknown event) or a model that
cannot be read or parsed exits 2 with `python -m seams_gen.sequence: <message>` on stderr,
and a file that cannot be written exits 1. Files are written as UTF-8 with `\n` newlines
by `write_diagrams`, which `seams sequence` shares.

**Goldens.** `docs/generation/sequences/chat-app/send_message.mmd` (one path, with the
Message Store lifeline from `seam:storedIn` and the `invoke_llm` delta arrow from
`seam:publishesTo`) and the five `docs/generation/sequences/expenses/submit_expense--*.mmd`
diagrams of expense chapter 8 (`auto`, then `manager` and `finance`, each `approved` or
`rejected`). Chapter 8 is the only expense checkpoint with `seam:storedIn`; earlier
chapters derive storedIn gaps instead of store lifelines.

```python
import seams
from seams_gen.sequence import derive, render
(d,) = derive(seams.load("examples/chat-app/chat-app.trig"), ":send_message")
d.name, d.gaps, render(d)   # 'send_message', (), 'sequenceDiagram\n    %% derived from ...'
```

The viewer imports the same `derive` and `render` for its `GET /sequence/{event}` route
and its Sequences section, and the docs site embeds the goldens by snippet import.

### As executed

The diagrams above are *as designed*: every path the model allows. `executed` is the
*as executed* counterpart (backlog U4): one diagram of one recorded run, drawn from the
trace rows the runtime's worker records per BPMN element, on the same actor, UI and API
lifelines as `derive`. The opening arrows (actor, `POST <operation>`, `start <process>`)
are the same; after them each row adds, in the order the worker ran it:

| Trace row field | Diagram element |
|---|---|
| `by` (a user task completed by a person) | `actor by_<id> as <id>`, `by_<id>->>UI: <task> on <form>`, `UI->>API: complete <task>` |
| `decision`, `outputs` | `API->>API: <task> (DMN <decision>) = <output values>` |
| `invokes` with `in_process` | `API->>API: <task>, <operation> (in process)` |
| `invokes` with `container`, `path`, `tokens` | `API->>C: <task>, <operation> <path>` and `C-->>API: <tokens> deltas` |
| `streamed` | `API-->>X: <channel> (<tokens> <event> deltas)` per `seam:consumes` container |
| `writes` | `API->>STORE: <task> writes <shape>` per `seam:storedIn` container (entity ids are not drawn) |
| `fires`, `status` | `Note over API: <transition> → <status>` |
| `published` | `API-->>X: <channel> (<event> event)` per consumer |
| `started` | `API->>C: start <process>` on its executing container |
| an error row (`task` null, `error`) | `Note over API: error <type>, <transition> → <status>` |

The diagram is named `<event>.executed` (file `<event>.executed.mmd`), its header reads
`%% executed from <event IRI>`, `%% path: <row task ids>` and, when the run is known,
`%% run: <instance id>`. A row the graph cannot place is a `%% gap:` line and the rest
of the run is still drawn: an IRI that is not an element of the triggered process, a
container, channel or started process the model does not have, or a row with no IRI.

`read_trace(source, db=None)` returns `(run id, rows)`. An existing file is JSON: an
instance result (`{"instance": ..., "trace": [...]}`, as `Instance.wait()` returns) or a
bare list of rows. Anything else is an instance id in the runtime's SQLite store at `db`
(default `SEAMS_DB`, else `./seams.sqlite`), read read-only with `sqlite3` from the
`workflow_state` checkpoint's `data.seams.trace`; seams_gen does not import
seams_runtime. A missing store or instance, or a file that is not a trace, raises a
GeneratorError naming it.

```python
import seams
from seams_gen.sequence import executed, read_trace, render
run, rows = read_trace("tests/fixtures/traces/chat_send_message.json")
d = executed(seams.load("examples/chat-app/chat-app.trig"), ":send_message", rows, run=run)
d.name, d.gaps   # 'send_message.executed', ()
```

**Golden.** `docs/generation/sequences/chat-app/send_message.executed.mmd`, rendered
from the captured run `tests/fixtures/traces/chat_send_message.json`; a live run with a
mocked LLM renders the same lines (`tests/test_sequence_executed.py`).

## Tests

`tests/test_htmx_fragments.py` covers the fragment names, the header-plus-page-lines
equality, a render of each partial, the CLI, the swap and `submitsTo` mutations and the
`seam:rendersComponent` errors. Also `tests/test_golden_target.py` (the stripping rule)
and `tests/test_htmx_generator.py`:
byte equality with the golden, the hash header, determinism, no domain literals in the
template, no logic nodes but the `visibleWhen` guard in the output (Jinja2 AST walk), a
render smoke test of the generated template, model-edit mutation, and missing or
ambiguous facts failing through both the API and the CLI.
`tests/test_fastapi_generator.py`: byte equality with the `chat_api.py` golden, the
hash header, determinism, no domain literals in the template, a Python AST walk with no
branch or loop in any handler, the POST handler's runtime calls being exactly
`validate`, `start_process`, `render_fragment`, every `runtime.<attr>` being callable on
`Runtime`, the `hydra:template` mutation, and missing `comm:path`, an unknown
`comm:requestMediaType` and no serving container failing through the API and the CLI, and
the process-less expense model (`tests/processless_model.py`) generating
`validate`, `write`, `render_fragment` with no `start_process`.
`tests/test_human_task_generators.py`: for the approval fixture
(`tests/fixtures/human_task/approval.trig`), the completion handler (task_policy
dependency, correlation key, `complete_task`, no validate), the task curie expanding to
the governed IRI, `Identity` imported only when needed, the generated module compiling
and answering 401/403 through `seams_runtime.host`, the task form partial (hx-post with
the key, one field per bound property, `sh:in` as a `<select>`, the task label and
entity, escaping), the completion partial, determinism, and the key-not-a-path-variable,
no-process, no-body and two-tasks errors.
`tests/test_compose_generator.py`: byte equality with the `compose.yaml` golden, the
hash header and `SEAMS_MODEL_HASH`, determinism, no domain literals in the template,
the parsed structure (read-only model binds, external secrets), bind sources following
`base_dir`, replicas/published-port/node-label/`deployedTo`/quoted-value mutations,
missing artifact, `deploy:secretName` and node label failing through the API and the
CLI, the CLI writing exactly `compose.yaml`, and `docker compose config -q` accepting
the output (skipped when docker compose is not installed).
`tests/test_complexity.py`: the chat app (0 / 3 / 60, two failures), checkout and
expense chapter 8 (4 / 6 / 115, passing, also through the CLI) scores,
determinism, the ontology not being loaded, a synthetic passing model and its
one-short-of-each-threshold boundary, an empty model, the CLI's exit codes 0, 1 and 2
(missing file, invalid TriG, a directory), and the complexity queries staying out of
the top level of `docs/queries/`.
