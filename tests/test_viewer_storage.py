"""The "stored in" seam edge in the viewer inspector (M011/S02, ADR-0011).

The chat app states MessageShape seam:storedIn :message_db. seam_edges() must
carry that edge both ways with the ontology's rdfs:label "stored in" (D006),
and since storedIn is a layer predicate it must not navigate.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer.app import seam_edges  # noqa: E402

CHAT = "https://example.org/chat/"
MESSAGE_SHAPE = f"{CHAT}MessageShape"
CONVERSATION_SHAPE = f"{CHAT}ConversationShape"
MESSAGE_DB = f"{CHAT}message_db"


def _stored_in(edges: list[dict]) -> list[dict]:
    return [e for e in edges if e["predicate"] == "seam:storedIn"]


def test_message_shape_has_stored_in_edge_to_message_db():
    edges = _stored_in(seam_edges(MESSAGE_SHAPE)["outgoing"])
    assert len(edges) == 1
    edge = edges[0]
    assert edge["target"] == MESSAGE_DB
    assert edge["predicateLabel"] == "stored in"
    assert edge["targetLabel"] == "Message Store"
    assert edge["reveal"] == "layer"
    assert edge["navigational"] is False


def test_message_db_lists_both_stored_shapes_as_incoming():
    sources = {e["source"] for e in _stored_in(seam_edges(MESSAGE_DB)["incoming"])}
    assert sources == {MESSAGE_SHAPE, CONVERSATION_SHAPE}


def test_shape_without_stored_in_has_no_such_edge():
    """Boundary: a container is not a shape and states no storedIn of its own."""
    assert _stored_in(seam_edges(MESSAGE_DB)["outgoing"]) == []


def test_conversation_shape_view_json_shows_stored_in():
    """ConversationShape self-lands (MEM012); storedIn is layer, so adding it
    must not make the view navigate away."""
    client = TestClient(viewer_app.app)
    resp = client.get(f"/view/{CONVERSATION_SHAPE}", params={"format": "json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["@id"] == CONVERSATION_SHAPE
    edges = _stored_in(body["seamEdges"]["outgoing"])
    assert [(e["target"], e["predicateLabel"]) for e in edges] == [(MESSAGE_DB, "stored in")]
