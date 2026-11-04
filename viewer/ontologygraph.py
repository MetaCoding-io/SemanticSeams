"""Class view and ontology health for seam:Ontology models (ADR-0022 sections 5 and 6).

ontology_graph_data() reads a seam:Ontology model through the typed view
(seams model.ontologies) and returns the (nodes, edges) pair the shared ELK
card renderer draws, as viewer/shapegraph.py does for shape graphs:

- one card per owl:Class of the model, labelled, described by its
  skos:definition; a class some property has as rdfs:domain is a frame
  holding one child card per such property;
- a "subClassOf" edge from each class to each rdfs:subClassOf target. A
  target declared in the model is its card; one declared in a resolved import
  (gist) is a read-only card in the "other" colour, labelled from the vendored
  file; one declared nowhere is a read-only "Undeclared class" card, the typo
  the health panel warns about.

Nodes are sorted by (parent, id) and edges by (from, to, label), so the ELK
layout is the same on every load (P002).

ontology_health() gives the health panel each owl:imports and its status, and
superclass_warnings() one warning per undeclared superclass. The viewer loads
the model with the import check off (ADR-0022 section 5), so a broken import is
a health fact here rather than a model that does not open. Superclasses of an
ontology with an unresolved import are not warned about: the import fault
already says why they are not found. The graph helpers come from viewer.app
through a late import, because viewer.app imports this module.
"""

from __future__ import annotations

import seams
from rdflib import RDF, RDFS, URIRef

IMPORTED_TYPE_LABEL = "Imported class"
UNDECLARED_TYPE_LABEL = "Undeclared class"


def _app():
    from viewer import app

    return app


def _ontology(model: seams.Model, model_iri: str) -> seams.Ontology | None:
    for ontology in model.ontologies:
        if str(ontology.iri) == model_iri:
            return ontology
    return None


def _broken(model: seams.Model) -> set[URIRef]:
    """The ontologies with at least one import that does not resolve."""
    return {s.ontology for s in model.import_statuses if not s.resolved}


def _property_card(cls: seams.OntologyClass, prop: seams.Element) -> dict:
    app = _app()
    graph = app.get_graph()
    ranges = sorted(app.qname(r) for r in graph.objects(prop.iri, RDFS.range))
    types = sorted(str(t) for t in graph.objects(prop.iri, RDF.type))
    type_q = app.qname(URIRef(types[0])) if types else "Property"
    return {
        "id": f"{cls.iri}::property::{app.qname(prop.iri)}",
        "label": prop.label,
        "group": type_q,
        "type": type_q,
        "typeLabel": "Property",
        "description": f"→ {', '.join(ranges)}" if ranges else None,
        "layer": "data",
        "seams": [],
        "parent": str(cls.iri),
        "nestedVia": None,
        "focused": False,
        "navigateTo": str(prop.iri),
    }


def _superclass_card(sup: seams.Superclass) -> dict:
    imported = sup.source is not None
    if imported:
        description = sup.definition or f"from {seams.local_name(sup.source)}"
    else:
        description = "declared neither in the ontology nor in a resolved import"
    return {
        "id": str(sup.iri),
        "label": sup.label,
        "group": "owl:Class",
        "type": "owl:Class",
        "typeLabel": IMPORTED_TYPE_LABEL if imported else UNDECLARED_TYPE_LABEL,
        "description": description,
        "layer": "other",
        "seams": [],
        "parent": None,
        "nestedVia": None,
        "focused": False,
        "navigateTo": None,
        "readOnly": True,
    }


def ontology_graph_data(model_iri: str, focus: str | None = None) -> tuple[list[dict], list[dict]]:
    """Class cards, property cards, superclass cards and subClassOf edges of a
    seam:Ontology model; ([], []) when model_iri is no ontology model."""
    app = _app()
    model = app.get_model()
    ontology = _ontology(model, model_iri)
    if ontology is None:
        return [], []
    classes = ontology.classes()
    declared = {str(c.iri) for c in classes}
    base = {n["id"]: n for n in app.nodes_for(declared)}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for cls in classes:
        iri = str(cls.iri)
        nodes[iri] = {
            **base[iri],
            "label": cls.label,
            "typeLabel": "Class",
            "description": cls.definition,
            "parent": None,
            "nestedVia": None,
            "focused": iri == focus,
            "navigateTo": iri,
        }
        for prop in cls.properties:
            card = _property_card(cls, prop)
            nodes[card["id"]] = card
        for sup in cls.superclasses:
            target = str(sup.iri)
            if target not in declared and target not in nodes:
                nodes[target] = _superclass_card(sup)
            edges.append({"from": iri, "to": target, "label": "subClassOf"})
    ordered = sorted(nodes.values(), key=lambda n: (n["parent"] or "", n["id"]))
    edges.sort(key=lambda e: (e["from"], e["to"], e["label"]))
    return ordered, edges


def ontology_health(model: seams.Model) -> list[dict]:
    """One entry per owl:imports of every seam:Ontology model, sorted by
    (ontology, import): the vendored version it resolves to, or the
    ResolutionError facts (subject, predicate, detail) when it does not."""
    out = []
    for status in model.import_statuses:
        error = status.error
        out.append(
            {
                "ontology": str(status.ontology),
                "imported": str(status.imported),
                "label": seams.local_name(status.imported),
                "resolved": status.resolved,
                "vendored": str(status.vendored.version) if status.vendored is not None else None,
                "error": (
                    None
                    if error is None
                    else {"subject": str(error.subject), "predicate": str(error.predicate), "detail": error.detail}
                ),
            }
        )
    return out


def superclass_warnings(model: seams.Model) -> list[dict]:
    """One Warning per rdfs:subClassOf target declared neither in its ontology
    nor in a resolved import (ADR-0022 section 5), sorted by class then target.
    Ontologies with an unresolved import are skipped."""
    broken = _broken(model)
    found = sorted(
        (cls.iri, sup.iri)
        for ontology in model.ontologies
        if ontology.iri not in broken
        for cls in ontology.classes()
        for sup in cls.superclasses
        if sup.source is None
    )
    return [
        {
            "focusNode": str(cls),
            "path": str(RDFS.subClassOf),
            "message": f"{sup} is declared neither in the ontology nor in a resolved import (a likely typo)",
            "severity": "Warning",
            "sourceShape": None,
        }
        for cls, sup in found
    ]


__all__ = ["ontology_graph_data", "ontology_health", "superclass_warnings"]
