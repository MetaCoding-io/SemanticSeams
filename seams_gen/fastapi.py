"""The FastAPI route generator (M004/S05, D016, D017).

``extract_routes`` reads, for each serving ``arch:Container`` (one that
``seam:executes`` a ``proc:Process``, or ``seam:exposes`` a ``hydra:Operation``
some ``ifml:Event`` ``seam:submitsTo``; D026), the operations and channels it
``seam:exposes`` into frozen dataclasses; ``render_routes`` renders each
container through templates/fastapi_routes.py.j2 into ``<container local
name>.py``. The handlers are thin (ADR-0007 rule 1): read the request,
validate it against the accepted shape, start the process the operation
triggers (or, when it triggers none and an ``ifml:Form`` that ``seam:writes``
the accepted shape submits to it, ``runtime.write`` the entity, which
validates it and assigns its ``:id``; or, when the submitting form is the one
a ``proc:UserTask`` ``seam:completedOn``, ``runtime.complete_task`` the task
as the identity its ``task_policy`` dependency yields, ADR-0009), query the
returned shape and render the fragment the GAP-19 rule names. Nothing else:
no branching, no domain names. A channel-started process (ADR-0010) gets no
route: the runtime starts it when its channel is published on. A channel whose
comm:transport is comm:SemPKMWebhook (ADR-0027) gets a ``POST`` route at its
comm:path that hands the raw body to ``runtime.receive_webhook``; its facts are
``ModelGraph.webhook_channel``'s, so a fault raises GeneratorError on the
subject and predicate the runtime's ResolutionError names. Nor does an
exposed operation that a task of an executed process ``seam:invokes`` and no
``ifml:Event`` ``seam:submitsTo`` (a ``comm:PythonHandler``'s operation,
ADR-0012): the worker serves it in-process, and the module header says so.
An operation that declares error statuses (ADR-0013: each ``hydra:possibleStatus``
with a ``comm:errorCode``) lists each as an ``application/problem+json``
response, keyed by its ``hydra:statusCode``, with a JSON Schema derived from
the status's ``seam:returnsShape``; the module then defines one
``problem_handler`` that ``seams_runtime.host`` installs for
``OperationError``, answering with ``Runtime.problem`` for the raising route's
operation. Each target-classed shape a routed operation accepts or returns
gets a route ``GET /contexts/<shape local name>.jsonld`` answering its JSON-LD
context (ADR-0024 section 5), the ``jsonld`` generator's own document embedded
as a string constant; the 2xx answer of an operation whose returned shape has a
target class carries a ``Link`` header naming that context. Every collection is
sorted by IRI (the context routes by path), and a missing or ambiguous
required fact raises ``GeneratorError`` naming the subject IRI and predicate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rdflib import RDF, URIRef
from rdflib.namespace import SH, XSD
from seams import (
    ARCH,
    COMM,
    HYDRA,
    IFML,
    PROC,
    SEAM,
    Channel,
    Container,
    Many,
    Model,
    ModelGraph,
    Operation,
    Process,
    ResolutionError,
    Shape,
    Status,
    load,
    local_name,
)
from seams import Component as ComponentView

from . import GeneratorError
from ._views import label, required, view_errors
from .fragments import ITEM, fragment_for
from .htmx import _environment, _path_template, _shape_name, _task_curie, _task_process, _tracing_environment
from .jsonld import SUFFIX, context_document, extract_jsonld
from .trace import Trace, trace_template, view_iris

TEMPLATE_NAME = "fastapi_routes.py.j2"

# comm:requestMediaType -> (variable, Starlette Request coroutine method)
REQUEST_BODIES = {
    "application/x-www-form-urlencoded": ("form", "form"),
    "application/json": ("body", "json"),
}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
PROBLEM_JSON = "application/problem+json"  # RFC 9457
# sh:datatype -> JSON Schema type of an error shape's member; any other datatype is a string
# Keyed by sh:datatype; a field without one (None) falls back to "string".
JSON_TYPES: dict[URIRef | None, str] = {XSD.integer: "integer", XSD.decimal: "number", XSD.boolean: "boolean"}
# ADR-0024 section 5: where a context is served, and the Link relation naming it (JSON-LD 1.1, 6.1)
CONTEXTS = "/contexts"
JSONLD = "application/ld+json"
CONTEXT_REL = "http://www.w3.org/ns/json-ld#context"


# ── the routes model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Body:
    var: str  # "form" or "body"
    call: str  # await request.<call>()


@dataclass(frozen=True)
class Validate:
    var: str  # the accepted shape's name (:MessageShape -> message)
    shape: str  # curie
    source: str  # the Body var


@dataclass(frozen=True)
class Start:
    process: str  # curie
    payload: str  # the validated var
    key: str  # proc:correlationKey rdfs:label, a path variable


@dataclass(frozen=True)
class Write:
    shape: str  # curie of the accepted shape the submitting form seam:writes
    var: str  # the stored entity's var (the Validate var)
    source: str  # the Body var; runtime.write validates it, so no separate validate call


@dataclass(frozen=True)
class Complete:
    task: str  # the proc:UserTask as a CURIE seams.Model.curie expands back to its IRI
    payload: str  # the Body var; runtime.complete_task validates it
    key: str  # proc:correlationKey rdfs:label of the task's process, a path variable


@dataclass(frozen=True)
class Query:
    var: str  # <shape name>s
    shape: str  # curie
    filters: tuple[str, ...]  # path variables, passed as var=var


@dataclass(frozen=True)
class Render:
    name: str  # fragment file name (seams_gen.fragments.fragment_for)
    data: str  # the var passed as data
    params: tuple[str, ...]  # component parameters that are path variables
    multiline: bool  # the POST layout
    lead: str = "return "  # "response = " when the answer carries a Link header first


@dataclass(frozen=True)
class ErrorResponse:
    """The problem+json response of one hydra:statusCode of an operation:
    every error status with that code (ADR-0013), sorted by IRI."""

    code: int  # hydra:statusCode, the responses key
    description: str  # the statuses' rdfs:labels, joined
    content: str  # the responses entry's "content" value, a Python literal
    facts: tuple[str, ...]  # one comment per status: its code, error code and error shape

    @property
    def description_literal(self) -> str:
        """``description`` as a Python string literal (a label may hold quotes)."""
        return _literal(self.description)


@dataclass(frozen=True)
class Endpoint:
    curie: str
    name: str  # local name minus a trailing _op (GAP-21)
    channel: bool  # comm:Channel (SSE) rather than hydra:Operation
    method: str  # upper case hydra:method ("GET" for a channel)
    path: str
    arguments: tuple[str, ...]  # handler parameters
    policies: tuple[str, ...] = ()
    body: Body | None = None
    validate: Validate | None = None
    start: Start | None = None
    write: Write | None = None
    complete: Complete | None = None
    query: Query | None = None
    render: Render | None = None
    accepts: str | None = None  # a channel's seam:acceptsShape curie
    scope: str | None = None  # a channel's single path variable
    errors: tuple[ErrorResponse, ...] = ()  # by hydra:statusCode
    method_lower: str = ""  # the decorator name, @router.<method_lower>
    arguments_text: str = ""  # arguments joined with ", "
    accepts_suffix: str = ""  # a channel's " ; seam:acceptsShape <curie>" header fact, or ""
    dependencies: str = ""  # the decorator's policy list, '[Depends(runtime.policy("<curie>")), ...]'
    validate_only: bool = False  # a separate runtime.validate call (no write or completion validates)
    link: str = ""  # the Link header naming the returned shape's JSON-LD context, a Python literal, or ""
    webhook: bool = False  # a comm:SemPKMWebhook channel (ADR-0027): POST, runtime.receive_webhook
    event_name: str = ""  # a webhook channel's comm:eventName
    iri: str = ""  # the operation's or channel's full IRI, its origin in a generation trace (ADR-0019)
    # the IRIs of the shapes, processes (with their BPMN models and correlation
    # keys), task, policies, rendered component and the flows to it the
    # extraction read, sorted: further trace origins
    origins: tuple[str, ...] = ()

    @property
    def multiline_decorator(self) -> bool:
        """Whether the decorator spreads its arguments over lines (policies or errors)."""
        return bool(self.policies or self.errors)


@dataclass(frozen=True)
class NotRouted:
    operation: str  # curie of an operation a task of this container invokes
    container: str  # curie of the other container that exposes it
    iri: str = ""  # the operation's full IRI, its origin in a generation trace (ADR-0019)
    origins: tuple[str, ...] = ()  # the exposing container's IRI, a further trace origin


@dataclass(frozen=True)
class ProblemRoute:
    name: str  # handler name
    curie: str  # the operation that declares errors


@dataclass(frozen=True)
class ContextRoute:
    """The route answering one target-classed shape's JSON-LD context (ADR-0024 section 5)."""

    shape: str  # curie of the shape
    target: str  # curie of its sh:targetClass
    file_name: str  # the jsonld generator's file name, <shape local name>.jsonld
    path: str  # /contexts/<file name>
    name: str  # handler name, <shape name>_context
    constant: str  # the module constant holding the document
    lines: tuple[str, ...]  # the document, one Python string literal per line (each ends in a newline)
    iri: str = ""  # the shape's full IRI, its origin in a generation trace (ADR-0019)
    origins: tuple[str, ...] = ()  # the context's sources: class, category members


