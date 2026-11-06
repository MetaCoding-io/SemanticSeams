"""Cross-aggregate invariants: a profile's rules on instance data (ADR-0036).

An **instance-data rule** is a ``sh:NodeShape`` of the attached profile's
shapes graph (``seams.resolve_profile``) with ``sh:severity sh:Warning`` and
at least one ``sh:sparql`` constraint. ``instance_rules`` names them, sorted.

``lift`` builds the data graph the rules run on from the store: every stored
shape of the model (a ``sh:NodeShape`` that is ``seam:storedIn`` a store), in
IRI order, is read with ``store.query(shape)``, and each entity's data keys
that are fields of the shape's contract go through ``contracts.to_rdf`` with
the focus node ``urn:seams:entity:<percent-encoded id>``. Only the shape's
``sh:path``s are used: no ``rdf:type``, no store column and no ``seam:`` term
(ADR-0001). The graphs are unioned, so a rule can join two shapes. A stored
entity ``to_rdf`` refuses raises its ``ContractViolation``: it is a store
fault, not skipped. Nothing is written.

``data_health`` validates the lifted graph against the rules only, inference
off and no ontology merged, and returns one ``Finding`` per result (shape,
focus, message, severity), sorted. A model whose profile holds no rule gives
``[]`` without reading the store. ``Runtime.data_health`` resolves the
profile, logs the count and emits the ``seams.data_health`` span; no write
path calls either.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from pyshacl import validate as _shacl_validate
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SH

from .contracts import shape_contract, to_rdf
from .model import SEAM, ModelGraph, local_name

ENTITY_FOCUS = "urn:seams:entity:"


@dataclass(frozen=True, order=True)
class Finding:
    """One result of an instance-data rule: the rule's shape, the entity (or
    joined value) it is about, its message and its severity's local name."""

    shape: str
    focus: str
    message: str
    severity: str


def entity_focus(entity_id: str) -> URIRef:
    """The focus node an entity is lifted under (never written anywhere)."""
    return URIRef(ENTITY_FOCUS + quote(str(entity_id), safe=""))


def instance_rules(shapes: Graph) -> list[URIRef]:
    """The profile's instance-data rules: sh:Warning node shapes with a sh:sparql constraint."""
    return sorted(
        s
        for s in set(shapes.subjects(RDF.type, SH.NodeShape))
        if isinstance(s, URIRef) and (s, SH.severity, SH.Warning) in shapes and shapes.value(s, SH.sparql) is not None
    )


def stored_shapes(model: ModelGraph) -> list[URIRef]:
    """Every sh:NodeShape of the model that is seam:storedIn a store, by IRI."""
    shape_graph = model.shape_graph()
    return sorted(
        s
        for s in set(model.ds.subjects(SEAM.storedIn, None))
        if isinstance(s, URIRef) and (s, RDF.type, SH.NodeShape) in shape_graph
    )


def lift(model: ModelGraph, store) -> Graph:
    """The stored entities of every stored shape as one RDF graph, through
    the shape contracts' sh:paths only."""
    data = Graph()
    for shape in stored_shapes(model):
        fields = shape_contract(model, shape).fields
        for row in store.query(shape):
            payload = {k: v for k, v in sorted(row["data"].items()) if k in fields}
            graph, _focus, _normalised = to_rdf(model, shape, payload, focus=entity_focus(row["id"]))
            data += graph
    return data


def data_health(model: ModelGraph, store, shapes: Graph) -> list[Finding]:
    """The findings of the instance-data rules in ``shapes`` (a resolved
    profile's shapes graph) on the store's entities, sorted."""
    rules = instance_rules(shapes)
    if not rules:
        return []
    _conforms, results, _text = _shacl_validate(
        lift(model, store),
        shacl_graph=shapes,
        use_shapes=rules,
        inference="none",
        advanced=False,
    )
    findings = set()
    for r in results.subjects(RDF.type, SH.ValidationResult):
        severity = results.value(r, SH.resultSeverity)
        findings.add(
            Finding(
                str(results.value(r, SH.sourceShape)),
                str(results.value(r, SH.focusNode)),
                str(results.value(r, SH.resultMessage) or ""),
                local_name(severity) if severity is not None else "",
            )
        )
    return sorted(findings)
