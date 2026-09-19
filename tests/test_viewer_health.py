"""Tests for viewer/validation.py's SHACL conformance summary (S02 T01).

Exercises viewer.validation.get_model_conformance() against the real loaded
chat-app model (conforming) and a deliberately broken in-memory Dataset
(non-conforming), plus the per-dataset cache behavior.
"""

import sys
from pathlib import Path

import pytest
import rdflib
from rdflib import Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

SEAM = Namespace("https://w3id.org/seams/seam#")
EX = Namespace("https://example.org/broken/")


@pytest.fixture(autouse=True)
def clear_conformance_cache():
    """id()-keyed cache: clear before each test so a garbage-collected
    Dataset's recycled id cannot serve another test's stale result."""
    validation._clear_cache()
    yield


def _broken_dataset() -> rdflib.Dataset:
    """Violates seamsh:DetailedByShape (seam-shapes.ttl line 52):
    seam:detailedBy must point at a seam:Model, but ex:not_a_model
    carries no type at all."""
    ds = rdflib.Dataset()
    g = ds.graph(URIRef("urn:test:graph:broken"))
    g.add((EX.thing, SEAM.detailedBy, EX.not_a_model))
    return ds


def test_loaded_model_conforms():
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is True
    assert result["violationCount"] == 0
    assert result["violations"] == []


def test_non_conforming_dataset_reports_violations():
    result = validation.get_model_conformance(_broken_dataset())
    assert result["conforms"] is False
    assert result["violationCount"] >= 1
    assert result["violationCount"] == len(result["violations"])
    for v in result["violations"]:
        assert v["focusNode"]
        assert v["message"]
        assert v["severity"]


def test_violation_details_carry_shape_provenance():
    """The broken fixture's violation must name the offending node and read
    as a Violation-severity result — the fields the health panel renders."""
    result = validation.get_model_conformance(_broken_dataset())
    focus_nodes = {v["focusNode"] for v in result["violations"]}
    assert str(EX.not_a_model) in focus_nodes
    assert any(v["severity"] == "Violation" for v in result["violations"])


def test_cache_returns_same_object_for_same_dataset():
    ds = viewer_app.get_graph()
    first = validation.get_model_conformance(ds)
    second = validation.get_model_conformance(ds)
    assert first is second


def test_clear_cache_forces_revalidation():
    ds = viewer_app.get_graph()
    first = validation.get_model_conformance(ds)
    validation._clear_cache()
    second = validation.get_model_conformance(ds)
    assert first is not second
    assert first == second