@dataclass(frozen=True)
class RouteModule:
    file_name: str  # <container local name>.py
    id: str
    curie: str
    system: str  # curie of the arch:System that arch:contains the container
    exposes: tuple[str, ...]
    not_routed: tuple[NotRouted, ...]
    invoked_only: tuple[str, ...]  # curies of exposed operations only a task invokes (not routed)
    endpoints: tuple[Endpoint, ...]
    exposes_text: str  # exposes joined with " , ", the header's seam:exposes object list
    iri: str = ""  # the container's full IRI, its origin in a generation trace (ADR-0019)
    origins: tuple[str, ...] = ()  # the arch:System's IRI, a further trace origin
    contexts: tuple[ContextRoute, ...] = ()  # by path

    @property
    def needs_identity(self) -> bool:
        """Whether a completion handler takes ``identity: Identity``."""
        return any(e.complete is not None for e in self.endpoints)

    @property
    def problem_routes(self) -> tuple[tuple[str, str], ...]:
        """(handler name, operation curie) of each endpoint that declares errors."""
        return tuple((e.name, e.curie) for e in self.endpoints if e.errors)

    @property
    def problem_operations(self) -> tuple[ProblemRoute, ...]:
        """``problem_routes`` as named pairs, for the PROBLEM_OPERATIONS table."""
        return tuple(ProblemRoute(name=name, curie=curie) for name, curie in self.problem_routes)

    @property
    def runtime_imports(self) -> str:
        """The names the module imports from seams_runtime."""
        names = ["Identity"] if self.needs_identity else []
        names += ["OperationError"] if self.problem_routes else []
        return ", ".join([*names, "Runtime"])

    @property
    def response_imports(self) -> str:
        """The names the module imports from fastapi.responses."""
        json_response = self.problem_routes or any(e.webhook for e in self.endpoints)
        names = ["HTMLResponse", *(["JSONResponse"] if json_response else [])]
        return ", ".join([*names, *(["Response"] if self.contexts else []), "StreamingResponse"])


