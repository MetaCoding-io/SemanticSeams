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
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import seams
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.routing import BaseRoute
from fastapi.templating import Jinja2Templates
from rdflib import RDF, RDFS, Dataset, Namespace, URIRef
from rdflib.namespace import SH

import seams_edit
from seams_gen import GeneratorError
from seams_gen.sequence import derive, render
from viewer import editing, ifml, layers, legend, preview, validation
from viewer import queries as canned_queries
from viewer.levels import C4_LEVELS, DEFAULT_LEVEL, load_rollup
from viewer.profiles import Profile, resolve_profile
from viewer.shapegraph import shapegraph_graph_data
from viewer.validation import get_lifted_iri_health, get_model_conformance

# uvicorn configures handlers for its own loggers only, so log through
# uvicorn.error to have the startup line show up in the server output.
logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent
MODEL_ENV = "SEAMS_MODEL"
ROOT_ENV = "SEAMS_VIEWER_ROOT"
# ADR-0017: edit mode is off unless SEAMS_EDIT=1 when the viewer starts (or when
# configure() runs); without it no route that writes is mounted.
EDIT_ENV = "SEAMS_EDIT"
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_graph()
    logger.info(
        "viewer model %s (%s), root %s",
        MODEL_PATH,
        f"from {MODEL_ENV}" if os.environ.get(MODEL_ENV) else "default",
        root_iri(),
    )
    yield


app = FastAPI(title="SemanticSeams Viewer", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


_model: seams.Model | None = None
_root_iri: str | None = None
# ADR-0018: the domain profile the loaded model conforms to, resolved with the
# model, or the ResolutionError facts that stopped it (then no profile applies).
_profile: Profile | None = None
_profile_error: dict | None = None


def configure(path: Path) -> None:
    """Point the viewer at another model and drop the loaded model, root and
    cached conformance (validation keys it by id(ds), which a fresh Dataset
    can reuse, MEM010)."""
    global MODEL_PATH, MODEL_DIR, _model, _root_iri, _profile, _profile_error
    MODEL_PATH = Path(path).resolve()
    MODEL_DIR = model_base_dir(MODEL_PATH)
    _model = None
    _root_iri = None
    _profile = _profile_error = None
    validation._clear_cache()
    _undo_stack.clear()
    mount_edit_routes()


def reload_model() -> None:
    """Drop the loaded model and its cached conformance after an edit, so the next
    request reads the files seams_edit wrote (MEM010: the cache is keyed by id(ds)).
    The domain profile is resolved again with the model (ADR-0018)."""
    global _model, _root_iri, _profile, _profile_error
    _model = None
    _root_iri = None
    _profile = _profile_error = None
    validation._clear_cache()


def get_model() -> seams.Model:
    """The loaded model (seams.load on MODEL_PATH, on first use)."""
    global _model
    if _model is None:
        if not (MODEL_PATH.is_file() or MODEL_PATH.is_dir()):
            source = f" (from {MODEL_ENV})" if os.environ.get(MODEL_ENV) else ""
            raise FileNotFoundError(f"viewer model not found: {MODEL_PATH}{source}")
        _model = seams.load(MODEL_PATH)
        _resolve_profile(_model.ds)
    return _model


def _resolve_profile(ds: Dataset) -> None:
    """Resolve the model's domain profile (ADR-0018) and log it in one line. A
    ResolutionError is kept as a health fact and the viewer carries on without one."""
    global _profile, _profile_error
    try:
        _profile = resolve_profile(ds, MODEL_DIR)
        _profile_error = None
    except seams.ResolutionError as err:
        _profile = None
        _profile_error = {"subject": err.subject, "predicate": err.predicate, "detail": err.detail}
        logger.warning("profile not resolved: %s %s: %s", err.subject, err.predicate, err.detail)
        return
    if _profile is not None:
        logger.info(
            "profile %s: %d class(es), %d generator(s)",
            _profile.iri,
            len(_profile.classes),
            len(_profile.generators),
        )


def get_profile() -> Profile | None:
    """The domain profile the loaded model conforms to, or None (ADR-0018)."""
    get_model()
    return _profile


def profile_health() -> dict | None:
    """The health panel's profile fact: the attached profile's IRI, label and
    counts, or the ResolutionError facts that stopped it; None with no profile."""
    profile = get_profile()
    if _profile_error is not None:
        return {"iri": None, "label": None, "classes": 0, "generators": 0, "error": _profile_error}
    if profile is None:
        return None
    name = profile.graph.value(profile.iri, RDFS.label)
    return {
        "iri": str(profile.iri),
        "label": str(name) if name is not None else str(profile.iri),
        "classes": len(profile.classes),
        "generators": len(profile.generators),
        "error": None,
    }


def get_graph() -> Dataset:
    """The loaded model's merged Dataset (default_union)."""
    return get_model().ds


def model_health(ds: Dataset) -> dict:
    """The health panel's facts: the cached SHACL conformance summary (with the
    domain profile's shapes and out-of-profile warnings, ADR-0018), ``liftedIris``,
    the BPMN/DMN lifted IRIs with no matching id in their payload XML (ADR-0002
    rule 4), resolved against MODEL_DIR as payloads are, and ``profile`` when the
    model states a seam:conformsTo (no key otherwise, so nothing changes)."""
    health = {**get_model_conformance(ds, get_profile()), "liftedIris": get_lifted_iri_health(ds, MODEL_DIR)}
    profile = profile_health()
    return health if profile is None else {**health, "profile": profile}


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


def sequence_events(focus: str) -> list[dict]:
    """Template-only: the ifml:Events whose derived sequence (M013/S03, D048)
    the view links to. The focus itself when it is an event, the events of a
    focused IFML model, and the events whose seam:triggers target sits in the
    focused model (the BPMN view /view/{event} lands on, ADR-0005)."""
    graph = get_graph()
    events = {str(e) for e in graph.subjects(RDF.type, IFML.Event)}
    found: set[str] = set()
    if focus in events:
        found.add(focus)
    if is_model(focus) and notation_of(focus) == "ifml":
        found.update(m for m in model_members(focus) if m in events)
    model = focused_model(focus)
    if model is not None:
        for ev, target in graph.subject_objects(SEAM.triggers):
            if str(ev) in events and focused_model(str(target)) == model:
                found.add(str(ev))
    return [
        {"iri": e, "label": label(e), "href": f"/sequence/{quote(e, safe='')}?format=html"}
        for e in sorted(found, key=lambda e: (label(e), e))
    ]


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
        "modelConformance": model_health(get_graph()),
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


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url=f"/view/{quote(root_iri(), safe='')}")


