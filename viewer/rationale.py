"""The inspector's Why section (backlog X8, M033/S02, ADR-0045).

``why(graph, focus)`` lists the ``arch:DecisionRecord``s whose
``dcterms:references`` name the focused element: one ``WhyRow`` per record,
with its ``dcterms:identifier``, its ``rdfs:label``, the ``rdfs:seeAlso``
document it links to (None without one) and the record's IRI, sorted by
identifier and then IRI so the same model gives the same section.

The shapes (``seamsh:DecisionRecordShape``) require one label and one
identifier; a record that breaks them is still listed, falling back to its
IRI, so a model under repair still says why. Blank-node records are skipped:
the viewer can neither name nor link them (``DecisionRecordIriShape``).
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import RDF, RDFS, Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS

ARCH = Namespace("https://w3id.org/seams/arch#")


@dataclass(frozen=True)
class WhyRow:
    identifier: str
    label: str
    href: str | None
    iri: str


def why(graph: Graph, focus: str) -> list[WhyRow]:
    """The decision records referencing ``focus``, sorted by (identifier, IRI)."""
    rows: set[WhyRow] = set()
    for record in graph.subjects(DCTERMS.references, URIRef(focus)):
        if not isinstance(record, URIRef) or (record, RDF.type, ARCH.DecisionRecord) not in graph:
            continue
        identifier = graph.value(record, DCTERMS.identifier)
        title = graph.value(record, RDFS.label)
        doc = graph.value(record, RDFS.seeAlso)
        rows.add(
            WhyRow(
                identifier=str(identifier) if identifier is not None else str(record),
                label=str(title) if title is not None else str(record),
                href=str(doc) if isinstance(doc, URIRef) else None,
                iri=str(record),
            )
        )
    return sorted(rows, key=lambda r: (r.identifier, r.iri))
