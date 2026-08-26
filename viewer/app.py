"""Seams viewer — Phase A POC.

FastAPI server implementing the /view/{iri} contract (ADR-0004) over an
in-process rdflib graph loaded from examples/chat-app/chat-app.trig. The
graph load is behind get_graph() so a Fuseki-backed store can drop in later
without touching routes or resolution logic.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from rdflib import RDF, RDFS, Dataset, Namespace, URIRef

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "examples" / "chat-app"
DATA_PATH = DATA_DIR / "chat-app.trig"
ROOT_IRI = "https://example.org/chat/chat_architecture"

# ADR-0003 specifies manifest-graph resolution (path/checksum/mediaType via a
# dedicated <urn:seams:graph:manifest> graph). Phase B takes a simplified path:
# seam:renderPayload values are relative IRIs resolved by rdflib against the
# trig file's own path, which already yields a file:// URI under DATA_DIR — so
# that URI is trusted directly instead of introducing manifest predicates.
PAYLOAD_MEDIA_TYPES = {
    ".bpmn": "application/bpmn+xml",
    ".dmn": "application/dmn+xml",
}

SEAM = Namespace("https://w3id.org/seams/seam#")
ARCH = Namespace("https://w3id.org/seams/arch#")
IFML = Namespace("https://w3id.org/seams/ifml#")
STATE = Namespace("https://w3id.org/seams/state#")

NOTATION_LABELS = {
    SEAM.C4: "c4",
    SEAM.IFML: "ifml",
    SEAM.BPMN: "bpmn",
    SEAM.DMN: "dmn",
    SEAM.Statechart: "statechart",
    SEAM.ShapeGraph: "shapegraph",
}

# ADR-0005: predicates that trigger navigation on click.
NAVIGATIONAL_PREDICATES = {SEAM.detailedBy, SEAM.triggers, SEAM.presents, SEAM.decidedBy}

# Administrative seam predicates excluded from the seamEdges inspector list —
# they drive rendering/dispatch rather than representing a cross-layer edge.
SEAM_ADMIN_PREDICATES = {SEAM.inModel, SEAM.notation, SEAM.renderPayload}

RENDERERS_IMPLEMENTED = {"c4", "ifml", "statechart", "bpmn", "dmn"}
PAYLOAD_RENDERERS = {"bpmn", "dmn"}

app = FastAPI(title="Seams Viewer")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class ModelStore:
    """Wraps graph access so the backing store (rdflib now, Fuseki later) is swappable."""

    def __init__(self, path: Path):
        self._path = path
        self._graph = Dataset(default_union=True)
        self._graph.parse(str(path), format="trig")

    @property
    def graph(self) -> Dataset:
        return self._graph


_store: ModelStore | None = None


def get_graph() -> Dataset:
    global _store
    if _store is None:
        _store = ModelStore(DATA_PATH)
    return _store.graph


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


def render_payload_of(iri: str) -> str | None:
    val = get_graph().value(URIRef(iri), SEAM.renderPayload)
    return str(val) if val is not None else None


def resolve_payload_path(payload_iri: str) -> Path:
    """Resolve a seam:renderPayload file:// IRI to a path, rejecting anything
    outside DATA_DIR so an unexpected payload IRI can't read arbitrary files."""
    parts = urlsplit(payload_iri)
    if parts.scheme != "file":
        raise HTTPException(status_code=404, detail=f"payload {payload_iri} is not a resolvable file")
    candidate = Path(unquote(parts.path)).resolve()
    if DATA_DIR.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail=f"payload {payload_iri} is outside the model root")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"payload file not found: {candidate}")
    return candidate


def native_element_id(iri: str) -> str | None:
    return iri.rsplit("#", 1)[1] if "#" in iri else None


