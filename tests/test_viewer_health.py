"""Tests for viewer/validation.py's SHACL conformance summary (S02 T01).

Exercises viewer.validation.get_model_conformance() against the real loaded
chat-app model (conforming) and a deliberately broken in-memory Dataset
(non-conforming), plus the per-dataset cache behavior, the storage health
findings, the static decision warnings (backlog K2, X13) and the model review
warnings (backlog R1).
"""

import shutil
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


CHAT = "https://example.org/chat/"
SH_PATH = "http://www.w3.org/ns/shacl#path"
SH_TARGET_CLASS = "http://www.w3.org/ns/shacl#targetClass"

# The chat app's model review findings (backlog R1) as (focusNode, path).
CHAT_REVIEW = [
    (CHAT + "ConversationShape", SH_TARGET_CLASS),
    (CHAT + "ConversationShape", CHAT + "hasMessage"),
    (CHAT + "MessageShape", SH_TARGET_CLASS),
    (CHAT + "MessageShape", CHAT + "status"),
    *((CHAT + name, SH_PATH) for name in ("content", "hasMessage", "id", "role", "status", "timestamp", "title")),
]


def _review_warnings(ds: rdflib.Dataset) -> list[dict]:
    """The warnings seams.review_findings gives for ds, as the panel shows them."""
    model = validation.seams.ModelGraph(ROOT / "viewer.trig", dataset=ds)
    return [
        {"focusNode": f.subject, "path": f.fact, "message": f.message, "severity": "Warning", "sourceShape": None}
        for f in validation.seams.review_findings(model)
    ]


def _store_warnings(result: dict, ds: rdflib.Dataset) -> list[dict]:
    """The warnings before the review findings, which must close the list."""
    review = _review_warnings(ds)
    split = len(result["warnings"]) - len(review)
    assert result["warnings"][split:] == review
    return result["warnings"][:split]


def test_loaded_chat_app_warns_about_the_replica_cap_and_review_findings():
    """No store warnings or notes; :chat_api's deploy:replicas 3 is capped at
    one replica until backlog A10 (ADR-0015), then one warning per model
    review finding (backlog R1)."""
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is True
    replicas, *review = result["warnings"]
    assert replicas["focusNode"] == "https://example.org/chat/chat_api"
    assert replicas["path"] == str(DEPLOY.replicas)
    assert "A10" in replicas["message"]
    assert [(w["focusNode"], w["path"]) for w in review] == CHAT_REVIEW
    assert {w["severity"] for w in review} == {"Warning"}
    assert {w["sourceShape"] for w in review} == {None}
    by_fact = {(w["focusNode"], w["path"]): w["message"] for w in review}
    assert by_fact[(CHAT + "MessageShape", CHAT + "status")] == (
        "sh:in on status copies the rdfs:labels of message_lifecycle's states, so it can drift "
        "from the lifecycle; use the state IRIs (s_composing, s_sending, s_streaming, s_complete, s_failed)"
    )
    assert by_fact[(CHAT + "ConversationShape", CHAT + "hasMessage")] == (
        "sh:class on hasMessage is MessageShape, a sh:NodeShape, not a class; "
        "declare the class and give the shape sh:targetClass"
    )
    assert result["notes"] == []


REVIEW_ONLY = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix :     <https://example.org/review/> .
<urn:test:graph:review> {
    :ThingShape a sh:NodeShape ; rdfs:label "Thing" ;
        sh:property [ sh:path :name ] .
}
"""


def test_review_findings_never_change_conforms():
    """A model whose only faults are review findings conforms, with no
    violations and one warning per finding."""
    ds = _dataset(REVIEW_ONLY)
    result = validation.get_model_conformance(ds)
    assert result["conforms"] is True
    assert result["violations"] == []
    assert [(w["focusNode"], w["path"]) for w in result["warnings"]] == [
        ("https://example.org/review/ThingShape", SH_TARGET_CLASS),
        ("https://example.org/review/name", SH_PATH),
    ]
    assert result["warnings"] == _review_warnings(ds)


def _unique_chapter_09(tmp_path: Path) -> rdflib.Dataset:
    """Chapter 9 copied to tmp_path with approval.dmn's FIRST table made UNIQUE."""
    src = ROOT / "examples/expenses/chapter-09"
    for path in [src / "expenses.trig", *src.glob("*.bpmn"), *src.glob("*.dmn")]:
        shutil.copy(path, tmp_path / path.name)
    dmn = tmp_path / "approval.dmn"
    dmn.write_text(dmn.read_text().replace('hitPolicy="FIRST"', 'hitPolicy="UNIQUE"', 1))
    return _dataset(files=(tmp_path / "expenses.trig",))


def test_overlapping_unique_table_rules_are_warnings(tmp_path):
    """seams.decision_findings reads the copied DMN: each overlapping rule pair
    of a UNIQUE table is one Warning on the decision, just before the review
    findings, and the model still conforms."""
    ds = _unique_chapter_09(tmp_path)
    result = validation.get_model_conformance(ds)
    assert result["conforms"] is True
    table = "of UNIQUE table 'approval_routing' in approval.dmn both match amount = 99"
    decision = [w for w in result["warnings"] if w["path"] == "dmn:rule"]
    assert decision == [
        {
            "focusNode": "https://example.org/expenses/approval_routing",
            "path": "dmn:rule",
            "message": f"rules {a!r} and {b!r} {table}",
            "severity": "Warning",
            "sourceShape": None,
        }
        for a, b in [("rule_auto", "rule_finance"), ("rule_auto", "rule_manager"), ("rule_manager", "rule_finance")]
    ]
    assert result["warnings"][-len(_review_warnings(ds)) - len(decision) :][: len(decision)] == decision


