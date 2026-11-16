"""The C4 model the interchange exports share (M033/S01, backlog X9, ADR-0044).

``extract_c4(model)`` reads the C4 layer through the seams views
(``model.architecture``, ``model.interfaces``, ``model.policies``) into a
frozen ``C4Model``, which the ``structurizr`` and ``likec4`` generators only
print. It holds:

- the people: each odrl:assignee of a policy seam:governedBy an ifml:Event a
  container presents (the container that seam:presents the interaction model
  holding the event's owner, as ``seams_gen.sequence`` finds it), the
  operation that event seam:submitsTo, or a user task seam:completedOn the
  event's form. These are the actors of the sequence and storm views;
- the systems, the model's own and the arch:external ones (ADR-0040), each
  with the containers it arch:contains;
- the relationships, one per (source, destination) pair: a person to the
  container presenting the events its policies govern, labelled with those
  events' local names; a container to each container exposing what it
  seam:consumes, labelled with those operations' and channels' local names;
  and a container to each container it arch:dependsOn, labelled
  ``depends on`` when it consumes nothing from it.

Everything is sorted by IRI. An identifier is the element's local name with
every character outside ``[A-Za-z0-9_]`` replaced by ``_`` (and ``_``
prefixed before a leading digit), so both formats accept it; two elements
with one identifier raise ``GeneratorError``. A fact the exports expect and
cannot find is a gap, a comment line in each export, never an invented
element: an event no container presents, an event no assignee's policy
governs, a container with no arch:technology, a container in no system or
in several, and a consumed endpoint no container exposes. A view
``ResolutionError`` is passed on as the ``GeneratorError`` on the same fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdflib import RDF, URIRef
from seams import Component as ComponentView
from seams import Event, Model, local_name
from seams.views import Container as ContainerView

from . import GeneratorError
from ._views import view_errors
from .sequence import _presenter

#: The label of a dependsOn relationship that carries no consumed endpoint.
DEPENDS_ON = "depends on"


@dataclass(frozen=True)
class Person:
    """A party some policy assigns: its IRI, identifier and rdfs:label."""

    iri: str
    identifier: str
    name: str


@dataclass(frozen=True)
class Container:
    """An arch:Container of one system: its arch:technology, None when it has none."""

    iri: str
    identifier: str
    name: str
    technology: str | None


@dataclass(frozen=True)
class System:
    """An arch:System: ``external`` when it states arch:external true (ADR-0040),
    with its containers by IRI."""

    iri: str
    identifier: str
    name: str
    external: bool
    containers: tuple[Container, ...]


@dataclass(frozen=True)
class Relationship:
    """One arrow: the source and destination IRIs and identifiers, its label,
    and the IRIs it comes from (the events, policies, endpoints)."""

    source: str
    destination: str
    source_id: str
    destination_id: str
    label: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class C4Model:
    """The people, systems and relationships by IRI, the gaps sorted, and every
    IRI the exports come from."""

    people: tuple[Person, ...]
    systems: tuple[System, ...]
    relationships: tuple[Relationship, ...]
    gaps: tuple[str, ...]
    sources: tuple[str, ...]

    @property
    def containers(self) -> tuple[Container, ...]:
        """Every container of every system, by IRI."""
        return tuple(sorted((c for s in self.systems for c in s.containers), key=lambda c: c.iri))

    def system_of(self, container: Container) -> System:
        """The system holding ``container``."""
        return next(s for s in self.systems if container in s.containers)


def identifier(iri: URIRef) -> str:
    """The local name of ``iri`` as an identifier both formats accept."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", local_name(iri))
    return f"_{name}" if not name or name[0].isdigit() else name


class _Builder:
    def __init__(self, model: Model) -> None:
        self.model = model
        self.gaps: set[str] = set()
        self.sources: set[str] = set()
        # (source, destination) -> (labels, source IRIs); no label is a bare arch:dependsOn
        self.arrows: dict[tuple[URIRef, URIRef], tuple[set[str], set[str]]] = {}

    def arrow(self, source: URIRef, destination: URIRef, label: str | None, *terms: URIRef) -> None:
        labels, sources = self.arrows.setdefault((source, destination), (set(), set()))
        if label is not None:
            labels.add(label)
        sources.update(str(t) for t in terms)


def _event_policies(model: Model, event: Event) -> list[URIRef]:
    """The policies on the event, on what it submits to, and on each user task
    its form completes (the storm and sequence actors' rule), by IRI."""
    found = {p.iri for p in event.governed_by}
    op = event.submits_to
    if op is not None:
        found.update(p.iri for p in op.governed_by)
    tasks = {t.iri for owner in event.owners if isinstance(owner, ComponentView) for t in owner.completes}
    for policy in model.policies:
        if tasks & set(policy.governs.iris()):
            found.add(policy.iri)
    return sorted(found, key=str)


