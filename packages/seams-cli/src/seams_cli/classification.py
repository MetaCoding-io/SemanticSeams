"""The shared change classification (ADR-0021 section 7): two verdicts and one ``Change`` record.

``seams diff`` (``seams_cli.diff``) classifies a model's shape and operation-contract
changes with these verdicts; the vocabulary gate (``seams_cli.vocabulary_gate``)
classifies changes to the vocabularies in ``ontology/`` with the same ones. A
``compatible`` change is widening (a minor bump, no migration); a ``breaking`` one
is not (a major bump and a migration step).

``classify_terms`` holds the rules for vocabulary terms. A term is a subject the
vocabulary file gives an ``rdf:type`` (a class, a property or an individual),
other than the ``owl:Ontology`` itself:

- an added term, a newly ``owl:deprecated`` term, or a looser ``rdfs:domain`` or
  ``rdfs:range`` is compatible;
- a removed term, a renamed term (an old-only and a new-only term linked in NEW by
  ``owl:sameAs``, ``owl:equivalentClass``, ``owl:equivalentProperty``,
  ``dct:isReplacedBy`` or ``dct:replaces``) or a narrower or unrelated domain or
  range is breaking.

A domain or range is a set of classes, read as their intersection. The new set is
looser when every class in it is the same as, or a superclass (``rdfs:subClassOf``,
transitively, over both versions) of, a class in the old set; dropping the
constraint is looser, adding one narrower.
"""

from __future__ import annotations

from typing import NamedTuple

import rdflib
from rdflib.term import Node

COMPATIBLE = "compatible"
BREAKING = "breaking"
ABSENT = "-"

#: The scope of a change to a vocabulary term (``seams diff`` uses ``data`` and ``contract``).
VOCABULARY = "vocabulary"

DCT = rdflib.Namespace("http://purl.org/dc/terms/")
OWL = rdflib.OWL
RDFS = rdflib.RDFS

#: Predicates in NEW that link an old-only term to the new-only term that renames it.
RENAME_PREDICATES = (OWL.sameAs, OWL.equivalentClass, OWL.equivalentProperty, DCT.isReplacedBy, DCT.replaces)


class Change(NamedTuple):
    """One difference. ``subject`` is a shape, operation or term IRI; ``detail`` names the path and values.
    ``contexts`` are the downstream arch:BoundedContexts a change to the subject reaches (``seams diff``,
    ADR-0032 section 2), sorted; empty for a model with no contexts and for vocabulary terms."""

    verdict: str
    kind: str
    subject: str
    detail: str
    scopes: tuple[str, ...]
    contexts: tuple[str, ...] = ()


def sort_changes(changes: list[Change]) -> list[Change]:
    """``changes`` in the one order every report uses."""
    return sorted(changes, key=lambda c: (c.subject, c.kind, c.detail, c.verdict))


def terms(graph: rdflib.Graph) -> set[rdflib.URIRef]:
    """The terms a vocabulary graph defines: typed IRI subjects other than an ``owl:Ontology``."""
    ontologies = set(graph.subjects(rdflib.RDF.type, OWL.Ontology))
    return {s for s in graph.subjects(rdflib.RDF.type, None) if isinstance(s, rdflib.URIRef) and s not in ontologies}


def _key(graph: rdflib.Graph, node: Node) -> str:
    """A stable string for a class; a blank node is spelled out from its triples."""
    if not isinstance(node, rdflib.BNode):
        return str(node)
    parts = sorted(f"{p} {_key(graph, o)}" for p, o in graph.predicate_objects(node))
    return "[" + "; ".join(parts) + "]"


def _classes(graph: rdflib.Graph, term: rdflib.URIRef, predicate: rdflib.URIRef) -> frozenset[str]:
    return frozenset(_key(graph, o) for o in graph.objects(term, predicate))


def _superclasses(graph: rdflib.Graph) -> dict[str, set[str]]:
    """Each class's superclasses, itself included, by ``rdfs:subClassOf`` transitively."""
    direct: dict[str, set[str]] = {}
    for sub, sup in graph.subject_objects(RDFS.subClassOf):
        direct.setdefault(_key(graph, sub), set()).add(_key(graph, sup))
    closed: dict[str, set[str]] = {}
    for start in direct:
        seen = {start}
        todo = [start]
        while todo:
            for sup in direct.get(todo.pop(), set()) - seen:
                seen.add(sup)
                todo.append(sup)
        closed[start] = seen
    return closed


def _looser(old: frozenset[str], new: frozenset[str], supers: dict[str, set[str]]) -> bool:
    """True when the constraint ``new`` admits everything ``old`` admits."""
    return all(any(n in supers.get(o, {o}) for o in old) for n in new)


def _values(values: frozenset[str]) -> str:
    return ",".join(sorted(values)) or ABSENT


def _renames(new: rdflib.Graph, old_only: set[rdflib.URIRef], new_only: set[rdflib.URIRef]) -> dict[str, str]:
    """Old term IRI to new term IRI, from a rename link in NEW, in either direction."""
    renames: dict[str, str] = {}
    for predicate in RENAME_PREDICATES:
        for a, b in sorted(new.subject_objects(predicate)):
            for newer, older in ((a, b), (b, a)):
                if newer in new_only and older in old_only and str(older) not in renames:
                    renames[str(older)] = str(newer)
    return renames


def classify_terms(old: rdflib.Graph, new: rdflib.Graph, hierarchy: rdflib.Graph | None = None) -> list[Change]:
    """Every term change from vocabulary graph OLD to NEW, sorted. ``hierarchy`` (default: OLD and NEW
    together) gives the ``rdfs:subClassOf`` facts that decide whether a domain or range is looser."""
    if hierarchy is None:
        hierarchy = old + new
    supers = _superclasses(hierarchy)
    old_terms, new_terms = terms(old), terms(new)
    renames = _renames(new, old_terms - new_terms, new_terms - old_terms)
    changes: list[Change] = []

    def change(verdict: str, kind: str, term: str, detail: str) -> None:
        changes.append(Change(verdict, kind, term, detail, (VOCABULARY,)))

    for old_iri, new_iri in renames.items():
        change(BREAKING, "term-renamed", new_iri, f"{old_iri} -> {new_iri}")
    for term in sorted(old_terms - new_terms):
        if str(term) not in renames:
            change(BREAKING, "term-removed", str(term), ABSENT)
    for term in sorted(new_terms - old_terms):
        if str(term) not in renames.values():
            change(COMPATIBLE, "term-added", str(term), ABSENT)

    for term in sorted(old_terms & new_terms):
        was = any(o.toPython() is True for o in old.objects(term, OWL.deprecated) if isinstance(o, rdflib.Literal))
        now = any(o.toPython() is True for o in new.objects(term, OWL.deprecated) if isinstance(o, rdflib.Literal))
        if now and not was:
            change(COMPATIBLE, "term-deprecated", str(term), ABSENT)
        for kind, predicate in (("domain-changed", RDFS.domain), ("range-changed", RDFS.range)):
            before, after = _classes(old, term, predicate), _classes(new, term, predicate)
            if before != after:
                verdict = COMPATIBLE if _looser(before, after, supers) else BREAKING
                change(verdict, kind, str(term), f"{_values(before)} -> {_values(after)}")
    return sort_changes(changes)
