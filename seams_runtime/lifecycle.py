"""Lifecycle guard for seam:fires transitions (ADR-0007).

A shape's lifecycle is its ``seam:lifecycle`` state machine. Its states are
named by ``rdfs:label``, and those labels are the values a payload's status
field carries. Before a task that ``seam:fires`` a transition runs, the
worker checks that the transition's ``state:from`` label is the entity's
current status. A missing status means the machine's ``state:initial``.
"""

from __future__ import annotations

from .errors import LifecycleViolation, ResolutionError
from .model import STATE, ModelGraph, Transition


class LifecycleGuard:
    def __init__(self, model: ModelGraph):
        self.model = model

    def _transitions(self, shape):
        lifecycle = self.model.lifecycle_for(shape)
        return lifecycle, set(lifecycle.transitions)

    def check(self, shape, current_status, transition) -> Transition:
        """The transition, if it is enabled in ``current_status``; otherwise
        LifecycleViolation naming the transition, current and required state."""
        lifecycle, owned = self._transitions(shape)
        t = self.model.curie(transition)
        if t not in owned:
            raise ResolutionError(lifecycle.iri, STATE.hasTransition, f"{t} is not a transition of this lifecycle")
        tr = self.model._transition(t)
        current = current_status or lifecycle.initial
        if tr.from_state != current:
            raise LifecycleViolation(self.model.curie(shape), t, current, tr.from_state)
        return tr

    def apply(self, shape, current_status, transition) -> str:
        """Check the transition and return its state:to label."""
        return self.check(shape, current_status, transition).to_state

    def on_error(self, shape, current_status, trigger: str = "error") -> Transition | None:
        """The lifecycle's transition leaving ``current_status`` with this
        state:trigger, or None when the state has no such exit."""
        lifecycle, owned = self._transitions(shape)
        current = current_status or lifecycle.initial
        matches = [tr for tr in self.model.transitions_from(current, trigger) if tr.iri in owned]
        if len(matches) > 1:
            raise ResolutionError(
                lifecycle.iri,
                STATE.trigger,
                f"ambiguous {trigger!r} exits from {current!r}: {[str(m.iri) for m in matches]}",
            )
        return matches[0] if matches else None
