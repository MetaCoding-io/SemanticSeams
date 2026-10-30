"""SHACL shape graph projection for the shared ELK card renderer (M007/S03, D022).

shapegraph_graph_data() reads a seam:ShapeGraph model and returns the same
(nodes, edges) pair the C4 branch hands to ELK:

- one frame per sh:NodeShape member of the model (parent None);
- one child card per sh:property of that shape, described by its datatype or
  "→ target", its "min..max" cardinality and "one of N" for sh:in;
- an edge from a property card to the shape its sh:class / sh:node names,
  when that shape is a NodeShape member of the same model.

Property shapes without an sh:path are skipped (they have no stable id).
A cyclic sh:node only yields edges; nothing recurses. Output is sorted so
repeated calls give identical JSON. The graph helpers come from viewer.app
through a late import, because viewer.app imports this module.
"""

from __future__ import annotations

from rdflib import RDF, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH

SEAM_IN_MODEL = URIRef("https://w3id.org/seams/seam#inModel")
REFERENCE_PREDICATES = ((SH["class"], "sh:class"), (SH.node, "sh:node"))


def _app():
    from viewer import app

    return app


def _int(val, default):
    try:
        return int(val.toPython())
    except (AttributeError, TypeError, ValueError):
        return default


def _shape_label() -> str:
    return _app().ontology_labels().get(str(SH.NodeShape), "Node shape")


def _property_cards(shape: str, shapes: set[str]) -> tuple[list[dict], list[dict]]:
    app = _app()
    graph = app.get_graph()
    rows = []
    for prop in graph.objects(URIRef(shape), SH.property):
        path = graph.value(prop, SH.path)
        if not isinstance(path, URIRef):
            continue
        path_q = app.qname(path)
        order = _int(graph.value(prop, SH.order), None)

        parts = []
        target, via = None, None
        datatype = graph.value(prop, SH.datatype)
        if datatype is not None:
            parts.append(app.qname(datatype))
        else:
            for pred, kind in REFERENCE_PREDICATES:
                ref = graph.value(prop, pred)
                if ref is not None:
                    target, via = str(ref), kind
                    parts.append(f"→ {app.label(target)}")
                    break
        min_count = _int(graph.value(prop, SH.minCount), 0)
        max_val = graph.value(prop, SH.maxCount)
        max_count = _int(max_val, "*") if max_val is not None else "*"
        parts.append(f"{min_count}..{max_count}")
        in_list = graph.value(prop, SH["in"])
        if in_list is not None:
            parts.append(f"one of {len(list(Collection(graph, in_list)))}")

        name = graph.value(prop, SH.name)
        card_id = f"{shape}::property::{path_q}"
        in_model_target = target if target in shapes else None
        rows.append(
            (
                (order is None, order or 0, path_q),
                {
                    "id": card_id,
                    "label": str(name) if name is not None else app.short_name(str(path)),
                    "group": "sh:PropertyShape",
                    "type": "sh:PropertyShape",
                    "typeLabel": "Property",
                    "description": " · ".join(parts),
                    "layer": "data",
                    "seams": [],
                    "parent": shape,
                    "nestedVia": None,
                    "focused": False,
                    "navigateTo": in_model_target or shape,
                },
                {"from": card_id, "to": in_model_target, "label": via} if in_model_target else None,
            )
        )
    rows.sort(key=lambda r: r[0])
    return [r[1] for r in rows], [r[2] for r in rows if r[2]]


def shapegraph_graph_data(model_iri: str, focus: str | None = None) -> tuple[list[dict], list[dict]]:
    """Frames, property cards and reference edges of a shapegraph model; ([], [])
    when model_iri holds no sh:NodeShape."""
    app = _app()
    graph = app.get_graph()
    shapes = {str(s) for s in graph.subjects(SEAM_IN_MODEL, URIRef(model_iri)) if (s, RDF.type, SH.NodeShape) in graph}
    type_label = _shape_label()
    frames = sorted(app.nodes_for(shapes), key=lambda n: n["id"])
    nodes, edges = [], []
    for frame in frames:
        nodes.append(
            {
                **frame,
                "typeLabel": type_label,
                "parent": None,
                "nestedVia": None,
                "focused": frame["id"] == focus,
                "navigateTo": frame["id"],
            }
        )
    for frame in frames:
        cards, card_edges = _property_cards(frame["id"], shapes)
        nodes.extend(cards)
        edges.extend(card_edges)
    edges.sort(key=lambda e: (e["from"], e["to"]))
    return nodes, edges
