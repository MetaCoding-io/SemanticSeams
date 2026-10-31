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
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
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


def run_scenario(client, runtime, scenario: Scenario, timeout: float = DEFAULT_TIMEOUT) -> Run:
    """Drive ``scenario`` through the app ``serve`` built and return its ``Run``."""
    _send(client, scenario, scenario.start, "start")
    row = _settle(runtime, scenario, "the start", timeout)
    for number, step in enumerate(scenario.steps, 1):
        what = f"step {number} ({step.task})"
        open_tasks = sorted(r["task"] for r in runtime.store.list_user_tasks() if r["correlation_key"] == scenario.key)
        if step.task not in open_tasks:
            raise ScenarioError(
                f"{scenario.iri}: {what} is not open; the instance is {row['status']!r} with open tasks {open_tasks}"
            )
        _send(client, scenario, step.request, what)
        row = _settle(runtime, scenario, what, timeout)
    state = None
    if scenario.entity_shape is not None:
        entities = runtime.store.query(URIRef(scenario.entity_shape), correlation_key=scenario.key)
        state = entities[-1].get("status") if entities else None
    workflow = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"]))
    reached = tuple(r["iri"] for r in workflow.data["seams"]["trace"])
    return Run(row["status"], row.get("error"), state, reached)


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


def shape_conforms(model: ModelGraph, shape: str, node: str) -> tuple[bool, str]:
    """(conforms, pyshacl's report text) of example ``node`` against ``shape`` alone."""
    from pyshacl import validate

    shapes, data = Graph(), Graph()
    _describe(model.ds, URIRef(shape), shapes)
    shapes.add((URIRef(shape), SH.targetNode, URIRef(node)))
    _describe(model.ds, URIRef(node), data)
    conforms, _, text = validate(data, shacl_graph=shapes)
    return bool(conforms), str(text)


__all__ = [
    "DEFAULT_TIMEOUT",
    "FAILED",
    "Engine",
    "ModelHashMismatch",
    "Request",
    "Run",
    "Scenario",
    "ScenarioError",
    "Step",
    "decide",
    "identity",
    "load_model",
    "run_scenario",
    "serve",
    "shape_conforms",
    "value",
]
