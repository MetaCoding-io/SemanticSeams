"""The generic worker: runs one process instance using only graph facts (D013).

No handler here is keyed on a bpmn id (ADR-0007 rule 1). The worker steps
the Spiff workflow as the ADR-0007 spike driver did (READY tasks run; a
plain ServiceTask stays STARTED until the worker has dispatched it, then it
is completed) and applies these rules to each BPMN element, in this order:

1. ``seam:fires T``: before dispatch, ``LifecycleGuard.check`` that T leaves
   the instance's current status for the shape whose ``seam:lifecycle``
   owns T (a missing status is the machine's ``state:initial``).
2. Business-rule tasks (``seam:decidedBy``): ``Engine.before_task`` fills the
   dec:input variables from the current entity of the shape the task
   ``seam:reads``; after the run, ``Engine.after_task`` returns the
   dec:output process variables.
3. ``seam:invokes op``: when op's implementing container (the one that
   ``seam:exposes`` it) also ``seam:executes`` the process, the call is
   in-process and needs no remote call (its ``seam:acceptsShape`` was
   validated when the process started). Any other container gets a streaming
   OpenAI-compatible call to op's ``comm:path``. Each delta is published on
   the process's ``seam:publishesTo`` channel, scoped by the correlation key
   and named by its ``comm:eventName``. The assembled reply
   ``{role: "assistant", content}`` is validated against op's
   ``seam:returnsShape`` and becomes the current entity of that shape.
   The request's ``model`` is the value of the most recent decision when it
   produced exactly one output (the routed provider), else omitted.
4. ``seam:writes Shape``: persist the current entity of that shape (the
   first write persists the user message; after an invoke, the reply). A
   shape with a ``seam:lifecycle`` and no status yet (a user task's output,
   say) is stored in, and from then on tracked at, its ``state:initial``.
5. After dispatch, the fired transition is applied: the status becomes T's
   ``state:to`` label (for example "sending") and is persisted on every
   entity of that shape the instance has written.
6. ``seam:publishesTo`` a comm:Channel from a message throw event: publish a
   completion event named after the channel's ``rdfs:label`` (gaps.md GAP-26).
   Then ``on_published`` (set by Runtime) starts every channel-started process
   subscribed to that channel (ADR-0010); the trace row records them under
   ``started`` as ``[{process, instance}]``.
7. Any exception while dispatching: apply ``LifecycleGuard.on_error`` for
   each tracked status that has an "error" exit (status becomes "failed"),
   record the error as JSON, close the channel scope and mark the instance
   failed. The error is not re-raised; ``Instance.wait()`` returns it. When
   Spiff wrapped a model error (a ``ResolutionError`` raised inside a
   business-rule task becomes a ``WorkflowTaskException``), the model error
   is the one recorded, so the error names the decision.
8. After each element the workflow is checkpointed with the engine's
   serializer into the store, so ``Runtime.resume`` can continue it. The
   checkpoint also replaces the instance's open ``user_tasks`` rows with its
   READY manual tasks (none once it completes or fails).
9. User tasks (``proc:UserTask``, manual in Spiff) are never stepped by the
   loop: the instance ends "waiting" on them. ``complete_user_task`` makes
   the person's validated payload the current entity of the task's output
   shape (the seam:completedOn form's seam:writes) and merges it into the
   task data so gateways can route on it, then applies rules 1 and 3-6 to the
   task with the trace row's ``by`` set to the completing identity (ADR-0009).

The worker's own state (current entities, statuses, decision outputs and a
trace row per element) lives in ``workflow.data["seams"]``, which Spiff
serializes with the workflow.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from urllib.parse import quote

from rdflib import URIRef
from SpiffWorkflow.util.task import TaskState

from .contracts import validate
from .errors import ResolutionError, RuntimeModelError
from .model import SEAM, ModelGraph

log = logging.getLogger(__name__)

RUNNING, STOPPED, COMPLETE, FAILED, WAITING = "running", "stopped", "complete", "failed", "waiting"


def new_state(process, correlation_key: str) -> dict:
    """The initial ``workflow.data["seams"]`` record."""
    return {
        "process": str(process),
        "correlation_key": correlation_key,
        "current": {},
        "status": {},
        "history": {},
        "written": {},
        "variables": {},
        "decision": {},
        "trace": [],
        "error": None,
    }


class Instance:
    """A running (or finished) process instance. ``await wait()`` returns the
    worker's result dict."""

    def __init__(self, id: str, correlation_key: str, process, workflow, stop_after=None):
        self.id = id
        self.correlation_key = correlation_key
        self.process = process
        self.workflow = workflow
        self.stop_after = stop_after
        self.task: asyncio.Task | None = None
        self.result: dict | None = None

    async def wait(self) -> dict:
        return await asyncio.shield(self.task)

    @property
    def state(self) -> dict:
        return self.workflow.data["seams"]

    def __repr__(self) -> str:
        status = None if self.result is None else self.result["status"]
        return f"Instance({self.id!r}, correlation_key={self.correlation_key!r}, status={status!r})"