@dataclass(frozen=True)
class RoutesModel:
    model_stem: str
    model_file: str  # the TriG file name, mounted at /model/<file>
    model_hash: str
    modules: tuple[RouteModule, ...]


# ── extraction ──────────────────────────────────────────────────────────────


def route_file_name(container_iri) -> str:
    """The file name of a serving container's route module: <local name>.py.
    The dockerfile generator copies it into the runtime image and names its
    own file after it."""
    return f"{local_name(container_iri)}.py"


def serving_containers(model: Model) -> Many[Container]:
    """The arch:Containers that serve routes (D026), by IRI:
    ``model.architecture.serving_containers()``, which the replica-cap
    health check shares."""
    return model.architecture.serving_containers()


def extract_routes(model: Model) -> RoutesModel:
    with view_errors():
        containers = serving_containers(model)
    if not containers:
        raise GeneratorError(
            model.subject,
            SEAM.executes,
            "no arch:Container seam:executes a proc:Process or seam:exposes "
            "a hydra:Operation an ifml:Event seam:submitsTo",
        )
    return RoutesModel(
        model_stem=model.path.stem,
        model_file=model.path.name,
        model_hash=model.hash,
        modules=tuple(_module(model, c) for c in containers),
    )


def _module(model: Model, container: Container) -> RouteModule:
    systems = container.systems
    if len(systems) != 1:
        raise GeneratorError(
            container.iri, ARCH.contains, f"expected one arch:System containing the container, found {len(systems)}"
        )
    processes = container.executes
    triggered = _triggered(model, processes)
    exposed = container.exposes
    invoked_only = _invoked_only(model, container, processes)
    exposes = tuple(model.compact(e.iri) for e in exposed)
    endpoints = tuple(_endpoint(model, e, triggered) for e in exposed if e.iri not in invoked_only)
    routed = [e for e in exposed if e.iri not in invoked_only and not isinstance(e, Channel)]
    return RouteModule(
        file_name=route_file_name(container.iri),
        id=local_name(container.iri),
        curie=model.compact(container.iri),
        system=model.compact(systems[0].iri),
        exposes=exposes,
        exposes_text=" , ".join(exposes),
        not_routed=_not_routed(model, container, processes),
        invoked_only=tuple(model.compact(e.iri) for e in exposed if e.iri in invoked_only),
        endpoints=endpoints,
        iri=str(container.iri),
        origins=(str(systems[0].iri),),
        contexts=_contexts(model, routed, endpoints),
    )


