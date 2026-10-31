"""SemanticSeams viewer — Phase A POC.

FastAPI server implementing the /view/{iri} contract (ADR-0004) over an
in-process rdflib Dataset loaded through the seams library (seams.load).
SEAMS_MODEL chooses the model, a TriG file or a directory of TriG files loaded
together (default examples/chat-app/chat-app.trig); its payload files must sit
in the model's base directory. The root view is the model's single C4
seam:Model, or SEAMS_VIEWER_ROOT when set. The load is behind get_model() and
get_graph() so a Fuseki-backed store can drop in later without touching routes
or resolution logic.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import seams
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from rdflib import RDF, RDFS, Dataset, Namespace, URIRef
from rdflib.namespace import SH

from viewer import ifml, legend, validation
from viewer import queries as canned_queries
from viewer.levels import C4_LEVELS, DEFAULT_LEVEL, load_rollup
from viewer.shapegraph import shapegraph_graph_data
from viewer.validation import get_model_conformance

# uvicorn configures handlers for its own loggers only, so log through
# uvicorn.error to have the startup line show up in the server output.
logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent
MODEL_ENV = "SEAMS_MODEL"
ROOT_ENV = "SEAMS_VIEWER_ROOT"
DEFAULT_MODEL_PATH = BASE_DIR.parent / "examples" / "chat-app" / "chat-app.trig"


def model_path_from_env() -> Path:
    """SEAMS_MODEL when set and non-empty, else the chat app's TriG."""
    value = os.environ.get(MODEL_ENV)
    return Path(value).resolve() if value else DEFAULT_MODEL_PATH


def model_base_dir(path: Path) -> Path:
    """The directory payloads resolve against: a directory model is its own
    base, a file model's base is its parent (as seams.Model.base_dir)."""
    return path if path.is_dir() else path.parent


MODEL_PATH = model_path_from_env()
MODEL_DIR = model_base_dir(MODEL_PATH)

# ADR-0003 specifies manifest-graph resolution (path/checksum/mediaType via a
# dedicated <urn:seams:graph:manifest> graph). Phase B takes a simplified path:
# seam:renderPayload values are relative IRIs resolved by rdflib against the
# trig file's own path, which already yields a file:// URI under MODEL_DIR — so
# that URI is trusted directly instead of introducing manifest predicates.
PAYLOAD_MEDIA_TYPES = {
    ".bpmn": "application/bpmn+xml",
    ".dmn": "application/dmn+xml",
}

SEAM = Namespace("https://w3id.org/seams/seam#")
ARCH = Namespace("https://w3id.org/seams/arch#")
IFML = Namespace("https://w3id.org/seams/ifml#")
STATE = Namespace("https://w3id.org/seams/state#")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")

NOTATION_LABELS = {
    SEAM.C4: "c4",
    SEAM.IFML: "ifml",
    SEAM.BPMN: "bpmn",
    SEAM.DMN: "dmn",
    SEAM.Statechart: "statechart",
    SEAM.ShapeGraph: "shapegraph",
}

# ADR-0005 (amended M007/S02): each seam predicate declares a seam:reveal mode
# in ontology/seam.ttl. Open and nest predicates navigate on click; layer
# predicates stay inspector-only. See reveal_mode() and navigational_predicates().
REVEAL_MODES = {SEAM.Open: "open", SEAM.Nest: "nest", SEAM.Layer: "layer"}
NAVIGATING_MODES = {"open", "nest"}

# Administrative seam predicates excluded from the seamEdges inspector list —
# they drive rendering/dispatch rather than representing a cross-layer edge.
SEAM_ADMIN_PREDICATES = {SEAM.inModel, SEAM.notation, SEAM.renderPayload}

# Reveal-modes card (docs/research/2026-10-15-reveal-modes.md §1): each
# notation maps to one of six layers, which drives the layer colour tokens.
LAYER_BY_NOTATION = {
    "c4": "architecture",
    "ifml": "interaction",
    "bpmn": "process",
    "dmn": "decision",
    "shapegraph": "data",
    "statechart": "lifecycle",
}

RENDERERS_IMPLEMENTED = {"c4", "ifml", "statechart", "bpmn", "dmn", "shapegraph"}
PAYLOAD_RENDERERS = {"bpmn", "dmn"}

app = FastAPI(title="SemanticSeams Viewer")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


_model: seams.Model | None = None
_root_iri: str | None = None


