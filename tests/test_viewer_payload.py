"""Tests for viewer/app.py's native-payload serving (GET /payload/{iri},
resolve_payload_path) and payload_element_map(), the id -> IRI map that the
bpmn-js/dmn-js element.click handlers in fragment.html use to turn a click on
a native diagram element into seam navigation.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_BPMN = f"{CHAT}chat_bpmn"
ROUTING_DMN = f"{CHAT}routing_dmn"
BPMN_FILE = viewer_app.MODEL_DIR / "chat_process.bpmn"
DMN_FILE = viewer_app.MODEL_DIR / "routing.dmn"


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def payload_url(path: Path) -> str:
    return f"/payload/{quote(path.resolve().as_uri(), safe='')}"


def xml_ids(path: Path) -> set[str]:
    return {i for el in ET.parse(path).iter() if (i := el.get("id"))}


@pytest.mark.parametrize(
    "path, media_type",
    [(BPMN_FILE, "application/bpmn+xml"), (DMN_FILE, "application/dmn+xml")],
)
def test_payload_serves_native_xml_with_media_type(client, path, media_type):
    resp = client.get(payload_url(path))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(media_type)
    assert resp.content == path.read_bytes()


def test_view_payload_url_round_trips_through_payload_route(client):
    """The payload_url the fragment fetches must be servable as-is."""
    for model in (CHAT_BPMN, ROUTING_DMN):
        resp = client.get(f"/view/{quote(model, safe='')}", headers={"hx-request": "true"})
        assert resp.status_code == 200
        start = resp.text.index('fetch("') + len('fetch("')
        url = resp.text[start:resp.text.index('"', start)]
        assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "payload_iri",
    [
        "https://example.org/chat/routing.dmn",  # not a file:// IRI
        (viewer_app.MODEL_DIR.parent.parent / "README.md").resolve().as_uri(),  # outside MODEL_DIR
        (viewer_app.MODEL_DIR / ".." / ".." / "README.md").as_uri(),  # traversal
        (viewer_app.MODEL_DIR / "missing.bpmn").resolve().as_uri(),  # absent
    ],
)
def test_payload_rejects_unresolvable_iris(client, payload_iri):
    with pytest.raises(HTTPException) as exc:
        viewer_app.resolve_payload_path(payload_iri)
    assert exc.value.status_code == 404
    assert client.get(f"/payload/{quote(payload_iri, safe='')}").status_code == 404


def test_bpmn_element_map_covers_lifted_elements():
    element_map = viewer_app.payload_element_map(CHAT_BPMN)
    assert element_map["route_to_provider"] == f"{CHAT_BPMN}#route_to_provider"
    assert element_map["send_message_process"] == f"{CHAT}send_message_process"
    assert len(element_map) == 6


def test_dmn_element_map_covers_decision():
    assert viewer_app.payload_element_map(ROUTING_DMN) == {
        "routing_decision": f"{CHAT}routing_decision"
    }


@pytest.mark.parametrize("model, path", [(CHAT_BPMN, BPMN_FILE), (ROUTING_DMN, DMN_FILE)])
def test_element_map_keys_exist_in_native_payload(model, path):
    """A key missing from the XML is a seam element no click can ever reach."""
    assert set(viewer_app.payload_element_map(model)) <= xml_ids(path)
