# Getting started

SemanticSeams is a set of RDF vocabularies, worked example models, SHACL shapes, canned
SPARQL queries and a read-only viewer that ties them together. This page takes you from
a fresh clone to the test suite passing and the viewer open in a browser on the chat-app
example.

## What you need

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 from `.python-version` if
  you do not have it. CI runs on 3.12.
- A browser with internet access. The viewer loads htmx, vis-network, elkjs, bpmn-js,
  dmn-js and diagram-js (via esm.sh) from a CDN.
- Nothing else: there is no database to start. The viewer reads the example model into
  memory through the `seams` library.

## Install

```sh
git clone https://github.com/MetaCoding-io/SemanticSeams.git
cd SemanticSeams
uv sync --all-packages
source .venv/bin/activate
```

The repository is a uv workspace. `uv sync --all-packages` creates `.venv` with the exact
versions pinned in `uv.lock`; without `--all-packages` it installs nothing from the
members. Each member declares its own dependencies in its `pyproject.toml`:

| Member | Distribution | Dependencies |
|---|---|---|
| `packages/seams` | `semanticseams` | rdflib, lxml |
| `seams_runtime` | `semanticseams-runtime` | semanticseams, rdflib, pySHACL, SpiffWorkflow, lxml, httpx, FastAPI, python-multipart, Jinja2, uvicorn |
| `seams_gen` | `semanticseams-gen` | semanticseams, rdflib, Jinja2, PyYAML |
| `seams_gateway` | `semanticseams-gateway` | FastAPI, uvicorn, httpx |
| `viewer` | `semanticseams-viewer` | semanticseams, FastAPI, uvicorn, Jinja2, rdflib, pySHACL |

The root `pyproject.toml` adds a `dev` group with pytest, PyYAML, httpx, ruff and pyright.
If you prefer not to activate the environment, prefix any command with `uv run`, for
example `uv run pytest`.

## Run the tests

```sh
pytest
```

The suite is the project's acceptance test. It parses every Turtle and TriG file,
validates both worked examples against the [seam shapes](/reference/shapes), proves the
shapes reject deliberately broken seams, checks that every non-reserved seam predicate is
used somewhere, asserts the exact rows of every [canned query](/reference/queries), and
exercises the viewer's endpoints. CI runs the same command on every push and pull
request.

## Lint and type-check

CI runs these as their own jobs:

```sh
uv run ruff check
uv run ruff format --check
uv run pyright
```

Ruff covers the whole tree except committed generated code. Pyright checks
`packages/seams` in strict mode.

## Open the viewer

```sh
python3 -m uvicorn viewer.app:app --port 8000
```

The viewer loads the chat app unless `SEAMS_MODEL` names another TriG file or a
directory of TriG files (see [Authoring a model](/guide/authoring-a-model#view-it)).

Open <http://localhost:8000>. The root redirects to the chat app's architecture view,
the top of the descent. From there:

1. Click **Chat Web Interface** to land on the interaction model it presents.
2. Click **Send Message** to land on the BPMN process the event triggers.
3. Click the **Route to Provider** task. Its decision is detailed by two models, so the
   viewer asks which one to open. Choose the DMN model, then open its decision table.

The viewer loads its Python code once, at start-up. After pulling new commits or editing
`viewer/*.py`, restart it, or start it with `--reload` so it restarts itself; a viewer left
running from an earlier checkout keeps serving the old views.

[Using the viewer](/guide/the-viewer) walks through the same descent with screenshots
and explains everything else on the page.

## What next

- [Quick start: the chat app](/tutorial): regenerate the chat app from its model and run
  it with Docker Compose.
- [Build an expense approval app](/tutorials/expenses/): write a model yourself, one layer
  per chapter, from an empty file to the whole system under `docker compose up`.
- [Using the viewer](/guide/the-viewer): what each part of the page does, and the URLs
  behind it.
- [Diagrams are views](/concepts/diagrams-are-views): the idea the project rests on.
- [Authoring a model](/guide/authoring-a-model): the conventions a model must follow to
  be navigable and to pass the shapes.