def configure(path: Path) -> None:
    """Point the viewer at another model and drop the loaded model, root and
    cached conformance (validation keys it by id(ds), which a fresh Dataset
    can reuse, MEM010)."""
    global MODEL_PATH, MODEL_DIR, _model, _root_iri
    MODEL_PATH = Path(path).resolve()
    MODEL_DIR = model_base_dir(MODEL_PATH)
    _model = None
    _root_iri = None
    validation._clear_cache()


def get_model() -> seams.Model:
    """The loaded model (seams.load on MODEL_PATH, on first use)."""
    global _model
    if _model is None:
        if not (MODEL_PATH.is_file() or MODEL_PATH.is_dir()):
            source = f" (from {MODEL_ENV})" if os.environ.get(MODEL_ENV) else ""
            raise FileNotFoundError(f"viewer model not found: {MODEL_PATH}{source}")
        _model = seams.load(MODEL_PATH)
    return _model


def get_graph() -> Dataset:
    """The loaded model's merged Dataset (default_union)."""
    return get_model().ds


def root_iri() -> str:
    """The IRI the viewer opens at: SEAMS_VIEWER_ROOT, else the model's single
    C4 seam:Model. Computed once per loaded model."""
    global _root_iri
    if _root_iri is None:
        override = os.environ.get(ROOT_ENV)
        if override:
            _root_iri = override
        else:
            graph = get_graph()
            candidates = sorted(
                str(s) for s in set(graph.subjects(RDF.type, SEAM.Model)) if (s, SEAM.notation, SEAM.C4) in graph
            )
            if len(candidates) != 1:
                found = ", ".join(candidates) if candidates else "none"
                raise RuntimeError(
                    f"{MODEL_PATH} must have exactly one seam:Model with seam:notation seam:C4 "
                    f"to use as the viewer root (found: {found}); set {ROOT_ENV} to choose one"
                )
            _root_iri = candidates[0]
    return _root_iri


def short_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def qname(iri) -> str:
    graph = get_graph()
    try:
        return graph.qname(iri)
    except Exception:
        return short_name(str(iri))


def label(iri: str) -> str:
    val = get_graph().value(URIRef(iri), RDFS.label)
    return str(val) if val is not None else short_name(iri)


# D004 keeps the seams-loaded Dataset model-only (ontology triples would pollute
# canned SPARQL queries and seam_edges), so predicate labels come from a
# side lookup parsed straight from ontology/*.ttl on first use.
_ontology_labels: dict[str, str] | None = None


def ontology_labels() -> dict[str, str]:
    global _ontology_labels
    if _ontology_labels is None:
        from rdflib import Graph

        g = Graph()
        for p in sorted((BASE_DIR.parent / "ontology").glob("*.ttl")):
            g.parse(p, format="turtle")
        _ontology_labels = {str(s): str(o) for s, o in g.subject_objects(RDFS.label)}
    return _ontology_labels


# Reveal modes come from the same ontology side lookup as labels (D004, D006):
# the annotations never enter the seams-loaded Dataset.
_ontology_reveal: dict[str, str] | None = None


def ontology_reveal() -> dict[str, str]:
    """Predicate IRI -> "open" | "nest" | "layer", from seam:reveal in ontology/*.ttl."""
    global _ontology_reveal
    if _ontology_reveal is None:
        from rdflib import Graph

        g = Graph()
        for p in sorted((BASE_DIR.parent / "ontology").glob("*.ttl")):
            g.parse(p, format="turtle")
        _ontology_reveal = {str(s): REVEAL_MODES[o] for s, o in g.subject_objects(SEAM.reveal) if o in REVEAL_MODES}
    return _ontology_reveal


def reveal_mode(p) -> str:
    """Reveal mode of a predicate: a model-graph seam:reveal wins, then the
    ontology default, then "layer" (unannotated predicates never navigate)."""
    local = get_graph().value(URIRef(str(p)), SEAM.reveal)
    if local in REVEAL_MODES:
        return REVEAL_MODES[local]
    return ontology_reveal().get(str(p), "layer")


def navigational_predicates() -> set[URIRef]:
    """Seam predicates whose reveal mode is open or nest (ADR-0005 as amended)."""
    preds = set(ontology_reveal()) | {str(s) for s in get_graph().subjects(SEAM.reveal, None)}
    return {URIRef(p) for p in preds if reveal_mode(p) in NAVIGATING_MODES}


def predicate_label(p) -> str:
    """Friendly label for a predicate: model-local rdfs:label wins, then the
    ontology lookup, then the qname fallback."""
    pref = URIRef(str(p))
    val = get_graph().value(pref, RDFS.label)
    if val is not None:
        return str(val)
    onto = ontology_labels().get(str(pref))
    if onto is not None:
        return onto
    return qname(pref)


