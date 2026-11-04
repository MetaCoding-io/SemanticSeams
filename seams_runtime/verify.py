"""Run what a model says it should do (ADR-0014): the harness generated tests call.

The tests generator (``seams_gen.tests``) writes pytest files whose data all
comes from the model: each ``verify:Scenario`` as a ``Scenario`` value,
each decision example as a decision IRI with its inputs and outputs, each
shape example as a shape and a node. Those files hold no logic beyond
asserting what this module returns, so a generated test reads as the model
fact it checks (principle 7, the P007 thin-handler rule applied to tests).

- ``serve`` builds the host app (``seams_runtime.host.build_app``) for a
  route module on a temporary SQLite store, with no dev user or seed, so
  every identity comes from the request headers.
- ``run_scenario`` drives a ``Scenario`` through that app's routes as a
  person would: it submits the start form as the scenario's party, then
  completes each step's user task as the step's party, waiting after each
  request until the instance settles. It returns a ``Run``: the instance
  status, the entity's lifecycle state and the BPMN elements reached. A
  request that is not answered 200, a step whose task is not open, or a run
  that never settles raises ``ScenarioError`` (an ``AssertionError``, so
  pytest reports it as the scenario's failure) naming the scenario and step.
- ``attempt`` sends the request that reaches a permission's target (a
  ``Target``: a scenario's start or step, or a direct request when no
  scenario reaches it) as a party, or with no identity, after driving the
  scenario up to it. It returns an ``Attempt``: the status, the problem
  detail and whether the store is unchanged, for the generated policy tests.
- ``identity`` is the headers a party acts with: the party's local name as
  the user and as its one role, which ``RoleEvaluator`` admits for a
  permission assigned to that party.
- ``load_model`` loads the model and checks it still hashes to the hash the
  generated file embeds, so stale tests fail with "regenerate" rather than
  testing an old model's data.
- ``decide`` evaluates a decision through ``Engine.decide``, and ``value``
  turns an expected literal into the Python value to compare with.
- ``shape_conforms`` validates one example node against one shape with
  pyshacl: the shape's description (its triples and blank nodes) with an
  added ``sh:targetNode``, and the node's description as the data graph, so
  no other shape in the model takes part.
- ``response_conforms`` does the same for a JSON response body: each object
  becomes a node whose keys are the shape's field local names.
- ``smoke`` is what the smoke generator's tests (``seams_gen.smoke``,
  backlog A9) call: it sends a ``Probe`` (one operation, its path filled)
  to a running app as the ``Caller`` the environment configures
  (``smoke_caller``), and checks the answer's status and body against the
  operation's seam:returnsShape. ``smoke_skip`` says why a probe is not
  sent: a governing policy does not admit the caller, or no example fills
  its path.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rdflib import RDF, BNode, Graph, Literal, URIRef
from rdflib.namespace import SH
from rdflib.term import Node

from .engine import Engine
from .model import ModelGraph, local_name
from .policy import DEFAULT_IDENTITY_HEADER, DEFAULT_ROLES_HEADER, DEV_USER_ENV
from .runtime import DB_ENV, MODEL_ENV, STORE_OVERRIDE_ENV, TEMPLATES_ENV
from .worker import COMPLETE, FAILED, WAITING

SETTLED = (WAITING, COMPLETE, FAILED)
DEFAULT_TIMEOUT = 10.0


class ScenarioError(AssertionError):
    """A scenario could not be driven to its end; the message names the scenario and the step."""


class ModelHashMismatch(AssertionError):
    """The generated tests were generated from a different model; regenerate them."""


@dataclass(frozen=True)
class Request:
    """One form submission: the route (method and hydra:template), the
    party who sends it and the form fields (sh:path local name -> lexical value)."""

    method: str
    path: str
    actor: str
    data: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Step:
    """Complete the user task ``task`` (IRI) with ``request``."""

    task: str
    request: Request


@dataclass(frozen=True)
class Scenario:
    """A verify:Scenario resolved to routes. ``key_variable`` is the
    process's proc:correlationKey path variable; ``key`` fills it.
    ``entity_shape`` is the shape whose stored status the run's ``state``
    reads (the shape whose seam:lifecycle holds the expected state), or None."""

    iri: str
    process: str
    key_variable: str
    key: str
    start: Request
    steps: tuple[Step, ...]
    entity_shape: str | None


@dataclass(frozen=True)
class Run:
    """What a scenario run reached: the instance ``status`` (waiting,
    complete or failed), its ``error`` when failed, the ``entity_shape``
    entity's stored lifecycle ``state`` label (None without one), and the
    IRI of every BPMN element the run went through, in order."""

    status: str
    error: object
    state: str | None
    reached: tuple[str, ...]


@dataclass(frozen=True)
class Target:
    """Where an odrl:permission's target is reached. With ``scenario``: its
    request ``at`` (0: the start request, n: step n's), after the start and
    the steps before it. Without one (no scenario reaches the target):
    ``request`` sent at once, every path variable set to ``key``."""

    scenario: Scenario | None
    at: int = 0
    request: Request | None = None
    key: str = ""


@dataclass(frozen=True)
class Attempt:
    """The answer to a request a party sent to a target: the HTTP ``status``,
    the problem response's ``detail`` (None unless the answer is JSON), the
    body ``text`` and whether the store's instances and open tasks are
    ``unchanged`` by the request."""

    status: int
    detail: object
    text: str
    unchanged: bool


def load_model(model: Path, expected_hash: str) -> ModelGraph:
    """The model at ``model``; ``ModelHashMismatch`` unless it hashes to
    ``expected_hash``, the hash the generated tests embed (principle 7)."""
    graph = ModelGraph(model)
    if graph.hash != expected_hash:
        raise ModelHashMismatch(
            f"these tests were generated from {expected_hash}, but {model} is {graph.hash}; "
            "regenerate them (seams generate --project <the app's directory>)"
        )
    return graph


def value(lexical: str, datatype: str | None = None) -> object:
    """The Python value of the literal ``lexical``^^``datatype`` (rdflib's mapping)."""
    return Literal(lexical, datatype=None if datatype is None else URIRef(datatype)).toPython()


def identity(party: str) -> dict[str, str]:
    """The request headers party ``party`` (an IRI or local name) acts with."""
    name = local_name(party)
    return {DEFAULT_IDENTITY_HEADER: name, DEFAULT_ROLES_HEADER: name}


@contextmanager
def serve(model: Path, routes: Path, templates: Path, db: Path) -> Iterator[tuple[object, object]]:
    """(TestClient, Runtime) of the host app for ``routes`` on ``model``, with
    templates from ``templates`` and a fresh SQLite store at ``db``. The
    environment variables it sets are restored on exit."""
    from fastapi.testclient import TestClient

    from .host import SEED_ENV, build_app

    wanted = {
        MODEL_ENV: str(model),
        TEMPLATES_ENV: str(templates),
        DB_ENV: str(db),
        STORE_OVERRIDE_ENV: "sqlite",
        DEV_USER_ENV: None,
        SEED_ENV: None,
    }
    saved = {name: os.environ.get(name) for name in wanted}
    try:
        for name, value in wanted.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        app = build_app(routes)
        with TestClient(app) as client:
            yield client, app.state.runtime
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _instance(runtime, scenario: Scenario) -> dict | None:
    rows = [r for r in runtime.store.list_instances(correlation_key=scenario.key) if r["process"] == scenario.process]
    return rows[-1] if rows else None


def _settle(runtime, scenario: Scenario, after: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        row = _instance(runtime, scenario)
        if row is not None and row["status"] in SETTLED:
            return row
        if time.monotonic() >= deadline:
            status = None if row is None else row["status"]
            raise ScenarioError(f"{scenario.iri}: no settled instance {timeout}s after {after} (status {status!r})")
        time.sleep(0.02)


def _send(client, scenario: Scenario, request: Request, what: str):
    path = request.path.replace("{" + scenario.key_variable + "}", scenario.key)
    if "{" in path:
        raise ScenarioError(
            f"{scenario.iri}: {what}: {request.path} has a path variable other than the "
            f"correlation key {{{scenario.key_variable}}}"
        )
    response = client.request(request.method, path, data=dict(request.data), headers=identity(request.actor))
    if response.status_code != 200:
        raise ScenarioError(
            f"{scenario.iri}: {what}: {request.method} {path} as {local_name(request.actor)} "
            f"answered {response.status_code}: {response.text}"
        )
    return response


def _open_step(runtime, scenario: Scenario, row: dict, number: int, step: Step) -> str:
    """The step's description; ``ScenarioError`` unless its task is open."""
    what = f"step {number} ({step.task})"
    open_tasks = sorted(r["task"] for r in runtime.store.list_user_tasks() if r["correlation_key"] == scenario.key)
    if step.task not in open_tasks:
        raise ScenarioError(
            f"{scenario.iri}: {what} is not open; the instance is {row['status']!r} with open tasks {open_tasks}"
        )
    return what


def _drive(client, runtime, scenario: Scenario, steps: int, timeout: float) -> dict | None:
    """Submit the start and complete the first ``steps`` steps; the settled
    instance row (None when ``steps`` is negative, so nothing was sent)."""
    if steps < 0:
        return None
    _send(client, scenario, scenario.start, "start")
    row = _settle(runtime, scenario, "the start", timeout)
    for number, step in enumerate(scenario.steps[:steps], 1):
        what = _open_step(runtime, scenario, row, number, step)
        _send(client, scenario, step.request, what)
        row = _settle(runtime, scenario, what, timeout)
    return row


def run_scenario(client, runtime, scenario: Scenario, timeout: float = DEFAULT_TIMEOUT) -> Run:
    """Drive ``scenario`` through the app ``serve`` built and return its ``Run``."""
    row = _drive(client, runtime, scenario, len(scenario.steps), timeout)
    state = None
    if scenario.entity_shape is not None:
        entities = runtime.store.query(URIRef(scenario.entity_shape), correlation_key=scenario.key)
        state = entities[-1].get("status") if entities else None
    workflow = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"]))
    reached = tuple(r["iri"] for r in workflow.data["seams"]["trace"])
    return Run(row["status"], row.get("error"), state, reached)


def _store_snapshot(runtime) -> tuple:
    """Every instance's status and every open user task: what a denied request must not change."""
    instances = sorted((r["instance_id"], r["status"]) for r in runtime.store.list_instances())
    tasks = sorted((r["task"], r["correlation_key"]) for r in runtime.store.list_user_tasks())
    return instances, tasks


def attempt(client, runtime, target: Target, party: str | None, timeout: float = DEFAULT_TIMEOUT) -> Attempt:
    """Reach ``target`` and send its request as ``party`` (None: no identity headers).

    With a scenario, its start and the steps before ``target.at`` run as
    their own parties first, and the target step's task must be open
    (``ScenarioError`` otherwise). An answered 200 is settled before the
    ``Attempt`` is returned."""
    scenario = target.scenario
    if scenario is None:
        request, key = target.request, target.key
        path = re.sub(r"\{[^}]*\}", key, request.path)
    else:
        row = _drive(client, runtime, scenario, target.at - 1, timeout)
        if target.at == 0:
            request = scenario.start
        else:
            request = scenario.steps[target.at - 1].request
            _open_step(runtime, scenario, row, target.at, scenario.steps[target.at - 1])
        path = request.path.replace("{" + scenario.key_variable + "}", scenario.key)
    before = _store_snapshot(runtime)
    headers = {} if party is None else identity(party)
    response = client.request(request.method, path, data=dict(request.data), headers=headers)
    if response.status_code == 200 and scenario is not None:
        _settle(runtime, scenario, f"{request.method} {path}", timeout)
    detail = None
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
    return Attempt(response.status_code, detail, response.text, _store_snapshot(runtime) == before)


def decide(engine: Engine, decision: str, inputs: dict[str, str]) -> dict:
    """{DMN output name: value} of ``decision`` on ``inputs`` (``Engine.decide``)."""
    return engine.decide(URIRef(decision), inputs)


def _describe(source: Graph, node: Node, into: Graph) -> None:
    """Copy ``node``'s triples into ``into``, following blank-node objects (its description)."""
    for _, p, o in source.triples((node, None, None)):
        if (node, p, o) in into:
            continue
        into.add((node, p, o))
        if isinstance(o, BNode):
            _describe(source, o, into)


def _conforms(model: ModelGraph, shape: str, data: Graph, nodes: list[Node]) -> tuple[bool, str]:
    """(conforms, pyshacl's report text) of ``nodes`` in ``data`` against ``shape`` alone.
    Only results of a severity other than sh:Warning break conformance (ADR-0021)."""
    from pyshacl import validate

    shapes = Graph()
    _describe(model.ds, URIRef(shape), shapes)
    for node in nodes:
        shapes.add((URIRef(shape), SH.targetNode, node))
    _, report, text = validate(data, shacl_graph=shapes)
    results = cast(Graph, report)
    conforms = all(
        results.value(r, SH.resultSeverity) == SH.Warning for r in results.subjects(RDF.type, SH.ValidationResult)
    )
    return conforms, str(text)


def shape_conforms(model: ModelGraph, shape: str, node: str) -> tuple[bool, str]:
    """(conforms, pyshacl's report text) of example ``node`` against ``shape`` alone."""
    data = Graph()
    _describe(model.ds, URIRef(node), data)
    return _conforms(model, shape, data, [URIRef(node)])


def _literal(value: object, datatype: URIRef | None) -> Literal:
    """A JSON scalar as the literal a field of ``datatype`` holds: its JSON
    lexical form with that datatype, or rdflib's mapping without one."""
    if datatype is None or isinstance(value, bool):
        return Literal(value)
    return Literal(str(value), datatype=datatype)


def response_conforms(model: ModelGraph, shape: str, data: object) -> tuple[bool, str]:
    """(conforms, report) of a JSON response body against ``shape`` alone.

    An object is one node; a list is one node per item. Each key that is the
    local name of one of the shape's field paths becomes a triple on that
    path (a list value, one per item), typed with the field's sh:datatype.
    Other keys and null values are left out, so a key the shape does not
    name is not checked. A body that is neither an object nor a list of
    objects does not conform."""
    items = data if isinstance(data, list) else [data]
    if not all(isinstance(item, dict) for item in items):
        return False, f"expected a JSON object or a list of objects for {shape}, got {data!r}"
    fields = {f.name: f for f in model.shape(shape).fields()}
    graph, nodes = Graph(), []
    for item in items:
        node = BNode()
        nodes.append(node)
        for key, raw in sorted(item.items()):
            found = fields.get(key)
            if found is None:
                continue
            for one in raw if isinstance(raw, list) else [raw]:
                if one is not None:
                    graph.add((node, found.iri, _literal(one, found.datatype)))
    return _conforms(model, shape, graph, nodes)


# ── smoke tests (backlog A9): each operation called on a running app ─────────

SMOKE_BASE_URL_ENV = "SEAMS_SMOKE_BASE_URL"
SMOKE_USER_ENV = "SEAMS_SMOKE_USER"
SMOKE_GROUPS_ENV = "SEAMS_SMOKE_GROUPS"
E2E_ENV = "SEAMS_E2E"
JSON_TYPES = ("application/json", "application/problem+json")


@dataclass(frozen=True)
class Probe:
    """One hydra:Operation a smoke test calls. ``path`` is its comm:path
    with every variable filled; ``data`` the form fields it sends. A 2xx
    answer conforms to ``returns`` (when ``json``; a seam:UIFragment's HTML
    is checked by status only), and an answer with an ``errors`` status
    (hydra:statusCode, error shape) conforms to that error shape. When
    ``policies`` govern it, only an identity named by ``parties`` (or any
    identity, with ``any_party``) is admitted. ``skip`` is why it cannot be
    called at all (a path variable or body no example gives)."""

    iri: str
    method: str
    path: str
    data: tuple[tuple[str, str], ...] = ()
    json: bool = True
    returns: str | None = None
    errors: tuple[tuple[int, str | None], ...] = ()
    policies: tuple[str, ...] = ()
    parties: tuple[str, ...] = ()
    any_party: bool = False
    skip: str | None = None


@dataclass(frozen=True)
class Caller:
    """Who smoke tests call as, and where: the app's ``base_url`` and the
    identity sent as ``X-Forwarded-User`` (``user``) and
    ``X-Forwarded-Groups`` (``groups``); no user sends no identity headers."""

    base_url: str
    user: str | None = None
    groups: tuple[str, ...] = ()

    @property
    def headers(self) -> dict[str, str]:
        if not self.user:
            return {}
        headers = {DEFAULT_IDENTITY_HEADER: self.user}
        if self.groups:
            headers[DEFAULT_ROLES_HEADER] = ",".join(self.groups)
        return headers

    @property
    def who(self) -> str:
        if not self.user:
            return "no identity"
        return f"{self.user} (groups: {', '.join(self.groups) or 'none'})"


@dataclass(frozen=True)
class Check:
    """A smoke call's verdict: ``ok``, and a ``detail`` naming the method,
    URL and status, with pyshacl's report when the body does not conform."""

    ok: bool
    detail: str


def smoke_caller(env: dict[str, str] | None = None) -> Caller | None:
    """The ``Caller`` the environment configures (SEAMS_SMOKE_BASE_URL,
    SEAMS_SMOKE_USER, comma-separated SEAMS_SMOKE_GROUPS); None without a base URL."""
    env = dict(os.environ) if env is None else env
    base_url = env.get(SMOKE_BASE_URL_ENV, "").strip()
    if not base_url:
        return None
    groups = tuple(g.strip() for g in env.get(SMOKE_GROUPS_ENV, "").split(",") if g.strip())
    return Caller(base_url.rstrip("/"), env.get(SMOKE_USER_ENV, "").strip() or None, groups)


def smoke_required(env: dict[str, str] | None = None) -> bool:
    """True under SEAMS_E2E=1, where a missing base URL fails rather than skips."""
    env = dict(os.environ) if env is None else env
    return env.get(E2E_ENV) == "1"


def smoke_skip(probe: Probe, caller: Caller) -> str | None:
    """Why ``caller`` cannot call ``probe`` (its own skip, or a governing
    policy that does not admit the identity, named by CURIE); None when it can.
    Admission is ``RoleEvaluator``'s: the user or a group is a party's IRI or local name."""
    if probe.skip is not None:
        return probe.skip
    if not probe.policies:
        return None
    names = {n for n in (caller.user, *caller.groups) if n}
    if names and (probe.any_party or any(p in names or local_name(p) in names for p in probe.parties)):
        return None
    admits = "any authenticated identity" if probe.any_party else ", ".join(local_name(p) for p in probe.parties)
    return f"{', '.join(probe.policies)} does not admit {caller.who}; it admits {admits}"


def _body(response) -> object:
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in JSON_TYPES:
        raise ValueError(f"the body is {content_type or 'untyped'}, not JSON")
    return response.json()


def smoke(model: ModelGraph, probe: Probe, caller: Caller, timeout: float = DEFAULT_TIMEOUT, client=None) -> Check:
    """Call ``probe`` on ``caller``'s app and check the answer: a 2xx body
    conforms to ``returns`` (JSON operations), and any other status is one
    of ``errors`` whose body conforms to its error shape. No answer (a
    connection error or timeout) and an undeclared status fail the check.
    ``client`` (anything with httpx's ``request``, e.g. a ``TestClient``,
    which brings its own timeout) defaults to a fresh httpx request."""
    import httpx

    url = caller.base_url + probe.path
    what = f"{probe.method} {url} as {caller.who}"
    headers = {**caller.headers, "Accept": "application/json, application/problem+json, text/html"}
    data = dict(probe.data) or None
    try:
        if client is None:
            response = httpx.request(probe.method, url, data=data, headers=headers, timeout=timeout)
        else:
            response = client.request(probe.method, url, data=data, headers=headers)
    except httpx.HTTPError as err:
        return Check(False, f"{what}: no answer: {type(err).__name__}: {err}")
    status = response.status_code
    answered = f"{what} answered {status}"
    if 200 <= status < 300:
        shape = probe.returns if probe.json else None
        kind = "a seam:UIFragment, checked by status" if not probe.json else "no seam:returnsShape"
    else:
        declared = dict(probe.errors)
        if status not in declared:
            known = ", ".join(str(code) for code in sorted(declared)) or "none"
            return Check(False, f"{answered}, not 2xx or a declared error status ({known}): {response.text[:2000]}")
        shape, kind = declared[status], "a declared error status with no seam:returnsShape"
    if shape is None:
        return Check(True, f"{answered} ({kind})")
    try:
        body = _body(response)
    except ValueError as err:
        return Check(False, f"{answered}: {err}, so it cannot conform to {shape}: {response.text[:2000]}")
    conforms, report = response_conforms(model, shape, body)
    if not conforms:
        return Check(False, f"{answered}; the body does not conform to {shape}:\n{report}")
    return Check(True, f"{answered}; the body conforms to {shape}")


# ── acceptance checks (backlog C2): a hand-written handler against the model ──

#: (sh:path local name, required) for each field of a shape, by name.
Fields = tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class Handler:
    """One ``comm:PythonHandler`` function the acceptance tests check:
    ``handler`` its ``comm:handler`` dotted path in the handlers package,
    ``implementation`` the implementation IRI, and per operation it
    implements the fields of the shape it accepts and of the shape it
    returns (None: the operation states no seam:acceptsShape or
    seam:returnsShape)."""

    handler: str
    implementation: str
    accepts: tuple[Fields | None, ...] = ()
    returns: tuple[Fields | None, ...] = ()


def resolve_handler(model: ModelGraph, handler: Handler, handlers: Path | None = None):
    """The callable ``handler`` names in the handlers package of ``model``
    (``handlers``, else as the runtime finds it: SEAMS_HANDLERS, else
    ``handlers/`` beside the model). ``ResolutionError(implementation,
    comm:handler)`` when it cannot be imported."""
    from .handlers import HandlersPackage, handlers_dir

    package = HandlersPackage(handlers_dir(model.path, handlers))
    return package.resolve(URIRef(handler.implementation), handler.handler)


def _members(annotation: object) -> list[object]:
    """The members of a union annotation, else the annotation alone."""
    import types
    import typing

    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return list(typing.get_args(annotation))
    return [annotation]


def _typed_fields(cls: object) -> Fields:
    required = getattr(cls, "__required_keys__", frozenset())
    return tuple(sorted((key, key in required) for key in getattr(cls, "__annotations__", {})))


def _annotation_fault(annotation: object, expected: tuple[Fields | None, ...], what: str) -> str | None:
    """Why ``annotation`` does not fit the shapes ``expected`` (None: it does).
    A plain ``dict`` fits a shape; a TypedDict must have the shape's keys
    with the same required-ness; ``None`` fits only an operation with no
    shape on the returns side (``what`` "the return")."""
    import typing

    shapes = {tuple(sorted(f)) for f in expected if f is not None}
    for member in _members(annotation):
        if member is None or member is type(None):
            if what == "the return" and None in expected:
                continue
            return f"{what} annotation admits None, but every operation states a shape"
        if member is dict or typing.get_origin(member) is dict:
            if what == "the return" and not shapes:
                return f"{what} annotation is a dict, but no operation states a seam:returnsShape"
            continue
        if typing.is_typeddict(member):
            found = _typed_fields(member)
            if found in shapes:
                continue
            want = " or ".join(repr(s) for s in sorted(shapes)) or "no shape"
            name = getattr(member, "__name__", repr(member))
            return f"{what} annotation {name} has the keys (name, required) {found!r}; the model's shape has {want}"
        return f"{what} annotation {member!r} is neither dict nor a TypedDict of the shape"
    return None


def handler_types(model: ModelGraph, handler: Handler, handlers: Path | None = None) -> Check:
    """The handler's signature against the model: exactly one positional
    entity parameter, annotated ``dict`` or a TypedDict whose keys and
    required-ness are the accepted shape's fields, and a return annotation
    that is ``dict`` or such a TypedDict of the returned shape, or ``None``
    for an operation with no seam:returnsShape (as the stub generator
    writes them)."""
    import inspect
    import typing

    what = f"{handler.implementation} ({handler.handler})"
    try:
        target = resolve_handler(model, handler, handlers)
    except Exception as err:  # noqa: BLE001 - a handler that does not import fails the check, named
        return Check(False, f"{what}: {err}")
    params = list(inspect.signature(target).parameters.values())
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if len(params) != 1 or params[0].kind not in positional:
        return Check(False, f"{what}: takes {[p.name for p in params]}; the runtime passes one entity argument")
    try:
        hints = typing.get_type_hints(target)
    except Exception as err:  # noqa: BLE001 - an annotation that does not resolve fails the check
        return Check(False, f"{what}: its annotations do not resolve: {type(err).__name__}: {err}")
    entity = params[0].name
    if entity not in hints or "return" not in hints:
        return Check(
            False, f"{what}: annotate the entity parameter and the return (seam:acceptsShape, seam:returnsShape)"
        )
    for annotation, expected, side, predicate in (
        (hints[entity], handler.accepts, "the entity", "seam:acceptsShape"),
        (hints["return"], handler.returns, "the return", "seam:returnsShape"),
    ):
        fault = _annotation_fault(annotation, expected, side)
        if fault is not None:
            return Check(False, f"{what}: {fault} ({predicate})")
    return Check(True, f"{what}: its signature fits the model")


def _call(target, entity: dict) -> object:
    """Call a handler as the worker does: an async def is awaited."""
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(target):
        return asyncio.run(target(entity))
    result = target(entity)
    if inspect.isawaitable(result):

        async def _await() -> object:
            return await result

        return asyncio.run(_await())
    return result


def handler_result(
    model: ModelGraph, handler: Handler, operation: str, example: str, handlers: Path | None = None
) -> Check:
    """Call the handler with ``example`` (a verify:validExample of the
    operation's seam:acceptsShape), validated and stripped of its lifecycle
    status as the worker passes it, and check the answer as the worker
    does: a dict that the runtime's validator accepts for the
    seam:returnsShape (None when the operation states none), or an
    ``OperationError`` whose code is one of the operation's
    hydra:possibleStatus, with a problem body that conforms to the
    status's error shape."""
    from .contracts import problem_body, validate
    from .errors import OperationError, RuntimeModelError

    op = model.operations.by_iri(URIRef(operation))
    what = f"{handler.handler} on {example} ({operation})"
    accepts, returns = op.accepts, op.returns
    if accepts is None:
        return Check(False, f"{what}: {operation} states no seam:acceptsShape to take an example from")
    payload: dict[str, object] = {}
    for f, v in accepts.example_values(URIRef(example)):
        payload.setdefault(f.name, str(v))
    try:
        entity = dict(validate(model, accepts.iri, payload, operation=op.iri))
        target = resolve_handler(model, handler, handlers)
    except Exception as err:  # noqa: BLE001 - the example or the handler cannot be used: named
        return Check(False, f"{what}: {err}")
    if model.has_lifecycle(accepts.iri):
        entity.pop("status", None)
    try:
        result = _call(target, entity)
    except OperationError as err:
        codes = sorted(s.error_code for s in op.errors if s.error_code is not None)
        if err.code not in codes:
            return Check(False, f"{what}: raised OperationError({err.code!r}); hydra:possibleStatus declares {codes}")
        try:
            problem_body(model, op.iri, err.code, err.detail, err.extensions)
        except RuntimeModelError as fault:
            return Check(False, f"{what}: raised OperationError({err.code!r}), but {fault}")
        return Check(True, f"{what}: raised the declared error {err.code!r}")
    except Exception as err:  # noqa: BLE001 - any other fault fails the instance at run time
        return Check(False, f"{what}: raised {type(err).__name__}: {err}; only a declared OperationError may be raised")
    if returns is None:
        if result is not None:
            return Check(False, f"{what}: returned a {type(result).__name__}; {operation} states no seam:returnsShape")
        return Check(True, f"{what}: returned None")
    if not isinstance(result, dict):
        return Check(False, f"{what}: returned a {type(result).__name__}, expected a dict of {returns.iri}")
    try:
        validate(model, returns.iri, result, operation=op.iri)
    except RuntimeModelError as fault:
        return Check(False, f"{what}: the result does not conform to {returns.iri} (seam:returnsShape): {fault}")
    return Check(True, f"{what}: the result conforms to {returns.iri}")


def transition_guard(model: ModelGraph, task: str, transition: str) -> Check:
    """The lifecycle guard the worker runs before ``task`` (rule 1): with
    the entity in the transition's state:from the task may run and the
    entity moves to state:to; in any other state of the lifecycle the
    task is refused (``LifecycleViolation``), so it never runs."""
    from .errors import LifecycleViolation
    from .lifecycle import LifecycleGuard

    fired = model.task_element(URIRef(task)).fires
    if fired is None or str(fired.iri) != transition:
        found = None if fired is None else str(fired.iri)
        return Check(False, f"{task}: seam:fires {found}, but the tests expect {transition}; regenerate them")
    guard = LifecycleGuard(model)
    shape = model.lifecycle_shape(URIRef(transition))
    lifecycle = model.lifecycle_for(shape)
    source, target = lifecycle.states[fired.from_state.iri], lifecycle.states[fired.to_state.iri]
    try:
        moved = guard.apply(shape, source, URIRef(transition))
    except LifecycleViolation as err:
        return Check(False, f"{task}: {transition} is refused in its own state:from {source!r}: {err}")
    if moved != target:
        return Check(False, f"{task}: {transition} moves {source!r} to {moved!r}, not to its state:to {target!r}")
    for state in sorted(set(lifecycle.states.values()) - {source}):
        try:
            guard.check(shape, state, URIRef(transition))
        except LifecycleViolation:
            continue
        return Check(False, f"{task}: {transition} is enabled in {state!r}, not only in its state:from {source!r}")
    return Check(True, f"{task}: {transition} moves {source!r} to {target!r} and is refused in every other state")


def _expected_route(model: ModelGraph, task, example) -> tuple[bool, list[str]]:
    """(whether the example's expected outputs take a gateway flow into
    ``task``, the flows read). Each output becomes its dec:processVariable,
    and each conditioned flow from a gateway is evaluated by Spiff's
    ``PythonScriptEngine``, as the workflow evaluates it; a flow with no condition is taken."""
    from SpiffWorkflow.bpmn.script_engine import PythonScriptEngine

    script = PythonScriptEngine()
    element = model.task_element(task)
    process = element.process
    node = next(fn for fn in process.nodes() if fn.iri == element.iri)
    gateways = {fn.bpmn_id for fn in process.nodes() if fn.node.is_gateway}
    variables = {}
    names = {o.variable: o.process_variable for o in example.decision.outputs}
    for out in example.expected:
        variables[names.get(out.variable, out.variable)] = out.value.toPython()
    taken, flows = False, []
    for flow in node.incoming:
        if flow.source not in gateways:
            continue
        flows.append(str(process.element_iri(flow.id)))
        if not flow.condition or script.environment.evaluate(flow.condition, dict(variables)):
            taken = True
    return taken, flows


def decision_route(model: ModelGraph, task: str, example: str, db: Path, handlers: Path | None = None) -> Check:
    """Run the task's process in-process with the hand-written handlers:
    started with the first verify:validExample of the triggering
    operation's seam:acceptsShape, its fields set from the decision
    example's givens. The task must be reached exactly when the example's
    expected outputs take a gateway flow into it; when reached, its trace
    row must fire the task's seam:fires transition (none when it fires
    none), unless a boundary caught a declared error. A failed instance
    fails the check with its error."""
    import asyncio

    from .runtime import Runtime
    from .store import SQLiteStore

    found = [e for e in model.decision_examples if str(e.iri) == example]
    if not found:
        return Check(False, f"{example}: no such verify:DecisionExample; regenerate the tests")
    ex = found[0]
    element = model.task_element(URIRef(task))
    process = element.process
    what = f"{task} on {example} ({ex.decision.iri})"
    try:
        op = model.triggering_operation(process.iri)
        accepts = model.shape(model.accepted_shape(op))
    except Exception as err:  # noqa: BLE001 - a process with no form starting it: named
        return Check(False, f"{what}: {err}")
    payload: dict[str, object] = {}
    if accepts.valid_examples:
        for f, v in accepts.example_values(accepts.valid_examples[0]):
            payload.setdefault(f.name, str(v))
    for given in ex.givens:
        payload[local_name(given.field)] = str(given.value)
    expected, flows = _expected_route(model, URIRef(task), ex)

    async def _run() -> tuple[str, object, list[dict]]:
        runtime = Runtime(model, SQLiteStore(Path(db)), handlers=handlers_dir_for(model, handlers))
        instance = await runtime.start_process(process.iri, payload, local_name(example))
        result = await instance.wait()
        return result["status"], result.get("error"), list(instance.state["trace"])

    try:
        status, error, trace = asyncio.run(_run())
    except Exception as err:  # noqa: BLE001 - a start that is refused: named
        return Check(False, f"{what}: the process did not start: {type(err).__name__}: {err}")
    if status == FAILED:
        return Check(False, f"{what}: the instance failed: {error}")
    rows = [r for r in trace if r["iri"] == task]
    reached = bool(rows)
    if reached != expected:
        verb = "reached" if reached else "not reached"
        return Check(
            False,
            f"{what}: the task was {verb}, but the expected outputs {'take' if expected else 'do not take'} {flows}",
        )
    if not reached:
        return Check(True, f"{what}: not reached, as {flows} expect")
    row = rows[0]
    if "boundary" in row:
        return Check(True, f"{what}: reached; a boundary caught {row['error']['code']!r}")
    fired = element.fires
    want = None if fired is None else str(fired.iri)
    if row.get("fires") != want:
        return Check(False, f"{what}: reached and fired {row.get('fires')}, but seam:fires is {want}")
    return Check(True, f"{what}: reached through {flows}, firing {want}")


def handlers_dir_for(model: ModelGraph, handlers: Path | None = None) -> Path:
    """The handlers package directory the runtime would use for ``model``."""
    from .handlers import handlers_dir

    return handlers_dir(model.path, handlers)


__all__ = [
    "DEFAULT_TIMEOUT",
    "E2E_ENV",
    "FAILED",
    "Fields",
    "SMOKE_BASE_URL_ENV",
    "SMOKE_GROUPS_ENV",
    "SMOKE_USER_ENV",
    "Attempt",
    "Caller",
    "Check",
    "Engine",
    "Handler",
    "ModelHashMismatch",
    "Probe",
    "Request",
    "Run",
    "Scenario",
    "ScenarioError",
    "Step",
    "Target",
    "attempt",
    "decide",
    "decision_route",
    "handler_result",
    "handler_types",
    "handlers_dir_for",
    "identity",
    "load_model",
    "resolve_handler",
    "response_conforms",
    "run_scenario",
    "serve",
    "shape_conforms",
    "smoke",
    "smoke_caller",
    "smoke_required",
    "smoke_skip",
    "transition_guard",
    "value",
]
