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


# --- HTTP-level contract tests (S02 T02): modelConformance in /view/{iri} ---

ROOT_IRI = "https://example.org/chat/chat_architecture"
ROUTING_DECISION = "https://example.org/chat/routing_decision"


def _client():
    from fastapi.testclient import TestClient

    return TestClient(viewer_app.app)


def test_view_json_contains_model_conformance():
    """GET /view/{root}?format=json carries the additive modelConformance
    field with the loaded (conforming) model's summary."""
    resp = _client().get(f"/view/{ROOT_IRI}", params={"format": "json"})
    assert resp.status_code == 200
    mc = resp.json()["modelConformance"]
    assert mc["conforms"] is True
    assert mc["violationCount"] == 0
    assert mc["violations"] == []


def test_view_json_preexisting_contract_fields_unbroken():
    """Regression guard: adding modelConformance must not disturb the
    ADR-0004 response contract fields."""
    resp = _client().get(f"/view/{ROOT_IRI}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    for field in ("@id", "label", "seamEdges", "breadcrumbs", "detailedByCandidates", "warnings"):
        assert field in body, f"missing pre-existing contract field {field}"
    assert body["@id"] == ROOT_IRI


def test_disambiguation_response_also_carries_model_conformance():
    """The S01 multi-detailedBy fixture (routing_decision) renders a
    disambiguation response, not an auto-navigation — modelConformance must
    be present on that response shape too."""
    resp = _client().get(f"/view/{ROUTING_DECISION}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == ROUTING_DECISION
    assert len(body["detailedByCandidates"]) == 2
    mc = body["modelConformance"]
    assert mc["conforms"] is True
    assert mc["violationCount"] == 0


# --- HTML shell tests (S02 T03): health panel renders in page.html only ---


def test_full_page_renders_health_panel():
    """A full-page HTML render carries the health panel with the green
    Conforms badge for the (conforming) chat-app model."""
    resp = _client().get(f"/view/{ROOT_IRI}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    html = resp.text
    assert 'class="health-panel"' in html
    assert "Conforms" in html
    assert 'data-conforms="true"' in html


def test_fragment_response_omits_health_panel():
    """The htmx fragment path (hx-request: true) swaps only #view-content;
    the health panel lives in the shell and must not re-render there."""
    resp = _client().get(
        f"/view/{ROOT_IRI}",
        headers={"Accept": "text/html", "hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "health-panel" not in resp.text


# --- Storage health (M011/S04 T02): store_health() findings in the panel ---

DEPLOY = Namespace("https://w3id.org/seams/deploy#")
CHAT_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
CH07_TRIG = ROOT / "examples" / "expenses" / "chapter-07" / "expenses.trig"
STORE = "https://example.org/store/"

STORE_PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/store/> .
"""

UNUSED_STORE = """
<urn:test:graph:spare> {
    <https://example.org/store/spare_db> a <https://w3id.org/seams/arch#Container> ;
        <http://www.w3.org/2000/01/rdf-schema#label> "Spare Store" ;
        <https://w3id.org/seams/deploy#storeKind> <https://w3id.org/seams/deploy#PostgreSQL> .
}
"""


def _dataset(*trig_texts: str, files: tuple[Path, ...] = ()) -> rdflib.Dataset:
    ds = rdflib.Dataset(default_union=True)
    for path in files:
        ds.parse(path, format="trig")
    for text in trig_texts:
        ds.parse(data=text, format="trig")
    return ds


def test_loaded_chat_app_warns_only_about_the_replica_cap():
    """No store warnings or notes; :chat_api's deploy:replicas 3 is capped at
    one replica until backlog A10 (ADR-0015), which model health shows."""
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is True
    [warning] = result["warnings"]
    assert warning["focusNode"] == "https://example.org/chat/chat_api"
    assert warning["path"] == str(DEPLOY.replicas)
    assert "A10" in warning["message"]
    assert result["notes"] == []


def test_unused_postgres_store_warns_and_still_conforms():
    """A declared store no shape is seam:storedIn (the original chat-app
    mismatch) is a warning, not a violation."""
    result = validation.get_model_conformance(_dataset(UNUSED_STORE, files=(CHAT_TRIG,)))
    assert result["conforms"] is True
    assert result["violations"] == []
    [warning] = [w for w in result["warnings"] if w["path"] != str(DEPLOY.replicas)]
    assert warning["focusNode"] == STORE + "spare_db"
    assert warning["path"] == str(SEAM.storedIn)
    assert warning["severity"] == "Warning"
    assert result["notes"] == []


def test_unsupported_store_kind_is_a_violation():
    """A written shape stored in a store whose kind the runtime does not
    support fails the panel with a deploy:storeKind violation."""
    trig = (
        STORE_PREFIXES
        + """
<urn:test:graph:store> {
    :api a arch:Container ; rdfs:label "API" ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "DB_URL" ; deploy:value "mongodb://x" ; deploy:connectsTo :db ] ] .
    :db a arch:Container ; rdfs:label "DB" ; deploy:storeKind deploy:MongoDB .
    :MessageShape a sh:NodeShape ; rdfs:label "Message" ; seam:storedIn :db .
}
"""
    )
    result = validation.get_model_conformance(_dataset(trig))
    assert result["conforms"] is False
    assert result["violationCount"] == len(result["violations"])
    # SHACL flags the kind too; the store_health one carries no sourceShape.
    [store_violation] = [
        v for v in result["violations"] if v["path"] == str(DEPLOY.storeKind) and v["sourceShape"] is None
    ]
    assert store_violation["focusNode"] == STORE + "db"
    assert store_violation["severity"] == "Violation"


def test_no_store_model_conforms_with_an_embedded_sqlite_note():
    result = validation.get_model_conformance(_dataset(files=(CH07_TRIG,)))
    assert result["conforms"] is True
    assert result["warnings"] == []
    [note] = result["notes"]
    assert note["severity"] == "Info"
    assert note["focusNode"] is None
    assert "SQLite" in note["message"]


def test_broken_dataset_keeps_store_lists():
    result = validation.get_model_conformance(_broken_dataset())
    assert isinstance(result["warnings"], list)
    assert isinstance(result["notes"], list)


@pytest.fixture
def unused_store_viewer(tmp_path, monkeypatch):
    """The chat app plus an unused PostgreSQL store, loaded by the viewer."""
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    model = tmp_path / "chat-app.trig"
    model.write_text(CHAT_TRIG.read_text() + UNUSED_STORE)
    viewer_app.configure(model)
    yield
    viewer_app.configure(original)


def test_full_page_renders_store_warning(unused_store_viewer):
    resp = _client().get(f"/view/{ROOT_IRI}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    html = resp.text
    assert 'data-conforms="true"' in html
    assert 'data-warnings="2"' in html  # the unused store and the chat app's replica cap
    assert STORE + "spare_db" in html
    json_mc = _client().get(f"/view/{ROOT_IRI}", params={"format": "json"}).json()["modelConformance"]
    assert len(json_mc["warnings"]) == 2


def test_fragment_response_omits_store_warning(unused_store_viewer):
    resp = _client().get(
        f"/view/{ROOT_IRI}",
        headers={"Accept": "text/html", "hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "data-warnings" not in resp.text


def test_failing_store_check_is_reported_as_a_violation(monkeypatch):
    def boom(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(validation.seams.ModelGraph, "store_health", boom)
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is False
    assert result["violationCount"] == len(result["violations"]) == 1
    assert "store health check failed: boom" in result["violations"][0]["message"]