def types_of(iri: str) -> list[str]:
    return [qname(t) for t in get_graph().objects(URIRef(iri), RDF.type)]


def is_model(iri: str) -> bool:
    return (URIRef(iri), SEAM.notation, None) in get_graph()


def notation_of(iri: str) -> str:
    val = get_graph().value(URIRef(iri), SEAM.notation)
    if val is None:
        return "none"
    return NOTATION_LABELS.get(val, short_name(str(val)))


def focused_model(iri: str) -> str | None:
    if is_model(iri):
        return iri
    val = get_graph().value(URIRef(iri), SEAM.inModel)
    return str(val) if val is not None else None


def layer_of(iri: str) -> str:
    """Layer of the model iri lives in (or is) — "other" when it is in no model."""
    model = focused_model(iri)
    return LAYER_BY_NOTATION.get(notation_of(model), "other") if model else "other"


def primary_type(iri: str) -> str | None:
    """IRI of the element's primary rdf:type, or None when it has none.
    Picks deterministically, preferring a domain type over the generic seam:Model."""
    types = sorted(str(t) for t in get_graph().objects(URIRef(iri), RDF.type))
    if not types:
        return None
    domain = [t for t in types if t != str(SEAM.Model)]
    return (domain or types)[0]


def type_label(iri: str) -> str:
    """Friendly label of the element's primary rdf:type for the card's type pill."""
    t = primary_type(iri)
    if t is None:
        return "Element"
    return ontology_labels().get(t, short_name(t))


def description_of(iri: str) -> str | None:
    """One-line card description: rdfs:comment, arch:technology, deploy:version,
    then the version on a deploy:artifact; None when there is none."""
    graph = get_graph()
    subj = URIRef(iri)
    for pred in (RDFS.comment, ARCH.technology, DEPLOY.version):
        val = graph.value(subj, pred)
        if val is not None:
            return str(val)
    for artifact in graph.objects(subj, DEPLOY.artifact):
        val = graph.value(artifact, DEPLOY.version)
        if val is not None:
            return str(val)
    return None


def render_payload_of(iri: str) -> str | None:
    val = get_graph().value(URIRef(iri), SEAM.renderPayload)
    return str(val) if val is not None else None


def resolve_payload_path(payload_iri: str) -> Path:
    """Resolve a seam:renderPayload file:// IRI to a path, rejecting anything
    outside MODEL_DIR so an unexpected payload IRI can't read arbitrary files."""
    parts = urlsplit(payload_iri)
    if parts.scheme != "file":
        raise HTTPException(status_code=404, detail=f"payload {payload_iri} is not a resolvable file")
    candidate = Path(unquote(parts.path)).resolve()
    if MODEL_DIR.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail=f"payload {payload_iri} is outside the model root")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"payload file not found: {candidate}")
    return candidate


def native_element_id(iri: str) -> str | None:
    return iri.rsplit("#", 1)[1] if "#" in iri else None


def is_seam_predicate(p) -> bool:
    return str(p).startswith(str(SEAM)) and p not in SEAM_ADMIN_PREDICATES


def seam_edges(iri: str) -> dict:
    graph = get_graph()
    subj = URIRef(iri)
    outgoing = []
    for p, o in graph.predicate_objects(subj):
        if is_seam_predicate(p):
            outgoing.append(
                {
                    "predicate": qname(p),
                    "predicateLabel": predicate_label(p),
                    "target": str(o),
                    "targetLabel": label(str(o)),
                    "targetLayer": layer_of(str(o)),
                    "reveal": reveal_mode(p),
                    "navigational": reveal_mode(p) in NAVIGATING_MODES,
                }
            )
    incoming = []
    for s, p in graph.subject_predicates(subj):
        if is_seam_predicate(p):
            incoming.append(
                {
                    "predicate": qname(p),
                    "predicateLabel": predicate_label(p),
                    "source": str(s),
                    "sourceLabel": label(str(s)),
                    "sourceLayer": layer_of(str(s)),
                    "reveal": reveal_mode(p),
                    "navigational": reveal_mode(p) in NAVIGATING_MODES,
                }
            )
    return {"outgoing": outgoing, "incoming": incoming}


def detailedby_targets(iri: str) -> list[str]:
    """seam:detailedBy targets of iri that are themselves renderable models."""
    graph = get_graph()
    return [str(t) for t in graph.objects(URIRef(iri), SEAM.detailedBy) if is_model(str(t))]