def test_failing_decision_check_is_one_warning(monkeypatch):
    def boom(model):
        raise RuntimeError("boom")

    monkeypatch.setattr(validation.seams, "decision_findings", boom)
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is True
    assert {
        "focusNode": None,
        "path": None,
        "message": "decision check failed: boom",
        "severity": "Warning",
        "sourceShape": None,
    } in result["warnings"]


def test_failing_review_check_is_one_warning(monkeypatch):
    def boom(model):
        raise RuntimeError("boom")

    monkeypatch.setattr(validation.seams, "review_findings", boom)
    result = validation.get_model_conformance(viewer_app.get_graph())
    assert result["conforms"] is True
    assert result["violations"] == []
    replicas, failed = result["warnings"]
    assert replicas["path"] == str(DEPLOY.replicas)
    assert failed == {
        "focusNode": None,
        "path": None,
        "message": "model review check failed: boom",
        "severity": "Warning",
        "sourceShape": None,
    }


def test_full_page_renders_review_warnings():
    resp = _client().get(f"/view/{ROOT_IRI}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    html = resp.text
    assert 'data-conforms="true"' in html
    assert f'data-warnings="{1 + len(CHAT_REVIEW)}"' in html
    assert "MessageShape has no sh:targetClass" in html


def test_fragment_response_omits_review_warnings():
    resp = _client().get(
        f"/view/{ROOT_IRI}",
        headers={"Accept": "text/html", "hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "data-warnings" not in resp.text
    assert "has no sh:targetClass" not in resp.text


def test_unused_postgres_store_warns_and_still_conforms():
    """A declared store no shape is seam:storedIn (the original chat-app
    mismatch) is a warning, not a violation."""
    ds = _dataset(UNUSED_STORE, files=(CHAT_TRIG,))
    result = validation.get_model_conformance(ds)
    assert result["conforms"] is True
    assert result["violations"] == []
    [warning] = [w for w in _store_warnings(result, ds) if w["path"] != str(DEPLOY.replicas)]
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
    ds = _dataset(files=(CH07_TRIG,))
    result = validation.get_model_conformance(ds)
    assert result["conforms"] is True
    assert _store_warnings(result, ds) == []
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
    # the unused store, the chat app's replica cap and its review findings
    assert f'data-warnings="{2 + len(CHAT_REVIEW)}"' in html
    assert STORE + "spare_db" in html
    json_mc = _client().get(f"/view/{ROOT_IRI}", params={"format": "json"}).json()["modelConformance"]
    assert len(json_mc["warnings"]) == 2 + len(CHAT_REVIEW)


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


# ── sh:Warning results (ADR-0021 section 6) ──

VOCAB_V2 = ROOT / "tests" / "fixtures" / "vocab-v2"
CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01"


def test_a_warning_shape_result_is_a_warning_not_a_violation(monkeypatch):
    """Against the vocab-v2 fixture's shapes, chapter-01 as written (seam 1.0;
    the viewer's store check re-runs the version check against the shipped
    ontology, so the dataset is not migrated here) meets the sh:Warning shapes
    of the deprecated seam:Model and seam:inModel: four warnings, listed before
    the review findings, and the model still conforms."""
    import seams

    monkeypatch.setattr(validation, "ONTOLOGY_FILES", sorted(VOCAB_V2.glob("*.ttl")))
    monkeypatch.setattr(validation, "SHAPES_FILE", VOCAB_V2 / "shapes" / "seam-shapes.ttl")
    result = validation.get_model_conformance(seams.load(CHAPTER_01, check_versions=False).ds)
    assert result["conforms"] is True
    assert result["violationCount"] == 0
    shape_warnings = [w for w in result["warnings"] if w["sourceShape"] is not None]
    assert shape_warnings == result["warnings"][: len(shape_warnings)]
    assert len(shape_warnings) == 4
    assert {
        "focusNode": "https://example.org/expenses/expense_architecture",
        "path": None,
        "message": "seam:Model is deprecated since seam 2.0 and goes in seam 3.0.",
        "severity": "Warning",
        "sourceShape": "https://w3id.org/seams/shapes#ModelDeprecatedShape",
    } in shape_warnings


def test_a_violation_beside_a_warning_still_fails(monkeypatch):
    import seams

    monkeypatch.setattr(validation, "ONTOLOGY_FILES", sorted(VOCAB_V2.glob("*.ttl")))
    monkeypatch.setattr(validation, "SHAPES_FILE", VOCAB_V2 / "shapes" / "seam-shapes.ttl")
    ds = seams.load(CHAPTER_01, check_versions=False).ds
    for quad in _broken_dataset().quads((None, None, None, None)):
        ds.add(quad)
    result = validation.get_model_conformance(ds)
    assert result["conforms"] is False
    assert [v["severity"] for v in result["violations"]] == ["Violation"]
    assert any(w["severity"] == "Warning" and w["sourceShape"] for w in result["warnings"])
