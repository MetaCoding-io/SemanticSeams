"""Tests for viewer/app.py's ADR-0005 navigation resolution, including the
section 6 multi-detailedBy disambiguation behavior.

Exercises viewer.app.resolve_navigation() directly against the chat-app.trig
fixture (examples/chat-app/chat-app.trig), which T01 extended so that
routing_decision carries two seam:detailedBy targets (:routing_dmn and
:chat_data_shapes) specifically to exercise this scenario.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402

CHAT = "https://example.org/chat/"
ROUTING_DECISION = f"{CHAT}routing_decision"
ROUTING_DMN = f"{CHAT}routing_dmn"
CHAT_DATA_SHAPES = f"{CHAT}chat_data_shapes"
ROUTE_TO_PROVIDER = f"{CHAT}chat_bpmn#route_to_provider"
SEND_MESSAGE_PROCESS = f"{CHAT}send_message_process"
CHAT_BPMN = f"{CHAT}chat_bpmn"
MESSAGE_SHAPE = f"{CHAT}MessageShape"


def test_direct_multi_detailedby_returns_disambiguation_candidates():
    """Visiting routing_decision itself: 2 direct detailedBy targets means no
    auto-navigate — the caller must render routing_decision with both
    candidates instead of silently picking one (ADR-0005 section 6)."""
    nav = viewer_app.resolve_navigation(ROUTING_DECISION)
    assert nav["target"] is None
    assert nav["landing"] == ROUTING_DECISION
    assert nav["candidates"] is not None
    assert {c["iri"] for c in nav["candidates"]} == {ROUTING_DMN, CHAT_DATA_SHAPES}
    for c in nav["candidates"]:
        assert c["label"]
        assert c["notation"] in {"dmn", "shapegraph"}


def test_one_hop_multi_detailedby_returns_disambiguation_candidates():
    """Clicking the task with the decidedBy edge (one navigational hop away
    from routing_decision) must surface the same ambiguity at the hop, per
    ADR-0005 section 4+6 combined, rather than auto-picking the first hit."""
    nav = viewer_app.resolve_navigation(ROUTE_TO_PROVIDER)
    assert nav["target"] is None
    assert nav["landing"] == ROUTING_DECISION
    assert {c["iri"] for c in nav["candidates"]} == {ROUTING_DMN, CHAT_DATA_SHAPES}


def test_single_target_detailedby_still_auto_navigates():
    """Regression guard: single-target detailedBy must keep auto-navigating,
    unaffected by the new disambiguation branch."""
    nav = viewer_app.resolve_navigation(SEND_MESSAGE_PROCESS)
    assert nav["target"] == CHAT_BPMN
    assert nav["landing"] == CHAT_BPMN
    assert nav["candidates"] is None


def test_single_target_detailedby_on_non_hop_element_auto_navigates():
    """Direct (non-hop) single detailedBy target also still auto-navigates."""
    nav = viewer_app.resolve_navigation(MESSAGE_SHAPE)
    assert nav["target"] == CHAT_DATA_SHAPES
    assert nav["landing"] == CHAT_DATA_SHAPES
    assert nav["candidates"] is None


def test_view_endpoint_json_surfaces_candidates_without_navigating():
    """The /view/{iri} JSON response for a multi-detailedBy element must list
    candidates in detailedByCandidates and keep @id pinned to the requested
    (ambiguous) element rather than jumping to one target."""
    from fastapi.testclient import TestClient

    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == ROUTING_DECISION
    assert {c["iri"] for c in body["detailedByCandidates"]} == {ROUTING_DMN, CHAT_DATA_SHAPES}


def test_view_endpoint_json_single_target_auto_navigates():
    """A single-detailedBy element's /view/{iri} JSON response must still
    auto-navigate to the resolved target, with an empty candidates list."""
    from fastapi.testclient import TestClient

    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{SEND_MESSAGE_PROCESS}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == CHAT_BPMN
    assert body["detailedByCandidates"] == []


def test_view_endpoint_html_renders_disambiguation_popover():
    """T03: the HTML fragment for a multi-detailedBy element renders the
    ADR-0005 §6 disambiguation popover with one htmx-navigable option per
    candidate, each carrying the candidate's friendly label."""
    from fastapi.testclient import TestClient

    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    assert 'id="disambiguation"' in html
    assert 'data-candidate-count="2"' in html
    assert html.count('class="disambiguation-option"') == 2
    assert f'data-iri="{ROUTING_DMN}"' in html
    assert f'data-iri="{CHAT_DATA_SHAPES}"' in html
    assert "Provider Routing (DMN)" in html
    assert "Chat Data Model" in html
    # Options navigate through the existing htmx swap into #view-content.
    assert html.count('class="disambiguation-option" data-iri=') == 2
    assert 'hx-target="#view-content"' in html


def test_view_endpoint_html_single_target_has_no_popover():
    """Negative: a single-detailedBy element auto-navigates and its HTML must
    not contain the disambiguation popover at all."""
    from fastapi.testclient import TestClient

    client = TestClient(viewer_app.app)
    for iri in (SEND_MESSAGE_PROCESS, MESSAGE_SHAPE):
        resp = client.get(f"/view/{iri}", headers={"hx-request": "true"})
        assert resp.status_code == 200
        assert 'id="disambiguation"' not in resp.text
        assert "disambiguation-option" not in resp.text


def test_view_endpoint_full_page_renders_popover_for_multi_detailedby():
    """Non-htmx (full page) load of the ambiguous element also renders the
    popover, and the page ships the popover styles."""
    from fastapi.testclient import TestClient

    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{ROUTING_DECISION}")
    assert resp.status_code == 200
    assert 'id="disambiguation"' in resp.text
    assert ".disambiguation-option" in resp.text
