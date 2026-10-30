"""``model.shapes``: SHACL node shapes and their fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from rdflib import RDFS, Literal, URIRef
from rdflib.namespace import SH
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import SEAM, local_name
from ._base import Element, Many, element_type, optional, sorted_many

if TYPE_CHECKING:
    from .lifecycles import Lifecycle


@dataclass(frozen=True)
class Field:
    """One sh:property of a shape. ``iri`` is its sh:path (unique within the
    shape), ``name`` the path's local name and ``label`` its sh:name (or
    rdfs:label, else ``name``)."""

    iri: URIRef
    shape: URIRef
    name: str
    label: str
    datatype: URIRef | None
    min_count: int | None
    max_count: int | None
    order: int | None

    @property
    def path(self) -> URIRef:
        return self.iri

    @property
    def required(self) -> bool:
        return (self.min_count or 0) > 0


def _int(value: Node | None) -> int | None:
    return None if value is None else int(cast(Literal, value))


@element_type(SH.NodeShape)
@dataclass(frozen=True, eq=False)
class Shape(Element):
    """An sh:NodeShape."""

    def fields(self) -> Many[Field]:
        """Its sh:property fields by sh:order (fields without one last), then path IRI."""
        ds = self.views.ds
        out: list[Field] = []
        for node in ds.objects(self.iri, SH.property):
            path = ds.value(node, SH.path)
            if not isinstance(path, URIRef):
                raise ResolutionError(self.iri, SH.path, "sh:property without an IRI sh:path")
            datatype = ds.value(node, SH.datatype)
            label = ds.value(node, SH.name) or ds.value(node, RDFS.label)
            out.append(
                Field(
                    iri=path,
                    shape=self.iri,
                    name=local_name(path),
                    label=local_name(path) if label is None else str(label),
                    datatype=datatype if isinstance(datatype, URIRef) else None,
                    min_count=_int(ds.value(node, SH.minCount)),
                    max_count=_int(ds.value(node, SH.maxCount)),
                    order=_int(ds.value(node, SH.order)),
                )
            )
        return sorted_many(
            out,
            self.iri,
            SH.property,
            self.views.model.curie,
            key=lambda f: (f.order is None, f.order or 0, str(f.iri)),
        )

    @property
    def lifecycle(self) -> Lifecycle | None:
        """The state machine it names with seam:lifecycle."""
        from .lifecycles import Lifecycle

        return optional(self._many(Lifecycle, self._objects(SEAM.lifecycle), SEAM.lifecycle))

    @property
    def read_by(self) -> Many[Element]:
        """The elements that seam:read it."""
        return self._related(self._subjects(SEAM.reads), SEAM.reads)

    @property
    def written_by(self) -> Many[Element]:
        """The elements that seam:write it."""
        return self._related(self._subjects(SEAM.writes), SEAM.writes)