def candidate_info(iri: str) -> dict:
    return {"iri": iri, "label": label(iri), "notation": notation_of(iri)}


def resolve_navigation(iri: str) -> dict:
    """ADR-0005 resolution algorithm, extended for section 6 disambiguation.

    Returns a dict with:
      - target: the iri to auto-navigate to, or None when ambiguous / unresolved.
      - landing: the iri whose view should be rendered for this request — the
        auto-navigate target when unambiguous, otherwise the element that
        carries the 2+ detailedBy candidates (iri itself for a direct match,
        or the one-hop navigational target for the hop case).
      - candidates: list of {iri, label, notation} when 2+ detailedBy targets
        were found at `landing`, else None.
    """
    if is_model(iri):
        return {"target": iri, "landing": iri, "candidates": None}

    graph = get_graph()
    subj = URIRef(iri)

    direct = detailedby_targets(iri)
    if len(direct) > 1:
        return {"target": None, "landing": iri, "candidates": [candidate_info(t) for t in direct]}
    if direct:
        return {"target": direct[0], "landing": direct[0], "candidates": None}

    for pred in sorted(navigational_predicates() - {SEAM.detailedBy}, key=str):
        for target in graph.objects(subj, pred):
            target = str(target)
            if is_model(target):
                return {"target": target, "landing": target, "candidates": None}
            hops = detailedby_targets(target)
            if len(hops) > 1:
                return {"target": None, "landing": target, "candidates": [candidate_info(t) for t in hops]}
            if hops:
                return {"target": hops[0], "landing": hops[0], "candidates": None}

    return {"target": None, "landing": iri, "candidates": None}


def model_members(model_iri: str) -> list[str]:
    return [str(s) for s in get_graph().subjects(SEAM.inModel, URIRef(model_iri))]


def payload_element_map(model_iri: str) -> dict:
    """Maps native element ids inside a payload diagram (BPMN/DMN element @id,
    which mirrors the fragment/path segment of the model member's own IRI) back
    to the member's full IRI, so a diagram click can resolve to a seam entity."""
    return {short_name(m): m for m in model_members(model_iri)}


def payload_element_seams(model_iri: str) -> dict[str, list[dict]]:
    """Native element id -> its outgoing seams (card_seams shape), for the
    overlay badges drawn on BPMN/DMN diagrams. Seams back to model_iri itself
    are dropped (a badge would only re-open the current view), and so are ids
    left with no seams, so a badge appears only for a seam in the graph."""
    seams = {
        native_id: [s for s in card_seams(iri) if s["target"] != model_iri]
        for native_id, iri in payload_element_map(model_iri).items()
    }
    return {native_id: lst for native_id, lst in seams.items() if lst}


def card_seams(iri: str) -> list[dict]:
    """Outgoing seam edges of iri as card dots, sorted by predicate then target."""
    edges = [(p, str(o)) for p, o in get_graph().predicate_objects(URIRef(iri)) if is_seam_predicate(p)]
    return [
        {
            "predicate": qname(p),
            "predicateLabel": predicate_label(p),
            "target": o,
            "targetLabel": label(o),
            "targetLayer": layer_of(o),
            "reveal": reveal_mode(p),
        }
        for p, o in sorted(edges, key=lambda e: (str(e[0]), e[1]))
    ]


def nodes_for(members: set[str]) -> list[dict]:
    return [
        {
            "id": m,
            "label": label(m),
            "group": (types_of(m) or ["Element"])[0],
            "type": qname(primary_type(m)) if primary_type(m) else "Element",
            "typeLabel": type_label(m),
            "description": description_of(m),
            "layer": layer_of(m),
            "seams": card_seams(m),
        }
        for m in members
    ]


def edges_for_predicates(members: set[str], preds: list[tuple]) -> list[dict]:
    graph = get_graph()
    edges = []
    for pred, kind in preds:
        for s, o in graph.subject_objects(pred):
            if str(s) in members and str(o) in members:
                edges.append({"from": str(s), "to": str(o), "label": kind})
    return edges


