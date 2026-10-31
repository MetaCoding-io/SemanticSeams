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
    from .shapes import Shape


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
class Build:
    """An artifact's deploy:build: the deploy:context directory, relative to
    the model file's directory, and the deploy:dockerfile within it (or None)."""

    context: str
    dockerfile: str | None


@dataclass(frozen=True)
class Artifact:
    """A container's deploy:artifact: the image deploy:reference and
    deploy:version, and its deploy:build when it is built from source."""

    reference: str
    version: str
    build: Build | None = None


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


#: The predicates a configuration binding takes its value from; a binding has
#: exactly one. deploy:connectsTo is not one: it sits beside a value source.
BINDING_KINDS = (DEPLOY.value, DEPLOY.secretRef, DEPLOY.secretFile, DEPLOY.serviceOf)


@dataclass(frozen=True)
class Binding:
    """A deploy:binding of a container's deploy:configuration.

    ``kinds`` lists which of ``BINDING_KINDS`` it states (a well-formed
    binding states one): a plain ``value``, an external secret
    (``secret_ref`` and its ``secret_name``), a secret read from a file
    (``secret_file``, a path relative to the model file's directory) or the
    URL of another container (``service_of``, None when the object is not
    an IRI).
    ``connects_to`` is the store container its value reaches
    (deploy:connectsTo, ADR-0011), or None.
    """

    key: str
    kinds: tuple[URIRef, ...]
    value: str | None
    secret_ref: Node | None
    secret_name: str | None
    service_of: Container | None
    connects_to: Container | None = None
    secret_file: str | None = None


#: The predicates a deploy:Override may carry besides rdf:type and
#: deploy:environment (ADR-0015, v1).
OVERRIDABLE = (DEPLOY.artifact, DEPLOY.configuration, DEPLOY.replicas)


@dataclass(frozen=True)
class Override:
    """A container's deploy:override for one deploy:environment. Each field is
    None when the override does not state it, so the shared fact applies;
    ``bindings`` are the override's own, by key, not yet merged."""

    environment: Environment
    artifact: Artifact | None
    bindings: tuple[Binding, ...] | None
    replicas: int | None