class Worker:
    def __init__(self, model: ModelGraph, engine, store, bus, guard, llm):
        self.model = model
        self.engine = engine
        self.store = store
        self.bus = bus
        self.guard = guard
        self.llm = llm
        # Set by Runtime: called as on_published(instance, channel IRI) after
        # rule 6 publishes; returns [{process, instance}] for the trace row.
        self.on_published = None

    # ── the loop ──

    async def run(self, instance: Instance) -> dict:
        wf = instance.workflow
        try:
            while True:
                task = self._next(wf)
                if task is None:
                    break
                bpmn_id = task.task_spec.bpmn_id
                await self._element(instance, task)
                self._checkpoint(instance, RUNNING)
                if bpmn_id is not None and self._is_stop(instance, task):
                    log.info("instance %s stopped after %s", instance.id, bpmn_id)
                    self._checkpoint(instance, STOPPED)
                    return self._finish(instance, STOPPED)
        except Exception as exc:  # noqa: BLE001 - every failure ends the instance as failed
            self._fail(instance, exc)
            return self._finish(instance, FAILED)
        status = COMPLETE if wf.is_completed() else WAITING
        self._checkpoint(instance, status)
        if status == WAITING:
            log.info(
                "instance %s waiting on user task(s) %s",
                instance.id,
                [t.task_spec.bpmn_id for t in self.open_user_tasks(wf)] or "(none)",
            )
        return self._finish(instance, status)

    @staticmethod
    def _next(wf):
        started = [t for t in wf.get_tasks(state=TaskState.STARTED)]
        if started:
            return started[0]
        ready = [t for t in wf.get_tasks(state=TaskState.READY) if not t.task_spec.manual]
        return ready[0] if ready else None

    @staticmethod
    def open_user_tasks(wf) -> list:
        """READY manual tasks with a BPMN element (the open user tasks)."""
        return [
            t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.manual and t.task_spec.bpmn_id is not None
        ]

    async def complete_user_task(self, instance: Instance, task_iri, shape, payload: dict, by: str) -> None:
        """Complete the open user task ``task_iri`` with an already validated
        ``payload`` of ``shape``, then checkpoint. The caller resumes the loop.
        LookupError when the instance has no such READY task."""
        task_iri = str(task_iri)
        tasks = [t for t in self.open_user_tasks(instance.workflow) if str(self.engine.task_iri(t)) == task_iri]
        if not tasks:
            raise LookupError(f"instance {instance.id} has no open user task {task_iri}")
        task = tasks[0]
        instance.state["current"][str(shape)] = {"id": None, "data": dict(payload)}
        task.data.update(payload)
        await self._element(instance, task, by=by)
        self._checkpoint(instance, RUNNING)

    def _is_stop(self, instance: Instance, task) -> bool:
        if instance.stop_after is None:
            return False
        stop = str(instance.stop_after)
        return stop in (task.task_spec.bpmn_id, str(self.engine.task_iri(task)))

    # ── one element ──

    async def _element(self, instance: Instance, task, by: str | None = None) -> None:
        st = instance.state
        bpmn_id = task.task_spec.bpmn_id
        if bpmn_id is None:  # Spiff's internal Start / End.* specs carry no graph facts
            if task.state == TaskState.READY:
                task.run()
            if task.state == TaskState.STARTED:
                task.complete()
            return
        iri = self.engine.task_iri(task)
        row = {"task": bpmn_id, "iri": str(iri)}
        if by is not None:
            row["by"] = by
        log.info("instance %s: %s%s", instance.id, bpmn_id, "" if by is None else f" (by {by})")

        # 1. the fired transition must be enabled
        transition = shape = None
        t_iri = self.model.ds.value(iri, SEAM.fires)
        if t_iri is not None:
            shape = self.model.lifecycle_shape(t_iri)
            transition = self.guard.check(shape, st["status"].get(str(shape)), t_iri)
            row["fires"] = str(t_iri)

        # 2. business-rule inputs, then run the element
        brt = self.engine.is_business_rule(task)
        if brt:
            binding = self.engine.binding(task)
            row["decision"] = str(binding.decision)
            self.engine.before_task(task, self._read_entity(iri, st))
        if task.state == TaskState.READY:
            task.run()
        if brt:
            mapped = self.engine.after_task(task)
            st["variables"].update(mapped)
            st["decision"] = dict(mapped)
            row["outputs"] = dict(mapped)

        # 3. invoke
        op = self.model.ds.value(iri, SEAM.invokes)
        if op is not None:
            await self._invoke(instance, op, row)

        # 4. writes
        for written in self.model.written_shapes(iri):
            row.setdefault("writes", []).append(self._persist(instance, iri, written))

        # 5. apply the transition
        if transition is not None:
            self._set_status(instance, shape, transition.to_state)
            row["status"] = transition.to_state

        if task.state == TaskState.STARTED:
            task.complete()  # only now: after the handler (and the whole stream) finished

        # 6. message throw events publish a completion event
        if op is None and not self.engine.is_service_task(task) and (iri, SEAM.publishesTo, None) in self.model.ds:
            ch = self.model.channel_for_event(iri)
            data = {
                "instance": instance.id,
                "event": self.model.label(iri),
                "status": {self.model.label(URIRef(s)): v for s, v in st["status"].items()},
            }
            self.bus.publish(ch.iri, instance.correlation_key, ch.label, data)
            row["published"] = {"channel": str(ch.iri), "event": ch.label}
            # 6a. start the channel-started processes subscribed to it (ADR-0010)
            if self.on_published is not None:
                started = self.on_published(instance, ch.iri)
                if started:
                    row["started"] = started
        st["trace"].append(row)

    def _read_entity(self, iri, st) -> dict | None:
        for shape in self.model.read_shapes(iri):
            cur = st["current"].get(str(shape))
            if cur is not None:
                return cur["data"]
        return None

    async def _invoke(self, instance: Instance, op, row: dict) -> None:
        st = instance.state
        container = self.model.implementing_container(op, instance.process)
        row.update(invokes=str(op), container=str(container.iri), in_process=container.in_process)
        if container.in_process:
            return  # its acceptsShape was validated at start_process
        op_path = self.model.operation_path(op)
        accepts = self.model.accepted_shape(op)
        cur = st["current"].get(str(accepts))
        if cur is None:
            raise ResolutionError(op, SEAM.acceptsShape, f"no current {accepts} entity to send")
        path = op_path.template
        for m in op_path.mappings:
            if m.property not in cur["data"]:
                raise ResolutionError(op, m.property_iri, f"entity has no {m.property!r} for {{{m.variable}}}")
            path = path.replace("{" + m.variable + "}", quote(str(cur["data"][m.property]), safe=""))
        row["path"] = path
        messages = [{"role": cur["data"].get("role") or "user", "content": cur["data"]["content"]}]
        decided = list(st["decision"].values())
        model_name = decided[0] if len(decided) == 1 else None
        row["model"] = model_name

        if self.llm.base_url:
            base = self.llm.base_url
        else:
            executor = self.model.executing_container(instance.process)
            base = self.llm.resolve_base_url(self.model.service_binding_key(executor.iri, container.iri))
        channel = self.model.process_channel(instance.process)
        parts: list[str] = []
        async for delta in self.llm.stream_completion(path, messages, model_name, base_url=base):
            self.bus.publish(
                channel.iri,
                instance.correlation_key,
                channel.event_name,
                {"instance": instance.id, "seq": len(parts), "content": delta},
            )
            parts.append(delta)
        returns = self.model.returned_shape(op)
        reply = validate(self.model, returns, {"role": "assistant", "content": "".join(parts)}, operation=op)
        st["current"][str(returns)] = {"id": None, "data": reply}
        row["tokens"] = len(parts)

    # ── entities and statuses ──

    def _persist(self, instance: Instance, iri, shape) -> str:
        st = instance.state
        cur = st["current"].get(str(shape))
        if cur is None:
            raise ResolutionError(iri, SEAM.writes, f"no current {shape} entity to persist")
        if cur["id"] is None:
            cur["id"] = str(uuid.uuid4())
        status = st["status"].get(str(shape))
        if status is None and (shape, SEAM.lifecycle, None) in self.model.ds:
            # first write of a lifecycle shape no transition has moved yet
            # (e.g. a user task's output): it is stored in state:initial
            status = self.model.lifecycle_for(shape).initial
            st["status"][str(shape)] = status
            st["history"].setdefault(str(shape), []).append(status)
        data = dict(cur["data"])
        if status is not None:
            data["status"] = status
        self.store.put_entity(
            cur["id"], shape, data, correlation_key=instance.correlation_key, instance_id=instance.id, status=status
        )
        written = st["written"].setdefault(str(shape), [])
        if cur["id"] not in written:
            written.append(cur["id"])
        return cur["id"]

    def _set_status(self, instance: Instance, shape, status: str) -> None:
        st = instance.state
        st["status"][str(shape)] = status
        st["history"].setdefault(str(shape), []).append(status)
        for entity_id in st["written"].get(str(shape), []):
            entity = self.store.get_entity(entity_id)
            if entity is not None:
                data = dict(entity["data"], status=status)
                self.store.put_entity(
                    entity_id,
                    shape,
                    data,
                    correlation_key=entity["correlation_key"],
                    instance_id=entity["instance_id"],
                    status=status,
                )
        cur = st["current"].get(str(shape))
        if cur is not None and cur["id"] is None:
            cur["data"]["status"] = status

    # ── failure, checkpoints, results ──

    @staticmethod
    def _model_error(exc: BaseException) -> BaseException:
        """The first RuntimeModelError in ``exc``'s cause/context chain, else ``exc``."""
        seen, cur = set(), exc
        while cur is not None and id(cur) not in seen:
            if isinstance(cur, RuntimeModelError):
                return cur
            seen.add(id(cur))
            cur = cur.__cause__ or cur.__context__
        return exc

    def _fail(self, instance: Instance, exc: Exception) -> None:
        st = instance.state
        exc = self._model_error(exc)
        log.error("instance %s failed: %s", instance.id, exc, exc_info=not isinstance(exc, RuntimeModelError))
        st["error"] = (
            exc.to_dict()
            if isinstance(exc, RuntimeModelError)
            else {"type": type(exc).__name__, "message": str(exc), "http_status": 500}
        )
        for shape, current in list(st["status"].items()):
            try:
                tr = self.guard.on_error(shape, current)
                if tr is not None:
                    self._set_status(instance, shape, tr.to_state)
                    st["trace"].append(
                        {"task": None, "fires": str(tr.iri), "status": tr.to_state, "error": st["error"]["type"]}
                    )
            except Exception:  # noqa: BLE001 - keep failing closed; the original error is recorded
                log.exception("instance %s: on_error for %s failed", instance.id, shape)
        try:
            ch = self.model.process_channel(instance.process)
            self.bus.close(ch.iri, instance.correlation_key)
        except ResolutionError:
            pass
        try:
            self._checkpoint(instance, FAILED)
        except Exception:  # noqa: BLE001 - the state may be unserializable mid-task
            log.exception("instance %s: checkpoint after failure failed", instance.id)
            self.store.save_state(
                instance.id, instance.process, "{}", correlation_key=instance.correlation_key, status=FAILED
            )
            self.store.replace_user_tasks(instance.id, [])

    def _checkpoint(self, instance: Instance, status: str) -> None:
        self.store.save_state(
            instance.id,
            instance.process,
            self.engine.serialize(instance.workflow),
            correlation_key=instance.correlation_key,
            status=status,
        )
        tasks = [] if status in (COMPLETE, FAILED) else self.open_user_tasks(instance.workflow)
        self.store.replace_user_tasks(
            instance.id,
            [
                {
                    "task": str(self.engine.task_iri(t)),
                    "bpmn_id": t.task_spec.bpmn_id,
                    "process": str(instance.process),
                    "correlation_key": instance.correlation_key,
                }
                for t in tasks
            ],
        )

    def _finish(self, instance: Instance, status: str) -> dict:
        st = instance.state
        label = self.model.label
        instance.result = {
            "instance": instance.id,
            "correlation_key": instance.correlation_key,
            "status": status,
            "lifecycle": {label(URIRef(s)): v for s, v in st["status"].items()},
            "history": {label(URIRef(s)): list(v) for s, v in st["history"].items()},
            "variables": dict(st["variables"]),
            "entities": {label(URIRef(s)): list(v) for s, v in st["written"].items()},
            "trace": [dict(r) for r in st["trace"]],
            "error": st["error"],
        }
        return instance.result
