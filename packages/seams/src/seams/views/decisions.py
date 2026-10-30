"""``model.decisions``: DMN decisions and how a business-rule task binds them.

A ``Decision`` here is the binding: the DMN decision id, the file it lives
in and the input and output variables, with the same semantics and sort as
``ModelGraph.decision_binding``. The decision table itself (hit policy and
rules) is read in S04 as ``Decision.table``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rdflib import URIRef

from ..errors import ResolutionError
from ..graph import InputBinding, OutputBinding, dmn_decision_ids, dmn_input_types
from ..namespaces import DEC, SEAM, local_name
from ._base import Element, Many, Views, element_type

if TYPE_CHECKING:
    from .processes import ProcessElement
    from .shapes import Shape


@element_type(DEC.Decision)
@dataclass(frozen=True, eq=False)
class Decision(Element):
    """A dec:Decision bound to a DMN decision by dec:payloadElement."""

    @property
    def dmn_model(self) -> URIRef:
        """The DMN seam:Model it is seam:inModel."""
        if self.model is None:
            raise ResolutionError(self.iri, SEAM.inModel, "decision names no DMN model")
        return self.model

    @property
    def dmn_path(self) -> Path:
        """The DMN file its model seam:renderPayload names."""
        return self.views.model.payload_path(self.dmn_model)

    @property
    def decision_id(self) -> str:
        """The dec:payloadElement id; it must be a decision id in the DMN file."""
        element = self._value(DEC.payloadElement)
        if element is None:
            raise ResolutionError(self.iri, DEC.payloadElement, "decision names no DMN decision id")
        ids = dmn_decision_ids(self.dmn_path)
        if str(element) not in ids:
            raise ResolutionError(
                self.iri,
                DEC.payloadElement,
                f"{str(element)!r} not among DMN decision ids {ids} in {self.dmn_path.name}",
            )
        return str(element)

    @property
    def inputs(self) -> tuple[InputBinding, ...]:
        """Each dec:input (variable, fromPath, measure and the DMN typeRef), by variable."""
        ds = self.views.ds
        types = dmn_input_types(self.dmn_path, self.decision_id)
        out: list[InputBinding] = []
        for node in ds.objects(self.iri, DEC.input):
            path, variable = ds.value(node, DEC.fromPath), ds.value(node, DEC.variable)
            if not isinstance(path, URIRef) or variable is None:
                raise ResolutionError(self.iri, DEC.input, "input needs dec:variable and an IRI dec:fromPath")
            measure = ds.value(node, DEC.measure)
            out.append(
                InputBinding(
                    variable=str(variable),
                    from_path=local_name(path),
                    from_path_iri=path,
                    measure=measure if isinstance(measure, URIRef) else None,
                    type_ref=types.get(str(variable)),
                )
            )
        return tuple(sorted(out, key=lambda b: b.variable))

    @property
    def outputs(self) -> tuple[OutputBinding, ...]:
        """Each dec:output (DMN variable -> process variable), by variable."""
        ds = self.views.ds
        out: list[OutputBinding] = []
        for node in ds.objects(self.iri, DEC.output):
            variable, process_variable = ds.value(node, DEC.variable), ds.value(node, DEC.processVariable)
            if variable is None or process_variable is None:
                raise ResolutionError(self.iri, DEC.output, "output needs dec:variable and dec:processVariable")
            out.append(OutputBinding(str(variable), str(process_variable)))
        return tuple(sorted(out, key=lambda b: b.variable))

    @property
    def reads(self) -> Many[Shape]:
        from .shapes import Shape

        return self._many(Shape, self._objects(SEAM.reads), SEAM.reads)

    @property
    def decides_for(self) -> Many[ProcessElement]:
        """The business-rule tasks seam:decidedBy it."""
        from .processes import ProcessElement

        return self._many(ProcessElement, self._subjects(SEAM.decidedBy), SEAM.decidedBy)


def all_decisions(views: Views) -> Many[Decision]:
    """Every decision a task is seam:decidedBy or that names a dec:payloadElement, by IRI."""
    ds = views.ds
    iris = {*views.iris(ds.objects(None, SEAM.decidedBy)), *views.iris(ds.subjects(DEC.payloadElement, None))}
    return views.many(Decision, iris, views.model.subject, DEC.payloadElement)