@dataclass(frozen=True)
class Deployment:
    """The facts a container has in one environment under ADR-0015's override
    rule: ``Container.for_environment``."""

    environment: Environment
    artifact: Artifact | None
    bindings: tuple[Binding, ...]
    replicas: int | None


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

    def _artifact(self, subject: Node, what: str) -> Artifact | None:
        node = self._node_optional(subject, DEPLOY.artifact, what)
        if node is None:
            return None
        build = None
        build_node = self._node_optional(node, DEPLOY.build, f"{what} deploy:artifact")
        if build_node is not None:
            dockerfile = self._node_optional(build_node, DEPLOY.dockerfile, "deploy:build")
            build = Build(
                str(self._node_one(build_node, DEPLOY.context, "deploy:build")),
                None if dockerfile is None else str(dockerfile),
            )
        return Artifact(
            str(self._node_one(node, DEPLOY.reference, "deploy:artifact")),
            str(self._node_one(node, DEPLOY.version, "deploy:artifact")),
            build,
        )

    @property
    def artifact(self) -> Artifact | None:
        """Its shared deploy:artifact image, or None; several raise
        ``ResolutionError(container, deploy:artifact)``."""
        return self._artifact(self.iri, "deploy:artifact")

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
        """The shared deploy:replicas, or None."""
        return self._int(DEPLOY.replicas)

    @property
    def proxies(self) -> Container | None:
        """The container it deploy:proxies (a code-free reverse proxy), or None;
        several, or a literal, raise ``ResolutionError(container, deploy:proxies)``."""
        target = self._optional_value(DEPLOY.proxies)
        if target is None:
            return None
        if not isinstance(target, URIRef) or (target, RDF.type, ARCH.Container) not in self.views.ds:
            raise ResolutionError(self.iri, DEPLOY.proxies, f"expected an arch:Container, found {target}")
        return self.views.intern(Container, target)

    @property
    def deploy_depends_on(self) -> Many[Container]:
        """The containers it deploy:dependsOn (start order; ``depends_on`` is the C4 arch:dependsOn)."""
        return self._many(Container, self._objects(DEPLOY.dependsOn), DEPLOY.dependsOn)

    def _bindings(self, subject: Node) -> tuple[Binding, ...]:
        found: list[Binding] = []
        for cfg in self._node_values(subject, DEPLOY.configuration):
            for b in self._node_values(cfg, DEPLOY.binding):
                key = str(self._node_one(b, DEPLOY.key, "deploy:binding"))
                what = f"binding {key!r}"
                value = self._node_optional(b, DEPLOY.value, what)
                name = self._node_optional(b, DEPLOY.secretName, what)
                path = self._node_optional(b, DEPLOY.secretFile, what)
                service = self._node_optional(b, DEPLOY.serviceOf, what)
                store = self._node_optional(b, DEPLOY.connectsTo, what)
                found.append(
                    Binding(
                        key=key,
                        kinds=tuple(k for k in BINDING_KINDS if self._node_values(b, k)),
                        value=None if value is None else str(value),
                        secret_ref=self._node_optional(b, DEPLOY.secretRef, what),
                        secret_name=None if name is None else str(name),
                        service_of=self.views.intern(Container, service) if isinstance(service, URIRef) else None,
                        connects_to=self.views.intern(Container, store) if isinstance(store, URIRef) else None,
                        secret_file=None if path is None else str(path),
                    )
                )
        return tuple(sorted(found, key=_binding_order))

    @property
    def bindings(self) -> tuple[Binding, ...]:
        """Every shared deploy:binding of its deploy:configurations, by key. Keys
        are not checked for uniqueness here: a generator reports a key bound twice."""
        return self._bindings(self.iri)

    # ── environments (ADR-0015): overrides and the override rule.

    @property
    def overrides(self) -> tuple[Override, ...]:
        """Its deploy:overrides, by environment IRI. Raises
        ``ResolutionError(container, predicate)`` for an override that is no
        deploy:Override (rdf:type), states a predicate other than
        deploy:environment, deploy:artifact, deploy:configuration and
        deploy:replicas (that predicate), names no single arch:Environment
        (deploy:environment), or shares its environment with another
        (deploy:override)."""
        ds = self.views.ds
        found: dict[URIRef, Override] = {}
        for node in self._values(DEPLOY.override):
            if (node, RDF.type, DEPLOY.Override) not in ds:
                raise ResolutionError(self.iri, RDF.type, f"deploy:override {node} is not a deploy:Override")
            for predicate in sorted({p for p in ds.predicates(node, None)}, key=str):
                if predicate not in (RDF.type, DEPLOY.environment, *OVERRIDABLE):
                    raise ResolutionError(
                        self.iri,
                        predicate,
                        "a deploy:Override carries only deploy:artifact, deploy:configuration and deploy:replicas",
                    )
            env = self._node_one(node, DEPLOY.environment, "deploy:override")
            if not isinstance(env, URIRef) or (env, RDF.type, ARCH.Environment) not in ds:
                raise ResolutionError(self.iri, DEPLOY.environment, f"{env} is not an arch:Environment")
            if env in found:
                raise ResolutionError(self.iri, DEPLOY.override, f"two deploy:overrides for environment {env}")
            bindings = self._bindings(node) if self._node_values(node, DEPLOY.configuration) else None
            found[env] = Override(
                environment=self.views.intern(Environment, env),
                artifact=self._artifact(node, "deploy:override"),
                bindings=bindings,
                replicas=int_value(
                    self.iri, DEPLOY.replicas, self._node_optional(node, DEPLOY.replicas, "deploy:override")
                ),
            )
        return tuple(found[env] for env in sorted(found, key=str))

    def for_environment(self, environment: Environment) -> Deployment:
        """Its artifact, bindings and replicas in ``environment`` (ADR-0015).

        Every shared fact applies unless the container's override for the
        environment states the predicate: an override deploy:artifact or
        deploy:replicas replaces the shared one whole, and each override
        binding replaces the shared binding with its deploy:key or adds one,
        leaving the others in place. No override, or an override silent on a
        predicate, means the shared fact. An override binding keeps the
        deploy:connectsTo of the shared binding with its key (the store never
        changes per environment); a difference raises ``ResolutionError(container,
        deploy:connectsTo)``, and a key the override binds twice
        ``ResolutionError(container, deploy:key)``. Bindings come back by key."""
        override = next((o for o in self.overrides if o.environment == environment), None)
        shared = self.bindings
        if override is None:
            return Deployment(environment, self.artifact, shared, self.replicas)

        bindings = shared
        if override.bindings is not None:
            replacing: dict[str, Binding] = {}
            for b in override.bindings:
                if b.key in replacing:
                    raise ResolutionError(self.iri, DEPLOY.key, f"the {environment.iri} override binds {b.key!r} twice")
                replacing[b.key] = b
                stores = {s.connects_to for s in shared if s.key == b.key}
                if stores != {b.connects_to} and (stores or b.connects_to is not None):
                    were = sorted(str(s.iri) for s in stores if s is not None) or "no store"
                    now = "no store" if b.connects_to is None else str(b.connects_to.iri)
                    raise ResolutionError(
                        self.iri,
                        DEPLOY.connectsTo,
                        f"the {environment.iri} override binding {b.key!r} connects to {now}, "
                        f"the shared binding to {were}; the store cannot change per environment",
                    )
            kept = [b for b in shared if b.key not in replacing]
            bindings = tuple(sorted([*kept, *replacing.values()], key=_binding_order))

        return Deployment(
            environment,
            self.artifact if override.artifact is None else override.artifact,
            bindings,
            self.replicas if override.replicas is None else override.replicas,
        )

    @property
    def connecting_bindings(self) -> tuple[Binding, ...]:
        """Its ``bindings`` that deploy:connectsTo a store, by key."""
        return tuple(b for b in self.bindings if b.connects_to is not None)

    @property
    def store_kinds(self) -> tuple[URIRef, ...]:
        """The deploy:storeKind IRIs it states (a store states exactly one), sorted."""
        return tuple(sorted(self._objects(DEPLOY.storeKind), key=str))

    @property
    def stored_shapes(self) -> Many[Shape]:
        """The shapes seam:storedIn it."""
        from .shapes import Shape

        return self._many(Shape, self._subjects(SEAM.storedIn), SEAM.storedIn)

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


def _binding_order(b: Binding) -> tuple[str, list[str]]:
    return (b.key, [str(k) for k in b.kinds])


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

    def serving_containers(self) -> Many[Container]:
        """The arch:Containers that serve routes and hold process state (D026):
        each one that seam:executes a proc:Process or seam:exposes a
        hydra:Operation some ifml:Event seam:submitsTo, by IRI. An operation
        only a task seam:invokes (the chat app's :completion_op) does not make
        its container serving."""
        from .operations import Operation

        model = self._views.model
        processes, operations = model.processes, model.operations
        return self.containers().where(
            lambda c: (
                any(p in processes for p in c.executes)
                or any(isinstance(e, Operation) and e in operations and e.submitted_by for e in c.exposes)
            )
        )

    def deployment_nodes(self) -> Many[DeploymentNode]:
        return self._views.all(DeploymentNode, ARCH.DeploymentNode)

    def environments(self) -> Many[Environment]:
        return self._views.all(Environment, ARCH.Environment)
