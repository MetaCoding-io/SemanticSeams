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
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi.responses import HTMLResponse

from .channels import ChannelBus, Subscription
from .contracts import validate as _validate
from .engine import Engine
from .errors import ModelHashMismatch, ResolutionError
from .fragments import FragmentRenderer, flatten
from .lifecycle import LifecycleGuard
from .llm import LLMClient
from .model import SEAM, ModelGraph, local_name
from .policy import PolicyHook, authenticator_from_env
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
        self.instances: dict[str, Instance] = {}
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
        names one, as ``start_process`` does. Returns the stored row (the form
        ``query`` returns), or raises ContractViolation (422) and stores
        nothing."""
        shape = self.model.curie(shape_curie)
        data = dict(_validate(self.model, shape, payload))
        status = None
        if (shape, SEAM.lifecycle, None) in self.model.ds:
            status = data.get("status") or self.model.lifecycle_for(shape).initial
            data["status"] = status
        entity = self.store.put_entity(str(uuid.uuid4()), shape, data, status=status)
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
