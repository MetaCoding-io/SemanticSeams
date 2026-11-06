"""``Runtime``: the facade generated route modules import (ADR-0007, D013).

    runtime = Runtime.load("/model/chat-app.trig", model_hash=MODEL_HASH)

``SEAMS_MODEL``, when set and non-empty, takes precedence over ``trig_path``:
the generated module names the path it was generated against, and the
deployment (compose sets ``SEAMS_MODEL``) chooses the model actually mounted.
A missing model file raises ``FileNotFoundError`` naming the path (and
``SEAMS_MODEL`` when that chose it).

``load`` refuses a model whose hash differs from the one the code was
generated from (ADR-0007 rule 2) unless ``allow_hash_mismatch=True`` or
``SEAMS_ALLOW_HASH_MISMATCH=1``. It then opens the store the model declares
(ADR-0011, ``ModelGraph.store_plan``): embedded SQLite at ``db_path``,
``SEAMS_DB`` or ``./seams.sqlite`` when the model declares no store or a
deploy:SQLite one; PostgreSQL at the URL in the environment variable the
connecting binding's deploy:key names, else in the file ``<key>_FILE`` names.
``store=`` injects a backend (tests), and ``SEAMS_STORE_OVERRIDE=sqlite``
forces embedded SQLite; both still resolve the plan first, so a bad model
fails at load either way. A plan with a deploy:SemPKM store (ADR-0025) keeps
the entities of the shapes stored there in SemPKM, at the base URL in the
environment variable its connecting binding's deploy:key names, with the
service token its deploy:authenticatesTo binding's key names (each also
from ``<key>_FILE``): the relational store, declared or injected, is wrapped
in a ``SplitStore`` (``sempkm_transport=`` gives the SemPKM client an httpx
transport). ``SEAMS_STORE_OVERRIDE=sqlite`` keeps those entities in SQLite too. The other methods are what a thin handler
calls: ``policy`` (a FastAPI dependency for seam:governedBy), ``validate``
(SHACL at the boundary), ``start_process`` / ``resume`` (run the generic
worker as an asyncio task), ``write`` (persist a validated entity when the
operation triggers no process, D026), ``query`` (persisted entities of a shape) and
``subscribe`` (SSE frames of a channel scope) and ``render_fragment`` (an
htmx partial from ``templates_dir``, ``SEAMS_TEMPLATES`` or ``./templates``)
and ``render_page`` (the landmark page, every block bound as its partial is).

Channel-started processes (ADR-0010): when a message throw event publishes on
a channel, ``start_subscribed`` starts every process whose start event
seam:subscribesTo it, with the publisher's correlation key, entities and
statuses.

SemPKM webhooks (ADR-0027): every channel whose comm:transport is
comm:SemPKMWebhook is resolved when the runtime is built
(``ModelGraph.webhook_channels``, ``ResolutionError`` on a fault), and
``receive_webhook`` handles one SemPKM delivery on it
(``seams_runtime.webhooks``): it reads the event back with the service token,
reads the changed objects of the accepted shape's class and starts each
subscribed process once per (process, event, object), the object's IRI as
correlation key. The worker's entity writes run in a thread, so a SemPKM
write does not stop the loop from answering its own delivery.

Human tasks (ADR-0009): ``user_tasks`` lists the open BPMN user tasks an
identity may complete, ``complete_task`` checks the task's policies,
validates the payload against its output shape and completes it on the
waiting instance (then the worker continues), and ``task_policy`` is the
FastAPI dependency for a completion route.

Implementations (ADR-0012): every operation a service task seam:invokes is
resolved when the runtime is built, before any request is served
(``resolve_implementations``): its seam:implementedBy kind must agree with
where it is served, and a comm:PythonHandler is imported from the handlers
package (``handlers=``, ``SEAMS_HANDLERS`` or ``handlers/`` beside the model).
A fault raises ``ResolutionError`` naming the operation or implementation.
``http_transport=`` / ``http_base_url=`` configure the comm:HTTPEndpoint
client as ``llm_transport=`` / ``llm_base_url=`` do the LLM one.

Error boundaries (ADR-0013): every lifted proc:ErrorBoundaryEvent is joined
to its BPMN boundary, the task it is attached to and the error it catches
when the runtime is built (``resolve_boundaries``, through
``Process.error_boundaries``); a graph that disagrees with the XML raises
``ResolutionError`` naming the boundary. The worker routes a declared error
its task's operation raises down the boundary that catches it.

Aggregates (ADR-0035): ``load`` refuses, before any store is opened, an
aggregate whose seam:aggregateMember shapes the store cannot commit
atomically: more than one member with one stored in a deploy:SemPKM store, or
members stored in two stores (``resolve_aggregates``, ``ResolutionError``
naming the aggregate and seam:aggregateMember). ``write_aggregate`` validates
one payload per member shape and writes them all in one
``store.transaction()``, or nothing (``AggregateRolledBack``).

Data health (ADR-0036): ``data_health`` resolves the attached profile
(``seams.resolve_profile``) and runs its instance-data rules, the sh:Warning
shapes with a sh:sparql constraint, on the stored entities lifted to RDF
through the shape contracts (``seams_runtime.invariants``). It returns the
findings sorted, logs ``data health <profile> N warning(s)`` and emits a
``seams.data_health`` span. No write calls it: a broken rule never refuses a
write.

Tracing (D049): ``telemetry=`` injects a ``Telemetry`` (tests); otherwise
``tracer_from_env()`` builds one, a no-op unless ``OTEL_EXPORTER_OTLP_ENDPOINT``
is set and the otel extra is installed (``seams_runtime.telemetry``).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import uuid
from pathlib import Path

from fastapi.responses import HTMLResponse, JSONResponse
from seams import model_dir, resolve_profile

from .channels import ChannelBus, Subscription
from .contracts import _items, problem_body, shape_contract
from .contracts import validate as _validate
from .engine import Engine
from .errors import ModelHashMismatch, OperationError, PolicyDenied, ResolutionError, RuntimeModelError, TaskNotOpen
from .fragments import FragmentRenderer, flatten
from .handlers import EndpointClient, HandlersPackage, handlers_dir
from .invariants import Finding
from .invariants import data_health as _data_health
from .lifecycle import LifecycleGuard
from .llm import LLMClient
from .model import COMM, DEPLOY, SEAM, ModelGraph, local_name
from .policy import Identity, PolicyHook, authenticator_from_env
from .sempkm import SemPKMStore
from .store import PostgresStore, SplitStore, SQLiteStore, Store
from .telemetry import Telemetry, tracer_from_env
from .webhooks import WebhookReceiver
from .worker import RUNNING, Instance, Worker, commit_aggregate, new_state

log = logging.getLogger(__name__)

MODEL_ENV = "SEAMS_MODEL"
DB_ENV = "SEAMS_DB"
ALLOW_MISMATCH_ENV = "SEAMS_ALLOW_HASH_MISMATCH"
DEFAULT_DB = "seams.sqlite"
STORE_OVERRIDE_ENV = "SEAMS_STORE_OVERRIDE"
STORE_KINDS = {DEPLOY.SQLite: "sqlite", DEPLOY.PostgreSQL: "postgresql", DEPLOY.SemPKM: "sempkm"}  # kind -> Store.kind
TEMPLATES_ENV = "SEAMS_TEMPLATES"
DEFAULT_TEMPLATES = "templates"
PROBLEM_JSON = "application/problem+json"  # RFC 9457


def _db(db_path) -> Path:
    """The embedded SQLite file: ``db_path``, else ``SEAMS_DB``, else ``./seams.sqlite``."""
    return Path(db_path if db_path is not None else os.environ.get(DB_ENV) or DEFAULT_DB)


def _binding_value(key: str, what: str, container, predicate, store) -> str:
    """The value of the binding with deploy:key ``key``: the environment
    variable ``key`` names, else the file ``<key>_FILE`` names (stripped),
    else ResolutionError(container, predicate). The value is never logged."""
    value = os.environ.get(key)
    if value:
        log.info("store %s from %s", what, key)
        return value
    path = os.environ.get(f"{key}_FILE")
    if path:
        log.info("store %s from the file %s_FILE names (%s)", what, key, path)
        return Path(path).read_text(encoding="utf-8").strip()
    raise ResolutionError(
        container,
        predicate,
        f"store {store} needs its {what} in {key} or a file named by {key}_FILE; neither is set",
    )


def _connection_url(plan) -> str:
    """The PostgreSQL URL for ``plan`` (``_binding_value`` of its deploy:key)."""
    return _binding_value(plan.key, "connection string", plan.container, DEPLOY.connectsTo, plan.store)


def _sempkm_store(model: ModelGraph, plan, transport=None) -> SemPKMStore:
    """The SemPKM entity store of a ``SemPKMPlan``: its base URL from the
    connecting binding, its token from the deploy:authenticatesTo binding."""
    url = _binding_value(plan.key, "base URL", plan.container, DEPLOY.connectsTo, plan.store)
    token = _binding_value(plan.token_key, "service token", plan.container, DEPLOY.authenticatesTo, plan.store)
    return SemPKMStore(model, plan, url, token, transport=transport)


def _check_where(model: ModelGraph, process, op, impl, container) -> None:
    """ADR-0012's where-rule: the kind must agree with where ``op`` is served
    for ``process`` (GAP-27)."""
    if impl is None:
        if not container.in_process:
            raise ResolutionError(
                op,
                SEAM.implementedBy,
                f"invoked by {process} across containers ({container.iri} serves it) and declares no implementation",
            )
        return
    kind = local_name(impl.kind)
    if impl.kind == COMM.PythonHandler:
        if not container.in_process:
            raise ResolutionError(
                op,
                SEAM.exposes,
                f"{impl.iri} is a comm:{kind}, which runs in the runtime, "
                f"but {container.iri} does not seam:executes {process}",
            )
        return
    if container.in_process:
        raise ResolutionError(
            op,
            SEAM.exposes,
            f"{impl.iri} is a comm:{kind}, which reaches another container, "
            f"but {container.iri} also seam:executes {process}",
        )
    executor = model.executing_container(process)
    try:
        model.service_binding_key(executor.iri, container.iri)
    except ResolutionError as exc:
        raise ResolutionError(
            op,
            SEAM.exposes,
            f"{impl.iri} is a comm:{kind}, but {executor.iri} has no deploy:binding "
            f"with deploy:serviceOf {container.iri}",
        ) from exc


def resolve_implementations(model: ModelGraph, handlers=None) -> dict:
    """``{operation IRI: (Implementation | None, callable | None)}`` for every
    operation a process seam:invokes (ADR-0012). The kind is checked against
    where the operation is served, and each comm:PythonHandler is imported
    from the handlers package now, not on first use. ``None`` as the
    implementation means the runtime itself serves the in-process operation.
    Any fault raises ``ResolutionError``."""
    resolved: dict = {}
    package = None
    for process in sorted(model.processes, key=lambda p: str(p.iri)):
        for op in process.invoked_operations:
            impl = model.operation_implementation(op.iri)
            _check_where(model, process.iri, op.iri, impl, model.implementing_container(op.iri, process.iri))
            if op.iri in resolved:
                continue
            target = None
            if impl is not None and impl.kind == COMM.PythonHandler:
                if package is None:
                    package = HandlersPackage(handlers_dir(model.path, handlers))
                target = package.resolve(impl.iri, impl.handler)
            resolved[op.iri] = (impl, target)
            log.info(
                "operation %s implemented by %s%s",
                op.iri,
                "the runtime" if impl is None else f"{impl.iri} ({local_name(impl.kind)})",
                "" if impl is None or impl.handler is None else f", handler {impl.handler}",
            )
    return resolved


def resolve_boundaries(model: ModelGraph) -> dict:
    """``{(task IRI, errorCode): seams.ErrorBoundary}`` for every lifted error
    boundary of every process (ADR-0013). Any disagreement between the graph
    and the BPMN XML raises ``ResolutionError`` naming the boundary."""
    resolved: dict = {}
    for process in sorted(model.processes, key=lambda p: str(p.iri)):
        for boundary in process.error_boundaries():
            resolved[(boundary.task.iri, boundary.code)] = boundary
            log.info(
                "error boundary %s on %s catches %s (%s of %s)",
                boundary.iri,
                boundary.task.iri,
                boundary.code,
                boundary.status.iri,
                boundary.operation.iri,
            )
    return resolved


def resolve_aggregates(model: ModelGraph) -> None:
    """ADR-0035 section 5: every aggregate's members can commit in one store
    transaction. More than one member with one seam:storedIn a deploy:SemPKM
    store, or members stored in more than one store, raises
    ``ResolutionError(aggregate, seam:aggregateMember)``; so does a member
    listed by two aggregates (``Shape.aggregate``)."""
    for aggregate in model.aggregates:
        members = aggregate.members
        names = [str(m) for m in members.iris()]
        for member in members:
            member.aggregate  # noqa: B018 - raises for a shape listed by two aggregates
            if len(members) < 2:
                continue
            for store in member.stored_in:
                if DEPLOY.SemPKM in store.store_kinds:
                    raise ResolutionError(
                        aggregate.iri,
                        SEAM.aggregateMember,
                        f"{member.iri} is stored in the deploy:SemPKM store {store.iri}, which cannot commit "
                        f"more than one entity of an aggregate atomically (ADR-0035); its members are {names}",
                    )
        stores = sorted({str(store.iri) for member in members for store in member.stored_in})
        if len(stores) > 1:
            raise ResolutionError(
                aggregate.iri,
                SEAM.aggregateMember,
                f"its members are stored in more than one store, {stores}; "
                "an aggregate commits in one store transaction (ADR-0035)",
            )
        log.info("aggregate %s commits %s in one transaction", aggregate.iri, ", ".join(names))


class Runtime:
    def __init__(
        self,
        model: ModelGraph,
        store: Store,
        *,
        authenticator=None,
        evaluator=None,
        llm: LLMClient | None = None,
        bus: ChannelBus | None = None,
        templates_dir=None,
        store_plan=None,
        store_override: bool = False,
        telemetry: Telemetry | None = None,
        handlers=None,
        http: EndpointClient | None = None,
        implementations: dict | None = None,
        boundaries: dict | None = None,
        webhooks: list | None = None,
    ):
        self.model = model
        self.store = store
        self.store_plan = store_plan  # the seams StorePlan Runtime.load resolved, else None
        self.store_override = store_override  # True when the store is not the one the model declares
        self.engine = Engine(model)
        self.bus = bus if bus is not None else ChannelBus()
        self.guard = LifecycleGuard(model)
        self.hook = PolicyHook(
            model, authenticator if authenticator is not None else authenticator_from_env(), evaluator
        )
        self.llm = llm if llm is not None else LLMClient()
        self.http = http if http is not None else EndpointClient()
        # ADR-0012: resolved before any request is served; ResolutionError on a model fault
        self.implementations = (
            implementations if implementations is not None else resolve_implementations(model, handlers)
        )
        # ADR-0013: lifted error boundaries, checked against the BPMN XML
        self.boundaries = boundaries if boundaries is not None else resolve_boundaries(model)
        # OpenTelemetry spans (D049): off unless OTEL_EXPORTER_OTLP_ENDPOINT is set
        self.telemetry = telemetry if telemetry is not None else tracer_from_env()
        self.worker = Worker(
            model,
            self.engine,
            store,
            self.bus,
            self.guard,
            self.llm,
            self.telemetry,
            implementations=self.implementations,
            http=self.http,
            boundaries=self.boundaries,
        )
        self.worker.on_published = self._on_published
        self.instances: dict[str, Instance] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        self.templates_dir = Path(
            templates_dir if templates_dir is not None else os.environ.get(TEMPLATES_ENV) or DEFAULT_TEMPLATES
        )
        self.fragments = FragmentRenderer(model, self.templates_dir)
        # ADR-0027: SemPKM webhook channels, resolved before any request is served
        self.webhooks = WebhookReceiver(self, webhooks)

    @classmethod
    def load(
        cls,
        trig_path,
        model_hash: str | None = None,
        *,
        allow_hash_mismatch: bool = False,
        db_path=None,
        authenticator=None,
        evaluator=None,
        llm_transport=None,
        llm_base_url: str | None = None,
        templates_dir=None,
        store: Store | None = None,
        telemetry: Telemetry | None = None,
        handlers=None,
        http_transport=None,
        http_base_url: str | None = None,
        sempkm_transport=None,
    ) -> Runtime:
        override = os.environ.get(MODEL_ENV)
        if override:
            log.info("model path %s from %s (overrides argument %s)", override, MODEL_ENV, trig_path)
            trig_path = override
        else:
            log.info("model path %s from argument (%s unset)", trig_path, MODEL_ENV)
        if not Path(trig_path).exists():
            source = f" (from {MODEL_ENV})" if override else ""
            raise FileNotFoundError(f"model file {trig_path} not found{source}")
        model = ModelGraph(trig_path)
        if model_hash is not None and model_hash != model.hash:
            if allow_hash_mismatch or os.environ.get(ALLOW_MISMATCH_ENV) == "1":
                log.warning(
                    "model hash mismatch allowed for %s: expected %s, got %s", model.path, model_hash, model.hash
                )
            else:
                raise ModelHashMismatch(model_hash, model.hash, model.path)
        plan = model.store_plan()  # ResolutionError on a bad model, whatever store is used
        # ADR-0012: implementations resolve before a store is opened, so a model fault opens nothing
        implementations = resolve_implementations(model, handlers)
        boundaries = resolve_boundaries(model)  # ADR-0013, also before the store
        webhooks = model.webhook_channels()  # ADR-0027, also before the store
        resolve_aggregates(model)  # ADR-0035, also before the store, whatever store is used
        declared = STORE_KINDS[plan.kind]
        override = False
        forced = bool(os.environ.get(STORE_OVERRIDE_ENV)) and store is None
        # ADR-0025: the SemPKM base URL and token resolve before any store is opened
        sempkm = None if plan.sempkm is None or forced else _sempkm_store(model, plan.sempkm, sempkm_transport)
        if store is not None:
            override = store.kind != declared
            if override:
                log.warning(
                    "injected %s store %s replaces the declared %s store %s",
                    store.kind,
                    store.location,
                    declared,
                    plan.store,
                )
        elif mode := os.environ.get(STORE_OVERRIDE_ENV):
            if mode != "sqlite":
                raise ValueError(f"{STORE_OVERRIDE_ENV}={mode!r}: the only supported override is 'sqlite'")
            store = SQLiteStore(_db(db_path))
            override = True
            log.warning(
                "%s=sqlite: embedded SQLite at %s replaces the declared %s store %s",
                STORE_OVERRIDE_ENV,
                store.location,
                declared,
                plan.store or "(none declared)",
            )
            if plan.sempkm is not None:
                log.warning(
                    "%s=sqlite: the entities of the SemPKM store %s stay in embedded SQLite too",
                    STORE_OVERRIDE_ENV,
                    plan.sempkm.store,
                )
        elif plan.kind == DEPLOY.PostgreSQL:
            store = PostgresStore(_connection_url(plan))
        else:
            store = SQLiteStore(_db(db_path))
        if sempkm is not None:
            store = SplitStore(store, sempkm)
            log.info(
                "entities of %s in the SemPKM store %s at %s (url %s, token %s)",
                ", ".join(str(s) for s in sempkm.shapes),
                sempkm.store,
                sempkm.location,
                plan.sempkm.key,
                plan.sempkm.token_key,
            )
        runtime = cls(
            model,
            store,
            authenticator=authenticator,
            evaluator=evaluator,
            llm=LLMClient(llm_base_url, transport=llm_transport),
            templates_dir=templates_dir,
            store_plan=plan,
            store_override=override,
            telemetry=telemetry,
            http=EndpointClient(http_base_url, transport=http_transport),
            implementations=implementations,
            boundaries=boundaries,
            webhooks=webhooks,
        )
        log.info(
            "runtime loaded %s (%s), store kind %s (declared %s: store %s, container %s, key %s) at %s, templates %s",
            model.path,
            model.hash,
            store.kind,
            local_name(plan.kind) if plan.declared else "nothing",
            plan.store,
            plan.container,
            plan.key,
            store.location,
            runtime.templates_dir,
        )
        return runtime

    # ── boundary ──

    def policy(self, policy_curie, operation=None):
        """FastAPI dependency enforcing a seam:governedBy policy (401/403)."""
        return self.hook.dependency(policy_curie, operation)

    def validate(self, shape_curie, payload) -> dict:
        """The normalised payload, or ContractViolation (422)."""
        return _validate(self.model, shape_curie, payload)

    def write(self, shape_curie, payload) -> dict:
        """Validate ``payload`` against the shape and persist it as a new
        entity, for an operation that triggers no process (D026). A shape
        with seam:lifecycle starts in its initial status unless the payload
        names one, as ``start_process`` does. A shape with an ``:id`` path
        (the identifier convention) gets the new entity's id there before
        validation, replacing any the payload sent: a form never enters it.
        Returns the stored row (the form ``query`` returns), or raises
        ContractViolation (422) and stores nothing."""
        shape = self.model.curie(shape_curie)
        entity_id, data, status = self._prepare(shape, payload)
        entity = self.store.put_entity(entity_id, shape, data, status=status)
        log.info("wrote %s entity %s (status %s)", shape, entity["id"], status)
        return entity

    def _prepare(self, shape, payload) -> tuple[str, dict, str | None]:
        """``write``'s rules before the store: a new id (in the ``:id`` field
        when the shape has one), the validated data and its initial status."""
        entity_id = str(uuid.uuid4())
        if "id" in shape_contract(self.model, shape).fields:
            payload = {**dict(_items(payload)), "id": entity_id}
        data = dict(_validate(self.model, shape, payload))
        status = None
        if self.model.has_lifecycle(shape):
            status = data.get("status") or self.model.lifecycle_for(shape).initial
            data["status"] = status
        return entity_id, data, status

    def write_aggregate(self, aggregate_curie, payloads) -> dict:
        """Persist one new entity per member shape of an aggregate, all or
        none (ADR-0035). ``payloads`` maps member shapes (CURIE or IRI) to
        payloads, each written by ``write``'s rules. Every payload is
        validated before anything is written; then the entities are written
        in member-IRI order in one ``store.transaction()``. Returns the stored
        rows keyed by shape IRI. Raises ``ResolutionError(shape or aggregate,
        seam:aggregateMember)`` for a shape that is not a member, no payloads
        or an aggregate that names no members; ``ContractViolation`` (422)
        storing nothing; or ``AggregateRolledBack`` when a write fails and
        the transaction rolled them all back."""
        aggregate = self.model.curie(aggregate_curie)
        found = [a for a in self.model.aggregates if a.iri == aggregate]
        if not found:
            raise ResolutionError(
                aggregate, SEAM.aggregateMember, "names no member shapes, so it declares no transaction boundary"
            )
        members = found[0].members.iris()
        if not payloads:
            raise ResolutionError(aggregate, SEAM.aggregateMember, "no member payloads to write")
        shapes = {self.model.curie(s): p for s, p in dict(payloads).items()}
        for shape in sorted(shapes, key=str):
            if shape not in members:
                raise ResolutionError(
                    shape,
                    SEAM.aggregateMember,
                    f"not a member of {aggregate}; its members are {[str(m) for m in members]}",
                )
        prepared = {
            shape: self._prepare(shape, payload) for shape, payload in sorted(shapes.items(), key=lambda i: str(i[0]))
        }

        def put(shape) -> dict:
            entity_id, data, status = prepared[shape]
            return self.store.put_entity(entity_id, shape, data, status=status)

        rows = commit_aggregate(self.store, self.telemetry, aggregate, list(prepared), put)
        return {str(shape): row for shape, row in zip(sorted(prepared, key=str), rows, strict=True)}

    def problem(self, operation_curie, error: OperationError) -> JSONResponse:
        """The problem+json response for ``error`` raised while serving
        ``operation_curie`` (ADR-0013): the declared status's hydra:statusCode
        and the body ``problem_body`` built and validated against its error
        shape. A generated route module's problem handler calls this. A code
        the operation does not declare (or no operation, None) and a body
        that violates the error shape are server faults: 500 with
        ``{"detail": error.to_dict()}``, the error naming the operation or the
        status."""
        try:
            if operation_curie is None:
                raise ResolutionError(
                    "(route)", "hydra:possibleStatus", f"{error.code!r} raised by a route that declares no errors"
                )
            status, body = problem_body(self.model, operation_curie, error.code, error.detail, error.extensions)
        except RuntimeModelError as fault:
            log.error("%s raised %s: no valid problem+json (%s)", operation_curie, error.code, fault)
            return JSONResponse(status_code=500, content={"detail": fault.to_dict()})
        log.info("%s raised %s -> %s %s", operation_curie, error.code, status, PROBLEM_JSON)
        return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)

    # ── processes ──

    async def start_process(self, process_curie, payload, correlation_key: str, *, stop_after=None) -> Instance:
        """Validate ``payload`` against the acceptsShape of the operation the
        process's triggering event seam:submitsTo, checkpoint a new instance
        and run the worker as an asyncio task. Returns at once; ``await
        instance.wait()`` for the result. ``stop_after`` (a bpmn id or element
        IRI) stops the worker after that element, leaving it resumable."""
        process = self.model.curie(process_curie)
        op = self.model.triggering_operation(process)
        shape = self.model.accepted_shape(op)
        message = _validate(self.model, shape, payload, operation=op)
        if not correlation_key:
            raise ResolutionError(process, "proc:correlationKey", "empty correlation key")

        wf = self.engine.new_workflow(process)
        state = new_state(process, correlation_key)
        state["current"][str(shape)] = {"id": None, "data": dict(message)}
        if self.model.has_lifecycle(shape):
            status = message.get("status") or self.model.lifecycle_for(shape).initial
            state["status"][str(shape)] = status
            state["history"][str(shape)] = [status]
        wf.data["seams"] = state
        instance = Instance(str(uuid.uuid4()), correlation_key, process, wf, stop_after)
        self.worker._checkpoint(instance, RUNNING)
        log.info("started %s instance %s (correlation %s)", process, instance.id, correlation_key)
        return self._launch(instance)

    def fail_operation(self, correlation_key: str, operation_curie, code: str) -> None:
        """Make ``operation_curie`` fail with the declared error ``code`` for
        every instance with ``correlation_key`` (worker rule 3b): what a
        scenario's verify:failure asks for (ADR-0014). ``ResolutionError``
        unless ``code`` is the comm:errorCode of one of the operation's errors."""
        op = self.model.curie(operation_curie)
        self.model.operations.by_iri(op).error(code)  # ResolutionError(op, comm:errorCode)
        self.worker.fail(correlation_key, op, code)

    async def start_subscribed(
        self, process_curie, correlation_key: str, current: dict, status: dict, *, stop_after=None
    ) -> Instance:
        """Start a channel-started process (ADR-0010) as the worker does when a
        message throw event publishes on the channel its start event
        seam:subscribesTo: the same correlation key, and a copy of the
        publisher's ``current`` entities (ids kept) and ``status`` map. No
        operation accepts the payload, so nothing is re-validated. The new
        instance is checkpointed before its worker task runs."""
        return self._start_subscribed(self.model.curie(process_curie), correlation_key, current, status, stop_after)

    async def receive_webhook(self, channel_curie, body) -> JSONResponse:
        """Handle one SemPKM webhook delivery (the raw request ``body``) on the
        comm:SemPKMWebhook channel ``channel_curie`` (ADR-0027): 202 with the
        ``started`` and ``skipped`` objects, or problem+json naming the
        channel (400, 422, 502, 503). A generated route only calls this."""
        return await self.webhooks.receive(channel_curie, body)

    def _start_subscribed(self, process, correlation_key, current, status, stop_after=None, origin=None) -> Instance:
        start = self.model.start_channel(process)
        if not correlation_key:
            raise ResolutionError(process, "proc:correlationKey", "empty correlation key")
        wf = self.engine.new_workflow(process)
        self.engine.deliver_start(wf, start.event)
        state = new_state(process, correlation_key)
        state["current"] = copy.deepcopy(dict(current))
        state["status"] = dict(status)
        state["history"] = {shape: [value] for shape, value in status.items()}
        if origin is not None:
            state["start"] = dict(origin)  # ADR-0027: the {channel, event, object} that started it
        wf.data["seams"] = state
        instance = Instance(str(uuid.uuid4()), correlation_key, process, wf, stop_after)
        self.worker._checkpoint(instance, RUNNING)
        log.info(
            "started %s instance %s from %s on %s (correlation %s)",
            process,
            instance.id,
            start.event,
            start.channel,
            correlation_key,
        )
        return self._launch(instance)

    def _on_published(self, publisher: Instance, channel) -> list[dict]:
        """Worker rule 6a: start every process subscribed to ``channel``. A
        subscriber that cannot start is logged and recorded with its error;
        it never fails the publisher."""
        started = []
        try:
            processes = self.model.subscribed_processes(channel)
        except Exception as exc:  # noqa: BLE001 - a broken subscription never fails the publisher
            log.exception("instance %s: resolving subscribers of %s failed", publisher.id, channel)
            return [{"process": None, "instance": None, "error": {"type": type(exc).__name__, "message": str(exc)}}]
        for process in processes:
            try:
                inst = self._start_subscribed(
                    process, publisher.correlation_key, publisher.state["current"], publisher.state["status"]
                )
                started.append({"process": str(process), "instance": inst.id})
            except Exception as exc:  # noqa: BLE001 - the publisher's element already completed
                log.exception("instance %s: starting subscriber %s on %s failed", publisher.id, process, channel)
                started.append(
                    {
                        "process": str(process),
                        "instance": None,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                )
        return started

    async def resume(self, instance_id: str, *, stop_after=None) -> Instance:
        """Continue a checkpointed instance (e.g. after a restart) in this runtime."""
        meta = self.store.get_instance(instance_id)
        if meta is None:
            raise LookupError(f"no instance {instance_id} in {self.store.location}")
        wf = self.engine.deserialize(self.store.load_state(instance_id))
        instance = Instance(instance_id, meta["correlation_key"], self.model.curie(meta["process"]), wf, stop_after)
        log.info("resuming instance %s (was %s)", instance_id, meta["status"])
        return self._launch(instance)

    def _launch(self, instance: Instance) -> Instance:
        instance.task = asyncio.get_running_loop().create_task(
            self.worker.run(instance), name=f"seams-instance-{instance.id}"
        )
        self.instances[instance.id] = instance
        return instance

    # ── human tasks (ADR-0009) ──

    def task_policy(self, task_curie):
        """FastAPI dependency for a completion route: 401 without an identity,
        403 unless every seam:governedBy policy of the task permits it."""
        return self.hook.task_dependency(task_curie)

    def user_tasks(self, identity: Identity | None, process=None) -> list[dict]:
        """Open user tasks ``identity`` may complete, oldest first. Each is a
        dict: instance, task (IRI), bpmn_id, label, process, correlation_key,
        form (IRI), partial (the form's htmx partial name), screen (the
        ifml:path of the page holding the form, or None) and entity (the
        newest stored entity of the task's seam:reads shape for that key,
        flattened, or None). No identity raises PolicyDenied (401)."""
        if identity is None:
            raise PolicyDenied("seam:governedBy", None, 401, f"no authenticated identity ({self.hook.authenticator!r})")
        wanted = None if process is None else str(self.model.curie(process))
        out = []
        for row in self.store.list_user_tasks():
            if wanted is not None and row["process"] != wanted:
                continue
            task = self.model.curie(row["task"])
            allowed, reason = self.hook.allows(task, identity)
            if not allowed:
                log.debug("user task %s hidden from %s: %s", task, identity.id, reason)
                continue
            form = self.model.user_task_form(task)
            screen = self.model.form_screen(form)
            out.append(
                {
                    "instance": row["instance_id"],
                    "task": str(task),
                    "bpmn_id": row["bpmn_id"],
                    "label": self.model.label(task),
                    "process": row["process"],
                    "correlation_key": row["correlation_key"],
                    "form": str(form),
                    "partial": f"{local_name(form)}.html",
                    "screen": None if screen is None else self.model.page(screen).path,
                    "entity": self._task_entity(task, row),
                    "created": row["created"],
                }
            )
        return out

    def _task_entity(self, task, row) -> dict | None:
        for shape in self.model.read_shapes(task):
            rows = self.store.query(shape, correlation_key=row["correlation_key"])
            mine = [r for r in rows if r["instance_id"] == row["instance_id"]] or rows
            if mine:
                return flatten(mine[-1])
        return None

    async def complete_task(self, task_curie, payload, correlation_key: str, identity: Identity | None) -> Instance:
        """Complete the open user task ``task_curie`` of the instance with
        ``correlation_key`` as ``identity``, then let the worker continue.
        Raises PolicyDenied (401/403), TaskNotOpen (409) or ContractViolation
        (422, nothing changed). ``await instance.wait()`` for the result."""
        task = self.model.curie(task_curie)
        try:
            self.hook.check_element(task, identity)
        except PolicyDenied as denied:
            log.info(
                "complete %s (%s) by %s: denied %s (%s)",
                task,
                correlation_key,
                getattr(identity, "id", None),
                denied.http_status,
                denied.reason,
            )
            raise
        if self.store.get_user_task(task, correlation_key) is None:
            raise TaskNotOpen(task, correlation_key)
        shape = self.model.task_output_shape(task)
        data = _validate(self.model, shape, payload)

        lock = self._task_locks.setdefault(f"{task} {correlation_key}", asyncio.Lock())
        async with lock:
            row = self.store.get_user_task(task, correlation_key)  # a racing call may have won
            if row is None:
                raise TaskNotOpen(task, correlation_key)
            instance = await self._waiting_instance(row["instance_id"])
            try:
                await self.worker.complete_user_task(instance, task, shape, data, identity.id)
            except Exception:
                self.instances.pop(instance.id, None)  # next call reloads the last checkpoint
                log.exception("complete %s on instance %s by %s failed", task, instance.id, identity.id)
                raise
            log.info(
                "completed %s on instance %s (correlation %s) by %s", task, instance.id, correlation_key, identity.id
            )
            return self._launch(instance)

    async def _waiting_instance(self, instance_id: str) -> Instance:
        """The in-memory instance once its worker has stopped, else the
        checkpoint deserialized from the store."""
        instance = self.instances.get(instance_id)
        if instance is not None and instance.task is not None:
            if not instance.task.done():
                await instance.wait()
            if instance.result is not None and instance.result["status"] == "waiting":
                return instance
        meta = self.store.get_instance(instance_id)
        wf = self.engine.deserialize(self.store.load_state(instance_id))
        return Instance(instance_id, meta["correlation_key"], self.model.curie(meta["process"]), wf)

    # ── reads ──

    def query(self, shape_curie, **filters) -> list[dict]:
        """Persisted entities of a shape. A filter named after a correlation-key
        parameter label (``conversation=``) matches the correlation key; others
        match top-level payload fields."""
        labels = self.model.correlation_key_labels()
        mapped = {}
        for name, value in filters.items():
            mapped["correlation_key" if name in labels else name] = value
        return self.store.query(self.model.curie(shape_curie), **mapped)

    def data_health(self) -> list[Finding]:
        """The findings of the attached profile's instance-data rules on the
        stored entities (ADR-0036), sorted; ``[]`` when the model attaches no
        profile. Raises the resolver's ``ResolutionError`` (seam:conformsTo or
        seam:profileShapes) when the profile cannot be loaded, and a stored
        entity's ``ContractViolation`` when the shape contract refuses it."""
        profile = resolve_profile(self.model.ds, model_dir(self.model.path))
        if profile is None:
            log.info("data health: the model attaches no profile")
            return []
        with self.telemetry.data_health_span(profile.iri) as span:
            findings = _data_health(self.model, self.store, profile.shapes)
            span.count(len(findings))
        log.info("data health %s %d warning(s)", profile.iri, len(findings))
        return findings

    def subscribe(self, channel_curie, scope) -> Subscription:
        """SSE frames of one channel scope (backlog replay, then live)."""
        return self.bus.subscribe(self.model.curie(channel_curie), scope)

    def render_fragment(self, name: str, data, **params) -> HTMLResponse:
        """Render the htmx partial ``name`` (a seam:rendersComponent target's
        local name plus ``.html``, or ``_item.html`` for one item) with
        ``data`` bound per the seam.ttl visibleWhen rule. An unknown name
        raises ResolutionError before any template file is opened."""
        return HTMLResponse(self.fragments.render(name, data, params))

    def page_context(self, page=None, **params) -> dict:
        """The variables of a page template (default: the landmark page).

        Each ifml:contains component that seam:reads a shape is bound by
        FragmentRenderer's rule. A component whose ifml:hasParameter labels
        include a proc:correlationKey label is scoped: it reads only entities
        of that correlation key, taken from ``params`` or, when absent, the
        smallest id among the unscoped components' entities. The key is bound
        under its label too (``conversation``)."""
        page = self.model.landmark_page() if page is None else self.model.curie(page)
        keys = self.model.correlation_key_labels()
        blocks = []
        for component in self.model.page_components(page):
            reads = self.model.component(component).reads
            if reads:
                blocks.append((component, reads[0].iri, sorted(keys & self.model.parameter_labels(component))))
        ctx: dict = {}
        ids = []
        for component, shape, scope in blocks:
            if not scope:
                rows = self.query(shape)
                ctx.update(self.fragments.component_context(component, rows))
                ids += [str(i) for i in (flatten(r).get("id") for r in rows) if i is not None]
        for key in sorted({k for _c, _s, scope in blocks for k in scope}):
            if params.get(key):
                ctx[key] = str(params[key])
            elif ids:
                ctx[key] = min(ids)
        for component, shape, scope in blocks:
            if scope:
                filters = {k: ctx[k] for k in scope if k in ctx}
                rows = self.query(shape, **filters) if len(filters) == len(scope) else []
                ctx.update(self.fragments.component_context(component, rows))
        return ctx

    def render_page(self, page=None, **params) -> HTMLResponse:
        """Render ``<page local name>.html`` from the templates dir with
        ``page_context``. ``params`` are correlation-key values, e.g. the
        page's ``?conversation=`` query parameter."""
        page = self.model.landmark_page() if page is None else self.model.curie(page)
        ctx = self.page_context(page, **params)
        return HTMLResponse(self.fragments.render_template(f"{local_name(page)}.html", ctx))