def c4_graph_data(model_iri: str, level: str = DEFAULT_LEVEL) -> tuple[list[dict], list[dict]]:
    """Compound C4 graph at one zoom level (ADR-0008, viewer/levels.py).

    Nodes carry a "parent" (the visible node that arch:contains them, or at L3
    seam:exposes them) instead of contains edges, so the renderer can nest.
    Output is sorted so repeated calls and processes give identical JSON.
    """
    graph = get_graph()
    spec = C4_LEVELS[level]
    visible = {
        m for m in model_members(model_iri) if any(t in spec.classes for t in graph.objects(URIRef(m), RDF.type))
    }

    parents: dict[str, str] = {}
    for s, o in graph.subject_objects(ARCH.contains):
        if str(s) in visible and str(o) in visible:
            # min() keeps the choice stable if an element has two containers.
            parents[str(o)] = min(parents.get(str(o), str(s)), str(s))
    if spec.exposed_elements:
        for s, o in graph.subject_objects(SEAM.exposes):
            if str(s) in visible and str(o) not in visible:
                parents[str(o)] = min(parents.get(str(o), str(s)), str(s))
        visible |= {o for o, p in parents.items() if p in visible}

    nested_via: dict[str, str] = {}
    if spec.nest:
        nested_via, nested_layers = _nest_targets(visible, parents)
        visible |= set(nested_via) | {o for o, p in parents.items() if p in nested_via}

    nodes = [{**n, "parent": parents.get(n["id"]), "nestedVia": nested_via.get(n["id"])} for n in nodes_for(visible)]
    if spec.nest:
        for n in nodes:
            if n["id"] in nested_layers and n["layer"] == "other":
                n["layer"] = nested_layers[n["id"]]
    nodes.sort(key=lambda n: (n["parent"] or "", n["id"]))

    if spec.rollup:
        edges = [
            {"from": frm, "to": to, "label": kind, "kind": "rollup"}
            for frm, to, kind in load_rollup(graph)
            if frm in visible and to in visible
        ]
    else:
        edges = [
            {**e, "kind": qname(pred)}
            for pred, kind in spec.edge_rules
            for e in edges_for_predicates(visible, [(pred, kind)])
        ]
    edges.sort(key=lambda e: (e["from"], e["to"], e["label"]))
    return nodes, edges


# Containment predicates that make a model member a child of another member;
# L4 nests only a nested model's top-level members (the ones no sibling holds).
NEST_CONTAINMENT_PREDICATES = (IFML.contains, IFML.hasEvent, IFML.hasParameter, ARCH.contains)


def nested_model_of(iri: str) -> str | None:
    """Model a nest-mode target stands for: itself, else its single detailedBy model."""
    if is_model(iri):
        return iri
    targets = detailedby_targets(iri)
    return targets[0] if len(targets) == 1 else None


def top_level_members(model_iri: str) -> list[str]:
    """Labelled members of model_iri that no other member of it contains."""
    graph = get_graph()
    members = set(model_members(model_iri))
    held = {
        str(o)
        for pred in NEST_CONTAINMENT_PREDICATES
        for s, o in graph.subject_objects(pred)
        if str(s) in members and str(s) != str(o)
    }
    return sorted(m for m in members - held if (URIRef(m), RDFS.label, None) in graph)


