"""Tests for the node-card data in viewer/app.py (M006/S01): layer_of(),
type_label(), description_of() and the typeLabel/description/layer/seams
fields nodes_for() adds for the shared card renderer, plus the additive
targetLayer/sourceLayer/layer fields on the /view contract (MEM016).
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
MESSAGE_LIFECYCLE = f"{CHAT}message_lifecycle"
CHAT_UI = f"{CHAT}chat_ui"
CHAT_API = f"{CHAT}chat_api"
UI_TECHNOLOGY = "htmx + server-rendered fragments"


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


@pytest.mark.parametrize(
    "target, layer",
    [
        (f"{CHAT}app01", "architecture"),
        (f"{CHAT}chat_ifml", "interaction"),
        (f"{CHAT}send_message_process", "process"),
        (f"{CHAT}routing_decision", "decision"),
        (f"{CHAT}MessageShape", "data"),
        (f"{CHAT}t_send", "lifecycle"),
        (f"{CHAT}s_composing", "lifecycle"),
        (f"{CHAT}send_message_op", "other"),
        (f"{CHAT}user_send_policy", "other"),
        ("https://w3id.org/seams/seam#UIFragment", "other"),
    ],
)
def test_layer_of(target, layer):
    assert viewer_app.layer_of(target) == layer


def test_c4_nodes_carry_card_fields():
    nodes, _ = viewer_app.c4_graph_data(CHAT_ARCHITECTURE)
    assert nodes
    for node in nodes:
        assert {"id", "label", "group", "typeLabel", "description", "layer", "seams"} <= node.keys()
        assert node["layer"] == "architecture"
        assert isinstance(node["seams"], list)


def test_web_ui_container_card():
    nodes, _ = viewer_app.c4_graph_data(CHAT_ARCHITECTURE)
    ui = next(n for n in nodes if n["description"] == UI_TECHNOLOGY)
    assert ui["id"] == CHAT_UI
    assert ui["typeLabel"] == "Container"
    presents = [s for s in ui["seams"] if s["predicate"] == "seam:presents"]
    assert presents and presents[0]["targetLayer"] == "interaction"
    assert presents[0]["target"] == f"{CHAT}chat_ifml"
    for seam in ui["seams"]:
        assert {"predicate", "predicateLabel", "target", "targetLabel", "targetLayer"} <= seam.keys()


def test_card_seams_sorted_and_exclude_admin():
    seams = viewer_app.card_seams(CHAT_API)
    keys = [(s["predicate"], s["target"]) for s in seams]
    assert keys == sorted(keys)
    assert all(s["predicate"] not in {"seam:inModel", "seam:notation", "seam:renderPayload"} for s in seams)
    assert ("seam:deployedTo", f"{CHAT}app01") in keys


def test_chat_api_description_prefers_technology():
    assert viewer_app.description_of(CHAT_API) == "FastAPI, SSE streaming"


def test_statechart_nodes_are_lifecycle():
    nodes, _ = viewer_app.statechart_graph_data(MESSAGE_LIFECYCLE)
    assert nodes
    assert {n["layer"] for n in nodes} == {"lifecycle"}


def test_view_json_has_layers(client):
    resp = client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}?format=json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["layer"] == "architecture"
    for e in body["seamEdges"]["outgoing"]:
        assert "targetLayer" in e
    for e in body["seamEdges"]["incoming"]:
        assert "sourceLayer" in e


def test_seam_edges_layers_on_both_directions():
    edges = viewer_app.seam_edges(CHAT_UI)
    out = {e["target"]: e["targetLayer"] for e in edges["outgoing"]}
    assert out[f"{CHAT}chat_ifml"] == "interaction"
    assert out[f"{CHAT}send_message_op"] == "other"
    incoming = viewer_app.seam_edges(f"{CHAT}chat_ifml")["incoming"]
    assert any(e["source"] == CHAT_UI and e["sourceLayer"] == "architecture" for e in incoming)


def test_element_without_seams_has_empty_dots():
    # s_sending is a state with no seam edges at all.
    assert viewer_app.card_seams(f"{CHAT}s_sending") == []
    node = viewer_app.nodes_for({f"{CHAT}s_sending"})[0]
    assert node["seams"] == []
    assert node["description"] is None


def test_untyped_undescribed_element():
    iri = "https://w3id.org/seams/seam#UIFragment"
    assert viewer_app.type_label(iri) == "Element"
    assert viewer_app.description_of(iri) is None
    assert viewer_app.layer_of(iri) == "other"
    node = viewer_app.nodes_for({iri})[0]
    assert node["typeLabel"] == "Element"
    assert node["description"] is None
    assert node["seams"] == []


def test_unknown_iri_does_not_error():
    iri = f"{CHAT}does_not_exist"
    assert viewer_app.layer_of(iri) == "other"
    assert viewer_app.type_label(iri) == "Element"
    assert viewer_app.description_of(iri) is None
    assert viewer_app.card_seams(iri) == []
