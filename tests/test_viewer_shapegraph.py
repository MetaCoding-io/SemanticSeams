"""Tests for viewer/shapegraph.py (M007/S03, D022): the frames, property cards
and sh:class/sh:node edges a seam:ShapeGraph model hands to the shared ELK
card renderer, and the self-landing rule that keeps ConversationShape on
its own model's shape graph. Template assertions live with T02.
"""

import sys
from pathlib import Path

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer.shapegraph import shapegraph_graph_data  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_DATA_SHAPES = f"{CHAT}chat_data_shapes"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
MESSAGE_SHAPE = f"{CHAT}MessageShape"
CONVERSATION_SHAPE = f"{CHAT}ConversationShape"


def prop_id(shape: str, path: str) -> str:
    return f"{shape}::property::{viewer_app.qname(URIRef(CHAT + path))}"


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


@pytest.fixture
def data():
    nodes, edges = shapegraph_graph_data(CHAT_DATA_SHAPES)
    return {n["id"]: n for n in nodes}, nodes, edges


def test_frames_for_each_node_shape(data):
    by_id, nodes, _ = data
    frames = [n for n in nodes if n["parent"] is None]
    assert [f["id"] for f in frames] == [CONVERSATION_SHAPE, MESSAGE_SHAPE]
    for f in frames:
        assert f["layer"] == "data"
        assert f["typeLabel"] == "Node shape"
        assert f["navigateTo"] == f["id"]
        assert f["nestedVia"] is None
        assert f["focused"] is False
    assert by_id[MESSAGE_SHAPE]["label"] == "Message"


def test_message_property_cards_follow_sh_order(data):
    _, nodes, _ = data
    labels = [n["label"] for n in nodes if n["parent"] == MESSAGE_SHAPE]
    assert labels == ["content", "role", "status", "timestamp"]


def test_property_card_fields(data):
    _, nodes, _ = data
    cards = [n for n in nodes if n["parent"] is not None]
    assert len(cards) == 7
    for c in cards:
        assert "::property::" in c["id"]
        assert c["typeLabel"] == "Property"
        assert c["group"] == c["type"] == "sh:PropertyShape"
        assert c["layer"] == "data"
        assert c["seams"] == []
        assert c["focused"] is False


def test_property_descriptions(data):
    by_id, _, _ = data
    content = by_id[prop_id(MESSAGE_SHAPE, "content")]["description"]
    assert "xsd:string" in content and "1..1" in content
    assert "0..1" in by_id[prop_id(MESSAGE_SHAPE, "timestamp")]["description"]
    assert "one of 5" in by_id[prop_id(MESSAGE_SHAPE, "status")]["description"]
    has_message = by_id[prop_id(CONVERSATION_SHAPE, "hasMessage")]["description"]
    assert "0..*" in has_message and "Message" in has_message


def test_sh_class_reference_navigates_and_draws_edge(data):
    by_id, _, edges = data
    card = prop_id(CONVERSATION_SHAPE, "hasMessage")
    assert by_id[card]["navigateTo"] == MESSAGE_SHAPE
    assert edges == [{"from": card, "to": MESSAGE_SHAPE, "label": "sh:class"}]
    # Datatype properties navigate to their own shape.
    assert by_id[prop_id(MESSAGE_SHAPE, "content")]["navigateTo"] == MESSAGE_SHAPE


def test_output_is_deterministic():
    assert shapegraph_graph_data(CHAT_DATA_SHAPES) == shapegraph_graph_data(CHAT_DATA_SHAPES)


def test_focus_marks_only_that_frame():
    nodes, _ = shapegraph_graph_data(CHAT_DATA_SHAPES, focus=CONVERSATION_SHAPE)
    assert [n["id"] for n in nodes if n["focused"]] == [CONVERSATION_SHAPE]


@pytest.mark.parametrize("model", [CHAT_ARCHITECTURE, f"{CHAT}no_such_model"])
def test_non_shape_or_unknown_model_is_empty(model):
    assert shapegraph_graph_data(model) == ([], [])


def test_pathless_property_skipped_and_cyclic_node_only_edges():
    """A property with no sh:path draws nothing; an sh:node back to its own
    shape adds an edge and does not recurse."""
    graph = viewer_app.get_graph()
    shape = URIRef(CONVERSATION_SHAPE)
    pathless, cyclic = BNode(), BNode()
    added = [
        (shape, SH.property, pathless),
        (pathless, SH.datatype, URIRef("http://www.w3.org/2001/XMLSchema#string")),
        (shape, SH.property, cyclic),
        (cyclic, SH.path, URIRef(f"{CHAT}parent")),
        (cyclic, SH.node, shape),
        (cyclic, SH.maxCount, Literal(1)),
    ]
    for t in added:
        graph.add(t)
    try:
        nodes, edges = shapegraph_graph_data(CHAT_DATA_SHAPES)
    finally:
        for t in added:
            graph.remove(t)
    cards = [n for n in nodes if n["parent"] == CONVERSATION_SHAPE]
    assert len(cards) == 4
    card = prop_id(CONVERSATION_SHAPE, "parent")
    assert {"from": card, "to": CONVERSATION_SHAPE, "label": "sh:node"} in edges
    assert next(n for n in cards if n["id"] == card)["description"] == "→ Conversation · 0..1"


def test_navigation_unchanged():
    assert viewer_app.resolve_navigation(CONVERSATION_SHAPE)["landing"] == CONVERSATION_SHAPE
    assert viewer_app.resolve_navigation(MESSAGE_SHAPE)["landing"] == CHAT_DATA_SHAPES


def test_shapegraph_registered():
    assert "shapegraph" in viewer_app.RENDERERS_IMPLEMENTED
    assert viewer_app.GRAPH_BUILDERS["shapegraph"] is shapegraph_graph_data


def test_json_contract_keeps_notation(client):
    """D022 self-landing is template-only: the ADR-0004 JSON is unchanged."""
    resp = client.get(f"/view/{CONVERSATION_SHAPE}", headers={"accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["notation"] == "none"
    resp = client.get(f"/view/{MESSAGE_SHAPE}", headers={"accept": "application/json"})
    assert resp.json()["notation"] == "shapegraph"
