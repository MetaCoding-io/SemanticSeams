"""``model.policies``: ODRL policies, their permissions and what they govern."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from rdflib import RDF, URIRef
from rdflib.term import Node

from ..graph import Permission
from ..namespaces import ODRL, SEAM
from ._base import Element, Many, element_type


def _opt_iri(node: Node | None) -> URIRef | None:
    return node if isinstance(node, URIRef) else None


@element_type(ODRL.Policy)
@dataclass(frozen=True, eq=False)
class Policy(Element):
    """An odrl:Policy."""

    @property
    def permissions(self) -> tuple[Permission, ...]:
        """Each odrl:permission (target, action, assignee and the assignee's
        rdf:types), sorted by (target, action, assignee) as ``ModelGraph.policy``."""
        ds = self.views.ds
        perms: list[Permission] = []
        for node in ds.objects(self.iri, ODRL.permission):
            assignee = _opt_iri(ds.value(node, ODRL.assignee))
            types = () if assignee is None else tuple(self.views.iris(ds.objects(assignee, RDF.type)))
            perms.append(
                Permission(
                    _opt_iri(ds.value(node, ODRL.target)),
                    _opt_iri(ds.value(node, ODRL.action)),
                    assignee,
                    cast(tuple[URIRef, ...], types),
                )
            )
        perms.sort(key=lambda x: (str(x.target), str(x.action), str(x.assignee)))
        return tuple(perms)

    @property
    def governs(self) -> Many[Element]:
        """The elements seam:governedBy it: ``Operation``, ``ProcessElement``
        (user tasks) or ``Event`` objects, as the graph types them."""
        return self._related(self._subjects(SEAM.governedBy), SEAM.governedBy)
