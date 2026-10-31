"""Canned cross-layer query catalog + execution engine (S03 T01).

Exposes canned questions as a browsable catalog and runs them against the
viewer's loaded model with a focus element bound. Most are SPARQL from the
seams question bundle (byte-identical to docs/queries/), bound via
initBindings. The focus IRI never reaches the query text by string
interpolation — initBindings with a URIRef is the SPARQL-injection guard.

The coverage questions (M015/S04, D054) join the same catalog. Two are the
coverage/*.rq bundle queries; unexercised-paths is answered by
seams.coverage, because sequence flows live only in the BPMN XML
(ADR-0007), and its rows take the same columns/rows shape as a SPARQL result.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import seams
from rdflib import RDF, Namespace, URIRef
from rdflib.namespace import ODRL2, SH

ARCH = Namespace("https://w3id.org/seams/arch#")
STATE = Namespace("https://w3id.org/seams/state#")
PROC = Namespace("https://w3id.org/seams/proc#")

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
    # The seams bundle question that answers it ("" means its own name), or
    # None when Python answers it (PYTHON_ANSWERS).
    source: str | None = ""


QUERIES: dict[str, CannedQuery] = {
    "what-writes-shape": CannedQuery(
        name="what-writes-shape",
        label="What writes this shape?",
        question=("Which UI events can eventually write this data shape, and through which task?"),
        focusVariable="shape",
        focusType=SH.NodeShape,
    ),
    "impact-of-node": CannedQuery(
        name="impact-of-node",
        label="What breaks if this node goes away?",
        question=("What breaks — containers, processes *and data* — if this deployment node goes away?"),
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
    "screens-by-role-writing-shape": CannedQuery(
        name="screens-by-role-writing-shape",
        label="Which screens can each role use to write this shape?",
        question=(
            "Which screens can each role use whose events eventually write this data shape, and through which task?"
        ),
        focusVariable="shape",
        focusType=SH.NodeShape,
    ),
    "unfired-transitions": CannedQuery(
        name="unfired-transitions",
        label="Which transitions does nothing fire?",
        question="Which transitions of this lifecycle does no process task fire, so no scenario can exercise them?",
        focusVariable="lifecycle",
        focusType=STATE.StateMachine,
        source="coverage/unfired-transitions",
    ),
    "policies-without-deny": CannedQuery(
        name="policies-without-deny",
        label="Which permissions have no deny test?",
        question="Which permissions of this policy get no party deny test from the tests generator?",
        focusVariable="policy",
        focusType=ODRL2.Policy,
        source="coverage/policies-without-deny",
    ),
    "unexercised-paths": CannedQuery(
        name="unexercised-paths",
        label="Which paths does no scenario run?",
        question="Which start-to-end paths through this process does no verify scenario exercise?",
        focusVariable="process",
        focusType=PROC.Process,
        source=None,
    ),
}


def _unexercised_paths(model: seams.Model, focus: URIRef) -> tuple[list[str], list[dict[str, str]]]:
    """seams.coverage.unexercised_paths for one process, as columns and rows.

    A focus that is not a proc:Process of the model gives no rows (the same
    empty answer a SPARQL query gives for a non-applicable focus).
    """
    columns = ["start", "end", "path"]
    try:
        paths = seams.unexercised_paths(model, focus)
    except seams.ResolutionError:
        return columns, []
    rows = [{"start": str(p.start.iri), "end": str(p.end.iri), "path": " → ".join(p.bpmn_ids)} for p in paths]
    return columns, rows


PYTHON_ANSWERS: dict[str, Callable[[seams.Model, URIRef], tuple[list[str], list[dict[str, str]]]]] = {
    "unexercised-paths": _unexercised_paths,
}


def load_query(name: str) -> str:
    """Return the SPARQL text for a catalog query.

    Raises KeyError for names not in QUERIES before touching the seams
    bundle, so a hostile name can never become a path component (no path
    traversal; seams.load_question checks the name again).
    """
    if name not in QUERIES:
        raise KeyError(f"unknown canned query: {name!r}")
    source = QUERIES[name].source
    if source is None:
        raise KeyError(f"canned query {name!r} is answered by seams.coverage, not SPARQL")
    return seams.load_question(source or name)


def is_applicable(graph, focus_iri: str, query: CannedQuery) -> bool:
    """Whether a query's focus binding makes sense for this element.

    Explicit instance-level rdf:type check only — no RDFS/OWL inference, so
    subclasses of the focus type are missed. False negatives are acceptable
    v1 behavior (a button not shown, never a broken one).
    """
    return (URIRef(focus_iri), RDF.type, query.focusType) in graph


def execute_query(graph, query_name: str, focus_iri: str, model: seams.Model | None = None) -> dict:
    """Run a canned query with the focus element bound, returning a JSON-able dict.

    The focus IRI reaches the query only through initBindings as a URIRef —
    never interpolated into the query string. A Python-answered query
    (PYTHON_ANSWERS) needs the loaded ``model`` that ``graph`` belongs to.
    """
    query = QUERIES[query_name]
    focus = URIRef(focus_iri)
    start = time.perf_counter()
    rows = []
    truncated = False
    if query.source is None:
        if model is None:
            raise ValueError(f"canned query {query_name!r} is answered by seams.coverage and needs the loaded model")
        columns, answer = PYTHON_ANSWERS[query_name](model, focus)
        truncated = len(answer) > MAX_ROWS
        rows = answer[:MAX_ROWS]
    else:
        result = graph.query(load_query(query_name), initBindings={query.focusVariable: focus})
        columns = [str(var) for var in result.vars]
        for binding_row in result:
            if len(rows) >= MAX_ROWS:
                truncated = True
                break
            rows.append(
                {col: (str(val) if val is not None else "") for col, val in zip(columns, binding_row, strict=False)}
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
