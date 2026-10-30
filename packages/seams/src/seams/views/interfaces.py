"""``model.interfaces``: IFML interaction models, pages, components and events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import RDF, URIRef
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import IFML, SEAM, local_name
from ._base import E, Element, Many, Views, element_type, one_value, optional

if TYPE_CHECKING:
    from .architecture import Container
    from .lifecycles import State
    from .operations import Operation
    from .policies import Policy
    from .processes import Process, ProcessElement
    from .shapes import Shape

#: The IFML classes a page's parts are typed with; ``Component.kind`` is one of their local names.
COMPONENT_TYPES = (IFML.ViewComponent, IFML.Form, IFML.Details, IFML.List)

#: The concrete component classes a generator renders, in the order
#: ``Component.types`` lists them (a rendered component has exactly one).
RENDERED_TYPES = (IFML.List, IFML.Details, IFML.Form)

#: The IFML flow classes; ``Flow.kind`` is one of them.
FLOW_TYPES = (IFML.NavigationFlow, IFML.DataFlow)


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
    def title(self) -> str | None:
        """The ifml:title shown in the browser tab, or None."""
        return self._text(IFML.title)

    @property
    def is_landmark(self) -> bool:
        """True when it is ifml:isLandmark true (the app's entry page)."""
        return self._flag(IFML.isLandmark)

    @property
    def is_xor(self) -> bool:
        """True when it is ifml:isXOR true (its children are mutually exclusive)."""
        return self._flag(IFML.isXOR)

    @property
    def is_default(self) -> bool:
        """True when it is ifml:isDefault true (shown first among XOR siblings)."""
        return self._flag(IFML.isDefault)

    def pages(self) -> Many[Page]:
        """The nested ifml:ViewContainers it ifml:contains, by IRI."""
        views = self.views
        iris = [i for i in self._objects(IFML.contains) if (i, RDF.type, IFML.ViewContainer) in views.ds]
        return self._many(Page, iris, IFML.contains)

    @property
    def parents(self) -> Many[Page]:
        """The ifml:ViewContainers that ifml:contain it, by IRI (empty for a top-level page)."""
        views = self.views
        iris = [i for i in self._subjects(IFML.contains) if (i, RDF.type, IFML.ViewContainer) in views.ds]
        return self._many(Page, iris, IFML.contains)

    @property
    def visible_when(self) -> Many[State]:
        """The lifecycle states it renders in (seam:visibleWhen); empty means always."""
        from .lifecycles import State

        return self._many(State, self._objects(SEAM.visibleWhen), SEAM.visibleWhen)

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
            value = c.order
            return (value if value is not None else 1 << 30, str(c.iri))

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
    def types(self) -> tuple[URIRef, ...]:
        """The concrete IFML component classes it has, in ``RENDERED_TYPES``
        order (ifml:List, ifml:Details, ifml:Form); a renderable component has one."""
        ds = self.views.ds
        return tuple(t for t in RENDERED_TYPES if (self.iri, RDF.type, t) in ds)

    @property
    def order(self) -> int | None:
        """Its ifml:order on the page, or None. Several values, or one that
        is not an integer, raise ``ResolutionError(component, ifml:order)``."""
        return self._int(IFML.order)

    @property
    def page(self) -> Page | None:
        """The ifml:ViewContainer that ifml:contains it."""
        return optional(self.screens)

    @property
    def screens(self) -> Many[Page]:
        """Every ifml:ViewContainer that ifml:contains it, by IRI (a task form's screens)."""
        views = self.views
        iris = [i for i in self._subjects(IFML.contains) if (i, RDF.type, IFML.ViewContainer) in views.ds]
        return self._many(Page, iris, IFML.contains)

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

    @property
    def parameter_bindings(self) -> tuple[Parameter, ...]:
        """Each ifml:hasParameter parameter with its label and the sh:path it
        is ifml:boundTo (None when unbound), by parameter IRI. A parameter
        bound to several paths raises ``ResolutionError(parameter, ifml:boundTo)``."""
        views = self.views
        out: list[Parameter] = []
        for p in self._objects(IFML.hasParameter):
            bound = sorted(set(views.ds.objects(p, IFML.boundTo)), key=str)
            if len(bound) > 1:
                raise ResolutionError(p, IFML.boundTo, f"expected at most one, found {', '.join(map(str, bound))}")
            target = bound[0] if bound and isinstance(bound[0], URIRef) else None
            out.append(Parameter(p, views.model.label(p), target))
        return tuple(out)

    @property
    def data_flows(self) -> Many[Flow]:
        """The ifml:DataFlows whose ifml:source it is, by IRI."""
        return _flows_from(self).where(lambda f: f.kind == IFML.DataFlow)

    @property
    def rendered_by(self) -> Many[Operation]:
        """The operations that seam:rendersComponent it (UI fragments), by IRI."""
        from .operations import Operation

        return self._many(Operation, self._subjects(SEAM.rendersComponent), SEAM.rendersComponent)

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
    def owners(self) -> Many[Element]:
        """Every element that ifml:hasEvent it, typed as the graph says (a
        component, a page, or an action such as a process), by IRI."""
        return self._related(self._subjects(IFML.hasEvent), IFML.hasEvent)

    @property
    def triggers(self) -> Process | None:
        """The process it seam:triggers (starts)."""
        return optional(self.triggers_all)

    @property
    def triggers_all(self) -> Many[Process]:
        """Every process it seam:triggers, by IRI."""
        from .processes import Process

        return self._many(Process, self._objects(SEAM.triggers), SEAM.triggers)

    @property
    def governed_by(self) -> Many[Policy]:
        """The odrl:Policies it is seam:governedBy, by IRI."""
        from .policies import Policy

        return self._many(Policy, self._objects(SEAM.governedBy), SEAM.governedBy)

    @property
    def flows(self) -> Many[Flow]:
        """The IFML flows (navigation and data) whose ifml:source it is, by
        IRI; ``.where(lambda f: f.kind == IFML.NavigationFlow).only()`` names
        (event, ifml:source) when it has none or several."""
        return _flows_from(self)

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


@dataclass(frozen=True)
class Parameter:
    """An ifml:Parameter of a component: its IRI, label and the sh:path it is
    ifml:boundTo (None for a parameter only a flow or route binds)."""

    iri: URIRef
    label: str
    bound_to: URIRef | None


@dataclass(frozen=True)
class ParameterBinding:
    """One ifml:ParameterBinding of a data flow: the ifml:sourceParameter
    whose value fills the ifml:targetParameter."""

    source: URIRef
    target: URIRef


@element_type(*FLOW_TYPES)
@dataclass(frozen=True, eq=False)
class Flow(Element):
    """An ifml:NavigationFlow or ifml:DataFlow."""

    @property
    def kind(self) -> URIRef | None:
        """ifml:NavigationFlow or ifml:DataFlow (the first in ``FLOW_TYPES`` it has)."""
        ds = self.views.ds
        return next((t for t in FLOW_TYPES if (self.iri, RDF.type, t) in ds), None)

    @property
    def sources(self) -> Many[Element]:
        """Its ifml:source elements (an event or a component), by IRI."""
        return self._related(self._objects(IFML.source), IFML.source)

    @property
    def source(self) -> Element:
        """The single ifml:source; ``ResolutionError(flow, ifml:source)`` otherwise."""
        return self.views.resolve(_iri(self._one_value(IFML.source), self.iri, IFML.source))

    @property
    def targets(self) -> Many[Element]:
        """Its ifml:target elements (a page or a component), by IRI."""
        return self._related(self._objects(IFML.target), IFML.target)

    @property
    def target(self) -> Element:
        """The single ifml:target; ``ResolutionError(flow, ifml:target)`` otherwise."""
        return self.views.resolve(_iri(self._one_value(IFML.target), self.iri, IFML.target))

    @property
    def swap(self) -> URIRef:
        """Its ifml:swap strategy (ifml:Replace, ifml:Append, ifml:Prepend).
        None or several raise ``ResolutionError(flow, ifml:swap)``."""
        value = self._one_value(IFML.swap)
        if not isinstance(value, URIRef):
            raise ResolutionError(self.iri, IFML.swap, f"expected an IRI, found {value!r}")
        return value

    @property
    def binds(self) -> tuple[ParameterBinding, ...]:
        """Its ifml:binds parameter bindings, sorted by (source, target). A
        binding without exactly one IRI ifml:sourceParameter and
        ifml:targetParameter raises ``ResolutionError`` naming the binding node."""
        ds = self.views.ds
        out: list[ParameterBinding] = []
        for node in ds.objects(self.iri, IFML.binds):
            source, target = (
                _iri(one_value(ds, node, p), node, p) for p in (IFML.sourceParameter, IFML.targetParameter)
            )
            out.append(ParameterBinding(source, target))
        return tuple(sorted(set(out), key=lambda b: (str(b.source), str(b.target))))


def _iri(value: Node, subject: Node, predicate: URIRef) -> URIRef:
    if not isinstance(value, URIRef):
        raise ResolutionError(subject, predicate, f"expected an IRI, found {value!r}")
    return value


def _flows_from(element: Element) -> Many[Flow]:
    ds = element.views.ds
    iris = [
        f
        for f in element.views.iris(ds.subjects(IFML.source, element.iri))
        if any((f, RDF.type, t) in ds for t in FLOW_TYPES)
    ]
    return element.views.many(Flow, iris, element.iri, IFML.source)


class Interfaces:
    """The IFML layer across every interaction model in the graph."""

    def __init__(self, views: Views) -> None:
        self._views = views

    def models(self) -> Many[InteractionModel]:
        return self._views.all(InteractionModel, IFML.InteractionModel)

    def pages(self) -> Many[Page]:
        """Every ifml:ViewContainer, by IRI."""
        return self._views.all(Page, IFML.ViewContainer)

    def components(self) -> Many[Component]:
        """Every element typed with one of ``COMPONENT_TYPES``, by IRI."""
        return self._all_of(Component, COMPONENT_TYPES)

    def events(self) -> Many[Event]:
        """Every ifml:Event, by IRI."""
        return self._views.all(Event, IFML.Event)

    def flows(self) -> Many[Flow]:
        """Every ifml:NavigationFlow and ifml:DataFlow, by IRI."""
        return self._all_of(Flow, FLOW_TYPES)

    def _all_of(self, cls: type[E], rdf_types: tuple[URIRef, ...]) -> Many[E]:
        views = self._views
        iris = [i for t in rdf_types for i in views.typed(t)]
        return views.many(cls, iris, views.model.subject, RDF.type)

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
