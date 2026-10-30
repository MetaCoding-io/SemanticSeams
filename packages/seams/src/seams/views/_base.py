"""The view core: ``Many``, ``Element`` and the ``Views`` registry.

A view answers with collections, never with "the one": every list is a
``Many``, an immutable tuple built from an explicitly sorted iterable, and a
caller that needs exactly one says so with ``.only()``. ``.only()`` raises
``ResolutionError`` naming the subject and predicate that produced the list,
so the error points at the missing (or duplicated) graph fact.

Elements are frozen dataclasses interned per ``Views`` registry: a
cross-layer edge (an operation's ``exposed_by``) and the layer's own list
(``model.architecture.containers()``) hand back the same object.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, Self, TypeVar, cast

from rdflib import RDF, Dataset, URIRef
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import SEAM

if TYPE_CHECKING:
    from ..loader import Model


class HasIri(Protocol):
    @property
    def iri(self) -> URIRef: ...


T = TypeVar("T", bound=HasIri)
E = TypeVar("E", bound="Element")


def by_iri(item: HasIri) -> str:
    """The default sort key of every ``Many``."""
    return str(item.iri)


class Many(tuple[T, ...]):
    """An immutable, ordered collection of view items.

    ``subject`` and ``predicate`` name the graph fact the collection was read
    from (the model and ``rdf:type`` for a layer's list, the owning element
    and the edge predicate for an edge list). Build one with ``sorted_many``,
    which sorts, or pass items that are already in their documented order.
    """

    subject: str
    predicate: str
    _curie: Callable[[object], URIRef] | None

    def __new__(
        cls,
        items: Iterable[T] = (),
        subject: object = "",
        predicate: object = "",
        curie: Callable[[object], URIRef] | None = None,
    ) -> Self:
        self = super().__new__(cls, items)
        self.subject = str(subject)
        self.predicate = str(predicate)
        self._curie = curie
        return self

    def only(self) -> T:
        """The single item; ``ResolutionError(subject, predicate)`` otherwise."""
        if len(self) != 1:
            raise ResolutionError(
                self.subject, self.predicate, f"expected exactly one, found {[str(i) for i in self.iris()]}"
            )
        return self[0]

    def by_iri(self, iri: object) -> T:
        """The item with this IRI (or CURIE such as ``":chat_api"``)."""
        target = self._expand(iri)
        for item in self:
            if item.iri == target:
                return item
        raise ResolutionError(self.subject, self.predicate, f"{target} not among {[str(i) for i in self.iris()]}")

    def where(self, pred: Callable[[T], bool]) -> Many[T]:
        """The items ``pred`` keeps, in the same order and naming the same fact."""
        return Many([item for item in self if pred(item)], self.subject, self.predicate, self._curie)

    def iris(self) -> tuple[URIRef, ...]:
        return tuple(item.iri for item in self)

    def _expand(self, iri: object) -> URIRef:
        if isinstance(iri, URIRef):
            return iri
        text = str(iri)
        if self._curie is None or "://" in text or text.startswith("urn:"):
            return URIRef(text)
        return self._curie(text)


def sorted_many[I: HasIri](
    items: Iterable[I],
    subject: object,
    predicate: object,
    curie: Callable[[object], URIRef] | None = None,
    key: Callable[[I], Any] = by_iri,
) -> Many[I]:
    """A ``Many`` of the distinct items (by IRI), sorted by ``key`` (default ``str(iri)``)."""
    seen: dict[URIRef, I] = {}
    for item in items:
        seen.setdefault(item.iri, item)
    return Many(sorted(seen.values(), key=key), subject, predicate, curie)


# rdf:type -> element class, filled by @element_type as the view modules load.
_TYPES: dict[URIRef, type[Element]] = {}


def element_type(*rdf_types: URIRef) -> Callable[[type[E]], type[E]]:
    """Register an element class as the typed answer for these rdf:types."""

    def register(cls: type[E]) -> type[E]:
        for t in rdf_types:
            _TYPES[t] = cls
        return cls

    return register


@dataclass(frozen=True, eq=False)
class Element:
    """A graph element seen through a view.

    ``iri`` is the node, ``label`` its rdfs:label (or local name) and
    ``model`` the ``seam:Model`` it is ``seam:inModel`` (None when the
    element names none). Equality and hashing go by type and IRI.
    """

    iri: URIRef
    label: str
    model: URIRef | None
    views: Views = field(compare=False, repr=False, hash=False)

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.iri == cast(Element, other).iri

    def __hash__(self) -> int:
        return hash((type(self), self.iri))

    @property
    def raw(self) -> URIRef:
        """The rdflib node behind the element."""
        return self.iri

    @property
    def graph(self) -> Dataset:
        return self.views.ds

    @property
    def edges(self) -> tuple[tuple[URIRef, Node], ...]:
        """Every outgoing ``seam:`` triple as (predicate, object), sorted."""
        found = {
            (cast(URIRef, p), o) for p, o in self.views.ds.predicate_objects(self.iri) if str(p).startswith(str(SEAM))
        }
        return tuple(sorted(found, key=lambda po: (str(po[0]), str(po[1]))))

    # ── helpers for the view modules ──

    def _objects(self, predicate: URIRef) -> list[URIRef]:
        return self.views.iris(self.views.ds.objects(self.iri, predicate))

    def _subjects(self, predicate: URIRef) -> list[URIRef]:
        return self.views.iris(self.views.ds.subjects(predicate, self.iri))

    def _value(self, predicate: URIRef) -> Node | None:
        return self.views.ds.value(self.iri, predicate)

    def _text(self, predicate: URIRef) -> str | None:
        value = self._value(predicate)
        return None if value is None else str(value)

    def _many(self, cls: type[E], iris: Iterable[URIRef], predicate: URIRef) -> Many[E]:
        return self.views.many(cls, iris, self.iri, predicate)

    def _related(self, iris: Iterable[URIRef], predicate: URIRef) -> Many[Element]:
        """Elements of whatever type the graph says they are."""
        views = self.views
        return sorted_many((views.resolve(i) for i in iris), self.iri, predicate, views.model.curie)


def optional[I: HasIri](items: Many[I]) -> I | None:
    """None for an empty collection, the item for one, ResolutionError for more."""
    return None if not items else items.only()


class Views:
    """Per-model registry: builds each view once and interns every element,
    so the same IRI always answers with the same object. Caches live on the
    instance (never module-level, id()-keyed; MEM010)."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.ds: Dataset = model.ds
        self._elements: dict[tuple[type[Element], URIRef], Element] = {}
        self._views: dict[str, object] = {}

    def iris(self, nodes: Iterable[Node]) -> list[URIRef]:
        """The IRIs among ``nodes`` (blank nodes and literals left out), sorted and distinct."""
        return sorted({n for n in nodes if isinstance(n, URIRef)}, key=str)

    def typed(self, rdf_type: URIRef) -> list[URIRef]:
        return self.iris(self.ds.subjects(RDF.type, rdf_type))

    def intern(self, cls: type[E], iri: URIRef) -> E:
        key = (cls, iri)
        found = self._elements.get(key)
        if found is None:
            inmodel = self.ds.value(iri, SEAM.inModel)
            found = cls(iri, self.model.label(iri), inmodel if isinstance(inmodel, URIRef) else None, self)
            self._elements[key] = found
        return cast(E, found)

    def resolve(self, iri: URIRef) -> Element:
        """The element for ``iri``, typed by the first registered rdf:type it
        has (sorted by IRI); a plain ``Element`` when none is registered."""
        for t in self.iris(self.ds.objects(iri, RDF.type)):
            cls = _TYPES.get(t)
            if cls is not None:
                return self.intern(cls, iri)
        return self.intern(Element, iri)

    def many(self, cls: type[E], iris: Iterable[URIRef], subject: object, predicate: object) -> Many[E]:
        return sorted_many((self.intern(cls, i) for i in iris), subject, predicate, self.model.curie)

    def all(self, cls: type[E], rdf_type: URIRef) -> Many[E]:
        """Every subject of ``rdf_type`` as ``cls``; errors name the model and rdf:type."""
        return self.many(cls, self.typed(rdf_type), self.model.subject, RDF.type)

    def view(self, name: str, build: Callable[[], object]) -> Any:
        if name not in self._views:
            self._views[name] = build()
        return self._views[name]
