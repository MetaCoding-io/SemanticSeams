"""``model.interfaces``: IFML interaction models, pages, components and events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from rdflib import RDF, Literal, URIRef

from ..errors import ResolutionError
from ..namespaces import IFML, SEAM, local_name
from ._base import Element, Many, Views, element_type, optional

if TYPE_CHECKING:
    from .architecture import Container
    from .lifecycles import State
    from .operations import Operation
    from .processes import Process, ProcessElement
    from .shapes import Shape

#: The IFML classes a page's parts are typed with; ``Component.kind`` is one of their local names.
COMPONENT_TYPES = (IFML.ViewComponent, IFML.Form, IFML.Details, IFML.List)


@element_type(IFML.InteractionModel)
@dataclass(frozen=True, eq=False)
class InteractionModel(Element):
    """An ifml:InteractionModel."""

    def pages(self) -> Many[Page]:
        """The ifml:ViewContainers it ifml:contains, by IRI."""
        views = self.views
        iris = [i for i in self._objects(IFML.contains) if (i, RDF.type, IFML.ViewContainer) in views.ds]
        return self._many(Page, iris, IFML.contains)

    @property
    def presented_by(self) -> Container | None:
        """The container that seam:presents it."""
        from .architecture import Container

        return optional(self._many(Container, self._subjects(SEAM.presents), SEAM.presents))


@element_type(IFML.ViewContainer)
@dataclass(frozen=True, eq=False)
class Page(Element):
    """An ifml:ViewContainer."""

    @property
    def path(self) -> str | None:
        """The ifml:path it is served at, or None."""
        return self._text(IFML.path)

    @property
    def is_landmark(self) -> bool:
        """True when it is ifml:isLandmark true (the app's entry page)."""
        return (self.iri, IFML.isLandmark, Literal(True)) in self.views.ds

    @property
    def interaction_model(self) -> InteractionModel | None:
        """The ifml:InteractionModel that ifml:contains it."""
        views = self.views
        iris = [i for i in self._subjects(IFML.contains) if (i, RDF.type, IFML.InteractionModel) in views.ds]
        return optional(self._many(InteractionModel, iris, IFML.contains))

    def components(self) -> Many[Component]:
        """The parts it ifml:contains, by ifml:order (unordered last), then IRI,
        as ``ModelGraph.page_components``."""
        views = self.views

        def order(c: Component) -> tuple[int, str]:
            value = views.ds.value(c.iri, IFML.order)
            return (int(cast(Literal, value)) if value is not None else 1 << 30, str(c.iri))

        items = sorted((views.intern(Component, i) for i in self._objects(IFML.contains)), key=order)
        return Many(items, self.iri, IFML.contains, views.model.curie)

    @property
    def hosts_task_form(self) -> bool:
        """True when a part it ifml:contains is the form some user task is
        seam:completedOn. Such a page is reached through the task inbox
        (ADR-0009), not served at its path."""
        ds = self.views.ds
        return any((None, SEAM.completedOn, part) in ds for part in ds.objects(self.iri, IFML.contains))


@element_type(*COMPONENT_TYPES)
@dataclass(frozen=True, eq=False)
class Component(Element):
    """A part of a page: an ifml:Form, ifml:Details, ifml:List or other ifml:ViewComponent."""

    @property
    def kind(self) -> str | None:
        """The local name of its IFML component class (``Form``, ``Details``, ...)."""
        types = {t for t in self.views.ds.objects(self.iri, RDF.type)}
        found = sorted(local_name(t) for t in COMPONENT_TYPES if t in types)
        return found[0] if found else None

    @property
    def page(self) -> Page | None:
        """The ifml:ViewContainer that ifml:contains it."""
        views = self.views
        iris = [i for i in self._subjects(IFML.contains) if (i, RDF.type, IFML.ViewContainer) in views.ds]
        return optional(self._many(Page, iris, IFML.contains))

    @property
    def reads(self) -> Many[Shape]:
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.reads), SEAM.reads)

    @property
    def writes(self) -> Many[Shape]:
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.writes), SEAM.writes)

    def parameters(self) -> tuple[str, ...]:
        """The labels of its ifml:hasParameter parameters, sorted."""
        model = self.views.model
        return tuple(sorted({model.label(p) for p in self._objects(IFML.hasParameter)}))

    def events(self) -> Many[Event]:
        """Its ifml:hasEvent events, by IRI."""
        return self._many(Event, self._objects(IFML.hasEvent), IFML.hasEvent)

    @property
    def visible_when(self) -> Many[State]:
        """The lifecycle states it renders in (seam:visibleWhen); empty means always."""
        from .lifecycles import State

        return self._many(State, self._objects(SEAM.visibleWhen), SEAM.visibleWhen)

    @property
    def completes(self) -> Many[ProcessElement]:
        """The user tasks seam:completedOn this form."""
        from .processes import ProcessElement

        return self._many(ProcessElement, self._subjects(SEAM.completedOn), SEAM.completedOn)


