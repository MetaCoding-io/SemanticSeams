"""Canned cross-layer query catalog + execution engine (S03 T01).

Exposes the three docs/queries/ SPARQL queries as a browsable catalog and
runs them against the viewer's loaded model with a focus element bound via
initBindings. The focus IRI never reaches the query text by string
interpolation — initBindings with a URIRef is the SPARQL-injection guard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from rdflib import RDF, Namespace, URIRef
from rdflib.namespace import SH

BASE_DIR = Path(__file__).resolve().parent
QUERIES_DIR = BASE_DIR.parent / "docs" / "queries"

ARCH = Namespace("https://w3id.org/seams/arch#")
STATE = Namespace("https://w3id.org/seams/state#")

# Row cap for a single execution; responses report the emitted count and a
# truncated flag when the cap was hit.
MAX_ROWS = 1000


@dataclass(frozen=True)
class CannedQuery:
    name: str
    label: str
    question: str
    focusVariable: str
    focusType: URIRef


QUERIES: dict[str, CannedQuery] = {
    "what-writes-shape": CannedQuery(
        name="what-writes-shape",
        label="What writes this shape?",
        question=(
            "Which UI events can eventually write this data shape, "
            "and through which task?"
        ),
        focusVariable="shape",
        focusType=SH.NodeShape,
    ),
    "impact-of-node": CannedQuery(
        name="impact-of-node",
        label="What breaks if this node goes away?",
        question=(
            "What breaks — containers *and processes* — if this "
            "deployment node goes away?"
        ),
        focusVariable="node",
        focusType=ARCH.DeploymentNode,
    ),
    "what-moves-state": CannedQuery(
        name="what-moves-state",
        label="What moves an entity out of this state?",
        question="Which process tasks may move an entity out of this state?",
        focusVariable="state",
        focusType=STATE.State,
    ),
}


def load_query(name: str) -> str:
    """Return the SPARQL text for a catalog query.

    Raises KeyError for names not in QUERIES before touching the filesystem,
    so a hostile name can never become a path component (no path traversal).
    """
    if name not in QUERIES:
        raise KeyError(f"unknown canned query: {name!r}")
    return (QUERIES_DIR / f"{name}.rq").read_text(encoding="utf-8")


def is_applicable(graph, focus_iri: str, query: CannedQuery) -> bool:
    """Whether a query's focus binding makes sense for this element.

    Explicit instance-level rdf:type check only — no RDFS/OWL inference, so
    subclasses of the focus type are missed. False negatives are acceptable
    v1 behavior (a button not shown, never a broken one).
    """
    return (URIRef(focus_iri), RDF.type, query.focusType) in graph


def execute_query(graph, query_name: str, focus_iri: str) -> dict:
    """Run a canned query with the focus element bound, returning a JSON-able dict.

    The focus IRI reaches the query only through initBindings as a URIRef —
    never interpolated into the query string.
    """
    query = QUERIES[query_name]
    sparql = load_query(query_name)
    start = time.perf_counter()
    result = graph.query(sparql, initBindings={query.focusVariable: URIRef(focus_iri)})
    columns = [str(var) for var in result.vars]
    rows = []
    truncated = False
    for binding_row in result:
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append(
            {
                col: (str(val) if val is not None else "")
                for col, val in zip(columns, binding_row)
            }
        )
    duration_ms = (time.perf_counter() - start) * 1000
    payload = {
        "queryName": query.name,
        "focusIri": focus_iri,
        "bindings": {query.focusVariable: focus_iri},
        "columns": columns,
        "rows": rows,
        "resultCount": len(rows),
        "durationMs": round(duration_ms, 2),
    }
    if truncated:
        payload["truncated"] = True
    return payload
