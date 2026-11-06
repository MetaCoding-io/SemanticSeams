"""``model.lifecycles``: state machines, their states and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import OWL, RDF, URIRef
from rdflib.namespace import SH

from ..errors import ResolutionError
from ..namespaces import SEAM, STATE
from ._base import Element, Many, element_type, optional, sorted_many

if TYPE_CHECKING:
    from .processes import ProcessElement
    from .shapes import Shape


@element_type(STATE.StateMachine)
@dataclass(frozen=True, eq=False)
class Lifecycle(Element):
    """A state:StateMachine."""

    @property
    def initial(self) -> State:
        """Its state:initial state."""
        initial = self._objects(STATE.initial)
        return self._many(State, initial, STATE.initial).only()

    def states(self) -> Many[State]:
        """Its state:hasState states (and the initial one), by IRI."""
        iris = {*self._objects(STATE.hasState), *self._objects(STATE.initial)}
        return self._many(State, iris, STATE.hasState)

    def finals(self) -> Many[State]:
        return self._many(State, self._objects(STATE.final), STATE.final)

    def transitions(self) -> Many[Transition]:
        """Its state:hasTransition transitions, by IRI."""
        return self._many(Transition, self._objects(STATE.hasTransition), STATE.hasTransition)

    @property
    def shape(self) -> Shape | None:
        """The shape whose effective lifecycle it is."""
        return optional(self.shapes)

    @property
    def shapes(self) -> Many[Shape]:
        """Every shape whose effective lifecycle it is (ADR-0031 section 2),
        by IRI (normally one): the shapes that name it with seam:lifecycle
        and the sh:NodeShapes whose sh:targetClass names it. A class that
        names it is not itself one of them unless it is also a sh:NodeShape."""
        from .shapes import Shape

        ds = self.views.ds
        named = self._subjects(SEAM.lifecycle)
        direct = [s for s in named if (s, RDF.type, OWL.Class) not in ds or (s, RDF.type, SH.NodeShape) in ds]
        targeting = [s for cls in named for s in ds.subjects(SH.targetClass, cls) if (s, RDF.type, SH.NodeShape) in ds]
        return self._many(Shape, self.views.iris([*direct, *targeting]), SEAM.lifecycle)


@element_type(STATE.State)
@dataclass(frozen=True, eq=False)
class State(Element):
    """A state:State; its ``label`` is the value a shape's status holds."""

    @property
    def lifecycle(self) -> Lifecycle | None:
        return optional(self._many(Lifecycle, self._subjects(STATE.hasState), STATE.hasState))


@element_type(STATE.Transition)
@dataclass(frozen=True, eq=False)
class Transition(Element):
    """A state:Transition."""

    def _state(self, predicate: URIRef) -> State:
        found = self._objects(predicate)
        if not found:
            raise ResolutionError(self.iri, predicate)
        return self._many(State, found, predicate).only()

    @property
    def from_state(self) -> State:
        return self._state(STATE["from"])

    @property
    def from_states(self) -> Many[State]:
        """Its state:from states, by IRI (a well-formed transition has one)."""
        return self._many(State, self._objects(STATE["from"]), STATE["from"])

    @property
    def to_state(self) -> State:
        return self._state(STATE.to)

    @property
    def trigger(self) -> str | None:
        return self._text(STATE.trigger)

    @property
    def lifecycle(self) -> Lifecycle | None:
        return optional(self.lifecycles)

    @property
    def lifecycles(self) -> Many[Lifecycle]:
        """Every state machine that state:hasTransition it, by IRI (normally one)."""
        return self._many(Lifecycle, self._subjects(STATE.hasTransition), STATE.hasTransition)

    @property
    def fired_by(self) -> Many[ProcessElement]:
        """The process tasks that seam:fire it."""
        from .processes import ProcessElement

        return self._many(ProcessElement, self._subjects(SEAM.fires), SEAM.fires)


class Lifecycles(Many[Lifecycle]):
    """Every state machine in the model, by IRI."""

    def transitions(self) -> Many[Transition]:
        """Every transition of every lifecycle, by IRI."""
        items = [t for lc in self for t in lc.transitions()]
        return sorted_many(items, self.subject, STATE.hasTransition, self._curie)
