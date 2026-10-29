"""The FastAPI route generator (M004/S05, D016, D017).

``extract_routes`` reads, for each ``arch:Container`` that ``seam:executes`` a
``proc:Process``, the operations and channels it ``seam:exposes`` into frozen
dataclasses; ``render_routes`` renders each container through
templates/fastapi_routes.py.j2 into ``<container local name>.py``. The handlers
are thin (ADR-0007 rule 1): read the request, validate it against the accepted
shape, start the process the operation triggers, query the returned shape and
render the fragment the GAP-19 rule names. Nothing else: no branching, no
domain names. Every collection is sorted by IRI, and a missing or ambiguous
required fact raises ``GeneratorError`` naming the subject IRI and predicate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdflib import RDF, RDFS, Namespace

from seams_runtime import ModelGraph, ResolutionError
from seams_runtime.model import COMM, HYDRA, PROC, SEAM, local_name

from . import GeneratorError
from .facts import IFML, Facts
from .fragments import ITEM, fragment_for
from .htmx import _environment, _shape_name

ARCH = Namespace("https://w3id.org/seams/arch#")

TEMPLATE_NAME = "fastapi_routes.py.j2"

# comm:requestMediaType -> (variable, Starlette Request coroutine method)
REQUEST_BODIES = {
    "application/x-www-form-urlencoded": ("form", "form"),
    "application/json": ("body", "json"),
}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


# ── the routes model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Body:
    var: str         # "form" or "body"
    call: str        # await request.<call>()


@dataclass(frozen=True)
class Validate:
    var: str         # the accepted shape's name (:MessageShape -> message)
    shape: str       # curie
    source: str      # the Body var


@dataclass(frozen=True)
class Start:
    process: str     # curie
    payload: str     # the validated var
    key: str         # proc:correlationKey rdfs:label, a path variable


@dataclass(frozen=True)
class Query:
    var: str         # <shape name>s
    shape: str       # curie
    filters: tuple[str, ...]  # path variables, passed as var=var


@dataclass(frozen=True)
class Render:
    name: str        # fragment file name (seams_gen.fragments.fragment_for)
    data: str        # the var passed as data
    params: tuple[str, ...]  # component parameters that are path variables
    multiline: bool  # the POST layout


@dataclass(frozen=True)
class Endpoint:
    curie: str
    name: str        # local name minus a trailing _op (GAP-21)
    channel: bool    # comm:Channel (SSE) rather than hydra:Operation
    method: str      # upper case hydra:method ("GET" for a channel)
    path: str
    arguments: tuple[str, ...]  # handler parameters
    policies: tuple[str, ...] = ()
    body: Body | None = None
    validate: Validate | None = None
    start: Start | None = None
    query: Query | None = None
    render: Render | None = None
    accepts: str | None = None  # a channel's seam:acceptsShape curie
    scope: str | None = None    # a channel's single path variable


@dataclass(frozen=True)
class NotRouted:
    operation: str   # curie of an operation a task of this container invokes
    container: str   # curie of the other container that exposes it


@dataclass(frozen=True)
class RouteModule:
    file_name: str   # <container local name>.py
    id: str
    curie: str
    system: str      # curie of the arch:System that arch:contains the container
    exposes: tuple[str, ...]
    not_routed: tuple[NotRouted, ...]
    endpoints: tuple[Endpoint, ...]


@dataclass(frozen=True)
class RoutesModel:
    model_stem: str
    model_file: str  # the TriG file name, mounted at /model/<file>
    model_hash: str
    modules: tuple[RouteModule, ...]


# ── extraction ──────────────────────────────────────────────────────────────


def extract_routes(model: ModelGraph) -> RoutesModel:
    f = Facts(model)
    containers = sorted({c for c, p in f.ds.subject_objects(SEAM.executes)
                         if (c, RDF.type, ARCH.Container) in f.ds
                         and (p, RDF.type, PROC.Process) in f.ds}, key=str)
    if not containers:
        raise GeneratorError(model.subject, SEAM.executes,
                             "no arch:Container seam:executes a proc:Process")
    return RoutesModel(
        model_stem=model.path.stem,
        model_file=model.path.name,
        model_hash=model.hash,
        modules=tuple(_module(f, model, c) for c in containers),
    )


def _module(f: Facts, model: ModelGraph, container) -> RouteModule:
    systems = [s for s in f.subjects(ARCH.contains, container) if (s, RDF.type, ARCH.System) in f.ds]
    if len(systems) != 1:
        raise GeneratorError(container, ARCH.contains,
                             f"expected one arch:System containing the container, found {len(systems)}")
    processes = f.objects(container, SEAM.executes)
    triggered = _triggered(f, model, processes)
    exposed = f.objects(container, SEAM.exposes)
    return RouteModule(
        file_name=f"{local_name(container)}.py",
        id=local_name(container),
        curie=f.curie(container),
        system=f.curie(systems[0]),
        exposes=tuple(f.curie(e) for e in exposed),
        not_routed=_not_routed(f, container, processes),
        endpoints=tuple(_endpoint(f, e, triggered) for e in exposed),
    )


def _triggered(f: Facts, model: ModelGraph, processes) -> dict:
    """{operation: process} for each executed process's triggering operation
    (ModelGraph.triggering_operation: the operation the event that
    seam:triggers the process seam:submitsTo)."""
    found = {}
    for process in processes:
        if (process, RDF.type, PROC.Process) not in f.ds:
            raise GeneratorError(process, RDF.type, "a seam:executes target must be a proc:Process")
        try:
            op = model.triggering_operation(process)
        except ResolutionError as err:
            raise GeneratorError(process, SEAM.triggers, err.detail) from err
        if op in found:
            raise GeneratorError(op, SEAM.submitsTo,
                                 f"triggers both {found[op]} and {process}")
        found[op] = process
    return found


def _not_routed(f: Facts, container, processes) -> tuple[NotRouted, ...]:
    """Operations a process (or a task of its BPMN model) seam:invokes that
    another container seam:exposes."""
    prefixes = tuple(f"{m}#" for p in processes for m in f.objects(p, SEAM.detailedBy))
    invoked = sorted({op for s, op in f.ds.subject_objects(SEAM.invokes)
                      if s in processes or str(s).startswith(prefixes)}, key=str)
    return tuple(NotRouted(operation=f.curie(op), container=f.curie(other))
                 for op in invoked
                 for other in f.subjects(SEAM.exposes, op) if other != container)


def _handler_name(iri) -> str:
    name = local_name(iri)
    return name[: -len("_op")] if name.endswith("_op") and len(name) > 3 else name


def _endpoint(f: Facts, e, triggered) -> Endpoint:
    if (e, RDF.type, COMM.Channel) in f.ds:
        return _channel(f, e)
    if (e, RDF.type, HYDRA.Operation) not in f.ds:
        raise GeneratorError(e, RDF.type, "an exposed element must be a hydra:Operation or comm:Channel")
    return _operation(f, e, triggered)


def _channel(f: Facts, ch) -> Endpoint:
    transport = f.one(ch, COMM.transport)
    if transport != COMM.SSE:
        raise GeneratorError(ch, COMM.transport, f"only comm:SSE channels are routed, found {transport}")
    template, mappings = f.path_template(ch)
    variables = _variables(template)
    if len(variables) != 1:
        raise GeneratorError(ch, COMM.path,
                             f"an SSE channel needs exactly one path variable as its scope, found {variables}")
    accepts = f.optional(ch, SEAM.acceptsShape)
    return Endpoint(
        curie=f.curie(ch), name=_handler_name(ch), channel=True, method="GET", path=template,
        arguments=tuple(f"{v}: str" for v in variables),
        accepts=f.curie(accepts) if accepts is not None else None, scope=variables[0],
    )


def _variables(template: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", template)


def _operation(f: Facts, op, triggered) -> Endpoint:
    method = str(f.one(op, HYDRA.method)).upper()
    if method not in METHODS:
        raise GeneratorError(op, HYDRA.method, f"unknown method {method!r}")
    kind = f.one(op, SEAM.mediaKind)
    if kind != SEAM.UIFragment:
        raise GeneratorError(op, SEAM.mediaKind, f"only seam:UIFragment operations are routed, found {kind}")
    template, _ = f.path_template(op)
    variables = _variables(template)

    body = None
    media_type = f.optional(op, COMM.requestMediaType)
    if media_type is not None:
        if str(media_type) not in REQUEST_BODIES:
            raise GeneratorError(op, COMM.requestMediaType, f"unknown request media type {str(media_type)!r}")
        body = Body(*REQUEST_BODIES[str(media_type)])

    validate = None
    accepts = f.optional(op, SEAM.acceptsShape)
    if accepts is not None:
        if body is None:
            raise GeneratorError(op, COMM.requestMediaType, "seam:acceptsShape needs a request body")
        validate = Validate(var=_shape_name(accepts), shape=f.curie(accepts), source=body.var)

    start = None
    if op in triggered:
        process = triggered[op]
        if validate is None:
            raise GeneratorError(op, SEAM.acceptsShape, f"starting {process} needs a validated payload")
        key = f.label(f.one(process, PROC.correlationKey))
        if key not in variables:
            raise GeneratorError(process, PROC.correlationKey,
                                 f"{key!r} is not a path variable of {op} ({template})")
        start = Start(process=f.curie(process), payload=validate.var, key=key)

    returns = f.optional(op, SEAM.returnsShape)
    query = None
    if method == "GET" and returns is not None:
        query = Query(var=_shape_name(returns) + "s", shape=f.curie(returns), filters=tuple(variables))

    name, component, frag_kind = fragment_for(f, op)
    if frag_kind == ITEM:
        if validate is None or returns != accepts:
            raise GeneratorError(op, SEAM.returnsShape,
                                 f"the item partial {name} renders the accepted entity, "
                                 "so seam:returnsShape must equal seam:acceptsShape")
        render = Render(name=name, data=validate.var, params=(), multiline=method != "GET")
    else:
        if query is None:
            raise GeneratorError(op, SEAM.returnsShape,
                                 f"the component partial {name} renders a GET query of the returned shape")
        params = sorted({str(label) for p in f.objects(component, IFML.hasParameter)
                         for label in f.objects(p, RDFS.label) if str(label) in variables})
        render = Render(name=name, data=query.var, params=tuple(params), multiline=method != "GET")

    arguments = tuple(f"{v}: str" for v in variables) + (("request: Request",) if body else ())
    return Endpoint(
        curie=f.curie(op), name=_handler_name(op), channel=False, method=method, path=template,
        arguments=arguments, policies=tuple(f.curie(p) for p in f.objects(op, SEAM.governedBy)),
        body=body, validate=validate, start=start, query=query, render=render,
    )


# ── rendering ───────────────────────────────────────────────────────────────


def render_routes(routes: RoutesModel) -> dict[str, str]:
    """{file name: text}, one route module per executing container."""
    template = _environment().get_template(TEMPLATE_NAME)
    return {m.file_name: template.render(r=routes, m=m) for m in routes.modules}


def route_module(trig_path) -> tuple[str, str]:
    """(file name, text) of the model's one route module; no or several
    executing containers raise GeneratorError(model, seam:executes)."""
    model = ModelGraph.load(trig_path)
    routes = extract_routes(model)
    if len(routes.modules) != 1:
        raise GeneratorError(model.subject, SEAM.executes,
                             f"expected one executing container, found {[m.curie for m in routes.modules]}")
    name = routes.modules[0].file_name
    return name, render_routes(routes)[name]


def generate_routes(trig_path) -> str:
    """Load the model and render its one route module (chat_api.py for the
    chat app)."""
    return route_module(trig_path)[1]


__all__ = ["RoutesModel", "RouteModule", "Endpoint", "extract_routes", "generate_routes",
           "render_routes", "route_module", "TEMPLATE_NAME"]