@element_type(IFML.Event)
@dataclass(frozen=True, eq=False)
class Event(Element):
    """An ifml:Event."""

    @property
    def trigger(self) -> str | None:
        """ifml:trigger, e.g. ``submit`` or ``click``."""
        return self._text(IFML.trigger)

    @property
    def component(self) -> Component | None:
        """The component that ifml:hasEvent it."""
        return optional(self._many(Component, self._subjects(IFML.hasEvent), IFML.hasEvent))

    @property
    def triggers(self) -> Process | None:
        """The process it seam:triggers (starts)."""
        from .processes import Process

        return optional(self._many(Process, self._objects(SEAM.triggers), SEAM.triggers))

    @property
    def submits_to(self) -> Operation | None:
        """The operation it seam:submitsTo."""
        from .operations import Operation

        return optional(self._many(Operation, self._objects(SEAM.submitsTo), SEAM.submitsTo))

    def _flow_targets(self) -> list[URIRef]:
        ds = self.views.ds
        return self.views.iris(
            target
            for flow in ds.subjects(IFML.source, self.iri)
            if (flow, RDF.type, IFML.NavigationFlow) in ds
            for target in ds.objects(flow, IFML.target)
        )

    @property
    def navigates_to(self) -> Page | None:
        """The page an ifml:NavigationFlow from it targets, if it targets a page."""
        ds = self.views.ds
        pages = [t for t in self._flow_targets() if (t, RDF.type, IFML.ViewContainer) in ds]
        return optional(self._many(Page, pages, IFML.target))

    @property
    def updates(self) -> Many[Component]:
        """The components an ifml:NavigationFlow from it targets (swapped in place)."""
        ds = self.views.ds
        parts = [t for t in self._flow_targets() if (t, RDF.type, IFML.ViewContainer) not in ds]
        return self._many(Component, parts, IFML.target)


class Interfaces:
    """The IFML layer across every interaction model in the graph."""

    def __init__(self, views: Views) -> None:
        self._views = views

    def models(self) -> Many[InteractionModel]:
        return self._views.all(InteractionModel, IFML.InteractionModel)

    def pages(self) -> Many[Page]:
        """Every ifml:ViewContainer, by IRI."""
        return self._views.all(Page, IFML.ViewContainer)

    def landmark(self) -> Page:
        """The single page with ifml:isLandmark true. Zero or several raise
        ``ResolutionError(model, ifml:isLandmark)``."""
        found = self.pages().where(lambda p: p.is_landmark)
        if len(found) != 1:
            raise ResolutionError(
                self._views.model.subject,
                IFML.isLandmark,
                f"expected one ifml:ViewContainer with ifml:isLandmark true, found {[str(p) for p in found.iris()]}",
            )
        return found[0]

    def served_pages(self) -> Many[Page]:
        """The pages the generated app serves at their ifml:path, in this order:
        the landmark first, then by IRI every other page that has an ifml:path
        and does not host a task form (``hosts_task_form``)."""
        landmark = self.landmark()
        rest = self.pages().where(lambda p: p != landmark and p.path is not None and not p.hosts_task_form)
        views = self._views
        return Many([landmark, *rest], views.model.subject, IFML.path, views.model.curie)
