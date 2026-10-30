"""``model.operations`` and ``model.channels``: the communication contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import RDF, URIRef

from ..errors import ResolutionError
from ..graph import PathMapping
from ..namespaces import COMM, HYDRA, IFML, SEAM, local_name
from ._base import Element, Many, element_type, optional

if TYPE_CHECKING:
    from .architecture import Container
    from .interfaces import Component, Event
    from .policies import Policy
    from .shapes import Shape


@dataclass(frozen=True)
class PathTemplate:
    """A comm:path hydra:IriTemplate: the template and its variable
    mappings, sorted by variable (as ``ModelGraph.operation_path``)."""

    template: str
    mappings: tuple[PathMapping, ...]

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(m.variable for m in self.mappings)


@dataclass(frozen=True, eq=False)
class _Endpoint(Element):
    """What operations and channels share: a path, a shape and the containers on each side."""

    @property
    def path(self) -> PathTemplate | None:
        """The comm:path template, or None when the endpoint has none."""
        ds = self.views.ds
        node = self._value(COMM.path)
        if node is None:
            return None
        template = ds.value(node, HYDRA.template)
        if template is None:
            raise ResolutionError(self.iri, HYDRA.template, "comm:path has no hydra:template")
        mappings: list[PathMapping] = []
        for m in ds.objects(node, HYDRA.mapping):
            variable, prop = ds.value(m, HYDRA.variable), ds.value(m, HYDRA.property)
            if variable is None or not isinstance(prop, URIRef):
                raise ResolutionError(self.iri, HYDRA.mapping, "mapping needs hydra:variable and hydra:property")
            mappings.append(PathMapping(str(variable), local_name(prop), prop))
        return PathTemplate(str(template), tuple(sorted(mappings, key=lambda m: m.variable)))

    @property
    def accepts(self) -> Shape | None:
        """The shape it seam:acceptsShape."""
        from .shapes import Shape

        return optional(self._many(Shape, self._objects(SEAM.acceptsShape), SEAM.acceptsShape))

    @property
    def exposed_by(self) -> Many[Container]:
        """The containers that seam:expose it."""
        from .architecture import Container

        return self._many(Container, self._subjects(SEAM.exposes), SEAM.exposes)

    @property
    def consumed_by(self) -> Many[Container]:
        """The containers that seam:consume it."""
        from .architecture import Container

        return self._many(Container, self._subjects(SEAM.consumes), SEAM.consumes)


@element_type(HYDRA.Operation)
@dataclass(frozen=True, eq=False)
class Operation(_Endpoint):
    """A hydra:Operation."""

    @property
    def method(self) -> str | None:
        return self._text(HYDRA.method)

    @property
    def returns(self) -> Shape | None:
        """The shape it seam:returnsShape."""
        from .shapes import Shape

        return optional(self._many(Shape, self._objects(SEAM.returnsShape), SEAM.returnsShape))

    @property
    def media_kind(self) -> URIRef | None:
        """seam:mediaKind, e.g. seam:UIFragment or seam:Data."""
        value = self._value(SEAM.mediaKind)
        return value if isinstance(value, URIRef) else None

    @property
    def renders(self) -> Many[Component]:
        """The components it seam:rendersComponent (a UI fragment names one), by IRI."""
        from .interfaces import Component

        return self._many(Component, self._objects(SEAM.rendersComponent), SEAM.rendersComponent)

    @property
    def submitted_by(self) -> Many[Event]:
        """The ifml:Events that seam:submitsTo it, by IRI."""
        from .interfaces import Event

        views = self.views
        iris = [e for e in self._subjects(SEAM.submitsTo) if (e, RDF.type, IFML.Event) in views.ds]
        return self._many(Event, iris, SEAM.submitsTo)

    @property
    def request_media_type(self) -> str | None:
        return self._text(COMM.requestMediaType)

    @property
    def governed_by(self) -> Many[Policy]:
        """The odrl:Policies it is seam:governedBy."""
        from .policies import Policy

        return self._many(Policy, self._objects(SEAM.governedBy), SEAM.governedBy)


@element_type(COMM.Channel)
@dataclass(frozen=True, eq=False)
class Channel(_Endpoint):
    """A comm:Channel."""

    @property
    def transport(self) -> URIRef | None:
        """comm:transport, e.g. comm:SSE."""
        value = self._value(COMM.transport)
        return value if isinstance(value, URIRef) else None

    @property
    def event_name(self) -> str | None:
        return self._text(COMM.eventName)

    @property
    def published_by(self) -> Many[Element]:
        """The elements that seam:publishesTo it."""
        return self._related(self._subjects(SEAM.publishesTo), SEAM.publishesTo)

    @property
    def subscribed_by(self) -> Many[Element]:
        """The elements that seam:subscribesTo it."""
        return self._related(self._subjects(SEAM.subscribesTo), SEAM.subscribesTo)
