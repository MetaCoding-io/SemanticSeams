"""``model.architecture``: systems, containers, deployment nodes and environments (C4)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from rdflib import RDF, URIRef
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import ARCH, COMM, DEPLOY, SEAM
from ._base import Element, Many, Views, element_type, int_value, sorted_many

if TYPE_CHECKING:
    from .operations import Channel, Operation
    from .processes import Process


@element_type(ARCH.System)
@dataclass(frozen=True, eq=False)
class System(Element):
    """An arch:System."""

    @property
    def containers(self) -> Many[Container]:
        """The arch:Containers it arch:contains, by IRI."""
        ds = self.views.ds
        iris = [c for c in self._objects(ARCH.contains) if (c, RDF.type, ARCH.Container) in ds]
        return self._many(Container, iris, ARCH.contains)


@dataclass(frozen=True)
class Artifact:
    """A container's deploy:artifact: the image deploy:reference and deploy:version."""

    reference: str
    version: str


@dataclass(frozen=True)
class Port:
    """A deploy:port: deploy:containerPort, and deploy:publishedPort when published on the host."""

    container_port: int
    published_port: int | None


@dataclass(frozen=True)
class Volume:
    """A named deploy:volume: deploy:volumeName mounted at deploy:mountPath."""

    name: str
    mount_path: str


@dataclass(frozen=True)
class Healthcheck:
    """A deploy:healthcheck: the deploy:probe command and its deploy:interval."""

    probe: str
    interval: str


#: The predicates a configuration binding takes its value from; a binding has exactly one.
BINDING_KINDS = (DEPLOY.value, DEPLOY.secretRef, DEPLOY.serviceOf)


@dataclass(frozen=True)
class Binding:
    """A deploy:binding of a container's deploy:configuration.

    ``kinds`` lists which of ``BINDING_KINDS`` it states (a well-formed
    binding states one): a plain ``value``, an external secret
    (``secret_ref`` and its ``secret_name``) or the URL of another
    container (``service_of``, None when the object is not an IRI).
    """

    key: str
    kinds: tuple[URIRef, ...]
    value: str | None
    secret_ref: Node | None
    secret_name: str | None
    service_of: Container | None


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
        """The arch:Systems that arch:contain it, by IRI."""
        ds = self.views.ds
        iris = [s for s in self._subjects(ARCH.contains) if (s, RDF.type, ARCH.System) in ds]
        return self._many(System, iris, ARCH.contains)

    # ── deploy: facts. Ports, volumes and bindings are blank nodes, so every
    # error names the container and the predicate.

    def _node_values(self, node: Node, predicate: URIRef) -> list[Node]:
        return sorted(set(self.views.ds.objects(node, predicate)), key=str)

    def _node_one(self, node: Node, predicate: URIRef, what: str) -> Node:
        values = self._node_values(node, predicate)
        if len(values) != 1:
            found = "none" if not values else ", ".join(map(str, values))
            raise ResolutionError(self.iri, predicate, f"{what}: expected exactly one, found {found}")
        return values[0]

    def _node_optional(self, node: Node, predicate: URIRef, what: str) -> Node | None:
        values = self._node_values(node, predicate)
        if len(values) > 1:
            raise ResolutionError(
                self.iri, predicate, f"{what}: expected at most one, found {', '.join(map(str, values))}"
            )
        return values[0] if values else None

    def _node_int(self, node: Node, predicate: URIRef, what: str) -> int | None:
        return int_value(self.iri, predicate, self._node_optional(node, predicate, what))

    @property
    def artifact(self) -> Artifact | None:
        """Its deploy:artifact image, or None; several raise ``ResolutionError(container, deploy:artifact)``."""
        node = self._optional_value(DEPLOY.artifact)
        if node is None:
            return None
        return Artifact(
            str(self._node_one(node, DEPLOY.reference, "deploy:artifact")),
            str(self._node_one(node, DEPLOY.version, "deploy:artifact")),
        )

    @property
    def ports(self) -> tuple[Port, ...]:
        """Its deploy:ports, by container port (then published port)."""
        found: list[Port] = []
        for node in self._values(DEPLOY.port):
            port = self._node_int(node, DEPLOY.containerPort, "deploy:port")
            if port is None:
                raise ResolutionError(self.iri, DEPLOY.containerPort, "a deploy:port needs a deploy:containerPort")
            found.append(Port(port, self._node_int(node, DEPLOY.publishedPort, "deploy:port")))
        return tuple(
            sorted(found, key=lambda p: (p.container_port, p.published_port is not None, p.published_port or 0))
        )

    @property
    def volumes(self) -> tuple[Volume, ...]:
        """Its named deploy:volumes, by (name, mount path)."""
        found: list[Volume] = []
        for node in self._values(DEPLOY.volume):
            name = str(self._node_one(node, DEPLOY.volumeName, "deploy:volume"))
            found.append(Volume(name, str(self._node_one(node, DEPLOY.mountPath, f"deploy:volume {name}"))))
        return tuple(sorted(found, key=lambda v: (v.name, v.mount_path)))

    @property
    def healthcheck(self) -> Healthcheck | None:
        """Its deploy:healthcheck, or None; several raise ``ResolutionError(container, deploy:healthcheck)``."""
        node = self._optional_value(DEPLOY.healthcheck)
        if node is None:
            return None
        return Healthcheck(
            str(self._node_one(node, DEPLOY.probe, "deploy:healthcheck")),
            str(self._node_one(node, DEPLOY.interval, "deploy:healthcheck")),
        )

    @property
    def replicas(self) -> int | None:
        """deploy:replicas, or None."""
        return self._int(DEPLOY.replicas)

    @property
    def deploy_depends_on(self) -> Many[Container]:
        """The containers it deploy:dependsOn (start order; ``depends_on`` is the C4 arch:dependsOn)."""
        return self._many(Container, self._objects(DEPLOY.dependsOn), DEPLOY.dependsOn)

    @property
    def bindings(self) -> tuple[Binding, ...]:
        """Every deploy:binding of its deploy:configurations, by key. Keys
        are not checked for uniqueness here: a generator reports a key bound twice."""
        found: list[Binding] = []
        for cfg in self._values(DEPLOY.configuration):
            for b in self._node_values(cfg, DEPLOY.binding):
                key = str(self._node_one(b, DEPLOY.key, "deploy:binding"))
                what = f"binding {key!r}"
                value = self._node_optional(b, DEPLOY.value, what)
                name = self._node_optional(b, DEPLOY.secretName, what)
                service = self._node_optional(b, DEPLOY.serviceOf, what)
                found.append(
                    Binding(
                        key=key,
                        kinds=tuple(k for k in BINDING_KINDS if self._node_values(b, k)),
                        value=None if value is None else str(value),
                        secret_ref=self._node_optional(b, DEPLOY.secretRef, what),
                        secret_name=None if name is None else str(name),
                        service_of=self.views.intern(Container, service) if isinstance(service, URIRef) else None,
                    )
                )
        return tuple(sorted(found, key=lambda b: (b.key, [str(k) for k in b.kinds])))

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
