"""A generic ASGI host for one generated route module (ADR-0007).

    python -m seams_runtime.host --routes /app/chat_api.py --port 8000

``build_app`` imports the route module from its path (its import runs
``Runtime.load``), includes ``module.router`` and adds what every generated
app needs but no generated handler holds:

- a ``RuntimeModelError`` handler answering ``{"detail": exc.to_dict()}``
  with ``exc.http_status``;
- ``GET /healthz``;
- the landmark page at its ifml:path, rendered by ``Runtime.render_page``
  with the page's correlation-key query parameters, and each of
  ``ModelGraph.secondary_pages`` (a pathed page holding no task form) the
  same way at its own path;
- ``GET /tasks``, the task inbox (ADR-0009): the open user tasks
  ``Runtime.user_tasks`` lists for the request's identity, each rendered with
  its generated form partial (the row's ``partial``, given ``task=row``).
  JSON (``{"identity": ..., "tasks": [...]}``) when the request accepts
  ``application/json``; 401 without an identity;
- a startup seed from the JSON file ``SEAMS_SEED`` names (``seed_store``).

Nothing here names a model term: the page, its path and its blocks, and
each task's form partial, come from the graph.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from .contracts import shape_contract
from .errors import ContractViolation, RuntimeModelError

log = logging.getLogger(__name__)

ROUTES_ENV = "SEAMS_ROUTES"
SEED_ENV = "SEAMS_SEED"
DEFAULT_ROUTES = "/app/chat_api.py"  # where the generated compose file mounts the route module
TASKS_PATH = "/tasks"
HTMX_SRC = "https://unpkg.com/htmx.org@2.0.4"  # the version the generated pages load


def load_routes(routes_path):
    """Import the route module at ``routes_path`` under a name unique to that path."""
    path = Path(routes_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"route module {path} not found")
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(f"seams_routes_{path.stem}_{digest}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("router", "runtime"):
        if not hasattr(module, attr):
            raise AttributeError(f"route module {path} defines no {attr!r}")
    return module


def seed_store(runtime, seed_path) -> int:
    """Write the seed file's entities that are not stored yet; return how many.

    The file maps a shape CURIE to a list of items, each ``{"id": ..., ...}``.
    A field named after a proc:correlationKey label that is not a sh:path of
    the shape becomes the entity's correlation key. Every item is validated
    before any is written, so a bad seed writes nothing; the ContractViolation
    names the item (``focus`` is ``<file>#<shape>[<index>]`` plus its id)."""
    seed_path = Path(seed_path)
    doc = json.loads(seed_path.read_text())
    if not isinstance(doc, dict):
        raise ValueError(f"seed {seed_path}: expected an object of shape CURIE -> list of items")
    keys = runtime.model.correlation_key_labels()
    rows = []
    for curie, items in doc.items():
        shape = runtime.model.curie(curie)
        fields = shape_contract(runtime.model, shape).fields
        if not isinstance(items, list):
            raise ValueError(f"seed {seed_path}: {curie} is not a list of items")
        for index, item in enumerate(items):
            where = f"{seed_path.name}#{curie}[{index}]"
            if not isinstance(item, dict) or not item.get("id"):
                raise ValueError(f"seed {where}: an item must be an object with an \"id\"")
            item = dict(item)
            entity_id = str(item["id"] if "id" in fields else item.pop("id"))
            scope = {k: item.pop(k) for k in sorted(keys - set(fields)) if k in item}
            try:
                data = runtime.validate(shape, item)
            except ContractViolation as exc:
                err = ContractViolation(exc.shape, exc.results, focus=f"{where} id {entity_id!r}",
                                        operation=exc.operation)
                err.add_note(f"seed item {where} (id {entity_id!r}) violates {curie}")
                log.error("seed %s rejected: %s", where, exc)
                raise err from exc
            correlation_key = next(iter(scope.values()), None)
            rows.append((entity_id, shape, data, None if correlation_key is None else str(correlation_key)))
    written = 0
    for entity_id, shape, data, correlation_key in rows:
        if runtime.store.get_entity(entity_id) is not None:
            continue
        runtime.store.put_entity(entity_id, shape, data, correlation_key=correlation_key,
                                 status=data.get("status"))
        written += 1
    log.info("seeded %d of %d entities from %s", written, len(rows), seed_path)
    return written


def render_inbox(runtime, identity, tasks) -> str:
    """The task inbox page: one generated form partial per open task, in
    ``Runtime.user_tasks`` order (oldest first)."""
    parts = [runtime.fragments.render_template(row["partial"], {"task": row}) for row in tasks]
    body = "\n".join(parts) if parts else '<p class="empty">No open tasks.</p>'
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
        f'  <title>Tasks</title>\n  <script src="{HTMX_SRC}"></script>\n</head>\n<body>\n'
        f'<main id="tasks" data-identity="{html.escape(identity.id)}">\n'
        f'<h1>Tasks for {html.escape(identity.id)}</h1>\n{body}\n</main>\n</body>\n</html>\n'
    )


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def build_app(routes_path) -> FastAPI:
    module = load_routes(routes_path)
    runtime = module.runtime
    page = runtime.model.landmark_page()
    page_path = runtime.model.page_path(page)
    keys = sorted(runtime.model.correlation_key_labels())

    @asynccontextmanager
    async def lifespan(_app):
        seed = os.environ.get(SEED_ENV)
        if seed:
            seed_store(runtime, seed)
        yield

    app = FastAPI(title=runtime.model.label(page), lifespan=lifespan)
    app.state.module = module
    app.state.runtime = runtime

    @app.exception_handler(RuntimeModelError)
    async def _model_error(request: Request, exc: RuntimeModelError):
        log.warning("%s %s -> %s %s", request.method, request.url.path, exc.http_status, type(exc).__name__)
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.to_dict()})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "model_hash": runtime.model.hash}

    def page_route(served):
        async def render(request: Request) -> HTMLResponse:
            # only correlation-key parameters reach the template context
            params = {k: request.query_params[k] for k in keys if request.query_params.get(k)}
            return runtime.render_page(served, **params)
        return render

    async def tasks(request: Request):
        identity = runtime.hook.authenticate(request)
        rows = runtime.user_tasks(identity)  # PolicyDenied (401) without an identity
        log.info("GET %s for %s: %d open task(s)", TASKS_PATH, identity.id, len(rows))
        if wants_json(request):
            return JSONResponse(jsonable_encoder({"identity": identity.id, "tasks": rows}))
        return HTMLResponse(render_inbox(runtime, identity, rows))

    app.add_api_route(page_path, page_route(page), methods=["GET"], response_class=HTMLResponse)
    for other in runtime.model.secondary_pages():
        app.add_api_route(runtime.model.page_path(other), page_route(other), methods=["GET"],
                          response_class=HTMLResponse)
        log.info("host: %s at GET %s", other, runtime.model.page_path(other))
    app.add_api_route(TASKS_PATH, tasks, methods=["GET"])
    app.include_router(module.router)
    log.info("host: %s at GET %s, task inbox at GET %s, routes from %s", page, page_path, TASKS_PATH,
             module.__file__)
    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seams_runtime.host",
                                     description="Serve a generated seams route module.")
    parser.add_argument("--routes", default=os.environ.get(ROUTES_ENV) or DEFAULT_ROUTES,
                        help=f"route module path (default: ${ROUTES_ENV} or {DEFAULT_ROUTES})")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import uvicorn

    uvicorn.run(build_app(args.routes), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
