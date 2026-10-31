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
route: the runtime starts it when its channel is published on. Nor does an
exposed operation that a task of an executed process ``seam:invokes`` and no
``ifml:Event`` ``seam:submitsTo`` (a ``comm:PythonHandler``'s operation,
ADR-0012): the worker serves it in-process, and the module header says so.
An operation that declares error statuses (ADR-0013: each ``hydra:possibleStatus``
with a ``comm:errorCode``) lists each as an ``application/problem+json``
response, keyed by its ``hydra:statusCode``, with a JSON Schema derived from
the status's ``seam:returnsShape``; the module then defines one
``problem_handler`` that ``seams_runtime.host`` installs for
``OperationError``, answering with ``Runtime.problem`` for the raising route's
operation. Every collection is sorted by IRI, and a missing or ambiguous
required fact raises ``GeneratorError`` naming the subject IRI and predicate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rdflib import RDF, URIRef
from rdflib.namespace import XSD
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
from .htmx import _environment, _path_template, _shape_name, _task_curie, _task_process

TEMPLATE_NAME = "fastapi_routes.py.j2"

# comm:requestMediaType -> (variable, Starlette Request coroutine method)
REQUEST_BODIES = {
    "application/x-www-form-urlencoded": ("form", "form"),
    "application/json": ("body", "json"),
}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
PROBLEM_JSON = "application/problem+json"  # RFC 9457
# sh:datatype -> JSON Schema type of an error shape's member; any other datatype is a string
JSON_TYPES = {XSD.integer: "integer", XSD.decimal: "number", XSD.boolean: "boolean"}


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

    @property
    def multiline_decorator(self) -> bool:
        """Whether the decorator spreads its arguments over lines (policies or errors)."""
        return bool(self.policies or self.errors)


@dataclass(frozen=True)
class NotRouted:
    operation: str  # curie of an operation a task of this container invokes
    container: str  # curie of the other container that exposes it


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

    @property
    def needs_identity(self) -> bool:
        """Whether a completion handler takes ``identity: Identity``."""
        return any(e.complete is not None for e in self.endpoints)

    @property
    def problem_routes(self) -> tuple[tuple[str, str], ...]:
        """(handler name, operation curie) of each endpoint that declares errors."""
        return tuple((e.name, e.curie) for e in self.endpoints if e.errors)

    @property
    def runtime_imports(self) -> str:
        """The names the module imports from seams_runtime."""
        names = ["Identity"] if self.needs_identity else []
        names += ["OperationError"] if self.problem_routes else []
        return ", ".join([*names, "Runtime"])

    @property
    def response_imports(self) -> str:
        """The names the module imports from fastapi.responses."""
        return ", ".join(["HTMLResponse", *(["JSONResponse"] if self.problem_routes else []), "StreamingResponse"])


@dataclass(frozen=True)
class RoutesModel:
    model_stem: str
    model_file: str  # the TriG file name, mounted at /model/<file>
    model_hash: str
    modules: tuple[RouteModule, ...]


# ── extraction ──────────────────────────────────────────────────────────────


def serving_containers(model: Model) -> Many[Container]:
    """The arch:Containers that serve routes (D026): each one that
    seam:executes a proc:Process or seam:exposes a hydra:Operation some
    ifml:Event seam:submitsTo, by IRI. An operation only a task
    seam:invokes (the chat app's :completion_op) does not make its container
    serving."""
    processes, operations = model.processes, model.operations
    return model.architecture.containers().where(
        lambda c: (
            any(p in processes for p in c.executes)
            or any(isinstance(e, Operation) and e in operations and e.submitted_by for e in c.exposes)
        )
    )


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
    return RouteModule(
        file_name=f"{local_name(container.iri)}.py",
        id=local_name(container.iri),
        curie=model.compact(container.iri),
        system=model.compact(systems[0].iri),
        exposes=tuple(model.compact(e.iri) for e in exposed),
        not_routed=_not_routed(model, container, processes),
        invoked_only=tuple(model.compact(e.iri) for e in exposed if e.iri in invoked_only),
        endpoints=tuple(_endpoint(model, e, triggered) for e in exposed if e.iri not in invoked_only),
    )


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
        NotRouted(operation=model.compact(op.iri), container=model.compact(other.iri))
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
    return Endpoint(
        curie=model.compact(ch.iri),
        name=_handler_name(ch.iri),
        channel=True,
        method="GET",
        path=template,
        arguments=tuple(f"{v}: str" for v in variables),
        accepts=model.compact(accepts.iri) if accepts is not None else None,
        scope=variables[0],
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
    task = _completed_task(op)
    if task is not None:
        if op.iri in triggered:
            raise GeneratorError(
                op.iri, SEAM.submitsTo, f"completes {task} and starts {triggered[op.iri].iri}; an operation does one"
            )
        if body is None:
            raise GeneratorError(op.iri, COMM.requestMediaType, f"completing {task} needs a request body")
        process = _task_process(model, task)
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

    name, component, frag_kind = fragment_for(model, op)
    if frag_kind == ITEM:
        if validate is None or returns != accepts:
            raise GeneratorError(
                op.iri,
                SEAM.returnsShape,
                f"the item partial {name} renders the accepted entity, "
                "so seam:returnsShape must equal seam:acceptsShape",
            )
        render = Render(name=name, data=validate.var, params=(), multiline=method != "GET")
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
        render = Render(name=name, data=query.var, params=tuple(params), multiline=method != "GET")

    arguments = tuple(f"{v}: str" for v in variables) + (("request: Request",) if body else ())
    if complete is not None:
        arguments += (f'identity: Identity = Depends(runtime.task_policy("{complete.task}"))',)
    return Endpoint(
        curie=model.compact(op.iri),
        name=_handler_name(op.iri),
        channel=False,
        method=method,
        path=template,
        arguments=arguments,
        policies=tuple(model.compact(p.iri) for p in op.governed_by),
        body=body,
        validate=validate,
        start=start,
        write=write,
        complete=complete,
        query=query,
        render=render,
        errors=_errors(model, op),
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
    (its sh:path local name, typed from sh:datatype), required when
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


def route_module(trig_path) -> tuple[str, str]:
    """(file name, text) of the model's one route module; no or several
    serving containers raise GeneratorError(model, seam:executes)."""
    model = load(trig_path)
    routes = extract_routes(model)
    if len(routes.modules) != 1:
        raise GeneratorError(
            model.subject, SEAM.executes, f"expected one serving container, found {[m.curie for m in routes.modules]}"
        )
    name = routes.modules[0].file_name
    return name, render_routes(routes)[name]


def generate_routes(trig_path) -> str:
    """Load the model and render its one route module (chat_api.py for the
    chat app)."""
    return route_module(trig_path)[1]


__all__ = [
    "RoutesModel",
    "RouteModule",
    "Endpoint",
    "extract_routes",
    "generate_routes",
    "render_routes",
    "route_module",
    "serving_containers",
    "TEMPLATE_NAME",
]
