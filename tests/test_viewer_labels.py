"""Tests for friendly predicate labels in the seam-edge inspector (M003/S04).

predicate_label() resolves rdfs:label for seam predicates from the ontology
files (ontology/*.ttl) without loading ontology triples into the model-only
ModelStore Dataset (D004), falling back to the qname when no label exists.
seam_edges() threads the result through as predicateLabel on every outgoing
and incoming edge in the /view/{iri} JSON contract.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer.app import SEAM, predicate_label  # noqa: E402

CHAT = "https://example.org/chat/"
ROUTING_DECISION = f"{CHAT}routing_decision"
DB01 = f"{CHAT}db01"


def test_predicate_label_resolves_from_ontology():
    """Ontology-side rdfs:label wins even though the ModelStore Dataset holds
    zero ontology triples — proves the side lookup works."""
    assert predicate_label(SEAM.detailedBy) == "detailed by"
    assert predicate_label(SEAM.reads) == "reads"
    assert predicate_label(SEAM.deployedTo) == "deployed to"


def test_predicate_label_accepts_str_and_uriref():
    """Existing helpers accept either form; predicate_label must too."""
    assert predicate_label(str(SEAM.decidedBy)) == "decided by"
    assert predicate_label(SEAM.decidedBy) == "decided by"


def test_predicate_label_falls_back_to_qname():
    """An IRI with no rdfs:label anywhere (model or ontology) returns its
    qname/short name instead of raising or returning empty."""
    unlabeled = "https://example.org/nowhere#totallyUnlabeledPredicate"
    result = predicate_label(unlabeled)
    assert result
    assert "totallyUnlabeledPredicate" in result


def test_view_json_outgoing_edges_carry_predicate_label():
    """routing_decision self-lands (multi-detailedBy disambiguation, MEM012);
    its outgoing seam:detailedBy edges must carry predicateLabel 'detailed by'."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == ROUTING_DECISION
    detailed = [e for e in body["seamEdges"]["outgoing"] if e["predicate"] == "seam:detailedBy"]
    assert detailed, "expected seam:detailedBy outgoing edges on routing_decision"
    for e in detailed:
        assert e["predicateLabel"] == "detailed by"


def test_view_json_incoming_edges_carry_predicate_label():
    """db01 self-lands (MEM012) and has an incoming seam:deployedTo edge from
    message_db; the incoming edge must carry predicateLabel 'deployed to'."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{DB01}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == DB01
    deployed = [e for e in body["seamEdges"]["incoming"] if e["predicate"] == "seam:deployedTo"]
    assert deployed, "expected an incoming seam:deployedTo edge on db01"
    for e in deployed:
        assert e["predicateLabel"] == "deployed to"


def test_fragment_outgoing_edge_shows_friendly_label_with_qname_data_attr():
    """htmx fragment for routing_decision renders 'detailed by' as the visible
    predicate text while preserving the qname in data-predicate for debugging."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    assert "detailed by" in html
    assert 'data-predicate="seam:detailedBy"' in html


def test_fragment_incoming_edge_shows_friendly_label_with_qname_data_attr():
    """db01 self-lands (MEM012); its incoming seam:deployedTo edge renders as
    'deployed to' with the raw qname kept as data-predicate."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{DB01}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    assert "deployed to" in html
    assert 'data-predicate="seam:deployedTo"' in html


def test_fragment_no_longer_shows_raw_qname_as_visible_text():
    """The raw qname must survive only inside data-predicate, never as the
    visible <code> text of an edge's predicate label."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    assert '<code class="predicate-label"' in html
    assert ">seam:detailedBy</code>" not in html


def test_every_seam_edge_has_predicate_label_key():
    """Contract completeness: every outgoing and incoming entry carries a
    non-empty predicateLabel, on both fixtures exercised above."""
    client = TestClient(viewer_app.app)
    for iri in (ROUTING_DECISION, DB01):
        body = client.get(f"/view/{iri}", params={"format": "json"}).json()
        edges = body["seamEdges"]["outgoing"] + body["seamEdges"]["incoming"]
        assert edges, f"expected seam edges on {iri}"
        for e in edges:
            assert "predicateLabel" in e
            assert e["predicateLabel"]
