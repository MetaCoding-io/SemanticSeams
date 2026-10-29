# Research note: `seams`, a read-only Python library over the model

*Status: proposal, 2026-10-29. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Library" section). Revised the same day after M009 merged:
the expense tutorial's chapter 8 now exists, passes the complexity check, and shows how
the current code copes with several models per notation.*

## The question

Did the generation work produce a library a user could pick up to traverse the graph
together with the native BPMN and DMN files and the IFML, for the purpose of generating
their own artifacts? **Partly.** It produced a real fact layer, but one shaped around the
runtime's needs and the chat app, with no public surface and the runtime's whole
dependency stack attached. This note sets out what exists, proposes a small read-only
library, `seams`, that every consumer in the repository and every outside generator
would share, and makes the case for building it with modern Python tooling: a uv
workspace, a committed lockfile, `pyproject.toml` packaging, ruff and a type checker.

## What exists

`ModelGraph` in [`seams_runtime/model.py`](../../seams_runtime/model.py) (563 lines) is
the de facto library. It:

- loads a TriG file into an rdflib `Dataset`, computes the model's content hash, and
  resolves `seam:renderPayload` paths next to the model file;
- maps BPMN element IDs to their fragment IRIs;
- answers the worker's questions: the operation a task invokes, the shapes it reads and
  writes, the transition it fires, its decision binding, the container that implements
  an operation or executes a process, the operation's path, the channel for an event,
  the process's correlation key, an entity's lifecycle, and the policies on an operation;
- finds the landmark IFML page, its path and its components.

The generators in [`seams_gen`](../../seams_gen/README.md) build on it through a small
`Facts` helper.

### Who reads the graph today

| Reader | How |
|---|---|
| Runtime and generators | `ModelGraph` |
| Complexity check | rdflib directly, in `seams_gen/complexity.py` |
| Viewer | Its own loader (`ModelStore` in `viewer/app.py`, which now picks the model from `SEAMS_MODEL`), its own label, notation and seam-edge helpers, and its own IFML interpretation in `viewer/ifml.py` |
| Docs reference pages | rdflib directly, in `docs/scripts/generate.py` |

### Why it is not yet a library for users

1. **It is bundled with the runtime.** `seams_runtime/__init__.py` imports the engine,
   the host and the store, so `from seams_runtime import ModelGraph` pulls in
   SpiffWorkflow, FastAPI, uvicorn, httpx and the rest of
   `seams_runtime/requirements.txt`. Someone who only wants to read facts installs an
   execution stack. It reaches further than `ModelGraph`'s own users:
   `python -m seams_gen.complexity` runs three SPARQL queries with plain rdflib, yet it
   will not start without SpiffWorkflow installed, because importing anything in
   `seams_gen` imports `seams_runtime`, whose `__init__` imports the engine.
2. **It has no public surface.** The generators import a private helper
   (`_payload_files`) and namespace constants from inside `seams_runtime.model`. Nothing
   marks what is stable.
3. **It assumes one of each, and callers work around it.** `_bpmn_model()` raises
   unless exactly one model renders a BPMN payload, `task_iri()` resolves every BPMN ID
   against that one model, and `landmark_page()` requires exactly one landmark page. The
   [build-along tutorial](2026-10-29-build-along-tutorial.md)'s chapter 8 has two BPMN,
   two DMN, two IFML and two statechart models, and M009 shipped it by routing around
   these accessors rather than replacing them: the engine resolves task IRIs under the
   BPMN model each workflow was parsed from, and the htmx generator takes the landmark
   page plus a separate `secondary_pages()` list. The one-of-each accessors remain, so
   each new consumer has to know which of them are safe on a multi-model graph.
4. **It barely reads the native files.** `bpmn_process_ids()` and `dmn_decision_ids()`
   list IDs with lxml, and SpiffWorkflow parses the files to execute them. Nothing lets
   a generator walk a process in flow order, see its gateways and unlifted elements, or
   read a DMN table's inputs, outputs and rules next to the graph facts. The generators
   read no BPMN or DMN at all.