def _context_path(shape: Shape) -> str:
    return f"{CONTEXTS}/{local_name(shape.iri)}{SUFFIX}"


def _contexts(model: Model, routed: list[Operation], endpoints: tuple[Endpoint, ...]) -> tuple[ContextRoute, ...]:
    """The context route of each target-classed shape a routed operation
    seam:acceptsShape or seam:returnsShape, by path (ADR-0024 section 5). The
    document is the jsonld generator's, so the two cannot differ."""
    with view_errors():
        shapes = {s: s.target_class for op in routed for s in (op.accepts, op.returns) if s is not None}
    shapes = {s: t for s, t in shapes.items() if t is not None}
    if not shapes:
        return ()
    documents = {ctx.shape: ctx for ctx in extract_jsonld(model).contexts}
    with view_errors():
        pages = [p for p in model.interfaces.pages() if p.path is not None]
    taken = {e.path: e.curie for e in endpoints} | {e.name: e.curie for e in endpoints}
    taken |= {str(p.path): model.compact(p.iri) for p in pages}
    out = []
    for shape, target in sorted(shapes.items(), key=lambda pair: _context_path(pair[0])):
        ctx = documents[str(shape.iri)]
        path, name = _context_path(shape), f"{_shape_name(shape.iri)}_context"
        for claimed in (path, name):
            if claimed in taken:
                raise GeneratorError(
                    shape.iri,
                    SH.targetClass,
                    f"the JSON-LD context route of {model.compact(shape.iri)} (GET {path}, handler {name}) "
                    f"needs {claimed}, which is also the path or handler of {taken[claimed]}",
                )
        out.append(
            ContextRoute(
                shape=model.compact(shape.iri),
                target=model.compact(target.iri),
                file_name=ctx.file_name,
                path=path,
                name=name,
                constant=name.upper(),
                lines=tuple(repr(line) for line in context_document(ctx).splitlines(keepends=True)),
                iri=str(shape.iri),
                origins=tuple(s for s in ctx.sources if s != str(shape.iri)),
            )
        )
    return tuple(out)


