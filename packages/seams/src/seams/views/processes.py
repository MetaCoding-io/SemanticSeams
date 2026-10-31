"""``model.processes``: proc:Processes, their BPMN payloads and process elements.

A process element's IRI is ``<BPMN model IRI>#<bpmn id>``: the model the
process is ``seam:detailedBy`` plus the element's id in that model's BPMN
file. Several BPMN models in one graph are the normal case, so an id is
only unique within one model (``Processes.element`` says when it is not).

``Process.nodes()`` walks the BPMN XML (``seams.bpmn``, lxml only) in flow
order, every bpmn:process of the file in document order: start and end
events, tasks, intermediate events and gateways, lifted into the graph or
not. Each ``FlowNode`` carries its sequence flows and lane and is joined to
its ``ProcessElement`` when the graph types ``<bpmn_model>#<bpmn id>`` as
one, so its graph edges (``invokes``, ``completed_on``, ...) pass through.
``tasks()``, ``gateways()`` and ``lanes()`` filter that walk.

``Process.error_boundaries()`` joins each lifted proc:ErrorBoundaryEvent to
its BPMN boundary event, the task it is attached to and the error that task's
operation declares (ADR-0013), checking that the graph and the XML agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rdflib import RDF, URIRef

from .._xml import elements, localname
from ..bpmn import BpmnNode, BpmnProcess, Lane, SequenceFlow, parse_bpmn
from ..errors import ResolutionError
from ..graph import bpmn_start_event_ids
from ..namespaces import COMM, PROC, SEAM, local_name
from ._base import Element, Many, Views, element_type, optional, sorted_many

if TYPE_CHECKING:
    from .architecture import Container
    from .decisions import Decision
    from .interfaces import Component, Event
    from .lifecycles import Transition
    from .operations import Channel, Operation, Status
    from .shapes import Shape

#: The proc: classes a process element is typed with; ``ProcessElement.kind`` is one of their local names.
ELEMENT_TYPES = (
    PROC.Task,
    PROC.ServiceTask,
    PROC.UserTask,
    PROC.BusinessRuleTask,
    PROC.MessageCatchEvent,
    PROC.MessageThrowEvent,
    PROC.ErrorBoundaryEvent,
)


def bpmn_process_ids(views: Views, path: Path) -> tuple[str, ...]:
    """ids of every bpmn:process in the BPMN file, in document order (read once per registry)."""

    def read() -> tuple[str, ...]:
        return tuple(cast(str, el.get("id")) for el in elements(path) if localname(el.tag) == "process")

    return views.view(f"bpmn-process-ids:{path}", read)


def bpmn_processes(views: Views, path: Path) -> tuple[BpmnProcess, ...]:
    """``parse_bpmn(path)``, read once per registry."""
    return views.view(f"bpmn:{path}", lambda: parse_bpmn(path))


def _start_ids(views: Views, path: Path) -> set[str]:
    return views.view(f"bpmn-start-ids:{path}", lambda: bpmn_start_event_ids(path))


@element_type(PROC.Process)
@dataclass(frozen=True, eq=False)
class Process(Element):
    """A proc:Process."""

    @property
    def bpmn_models(self) -> tuple[URIRef, ...]:
        """Every seam:Model it is seam:detailedBy, by IRI (a well-formed process has one)."""
        return tuple(self._objects(SEAM.detailedBy))

    @property
    def bpmn_model(self) -> URIRef:
        """The BPMN seam:Model it is seam:detailedBy (exactly one)."""
        found = self.bpmn_models
        if len(found) != 1:
            raise ResolutionError(
                self.iri, SEAM.detailedBy, f"expected one BPMN model, found {[str(m) for m in found]}"
            )
        return found[0]

    @property
    def bpmn_path(self) -> Path:
        """The BPMN file its model seam:renderPayload names."""
        return self.views.model.payload_path(self.bpmn_model)

    @property
    def bpmn_process_ids(self) -> tuple[str, ...]:
        """ids of every bpmn:process its BPMN file declares, in document order."""
        return bpmn_process_ids(self.views, self.bpmn_path)

    @property
    def executed_by(self) -> Many[Container]:
        """The containers that seam:execute it (in-process)."""
        from .architecture import Container

        return self._many(Container, self._subjects(SEAM.executes), SEAM.executes)

    @property
    def triggered_by(self) -> Many[Event]:
        """The IFML events that seam:trigger it."""
        from .interfaces import Event

        return self._many(Event, self._subjects(SEAM.triggers), SEAM.triggers)

    @property
    def correlation_key(self) -> str | None:
        """The label of its proc:correlationKey parameter, or None."""
        param = self._value(PROC.correlationKey)
        return None if param is None else self.views.model.label(param)

    @property
    def correlation_parameters(self) -> tuple[URIRef, ...]:
        """Every proc:correlationKey parameter it names, by IRI (a process has at most one)."""
        return tuple(self._objects(PROC.correlationKey))

    @property
    def correlation_parameter(self) -> URIRef | None:
        """Its proc:correlationKey parameter, or None; several raise
        ``ResolutionError(process, proc:correlationKey)``."""
        param = self._optional_value(PROC.correlationKey)
        return param if isinstance(param, URIRef) else None

    @property
    def triggering_operations(self) -> Many[Operation]:
        """The operations the events that seam:trigger it seam:submitsTo, by
        IRI (a UI-started process has one; errors name the process and seam:triggers)."""
        from .operations import Operation

        ds = self.views.ds
        iris = self.views.iris(op for ev in self._subjects(SEAM.triggers) for op in ds.objects(ev, SEAM.submitsTo))
        return self._many(Operation, iris, SEAM.triggers)

    @property
    def invoked_operations(self) -> Many[Operation]:
        """The operations it, or an element of a BPMN model it is
        seam:detailedBy, seam:invokes, by IRI."""
        from .operations import Operation

        prefixes = tuple(f"{m}#" for m in self._objects(SEAM.detailedBy))
        ds = self.views.ds
        iris = self.views.iris(
            op for s, op in ds.subject_objects(SEAM.invokes) if s == self.iri or str(s).startswith(prefixes)
        )
        return self._many(Operation, iris, SEAM.invokes)

    def element_iri(self, bpmn_id: str) -> URIRef:
        """``<bpmn_model>#<bpmn_id>``."""
        return URIRef(f"{self.bpmn_model}#{bpmn_id}")

    def elements(self) -> Many[ProcessElement]:
        """Every graph subject under ``<bpmn_model>#``, by IRI."""
        prefix = f"{self.bpmn_model}#"
        views = self.views

        def build() -> Many[ProcessElement]:
            iris = [s for s in views.iris(views.ds.subjects()) if str(s).startswith(prefix)]
            return views.many(ProcessElement, iris, self.iri, SEAM.detailedBy)

        return views.view(f"process-elements:{self.iri}", build)

    def nodes(self) -> Many[FlowNode]:
        """Every flow node of every bpmn:process in ``bpmn_path``, in flow order
        (processes in document order, then each process's flow order)."""
        views = self.views

        def build() -> Many[FlowNode]:
            ds = views.ds
            found: list[FlowNode] = []
            for bp in bpmn_processes(views, self.bpmn_path):
                for node in bp.nodes:
                    iri = self.element_iri(node.id)
                    lifted = any((iri, RDF.type, t) in ds for t in ELEMENT_TYPES)
                    element = views.intern(ProcessElement, iri) if lifted else None
                    found.append(FlowNode(iri, node, self, element))
            return Many(found, self.iri, SEAM.detailedBy, views.model.curie)

        return views.view(f"process-nodes:{self.iri}", build)

    def tasks(self) -> Many[FlowNode]:
        """The task nodes (``is_task``), in flow order."""
        return self.views.view(f"process-tasks:{self.iri}", lambda: self.nodes().where(lambda n: n.node.is_task))

    def gateways(self) -> Many[FlowNode]:
        """The gateway nodes (``is_gateway``), in flow order."""
        return self.views.view(f"process-gateways:{self.iri}", lambda: self.nodes().where(lambda n: n.node.is_gateway))

    def lanes(self) -> tuple[Lane, ...]:
        """Every lane of every bpmn:process in ``bpmn_path``, in document order."""
        return self.views.view(
            f"process-lanes:{self.iri}",
            lambda: tuple(lane for bp in bpmn_processes(self.views, self.bpmn_path) for lane in bp.lanes),
        )

    def error_boundaries(self) -> Many[ErrorBoundary]:
        """Each error boundary event of ``bpmn_path`` attached to a task that
        seam:invokes an operation, joined to the error it catches (ADR-0013),
        in flow order. Built once.

        The graph and the XML must agree, else ``ResolutionError`` naming the
        boundary's IRI: ``bpmn:errorEventDefinition`` for a catch-all (no
        ``errorRef``) on an invoking task; ``bpmn:errorRef`` /
        ``bpmn:errorCode`` when the ref names no ``bpmn:error`` or it has no
        code; ``seam:catches`` when the boundary is not lifted, catches no
        status or several, catches a status that is not an error of the
        invoked operation or whose ``comm:errorCode`` differs from the XML's,
        is lifted on a task that invokes nothing, or repeats another
        boundary's code on the same task. A lifted proc:ErrorBoundaryEvent
        with no error boundary event in the XML is ``seam:catches`` too."""
        return self.views.view(f"process-error-boundaries:{self.iri}", self._error_boundaries)

    def _error_boundaries(self) -> Many[ErrorBoundary]:
        views = self.views
        nodes = self.nodes()
        parsed = {bp.id: bp for bp in bpmn_processes(views, self.bpmn_path)}
        found: list[ErrorBoundary] = []
        for fn in nodes:
            node = fn.node
            if not node.is_error_boundary or node.attached_to is None:
                continue
            task = next(n for n in nodes if n.node.process_id == node.process_id and n.bpmn_id == node.attached_to)
            lifted = fn.element is not None and PROC.ErrorBoundaryEvent in fn.element.types
            op = task.invokes
            if op is None:
                if lifted:
                    raise ResolutionError(
                        fn.iri, SEAM.catches, f"attached to {task.iri}, which seam:invokes no operation"
                    )
                continue  # a plain BPMN boundary: no seam, not lifted
            if node.error_ref is None:
                raise ResolutionError(
                    fn.iri,
                    "bpmn:errorEventDefinition",
                    f"a catch-all error boundary on {task.iri}, which seam:invokes {op.iri}, "
                    "would catch codes the operation never declared; give it an errorRef",
                )
            error = parsed[node.process_id].error(node.error_ref)
            if error is None:
                raise ResolutionError(
                    fn.iri, "bpmn:errorRef", f"{node.error_ref!r} names no bpmn:error in {self.bpmn_path.name}"
                )
            if not error.code:
                raise ResolutionError(fn.iri, "bpmn:errorCode", f"bpmn:error {error.id!r} has no errorCode")
            declared = op.errors.where(lambda s, code=error.code: s.error_code == code)
            if not lifted:
                said = f"declares it as {declared[0].iri}" if declared else "declares no hydra:possibleStatus with it"
                raise ResolutionError(
                    fn.iri,
                    SEAM.catches,
                    f"catches errorCode {error.code!r} of {op.iri}, which {said}, but is not a "
                    "proc:ErrorBoundaryEvent that seam:catches it",
                )
            status = fn.catches  # ResolutionError(boundary, seam:catches) when it catches several
            if status is None:
                raise ResolutionError(fn.iri, SEAM.catches, "a proc:ErrorBoundaryEvent catches exactly one error")
            if status.iri not in op.errors.iris():
                raise ResolutionError(
                    fn.iri,
                    SEAM.catches,
                    f"{status.iri} is not an error (a hydra:possibleStatus with a comm:errorCode) of {op.iri}, "
                    f"which {task.iri} seam:invokes",
                )
            if status.error_code != error.code:
                raise ResolutionError(
                    fn.iri,
                    SEAM.catches,
                    f"bpmn:error {error.id!r} has errorCode {error.code!r}, "
                    f"but {status.iri} has comm:errorCode {status.error_code!r}",
                )
            twin = next((b for b in found if b.task.iri == task.iri and b.code == error.code), None)
            if twin is not None:
                raise ResolutionError(fn.iri, SEAM.catches, f"{twin.iri} already catches {error.code!r} on {task.iri}")
            found.append(ErrorBoundary(fn.iri, fn, task, op, status, error.code))
        boundary_iris = {b.iri for b in found}
        for el in self.elements():
            if PROC.ErrorBoundaryEvent in el.types and el.iri not in boundary_iris:
                raise ResolutionError(
                    el.iri,
                    SEAM.catches,
                    f"no bpmn:boundaryEvent with an errorEventDefinition has id {el.bpmn_id!r} "
                    f"in {self.bpmn_path.name}",
                )
        return Many(found, self.iri, SEAM.catches, views.model.curie)

    @property
    def channel_starts(self) -> Many[MessageStart]:
        """Each proc:MessageCatchEvent of its BPMN model that seam:subscribesTo a
        comm:Channel and is a bpmn:startEvent of its payload (the rule of
        ``ModelGraph.start_channel``), by (event, channel)."""
        from .operations import Channel

        views = self.views
        ds = views.ds
        starts = _start_ids(views, self.bpmn_path)
        found: list[MessageStart] = []
        for el in self.elements():
            if (el.iri, RDF.type, PROC.MessageCatchEvent) not in ds or el.bpmn_id not in starts:
                continue
            for ch in el._objects(SEAM.subscribesTo):  # pyright: ignore[reportPrivateUsage]
                if (ch, RDF.type, COMM.Channel) in ds:
                    found.append(MessageStart(el.iri, el, views.intern(Channel, ch)))
        found.sort(key=lambda s: (str(s.event.iri), str(s.channel.iri)))
        return Many(found, self.iri, SEAM.subscribesTo, views.model.curie)


