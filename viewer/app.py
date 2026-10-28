"""SemanticSeams viewer — Phase A POC.

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

from viewer import ifml, legend
from viewer import queries as canned_queries
from viewer.levels import C4_LEVELS, DEFAULT_LEVEL, load_rollup
from viewer.validation import get_model_conformance

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
DEPLOY = Namespace("https://w3id.org/seams/deploy#")

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

RENDERERS_IMPLEMENTED = {"c4", "ifml", "statechart", "bpmn", "dmn"}
PAYLOAD_RENDERERS = {"bpmn", "dmn"}

app = FastAPI(title="SemanticSeams Viewer")
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


# D004 keeps the ModelStore Dataset model-only (ontology triples would pollute
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
                    "navigational": p in NAVIGATIONAL_PREDICATES,
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


def card_seams(iri: str) -> list[dict]:
    """Outgoing seam edges of iri as card dots, sorted by predicate then target."""
    edges = [
        (p, str(o))
        for p, o in get_graph().predicate_objects(URIRef(iri))
        if is_seam_predicate(p)
    ]
    return [
        {
            "predicate": qname(p),
            "predicateLabel": predicate_label(p),
            "target": o,
            "targetLabel": label(o),
            "targetLayer": layer_of(o),
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
        m
        for m in model_members(model_iri)
        if any(t in spec.classes for t in graph.objects(URIRef(m), RDF.type))
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

    nodes = [{**n, "parent": parents.get(n["id"])} for n in nodes_for(visible)]
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


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url=f"/view/{quote(ROOT_IRI, safe='')}")


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
    wants_html = (
        request.headers.get("hx-request") == "true"
        or request.query_params.get("format") == "html"
    )
    if not wants_html:
        return JSONResponse(result)
    query = canned_queries.QUERIES[query_name]
    ctx = {
        "request": request,
        "query_label": query.label,
        "query_question": query.question,
        "result": result,
        "cell_rows": [
            [result_cell(row[col]) for col in result["columns"]]
            for row in result["rows"]
        ],
    }
    return templates.TemplateResponse(request, "query-results.html", ctx)


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
                "href": href_for(
                    focus, incoming_trail, view["level"], toggled(view["hiddenTypes"], entry["type"])
                ),
            }
            for entry in view["legend"]
        ],
        "model_conformance": view["modelConformance"],
        "outgoing": view["seamEdges"]["outgoing"],
        "incoming": view["seamEdges"]["incoming"],
        "breadcrumbs": [
            {"label": c["label"], "href": href_for(c["iri"], incoming_trail[:i], carried_level)}
            for i, c in enumerate(view["breadcrumbs"])
            if c["iri"] != ROOT_IRI
        ],
        "root_href": href_for(ROOT_IRI, [], carried_level),
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
    elif render_kind in GRAPH_BUILDERS:
        nodes, edges = GRAPH_BUILDERS[render_kind](focus)
        ctx["nodes"] = nodes
        ctx["edges"] = edges
    elif render_kind in PAYLOAD_RENDERERS and view["renderPayload"]:
        ctx["payload_url"] = f"/payload/{quote(view['renderPayload'], safe='')}"
        ctx["element_map"] = payload_element_map(focus)

    def link(iri_str: str) -> str:
        return href_for(iri_str, outgoing_trail, carried_level)

    for e in ctx["outgoing"]:
        e["href"] = link(e["target"])
    for e in ctx["incoming"]:
        e["href"] = link(e["source"])

    ctx["detailed_by_candidates"] = [
        {**c, "href": link(c["iri"])} for c in view["detailedByCandidates"]
    ]

    template = "fragment.html" if request.headers.get("hx-request") == "true" else "page.html"
    return templates.TemplateResponse(request, template, ctx)
