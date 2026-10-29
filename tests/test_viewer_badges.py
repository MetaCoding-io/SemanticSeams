"""Tests for the BPMN/DMN layer tint and seam overlay badges (M007/S01):
viewer/app.py's payload_element_seams() (native id -> outgoing seams, self
targets dropped) and the fragment/shell markup that draws them.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_BPMN = f"{CHAT}chat_bpmn"
ROUTING_DMN = f"{CHAT}routing_dmn"
BPMN_FILE = viewer_app.DATA_DIR / "chat_process.bpmn"
DMN_FILE = viewer_app.DATA_DIR / "routing.dmn"
SEAM_KEYS = {"predicate", "predicateLabel", "target", "targetLabel", "targetLayer", "reveal"}


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def xml_ids(path: Path) -> set[str]:
    return {i for el in ET.parse(path).iter() if (i := el.get("id"))}


def view_path(iri: str) -> str:
    return f"/view/{quote(iri, safe='')}"


def test_bpmn_element_seams_keys_are_native_ids():
    seams = viewer_app.payload_element_seams(CHAT_BPMN)
    assert seams
    assert set(seams) <= xml_ids(BPMN_FILE)


def test_route_to_provider_has_decision_and_data_badges():
    seams = viewer_app.payload_element_seams(CHAT_BPMN)["route_to_provider"]
    assert any(
        s["targetLayer"] == "decision" and s["target"] == f"{CHAT}routing_decision" for s in seams
    )
    assert any(s["targetLayer"] == "data" and s["target"] == f"{CHAT}MessageShape" for s in seams)


def test_self_targets_dropped_and_empty_ids_omitted():
    seams = viewer_app.payload_element_seams(CHAT_BPMN)
    assert all(s["target"] != CHAT_BPMN for lst in seams.values() for s in lst)
    # send_message_process's only seam is detailedBy chat_bpmn (the current view).
    assert "send_message_process" not in seams
    assert all(seams.values())


def test_every_seam_entry_has_the_six_keys():
    for lst in viewer_app.payload_element_seams(CHAT_BPMN).values():
        for s in lst:
            assert set(s) == SEAM_KEYS


def test_bpmn_fragment_draws_tint_and_badges(client):
    resp = client.get(view_path(CHAT_BPMN), headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    for needle in ("elementSeams", "seamsDecorateDiagram(viewer", 'data-layer="process"'):
        assert needle in html, needle
    # MEM009: the badge CSS and the shared helper live in the shell, not the
    # swapped fragment.
    assert '.seam-badge[data-layer=' not in html
    assert "window.seamsDecorateDiagram = function" not in html


def test_full_page_carries_badge_and_tint_css(client):
    resp = client.get(view_path(CHAT_BPMN))
    assert resp.status_code == 200
    style = resp.text.split("<style>", 1)[1].split("</style>", 1)[0]
    assert '.seam-badge[data-layer="decision"]' in style
    assert "var(--layer-process)" in style
    assert '.payload-canvas[data-layer="process"]' in style
    assert '.payload-canvas[data-layer="decision"]' in style


def test_json_contract_has_no_element_seams(client):
    resp = client.get(f"{view_path(CHAT_BPMN)}?format=json")
    assert resp.status_code == 200
    assert "elementSeams" not in resp.json()
    assert "element_seams" not in resp.json()


def test_shell_helper_draws_tint_and_badges(client):
    resp = client.get(view_path(CHAT_BPMN))
    assert resp.status_code == 200
    html = resp.text
    helper = html.split("window.seamsDecorateDiagram = function", 1)[1].split("};", 1)[0]
    for needle in ("seams-tinted", "seams-member", 'get("overlays")', "seam-badge", "seamsNavigate"):
        assert needle in helper, needle
    assert "seam badge overlay failed:" in helper
    # Badge labels go through textContent/title, never innerHTML.
    assert "innerHTML" not in helper
    # Idempotent: re-running after a dmn-js view switch replaces old badges.
    assert 'overlays.remove({ type: "seam-badges" })' in helper


def test_dmn_element_seams_keys_are_native_ids():
    seams = viewer_app.payload_element_seams(ROUTING_DMN)
    assert seams
    assert set(seams) <= xml_ids(DMN_FILE)


def test_routing_decision_has_data_badge_and_no_self_target():
    seams = viewer_app.payload_element_seams(ROUTING_DMN)["routing_decision"]
    assert any(s["targetLayer"] == "data" and s["target"] == f"{CHAT}chat_data_shapes" for s in seams)
    assert all(s["target"] != ROUTING_DMN for s in seams)


def test_dmn_fragment_wires_tint_and_badges(client):
    resp = client.get(view_path(ROUTING_DMN), headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    for needle in ("elementSeams", 'data-layer="decision"', "seamsDecorateDiagram(activeViewer"):
        assert needle in html, needle
    assert '.seam-badge[data-layer=' not in html
    assert "window.seamsDecorateDiagram = function" not in html


def test_dmn_full_page_carries_decision_css(client):
    resp = client.get(view_path(ROUTING_DMN))
    assert resp.status_code == 200
    style = resp.text.split("<style>", 1)[1].split("</style>", 1)[0]
    assert '.seam-badge[data-layer="data"]' in style
    assert "var(--layer-decision)" in style
    assert '.payload-canvas[data-layer="decision"] .decision-table-name' in style
    assert "window.seamsDecorateDiagram = function" in resp.text