@dataclass(frozen=True)
class MessageStart:
    """A message start event and the channel it seam:subscribesTo; ``iri`` is the event's."""

    iri: URIRef
    event: ProcessElement
    channel: Channel


@dataclass(frozen=True)
class ErrorBoundary:
    """A lifted error boundary event (ADR-0013); ``iri`` is the boundary's.

    ``node`` is its flow node, ``task`` the flow node it is attached to,
    ``operation`` what that task seam:invokes, ``status`` the error it
    seam:catches and ``code`` the errorCode of its ``bpmn:error`` (equal to
    the status's comm:errorCode).
    """

    iri: URIRef
    node: FlowNode
    task: FlowNode
    operation: Operation
    status: Status
    code: str


@dataclass(frozen=True, eq=False)
class FlowNode:
    """A flow node of a process's BPMN file, joined to the graph.

    ``iri`` is ``Process.element_iri(bpmn_id)`` whether or not the graph
    states it; ``element`` is the interned ``ProcessElement`` when the graph
    types that IRI as a process element, else None (gateways, plain start
    and end events). The graph edges pass through ``element``: None, or an
    empty ``Many`` naming the same subject and predicate, when unlifted.
    """

    iri: URIRef
    node: BpmnNode
    process: Process
    element: ProcessElement | None

    @property
    def bpmn_id(self) -> str:
        return self.node.id

    @property
    def tag(self) -> str:
        """The BPMN local name (``userTask``, ``exclusiveGateway``, ``startEvent``, ...)."""
        return self.node.tag

    @property
    def name(self) -> str | None:
        return self.node.name

    @property
    def lane(self) -> Lane | None:
        """The innermost lane holding the node, or None."""
        lane_id = self.node.lane_id
        return next((lane for lane in self.process.lanes() if lane.id == lane_id), None)

    @property
    def incoming(self) -> tuple[SequenceFlow, ...]:
        return self.node.incoming

    @property
    def outgoing(self) -> tuple[SequenceFlow, ...]:
        return self.node.outgoing

    @property
    def paths(self) -> tuple[SequenceFlow, ...]:
        """The outgoing flows (the paths out of a gateway), with name, target and condition."""
        return self.node.paths

    @property
    def kind(self) -> str | None:
        """``element.kind``, or None when unlifted."""
        return None if self.element is None else self.element.kind

    @property
    def invokes(self) -> Operation | None:
        return None if self.element is None else self.element.invokes

    @property
    def decided_by(self) -> Decision | None:
        return None if self.element is None else self.element.decided_by

    @property
    def completed_on(self) -> Component | None:
        return None if self.element is None else self.element.completed_on

    @property
    def fires(self) -> Transition | None:
        return None if self.element is None else self.element.fires

    @property
    def reads(self) -> Many[Shape]:
        return self._empty(SEAM.reads) if self.element is None else self.element.reads

    @property
    def writes(self) -> Many[Shape]:
        return self._empty(SEAM.writes) if self.element is None else self.element.writes

    @property
    def publishes_to(self) -> Many[Channel]:
        return self._empty(SEAM.publishesTo) if self.element is None else self.element.publishes_to

    @property
    def subscribes_to(self) -> Many[Channel]:
        return self._empty(SEAM.subscribesTo) if self.element is None else self.element.subscribes_to

    @property
    def catches(self) -> Status | None:
        return None if self.element is None else self.element.catches

    @property
    def starts_from(self) -> Channel | None:
        """The channel of ``Process.channel_starts`` whose event is this node, or None."""
        starts = [s.channel for s in self.process.channel_starts if s.event.iri == self.iri]
        return optional(Many(starts, self.iri, SEAM.subscribesTo, self.process.views.model.curie))

    def _empty(self, predicate: URIRef) -> Many[Any]:
        return Many((), self.iri, predicate, self.process.views.model.curie)