def _triggered(model: Model, processes: Many[Process]) -> dict[URIRef, Process]:
    """{operation IRI: process} for each executed process's triggering
    operation (``Process.triggering_operations``: the operation the event
    that seam:triggers the process seam:submitsTo). A channel-started process
    (ADR-0010: ``Process.channel_starts``, its start event seam:subscribesTo a
    channel) has no route and is skipped; a process that is neither raises
    GeneratorError."""
    found: dict[URIRef, Process] = {}
    for process in processes:
        if process not in model.processes:
            raise GeneratorError(process.iri, RDF.type, "a seam:executes target must be a proc:Process")
        ops = process.triggering_operations
        if len(ops) != 1:
            try:
                starts = process.channel_starts
            except ResolutionError as err:
                raise GeneratorError(process.iri, SEAM.subscribesTo, err.detail) from err
            if len(starts) > 1:
                raise GeneratorError(
                    process.iri,
                    SEAM.subscribesTo,
                    "expected at most one subscribed start event, found "
                    f"{[(str(s.event.iri), str(s.channel.iri)) for s in starts]}",
                )
            if starts:
                continue
            raise GeneratorError(
                process.iri,
                SEAM.triggers,
                f"expected one triggering event submitting to one operation, found {[str(o) for o in ops.iris()]}"
                ", and no proc:MessageCatchEvent start event seam:subscribesTo a comm:Channel (ADR-0010)",
            )
        op = ops[0].iri
        if op in found:
            raise GeneratorError(op, SEAM.submitsTo, f"triggers both {found[op].iri} and {process.iri}")
        found[op] = process
    return found


def _not_routed(model: Model, container: Container, processes: Many[Process]) -> tuple[NotRouted, ...]:
    """Operations a process (or a task of its BPMN model) seam:invokes that
    another container seam:exposes."""
    invoked = sorted({op for p in processes for op in p.invoked_operations}, key=lambda op: str(op.iri))
    return tuple(
        NotRouted(
            operation=model.compact(op.iri),
            container=model.compact(other.iri),
            iri=str(op.iri),
            origins=(str(other.iri),),
        )
        for op in invoked
        for other in op.exposed_by
        if other != container
    )


def _invoked_only(model: Model, container: Container, processes: Many[Process]) -> set[URIRef]:
    """IRIs of the operations the container seam:exposes that a process it
    executes (or a task of its BPMN model) seam:invokes and no ifml:Event
    seam:submitsTo. The worker calls them in-process (ADR-0012), so they get
    no route."""
    invoked = {op.iri for p in processes for op in p.invoked_operations}
    return {
        e.iri
        for e in container.exposes
        if isinstance(e, Operation) and e in model.operations and e.iri in invoked and not e.submitted_by
    }


def _handler_name(iri) -> str:
    name = local_name(iri)
    return name[: -len("_op")] if name.endswith("_op") and len(name) > 3 else name


def _endpoint(model: Model, e: Operation | Channel, triggered: dict[URIRef, Process]) -> Endpoint:
    if isinstance(e, Channel):
        return _channel(model, e)
    if e not in model.operations:
        raise GeneratorError(e.iri, RDF.type, "an exposed element must be a hydra:Operation or comm:Channel")
    return _operation(model, e, triggered)


def _channel(model: Model, ch: Channel) -> Endpoint:
    transport = required(ch.transport, ch.iri, COMM.transport)
    if transport == COMM.SemPKMWebhook:
        return _webhook(model, ch)
    if transport != COMM.SSE:
        raise GeneratorError(ch.iri, COMM.transport, f"only comm:SSE channels are routed, found {transport}")
    with view_errors():
        template, _ = _path_template(ch)
        accepts = ch.accepts
    variables = _variables(template)
    if len(variables) != 1:
        raise GeneratorError(
            ch.iri, COMM.path, f"an SSE channel needs exactly one path variable as its scope, found {variables}"
        )
    arguments = tuple(f"{v}: str" for v in variables)
    accepts_curie = model.compact(accepts.iri) if accepts is not None else None
    return Endpoint(
        iri=str(ch.iri),
        origins=(str(accepts.iri),) if accepts is not None else (),
        curie=model.compact(ch.iri),
        name=_handler_name(ch.iri),
        channel=True,
        method="GET",
        path=template,
        arguments=arguments,
        accepts=accepts_curie,
        scope=variables[0],
        method_lower="get",
        arguments_text=", ".join(arguments),
        accepts_suffix=f" ; seam:acceptsShape {accepts_curie}" if accepts_curie else "",
    )