def _nest_targets(visible: set[str], parents: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """L4: adds nest-mode seam targets of visible nodes (and their models'
    top-level members) to parents. Returns (target -> qname of the nesting
    predicate, target -> layer of its nested model)."""
    graph = get_graph()
    nested_via: dict[str, str] = {}
    layers: dict[str, str] = {}
    for m in sorted(visible):
        for p, t in sorted(graph.predicate_objects(URIRef(m)), key=lambda po: (str(po[0]), str(po[1]))):
            target = str(t)
            if not isinstance(t, URIRef) or target in visible or reveal_mode(p) != "nest":
                continue
            if target in parents and parents[target] <= m:
                continue
            parents[target] = m
            nested_via[target] = qname(p)
    for target in sorted(nested_via):
        model = nested_model_of(target)
        if model is None:
            continue
        layers[target] = LAYER_BY_NOTATION.get(notation_of(model), "other")
        for member in top_level_members(model):
            if member not in visible and member not in nested_via and member != target:
                parents.setdefault(member, target)
    return nested_via, layers


def ifml_graph_data(model_iri: str) -> tuple[list[dict], list[dict]]:
    members = set(model_members(model_iri))
    nodes = nodes_for(members)
    edges = edges_for_predicates(
        members,
        [
            (IFML.contains, "contains"),
            (IFML.hasEvent, "event"),
            (IFML.hasParameter, "param"),
            (IFML.source, "flow source"),
            (IFML.target, "flow target"),
        ],
    )
    return nodes, edges


def statechart_graph_data(model_iri: str) -> tuple[list[dict], list[dict]]:
    graph = get_graph()
    members = set(model_members(model_iri))
    states = {m for m in members if (URIRef(m), RDF.type, STATE.State) in graph}
    transitions = members - states
    nodes = nodes_for(states)
    edges = []
    for t in transitions:
        subj = URIRef(t)
        if (subj, RDF.type, STATE.Transition) not in graph:
            continue
        frm = graph.value(subj, STATE["from"])
        to = graph.value(subj, STATE.to)
        trigger = graph.value(subj, STATE.trigger)
        if frm is not None and to is not None:
            edges.append({"from": str(frm), "to": str(to), "label": str(trigger) if trigger else ""})
    return nodes, edges


GRAPH_BUILDERS = {
    "c4": c4_graph_data,
    "ifml": ifml_graph_data,
    "statechart": statechart_graph_data,
    "shapegraph": shapegraph_graph_data,
}


def resolve_level(notation: str, requested: str) -> tuple[str | None, list[dict]]:
    """Effective C4 level and any warnings; None for non-C4 notations."""
    if notation != "c4":
        return None, []
    if not requested:
        return DEFAULT_LEVEL, []
    if requested not in C4_LEVELS:
        return DEFAULT_LEVEL, [{"message": f"Unknown level '{requested}'; showing {DEFAULT_LEVEL}"}]
    return requested, []


def level_summaries(model_iri: str) -> list[dict]:
    """Per-level node/edge counts for a C4 model, in C4_LEVELS order.

    A level is empty when it draws nothing, or when it draws exactly what the
    previous level drew (same node ids and same (from, to, label) edges), so
    switching to it would add nothing for this model.
    """
    summaries = []
    prev: tuple[set, set] | None = None
    for lv in C4_LEVELS.values():
        nodes, edges = c4_graph_data(model_iri, lv.id)
        node_ids = {n["id"] for n in nodes}
        edge_keys = {(e["from"], e["to"], e["label"]) for e in edges}
        empty = not node_ids or (prev is not None and prev == (node_ids, edge_keys))
        summaries.append(
            {
                "id": lv.id,
                "title": lv.title,
                "question": lv.question,
                "nodeCount": len(node_ids),
                "edgeCount": len(edge_keys),
                "empty": empty,
            }
        )
        prev = (node_ids, edge_keys)
    return summaries


def build_view(
    iri: str,
    breadcrumb_trail: list[str],
    detailed_by_candidates: list[dict] | None = None,
    level: str = "",
    hide: str = "",
) -> dict:
    notation = notation_of(iri)
    effective_level, warnings = resolve_level(notation, level)
    hidden, rejected = legend.parse_hide(hide)
    warnings = warnings + [{"message": f"Ignored hide value '{t}': expected a type qname"} for t in rejected]
    payload = render_payload_of(iri)
    if effective_level:
        level_nodes, _ = c4_graph_data(iri, effective_level)
        legend_items = legend.legend_entries(level_nodes, hidden)
    else:
        legend_items, hidden = [], []
    return {
        "@context": "https://w3id.org/seams/context.jsonld",
        "@id": iri,
        "label": label(iri),
        "types": types_of(iri),
        "focusedModel": focused_model(iri),
        "notation": notation,
        "level": effective_level,
        "levels": level_summaries(iri) if effective_level else [],
        "legend": legend_items,
        "hiddenTypes": hidden,
        "layer": layer_of(iri),
        "nativeElementId": native_element_id(iri),
        "renderPayload": payload,
        "seamEdges": seam_edges(iri),
        "breadcrumbs": [{"iri": a, "label": label(a)} for a in breadcrumb_trail],
        "detailedByCandidates": detailed_by_candidates or [],
        "warnings": warnings,
        "modelConformance": get_model_conformance(get_graph()),
        # Derived IFML notation diagram for the SVG renderer (M006/S05, D011).
        "ifml": ifml.ifml_diagram(iri) if notation == "ifml" else None,
    }


def wants_json(request: Request) -> bool:
    if request.query_params.get("format") == "json":
        return True
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return False
    return "application/ld+json" in accept or "application/json" in accept


def href_for(iri: str, trail: list[str], level: str = "", hide: list[str] | None = None) -> str:
    qs = quote(",".join(trail), safe="")
    href = f"/view/{quote(iri, safe='')}?path={qs}"
    # Only known level ids are ever carried into a link.
    if level in C4_LEVELS:
        href += f"&level={level}"
    # hide holds parse_hide()-validated qnames only (M006/S04, D010).
    if hide:
        href += f"&hide={quote(','.join(hide), safe=':,')}"
    return href


def toggled(hidden: list[str], type_qname: str) -> list[str]:
    return sorted(set(hidden) ^ {type_qname})


@app.on_event("startup")
def startup() -> None:
    get_graph()
    logger.info(
        "viewer model %s (%s), root %s",
        MODEL_PATH,
        f"from {MODEL_ENV}" if os.environ.get(MODEL_ENV) else "default",
        root_iri(),
    )


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url=f"/view/{quote(root_iri(), safe='')}")


