"""Tests for per-predicate reveal modes (M007/S02, ADR-0005 as amended).

ontology/seam.ttl gives every non-administrative seam predicate one seam:reveal
(open, nest or layer), seamsh:RevealShape checks it, and viewer/app.py derives
click navigation and the seamEdges "reveal" field from it.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pyshacl
import pytest
import rdflib
from rdflib import RDF, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402

SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")
SEAM_TTL = ROOT / "ontology" / "seam.ttl"
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
CHAT = "https://example.org/chat/"

ADMIN = {SEAM.inModel, SEAM.notation, SEAM.renderPayload}
MODES = {SEAM.Open, SEAM.Nest, SEAM.Layer}
DEFAULTS = {
    "nest": {"presents", "executes"},
    "open": {"detailedBy", "triggers", "decidedBy", "lifecycle"},
}


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def seam_ontology() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(SEAM_TTL, format="turtle")
    return g


def seam_properties(g: rdflib.Graph) -> set[URIRef]:
    return {p for p in g.subjects(RDF.type, RDF.Property) if str(p).startswith(str(SEAM))} - ADMIN


def shacl_conforms(g: rdflib.Graph) -> bool:
    conforms, _, _ = pyshacl.validate(g, shacl_graph=str(SHAPES_FILE), inference="none")
    return conforms


# ---------------------------------------------------------------- ontology


def test_every_seam_predicate_has_exactly_one_known_mode():
    g = seam_ontology()
    props = seam_properties(g)
    assert len(props) >= 20
    for p in props:
        values = set(g.objects(p, SEAM.reveal))
        assert len(values) == 1, f"{p} has {len(values)} reveal values"
        assert values <= MODES, f"{p} has unknown reveal {values}"


def test_admin_predicates_carry_no_reveal():
    g = seam_ontology()
    for p in ADMIN:
        assert g.value(p, SEAM.reveal) is None


def test_reveal_is_an_annotation_not_a_seam_edge():
    # An rdf:Property would have to be exercised in checkout.trig
    # (test_every_nonreserved_seam_predicate_is_exercised); it describes predicates.
    g = seam_ontology()
    assert (SEAM.reveal, RDF.type, rdflib.OWL.AnnotationProperty) in g
    assert (SEAM.reveal, RDF.type, RDF.Property) not in g


def test_default_modes():
    g = seam_ontology()
    for mode, names in DEFAULTS.items():
        for name in names:
            assert g.value(SEAM[name], SEAM.reveal) == SEAM[mode.capitalize()], name
    named = set().union(*DEFAULTS.values())
    for p in seam_properties(g):
        if p.split("#")[1] not in named:
            assert g.value(p, SEAM.reveal) == SEAM.Layer, p


def test_reveal_shape_targets_every_seam_predicate():
    # The shape's sh:targetNode list is hand-kept: a new seam predicate must join it.
    shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    targets = set(shapes.objects(SEAMSH.RevealShape, SH.targetNode))
    assert targets == seam_properties(seam_ontology())


# ---------------------------------------------------------------- SHACL


def test_seam_ontology_conforms_to_reveal_shape():
    assert shacl_conforms(seam_ontology())


def test_reveal_shape_rejects_two_modes():
    g = seam_ontology()
    g.add((SEAM.reads, SEAM.reveal, SEAM.Open))  # reads is already layer
    assert not shacl_conforms(g)


def test_reveal_shape_rejects_an_unknown_mode():
    g = seam_ontology()
    g.remove((SEAM.reads, SEAM.reveal, None))
    g.add((SEAM.reads, SEAM.reveal, SEAM.Explode))
    assert not shacl_conforms(g)


def test_reveal_shape_rejects_a_missing_mode():
    g = seam_ontology()
    g.remove((SEAM.writes, SEAM.reveal, None))
    assert not shacl_conforms(g)


# ---------------------------------------------------------------- viewer


def test_reveal_mode_reads_the_ontology():
    assert viewer_app.reveal_mode(SEAM.presents) == "nest"
    assert viewer_app.reveal_mode(SEAM.detailedBy) == "open"
    assert viewer_app.reveal_mode(str(SEAM.reads)) == "layer"


def test_reveal_mode_falls_back_to_layer():
    assert viewer_app.reveal_mode(URIRef("https://example.org/unannotated#p")) == "layer"
    assert viewer_app.reveal_mode(SEAM.inModel) == "layer"


def test_model_graph_reveal_overrides_the_ontology(monkeypatch):
    g = rdflib.Dataset(default_union=True)
    g.add((SEAM.reads, SEAM.reveal, SEAM.Open))
    g.add((SEAM.presents, SEAM.reveal, SEAM.Layer))
    monkeypatch.setattr(viewer_app, "get_graph", lambda: g)
    assert viewer_app.reveal_mode(SEAM.reads) == "open"
    assert viewer_app.reveal_mode(SEAM.presents) == "layer"
    navigational = viewer_app.navigational_predicates()
    assert SEAM.reads in navigational
    assert SEAM.presents not in navigational


def test_navigational_predicates():
    assert viewer_app.navigational_predicates() == {
        SEAM.detailedBy,
        SEAM.triggers,
        SEAM.presents,
        SEAM.decidedBy,
        SEAM.executes,
        SEAM.lifecycle,
    }


@pytest.mark.parametrize(
    "iri",
    [f"{CHAT}chat_bpmn", f"{CHAT}send_message_op", f"{CHAT}chat_ifml", f"{CHAT}completion_op"],
)
def test_json_seam_edges_carry_reveal(client, iri):
    resp = client.get(f"/view/{quote(iri, safe='')}?format=json")
    assert resp.status_code == 200
    edges = resp.json()["seamEdges"]
    rows = edges["outgoing"] + edges["incoming"]
    assert rows
    for e in rows:
        assert e["reveal"] in {"open", "nest", "layer"}
        assert e["navigational"] == (e["reveal"] != "layer")


def test_card_seams_carry_reveal():
    seams = viewer_app.card_seams(f"{CHAT}chat_api")
    by_pred = {s["predicate"]: s["reveal"] for s in seams}
    assert by_pred["seam:executes"] == "nest"
    assert by_pred["seam:deployedTo"] == "layer"


def test_chat_api_navigates_through_executes():
    # seam:executes is nest, so it navigates: chat_api -> send_message_process
    # -> seam:detailedBy -> chat_bpmn.
    nav = viewer_app.resolve_navigation(f"{CHAT}chat_api")
    assert nav["target"] == f"{CHAT}chat_bpmn"
    assert nav["landing"] == f"{CHAT}chat_bpmn"


def test_layer_only_element_stays_put():
    nav = viewer_app.resolve_navigation(f"{CHAT}send_message_op")
    assert nav["target"] is None
    assert nav["landing"] == f"{CHAT}send_message_op"