def _people(b: _Builder) -> dict[URIRef, Person]:
    model = b.model
    people: dict[URIRef, Person] = {}
    policies = {p.iri: p for p in model.policies}
    for event in model.interfaces.events():
        ev = local_name(event.iri)
        ui = _presenter(event.owners)
        if ui is None:
            b.gaps.add(f"{ev} has no interaction model seam:presents by one container, so no person uses it")
            continue
        found = 0
        for policy_iri in _event_policies(model, event):
            for perm in policies[policy_iri].permissions:
                if perm.assignee is None:
                    continue
                found += 1
                people.setdefault(
                    perm.assignee, Person(str(perm.assignee), identifier(perm.assignee), model.label(perm.assignee))
                )
                b.arrow(perm.assignee, ui, ev, event.iri, policy_iri, perm.assignee)
        if not found:
            b.gaps.add(
                f"{ev} has no seam:governedBy policy with an odrl:assignee (on it, its operation or the user task "
                "its form completes), so no person uses it"
            )
    return people


def _owner(b: _Builder, container: ContainerView) -> URIRef | None:
    """The one system containing ``container``; none or several is a gap."""
    systems = container.systems
    name = local_name(container.iri)
    if len(systems) == 1:
        return systems[0].iri
    if not systems:
        b.gaps.add(f"container {name} is arch:contains'ed by no arch:System, so it is left out")
    else:
        found = ", ".join(local_name(s) for s in systems.iris())
        b.gaps.add(f"container {name} is arch:contains'ed by several systems ({found}), so it is left out")
    return None


def _container_arrows(b: _Builder, container: ContainerView) -> None:
    name = local_name(container.iri)
    for endpoint in container.consumes:
        exposers = endpoint.exposed_by
        if not exposers:
            b.gaps.add(f"{local_name(endpoint.iri)} consumed by {name} has no seam:exposes container")
        for exposer in exposers:
            b.arrow(container.iri, exposer.iri, local_name(endpoint.iri), endpoint.iri)
    for dependency in container.depends_on:
        b.arrow(container.iri, dependency.iri, None)


def _unique(model: Model, ids: dict[URIRef, str]) -> None:
    """Two elements with one identifier would be one element in either format."""
    seen: dict[str, URIRef] = {}
    for iri, ident in sorted(ids.items(), key=lambda kv: str(kv[0])):
        if ident in seen:
            detail = (
                f"{model.compact(seen[ident])} and {model.compact(iri)} both have the C4 identifier "
                f'"{ident}"; a Structurizr or LikeC4 element is named by its identifier'
            )
            raise GeneratorError(iri, RDF.type, detail)
        seen[ident] = iri


def extract_c4(model: Model) -> C4Model:
    """The people, systems and relationships of ``model``'s C4 layer."""
    b = _Builder(model)
    with view_errors():
        people = _people(b)
        members: dict[URIRef, list[Container]] = {}
        placed: set[URIRef] = set()
        for container in model.architecture.containers():
            owner = _owner(b, container)
            if owner is None:
                continue
            if container.technology is None:
                b.gaps.add(f"container {local_name(container.iri)} has no arch:technology")
            c = Container(
                str(container.iri), identifier(container.iri), model.label(container.iri), container.technology
            )
            members.setdefault(owner, []).append(c)
            placed.add(container.iri)
            _container_arrows(b, container)
        systems = [
            System(
                str(s.iri),
                identifier(s.iri),
                model.label(s.iri),
                s.external,
                tuple(sorted(members.get(s.iri, []), key=lambda c: c.iri)),
            )
            for s in model.architecture.systems()
        ]
    for s in systems:
        if not s.containers:
            b.gaps.add(f"system {local_name(URIRef(s.iri))} arch:contains no arch:Container")

    ids = {URIRef(p.iri): p.identifier for p in people.values()}
    ids.update({URIRef(s.iri): s.identifier for s in systems})
    ids.update({URIRef(c.iri): c.identifier for s in systems for c in s.containers})
    _unique(model, ids)

    relationships: list[Relationship] = []
    for (source, destination), (labels, sources) in b.arrows.items():
        if destination not in placed or (source not in placed and source not in people):
            continue  # an end that is left out is already a gap
        label = ", ".join(sorted(labels)) if labels else DEPENDS_ON
        relationships.append(
            Relationship(str(source), str(destination), ids[source], ids[destination], label, tuple(sorted(sources)))
        )
        b.sources.update(sources)
    relationships.sort(key=lambda r: (r.source, r.destination))

    b.sources.update(str(i) for i in ids)
    return C4Model(
        people=tuple(sorted(people.values(), key=lambda p: p.iri)),
        systems=tuple(sorted(systems, key=lambda s: s.iri)),
        relationships=tuple(relationships),
        gaps=tuple(sorted(b.gaps)),
        sources=tuple(sorted(b.sources)),
    )


def c4_sources(model: Model) -> tuple[str, ...]:
    """The full IRIs a C4 export comes from: its people, systems, containers and
    the events, policies and endpoints its relationships are drawn from."""
    return extract_c4(model).sources


__all__ = [
    "DEPENDS_ON",
    "C4Model",
    "Container",
    "Person",
    "Relationship",
    "System",
    "c4_sources",
    "extract_c4",
    "identifier",
]
