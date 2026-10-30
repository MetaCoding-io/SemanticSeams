"""``model.lifecycles``: state machines, their states and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import URIRef

from ..errors import ResolutionError
from ..namespaces import SEAM, STATE
from ._base import Element, Many, element_type, optional, sorted_many

if TYPE_CHECKING:
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
        """The shape that names it with seam:lifecycle."""
        from .shapes import Shape

        return optional(self._many(Shape, self._subjects(SEAM.lifecycle), SEAM.lifecycle))


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
    def to_state(self) -> State:
        return self._state(STATE.to)

    @property
    def trigger(self) -> str | None:
        return self._text(STATE.trigger)

    @property
    def lifecycle(self) -> Lifecycle | None:
        return optional(self._many(Lifecycle, self._subjects(STATE.hasTransition), STATE.hasTransition))

    @property
    def fired_by(self) -> Many[Element]:
        """The elements (process tasks) that seam:fire it."""
        return self._related(self._subjects(SEAM.fires), SEAM.fires)


class Lifecycles(Many[Lifecycle]):
    """Every state machine in the model, by IRI."""

    def transitions(self) -> Many[Transition]:
        """Every transition of every lifecycle, by IRI."""
        items = [t for lc in self for t in lc.transitions()]
        return sorted_many(items, self.subject, STATE.hasTransition, self._curie)
