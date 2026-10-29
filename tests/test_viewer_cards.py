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
SEND_MESSAGE_OP = f"{CHAT}send_message_op"
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


# --- T02: card renderer, layer tokens, inspector side panel, wheel fix ---

LAYERS = ["architecture", "interaction", "process", "decision", "data", "lifecycle", "other"]
CHAT_BPMN = f"{CHAT}chat_bpmn"


def _fragment(client, iri):
    resp = client.get(f"/view/{quote(iri, safe='')}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    return resp.text


def test_full_page_has_all_layer_tokens(client):
    resp = client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    for layer in LAYERS:
        assert f"--layer-{layer}:" in resp.text
    assert "window.seamsLayerColours" in resp.text


def test_layer_tokens_are_shell_only(client):
    # The palette lives in page.html (MEM009) so it survives htmx swaps.
    assert "--layer-architecture:" not in _fragment(client, CHAT_ARCHITECTURE)


def test_c4_fragment_layout_and_card_renderer(client):
    html = _fragment(client, CHAT_ARCHITECTURE)
    assert 'class="view-layout"' in html
    assert 'class="view-canvas"' in html
    assert '<aside class="inspector">' in html
    assert '<section class="inspector">' not in html
    # C4 draws on ELK + SVG (ADR-0008), with the shared card data.
    assert "new ELK()" in html
    assert '"data-iri": n.id' in html
    assert 'class="level-toggle"' in html
    assert '"seams":' in html
    assert '"typeLabel":' in html
    # The inspector sits after the canvas column, inside the layout.
    assert html.index('class="view-canvas"') < html.index('<aside class="inspector">')


def test_ifml_fragment_is_not_vis_network(client):
    # IFML is drawn as IFML in server-side SVG (M006/S05, D011, ADR-0008).
    html = _fragment(client, f"{CHAT}chat_ifml")
    assert "new vis.Network" not in html
    assert 'class="ifml-diagram"' in html
    assert 'class="level-toggle"' not in html
    assert "new ELK()" not in html


def test_statechart_fragment_keeps_vis_card_renderer(client):
    # The statechart stays on vis-network with the S01 card (ADR-0008).
    html = _fragment(client, MESSAGE_LIFECYCLE)
    assert "new vis.Network" in html
    assert 'shape: "custom"' in html
    assert "ctxRenderer" in html
    assert 'class="ifml-diagram"' not in html


def test_inspector_seam_dots_carry_layers(client):
    # send_message_op self-lands: it has no open or nest seam (ADR-0005 as
    # amended). chat_api no longer does, since seam:executes now navigates it
    # into chat_bpmn. Its rows span the three layers: persist_user_msg
    # (process) invokes it, chat_api (architecture) exposes it, and it is
    # governedBy user_send_policy, which sits in no model ("other").
    html = _fragment(client, SEND_MESSAGE_OP)
    assert '<span class="seam-dot" data-layer="process"' in html
    assert '<span class="seam-dot" data-layer="architecture"' in html
    assert '<span class="seam-dot" data-layer="other"' in html
    # Incoming rows use the source's layer: chat_ui (a C4 container,
    # architecture layer) presents chat_ifml.
    incoming = _fragment(client, f"{CHAT}chat_ifml")
    assert '<span class="seam-dot" data-layer="architecture"' in incoming


def test_seam_dot_layers_are_known_values(client):
    import re

    html = _fragment(client, SEND_MESSAGE_OP)
    layers = re.findall(r'class="seam-dot" data-layer="([^"]*)"', html)
    assert layers
    assert set(layers) <= set(LAYERS)


def test_bpmn_fragment_disables_zoom_scroll(client):
    html = _fragment(client, CHAT_BPMN)
    assert "zoomScroll: { enabled: false }" in html
    assert '<aside class="inspector">' in html


def test_no_renderer_view_still_uses_layout(client):
    # An untyped/unknown element renders the no-renderer branch inside the
    # canvas column without breaking the layout.
    html = _fragment(client, "https://w3id.org/seams/seam#UIFragment")
    assert 'class="view-layout"' in html
    assert '<aside class="inspector">' in html
    assert "No renderer yet" in html or "network" in html or "payload-canvas" in html
