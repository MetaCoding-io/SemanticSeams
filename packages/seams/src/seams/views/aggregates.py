"""``model.aggregates``: the aggregates that name the shapes they commit together (ADR-0035)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..namespaces import SEAM
from ._base import Element, Many, optional

if TYPE_CHECKING:
    from .lifecycles import Lifecycle
    from .shapes import Shape


@dataclass(frozen=True, eq=False)
class Aggregate(Element):
    """An aggregate that declares a transaction boundary: the owl:Class or
    sh:NodeShape (ADR-0033) whose seam:aggregateMember triples name the
    shapes it commits together. It is not registered for an rdf:type, since
    it is a class or a shape seen through this one fact."""

    @property
    def members(self) -> Many[Shape]:
        """Its seam:aggregateMember shapes, by IRI: exactly the listed ones,
        never derived from sh:targetClass."""
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.aggregateMember), SEAM.aggregateMember)

    @property
    def lifecycle(self) -> Lifecycle | None:
        """The state machine it names with seam:lifecycle; more than one raises
        ``ResolutionError(aggregate, seam:lifecycle)``."""
        from .lifecycles import Lifecycle

        return optional(self._many(Lifecycle, self._objects(SEAM.lifecycle), SEAM.lifecycle))
