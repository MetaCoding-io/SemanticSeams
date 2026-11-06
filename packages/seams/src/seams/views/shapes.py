"""``model.shapes``: SHACL node shapes and their fields.

A field's name, options and flattening follow ADR-0023: ``sh:name`` is the
wire name, a category field's options are its members' labels, and an
``sh:node`` to a shape with one free property is one field."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from rdflib import OWL, RDF, RDFS, XSD, Dataset, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import DASH, GIST, SEAM, STATE, VERIFY, local_name
from ..ontologies import ontology_models
from ._base import Element, Many, element_type, optional, sorted_many

if TYPE_CHECKING:
    from .aggregates import Aggregate
    from .architecture import Container
    from .lifecycles import Lifecycle
    from .ontologies import OntologyClass

NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
"""What an ``sh:name`` must match (it becomes an HTML name and a Python identifier)."""

# The predicates a fixed property of a flattened sh:node may carry (ADR-0023 section 4).
_FIXED_KEYS = frozenset({SH.path, SH.hasValue, RDFS.label, RDF.type})


@dataclass(frozen=True)
class FlatNode:
    """The nested shape of a flattened field (ADR-0023 section 4): ``shape``
    is the sh:node shape, ``node_class`` its own sh:class (the nested node's
    type), ``free_path`` the one property a person enters and ``fixed`` the
    (path, sh:hasValue) pairs of the others, sorted by path."""

    shape: URIRef
    node_class: URIRef | None
    free_path: URIRef
    fixed: tuple[tuple[URIRef, Node], ...]


@dataclass(frozen=True)
class Field:
    """One sh:property of a shape. ``iri`` is its sh:path (unique within the
    shape), ``name`` its sh:name (else the path's local name) and ``label``
    its rdfs:label (else ``name``). ``editor`` is its dash:editor,
    ``options`` the values it allows in order (sh:in literals, or the
    rdfs:labels of its category ``members``) and ``max_length`` its
    sh:maxLength. ``category`` is the gist:Category subclass its sh:class
    names; a field with members and no sh:datatype has ``datatype``
    xsd:string, the type of its labels on the wire. ``node`` is set for a flattened sh:node field, whose datatype,
    options and max_length come from the nested shape's free property.
    ``reference`` is the sh:class of a reference field, a class that is not
    a category (its wire value is another entity's id)."""

    iri: URIRef
    shape: URIRef
    name: str
    label: str
    datatype: URIRef | None
    min_count: int | None
    max_count: int | None
    order: int | None
    max_length: int | None = None
    editor: URIRef | None = None
    options: tuple[str, ...] = ()
    members: tuple[URIRef, ...] = ()
    category: URIRef | None = None
    node: FlatNode | None = None
    reference: URIRef | None = None

    @property
    def path(self) -> URIRef:
        return self.iri

    @property
    def required(self) -> bool:
        return (self.min_count or 0) > 0


def _int(value: Node | None) -> int | None:
    return None if value is None else int(cast(Literal, value))


def _sorted(nodes: Iterable[Node]) -> list[Node]:
    return sorted(set(nodes), key=str)


@element_type(SH.NodeShape)
@dataclass(frozen=True, eq=False)
class Shape(Element):
    """An sh:NodeShape."""

    def fields(self) -> Many[Field]:
        """Its sh:property fields by sh:order (fields without one last), then path IRI."""
        out = [self._field(node) for node in self.views.ds.objects(self.iri, SH.property)]
        return sorted_many(
            out,
            self.iri,
            SH.property,
            self.views.model.curie,
            key=lambda f: (f.order is None, f.order or 0, str(f.iri)),
        )

    @property
    def target_class(self) -> OntologyClass | None:
        """The owl:Class it names with sh:targetClass (ADR-0023 section 1); a
        class no seam:Ontology model declares raises ``ResolutionError``."""
        from .ontologies import OntologyClass

        found = optional(self._many(OntologyClass, self._objects(SH.targetClass), SH.targetClass))
        if found is None:
            return None
        ds = self.views.ds
        ontologies = set(ontology_models(ds))
        declared = (found.iri, RDF.type, OWL.Class) in ds
        if not declared or not any(m in ontologies for m in ds.objects(found.iri, SEAM.inModel)):
            detail = f"{self._compact(found.iri)} is not an owl:Class of a seam:Ontology model"
            raise ResolutionError(self.iri, SH.targetClass, detail)
        return found

    # ── reading one sh:property ──

    def _compact(self, iri: Node) -> str:
        return self.views.model.compact(iri)

    def _field(self, node: Node) -> Field:
        ds = self.views.ds
        path = ds.value(node, SH.path)
        if not isinstance(path, URIRef):
            raise ResolutionError(self.iri, SH.path, "sh:property without an IRI sh:path")
        name = self._name(node, path)
        label = ds.value(node, RDFS.label)
        flat = self._flatten(node, name)
        source = node if flat is None else flat[1]
        options, members, category = self._options(source, name)
        datatype = ds.value(source, SH.datatype)
        if datatype is None and members:
            datatype = XSD.string  # the wire value of a member is its label
        editor = ds.value(node, DASH.editor) or ds.value(source, DASH.editor)
        cls = ds.value(source, SH["class"])
        reference = cls if isinstance(cls, URIRef) and category is None and not members else None
        return Field(
            iri=path,
            shape=self.iri,
            name=name,
            label=name if label is None else str(label),
            datatype=datatype if isinstance(datatype, URIRef) else None,
            min_count=_int(ds.value(node, SH.minCount)),
            max_count=_int(ds.value(node, SH.maxCount)),
            order=_int(ds.value(node, SH.order)),
            max_length=_int(ds.value(source, SH.maxLength)),
            editor=editor if isinstance(editor, URIRef) else None,
            options=options,
            members=members,
            category=category,
            node=None if flat is None else flat[0],
            reference=reference,
        )

    def _name(self, node: Node, path: URIRef) -> str:
        names = _sorted(self.views.ds.objects(node, SH.name))
        if not names:
            return local_name(path)
        if len(names) > 1 or not NAME_PATTERN.fullmatch(str(names[0])):
            found = ", ".join(repr(str(n)) for n in names)
            detail = f"{local_name(path)}: sh:name must be one name matching {NAME_PATTERN.pattern}, found {found}"
            raise ResolutionError(self.iri, SH.name, detail)
        return str(names[0])

    def _options(self, source: Node, name: str) -> tuple[tuple[str, ...], tuple[URIRef, ...], URIRef | None]:
        """(options, members, category) of a property: sh:in literals in list
        order, sh:in IRIs in list order, or a category class's members."""
        ds = self.views.ds
        listed = ds.value(source, SH["in"])
        if listed is not None:
            values = list(Collection(ds, listed))
            iris = [v for v in values if isinstance(v, URIRef)]
            if not iris:
                return tuple(str(v) for v in values), (), None
            if len(iris) != len(values):
                raise ResolutionError(self.iri, SH["in"], f"{name}: sh:in mixes IRIs and literals")
            return self._labels(iris, name, SH["in"], "sh:in"), tuple(iris), None
        cls = ds.value(source, SH["class"])
        if not isinstance(cls, URIRef) or not self._is_category(cls):
            return (), (), None
        members = self.views.iris(ds.subjects(RDF.type, cls))
        if not members:
            raise ResolutionError(self.iri, SH["class"], f"{name}: category {self._compact(cls)} has no members")
        ordered = self._member_order(members, cls, name)
        return self._labels(ordered, name, SH["class"], self._compact(cls)), ordered, cls

    def _is_category(self, cls: URIRef) -> bool:
        """True when ``cls`` reaches gist:Category over declared rdfs:subClassOf triples."""
        ds = self.views.ds
        seen: set[Node] = set()
        todo: list[Node] = [cls]
        while todo:
            current = todo.pop()
            if current == GIST.Category:
                return True
            if current not in seen:
                seen.add(current)
                todo.extend(ds.objects(current, RDFS.subClassOf))
        return False

    def _labels(self, members: Iterable[URIRef], name: str, predicate: URIRef, owner: str) -> tuple[str, ...]:
        """Each member's one rdfs:label, in member order; labels must be distinct."""
        ds = self.views.ds
        seen: dict[str, URIRef] = {}
        for member in members:
            labels = _sorted(ds.objects(member, RDFS.label))
            if len(labels) != 1:
                found = "none" if not labels else ", ".join(repr(str(v)) for v in labels)
                detail = f"member of {owner} ({name} of {self._compact(self.iri)}) needs exactly one rdfs:label, found {found}"
                raise ResolutionError(member, RDFS.label, detail)
            text = str(labels[0])
            if text in seen:
                pair = f"{self._compact(seen[text])} and {self._compact(member)}"
                raise ResolutionError(self.iri, predicate, f'{name}: members {pair} are both labelled "{text}"')
            seen[text] = member
        return tuple(seen)

    def _member_order(self, members: list[URIRef], cls: URIRef, name: str) -> tuple[URIRef, ...]:
        """Lifecycle order when every member is a state of one lifecycle, IRI
        order when none is a state (ADR-0023 section 3)."""
        ds = self.views.ds
        machines: dict[URIRef, set[URIRef]] = {}
        for member in members:
            owners = {
                lc for p in (STATE.hasState, STATE.initial) for lc in ds.subjects(p, member) if isinstance(lc, URIRef)
            }
            if owners or (member, RDF.type, STATE.State) in ds:
                machines[member] = owners
        if not machines:
            return tuple(members)
        found = sorted({lc for owners in machines.values() for lc in owners}, key=str)
        if len(machines) != len(members) or len(found) != 1 or not all(machines.values()):
            if len(found) > 1:
                where = "belong to " + " and ".join(self._compact(lc) for lc in found)
            elif len(machines) != len(members):
                where = "mix lifecycle states with other members"
            else:
                where = "include states of no lifecycle"
            detail = f"{name}: members of {self._compact(cls)} {where}; no single order"
            raise ResolutionError(self.iri, SH["class"], detail)
        depth = _depths(self.views.ds, found[0])
        unreachable = len(depth)
        return tuple(sorted(members, key=lambda m: (depth.get(m, unreachable), str(m))))

    def _flatten(self, node: Node, name: str) -> tuple[FlatNode, Node] | None:
        """The nested shape and its free property when ``node`` has sh:node;
        a shape that does not fit ADR-0023 section 4 raises ``ResolutionError``."""
        ds = self.views.ds
        nested = ds.value(node, SH.node)
        if nested is None:
            return None
        if not isinstance(nested, URIRef):
            raise ResolutionError(self.iri, SH.node, f"{name}: sh:node must name a node shape IRI")
        shape = self._compact(nested)
        if ds.value(node, SH.datatype) is not None:
            detail = f"{name}: sh:node {shape} and sh:datatype on one property; a flattened field takes its datatype from {shape}"
            raise ResolutionError(self.iri, SH.node, detail)
        fixed: list[tuple[URIRef, Node]] = []
        free: list[tuple[URIRef, Node]] = []
        for prop in ds.objects(nested, SH.property):
            path = ds.value(prop, SH.path)
            if not isinstance(path, URIRef):
                raise ResolutionError(nested, SH.path, "sh:property without an IRI sh:path")
            values = _sorted(ds.objects(prop, SH.hasValue))
            if not values:
                free.append((path, prop))
                continue
            extra = sorted({str(p) for p in ds.predicates(prop) if p not in _FIXED_KEYS})
            if len(values) != 1 or extra:
                detail = (
                    f"{name}: {shape}'s fixed property {self._compact(path)} needs exactly one sh:hasValue "
                    "and nothing else but sh:path"
                )
                raise ResolutionError(self.iri, SH.node, detail)
            fixed.append((path, values[0]))
        free.sort(key=lambda pn: str(pn[0]))
        if len(free) != 1:
            paths = ", ".join(self._compact(p) for p, _ in free)
            listed = f" ({paths})" if paths else ""
            detail = f"{name}: {shape} has {len(free)} free properties{listed}; a flattened field needs exactly one"
            raise ResolutionError(self.iri, SH.node, detail)
        free_path, free_node = free[0]
        if ds.value(free_node, SH.node) is not None or _int(ds.value(free_node, SH.maxCount)) != 1:
            detail = f"{name}: {shape}'s free property {self._compact(free_path)} needs sh:maxCount 1 and no sh:node"
            raise ResolutionError(self.iri, SH.node, detail)
        node_class = ds.value(nested, SH["class"])
        flat = FlatNode(
            shape=nested,
            node_class=node_class if isinstance(node_class, URIRef) else None,
            free_path=free_path,
            fixed=tuple(sorted(fixed, key=lambda pv: (str(pv[0]), str(pv[1])))),
        )
        return flat, free_node

    @property
    def lifecycle(self) -> Lifecycle | None:
        """Its effective lifecycle (ADR-0031 section 2): the state machine it
        names with seam:lifecycle, else the one its sh:targetClass names. A
        shape that reaches more than one machine raises ``ResolutionError``."""
        from .lifecycles import Lifecycle

        machines = effective_lifecycles(self.views.ds, self.iri)
        if len(machines) > 1:
            found = ", ".join(self._compact(m) for m in machines)
            detail = f"more than one effective lifecycle, its own or its sh:targetClass's: {found}"
            raise ResolutionError(self.iri, SEAM.lifecycle, detail)
        return optional(self._many(Lifecycle, machines, SEAM.lifecycle))

    @property
    def aggregate(self) -> Aggregate | None:
        """The aggregate it is a seam:aggregateMember of (ADR-0035), or None. A
        shape listed by two aggregates raises ``ResolutionError``."""
        from .aggregates import Aggregate

        owners = self._subjects(SEAM.aggregateMember)
        if len(owners) > 1:
            found = ", ".join(self._compact(o) for o in owners)
            raise ResolutionError(self.iri, SEAM.aggregateMember, f"a member of more than one aggregate: {found}")
        return optional(self._many(Aggregate, owners, SEAM.aggregateMember))

    @property
    def valid_examples(self) -> tuple[URIRef, ...]:
        """The nodes it must accept (verify:validExample, ADR-0014), by IRI."""
        return tuple(self._objects(VERIFY.validExample))

    @property
    def invalid_examples(self) -> tuple[URIRef, ...]:
        """The nodes it must reject (verify:invalidExample, ADR-0014), by IRI."""
        return tuple(self._objects(VERIFY.invalidExample))

    def example_values(self, node: URIRef) -> tuple[tuple[Field, Literal], ...]:
        """(field, value) for each wire value ``node`` (one of its examples)
        has on one of its fields: fields in ``fields()`` order, a field's
        values by lexical form. A literal is its own value, a category
        member IRI reads as its label and a flattened field reads through
        the nested node to its free path (ADR-0023). The node's other
        triples are left out."""
        ds = self.views.ds
        out: list[tuple[Field, Literal]] = []
        for f in self.fields():
            found = list(ds.objects(node, f.iri))
            if f.node is not None:
                found = [
                    v
                    for nested in found
                    if not isinstance(nested, Literal)
                    for v in ds.objects(nested, f.node.free_path)
                ]
            values = sorted((v for v in (_wire(f, v) for v in found) if v is not None), key=str)
            out.extend((f, v) for v in values)
        return tuple(out)

    @property
    def read_by(self) -> Many[Element]:
        """The elements that seam:read it."""
        return self._related(self._subjects(SEAM.reads), SEAM.reads)

    @property
    def written_by(self) -> Many[Element]:
        """The elements that seam:write it."""
        return self._related(self._subjects(SEAM.writes), SEAM.writes)

    @property
    def stored_in(self) -> Many[Container]:
        """The store containers it is seam:storedIn (ADR-0011)."""
        from .architecture import Container

        return self._many(Container, self._objects(SEAM.storedIn), SEAM.storedIn)


def effective_lifecycles(ds: Dataset, shape: Node) -> list[URIRef]:
    """The machines ``shape`` reaches by seam:lifecycle, directly or through
    its sh:targetClass (ADR-0031 section 2), sorted and distinct. A
    well-formed shape reaches at most one; the same machine reached both
    ways counts once."""
    direct = set(ds.objects(shape, SEAM.lifecycle))
    via = {m for cls in ds.objects(shape, SH.targetClass) for m in ds.objects(cls, SEAM.lifecycle)}
    return sorted({m for m in direct | via if isinstance(m, URIRef)}, key=str)


def _wire(f: Field, value: Node) -> Literal | None:
    """The wire value of one example value of ``f``: a literal as is, a member IRI as its label."""
    if isinstance(value, Literal):
        return value
    if isinstance(value, URIRef) and value in f.members:
        return Literal(f.options[f.members.index(value)])
    return None


def _depths(ds: Dataset, machine: URIRef) -> dict[URIRef, int]:
    """Each state's breadth-first distance from the lifecycle's state:initial
    over its transitions' state:from / state:to; unreachable states are absent."""
    edges: dict[Node, set[URIRef]] = {}
    for transition in ds.objects(machine, STATE.hasTransition):
        targets = {t for t in ds.objects(transition, STATE.to) if isinstance(t, URIRef)}
        for source in ds.objects(transition, STATE["from"]):
            edges.setdefault(source, set()).update(targets)
    level = sorted({s for s in ds.objects(machine, STATE.initial) if isinstance(s, URIRef)}, key=str)
    depth: dict[URIRef, int] = {}
    distance = 0
    while level:
        depth.update((state, distance) for state in level)
        level = sorted({t for s in level for t in edges.get(s, set()) if t not in depth}, key=str)
        distance += 1
    return depth