@app.get("/payload/{iri:path}")
def payload_endpoint(iri: str):
    payload_iri = unquote(iri)
    path = resolve_payload_path(payload_iri)
    media_type = PAYLOAD_MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


# Declared before the parameterized route below — FastAPI matches in
# declaration order, so /queries must not be swallowed by /queries/{...}.
@app.get("/queries")
def queries_catalog() -> JSONResponse:
    return JSONResponse(
        [
            {
                "name": q.name,
                "label": q.label,
                "question": q.question,
                "focusVariable": q.focusVariable,
                "focusType": str(q.focusType),
            }
            for q in canned_queries.QUERIES.values()
        ]
    )


def result_cell(value: str) -> dict:
    """Enrich a query result cell for HTML rendering: IRI values become
    labeled links into /view/, everything else renders as plain text."""
    is_iri = value.startswith(("http://", "https://", "urn:"))
    return {
        "value": value,
        "label": label(value) if is_iri else value,
        "href": f"/view/{quote(value, safe='')}" if is_iri else None,
        "isIri": is_iri,
    }


@app.get("/queries/{query_name}/{focus_iri:path}")
def query_endpoint(request: Request, query_name: str, focus_iri: str):
    focus = unquote(focus_iri)
    if query_name not in canned_queries.QUERIES:
        raise HTTPException(status_code=404, detail=f"unknown canned query: {query_name}")
    # Non-applicable or unknown focus IRIs are not errors: an empty result set
    # (resultCount 0) is meaningful feedback, so execute unconditionally.
    result = canned_queries.execute_query(get_graph(), query_name, focus)
    wants_html = request.headers.get("hx-request") == "true" or request.query_params.get("format") == "html"
    if not wants_html:
        return JSONResponse(result)
    query = canned_queries.QUERIES[query_name]
    ctx = {
        "request": request,
        "query_label": query.label,
        "query_question": query.question,
        "result": result,
        "cell_rows": [[result_cell(row[col]) for col in result["columns"]] for row in result["rows"]],
    }
    return templates.TemplateResponse(request, "query-results.html", ctx)


# Relations panel (M007/S02): the focused element's seam edges grouped by
# reveal mode. Hints follow docs/research/2026-10-15-reveal-modes.md section 2.
RELATION_GROUPS = (
    ("open", "Open", "opens the target's model"),
    ("nest", "Nest", "draws the target inside its source"),
    ("layer", "Layer", "overlays the target on this view; opens the inspector for now"),
)


def relation_groups(outgoing: list[dict], incoming: list[dict]) -> list[dict]:
    """Template-only context: outgoing and incoming edges (already carrying href)
    merged with a direction key, grouped open, nest, layer, empty groups omitted."""
    rows = [
        {**e, "direction": "out", "label": e["targetLabel"], "layer": e["targetLayer"], "iri": e["target"]}
        for e in outgoing
    ] + [
        {**e, "direction": "in", "label": e["sourceLabel"], "layer": e["sourceLayer"], "iri": e["source"]}
        for e in incoming
    ]
    groups = []
    for mode, title, hint in RELATION_GROUPS:
        edges = sorted(
            (r for r in rows if r["reveal"] == mode),
            key=lambda r: (r["predicateLabel"], r["label"], r["direction"], r["iri"]),
        )
        if edges:
            groups.append({"mode": mode, "title": title, "hint": hint, "edges": edges})
    return groups