def seam_edges(iri: str) -> dict:
    graph = get_graph()
    subj = URIRef(iri)
    outgoing = []
    for p, o in graph.predicate_objects(subj):
        if str(p).startswith(str(SEAM)) and p not in SEAM_ADMIN_PREDICATES:
            outgoing.append(
                {
                    "predicate": qname(p),
                    "target": str(o),
                    "targetLabel": label(str(o)),
                    "navigational": p in NAVIGATIONAL_PREDICATES,
                }
            )
    incoming = []
    for s, p in graph.subject_predicates(subj):
        if str(p).startswith(str(SEAM)) and p not in SEAM_ADMIN_PREDICATES:
            incoming.append(
                {
                    "predicate": qname(p),
                    "source": str(s),
                    "sourceLabel": label(str(s)),
                    "navigational": p in NAVIGATIONAL_PREDICATES,
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

    for pred in (SEAM.triggers, SEAM.presents, SEAM.decidedBy):
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


def nodes_for(members: set[str]) -> list[dict]:
    return [
        {"id": m, "label": label(m), "group": (types_of(m) or ["Element"])[0]}
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


def c4_graph_data(model_iri: str) -> tuple[list[dict], list[dict]]:
    members = set(model_members(model_iri))
    nodes = nodes_for(members)
    edges = edges_for_predicates(members, [(ARCH.contains, "contains"), (ARCH.dependsOn, "depends on")])
    return nodes, edges


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
}


def build_view(iri: str, breadcrumb_trail: list[str], detailed_by_candidates: list[dict] | None = None) -> dict:
    warnings = []
    payload = render_payload_of(iri)
    return {
        "@context": "https://w3id.org/seams/context.jsonld",
        "@id": iri,
        "label": label(iri),
        "types": types_of(iri),
        "focusedModel": focused_model(iri),
        "notation": notation_of(iri),
        "nativeElementId": native_element_id(iri),
        "renderPayload": payload,
        "seamEdges": seam_edges(iri),
        "breadcrumbs": [{"iri": a, "label": label(a)} for a in breadcrumb_trail],
        "detailedByCandidates": detailed_by_candidates or [],
        "warnings": warnings,
    }


def wants_json(request: Request) -> bool:
    if request.query_params.get("format") == "json":
        return True
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return False
    return "application/ld+json" in accept or "application/json" in accept


def href_for(iri: str, trail: list[str]) -> str:
    qs = quote(",".join(trail), safe="")
    return f"/view/{quote(iri, safe='')}?path={qs}"


@app.on_event("startup")
def startup() -> None:
    get_graph()


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url=f"/view/{quote(ROOT_IRI, safe='')}")


@app.get("/payload/{iri:path}")
def payload_endpoint(iri: str):
    payload_iri = unquote(iri)
    path = resolve_payload_path(payload_iri)
    media_type = PAYLOAD_MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.get("/view/{iri:path}")
def view_endpoint(request: Request, iri: str, path: str = ""):
    clicked = unquote(iri)
    incoming_trail = [p for p in unquote(path).split(",") if p]

    nav = resolve_navigation(clicked)
    focus = nav["landing"] if nav["candidates"] else (nav["target"] or clicked)
    view = build_view(focus, incoming_trail, detailed_by_candidates=nav["candidates"])

    if wants_json(request):
        return JSONResponse(view)

    outgoing_trail = incoming_trail + [focus] if focus not in incoming_trail else incoming_trail
    notation = view["notation"]
    render_kind = notation if notation in RENDERERS_IMPLEMENTED else "none"

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
        "outgoing": view["seamEdges"]["outgoing"],
        "incoming": view["seamEdges"]["incoming"],
        "breadcrumbs": [
            {"label": c["label"], "href": href_for(c["iri"], incoming_trail[:i])}
            for i, c in enumerate(view["breadcrumbs"])
            if c["iri"] != ROOT_IRI
        ],
        "root_href": href_for(ROOT_IRI, []),
        "next_path_qs": quote(",".join(outgoing_trail), safe=""),
    }

    if render_kind in GRAPH_BUILDERS:
        nodes, edges = GRAPH_BUILDERS[render_kind](focus)
        ctx["nodes"] = nodes
        ctx["edges"] = edges
    elif render_kind in PAYLOAD_RENDERERS and view["renderPayload"]:
        ctx["payload_url"] = f"/payload/{quote(view['renderPayload'], safe='')}"
        ctx["element_map"] = payload_element_map(focus)

    def link(iri_str: str) -> str:
        return href_for(iri_str, outgoing_trail)

    for e in ctx["outgoing"]:
        e["href"] = link(e["target"])
    for e in ctx["incoming"]:
        e["href"] = link(e["source"])

    ctx["detailed_by_candidates"] = [
        {**c, "href": link(c["iri"])} for c in view["detailedByCandidates"]
    ]

    template = "fragment.html" if request.headers.get("hx-request") == "true" else "page.html"
    return templates.TemplateResponse(request, template, ctx)
