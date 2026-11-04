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

`seams_gen.__version__` (in `seams_gen/__init__.py`) is the built-in generators'
version: each built-in `Generator`'s `version`, which `seams generate` records per output
in `seams.lock`. A third-party generator's outputs carry its own `version`. This member is never installed
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
# -> ./compose.development.yaml ./compose.production.yaml   (one per arch:Environment, ADR-0015;
#    paths are relative to --out, so `docker compose -f compose.development.yaml up` works there)
python -m seams_gen ifmledit examples/chat-app/chat-app.trig --out build/
# -> build/ifmledit.json   (the IFML layer as IFMLEdit.org JSON; the ifml: terms with no
#    IFMLEdit counterpart are named on stderr)
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
`examples/chat-app/generated/templates/*.html` and the root `compose.development.yaml` and
`compose.production.yaml`
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
from seams_gen import generate_compose, generate_compose_environments, extract_compose, render_compose
files = generate_compose_environments("examples/chat-app/chat-app.trig", base_dir=".")  # {compose.<env>.yaml: text}
dev_yaml = generate_compose("examples/chat-app/chat-app.trig", "development", base_dir=".")
```

| Generator | Writes | From |
|---|---|---|
| `htmx` | `<out>/<page local name>.html`, a Jinja2/htmx template (UTF-8, `\n` newlines) | the landmark `ifml:ViewContainer` and the seam, shape, comm and lifecycle facts it touches |
| `htmx` (fragments) | `<out>/<component>.html` and `<out>/<component>_item.html` partials, one per name the fragment rule gives | each operation the presenting container `seam:consumes` that `seam:rendersComponent` a page component |
| `htmx` (task forms) | `<out>/<form local name>.html`, one partial per form a user task is completed on, plus the partials its completion route renders on the form's screen | each `ifml:Form` a `proc:UserTask` `seam:completedOn` (ADR-0009, D027) |
| `htmx` (other served pages) | `<out>/<page local name>.html` and its partials, built like the landmark page but without task forms | each page of `model.interfaces.served_pages()` after the landmark: an `ifml:ViewContainer` with an `ifml:path` that is not the landmark and holds no task form, from any `ifml:InteractionModel` its container `seam:presents`. The expense tutorial's `:payouts_page` (chapter 8) is one. A partial two pages would render differently is a `GeneratorError` |
| `fastapi` | `<out>/<container local name>.py`, a thin FastAPI route module | the one serving `arch:Container` (it `seam:executes` a `proc:Process`, or `seam:exposes` an operation an `ifml:Event` `seam:submitsTo`), and what it `seam:exposes` |
| `compose` | `<out>/compose.<environment local name>.yaml`, one docker compose file per `arch:Environment` (ADR-0015), with paths relative to `<out>` | the `arch:Container`s of the one `arch:System`, their `deploy:` facts under the override rule for that environment, `seam:deployedTo` and the serving-container rule |
| `jsonld` | `<out>/<shape local name>.jsonld`, one JSON-LD 1.1 context document per `sh:NodeShape` with a `sh:targetClass` (ADR-0024, backlog O3), sorted JSON with a trailing newline; nothing for a model without target-classed shapes | `model.shapes`: `Shape.target_class` and `Shape.fields()`; [JSON-LD rendering rules](#json-ld-rendering-rules) |
| `mentalmodel` | `<out>/manifest.yaml` and `<out>/ontology/<modelId>.jsonld`, `<out>/shapes/<modelId>.jsonld`, `<out>/views/<modelId>.jsonld`: a SemPKM Mental Model that `POST /api/models/install` installs (ADR-0026, backlog O5), JSON-LD without a context, sorted, with a trailing newline | the one `seam:Ontology` model (its IRI, `owl:versionInfo`, `rdfs:label`, `rdfs:comment`, `owl:imports`), `model.shapes` with a `sh:targetClass` and the shapes they reach by `sh:node`, and each `ifml:List` / `ifml:Details` of `model.interfaces` that `seam:reads` a shape; [Mental Model rendering rules](#mental-model-rendering-rules) |
| `dockerfile` | `<out>/<route module stem>.Dockerfile` (`chat_api.Dockerfile`), the runtime image build file, with every path literal and relative to the build context; header and `io.semanticseams.model-hash` / `io.semanticseams.container` labels name the model hash and the container | the serving `arch:Container` and the `deploy:build` of its `deploy:artifact` in the `development` `arch:Environment` (ADR-0015); no serving container, or no development build, is a `GeneratorError` naming `seam:executes` or `deploy:build` |
| `tests` | `<out>/test_scenarios.py`, `<out>/test_decisions.py`, `<out>/test_shape_examples.py` and `<out>/test_policies.py`, pytest files (ADR-0014) | each `verify:Scenario`, `verify:DecisionExample` and `verify:validExample` / `verify:invalidExample`, read through `model.scenarios`, `model.decision_examples` and `Shape.valid_examples` / `Shape.invalid_examples`, and each `odrl:permission` of `model.policies` with every `odrl:Party`; [Tests rendering rules](#tests-rendering-rules) |
| `ifmledit` | `<out>/ifmledit.json`, the model's IFML layer as [IFMLEdit.org](https://github.com/B3rn475/IFMLEdit.org) JSON (backlog 12, a conformance check of the `ifml:` vocabulary): `elements` (`ifml.ViewContainer`, `ifml.ViewComponent` with stereotype `list` / `details` / `form`, `ifml.Event`, `ifml.NavigationFlow`, `ifml.DataFlow`) and `hierarchy` / `source` / `target` `relations`, ids the IRI local names, everything sorted, with a deterministic `metadata.graphics` layout the IFMLEdit loader requires. The `ifml:` terms with no IFMLEdit counterpart (`ifmledit.UNMAPPED`: `ifml:swap` and its strategies, `trigger`, `path`, `title`, `boundTo`, `order`, `InteractionModel`) are left out, printed on stderr and listed in [gaps.md](../docs/generation/golden/gaps.md) (GAP-29 to GAP-35) | `model.interfaces`; no `ifml:InteractionModel`, a component that is not exactly one of List, Details and Form, an element in several containers, an event without one exported owner, a flow with an unexported end or two elements with one local name is a `GeneratorError` |
| `smoke` | `<out>/test_smoke.py`, a pytest file that calls a running app (backlog A9) | each `hydra:Operation` of `model.operations` with a `hydra:method` and a `comm:path`, its `seam:acceptsShape` / `seam:returnsShape`, its error statuses (ADR-0013), the first `verify:validExample` of its shapes and each `odrl:permission` targeting it; [Smoke rendering rules](#smoke-rendering-rules) |
| `acceptance` | `<out>/test_<module>.py`, one pytest file per module of the handlers package (ADR-0012) that checks the hand-written body against the model (backlog C2) | each `comm:PythonHandler` function the stub generator writes (`stubs.extract_stubs`), its operations' `seam:acceptsShape` / `seam:returnsShape` and `hydra:possibleStatus`, the `verify:validExample`s of the accepted shape, and, per invoking `proc:ServiceTask`, its `seam:fires` transition and the `verify:DecisionExample`s of its process; [Acceptance rendering rules](#acceptance-rendering-rules) |

## The protocol and the registry

Every generator, built-in or not, is a `Generator` object (`protocol.py`,
[ADR-0016](../docs/adr/0016-generator-protocol.md)): a frozen, keyword-only dataclass
with `name`, `version`, `help`, `preconditions` (full `sh:NodeShape` IRIs, default `()`)
and three functions:

- `extract(trig, out)` reads the model into a frozen view model. Every check and
  computation is here; a missing or ambiguous fact raises `GeneratorError`.
- `render(view)` turns the view model into `{relative file name: text}`, with no model
  access.
- `sources(trig, out)` gives `{relative file name: full IRIs}` of the model elements each
  file comes from, with exactly the file names `render` returns; `seams generate`
  records them in `seams.lock`.

An optional fourth, `trace(view)` (default `None`), gives `{relative file name: Trace}`
with exactly the file names `render` returns: the line-level generation trace of each
file ([ADR-0019](../docs/adr/0019-generation-trace.md), "Generation traces" below).

`generate(trig, out)` is `render(extract(trig, out))`; only `compose` uses `out`.
`check_preconditions(results, shapes)` reads a pyshacl report of the model against
`ontology/shapes` and raises `GeneratorError` (subject the focus node, predicate the shape
IRI, naming the generator) on a result of a precondition shape or one of its
`sh:property` shapes. `seams generate` calls it before running anything (strict mode);
`seams_gen` itself does not depend on pyshacl. `precondition_faults(results, shapes)`
returns every such error, sorted by (shape, focus, message), and `check_preconditions`
raises the first. `seams generate --lenient` (D057) uses the list: it records each fault,
and each `GeneratorError` a generator raises, in the `faults` key of `seams.lock` instead
of stopping, and `seams check` reports that lock as `flagged`.

The built-ins `htmx`, `fastapi`, `compose` (S06), `tests` (M015), `smoke` (M015/S05),
`acceptance` (M022/S03), `dockerfile` (M016/S03), `ifmledit` (M008/S01), `jsonld` (M023/S05) and `mentalmodel` (M024/S03) are the objects of `builtin.py`. Each
has a real extract and render step built on its `extract_*` and `render_*` functions
(htmx extracts every `PageModel`, then renders each), takes its sources from
`sources.py` and declares no preconditions; `ifmledit` keeps its stderr summary of
unmapped terms. `htmx`, `fastapi`, `compose` and `dockerfile` have a `trace`
(`trace_pages`, `trace_routes`, `trace_compose_environments`, `trace_dockerfile`).

`registry.discover()` loads every entry point of the `seams.generators` group (D056) and
returns `{name: Generator}` sorted by name. The built-ins are registered in
`packages/seams-cli/pyproject.toml`, because this member is virtual and installs no
metadata (D033), so a third-party generator is found the same way:

```toml
[project.entry-points."seams.generators"]
checklist = "seams_checklist:generator"
```

An entry point that does not load, loads no `Generator`, names a different generator or
repeats a name raises `registry.RegistryError` (a `GeneratorError`) naming the entry
point and its distribution. After changing the entry points, run `uv sync --all-packages`
so the editable metadata refreshes. `GENERATORS` in `__main__.py` (subcommand to
`(help, generate)`) and `sources.output_sources` are views of the registry, so
`python -m seams_gen <name>` runs any registered generator. The
[guide](../docs/guide/write-your-own-generator.md#register-it-with-seams-generate)
registers one.

**Images.** `python -m seams_gen.images PROJECT...` (`images.py`) is not a generator: it
prints, as JSON, each Dockerfile a project's `dockerfile` generator writes, its build
context, the production `deploy:artifact` reference and version, and the tags
`<reference>:<version>` and `<reference>:sha-<first 12 hex digits of the model hash>`.
The gated `.github/workflows/publish-images.yml` (manual or `v*` tag only) builds and
pushes from that list. A missing project file or Dockerfile exits 1; a missing model fact
prints the `GeneratorError` and exits 2.

**Errors.** A missing or ambiguous required fact raises `GeneratorError(subject,
predicate, detail)`. Its message names the subject IRI and the predicate, so the model
author can find the fact to fix. The CLI prints that message to stderr and exits **2**.
A model file that cannot be read, or an output directory that cannot be written, exits
**1**. Nothing is written when generation fails.

**Parity with the shapes.** A model that passes `ontology/shapes/seam-shapes.ttl` must
generate (principle 5). A new `raise GeneratorError` therefore needs a parity case in
`tests/test_shape_generator_parity.py` (a mutated example that the shapes flag and the
generator rejects, naming the same subject and predicate) or a `GENERATOR_ONLY` entry
there with the reason no shape states it. The inventory tests count the raise sites per
module and fail on an unlisted or stale one.

## The golden-target rule

`golden_target(path, model_hash)` (`seams_gen.testing`) is the expected output: the golden with
every trailing `[graph: …]`, `[fixed]` or `[gap: GAP-NN]` marker removed (a comment
that held only a marker is dropped with the whitespace before it), each line
right-stripped, and `sha256:<model-hash>` replaced by the real hash. The marker
conventions are in [docs/generation/golden/README.md](../docs/generation/golden/README.md).
`tests/test_htmx_generator.py` asserts `generate_page(trig) == golden_target(golden, hash)`
and prints a unified diff on mismatch.

## Test kit

`seams_gen.testing` is the public test kit (backlog K4) a generator's tests import,
built-in or third-party:

| Function | Asserts | On failure |
|---|---|---|
| `golden_target(path, model_hash)`, `strip_markers(text, suffix)` | (returns) the golden-target rule above | `ValueError` for a marker outside a trailing comment or an unknown suffix |
| `assert_matches_golden(text, golden_path, model_hash)` | `text == golden_target(golden_path, model_hash)` | `AssertionError` naming the golden file and first differing line, then a unified diff |
| `assert_deterministic(generator, model_path, out=Path("generated"))` | two `generator.generate(model_path, out)` runs return the same `{file name: text}` | `AssertionError` naming the generator and the first (sorted) file name that differs or is produced by one run only |
| `check_output(path, text)` | `text` parses as its type: `.py` `ast.parse`, `.yaml`/`.yml` `yaml.safe_load_all`, `.json` `json.loads`, `.html` a Jinja2 parse | `AssertionError` `<path>:<line>: <parse error>`; an unknown suffix is a `ValueError` |
| `shape_violations(dataset, shapes, ontology=())` | (returns) `(focus, path, message)` of each SHACL result, validated as `seams check` does: the model unioned with the ontology graphs, pyshacl inference off; `path` is `None` when not a plain IRI | — |
| `assert_shapes_catch(extract, dataset, *, subject, predicate, focus, path=None, match='', model_path=None)` | the K1 parity rule: `extract(model)` raises a `GeneratorError` on `subject`/`predicate` (with `match` in its detail) and the shapes (default `ontology/shapes/seam-shapes.ttl` over `ontology/*.ttl`) report a result on `focus` (and `path`). Without `model_path` the dataset is written to a temporary TriG file and loaded from there | `AssertionError` saying `extract` did not raise or raised on another fact, or `no shape violation on <focus>` with the shape results found |

```python
from seams_gen.testing import assert_deterministic, assert_matches_golden, check_output
files = my_generator.generate(trig, Path("generated"))
assert_matches_golden(files["checklist.yaml"], golden, seams.model_hash(trig))
assert_deterministic(my_generator, trig)
for name, text in files.items():
    check_output(name, text)
```

`tests/test_generator_kit_third_party.py` tests a generator defined in the test with
nothing but this module, `seams` and `seams_gen.protocol`; the
[guide](../docs/guide/write-your-own-generator.md#test-it) walks through it.
`seams new-generator NAME --reference FILE` scaffolds a generator package whose test uses
this kit, from a reference output
([start from a reference output](../docs/guide/write-your-own-generator.md#start-from-a-reference-output)).

`tests/test_generator_testing.py` covers each function's pass and failure messages.

## htmx rendering rules

Every rule is keyed on a graph fact. Fixed text (doctype, the htmx CDN script, closing
tags) lives in `templates/htmx_page.html.j2`; everything else comes from the `PageModel`
that `extract_page` builds. `extract_page` is the IFML interpretation: it reads the model
only through `model.interfaces` and the views its elements link to (`model.shapes`,
`model.operations`, `model.channels`, `model.processes`, `model.lifecycles`), with
`model.compact` for curies, never raw triples (D036). `seams_gen/_views.py` turns a view's
`ResolutionError` into a `GeneratorError` naming the same subject and predicate, with the
"expected exactly one, found none" wording.

Every generator reads a shape's fields through `Shape.fields()` and names them by
`Field.name` ([ADR-0023](../docs/adr/0023-shapes-target-classes.md)): the property's
`sh:name`, else its `sh:path` local name. That name is the form control's `name`, the
JSON property of a problem schema, the key of a handler stub's `TypedDict` and the form
field a derived scenario test sends for a `verify:given` (looked up by the given's
`verify:field` path in the operation's `seam:acceptsShape`). A field's options are
`Field.options`, an `sh:in` list of literals or the `rdfs:label`s of its category
members in lifecycle order, and a flattened `sh:node` field reads as one field with the
free property's datatype, so a shape in either notation renders the same bytes
(`tests/test_shapes_categories_gen.py`, `tests/test_goldens.py`).

| Output | Graph fact |
|---|---|
| The page | The one `ifml:ViewContainer` with `ifml:isLandmark true` (none or several: error on the `ifml:InteractionModel`). `<main id>` is its local name; `<title>` is its `ifml:title`; the route comment is its `ifml:path`. |
| Header | `{# Generated by the seams htmx generator from the <trig stem> model. Do not edit. #}` then `{# model-hash: sha256:… #}` (`seams.model_hash`: TriG plus every `seam:renderPayload`). |
| Component order | Components the page `ifml:contains`, ascending by `ifml:order` (a component without one is an error). Each is a `{% block <local name> %}`. |
| `ifml:List` | `<nav aria-label="rdfs:label"><ul>`, looping `{% for item in <shape>s %}` where `<shape>` is the read shape's local name lowercased minus `Shape`. Each item shows the first `sh:order`ed datatype property that is not an identifier used by the link. |
| `ifml:Details` | `<section aria-label="rdfs:label"><ol id="<component>_items">`, looping with the singular shape name (`{% for message in messages %}`); `<li class>` is the shape's `rdfs:label` lowercased. Each `ifml:hasParameter` becomes a `data-<name>` attribute. |
| Field elements | The read shape's datatype `sh:property`s by `sh:order`: `dash:editor dash:TextAreaEditor` → `<p>`; `sh:datatype xsd:dateTime` → `<time datetime>`; anything else (including fields with options) → `<span class="<field name>">`. Object-valued (`sh:class`) properties are not rendered. |
| Swap → target | The `ifml:NavigationFlow` from the event: `ifml:swap ifml:Replace` → `hx-swap="outerHTML"`, `hx-target="#<target>"`; `ifml:Append` → `beforeend`, `#<target>_items`; `ifml:Prepend` → `afterbegin`, `#<target>_items` (the rule on `ifml:swap` in `ontology/ifml.ttl`). |
| List link | The `GET` operation that `seam:rendersComponent` the flow target gives `hx-get`: its `comm:path` `hydra:template`, each `{variable}` filled as `{{ item.<hydra:property local name> }}`. `hx-trigger` is the event's `ifml:trigger`. |
| `hx-vals` | Each `ifml:ParameterBinding` of an `ifml:DataFlow` from the List to the flow target: `"<targetParameter label>": "{{ item.<mapped property> }}"`. The parameter must be a path variable of the read operation. |
| SSE placement | A `comm:Channel` with `comm:transport comm:SSE` that the presenting container `seam:consumes` adds the htmx sse extension script to `<head>`, and a `<div hx-ext="sse">` inside the component whose `seam:reads` equals the channel's `seam:acceptsShape`: `sse-connect` from its `comm:path`, `sse-swap` from `comm:eventName`, `hx-swap="beforeend"` (the channel rule), and a comment naming the delta publisher: of the elements that `seam:publishesTo` the channel, the one that `seam:invokes` an operation, else the sole publisher (exactly one is required). |
| `seam:visibleWhen` guard | `{% if <shape>_state == "<state rdfs:label>" %}` around the component, or `{% if <shape>_state in ("<label>", ...) %}` with the labels sorted when `seam:visibleWhen` has several states. `<shape>` is the read shape's local name lowercased minus `Shape` (the rule on `seam:visibleWhen` in `ontology/seam.ttl`). Every state must be a `state:hasState` of the shape's `seam:lifecycle`. This is the only conditional a generated page contains. |
| `ifml:Form` | `<form aria-label="rdfs:label">`; the one event that `seam:submitsTo` an operation gives `hx-<hydra:method>` and the path (each variable must be a page `ifml:Parameter`). A `proc:correlationKey` variable that no component reading a shape on the page carries as a parameter (the form starts a new process instance, so `Runtime.page_context` binds nothing to it) stays literal (`/expenses/{expense}`), and an `hx-on::config-request` handler replaces it with a fresh random key on every submit. The operation must be one the presenting container `seam:consumes`. Target and swap follow that event's NavigationFlow. The button text is the event's `rdfs:label`. Comments cite `seam:triggers`, `seam:governedBy` and `seam:mediaKind`. |
| Form inputs | Only for parameters `ifml:boundTo` the `sh:path` of a datatype field of the written shape (a field with a `Field.datatype`: an `sh:datatype` property, a category or a flattened `sh:node`, bound by its outer path); the input's `name` is the field's name. A path that is no such field is a `GeneratorError` on the parameter and `ifml:boundTo`, naming the path's local name: `<label>`, then `<textarea>` for `dash:TextAreaEditor`, `<input type="datetime-local">` for `xsd:dateTime`, `<input type="text">` otherwise; `maxlength` from `sh:maxLength`, `required` from `sh:minCount ≥ 1`. Unbound properties are named in a comment as set by the runtime. |

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
| Fields | The datatype properties of the shape the form `seam:writes` that an `ifml:hasParameter` is `ifml:boundTo`, by `sh:order`. A field with options (`Field.options`: an `sh:in` list, or a category's member labels in lifecycle order) is a `<select>` with one `<option>` per option in order (`required` with `sh:minCount 1`); anything else is the page's `<input>` / `<textarea>` rule. Unbound properties get the page's "set by the runtime" comment. |
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
| Invoked-only comment | One line per operation the container `seam:exposes` that a process it executes (or an element of that process's BPMN model) `seam:invokes` and no `ifml:Event` `seam:submitsTo`, such as a `comm:PythonHandler`'s operation ([ADR-0012](../docs/adr/0012-operation-implementation.md); the expense tutorial's `:notify_manager_op`, chapter 9): `# :op is not routed: a task seam:invokes it and no ifml:Event seam:submitsTo it, so the runtime calls it in-process`. It gets no endpoint, so it needs no `hydra:method`, `seam:mediaKind` or rendered component. |
| `Runtime.load` | `"/model/<trig file name>"` with `model_hash=MODEL_HASH` (ADR-0007 rule 2). |
| Endpoints | Each element the container `seam:exposes` except its invoked-only operations, by IRI: a `hydra:Operation` or a `comm:Channel` (anything else: error on `rdf:type`). The handler name is the local name minus a trailing `_op` (GAP-21). |
| Decorator | `@router.<hydra:method lower>` (GET/POST/PUT/PATCH/DELETE); the path is the `comm:path` `hydra:template` (missing: error on `comm:path`). The operation must have `seam:mediaKind seam:UIFragment` (else error on `seam:mediaKind`) and gets `response_class=HTMLResponse`. Each `seam:governedBy` policy adds `Depends(runtime.policy("<curie>"))` to `dependencies=[…]`, and declared errors add `responses={…}` (the Errors row); with dependencies or errors the decorator is multi-line, without them single-line. |
| Signature | Each template variable as `<var>: str`, then `request: Request` when the operation has a `comm:requestMediaType`, then, for a Complete step, `identity: Identity = Depends(runtime.task_policy("<task>"))` (401 without an identity, 403 unless every `seam:governedBy` policy of the task permits it). `Identity` is imported only by a module with a Complete step. |
| Request body | `application/x-www-form-urlencoded` → `form = await request.form()`; `application/json` → `body = await request.json()`; any other media type raises `GeneratorError(op, comm:requestMediaType)`. |
| Validate | `seam:acceptsShape S` → `<s> = runtime.validate("<S curie>", form)`, where `<s>` is S's local name lowercased minus `Shape`, plus `_payload` when that name is also a path variable (so the payload never shadows the correlation key). It needs a request body. A handler with a Write or Complete step has no separate validate line: `runtime.write` and `runtime.complete_task` validate. |
| Start | When the operation is the triggering operation of a process the container executes (`Process.triggering_operations`: an event `seam:submitsTo` it and `seam:triggers` the process), `await runtime.start_process("<process>", <s>, correlation_key=<label>)`. The `proc:correlationKey` parameter's `rdfs:label` must be a path variable, else `GeneratorError(process, proc:correlationKey)`. A channel-started process ([ADR-0010](../docs/adr/0010-channel-started-processes.md): its start event, a `proc:MessageCatchEvent`, `seam:subscribesTo` a channel) gets no route; the runtime starts it when the channel is published on. An executed process with neither a `seam:triggers` event nor a subscribed start is `GeneratorError(process, seam:triggers)`. |
| Write | When no process is triggered by the operation, it has `seam:acceptsShape S`, and an event of an `ifml:Form` that `seam:writes S` (`ifml:hasEvent`) `seam:submitsTo` it (D026), `<s> = runtime.write("<S curie>", form)` in place of the validate line and before the return, so the item partial renders the stored entity. `runtime.write` validates the form itself because it first assigns the entity's `:id`, which the form never sends. Any other untriggered operation gets no write step. |
| Complete | When an event of an `ifml:Form` that a `proc:UserTask` `seam:completedOn` `seam:submitsTo` the operation (ADR-0009), `await runtime.complete_task("<task>", form, correlation_key=<key>, identity=identity)` in place of Start or Write. `<key>` is the `proc:correlationKey` label of the process whose BPMN model holds the task and must be a path variable, else `GeneratorError(process, proc:correlationKey)`. It needs a request body (error on `comm:requestMediaType`); an operation that also triggers a process, or whose forms complete several tasks, raises on `seam:submitsTo`. The serving-container rule covers the container through `seam:executes`. |
| Query | A `GET` (or an operation with a Complete step) with `seam:returnsShape S` → `<s>s = runtime.query("<S curie>", <var>=<var> …)`, one keyword per path variable. |
| Return | `runtime.render_fragment("<name>", …)` with the name from `fragment_for` (GAP-19). An item partial passes the validated `<s>` (`seam:returnsShape` must equal `seam:acceptsShape`); a component partial passes the query list `<s>s` plus `<p>=<p>` for each `ifml:hasParameter` of the component whose `rdfs:label` is a path variable. POST and other non-GET methods use the multi-line layout, GET the single-line one. |
| Errors | Each error status of the operation ([ADR-0013](../docs/adr/0013-error-shapes-and-boundaries.md): a `hydra:possibleStatus` with a `comm:errorCode`, `Operation.errors`) becomes a `responses={…}` entry keyed by its `hydra:statusCode`, preceded by a `# :status hydra:statusCode N ; comm:errorCode "c" ; seam:returnsShape :Shape` comment, with `"description"` its `rdfs:label` and `"content"` `{"application/problem+json": {"schema": …}}`. The schema is derived from the error shape: one property per field (its `Field.name`, typed `integer`, `number` or `boolean` from `sh:datatype`, else `string`), `required` the fields with `sh:minCount` > 0, and `additionalProperties: False`, as the runtime's validation is closed-world. Statuses sharing a code share one entry: labels joined with `; `, schema `oneOf` their shapes'. A status with no `hydra:statusCode` or no `seam:returnsShape` raises `GeneratorError` on the status and that predicate (`seamsh:ErrorStatusShape` catches both). |
| Problem handler | A module with any declared errors imports `JSONResponse` and `OperationError` and ends with `PROBLEM_OPERATIONS` (handler name → operation curie, one entry per endpoint with errors) and `async def problem_handler(request, exc: OperationError)`, which returns `runtime.problem(PROBLEM_OPERATIONS.get(<route name>), exc)`: the declared status and a problem+json body validated against its error shape. `seams_runtime.host` installs it as the app's `OperationError` handler. The route handlers themselves are unchanged: still no branching. A module without errors has neither, so the chat app's output is unchanged. |
| Context routes | Per `sh:NodeShape` with a `sh:targetClass` that a routed operation `seam:acceptsShape` or `seam:returnsShape` ([ADR-0024](../docs/adr/0024-json-ld-context.md) section 5): a `# :S sh:targetClass :C` comment, a `<S>_CONTEXT` string constant holding `jsonld.context_document` for the shape, byte for byte the file the `jsonld` generator writes, and `@router.get("/contexts/<S local name>.jsonld")` with handler `<s>_context` returning it as `application/ld+json`. One route per context, sorted by path, with no branching. A context path or handler name that another route or an `ifml:path` already has raises `GeneratorError(<shape>, sh:targetClass)`. |
| Link header | An operation whose `seam:returnsShape` has a target class keeps the rendered fragment as `response`, sets `response.headers["Link"] = '</contexts/<S>.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'` (the value computed in `extract`) and returns it. Problem+json and 422 responses carry none. |
| SSE channel | `comm:transport comm:SSE` → `@router.get(path)`, `async def <name>(<var>: str) -> StreamingResponse`, `events = runtime.subscribe("<curie>", scope=<var>)` with the single path variable, and `StreamingResponse(events, media_type="text/event-stream")`. Any transport other than SSE or `comm:SemPKMWebhook` raises `GeneratorError(channel, comm:transport)`; not exactly one path variable raises on `comm:path`. |
| SemPKM webhook channel | `comm:transport comm:SemPKMWebhook` ([ADR-0027](../docs/adr/0027-sempkm-webhook-channel.md)) → `@router.post(path, status_code=202, response_class=JSONResponse)`, `async def <name>(request: Request) -> JSONResponse`, `return await runtime.receive_webhook("<curie>", await request.body())`. The path is the channel's variable-free `comm:path`. The facts come from `ModelGraph.webhook_channel`, so each fault raises `GeneratorError` on the subject and predicate that the runtime's `ResolutionError` names (event type, accepted shape, its SemPKM store and class, path, receiving container, subscribers, bindings, and the writes rule). A header comment states the transport, `comm:eventName` and `seam:acceptsShape`. The module then imports `JSONResponse`. |

## JSON-LD rendering rules

`extract_jsonld(model)` builds a frozen `JsonLdModel`, one `Context` per shape with a
`Shape.target_class`, sorted by file name; `render_jsonld` writes each with
`context_document(ctx)` (`json.dumps`, sorted keys, two-space indent, trailing newline,
no header or model hash: `seams.lock` says where it came from), which the FastAPI
generator also embeds. The rules are
[ADR-0024](../docs/adr/0024-json-ld-context.md)'s:

| Output | Graph fact |
|---|---|
| Document | `{"@context": {"@version": 1.1, …}}`, full IRIs, no prefixes and no top-level `@vocab`. |
| Class term | The target class's local name mapped to its IRI. A field with the same name raises `GeneratorError(<shape>, sh:targetClass)`. Two fields of one shape with one name raise `GeneratorError(<shape>, sh:name)`. |
| Datatype field | `Field.name` → `{"@id": <sh:path>, "@type": <sh:datatype>}`, `xsd:string` included; a field with no datatype gets only `@id`. |
| Category field | `Field.members` set: `{"@id": <path>, "@type": "@vocab", "@context": {<label>: <member IRI>, …}}`, so the wire value stays the label. A label that is empty, starts with `@` or holds `:` raises `GeneratorError(<member>, rdfs:label)`. |
| Flattened and reference fields | A `sh:node` field (`Field.node`), or a reference field (`Field.reference`: an `sh:class` of a class that is not a category), maps to `null`: a context never states a triple the shape would reject. |
| File names | Two target-classed shapes with one local name raise `GeneratorError(<shape>, sh:targetClass)`. A view `ResolutionError` is passed on as the `GeneratorError` on the same fact. |

## Mental Model rendering rules

`extract_mentalmodel(model)` builds a frozen `MentalModel`: the `Manifest`, and one
`Document` per entrypoint (`ontology`, `shapes`, `views`) holding its `@graph` nodes and
sources. `render_mentalmodel` writes `manifest.yaml` with `manifest_text` and each
document with `document_text` (`json.dumps` of `{"@graph": […]}`, sorted keys, two-space
indent, trailing newline; no header or model hash). The rules are
[ADR-0026](../docs/adr/0026-mental-model.md)'s:

| Output | Graph fact |
|---|---|
| The package | Written for the model's one `seam:Model` with `seam:notation seam:Ontology`. None raises `GeneratorError(seam:Ontology, seam:notation)`; several raise on the second, `seam:notation`. |
| `modelId` | The ontology IRI's local name, lowercased, `_` replaced by `-`; one that does not match `^[a-z][a-z0-9-]*$` or is not 2 to 64 characters raises `GeneratorError(<ontology>, rdf:type)`. It names the three entrypoints, `<kind>/<modelId>.jsonld`, and the namespace `urn:sempkm:model:<modelId>:`. |
| `version`, `name`, `description` | The ontology's one `owl:versionInfo` (`MAJOR.MINOR.PATCH`), one `rdfs:label` (1 to 200 characters) and at most one `rdfs:comment` (at most 2000; omitted when absent). Otherwise `GeneratorError(<ontology>, owl:versionInfo / rdfs:label / rdfs:comment)`. Keys in the order `modelId`, `version`, `name`, `description`, `namespace`, `entrypoints`, every value a JSON string, so YAML reads it as a double-quoted string. No other key is written. |
| Package IRIs | The ontology node, the written shapes and the views are `urn:sempkm:model:<modelId>:<local name>`, each with `prov:wasDerivedFrom` its model term; domain terms keep their IRIs and appear only as objects. Two terms with one local name raise `GeneratorError(<second by IRI>, rdf:type)`. |
| Ontology file | One `owl:Ontology` node: `rdfs:label`, `owl:versionInfo`, `rdfs:comment` when stated, each `owl:imports`, and `prov:wasDerivedFrom` the `owl:versionIRI`. A gistCore import other than `gistCore14.0.0` raises `GeneratorError(<ontology>, owl:imports)`. |
| Shapes file | Each shape with a `sh:targetClass` and each shape those reach by `sh:node`, transitively, typed `sh:NodeShape`: every triple whose predicate is in the SHACL namespace, or is `rdfs:label` or `rdfs:comment`, and the same for the blank nodes those reach. RDF lists are `{"@list": […]}`, `sh:property` values in `Shape.fields()` order (`sh:order`, none last, then path), other multi-valued properties by value, and a `sh:node` to a written shape is its package IRI. `seam:` facts are not copied. |
| Views file | One `urn:sempkm:vocab:ViewSpec` per `ifml:List` or `ifml:Details` that `seam:reads` a shape: `rdfs:label` the component's, `targetClass` the shape's `sh:targetClass`, `rendererType` `"table"`, `columns` the `Field.name`s joined by `,`, and `sparqlQuery` `SELECT ?s ?<name> … WHERE { ?s a <class> . OPTIONAL { ?s <path> ?<name> } … }`, a flattened field as `OPTIONAL { ?s <path> [ <free path> ?<name> ] }`. A component reading several shapes raises `GeneratorError(<component>, seam:reads)`, a shape with no target class `GeneratorError(<shape>, sh:targetClass)`, and a field name that is not a SPARQL variable `GeneratorError(<shape>, sh:name)`. |
| Literals | `xsd:string` as a plain string, a language-tagged literal as `{"@value", "@language"}`, any other as `{"@value", "@type"}`; IRI objects as `{"@id": …}`. |

A view `ResolutionError` is passed on as the `GeneratorError` on the same fact.

## Compose rendering rules

The generator writes one file per `arch:Environment` of the model
([ADR-0015](../docs/adr/0015-environments.md)): `generate_compose_environments(trig,
base_dir=None)` returns `{compose.<environment local name>.yaml: text}` in environment
IRI order, and the CLI writes exactly those files; there is no `compose.yaml`. A model
with no `arch:Environment` raises `GeneratorError(<model file>, rdf:type)`, and so do two
environments with one local name; this is generator-only, not a shape, because models
without a compose target (the expense chapters 1 to 7) need no environment.

`extract_compose(model, base_dir, environment)` builds a frozen `ComposeModel` for one
environment, given as the `Environment` view, its IRI or its local name (an unknown one:
`GeneratorError(<model file>, rdf:type)` naming the declared ones); `render_compose`
renders it through `templates/compose.yaml.j2` (same environment, no domain literals).
`generate_compose(trig, environment, base_dir=None)` defaults `base_dir` to the working
directory; the CLI passes `--out` (D018). The bind-mount sources and `SEAMS_MODEL` follow
the TriG path it is given, so a model under another path or stem mounts and names that
file; the runtime reads `SEAMS_MODEL` in preference to the path in the generated route
module (see [seams_runtime/README.md](../seams_runtime/README.md)). Every value is
pre-rendered as a YAML scalar: plain when `yaml.safe_load` reads it back as the same
string, otherwise JSON double-quoted.

It reads `model.architecture`: `System.containers` and each `Container`'s
`for_environment(env)` (its `artifact`, `bindings` and `replicas` under the override
rule: an override's artifact or replicas replaces the shared one whole, its bindings
replace or add by `deploy:key`, and a silent override keeps the shared fact), plus the
shared `ports`, `deploy_depends_on`, `volumes`, `healthcheck`, `proxies` and
`deployed_to`. An override that breaks the rule (two for one environment, a store that
changes, a predicate an override cannot carry) is a `GeneratorError` on the container
and that predicate. Ports, volumes and bindings are blank nodes, so their errors name the
container.

| Output | Graph fact |
|---|---|
| Header | `# Generated by the seams compose generator from the <trig stem> model. Do not edit.`, then `# model-hash: sha256:…` (`seams.model_hash`), then `# environment: <environment IRI>`. |
| `name` | The project name: the `arch:System`'s local name, lower-cased, so two apps never share volumes. |
| Services | The `arch:Container`s that the one `arch:System` `arch:contains`, by IRI, named by local name (none or several systems: `GeneratorError(<model file>, arch:contains)`). SemPKM's containers ([ADR-0025](../docs/adr/0025-sempkm-store.md) section 10) are services too when the system does not contain them: a `deploy:storeKind deploy:SemPKM` store that a contained container is, or reaches through a `deploy:connectsTo` or `deploy:authenticatesTo` binding of the environment, and each container that store `arch:dependsOn` (its triplestore, its frontend). Only a SemPKM store brings in what it `arch:dependsOn`. Each takes the image, ports, volumes, healthcheck and start order its own facts give it, so nothing about SemPKM is hard-coded and a missing `deploy:artifact` is the usual error on that container; its trace origins name the container or store that brought it in. The URL binding renders like any `deploy:value` or `deploy:serviceOf` binding and the token binding like any secret, as for PostgreSQL. Keys in the order `image`, `build`, `pull_policy`, `command`, `ports`, `expose`, `depends_on`, `environment`, `secrets`, `volumes`, `healthcheck`, `deploy`. |
| `image` | The environment's `deploy:artifact`: `<deploy:reference>:<deploy:version>` (missing: error on the container and `deploy:artifact`). |
| `build` / `pull_policy` | An artifact with a `deploy:build`: `build.context` is `deploy:context` (relative to the model file's directory) rewritten relative to `--out`, `build.dockerfile` is `deploy:dockerfile` (relative to the context, as in Docker), and `pull_policy: build`. There are no build args: the serving container's `deploy:dockerfile` names the file the `dockerfile` generator writes, with the app's paths literal. An artifact without a build is pulled. |
| `command` | A container that `deploy:proxies` another: `caddy reverse-proxy --from :<its single deploy:containerPort> --to <target>:<target's single deploy:containerPort>` (not one port, or a target outside the system: error). |
| `ports` / `expose` | Each `deploy:port`: with `deploy:publishedPort` → `ports: - "pub:cont"`; without → `expose: - "cont"`. |
| `depends_on` | Each `deploy:dependsOn` target by local name (not `arch:dependsOn`), with `condition: service_healthy` when the target has a healthcheck (a `deploy:healthcheck`, or the serving container's probe) and `service_started` otherwise; a target outside the system is an error. |
| `environment` | For the serving container (the FastAPI rule above; at most one, else `GeneratorError(<model file>, seam:executes)`), first `SEAMS_MODEL: /model/<trig name>` and `SEAMS_MODEL_HASH`. Then each binding of the environment, by `deploy:key`: `deploy:value` → `KEY: value`, or `KEY: ${KEY:-value}` in the environment whose local name is `development`, so a host can override it; `deploy:secretRef` or `deploy:secretFile` → `KEY_FILE: /run/secrets/<key lower>`; `deploy:serviceOf S` → `KEY: http://<S>:<S's single deploy:containerPort>`. None or several kinds: error on the container and `deploy:binding`, naming the key. |
| `secrets` | Each `deploy:secretRef` binding adds `<key lower>` to the service and a top-level `<key lower>: {name: <deploy:secretName>, external: true}` (missing `deploy:secretName`: error on the container, naming the key). Each `deploy:secretFile` binding adds `<key lower>: {file: ${<KEY>_FILE:-<path relative to --out>}}`, so a host can point elsewhere. One key bound to two sources in one environment is an error. |
| `volumes` | For the serving container, read-only model binds first: `./<trig relative to --out>:/model/<trig name>:ro`, then each `seam:renderPayload` as `./<payload relative to --out>:/model/<path relative to the trig dir>:ro` and, when an operation that container `seam:exposes` is `seam:implementedBy` a `comm:PythonHandler` ([ADR-0012](../docs/adr/0012-operation-implementation.md)), the handlers package `./<handlers/ beside the trig, relative to --out>:/model/handlers:ro` (the runtime's default handlers directory), all sorted. Then each named `deploy:volume` as `<volumeName>:<mountPath>`, with a top-level `<volumeName>: {}`. |
| `healthcheck` | `deploy:healthcheck`: `test: ["CMD-SHELL", "<deploy:probe>"]`, `interval: <deploy:interval>`. The serving container without one gets the runtime's `/healthz` probe on its single `deploy:containerPort` (not one port: error), interval `5s`. Every healthcheck has the fixed `timeout: 5s`, `retries: 12` and `start_period: 5s`. |
| `deploy` | `replicas` from the environment's `deploy:replicas`; the serving container is capped at 1 (backlog A10: process state lives in the process), with a comment naming the declared count. `placement.constraints: - node.labels.seams.node == <rdfs:label>` of the one `seam:deployedTo` node, only in the environment that `arch:contains` that node (no label there: error on the node and `rdfs:label`). |
| Top level | `secrets:` and `volumes:` after `services:`, sorted, omitted when empty. |

## Tests rendering rules

`extract_tests` (`tests.py`) builds a `TestsModel`; `render_tests` renders it through
`templates/tests_scenarios.py.j2`, `tests_decisions.py.j2`,
`tests_shape_examples.py.j2` and `tests_policies.py.j2`, which share `tests_header.py.j2` and
`tests_project.py.j2`. Every value is pre-rendered as a Python literal in `extract`, so
the templates hold only the fixed calls into `seams_runtime.verify`, the harness the
generated files run on.

| Output | Graph fact |
|---|---|
| Header | `# Generated by the seams tests generator from the <trig stem> model. Do not edit.` then `# model-hash: sha256:…`. `MODEL_HASH` repeats it, and `load_model` refuses a model with another hash ("regenerate") |
| Project | Fixed lines: the nearest `seams.toml` above the file (`seams_cli.project.find_project`) gives the model and the `out` of its `fastapi` and `htmx` generators |
| `test_scenario_<local name>` | One per `verify:Scenario`, by IRI. The start `Request` is the one operation `Process.triggering_operations` gives (its `hydra:method` and `comm:path` template), sent as `verify:actor` with each `verify:given` as a form field (the name of the field of the operation's `seam:acceptsShape` whose path is the `verify:field`, else its local name, and the value's lexical form, by field IRI). Each `verify:step`, in list order, is the operation an event of the form its task `seam:completedOn` `seam:submitsTo`, sent as the step's actor. `key_variable` is the process's `proc:correlationKey` label; the key is the scenario's local name. `verify:expectState` asserts the stored status of the shape whose `seam:lifecycle` holds the state equals the state's `rdfs:label`; `verify:expectEndEvent` asserts the run's trace reached that IRI. The run must not fail |
| `test_decision_<local name>` | One per `verify:DecisionExample`, by IRI: `Engine.decide` on the decision with each given as input, then one assertion per `verify:expectOutput` (by `dec:variable`), comparing with the literal's Python value |
| `test_valid_example_<shape>_<node>` / `test_invalid_example_<shape>_<node>` | One per example, shapes by IRI, valid before invalid, nodes by IRI: pyshacl on the node's description against the shape's description with `sh:targetNode` the node, so no other shape takes part |
| `<POLICY>_<TARGET>` | One `Target` per `odrl:permission`, policies by IRI, permissions by (target, action, assignee). It is reached as the first scenario (by IRI) reaches it: the scenario whose start operation is the target (`at=0`), or whose step `at` completes the target user task, after the start and the earlier steps. With no such scenario, the target's operation (the target itself, or the one operation an event of the form the task `seam:completedOn` submits to) is sent at once with no form fields and every path variable set to the policy's local name |
| `test_policy_<policy>_<target>_allows_<party>` / `…_denies_<party>` | One per permission for each `odrl:Party` in the model, by IRI: the assignee (every party, for no assignee or an `odrl:PartyCollection`) is allowed, answered 200 (or, without a reaching scenario, anything but 401 or 403); every other party is answered 403 with a `PolicyDenied` detail naming the policy, and the store's instances and open tasks are unchanged |
| `test_policy_<policy>_<target>_denies_no_identity` | One per permission: no identity headers, answered 401 with a `PolicyDenied` detail naming the policy, store unchanged |

So `test_policies.py` holds parties × permissions tests plus one no-identity test per
permission. A permission whose target no route enforces (no `seam:governedBy`) fails its
denials, which is the point. A target governed by two policies is tested against this
permission alone: a party it admits that the other policy refuses fails its allow test.

A party acts as user and role `<party local name>` (`seams_runtime.verify.identity`),
which `RoleEvaluator` admits for a permission assigned to that party. A request not
answered 200, a step whose task is not open, a path variable other than the
correlation key, or a run that does not settle within the timeout fails the test with
a `ScenarioError` naming the scenario and the step.

**Errors.** The ADR-0014 shapes (`seamsh:ScenarioShape`, `GivenShape`,
`DecisionExampleShape`, `ExpectOutputShape`) flag every malformed `verify:` fact the
generator rejects: a missing process, actor, task or expectation, a given without one
field and one literal value, a decision example without an output. Generator-only,
because they are routing facts the `fastapi` generator needs as well: exactly one
serving route module when the model has scenarios; exactly one operation starting a
scenario's process, and exactly one completing each step's task, with a
`hydra:method` and a `comm:path`; a step's task `seam:completedOn` a form; a
permission's `odrl:target` that is missing, or neither a `hydra:Operation` nor a user
task completed on a form with one submitting operation (ADR-0009 policy targets, which
the shapes do not type); and two IRIs whose local names would give two tests the same
name.

## Smoke rendering rules

`extract_smoke` (`smoke.py`) builds a `SmokeModel` with one `ProbeModel` per operation;
`render_smoke` renders it through `templates/tests_smoke.py.j2`, which shares
`tests_header.py.j2` and `tests_project.py.j2` with the tests generator. Every value is a
Python literal prepared in `extract`; the template holds the fixed fixtures and the
calls into `seams_runtime.verify` (`smoke`, `smoke_skip`, `smoke_caller`).

| Output | Graph fact |
|---|---|
| Header | `# Generated by the seams smoke generator from the <trig stem> model. Do not edit.` then `# model-hash: sha256:…`; `load_model` refuses a model with another hash |
| `caller` fixture | Fixed: `SEAMS_SMOKE_BASE_URL` is the app; `SEAMS_SMOKE_USER` and comma-separated `SEAMS_SMOKE_GROUPS` are sent as `X-Forwarded-User` / `X-Forwarded-Groups`. Without a base URL every test is skipped, or fails under `SEAMS_E2E=1` |
| Comment | `<operation> <METHOD> <hydra:template> -> <seam:returnsShape>` (`(seam:UIFragment)` for a fragment), one line per error status (`<hydra:statusCode> -> <its seam:returnsShape>`) and one per governing permission (`governed by <policy> (odrl:assignee <party>)`) |
| `<LOCAL NAME>` = `Probe(...)` | One per `hydra:Operation` with a `hydra:method` (upper-cased) and a `comm:path`, by IRI. `path`: each `hydra:variable` replaced by the URL-quoted value its `hydra:property` has on the first `verify:validExample` (by IRI) of the accepted shape, else of the returned shape. `data`: for an operation that accepts a shape and is not a GET or HEAD, each field value of the accepted shape's first valid example (`Shape.example_values`), by field order. `json`: false for a `seam:UIFragment`. `returns`: the `seam:returnsShape`. `errors`: each `hydra:possibleStatus` with a `comm:errorCode`, as (`hydra:statusCode`, its `seam:returnsShape`), by code. `policies` / `parties` / `any_party`: the policies (CURIEs) of each `odrl:permission` whose `odrl:target` is the operation or a user task completed on a form that submits to it, their assignees, and whether one admits any authenticated party (no assignee, or an `odrl:PartyCollection`). `skip`: why it cannot be sent, when a path variable or the body has no example value |
| `test_smoke_<local name>` | Skipped with `smoke_skip`'s reason (the probe's own, or "`<policy>` does not admit `<identity>`; it admits `<parties>`"), else `smoke(model, probe, caller)`: a 2xx answer passes, with a JSON body that conforms to `returns` unless `json` is false; any other status must be one of `errors`, with a JSON body that conforms to its shape. The assertion message names the method, URL, identity and status, and pyshacl's report |

Operations with a path but no method (an operation the runtime calls, like a handler's)
are left out. A JSON body is validated by `response_conforms`: each object is a node, each
key that is a field's name a triple on its path, typed with the field's `sh:datatype`,
checked against the shape's lowered contract graph (`seams_runtime.contracts`).

**Errors.** Generator-only, as for the tests generator: a permission's `odrl:target` that
is missing, or neither a `hydra:Operation` nor a user task completed on a form with one
submitting operation; and two operations whose local names would give two tests the same
name. An error status without a `hydra:statusCode` is `GeneratorError(status,
hydra:statusCode)`, which `seamsh:ErrorStatusShape` also flags. A path variable or body
with no example value is not an error: the test is generated and skipped with the reason.

## Acceptance rendering rules

`extract_acceptance` (`acceptance.py`) reads every `comm:PythonHandler` function through
`stubs.extract_stubs`, grouped into the stub generator's modules, and builds one
`Handler` value (`seams_runtime.verify.Handler`) per function: its `comm:handler` path,
implementation and, per operation (by IRI), the (field, required) pairs of the stub's
TypedDicts. `render_acceptance` renders each module through `templates/acceptance.py.j2`
to `test_<module>.py` (the module path with `/` as `_`). The template holds the fixed
fixtures and one call per test into `seams_runtime.verify`; the expected decision routing
is not computed here but evaluated at test time from the BPMN flow conditions (ADR-0007).

| Output | Graph fact |
|---|---|
| Header | `# Generated by the seams acceptance generator from the <trig stem> model. Do not edit.` then `# model-hash: sha256:…`; `load_model` refuses a model with another hash. The model and handlers package come from the project's `seams.toml` |
| `test_types_<fn>` | `handler_types`: one entity parameter annotated `dict` or a TypedDict with the accepted shape's keys and required-ness; the return `dict`, such a TypedDict of the returned shape, or `None` for an operation with no `seam:returnsShape` |
| `test_shape_<fn>_<example>` | `handler_result`, per `verify:validExample` of each operation's `seam:acceptsShape`: the result conforms to `seam:returnsShape` under the runtime's validator, or the handler raises an `OperationError` whose code is one of the operation's `hydra:possibleStatus` |
| `test_transition_<fn>_<task>` | `transition_guard`, per `proc:ServiceTask` that `seam:invokes` the operation and `seam:fires` a transition: the lifecycle guard runs the task in `state:from`, moves the entity to `state:to`, and refuses it in every other state. A task that fires none gets no transition test |
| `test_decision_<fn>_<example>` | `decision_route`, per `verify:DecisionExample` of a decision in the task's process: run in process with the handlers package, the task is reached exactly when the example's expected outputs take a gateway flow into it (and, for a task with no transition, its run fires nothing) |

Every assertion message is the check's detail and names the model fact (shape, state,
transition, rule or example IRI). Each test file gets a trace sidecar (ADR-0019) citing the
shape, transition and decision each test derives from. CI runs chapter 9's generated
acceptance tests against `handlers/notify.py` through `tests/test_expense_derived_tests.py`.

**Errors.** Generator-only: two functions or tests that would get one name is
`GeneratorError(implementation, comm:handler)`; everything else the stub generator rejects
is caught by the shapes first.

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
| `compose` | `compose.<environment>.yaml` | the `arch:Environment`, the `arch:System` and each `arch:Container` it `arch:contains` |
| `tests` | `test_scenarios.py` | each `verify:Scenario`, its `proc:Process` and the `proc:UserTask` of each step |
| `tests` | `test_decisions.py` | each `verify:DecisionExample` and the `dec:Decision` it evaluates |
| `tests` | `test_shape_examples.py` | each `sh:NodeShape` with examples and each example node |
| `tests` | `test_policies.py` | each `odrl:Policy`, each permission target, each `odrl:Party` and each scenario that reaches a target |
| `smoke` | `test_smoke.py` | each operation with a method and a path, the shapes it accepts and returns and its error statuses' shapes, each example node it sends or fills a path from, and each governing `odrl:Policy` and its assignee |
| `acceptance` | `test_<module>.py` | each handler function's implementation, operations and shapes, each example node, each invoking task with its transition and states, and each decision example with its decision and process |

## Generation traces

`trace.py` ([ADR-0019](../docs/adr/0019-generation-trace.md)) holds `Trace` (`output`,
`generator`, `lines`) and `TraceLine` (`line`, `templates`, `terms`), and
`render_trace_json(trace)`, the `<output>.trace.json` sidecar text: sorted-key JSON, two-space
indented, ending in a newline, with `trace_version` 1. A trace has one line per
non-blank output line; `templates` are `<template file>:<line>`, outermost include
first, and `terms` are full model IRIs, sorted.

A trace is a second render of the same view model with a `TracingEnvironment`
(`htmx._tracing_environment()`: the shared options of `htmx._environment()`). Its
extension's `filter_stream` adds a line sentinel to each piece of template text and a
span around each `[[ expression ]]` and `[% include %]`; block-only and comment lines
emit no text and get none. Its `getattr`/`getitem` tag a plain `str` read off a view
object with an `iri` field (or an object reached from one) with that object's IRIs,
`view_iris(obj)`: the `iri`, then its `origins`, the sorted IRIs of the further model
elements its extraction read (the shapes, flows, processes, policies and so on the line
was derived from). Like `iri`, an origin is a model element, a subject of the model, so
it can be a `seams.lock` source. Its `finalize` emits a term sentinel per IRI before
each tagged value. The view objects with an `iri`: `PageModel`, `Component`, `Field`,
`Flow`, `Link`, `Stream`, `Submit`, `Input` and `TaskForm` (htmx); `RouteModule`,
`Endpoint` and `NotRouted` (fastapi); `ComposeModel`, `Service` and `Dependency`
(compose). A value a template filters, joins or concatenates loses its tag (value-level
spans wait for backlog T2).

`trace_template(env, template, context, output=, generator=, expected=, fallback=)`
strips the sentinels and requires exactly `expected`, the normal render, so templates
need no change. A line no term sentinel lands on takes the terms of its innermost
include that has any (the included component's), else `fallback`: the `view_iris` of the
page, fragment component, task form, serving container or `arch:Environment`.

`tests/test_generation_trace.py` checks the traces against the golden markers: on every
golden line that matches a generated line once its marker is stripped, each model element
(a subject of `chat-app.trig`) a `[graph: ...]` marker cites must be in the line's terms or in those of the include it
is in (a line-level trace records no loop scope), and each `[fixed]` line needs a
template origin. A cited element the generator does not read is listed in the test's
`KNOWN_GAPS`, with a backlog question. It raises
`GeneratorError`, writing nothing, when:

| Case | Subject | Detail |
|---|---|---|
| The normal render already holds a sentinel character (U+E000, U+E001) | the template | `line <n> of <output> already holds a trace sentinel character` |
| The stripped render differs from the normal one (say, a filter block over template text) | `<template file>:<line>` of the first differing line | `the traced render of <output> differs from the normal render at line <n>` |
| A non-blank line has no template origin | the template | `line <n> of <output> has no template origin` |

The predicate of each is `trace`.

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
python -m seams_gen.sequence examples/chat-app/chat-app.trig :send_message --out build/sequences \
    --trace tests/fixtures/traces/chat_send_message.json
# -> build/sequences/send_message.executed.mmd (--trace <instance id> --db seams.sqlite reads a stored run)
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

## Handler stubs

```
python -m seams_gen.stubs app/model.trig
# -> app/handlers/__init__.py, app/handlers/notify.py and a .trace.json beside each
#    (absent files only, each printed)
python -m seams_gen.stubs app/model.trig --handlers path/to/handlers
```

`seams_gen.stubs` writes a starting point for hand-written code under
[ADR-0012](../docs/adr/0012-operation-implementation.md)'s regeneration rule (D050). For
each `comm:PythonHandler` an operation is `seam:implementedBy`, it writes the module its
`comm:handler` names into the handlers package, `handlers/` beside the model file by
default (the runtime's default too; the runtime also reads `SEAMS_HANDLERS`, this command
only `--handlers`). It is not a `GENERATORS` entry: `seams generate` does not run it and
`seams.lock` does not record its files, because they are owned code from the moment they
exist.

**Write once.** A file that exists is never opened for writing (files are created with
mode `x`). A module that exists but does not bind a function the model names, or does not
parse, is reported on stderr as `<implementation IRI>: <comm:handler IRI>: ...` and left
alone; adding the function is the owner's edit. Existing files are read with `ast`, never
imported. A model with no `comm:PythonHandler`, such as the chat app, writes nothing, not
even the package.

| Graph fact | Stub |
|---|---|
| `comm:handler "a.b.f"` | function `f` in `a/b.py`; `a/__init__.py` and the package `__init__.py` are created when absent. A module that is also a package prefix is that package's `__init__.py`; a one-segment path is a function of the package `__init__.py` (as the runtime imports them). Functions of one module are sorted by name |
| Header | `# Generated once by the seams handler stub generator from the <stem> model.`, the owned-code line, `# model-hash: sha256:…` and `# context-hash: sha256:…`. The context hash is the invoking `proc:ServiceTask`'s `Manifest.context_hash` from [`seams.context_for`](../docs/reference/seams-library.md#context-assembly); with several invoking tasks it is `sha256` over their sorted hashes, each followed by a newline; with none the line is left out. A package `__init__.py` with no functions is the header alone |
| `seam:acceptsShape`, `seam:returnsShape` | one `TypedDict` per shape the module's functions use, named after the shape's local name, after `from typing import NotRequired, TypedDict` (`NotRequired` only when a field needs it). One key per `sh:property`, in `Shape.fields()` order: the field's name (`sh:name`, else the `sh:path` local name) |
| `sh:datatype` of a property | the key's type: `xsd:string` → `str`, `xsd:integer` → `int`, `xsd:decimal` and `xsd:double` → `float`, `xsd:boolean` → `bool`, `xsd:date` and `xsd:dateTime` → `str`. A category field reads as `xsd:string` (`str`) and a flattened `sh:node` field takes its free property's datatype; a property still without a datatype (a reference `sh:class`) holds an IRI: `str` |
| `sh:minCount` absent or `0` | the type wrapped in `NotRequired[…]` |
| Signature | `def f(entity: <Accepts>) -> <Returns>:` with the shape classes; `entity: dict` when an operation has no `seam:acceptsShape`; `-> None` when no operation the handler implements has a `seam:returnsShape`, `-> <Returns> \| None` when only some do |
| Docstring | `comm:handler "<path>" of <implementations> (comm:PythonHandler).`, then per operation: `Implements <op> (seam:implementedBy <impl>).`, the `seam:acceptsShape` the entity is and the `seam:returnsShape` the result must be |
| `seam:invokes` from a `proc:ServiceTask` | docstring lines from the task's `context_for` manifest: `Invoked by <task> (seam:invokes), a proc:ServiceTask of <process>.`, `Decided by <decision> (seam:decidedBy): …` for each decision it lists, and `Fires <transition> (seam:fires): <from> -> <to>.` for the transition the task fires. No lines when no task invokes the operation |
| Body | `raise NotImplementedError("<path>: write the handler for <operations>")`, so a stubbed operation fails its instance (naming the operation and `PythonHandler`) until it is written |
| Trace | `<module>.trace.json` beside each written module ([ADR-0019](../docs/adr/0019-generation-trace.md), generator `stubs`): every line cites the model IRIs behind it. Fields cite their `sh:path`, shape and operations; class lines their shape; the signature, summary and body the implementations, operations and shapes; each docstring line the task, decision or transition it names (with its process, task or states); header lines every IRI of the module's functions. Written once, only when its module is, and not recorded in `seams.lock` |

**Errors.** A fact `ModelGraph.operation_implementation` rejects (several
`seam:implementedBy`, a missing or unknown kind, a missing or non-identifier
`comm:handler`) is a `GeneratorError` naming the same subject and predicate: exit **2**,
nothing written. So is a property whose `sh:datatype` is not in the type table
(`GeneratorError(shape, sh:datatype)`, naming the property and the mapped datatypes), two
properties of a shape with the same field name, a shape local name or field name that
is not a Python identifier, two shapes of one module with the same local name, and a
shape whose local name is also a function of its module. `seamsh:HandlerShapeShape` in
`ontology/shapes/seam-shapes.ttl` states each of these for the shapes a
`comm:PythonHandler` operation accepts or returns, so a model that passes the shapes
writes its stubs (the parity cases are in `tests/test_shape_generator_parity.py`). A
`ResolutionError` from `context_for` becomes a `GeneratorError` with the same subject and
predicate. A model that does not parse also exits 2. A model file that cannot be
read or a handlers path that cannot be written exits **1**. Reports exit 0.

Owned handlers are not in ruff's `extend-exclude`: they are linted and tested like any
other code. The golden is `tests/golden/handler_stubs/notify.py` (plain text, with the
`sha256:<model-hash>` and `sha256:<context-hash>` placeholders `golden_target` fills).

```python
from seams import ModelGraph
from seams_gen.stubs import extract_stubs, plan_stubs, render_module, write_stubs
stubs = extract_stubs(ModelGraph.load("model.trig"))
plan = plan_stubs(stubs, "handlers")   # plan.writes: ((path, text), ...), plan.reports
write_stubs(plan)
```

## Tests

Templates hold text, not logic: a `[[ ]]` tag outputs an attribute path (optionally
`|e`), and a `[% %]` tag loops or branches on a bare path, closes a block, includes a
template by name or sets a name to a path. Everything else is computed in `extract`.
`tests/test_template_logic.py` scans every `templates/*.j2` and names the template, line
and expression of any tag that breaks the rule; its `computing_expressions(text)` scanner
is reusable on any template text.
`tests/test_htmx_fragments.py` covers the fragment names, the header-plus-page-lines
equality, a render of each partial, the CLI, the swap and `submitsTo` mutations and the
`seam:rendersComponent` errors. Also `tests/test_golden_target.py` (the stripping rule), `tests/test_generator_testing.py` (the test kit)
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
`tests/test_problem_json.py`: a chat-app copy whose `:send_message_op` declares three
error statuses (two sharing 422) generates one `responses` entry per status code with
the shape-derived schemas, the problem handler and its imports, and fails on a status
missing its code or shape; served through `seams_runtime.host`, an `OperationError`
answers with the declared status and a validated `application/problem+json` body, and
a malformed body or an undeclared code answers 500 naming the status or operation.
`tests/test_human_task_generators.py`: for the approval fixture
(`tests/fixtures/human_task/approval.trig`), the completion handler (task_policy
dependency, correlation key, `complete_task`, no validate), the task curie expanding to
the governed IRI, `Identity` imported only when needed, the generated module compiling
and answering 401/403 through `seams_runtime.host`, the task form partial (hx-post with
the key, one field per bound property, `sh:in` as a `<select>`, the task label and
entity, escaping), the completion partial, determinism, and the key-not-a-path-variable,
no-process, no-body and two-tasks errors.
`tests/test_compose_generator.py`: byte equality with the `compose.development.yaml`
and `compose.production.yaml` goldens, one file per environment in IRI order, the
header (hash and environment) and project name, determinism, no domain literals in the
template, the parsed structure of both files (read-only model binds, external secrets
in production; builds, secret files, `${KEY:-value}` and no placement in development),
healthchecks and `depends_on` conditions, the proxy command, the replica cap, paths
following `base_dir`, replicas/override-replicas/published-port/node-label/`deployedTo`/
environment-placement/quoted-value/healthcheck/proxy mutations, missing artifact,
`deploy:secretName`, node label, single ports, unknown or missing environments, two
environments with one name, override faults and one secret from two sources failing
through the API (and the first three through the CLI, which then writes no file), the
CLI writing exactly the two files, and `docker compose config -q` accepting both
(skipped when docker compose is not installed).
`tests/test_handler_stubs.py`: byte equality with the stub golden, the runtime loading
the stub, a second run leaving owned files byte-identical, the missing-function and
unparseable-module reports, nested packages, `-> None` without a returns shape,
determinism across hash seeds, the chat app writing nothing, and exit 2 (bad handler
path, bad kind, nothing written) and 1 (missing model, unwritable directory).
`tests/test_complexity.py`: the chat app (0 / 3 / 60, two failures), checkout and
expense chapter 8 (4 / 6 / 115, passing, also through the CLI) scores,
determinism, the ontology not being loaded, a synthetic passing model and its
one-short-of-each-threshold boundary, an empty model, the CLI's exit codes 0, 1 and 2
(missing file, invalid TriG, a directory), and the complexity queries staying out of
the top level of `docs/queries/`.

`tests/test_smoke_gen.py`: on chapter 9, one smoke test per operation with a method and
a path, by IRI, byte-identical across runs under the model-hash header, and a skip naming
the path variable no example fills; on a copy whose example has an `:id`, the submit
operation skipped for a manager with a reason naming `:employee_submit_policy`, and the
generated probes passing against the real app; `smoke` against stub answers (a valid
and an invalid JSON body, HTML for a JSON operation, an undeclared status, a declared
error, no answer); and the generated module skipping without `SEAMS_SMOKE_BASE_URL`
and failing under `SEAMS_E2E=1`.
