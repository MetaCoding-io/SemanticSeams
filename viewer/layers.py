"""Layer mode data (M008/S03, backlog item 11).

build_layers() projects the loaded model onto its six layers: one entry per
layer (in LAYER_ORDER) with the layer's models, their members as
nodes, and the edges that run between two nodes of the same layer. Every seam
triple whose ends sit in two different layers is a cross-layer seam, tagged
with its reveal mode (open, nest or layer) so the client can choose which to
draw. Elements whose layer is "other" (in no model, or in a model whose
notation maps to no layer) are listed in warnings instead of being dropped.

Everything is sorted, so the same model always gives the same JSON. The
loaded model and the label/layer/reveal helpers come from viewer.app through
a late import, because viewer.app imports this module.
"""

from __future__ import annotations

from urllib.parse import quote

from rdflib import RDF, URIRef

# Stacking order of the planes, top to bottom: from the deployed system down
# to the data and lifecycles it keeps (the six layers of LAYER_BY_NOTATION).
LAYER_ORDER = ("architecture", "interaction", "process", "decision", "data", "lifecycle")

# Triples that place an element rather than relate it to another element.
STRUCTURAL_PREDICATES = {RDF.type}


def build_layers() -> dict:
    from viewer import app

    graph = app.get_graph()
    layer_ids = [lid for lid in LAYER_ORDER if lid in app.LAYER_BY_NOTATION.values()]
    layer_cache: dict[str, str] = {}

    def layer(iri: str) -> str:
        if iri not in layer_cache:
            layer_cache[iri] = app.layer_of(iri)
        return layer_cache[iri]

    others: dict[str, str] = {}

    models: dict[str, list[str]] = {lid: [] for lid in layer_ids}
    for m in sorted({str(s) for s in graph.subjects(app.SEAM.notation, None)}):
        lid = layer(m)
        if lid in models:
            models[lid].append(m)
        else:
            others[m] = f"model notation '{app.notation_of(m)}' maps to no layer"

    nodes: dict[str, set[str]] = {lid: set() for lid in layer_ids}
    for lid, ms in models.items():
        for m in ms:
            nodes[lid].update(app.model_members(m))
    node_layer = {n: lid for lid, ns in nodes.items() for n in ns}

    edges: dict[str, list[dict]] = {lid: [] for lid in layer_ids}
    seams: list[dict] = []
    for s, p, o in graph.triples((None, None, None)):
        if not isinstance(o, URIRef) or p in STRUCTURAL_PREDICATES or p in app.SEAM_ADMIN_PREDICATES:
            continue
        src, dst = str(s), str(o)
        if app.is_seam_predicate(p):
            src_layer, dst_layer = layer(src), layer(dst)
            ends_other = [iri for iri, lid in ((src, src_layer), (dst, dst_layer)) if lid == "other"]
            for iri in ends_other:
                others.setdefault(iri, "seam end in no layer")
            if ends_other:
                continue
            if src_layer != dst_layer:
                seams.append(
                    {
                        "source": src,
                        "target": dst,
                        "predicate": app.qname(p),
                        "predicateLabel": app.predicate_label(p),
                        "reveal": app.reveal_mode(p),
                        "sourceLayer": src_layer,
                        "targetLayer": dst_layer,
                    }
                )
                continue
        lid = node_layer.get(src)
        if lid is not None and node_layer.get(dst) == lid:
            edges[lid].append({"from": src, "to": dst, "label": app.qname(p)})

    for m in sorted({str(s) for s in graph.subjects(app.SEAM.inModel, None)}):
        if m not in node_layer:
            others.setdefault(m, "member of a model in no layer")

    layers = [
        {
            "id": lid,
            "label": lid.capitalize(),
            "models": [{"iri": m, "label": app.label(m), "href": f"/view/{quote(m, safe='')}"} for m in models[lid]],
            "nodes": [
                {"iri": n, "label": app.label(n), "type": app.qname(t) if (t := app.primary_type(n)) else "Element"}
                for n in sorted(nodes[lid])
            ],
            "edges": sorted(edges[lid], key=lambda e: (e["from"], e["to"], e["label"])),
        }
        for lid in layer_ids
    ]
    seams.sort(key=lambda s: (s["source"], s["predicate"], s["target"]))
    warnings = [
        {"iri": iri, "label": app.label(iri), "message": f"{app.label(iri)} is not drawn: {reason}"}
        for iri, reason in sorted(others.items())
    ]
    return {"layers": layers, "seams": seams, "warnings": warnings}
