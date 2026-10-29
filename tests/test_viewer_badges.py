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
BPMN_FILE = viewer_app.DATA_DIR / "chat_process.bpmn"
SEAM_KEYS = {"predicate", "predicateLabel", "target", "targetLabel", "targetLayer"}


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


def test_every_seam_entry_has_the_five_keys():
    for lst in viewer_app.payload_element_seams(CHAT_BPMN).values():
        for s in lst:
            assert set(s) == SEAM_KEYS


def test_bpmn_fragment_draws_tint_and_badges(client):
    resp = client.get(view_path(CHAT_BPMN), headers={"hx-request": "true"})
    assert resp.status_code == 200
    html = resp.text
    for needle in ("elementSeams", "seam-badge", 'get("overlays")', "seams-tinted", 'data-layer="process"'):
        assert needle in html, needle
    assert "seam badge overlay failed:" in html
    # MEM009: the badge CSS lives in the shell, not the swapped fragment.
    assert '.seam-badge[data-layer=' not in html


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
