"""``Runtime``: the facade generated route modules import (ADR-0007, D013).

    runtime = Runtime.load("/model/chat-app.trig", model_hash=MODEL_HASH)

``SEAMS_MODEL``, when set and non-empty, takes precedence over ``trig_path``:
the generated module names the path it was generated against, and the
deployment (compose sets ``SEAMS_MODEL``) chooses the model actually mounted.
A missing model file raises ``FileNotFoundError`` naming the path (and
``SEAMS_MODEL`` when that chose it).

``load`` refuses a model whose hash differs from the one the code was
generated from (ADR-0007 rule 2) unless ``allow_hash_mismatch=True`` or
``SEAMS_ALLOW_HASH_MISMATCH=1``. The other methods are what a thin handler
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

Human tasks (ADR-0009): ``user_tasks`` lists the open BPMN user tasks an
identity may complete, ``complete_task`` checks the task's policies,
validates the payload against its output shape and completes it on the
waiting instance (then the worker continues), and ``task_policy`` is the
FastAPI dependency for a completion route.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import uuid
from pathlib import Path

from fastapi.responses import HTMLResponse

from .channels import ChannelBus, Subscription
from .contracts import _items, shape_contract
from .contracts import validate as _validate
from .engine import Engine
from .errors import ModelHashMismatch, PolicyDenied, ResolutionError, TaskNotOpen
from .fragments import FragmentRenderer, flatten
from .lifecycle import LifecycleGuard
from .llm import LLMClient
from .model import IFML, SEAM, ModelGraph, local_name
from .policy import Identity, PolicyHook, authenticator_from_env
from .store import Store
from .worker import RUNNING, Instance, Worker, new_state

log = logging.getLogger(__name__)

MODEL_ENV = "SEAMS_MODEL"
DB_ENV = "SEAMS_DB"
ALLOW_MISMATCH_ENV = "SEAMS_ALLOW_HASH_MISMATCH"
DEFAULT_DB = "seams.sqlite"
TEMPLATES_ENV = "SEAMS_TEMPLATES"
DEFAULT_TEMPLATES = "templates"


class Runtime:
    def __init__(self, model: ModelGraph, store: Store, *, authenticator=None, evaluator=None,
                 llm: LLMClient | None = None, bus: ChannelBus | None = None, templates_dir=None):
        self.model = model
        self.store = store
        self.engine = Engine(model)
        self.bus = bus if bus is not None else ChannelBus()
        self.guard = LifecycleGuard(model)
        self.hook = PolicyHook(model, authenticator if authenticator is not None else authenticator_from_env(),
                               evaluator)
        self.llm = llm if llm is not None else LLMClient()
        self.worker = Worker(model, self.engine, store, self.bus, self.guard, self.llm)
        self.worker.on_published = self._on_published
        self.instances: dict[str, Instance] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        self.templates_dir = Path(templates_dir if templates_dir is not None
                                  else os.environ.get(TEMPLATES_ENV) or DEFAULT_TEMPLATES)
        self.fragments = FragmentRenderer(model, self.templates_dir)

    @classmethod
    def load(cls, trig_path, model_hash: str | None = None, *, allow_hash_mismatch: bool = False,
             db_path=None, authenticator=None, evaluator=None, llm_transport=None,
             llm_base_url: str | None = None, templates_dir=None) -> "Runtime":
        override = os.environ.get(MODEL_ENV)
        if override:
            log.info("model path %s from %s (overrides argument %s)", override, MODEL_ENV, trig_path)
            trig_path = override
        else:
            log.info("model path %s from argument (%s unset)", trig_path, MODEL_ENV)
        if not Path(trig_path).is_file():
            source = f" (from {MODEL_ENV})" if override else ""
            raise FileNotFoundError(f"model file {trig_path} not found{source}")
        model = ModelGraph(trig_path)
        if model_hash is not None and model_hash != model.hash:
            if allow_hash_mismatch or os.environ.get(ALLOW_MISMATCH_ENV) == "1":
                log.warning("model hash mismatch allowed for %s: expected %s, got %s",
                            model.path, model_hash, model.hash)
            else:
                raise ModelHashMismatch(model_hash, model.hash, model.path)
        db = Path(db_path if db_path is not None else os.environ.get(DB_ENV) or DEFAULT_DB)
        runtime = cls(model, Store(db), authenticator=authenticator, evaluator=evaluator,
                      llm=LLMClient(llm_base_url, transport=llm_transport), templates_dir=templates_dir)
        log.info("runtime loaded %s (%s), store %s, templates %s", model.path, model.hash, db,
                 runtime.templates_dir)
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
        entity_id = str(uuid.uuid4())
        if "id" in shape_contract(self.model, shape).fields:
            payload = {**dict(_items(payload)), "id": entity_id}
        data = dict(_validate(self.model, shape, payload))
        status = None
        if (shape, SEAM.lifecycle, None) in self.model.ds:
            status = data.get("status") or self.model.lifecycle_for(shape).initial
            data["status"] = status
        entity = self.store.put_entity(entity_id, shape, data, status=status)
        log.info("wrote %s entity %s (status %s)", shape, entity["id"], status)
        return entity

    # ── processes ──

    async def start_process(self, process_curie, payload, correlation_key: str, *,
                            stop_after=None) -> Instance:
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
        if (shape, SEAM.lifecycle, None) in self.model.ds:
            status = message.get("status") or self.model.lifecycle_for(shape).initial
            state["status"][str(shape)] = status
            state["history"][str(shape)] = [status]
        wf.data["seams"] = state
        instance = Instance(str(uuid.uuid4()), correlation_key, process, wf, stop_after)
        self.worker._checkpoint(instance, RUNNING)
        log.info("started %s instance %s (correlation %s)", process, instance.id, correlation_key)
        return self._launch(instance)

    async def start_subscribed(self, process_curie, correlation_key: str, current: dict,
                               status: dict, *, stop_after=None) -> Instance:
        """Start a channel-started process (ADR-0010) as the worker does when a
        message throw event publishes on the channel its start event
        seam:subscribesTo: the same correlation key, and a copy of the
        publisher's ``current`` entities (ids kept) and ``status`` map. No
        operation accepts the payload, so nothing is re-validated. The new
        instance is checkpointed before its worker task runs."""
        return self._start_subscribed(self.model.curie(process_curie), correlation_key, current,
                                      status, stop_after)

    def _start_subscribed(self, process, correlation_key, current, status, stop_after=None) -> Instance:
        start = self.model.start_channel(process)
        if not correlation_key:
            raise ResolutionError(process, "proc:correlationKey", "empty correlation key")
        wf = self.engine.new_workflow(process)
        self.engine.deliver_start(wf, start.event)
        state = new_state(process, correlation_key)
        state["current"] = copy.deepcopy(dict(current))
        state["status"] = dict(status)
        state["history"] = {shape: [value] for shape, value in status.items()}
        wf.data["seams"] = state
        instance = Instance(str(uuid.uuid4()), correlation_key, process, wf, stop_after)
        self.worker._checkpoint(instance, RUNNING)
        log.info("started %s instance %s from %s on %s (correlation %s)", process, instance.id,
                 start.event, start.channel, correlation_key)
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
            return [{"process": None, "instance": None,
                     "error": {"type": type(exc).__name__, "message": str(exc)}}]
        for process in processes:
            try:
                inst = self._start_subscribed(process, publisher.correlation_key,
                                              publisher.state["current"], publisher.state["status"])
                started.append({"process": str(process), "instance": inst.id})
            except Exception as exc:  # noqa: BLE001 - the publisher's element already completed
                log.exception("instance %s: starting subscriber %s on %s failed", publisher.id,
                              process, channel)
                started.append({"process": str(process), "instance": None,
                                "error": {"type": type(exc).__name__, "message": str(exc)}})
        return started

    async def resume(self, instance_id: str, *, stop_after=None) -> Instance:
        """Continue a checkpointed instance (e.g. after a restart) in this runtime."""
        meta = self.store.get_instance(instance_id)
        if meta is None:
            raise LookupError(f"no instance {instance_id} in {self.store.path}")
        wf = self.engine.deserialize(self.store.load_state(instance_id))
        instance = Instance(instance_id, meta["correlation_key"], self.model.curie(meta["process"]),
                            wf, stop_after)
        log.info("resuming instance %s (was %s)", instance_id, meta["status"])
        return self._launch(instance)

    def _launch(self, instance: Instance) -> Instance:
        instance.task = asyncio.get_running_loop().create_task(
            self.worker.run(instance), name=f"seams-instance-{instance.id}")
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
            raise PolicyDenied("seam:governedBy", None, 401,
                               f"no authenticated identity ({self.hook.authenticator!r})")
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
            out.append({
                "instance": row["instance_id"], "task": str(task), "bpmn_id": row["bpmn_id"],
                "label": self.model.label(task), "process": row["process"],
                "correlation_key": row["correlation_key"], "form": str(form),
                "partial": f"{local_name(form)}.html",
                "screen": None if screen is None or (screen, IFML.path, None) not in self.model.ds
                else self.model.page_path(screen),
                "entity": self._task_entity(task, row), "created": row["created"],
            })
        return out

    def _task_entity(self, task, row) -> dict | None:
        for shape in self.model.read_shapes(task):
            rows = self.store.query(shape, correlation_key=row["correlation_key"])
            mine = [r for r in rows if r["instance_id"] == row["instance_id"]] or rows
            if mine:
                return flatten(mine[-1])
        return None

    async def complete_task(self, task_curie, payload, correlation_key: str,
                            identity: Identity | None) -> Instance:
        """Complete the open user task ``task_curie`` of the instance with
        ``correlation_key`` as ``identity``, then let the worker continue.
        Raises PolicyDenied (401/403), TaskNotOpen (409) or ContractViolation
        (422, nothing changed). ``await instance.wait()`` for the result."""
        task = self.model.curie(task_curie)
        try:
            self.hook.check_element(task, identity)
        except PolicyDenied as denied:
            log.info("complete %s (%s) by %s: denied %s (%s)", task, correlation_key,
                     getattr(identity, "id", None), denied.http_status, denied.reason)
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
            log.info("completed %s on instance %s (correlation %s) by %s", task, instance.id,
                     correlation_key, identity.id)
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
            shape = self.model.ds.value(component, SEAM.reads)
            if shape is not None:
                blocks.append((component, shape, sorted(keys & self.model.parameter_labels(component))))
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
