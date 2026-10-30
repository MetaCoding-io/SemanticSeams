"""``model.architecture``: systems, containers, deployment nodes and environments (C4)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from rdflib import RDF, URIRef

from ..namespaces import ARCH, COMM, DEPLOY, SEAM
from ._base import Element, Many, Views, element_type, sorted_many

if TYPE_CHECKING:
    from .operations import Channel, Operation
    from .processes import Process


@element_type(ARCH.System)
@dataclass(frozen=True, eq=False)
class System(Element):
    """An arch:System."""

    @property
    def containers(self) -> Many[Container]:
        """The arch:Containers it arch:contains."""
        return self._many(Container, self._objects(ARCH.contains), ARCH.contains)


@element_type(ARCH.Container)
@dataclass(frozen=True, eq=False)
class Container(Element):
    """An arch:Container and the seam edges to what it serves and runs."""

    @property
    def technology(self) -> str | None:
        return self._text(ARCH.technology)

    def _endpoints(self, iris: list[URIRef], predicate: URIRef) -> Many[Operation | Channel]:
        from .operations import Channel, Operation

        views = self.views
        items: list[Operation | Channel] = [
            views.intern(Channel, i) if (i, RDF.type, COMM.Channel) in views.ds else views.intern(Operation, i)
            for i in iris
        ]
        return sorted_many(items, self.iri, predicate, views.model.curie)

    @property
    def exposes(self) -> Many[Operation | Channel]:
        """The operations and channels it seam:exposes."""
        return self._endpoints(self._objects(SEAM.exposes), SEAM.exposes)

    @property
    def consumes(self) -> Many[Operation | Channel]:
        """The operations and channels it seam:consumes."""
        return self._endpoints(self._objects(SEAM.consumes), SEAM.consumes)

    @property
    def executes(self) -> Many[Process]:
        """The processes it seam:executes (in-process)."""
        from .processes import Process

        return self._many(Process, self._objects(SEAM.executes), SEAM.executes)

    @property
    def deployed_to(self) -> Many[DeploymentNode]:
        return self._many(DeploymentNode, self._objects(SEAM.deployedTo), SEAM.deployedTo)

    @property
    def depends_on(self) -> Many[Container]:
        """The containers it arch:dependsOn."""
        return self._many(Container, self._objects(ARCH.dependsOn), ARCH.dependsOn)

    @property
    def systems(self) -> Many[System]:
        """The arch:Systems that arch:contain it."""
        return self._many(System, self._subjects(ARCH.contains), ARCH.contains)

    @property
    def service_bindings(self) -> Mapping[str, URIRef]:
        """deploy:key -> deploy:serviceOf for each configuration binding that
        names a service (e.g. ``LLM_GATEWAY_URL`` -> the gateway), by key."""
        ds = self.views.ds
        found: dict[str, URIRef] = {}
        for cfg in ds.objects(self.iri, DEPLOY.configuration):
            for b in ds.objects(cfg, DEPLOY.binding):
                key, target = ds.value(b, DEPLOY.key), ds.value(b, DEPLOY.serviceOf)
                if key is not None and isinstance(target, URIRef):
                    found[str(key)] = target
        return MappingProxyType(dict(sorted(found.items())))


@element_type(ARCH.DeploymentNode)
@dataclass(frozen=True, eq=False)
class DeploymentNode(Element):
    """An arch:DeploymentNode."""

    @property
    def hosts(self) -> Many[Container]:
        """The containers seam:deployedTo it."""
        return self._many(Container, self._subjects(SEAM.deployedTo), SEAM.deployedTo)

    @property
    def environments(self) -> Many[Environment]:
        """The arch:Environments that arch:contain it."""
        return self._many(Environment, self._subjects(ARCH.contains), ARCH.contains)


@element_type(ARCH.Environment)
@dataclass(frozen=True, eq=False)
class Environment(Element):
    """An arch:Environment."""

    @property
    def nodes(self) -> Many[DeploymentNode]:
        return self._many(DeploymentNode, self._objects(ARCH.contains), ARCH.contains)


class Architecture:
    """The C4 layer across every architecture model in the graph."""

    def __init__(self, views: Views) -> None:
        self._views = views

    def systems(self) -> Many[System]:
        return self._views.all(System, ARCH.System)

    def containers(self) -> Many[Container]:
        return self._views.all(Container, ARCH.Container)

    def deployment_nodes(self) -> Many[DeploymentNode]:
        return self._views.all(DeploymentNode, ARCH.DeploymentNode)

    def environments(self) -> Many[Environment]:
        return self._views.all(Environment, ARCH.Environment)