@app.get("/layers")
def layers_endpoint(request: Request):
    """Layer mode (M008/S03): the model as six layers plus the seams between
    them, built by viewer/layers.py. JSON on request, otherwise the stacked
    planes of layers.html inside the page shell."""
    data = layers.build_layers()
    if wants_json(request):
        return JSONResponse(data)
    # Open-mode seams may end at a model, drawn at its link in the plane title.
    labels = {e["iri"]: e["label"] for lay in data["layers"] for e in lay["nodes"] + lay["models"]}
    planes = [
        {
            **lay,
            # A plane title opens its layer's first model flat; the rest are listed beside it.
            "href": lay["models"][0]["href"] if lay["models"] else None,
            "nodes": [{**n, "href": f"/view/{quote(n['iri'], safe='')}"} for n in lay["nodes"]],
        }
        for lay in data["layers"]
    ]
    seams = [
        {**s, "title": f"{labels[s['source']]} — {s['predicateLabel']} → {labels[s['target']]} ({s['reveal']})"}
        for s in data["seams"]
    ]
    ctx = {
        "request": request,
        "label": "Layers",
        "model_conformance": model_health(get_graph()),
        "content_template": "layers.html",
        "planes": planes,
        "seams": seams,
        "layer_warnings": data["warnings"],
        "reveal_modes": [(mode, title) for mode, title, _hint in RELATION_GROUPS],
    }
    return templates.TemplateResponse(request, "page.html", ctx)


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
    result = canned_queries.execute_query(get_graph(), query_name, focus, model=get_model())
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


