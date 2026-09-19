"""Reusable SHACL conformance check for the viewer's loaded model.

The viewer's Dataset (see viewer/app.py get_graph()) loads only
examples/chat-app/chat-app.trig — it carries no ontology triples. The shapes
in ontology/shapes/seam-shapes.ttl rely on subclass closure from the ontology
files (sh:class checks), so validation here mirrors tests/validate_chat_app.py:
merge the ontology .ttl files with the dataset's quads into one union graph,
then run pyshacl against seam-shapes.ttl with inference off.

Results are cached per Dataset identity: the model is loaded once per process,
so each dataset is validated at most once.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import rdflib
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


def get_model_conformance(ds: rdflib.Dataset) -> dict:
    """Validate the dataset (plus ontology closure) against seam-shapes.ttl.

    Returns {"conforms": bool, "violationCount": int, "violations": list[dict]}
    where each violation carries focusNode, path, message, severity, and
    sourceShape (path and sourceShape may be None).
    """
    key = id(ds)
    if key in _cache:
        return _cache[key]

    union = _build_union(ds)
    conforms, results_graph, _text = pyshacl.validate(
        union, shacl_graph=str(SHAPES_FILE), inference="none"
    )

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

    summary = {
        "conforms": bool(conforms),
        "violationCount": len(violations),
        "violations": violations,
    }
    _cache[key] = summary
    return summary