def _webhook(model: Model, ch: Channel) -> Endpoint:
    """The POST route of a SemPKM webhook channel (ADR-0027 section 3), from
    ``ModelGraph.webhook_channel``: its comm:path (no variables), event type
    and accepted shape. The runtime does the rest."""
    with view_errors():
        facts = ModelGraph(model.path, model.ds).webhook_channel(ch.iri)
    accepts = model.compact(facts.shape)
    return Endpoint(
        iri=str(ch.iri),
        origins=tuple(sorted({str(facts.shape), str(facts.target_class), *map(str, facts.processes)})),
        curie=model.compact(ch.iri),
        name=_handler_name(ch.iri),
        channel=False,
        webhook=True,
        method="POST",
        path=facts.path,
        arguments=("request: Request",),
        accepts=accepts,
        event_name=facts.event_name,
        method_lower="post",
        arguments_text="request: Request",
        accepts_suffix=f" ; seam:acceptsShape {accepts}",
    )


def _variables(template: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", template)


def _correlation_key(model: Model, process: Process) -> str:
    """The single rdfs:label of the process's single proc:correlationKey."""
    with view_errors():
        param = process.correlation_parameter
    return label(model, required(param, process.iri, PROC.correlationKey))


def _operation(model: Model, op: Operation, triggered: dict[URIRef, Process]) -> Endpoint:
    method = required(op.method, op.iri, HYDRA.method).upper()
    if method not in METHODS:
        raise GeneratorError(op.iri, HYDRA.method, f"unknown method {method!r}")
    kind = required(op.media_kind, op.iri, SEAM.mediaKind)
    if kind != SEAM.UIFragment:
        raise GeneratorError(op.iri, SEAM.mediaKind, f"only seam:UIFragment operations are routed, found {kind}")
    with view_errors():
        template, _ = _path_template(op)
        accepts = op.accepts
        returns = op.returns
    variables = _variables(template)

    body = None
    media_type = op.request_media_type
    if media_type is not None:
        if media_type not in REQUEST_BODIES:
            raise GeneratorError(op.iri, COMM.requestMediaType, f"unknown request media type {media_type!r}")
        body = Body(*REQUEST_BODIES[media_type])

    validate = None
    if accepts is not None:
        if body is None:
            raise GeneratorError(op.iri, COMM.requestMediaType, "seam:acceptsShape needs a request body")
        var = _shape_name(accepts.iri)
        if var in variables:
            var += "_payload"  # never shadow the path variable (the correlation key)
        validate = Validate(var=var, shape=model.compact(accepts.iri), source=body.var)

    complete = None
    used: list[Process] = []  # the processes the endpoint starts or completes a task of
    task = _completed_task(op)
    if task is not None:
        if op.iri in triggered:
            raise GeneratorError(
                op.iri, SEAM.submitsTo, f"completes {task} and starts {triggered[op.iri].iri}; an operation does one"
            )
        if body is None:
            raise GeneratorError(op.iri, COMM.requestMediaType, f"completing {task} needs a request body")
        process = _task_process(model, task)
        used.append(process)
        key = _correlation_key(model, process)
        if key not in variables:
            raise GeneratorError(
                process.iri,
                PROC.correlationKey,
                f"{key!r} is not a path variable of {op.iri} ({template}), "
                f"so the completion of {task} cannot name its instance",
            )
        complete = Complete(task=_task_curie(model, task), payload=body.var, key=key)

    start = None
    if op.iri in triggered:
        process = triggered[op.iri]
        used.append(process)
        if validate is None:
            raise GeneratorError(op.iri, SEAM.acceptsShape, f"starting {process.iri} needs a validated payload")
        key = _correlation_key(model, process)
        if key not in variables:
            raise GeneratorError(
                process.iri, PROC.correlationKey, f"{key!r} is not a path variable of {op.iri} ({template})"
            )
        start = Start(process=model.compact(process.iri), payload=validate.var, key=key)

    write = None
    if (
        start is None
        and complete is None
        and validate is not None
        and accepts is not None
        and _form_writes(op, accepts)
    ):
        write = Write(shape=validate.shape, var=validate.var, source=validate.source)

    query = None
    if (method == "GET" or complete is not None) and returns is not None:
        query = Query(var=_shape_name(returns.iri) + "s", shape=model.compact(returns.iri), filters=tuple(variables))

    with view_errors():
        target = returns.target_class if returns is not None else None
    link = ""
    if returns is not None and target is not None:
        link = repr(f'<{_context_path(returns)}>; rel="{CONTEXT_REL}"; type="{JSONLD}"')
    lead = "response = " if link else "return "

    name, component, frag_kind = fragment_for(model, op)
    if frag_kind == ITEM:
        if validate is None or returns != accepts:
            raise GeneratorError(
                op.iri,
                SEAM.returnsShape,
                f"the item partial {name} renders the accepted entity, "
                "so seam:returnsShape must equal seam:acceptsShape",
            )
        render = Render(name=name, data=validate.var, params=(), multiline=method != "GET", lead=lead)
    else:
        if query is None:
            raise GeneratorError(
                op.iri,
                SEAM.returnsShape,
                f"the component partial {name} renders a query of the returned shape "
                "(a GET, or a user-task completion)",
            )
        parameters = model.views.intern(ComponentView, URIRef(str(component))).parameters()
        params = [p for p in parameters if p in variables]
        render = Render(name=name, data=query.var, params=tuple(params), multiline=method != "GET", lead=lead)

    arguments = tuple(f"{v}: str" for v in variables) + (("request: Request",) if body else ())
    if complete is not None:
        arguments += (f'identity: Identity = Depends(runtime.task_policy("{complete.task}"))',)
    policies = tuple(model.compact(p.iri) for p in op.governed_by)
    with view_errors():
        origins = {str(x.iri) for x in (accepts, returns) if x is not None}
        origins |= {str(p.iri) for p in op.governed_by}
        origins.add(str(component))
        origins |= {
            str(flow.iri)
            for event in op.submitted_by
            for flow in event.flows
            if flow.kind == IFML.NavigationFlow and URIRef(str(component)) in flow.targets.iris()
        }
        for process in used:
            origins |= {str(process.iri), *map(str, process.bpmn_models)}
            if process.correlation_parameter is not None:
                origins.add(str(process.correlation_parameter))
    if task is not None:
        origins.add(str(task))
    if target is not None:
        origins.add(str(target.iri))
    return Endpoint(
        iri=str(op.iri),
        origins=tuple(sorted(origins)),
        curie=model.compact(op.iri),
        name=_handler_name(op.iri),
        channel=False,
        method=method,
        path=template,
        arguments=arguments,
        policies=policies,
        body=body,
        validate=validate,
        start=start,
        write=write,
        complete=complete,
        query=query,
        render=render,
        errors=_errors(model, op),
        method_lower=method.lower(),
        arguments_text=", ".join(arguments),
        dependencies="[" + ", ".join(f'Depends(runtime.policy("{p}"))' for p in policies) + "]",
        validate_only=validate is not None and write is None and complete is None,
        link=link,
    )


def _errors(model: Model, op: Operation) -> tuple[ErrorResponse, ...]:
    """The problem+json responses of the operation's error statuses
    (ADR-0013), one per hydra:statusCode; several statuses sharing a code
    share a response whose schema is oneOf their shapes'."""
    with view_errors():
        statuses = op.errors
    by_code: dict[int, list[tuple[Status, Shape]]] = {}
    for status in statuses:
        with view_errors():
            code, shape = status.status_code, status.returns
        code = required(code, status.iri, HYDRA.statusCode)
        shape = required(shape, status.iri, SEAM.returnsShape)
        by_code.setdefault(code, []).append((status, shape))
    out = []
    for code, pairs in sorted(by_code.items()):
        schemas = [_problem_schema(shape) for _status, shape in pairs]
        schema = schemas[0] if len(schemas) == 1 else {"oneOf": schemas}
        out.append(
            ErrorResponse(
                code=code,
                description="; ".join(label(model, status.iri) for status, _shape in pairs),
                content=_literal({PROBLEM_JSON: {"schema": schema}}),
                facts=tuple(
                    f"{model.compact(status.iri)} hydra:statusCode {code} ; "
                    f'comm:errorCode "{status.error_code}" ; seam:returnsShape {model.compact(shape.iri)}'
                    for status, shape in pairs
                ),
            )
        )
    return tuple(out)


def _literal(value) -> str:
    """``value`` (dicts, lists, str, int, bool) as a Python literal, dict keys
    sorted and strings double-quoted (JSON escaping is valid Python), so the
    text is the same on every run."""
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)}: {_literal(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    return json.dumps(value)


def _problem_schema(shape: Shape) -> dict:
    """A JSON Schema for a body of the error shape: one property per field
    (its Field.name, typed from sh:datatype), required when
    sh:minCount > 0, and closed, as the runtime's validation is."""
    with view_errors():
        fields = shape.fields()
    return {
        "type": "object",
        "properties": {f.name: {"type": JSON_TYPES.get(f.datatype, "string")} for f in fields},
        "required": sorted(f.name for f in fields if f.required),
        "additionalProperties": False,
    }


def _submitting_forms(op: Operation) -> list[ComponentView]:
    """The ifml:Forms that ifml:hasEvent an event that seam:submitsTo ``op``."""
    with view_errors():
        forms = [e.component for e in op.submitted_by]
    return [f for f in forms if f is not None and IFML.Form in f.types]


def _completed_task(op: Operation) -> URIRef | None:
    """The proc:UserTask that seam:completedOn an ifml:Form whose event
    seam:submitsTo ``op`` (ADR-0009), or None; several raise."""
    tasks = sorted(
        {t.iri for form in _submitting_forms(op) for t in form.completes if PROC.UserTask in t.types}, key=str
    )
    if len(tasks) > 1:
        raise GeneratorError(
            op.iri, SEAM.submitsTo, f"completes several user tasks {[str(t) for t in tasks]}; expected one"
        )
    return tasks[0] if tasks else None


def _form_writes(op: Operation, shape: Shape) -> bool:
    """Whether an ifml:Form that seam:writes ``shape`` has an event that
    seam:submitsTo ``op`` (the D026 write rule)."""
    return any(shape in form.writes for form in _submitting_forms(op))


# ── rendering ───────────────────────────────────────────────────────────────


def render_routes(routes: RoutesModel) -> dict[str, str]:
    """{file name: text}, one route module per serving container."""
    template = _environment().get_template(TEMPLATE_NAME)
    return {m.file_name: template.render(r=routes, m=m) for m in routes.modules}


def trace_routes(routes: RoutesModel, generator: str = "fastapi") -> dict[str, Trace]:
    """{file name: Trace} for the files of ``render_routes(routes)``; a line
    no origin-carrying value lands on takes the serving container's IRI."""
    files = render_routes(routes)
    env = _tracing_environment()
    return {
        m.file_name: trace_template(
            env,
            TEMPLATE_NAME,
            {"r": routes, "m": m},
            output=m.file_name,
            generator=generator,
            expected=files[m.file_name],
            fallback=view_iris(m),
        )
        for m in routes.modules
    }


def extract_route_module(model: Model) -> RoutesModel:
    """The routes model of the model's one serving container; no or several
    serving containers are a GeneratorError(model, seam:executes)."""
    routes = extract_routes(model)
    if len(routes.modules) != 1:
        raise GeneratorError(
            model.subject, SEAM.executes, f"expected one serving container, found {[m.curie for m in routes.modules]}"
        )
    return routes


def route_module(trig_path) -> tuple[str, str]:
    """(file name, text) of the model's one route module (``extract_route_module``)."""
    routes = extract_route_module(load(trig_path))
    name = routes.modules[0].file_name
    return name, render_routes(routes)[name]


def generate_routes(trig_path) -> str:
    """Load the model and render its one route module (chat_api.py for the
    chat app)."""
    return route_module(trig_path)[1]


__all__ = [
    "RoutesModel",
    "RouteModule",
    "ContextRoute",
    "Endpoint",
    "extract_route_module",
    "extract_routes",
    "generate_routes",
    "render_routes",
    "route_module",
    "trace_routes",
    "route_file_name",
    "serving_containers",
    "TEMPLATE_NAME",
]