@app.get("/sequence/{event_iri:path}")
def sequence_endpoint(request: Request, event_iri: str):
    """The derived sequence diagrams (M013/S03, D048) of one ifml:Event: one
    per gateway path, with its gaps and Mermaid text. JSON by default, the
    sequence.html fragment for htmx or ?format=html (as query_endpoint)."""
    iri = unquote(event_iri)
    try:
        diagrams = derive(get_model(), URIRef(iri))
    except GeneratorError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    result = {
        "event": iri,
        "label": label(iri),
        "diagrams": [
            {"name": d.name, "path": list(d.path), "gaps": list(d.gaps), "mermaid": render(d)} for d in diagrams
        ],
    }
    wants_html = request.headers.get("hx-request") == "true" or request.query_params.get("format") == "html"
    if not wants_html:
        return JSONResponse(result)
    ctx = {"request": request, **result, "json_href": f"/sequence/{quote(iri, safe='')}"}
    return templates.TemplateResponse(request, "sequence.html", ctx)


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


def applicable_queries(focus: str) -> list[dict]:
    """The canned questions the Questions catalog offers on a view.

    Those whose focus type the focused element has, then, when the focus is a
    model, those for each element seam:detailedBy it (by IRI). Such an element
    auto-navigates into its model (a proc:Process into its BPMN), so its own
    questions would otherwise never get a button; theirs name the element.
    """
    graph = get_graph()
    subjects = [focus]
    if is_model(focus):
        subjects += sorted(str(s) for s in set(graph.subjects(SEAM.detailedBy, URIRef(focus))) if str(s) != focus)
    return [
        {
            "name": q.name,
            "label": q.label if subject == focus else f"{q.label} ({label(subject)})",
            "href": f"/queries/{q.name}/{quote(subject, safe='')}?format=html",
        }
        for subject in subjects
        for q in canned_queries.QUERIES.values()
        if canned_queries.is_applicable(graph, subject, q)
    ]


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
        "applicable_queries": applicable_queries(focus),
        # Template-only (M013/S03): the /view JSON contract is unchanged.
        "sequence_events": sequence_events(focus),
        # Edit mode (ADR-0017): an Edit control only for an element some shape targets.
        "edit_href": _edit_href(focus) if edit_enabled() and _form_fields(focus) else None,
        "undo_count": len(_undo_stack),
        # Edit mode: BPMN and DMN open in the bpmn.io modelers, saving to /edit/payload.
        "modeler": edit_enabled() and render_kind in PAYLOAD_RENDERERS and bool(view["renderPayload"]),
        "save_payload_url": f"/edit/payload/{quote(focus, safe='')}",
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


# --- Edit mode (ADR-0017, backlog I2) ---------------------------------------
#
# The edit routes live on their own router, included in the app only when
# SEAMS_EDIT=1 at import or at configure(). A test switches edit mode with
# monkeypatch.setenv(EDIT_ENV, "1") (or delenv) and then configure(path), which
# mounts or unmounts the router. Every save goes through seams_edit.apply on the
# model's own TriG files; the viewer never opens a model file for writing.

edit_router = APIRouter()
_edit_routes: list[BaseRoute] = []
# The session's edit history (ADR-0017 Undo): in memory only, newest last.
_undo_stack: list[seams_edit.EditRecord] = []


def edit_enabled() -> bool:
    """Whether the edit routes are mounted."""
    return bool(_edit_routes)


templates.env.globals["edit_enabled"] = edit_enabled


def edit_palette() -> dict | None:
    """The classes the editor offers (ADR-0018): the attached profile's, with its
    labels, computed in viewer/editing.py. None without a profile or edit mode."""
    profile = get_profile() if edit_enabled() else None
    if profile is None:
        return None
    health = profile_health() or {}
    return {"profile": health.get("label"), "iri": str(profile.iri), "classes": editing.palette(profile)}


templates.env.globals["edit_palette"] = edit_palette


def mount_edit_routes() -> None:
    """Include the edit router when SEAMS_EDIT=1, remove it otherwise."""
    wanted = os.environ.get(EDIT_ENV) == "1"
    if wanted and not _edit_routes:
        before = list(app.router.routes)
        app.include_router(edit_router)
        _edit_routes.extend(r for r in app.router.routes if r not in before)
    elif not wanted and _edit_routes:
        app.router.routes[:] = [r for r in app.router.routes if r not in _edit_routes]
        _edit_routes.clear()
    app.openapi_schema = None


def _edit_href(iri: str) -> str:
    return f"/edit/{quote(iri, safe='')}"


def _form_fields(iri: str) -> list[editing.FormField]:
    """The element's form fields, with the attached profile's shapes (ADR-0018)."""
    profile = get_profile()
    if profile is None:
        return editing.form_fields(get_graph(), iri)
    return editing.form_fields(get_graph(), iri, profile.shapes)


