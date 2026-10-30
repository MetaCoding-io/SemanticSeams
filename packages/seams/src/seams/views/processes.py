"""``model.processes``: proc:Processes, their BPMN payloads and process elements.

A process element's IRI is ``<BPMN model IRI>#<bpmn id>``: the model the
process is ``seam:detailedBy`` plus the element's id in that model's BPMN
file. Several BPMN models in one graph are the normal case, so an id is
only unique within one model (``Processes.element`` says when it is not).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rdflib import RDF, URIRef

from .._xml import elements, localname
from ..errors import ResolutionError
from ..graph import bpmn_start_event_ids
from ..namespaces import COMM, PROC, SEAM, local_name
from ._base import Element, Many, Views, element_type, optional, sorted_many

if TYPE_CHECKING:
    from .architecture import Container
    from .decisions import Decision
    from .interfaces import Component, Event
    from .lifecycles import Transition
    from .operations import Channel, Operation
    from .shapes import Shape

#: The proc: classes a process element is typed with; ``ProcessElement.kind`` is one of their local names.
ELEMENT_TYPES = (
    PROC.Task,
    PROC.ServiceTask,
    PROC.UserTask,
    PROC.BusinessRuleTask,
    PROC.MessageCatchEvent,
    PROC.MessageThrowEvent,
)


def bpmn_process_ids(views: Views, path: Path) -> tuple[str, ...]:
    """ids of every bpmn:process in the BPMN file, in document order (read once per registry)."""

    def read() -> tuple[str, ...]:
        return tuple(cast(str, el.get("id")) for el in elements(path) if localname(el.tag) == "process")

    return views.view(f"bpmn-process-ids:{path}", read)


def _start_ids(views: Views, path: Path) -> set[str]:
    return views.view(f"bpmn-start-ids:{path}", lambda: bpmn_start_event_ids(path))


@element_type(PROC.Process)
@dataclass(frozen=True, eq=False)
class Process(Element):
    """A proc:Process."""

    @property
    def bpmn_model(self) -> URIRef:
        """The BPMN seam:Model it is seam:detailedBy (exactly one)."""
        found = self._objects(SEAM.detailedBy)
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
        types = set(self.views.ds.objects(self.iri, RDF.type))
        found = sorted(local_name(t) for t in ELEMENT_TYPES if t in types)
        return found[0] if found else None

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