@element_type(*ELEMENT_TYPES)
@dataclass(frozen=True, eq=False)
class ProcessElement(Element):
    """A task or event of a BPMN model, as the graph types it."""

    @property
    def bpmn_id(self) -> str:
        """The element's id in its BPMN file (the IRI fragment)."""
        return str(self.iri).rsplit("#", 1)[-1]

    @property
    def bpmn_model(self) -> URIRef:
        """The BPMN seam:Model its IRI sits under."""
        return URIRef(str(self.iri).rsplit("#", 1)[0])

    @property
    def kind(self) -> str | None:
        """The local name of its proc: class (``UserTask``, ``ServiceTask``, ...)."""
        found = sorted(local_name(t) for t in self.types)
        return found[0] if found else None

    @property
    def types(self) -> tuple[URIRef, ...]:
        """The ``ELEMENT_TYPES`` it has, in that order."""
        ds = self.views.ds
        return tuple(t for t in ELEMENT_TYPES if (self.iri, RDF.type, t) in ds)

    @property
    def process(self) -> Process | None:
        """The process seam:detailedBy its BPMN model."""
        views = self.views
        iris = [
            p
            for p in views.iris(views.ds.subjects(SEAM.detailedBy, self.bpmn_model))
            if (p, RDF.type, PROC.Process) in views.ds
        ]
        return optional(views.many(Process, iris, self.bpmn_model, SEAM.detailedBy))

    @property
    def invokes(self) -> Operation | None:
        from .operations import Operation

        return optional(self._many(Operation, self._objects(SEAM.invokes), SEAM.invokes))

    @property
    def reads(self) -> Many[Shape]:
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.reads), SEAM.reads)

    @property
    def writes(self) -> Many[Shape]:
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.writes), SEAM.writes)

    @property
    def fires(self) -> Transition | None:
        """The lifecycle transition it seam:fires."""
        from .lifecycles import Transition

        return optional(self._many(Transition, self._objects(SEAM.fires), SEAM.fires))

    @property
    def decided_by(self) -> Decision | None:
        """The decision it is seam:decidedBy (business-rule tasks)."""
        from .decisions import Decision

        return optional(self._many(Decision, self._objects(SEAM.decidedBy), SEAM.decidedBy))

    @property
    def completed_on(self) -> Component | None:
        """The form it is seam:completedOn (user tasks, ADR-0009)."""
        from .interfaces import Component

        return optional(self._many(Component, self._objects(SEAM.completedOn), SEAM.completedOn))

    @property
    def catches(self) -> Status | None:
        """The error it seam:catches (a proc:ErrorBoundaryEvent, ADR-0013)."""
        from .operations import Status

        return optional(self._many(Status, self._objects(SEAM.catches), SEAM.catches))

    @property
    def publishes_to(self) -> Many[Channel]:
        from .operations import Channel

        return self._many(Channel, self._objects(SEAM.publishesTo), SEAM.publishesTo)

    @property
    def subscribes_to(self) -> Many[Channel]:
        from .operations import Channel

        return self._many(Channel, self._objects(SEAM.subscribesTo), SEAM.subscribesTo)


class Processes(Many[Process]):
    """Every proc:Process in the model, by IRI."""

    def all(self) -> Many[Process]:
        return Many(self, self.subject, self.predicate, self._curie)

    def for_bpmn_process(self, pid: str) -> Many[Process]:
        """The processes whose BPMN file declares a bpmn:process with id ``pid``
        (callers ``.only()``; errors name the model and seam:detailedBy)."""
        return Many([p for p in self if pid in p.bpmn_process_ids], self.subject, SEAM.detailedBy, self._curie)

    def element(self, bpmn_id: str) -> Many[ProcessElement]:
        """The process elements with this BPMN id, across every process
        (callers ``.only()``; an id in two BPMN models makes that raise)."""
        items = [e for p in self for e in p.elements() if e.bpmn_id == bpmn_id]
        return sorted_many(items, self.subject, SEAM.detailedBy, self._curie)