def _edit_context(request: Request, iri: str, **extra) -> dict:
    ds = get_graph()
    fields = _form_fields(iri)
    return {
        "request": request,
        "focus_iri": iri,
        "label": label(iri),
        "action": _edit_href(iri),
        "view_href": f"/view/{quote(iri, safe='')}",
        "fields": [
            {
                **vars(f),
                "slot": i,
                "multiple": f.max_count != 1,
                # A text field shows each value, plus a blank input to add one.
                "inputs": list(f.values) + ([""] if f.max_count != 1 or not f.values else []),
                "checked": "true" in f.values,
            }
            for i, f in enumerate(fields)
        ],
        "undo_count": len(_undo_stack),
        "model_conformance": model_health(ds),
        "saved": None,
        "error": None,
        "preview": None,
        **extra,
    }


def _known_element(iri: str) -> None:
    if editing.element_graph(get_graph(), iri) is None:
        raise HTTPException(status_code=404, detail=f"no element {iri} in the model")


def _shares(record: seams_edit.EditRecord) -> list[dict]:
    return [
        {"file": e.path.name, "adds": len(e.patch.adds), "removes": len(e.patch.removes)}
        for e in sorted(record.files, key=lambda e: str(e.path))
    ]


@edit_router.post("/edit/undo")
def edit_undo(request: Request):
    """Reverse the newest edit of this session (seams_edit.undo), then reload."""
    if not _undo_stack:
        raise HTTPException(status_code=409, detail="nothing to undo")
    record = _undo_stack[-1]
    try:
        seams_edit.undo(record)
    except (seams_edit.PatchError, OSError) as err:
        logger.warning("edit undo failed: %s", err)
        return JSONResponse({"undone": False, "error": str(err)}, status_code=409)
    _undo_stack.pop()
    reload_model()
    files = _shares(record)
    logger.info("edit undone: %s", ", ".join(f"{f['file']} (-{f['adds']} +{f['removes']})" for f in files))
    response = JSONResponse({"undone": True, "files": files, "remaining": len(_undo_stack)})
    if request.headers.get("hx-request") == "true":
        # The undo button reloads the page, so the view and the health panel
        # both show the restored model.
        response.headers["HX-Refresh"] = "true"
    return response


@edit_router.post("/edit/payload/{iri:path}")
async def edit_payload(request: Request, iri: str):
    """Save a BPMN or DMN model's payload from the modeler (ADR-0017, ADR-0002 rule 5).

    The body is JSON ``{"xml": ..., "renames": [{"old": ..., "new": ...}]}``: the
    modeler's XML, and each element id the user changed, from the id in the file to the
    id in ``xml``. Each rename goes through seams_edit.rename_id, which moves the quads
    naming ``iri#old`` to ``iri#new``; then save_payload writes ``xml``. The records are
    combined into one, so one undo reverses the save. A PatchError is a 409 naming the
    subject, the predicate and the reason, after any rename already written is undone.
    """
    model_iri = unquote(iri)
    payload_iri = render_payload_of(model_iri) if notation_of(model_iri) in PAYLOAD_RENDERERS else None
    if payload_iri is None:
        raise HTTPException(status_code=404, detail=f"{model_iri} is not a BPMN or DMN model with a payload")
    payload = resolve_payload_path(payload_iri)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="the body is not JSON") from None
    xml = body.get("xml") if isinstance(body, dict) else None
    renames = body.get("renames", []) if isinstance(body, dict) else None
    if (
        not isinstance(xml, str)
        or not isinstance(renames, list)
        or not all(
            isinstance(r, dict) and isinstance(r.get("old"), str) and isinstance(r.get("new"), str) for r in renames
        )
    ):
        raise HTTPException(
            status_code=400, detail='the body must be {"xml": str, "renames": [{"old": str, "new": str}]}'
        )
    files = get_model().files
    records: list[seams_edit.EditRecord] = []
    try:
        for r in renames:
            records.append(seams_edit.rename_id(files, payload, model_iri, r["old"], r["new"]))
        records.append(seams_edit.save_payload(files, payload, xml))
        record = seams_edit.combine(records)
    except (seams_edit.PatchError, OSError) as err:
        rollback = _roll_back(records)
        if records:
            reload_model()
        logger.warning("payload save refused for %s: %s%s", model_iri, err, rollback)
        if isinstance(err, seams_edit.PatchError):
            error = {"subject": err.subject, "predicate": err.predicate, "detail": err.detail + rollback}
        else:
            error = {
                "subject": str(payload),
                "predicate": "file",
                "detail": f"could not write the model: {err}{rollback}",
            }
        return JSONResponse({"saved": False, "error": error}, status_code=409)
    shares = _shares(record)
    if record.files:
        _undo_stack.append(record)
        reload_model()
    logger.info(
        "payload saved %s (%s): %s",
        model_iri,
        ", ".join(f"{r['old']} -> {r['new']}" for r in renames) or "no renames",
        ", ".join(f"{f['file']} (+{f['adds']} -{f['removes']})" for f in shares) or "no change",
    )
    return JSONResponse({"saved": True, "renames": renames, "files": shares, "undo": len(_undo_stack)})


