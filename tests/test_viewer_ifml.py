"""Tests for the IFML diagram projection in viewer/ifml.py (M006/S05, D011):
the IFML derivations read from the chat graph, the deterministic geometry
invariants, and the additive "ifml" field on the /view JSON contract (MEM016).
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
from viewer import ifml  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_IFML = f"{CHAT}chat_ifml"
CHAT_PAGE = f"{CHAT}chat_page"
CONVERSATIONS = f"{CHAT}conversation_list"
THREAD = f"{CHAT}message_thread"
COMPOSE = f"{CHAT}compose_form"
SEND_MESSAGE = f"{CHAT}send_message"
SELECT_CONVERSATION = f"{CHAT}select_conversation"
SEND_PROCESS = f"{CHAT}send_message_process"


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


@pytest.fixture(scope="module")
def diagram():
    return ifml.ifml_diagram(CHAT_IFML)


def by_iri(items):
    return {i["iri"]: i for i in items}


def test_chat_page_is_landmark_container(diagram):
    (page,) = diagram["containers"]
    assert page["iri"] == CHAT_PAGE
    assert page["markers"] == ["[L]"]
    assert page["title"] == "[L] Chat Page"
    assert page["parent"] is None
    assert sorted(page["children"]) == sorted([CONVERSATIONS, THREAD, COMPOSE])


def test_components_carry_stereotypes_and_parent(diagram):
    comps = by_iri(diagram["components"])
    assert {i: c["stereotype"] for i, c in comps.items()} == {
        CONVERSATIONS: "«List»",
        THREAD: "«Details»",
        COMPOSE: "«Form»",
    }
    assert {c["label"] for c in comps.values()} == {"Conversations", "Message Thread", "Compose Message"}
    assert all(c["parent"] == CHAT_PAGE for c in comps.values())


def test_data_binding_strips(diagram):
    comps = by_iri(diagram["components"])
    assert comps[COMPOSE]["bindings"] == [
        {"shape": f"{CHAT}MessageShape", "label": "«DataBinding» Message", "predicate": "seam:writes"}
    ]
    assert comps[THREAD]["bindings"] == [
        {"shape": f"{CHAT}MessageShape", "label": "«DataBinding» Message", "predicate": "seam:reads"}
    ]
    assert comps[CONVERSATIONS]["bindings"][0]["predicate"] == "seam:reads"
    assert comps[CONVERSATIONS]["bindings"][0]["shape"] == f"{CHAT}ConversationShape"


def test_form_fields_come_only_from_message_shape(diagram):
    comps = by_iri(diagram["components"])
    fields = comps[COMPOSE]["fields"]
    assert [(f["name"], f["kind"]) for f in fields] == [
        ("content", "text"),
        ("role", "text"),
        ("status", "field"),
        ("timestamp", "datetime"),
    ]
    assert [f["label"] for f in fields] == [f"«SimpleField» {n}" for n in ("content", "role", "status", "timestamp")]
    assert [f["path"] for f in fields] == [viewer_app.qname(f"{CHAT}{n}") for n in ("content", "role", "status", "timestamp")]
    # Only forms get fields.
    assert comps[THREAD]["fields"] == [] and comps[CONVERSATIONS]["fields"] == []


def test_events_attached_to_owners_and_all_user(diagram):
    events = by_iri(diagram["events"])
    assert set(events) == {SEND_MESSAGE, SELECT_CONVERSATION}
    assert events[SEND_MESSAGE]["owner"] == COMPOSE
    assert events[SELECT_CONVERSATION]["owner"] == CONVERSATIONS
    assert {e["kind"] for e in events.values()} == {"user"}
    comps = by_iri(diagram["components"])
    assert comps[COMPOSE]["events"] == [SEND_MESSAGE]
    assert comps[THREAD]["events"] == []


def test_send_message_action_hexagon(diagram):
    (action,) = diagram["actions"]
    assert action["iri"] == SEND_PROCESS
    assert action["label"] == "Send Message Process"
    assert action["layer"] == "process"
    assert any(s["predicate"] == "seam:detailedBy" for s in action["seams"])
    assert len(action["points"]) == 6
    (flow,) = [f for f in diagram["flows"] if f["kind"] == "action"]
    assert (flow["from"], flow["to"]) == (SEND_MESSAGE, SEND_PROCESS)


def test_navigation_and_data_flows(diagram):
    flows = {f["iri"]: f for f in diagram["flows"] if f["iri"]}
    nav = flows[f"{CHAT}select_to_thread"]
    assert (nav["kind"], nav["from"], nav["to"]) == ("navigation", SELECT_CONVERSATION, THREAD)
    data = flows[f"{CHAT}list_to_thread"]
    assert (data["kind"], data["from"], data["to"]) == ("data", CONVERSATIONS, THREAD)
    assert data["bindings"] == ["selected conversation → conversation"]


def test_notes(diagram):
    notes = {n["kind"]: n for n in diagram["notes"]}
    act = notes["activation"]
    assert act["for"] == THREAD
    assert act["state"] == f"{CHAT}s_composing"
    assert act["text"] == "[state = composing]"
    assert notes["bindings"]["text"] == "«ParamBindingGroup» selected conversation → conversation"


def test_every_element_carries_card_fields(diagram):
    for key in ("containers", "components", "events", "actions"):
        for el in diagram[key]:
            assert {"iri", "label", "layer", "seams"} <= set(el), (key, el["iri"])
    by = by_iri(diagram["components"] + diagram["events"])
    assert by[THREAD]["layer"] == "interaction"
    assert [s["target"] for s in by[SEND_MESSAGE]["seams"] if s["predicate"] == "seam:triggers"] == [SEND_PROCESS]


# --- geometry -------------------------------------------------------------


def test_deterministic(diagram):
    assert ifml.ifml_diagram(CHAT_IFML) == ifml.ifml_diagram(CHAT_IFML) == diagram


def _walk_numbers(obj, path="root"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("x", "y", "w", "h", "cx", "cy", "r", "width", "height"):
                yield f"{path}.{k}", v
            elif k in ("points", "connector"):
                for i, pt in enumerate(v):
                    for j, n in enumerate(pt):
                        yield f"{path}.{k}[{i}][{j}]", n
            else:
                yield from _walk_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]")


def test_all_coordinates_are_ints(diagram):
    numbers = list(_walk_numbers(diagram))
    assert numbers
    bad = [(p, v) for p, v in numbers if type(v) is not int]
    assert bad == []


def test_boxes_present_on_every_drawn_element(diagram):
    for key in ("containers", "components", "events", "actions", "notes"):
        for el in diagram[key]:
            assert all(k in el for k in ("x", "y", "w", "h")), (key, el["iri"])
            assert el["w"] > 0 and el["h"] > 0


def _inside(inner, outer):
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
    )


def test_components_inside_container_and_ordered(diagram):
    (page,) = diagram["containers"]
    comps = by_iri(diagram["components"])
    for c in comps.values():
        assert _inside(c, page), c["iri"]
    # Flow sources come before their targets: the list is left of the thread.
    assert comps[CONVERSATIONS]["x"] + comps[CONVERSATIONS]["w"] <= comps[THREAD]["x"]
    # Left-to-right, no overlap.
    xs = sorted((c["x"], c["x"] + c["w"]) for c in comps.values())
    assert all(a[1] <= b[0] for a, b in zip(xs, xs[1:]))


def test_form_grows_with_field_rows(diagram):
    comps = by_iri(diagram["components"])
    assert comps[COMPOSE]["h"] > comps[THREAD]["h"]


def test_event_centres_on_owner_right_border(diagram):
    comps = by_iri(diagram["components"])
    for e in diagram["events"]:
        owner = comps[e["owner"]]
        assert e["cx"] == owner["x"] + owner["w"]
        assert owner["y"] <= e["cy"] <= owner["y"] + owner["h"]


def test_action_outside_container_aligned_with_event(diagram):
    (page,) = diagram["containers"]
    (action,) = diagram["actions"]
    assert action["x"] >= page["x"] + page["w"]
    send = by_iri(diagram["events"])[SEND_MESSAGE]
    assert action["y"] + action["h"] // 2 == send["cy"]
    assert diagram["width"] >= action["x"] + action["w"]
    assert diagram["height"] >= page["y"] + page["h"]


def test_flow_endpoints_on_borders(diagram):
    events = by_iri(diagram["events"])
    boxes = by_iri(diagram["components"] + diagram["actions"])
    for f in diagram["flows"]:
        start, end = f["points"][0], f["points"][-1]
        if f["from"] in events:
            e = events[f["from"]]
            assert start == [e["cx"] + e["r"], e["cy"]]
        else:
            src = boxes[f["from"]]
            assert start[0] == src["x"] + src["w"]
        tgt = boxes[f["to"]]
        on_left = end[0] == tgt["x"] and tgt["y"] <= end[1] <= tgt["y"] + tgt["h"]
        on_bottom = end[1] == tgt["y"] + tgt["h"] and tgt["x"] <= end[0] <= tgt["x"] + tgt["w"]
        assert on_left or on_bottom, f


def test_notes_sit_above_their_element_without_overlap(diagram):
    comps = by_iri(diagram["components"])
    notes = diagram["notes"]
    for n in notes:
        if n["kind"] == "activation":
            assert n["y"] + n["h"] <= comps[n["for"]]["y"]
    a, b = notes
    disjoint_x = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
    disjoint_y = a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
    assert disjoint_x or disjoint_y


def test_non_ifml_model_yields_empty_diagram():
    # A model with no IFML members derives nothing rather than raising.
    d = ifml.ifml_diagram(f"{CHAT}chat_architecture")
    assert d["containers"] == d["components"] == d["events"] == d["actions"] == []
    assert d["width"] > 0 and d["height"] > 0


def test_unknown_iri_yields_empty_diagram():
    d = ifml.ifml_diagram(f"{CHAT}no_such_model")
    assert d["flows"] == d["notes"] == []


# --- /view JSON contract --------------------------------------------------


def test_view_json_carries_ifml_for_ifml_model(client):
    resp = client.get(f"/view/{quote(CHAT_IFML, safe='')}?format=json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["notation"] == "ifml"
    assert [c["iri"] for c in body["ifml"]["containers"]] == [CHAT_PAGE]
    assert body["ifml"]["actions"][0]["iri"] == SEND_PROCESS


def test_view_json_ifml_is_null_for_other_notations(client):
    resp = client.get(f"/view/{quote(f'{CHAT}chat_architecture', safe='')}?format=json")
    assert resp.status_code == 200
    body = resp.json()
    assert "ifml" in body and body["ifml"] is None
