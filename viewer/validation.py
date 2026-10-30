"""Reusable SHACL conformance check for the viewer's loaded model.

The viewer's Dataset (see viewer/app.py get_graph()) loads only the configured
model's TriG (SEAMS_MODEL, default examples/chat-app/chat-app.trig) — it
carries no ontology triples. The shapes
in ontology/shapes/seam-shapes.ttl rely on subclass closure from the ontology
files (sh:class checks), so validation here mirrors tests/validate_chat_app.py:
merge the ontology .ttl files with the dataset's quads into one union graph,
then run pyshacl against seam-shapes.ttl with inference off.

The same summary carries the storage health checks of ADR-0011
(seams.ModelGraph.store_health()): a store the runtime cannot resolve is a
violation, a declared store no shape is seam:storedIn is a warning, and a model
that declares no store gets a note that the runtime keeps embedded SQLite.

Results are cached per Dataset identity: the model is loaded once per process,
so each dataset is validated at most once.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import rdflib
import seams
from rdflib import Namespace

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"

SH = Namespace("http://www.w3.org/ns/shacl#")

# Conformance cache keyed by id(ds); the viewer holds one Dataset per process.
_cache: dict[int, dict] = {}


def _clear_cache() -> None:
    _cache.clear()


def _short_name(term) -> str:
    """Local name of a URIRef (e.g. sh:Violation -> 'Violation')."""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


def _build_union(ds: rdflib.Dataset) -> rdflib.Graph:
    union = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        union.parse(p, format="turtle")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    return union


def _finding(finding: seams.StoreFinding) -> dict:
    return {
        "focusNode": str(finding.subject) if finding.subject is not None else None,
        "path": str(finding.predicate) if finding.predicate is not None else None,
        "message": finding.message,
        "severity": finding.severity,
        "sourceShape": None,
    }


def _store_findings(ds: rdflib.Dataset) -> list[dict]:
    """store_health() over the same Dataset (no file is read when a dataset
    is passed). A failure of the check itself is reported as a violation
    rather than taking the page down."""
    try:
        findings = seams.ModelGraph(ROOT / "viewer.trig", dataset=ds).store_health()
    except Exception as err:
        return [
            {
                "focusNode": None,
                "path": None,
                "message": f"store health check failed: {err}",
                "severity": "Violation",
                "sourceShape": None,
            }
        ]
    return [_finding(f) for f in findings]


def get_model_conformance(ds: rdflib.Dataset) -> dict:
    """Validate the dataset (plus ontology closure) against seam-shapes.ttl,
    then run the storage health checks.

    Returns {"conforms": bool, "violationCount": int, "violations": list[dict],
    "warnings": list[dict], "notes": list[dict]}. Each entry carries focusNode,
    path, message, severity, and sourceShape (focusNode, path and sourceShape
    may be None). Store violations join ``violations`` and make the model not
    conform; warnings and notes do not change ``conforms``.
    """
    key = id(ds)
    if key in _cache:
        return _cache[key]

    union = _build_union(ds)
    conforms, results_graph, _text = pyshacl.validate(union, shacl_graph=str(SHAPES_FILE), inference="none")

    violations: list[dict] = []
    for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
        focus = results_graph.value(result, SH.focusNode)
        path = results_graph.value(result, SH.resultPath)
        message = results_graph.value(result, SH.resultMessage)
        severity = results_graph.value(result, SH.resultSeverity)
        source_shape = results_graph.value(result, SH.sourceShape)
        violations.append(
            {
                "focusNode": str(focus) if focus is not None else None,
                "path": str(path) if path is not None else None,
                "message": str(message) if message is not None else None,
                "severity": _short_name(severity) if severity is not None else None,
                "sourceShape": str(source_shape) if source_shape is not None else None,
            }
        )

    store = _store_findings(ds)
    violations += [f for f in store if f["severity"] == "Violation"]
    warnings = [f for f in store if f["severity"] == "Warning"]
    notes = [f for f in store if f["severity"] == "Info"]

    summary = {
        "conforms": bool(conforms) and not any(f["severity"] == "Violation" for f in store),
        "violationCount": len(violations),
        "violations": violations,
        "warnings": warnings,
        "notes": notes,
    }
    _cache[key] = summary
    return summary