def _roll_back(records: list[seams_edit.EditRecord]) -> str:
    """Undo the records already written, newest first; '' or a note of what was left."""
    for done in reversed(records):
        try:
            seams_edit.undo(done)
        except (seams_edit.PatchError, OSError) as err:
            return f" (and undoing the earlier renames failed: {err})"
    return ""


def preview_context() -> dict:
    """The live preview of the loaded model (viewer/preview.py), logged with its
    project, output count, fault count and duration. An attached profile limits it
    to the profile's generators (ADR-0018)."""
    start = time.perf_counter()
    profile = get_profile()
    facts = preview.preview(MODEL_PATH, MODEL_DIR, profile.generators if profile is not None else None)
    logger.info(
        "preview %s: %d output(s), %d fault(s) in %.2fs%s",
        facts["project"] or MODEL_DIR,
        len(facts["files"]),
        len(facts["faults"]),
        time.perf_counter() - start,
        f" ({facts['error']})" if facts["error"] else "",
    )
    return facts


@edit_router.get("/edit/preview")
def edit_preview(request: Request, oob: bool = False):
    """The project's generators re-run in lenient mode on the edited model, in
    memory (backlog I3): nothing is written."""
    return templates.TemplateResponse(request, "preview-panel.html", {"preview": preview_context(), "oob": oob})


@edit_router.get("/edit/{iri:path}")
def edit_form(request: Request, iri: str):
    """The element's form, one field per shaped property (viewer/editing.py)."""
    element = unquote(iri)
    _known_element(element)
    return templates.TemplateResponse(request, "edit-form.html", _edit_context(request, element))


@edit_router.post("/edit/{iri:path}")
async def edit_save(request: Request, iri: str):
    """Save one field: build the patch, apply it with seams_edit, reload.

    A value that breaks the shapes is saved and the health badge flags it
    (principle 5). A PatchError renders in the form, naming the subject, the
    predicate and the reason, and nothing is written.
    """
    element = unquote(iri)
    _known_element(element)
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    path = (form.get("field") or [""])[0]
    fields = {f.path: f for f in _form_fields(element)}
    if path not in fields:
        raise HTTPException(status_code=400, detail=f"{element} has no shaped field {path!r}")
    try:
        patch = editing.build_patch(get_graph(), element, fields[path], form.get("value", []))
        record = seams_edit.apply(get_model().files, patch)
    except seams_edit.PatchError as err:
        logger.warning("edit refused by the writer: %s", err)
        error = {"subject": err.subject, "predicate": err.predicate, "detail": err.detail}
        return templates.TemplateResponse(request, "edit-form.html", _edit_context(request, element, error=error))
    except OSError as err:
        logger.warning("edit not written: %s", err)
        error = {"subject": element, "predicate": path, "detail": f"could not write the model: {err}"}
        return templates.TemplateResponse(request, "edit-form.html", _edit_context(request, element, error=error))
    if patch.is_empty:
        saved = {"field": path, "files": []}
    else:
        _undo_stack.append(record)
        reload_model()
        saved = {"field": path, "files": _shares(record)}
    logger.info(
        "edit saved %s %s: %s",
        element,
        path,
        ", ".join(f"{f['file']} (+{f['adds']} -{f['removes']})" for f in saved["files"]) or "no change",
    )
    return templates.TemplateResponse(
        request, "edit-form.html", _edit_context(request, element, saved=saved, preview=preview_context())
    )


mount_edit_routes()