@app.get("/view/{iri:path}")
def view_endpoint(request: Request, iri: str, path: str = "", level: str = "", hide: str = ""):
    clicked = unquote(iri)
    incoming_trail = [p for p in unquote(path).split(",") if p]

    nav = resolve_navigation(clicked)
    focus = nav["landing"] if nav["candidates"] else (nav["target"] or clicked)
    view = build_view(focus, incoming_trail, detailed_by_candidates=nav["candidates"], level=level, hide=hide)

    if wants_json(request):
        return JSONResponse(view)

    outgoing_trail = incoming_trail + [focus] if focus not in incoming_trail else incoming_trail
    # The C4 level rides along every link (M006/S03) so a descent into a
    # non-C4 view and the way back keep it. Only validated ids are carried.
    carried_level = view["level"] or (level if level in C4_LEVELS else "")
    notation = view["notation"]
    render_kind = notation if notation in RENDERERS_IMPLEMENTED else "none"
    # D022: a NodeShape that self-lands (no detail model, e.g. ConversationShape)
    # draws its model's shape graph with itself highlighted. Template-only:
    # build_view and the ADR-0004 JSON keep notation "none" for it.
    shape_model = None
    if render_kind == "none" and not is_model(focus):
        model = focused_model(focus)
        if (
            model is not None
            and (URIRef(focus), RDF.type, SH.NodeShape) in get_graph()
            and notation_of(model) == "shapegraph"
        ):
            render_kind = "shapegraph"
            shape_model = model

    root = root_iri()
    ctx = {
        "request": request,
        "focus_iri": focus,
        "label": view["label"],
        "notation": notation,
        "render_kind": render_kind,
        "types_str": ", ".join(view["types"]) or "—",
        "native_element_id": view["nativeElementId"],
        "render_payload": view["renderPayload"],
        "warnings": view["warnings"],
        "level": view["level"],
        "carried_level": carried_level,
        "levels": [
            {
                **summary,
                "href": href_for(focus, incoming_trail, summary["id"], view["hiddenTypes"]),
                "active": summary["id"] == view["level"],
            }
            for summary in view["levels"]
        ],
        # Legend entries toggle their own type in ?hide= and keep the level.
        # Descent links below carry the level but never hide (D010).
        "legend": [
            {
                **entry,
                "href": href_for(focus, incoming_trail, view["level"], toggled(view["hiddenTypes"], entry["type"])),
            }
            for entry in view["legend"]
        ],
        "model_conformance": view["modelConformance"],
        "outgoing": view["seamEdges"]["outgoing"],
        "incoming": view["seamEdges"]["incoming"],
        "breadcrumbs": [
            {"label": c["label"], "href": href_for(c["iri"], incoming_trail[:i], carried_level)}
            for i, c in enumerate(view["breadcrumbs"])
            if c["iri"] != root
        ],
        "root_href": href_for(root, [], carried_level),
        "next_path_qs": quote(",".join(outgoing_trail), safe=""),
        "applicable_queries": [
            {
                "name": q.name,
                "label": q.label,
                "href": f"/queries/{q.name}/{quote(focus, safe='')}?format=html",
            }
            for q in canned_queries.QUERIES.values()
            if canned_queries.is_applicable(get_graph(), focus, q)
        ],
    }

    if render_kind == "c4":
        nodes, edges = c4_graph_data(focus, view["level"])
        nodes, edges = legend.contract_hidden(nodes, edges, view["hiddenTypes"])
        ctx["nodes"] = nodes
        ctx["edges"] = edges
    elif render_kind == "shapegraph":
        nodes, edges = shapegraph_graph_data(shape_model or focus, focus=focus)
        ctx["nodes"] = nodes
        ctx["edges"] = edges
    elif render_kind in GRAPH_BUILDERS:
        nodes, edges = GRAPH_BUILDERS[render_kind](focus)
        ctx["nodes"] = nodes
        ctx["edges"] = edges
        if render_kind == "ifml":
            # IFML is drawn as IFML from viewer/ifml.py (M006/S05, D011);
            # nodes/edges are still built, but the ifml template does not use them.
            ctx["ifml"] = view["ifml"]
            # Template-only ELK port graph for the diagram-js canvas (M007/S04, D023).
            ctx["ifml_canvas"] = ifml.ifml_elk_graph(view["ifml"])
    elif render_kind in PAYLOAD_RENDERERS and view["renderPayload"]:
        ctx["payload_url"] = f"/payload/{quote(view['renderPayload'], safe='')}"
        ctx["element_map"] = payload_element_map(focus)
        # Template-only (not in build_view), so the JSON contract is unchanged.
        ctx["element_seams"] = payload_element_seams(focus)

    def link(iri_str: str) -> str:
        return href_for(iri_str, outgoing_trail, carried_level)

    for e in ctx["outgoing"]:
        e["href"] = link(e["target"])
    for e in ctx["incoming"]:
        e["href"] = link(e["source"])

    ctx["detailed_by_candidates"] = [{**c, "href": link(c["iri"])} for c in view["detailedByCandidates"]]
    ctx["relations"] = relation_groups(ctx["outgoing"], ctx["incoming"])

    template = "fragment.html" if request.headers.get("hx-request") == "true" else "page.html"
    return templates.TemplateResponse(request, template, ctx)
