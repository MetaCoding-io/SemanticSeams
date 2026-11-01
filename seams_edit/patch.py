"""The patch: a frozen value holding the quads an edit adds and removes (ADR-0017)."""

from collections.abc import Iterable
from dataclasses import dataclass

from rdflib.term import BNode, Literal, Node, URIRef

# (subject, predicate, object, graph). The graph of a default-graph statement is
# rdflib's DATASET_DEFAULT_GRAPH_ID.
Quad = tuple[Node, Node, Node, Node]


class PatchError(Exception):
    """A patch the write path cannot apply.

    The message names the subject and the predicate of the quad, and the reason, so the
    author can find the fact. These are writer faults, not shape faults: an edit that
    only breaks the shapes is applied and flagged elsewhere (principle 5).
    """

    def __init__(self, subject: object, predicate: object, detail: str = "") -> None:
        self.subject = str(subject)
        self.predicate = str(predicate)
        self.detail = detail
        message = f"{self.subject}: {self.predicate}"
        super().__init__(f"{message}: {detail}" if detail else message)


def term_text(term: Node) -> str:
    """A term as N-Triples would write it; never raises, unlike rdflib's ``n3()``."""
    if isinstance(term, URIRef):
        return f"<{term}>"
    if isinstance(term, BNode):
        return f"_:{term}"
    if isinstance(term, Literal):
        suffix = f"@{term.language}" if term.language else f"^^<{term.datatype}>" if term.datatype else ""
        return f'"{term}"{suffix}'
    return str(term)


def _term_key(term: Node) -> tuple[int, str]:
    rank = 0 if isinstance(term, URIRef) else 1 if isinstance(term, BNode) else 2 if isinstance(term, Literal) else 3
    return rank, term_text(term)


def quad_key(quad: Quad) -> tuple[tuple[int, str], ...]:
    """Sort key for a quad: graph, subject, predicate, object (principle 6)."""
    s, p, o, g = quad
    return _term_key(g), _term_key(s), _term_key(p), _term_key(o)


def _sorted(quads: Iterable[Quad]) -> tuple[Quad, ...]:
    return tuple(sorted(set(quads), key=quad_key))


@dataclass(frozen=True, init=False)
class Patch:
    """Quads added and quads removed, each sorted by graph, subject, predicate, object.

    A quad may not be both added and removed. Duplicates collapse, so two patches with
    the same quads are equal whatever order they were given in.
    """

    adds: tuple[Quad, ...]
    removes: tuple[Quad, ...]

    def __init__(self, adds: Iterable[Quad] = (), removes: Iterable[Quad] = ()) -> None:
        added, removed = _sorted(adds), _sorted(removes)
        both = set(added) & set(removed)
        if both:
            s, p, _, _ = min(both, key=quad_key)
            raise PatchError(s, p, "the patch both adds and removes this quad")
        object.__setattr__(self, "adds", added)
        object.__setattr__(self, "removes", removed)

    @property
    def is_empty(self) -> bool:
        return not self.adds and not self.removes

    def inverse(self) -> "Patch":
        """The patch that undoes this one: adds and removes swapped."""
        return Patch(adds=self.removes, removes=self.adds)