5. **IFML is interpreted twice.** The viewer's `ifml.py` and the htmx generator's
   `extract_page` each derive pages, components, events and flows from the same triples,
   with their own rules. They can drift. (IFML has no native file here: it lives in the
   graph as RDF, so the library's job for IFML is interpretation, not parsing.)

### Python tooling today

Four requirements files (`requirements-dev.txt`, `seams_runtime/requirements.txt`,
`seams_gateway/requirements.txt`, `viewer/requirements.txt`) with lower bounds only, no
`pyproject.toml`, no lockfile, and CI installing with pip on Python 3.12. The packages are
importable only from the repository root; none of them can be installed, built or
versioned, which is the first thing an outside user of a library would need.

## The proposal: one read-only library

A package that every reader shares: the runtime, the generators, the viewer, the docs
generator, and any generator a user writes for their own artifacts.

### Principles

- **Small dependencies.** rdflib and lxml only. No engine, no web framework.
- **One loader.** A single model file, or a directory of files loaded together (which
  also serves the build-along tutorial's per-chapter checkpoints). Payloads resolved next
  to the model; the content hash computed once.
- **Typed views per layer, joined with the native files.** Each view returns frozen
  dataclasses, with cross-layer edges already resolved to the objects at the other end.
- **Collections, never singletons.** Where a caller needs exactly one, `.only()` raises
  the existing `ResolutionError(subject, predicate, detail)`, which names the fact for
  the model author to fix, as the generators' errors do today.
- **Escape hatches everywhere.** Every object carries its IRI, label, owning `seam:Model`
  and seam edges, plus `.raw`: the rdflib node, or the lxml element for native-only
  elements. A SPARQL helper has the project's prefixes bound and runs the canned queries
  in `docs/queries/` by name.
- **Deterministic ordering is a guarantee,** because the generators' byte-for-byte golden
  outputs depend on it. Every collection is sorted explicitly.
- **Read-only.** Execution stays in the runtime; editing stays a v1 non-goal. No
  triplestore client in v1, though the loader is the seam where a Fuseki-backed store
  plugs in later, as `ModelStore`'s docstring already anticipates.

### Shape of the API

| View | Gives |
|---|---|
| `model.architecture` | Systems, containers, deployment nodes and environments, with `deploy:` facts |
| `model.interfaces` | Interaction models, then pages, components, events, flows, parameters and bindings; activation conditions from `seam:visibleWhen` |
| `model.processes` | Each BPMN model joined with its XML: elements in flow order, including those with no IRI, gateways and lanes; each task's seams resolved (invoked operation, shapes read and written, transition fired, decision); user tasks with the form they are completed on ([ADR-0009](../adr/0009-human-tasks.md)); message start events with the channel that starts them ([ADR-0010](../adr/0010-channel-started-processes.md)) |
| `model.decisions` | Each DMN decision with its table: inputs, outputs, hit policy and rules; the shapes it reads |
| `model.shapes` | SHACL shapes as fields: path, datatype, cardinality, label |
| `model.operations`, `model.channels` | Paths, methods, accepted and returned shapes, media kinds; channel transport |
| `model.lifecycles` | States, transitions, and the tasks that fire each transition |
| `model.policies` | Policies and the elements they govern |

A user's own generator, for example one that writes a review checklist per process:

```python
import seams

model = seams.load("examples/chat-app/chat-app.trig")
for page in model.interfaces.pages():
    for event in page.events():
        process = event.triggers                  # a Process, joined with its BPMN XML
        if process is None:
            continue
        print(f"{page.label}: {event.label} starts {process.label}")
        for task in process.tasks():              # flow order, read from the XML
            line = f"  {task.kind}: {task.label}"
            if task.invokes:
                line += f" -> {task.invokes.method} {task.invokes.path}"
            print(line)
            if task.decided_by:
                for rule in task.decided_by.table.rules:   # parsed from the DMN
                    print("    rule:", rule.inputs, "->", rule.outputs)

# The canned questions, by name, with the focus bound:
rows = model.question("impact-of-node", node="https://example.org/chat/db01")
```

## Built with modern Python tooling: a uv workspace

This is as much a part of the proposal as the API. A library is only usable if it can be
installed, locked, built and checked the same way on a laptop, in CI and in a container.
The setup below was tried end to end with uv 0.11 in a scratch workspace on 2026-10-29:
workspace members depending on each other, a shared dev group, sync, imports across
members, ruff, pytest, and `uv build` producing a wheel and an sdist.

### Layout

- **One uv workspace at the repository root.** The root `pyproject.toml` lists the
  members and holds the shared dev tools:

  ```toml
  [tool.uv.workspace]
  members = ["packages/seams", "seams_runtime", "seams_gen", "seams_gateway", "viewer"]

  [dependency-groups]
  dev = ["pytest>=8", "ruff", "pyright"]
  ```

- **The library in `src/` layout** under `packages/seams/`, as `uv init --lib` generates
  it: `src/seams/__init__.py`, a `py.typed` marker so type checkers use its annotations
  (PEP 561), and uv's own build backend:

  ```toml
  [project]
  name = "seams"            # distribution name to be decided, see open questions
  requires-python = ">=3.12"
  dependencies = ["rdflib>=7.0", "lxml>=5.0"]

  [build-system]
  requires = ["uv_build>=0.11,<0.12"]
  build-backend = "uv_build"
  ```

- **Members depend on the library through the workspace,** never by path hacks or by
  importing from the repository root:

  ```toml
  [project]
  dependencies = ["seams"]

  [tool.uv.sources]
  seams = { workspace = true }
  ```

- **Each existing package gets its own `pyproject.toml`** with the dependencies that are
  in its requirements file today, and the four requirements files go away. The
  applications (runtime, gateway, viewer) do not need to be published; whether they keep
  their flat layout as packaged members or become non-packaged members is a detail for
  the first slice to settle.
- **`uv.lock` is committed,** so the laptop, CI and the Docker images install the same
  versions. **`.python-version`** pins 3.12, the version CI uses today; uv installs it on
  demand.

### Commands

| Task | Command |
|---|---|
| Set up everything | `uv sync --all-packages` |
| Run the tests | `uv run pytest` |
| Lint and format | `uv run ruff check` and `uv run ruff format` |
| Type-check | `uv run pyright` (strict on `seams`, gradual elsewhere) |
| Run the viewer | `uv run uvicorn viewer.app:app --port 8000` |
| Run a generator | `uv run python -m seams_gen htmx examples/chat-app/chat-app.trig --out build/` |
| Build the library | `uv build --package seams` |
| Publish (later) | `uv publish`, with trusted publishing from CI |

One gotcha the trial surfaced: at a root that is only a workspace container, a plain
`uv sync` installs the root project alone and the members are missing. Use
`uv sync --all-packages`, or give the root project dependencies on the members.

### CI and containers

- Replace `actions/setup-python` and `pip install -r …` in `ci.yml` and
  `deploy-pages.yml` with `astral-sh/setup-uv` (with its cache) and
  `uv sync --locked --all-packages`. `--locked` fails the build when `uv.lock` is out of
  date with the `pyproject.toml` files, so a dependency change cannot land without its
  lock.
- In the runtime and gateway Dockerfiles, install from the lockfile with uv instead of
  pip, without the dev group, so the images match what CI tested.
- Add a lint job (`ruff check`, `ruff format --check`) and a type-check job on the
  library.

## How to get there

Each slice ships on its own and leaves every test green.

| # | Slice | Notes |
|---|---|---|
| L1 | **uv workspace and tooling.** `pyproject.toml` per package, `uv.lock`, `.python-version`, ruff; CI, the docs workflow and the Dockerfiles on uv; the requirements files removed. | No code changes. First, because it makes everything after it installable. |
| L2 | **Extract the core into `seams`:** loader (file or directory), hash, payload resolution, namespaces, errors. `seams_runtime` re-exports `ModelGraph`, now built on it; the generators import only the public API. | The loader honours `SEAMS_MODEL` as the runtime and viewer do since backlog item E2 (M009/S01). No behaviour change. |
| L3 | **Typed views over the graph,** replacing the one-of-each accessors with collections and `.only()`. | Replaces the per-caller workarounds M009 added for multiple models: per-workflow task IRIs in the engine, and the landmark-plus-secondary-pages split in the htmx generator. |
| L4 | **Native joins:** BPMN in flow order, DMN tables. | |
| L5 | **Port the consumers:** generators first (`extract_page` on the interfaces view), then the viewer (`ifml.py` on the same view, so IFML has one interpretation, and `ModelStore` replaced by the loader), then the docs reference generator. | Golden outputs must stay byte-identical. |
| L6 | **Docs:** an API reference page and a "Write your own generator" guide. | Could also be a chapter of the build-along tutorial. |

## Open questions

- **Names.** The distribution name on PyPI is not checked; `seams` is likely taken or too
  generic, and `semanticseams` is the obvious alternative. The import name can stay
  `seams` either way.
- **Where the existing packages live.** Moving them under `packages/` makes the workspace
  tidy but changes paths in the Dockerfiles, the docs and the tutorial. Keeping them
  where they are, as members in place, is cheaper.
- **Which type checker.** pyright or mypy; whichever is chosen runs strict on the
  library.
- **Publish in v1, or stay workspace-only** until the API has an outside consumer? Inside
  the repository there are now two real models to test it against, the chat app and the
  expense tutorial's chapter 8, which passes the complexity check (four notations with two
  models each, `ExpenseShape` reached from six models, 111 seam edges).
