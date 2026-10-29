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
        ("status", "text"),  # sh:datatype xsd:string (GAP-14)
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
    assert act["state"] == f"{CHAT}s_complete"
    assert act["text"] == "[state in (complete, composing, sending, streaming)]"
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


# --- HTML: the IFML notation on a diagram-js canvas (M007/S04, D023) -------


def _fragment(client, iri):
    resp = client.get(f"/view/{quote(iri, safe='')}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    return resp.text


@pytest.fixture(scope="module")
def ifml_html():
    return _fragment(TestClient(viewer_app.app), CHAT_IFML)


@pytest.fixture(scope="module")
def ifml_page():
    resp = TestClient(viewer_app.app).get(f"/view/{quote(CHAT_IFML, safe='')}")
    assert resp.status_code == 200
    return resp.text


def _canvas_json(html):
    """The ifml_elk_graph() payload embedded as seamsRenderIfml's second argument."""
    import json

    call = "window.seamsRenderIfml(container, "
    assert call in html, "seamsRenderIfml call with embedded canvas JSON missing"
    data, _ = json.JSONDecoder().raw_decode(html, html.index(call) + len(call))
    return data


def test_fragment_mounts_ifml_canvas(ifml_html):
    assert 'id="ifml-canvas"' in ifml_html
    assert 'data-notation="ifml"' in ifml_html
    assert 'aria-label="IFML: ' in ifml_html
    for zoom in ("in", "out", "fit"):
        assert f'data-zoom="{zoom}"' in ifml_html
    assert "window.seamsIfmlReady.then(" in ifml_html
    assert "window.seamsRenderIfml(" in ifml_html


def test_fragment_drops_server_svg_and_vis(ifml_html):
    assert 'class="ifml-diagram"' not in ifml_html
    assert "<svg" not in ifml_html
    assert "new vis.Network" not in ifml_html


def test_fragment_embeds_the_elk_graph(ifml_html):
    assert _canvas_json(ifml_html) == ifml.ifml_elk_graph(ifml.ifml_diagram(CHAT_IFML))


@pytest.mark.parametrize(
    "text",
    [
        "«Form»",
        "«List»",
        "«Details»",
        "«SimpleField» content",
        "«SimpleField» role",
        "«SimpleField» status",
        "«SimpleField» timestamp",
        "«DataBinding» Message",
        "«DataBinding» Conversation",
        "[L] Chat Page",
        "[state in (complete, composing, sending, streaming)]",
        "«ParamBindingGroup» selected conversation → conversation",
        "Send Message Process",
    ],
)
def test_canvas_json_carries_ifml_text(ifml_html, text):
    # The former visible SVG text now travels in the embedded canvas JSON.
    import json

    assert text in json.dumps(_canvas_json(ifml_html)["elements"], ensure_ascii=False)


def test_canvas_json_kinds_and_layers(ifml_html):
    elements = _canvas_json(ifml_html)["elements"]
    assert {e["kind"] for e in elements.values()} == {"container", "component", "event", "action", "note", "flow"}
    assert {e["layer"] for e in elements.values()} <= {
        "architecture", "interaction", "process", "decision", "data", "lifecycle", "other"
    }
    assert elements[CHAT_PAGE]["kind"] == "container"
    assert elements[SEND_PROCESS]["kind"] == "action" and elements[SEND_PROCESS]["layer"] == "process"
    assert len(elements[SEND_PROCESS]["points"]) == 6
    assert {elements[e]["eventKind"] for e in (SEND_MESSAGE, SELECT_CONVERSATION)} == {"user"}


def test_full_page_ships_diagram_js_renderer(ifml_page):
    assert "https://esm.sh/diagram-js@15" in ifml_page
    assert "https://esm.sh/tiny-svg@3" in ifml_page
    assert "window.seamsRenderIfml =" in ifml_page
    assert "window.seamsIfmlReady = " in ifml_page
    assert 'id="ifml-canvas"' in ifml_page
    assert ".ifml-action {" in ifml_page  # IFML CSS lives in page.html
    assert ".ifml-controls {" in ifml_page
    # Drawing order is pinned by the renderer: dashed data flows, 22px binding rows.
    assert '"stroke-dasharray"] = "6 4"' in ifml_page
    assert "44 + i * 22" in ifml_page


def test_no_scroll_zoom_anywhere(ifml_page, ifml_html):
    # Pan by drag and zoom by buttons only: page scroll is never trapped.
    for html in (ifml_page, ifml_html):
        assert "zoomscroll" not in html.lower()
        assert '"wheel"' not in html


def test_renderer_lives_only_in_the_shell(ifml_html):
    for shell_only in ("https://esm.sh/diagram-js@15", "window.seamsRenderIfml =", ".ifml-action {", "zoomscroll"):
        assert shell_only not in ifml_html


def test_non_ifml_model_has_no_ifml_canvas(client):
    html = _fragment(client, f"{CHAT}chat_architecture")
    assert 'id="ifml-canvas"' not in html
    assert "window.seamsRenderIfml(" not in html


# --- ELK port graph (M007/S04, D023) --------------------------------------


@pytest.fixture(scope="module")
def elk_graph(diagram):
    return ifml.ifml_elk_graph(diagram)


def _abs_nodes(node, ox=0, oy=0, out=None, ports=None):
    """Walk the ELK tree adding parent offsets: (absolute boxes, absolute port boxes)."""
    out = {} if out is None else out
    ports = {} if ports is None else ports
    for child in node.get("children", []):
        x, y = ox + child["x"], oy + child["y"]
        out[child["id"]] = (x, y, child["width"], child["height"])
        for p in child.get("ports", []):
            ports[p["id"]] = (child["id"], x + p["x"], y + p["y"], p["width"], p["height"])
        _abs_nodes(child, x, y, out, ports)
    return out, ports


def _find_node(node, iri):
    for child in node.get("children", []):
        if child["id"] == iri:
            return child
        found = _find_node(child, iri)
        if found:
            return found
    return None


def test_elk_graph_deterministic(diagram, elk_graph):
    assert ifml.ifml_elk_graph(ifml.ifml_diagram(CHAT_IFML)) == ifml.ifml_elk_graph(diagram) == elk_graph


def test_elk_root_is_fixed_and_sized(diagram, elk_graph):
    root = elk_graph["elk"]
    assert root["id"] == "root" and (root["x"], root["y"]) == (0, 0)
    assert (root["width"], root["height"]) == (diagram["width"], diagram["height"])
    assert root["layoutOptions"]["elk.algorithm"] == "fixed"
    assert root["layoutOptions"]["elk.nodeSize.fixedGraphSize"] is True
    assert [c["id"] for c in root["children"]] == sorted(c["id"] for c in root["children"])
    assert [e["id"] for e in root["edges"]] == sorted(e["id"] for e in root["edges"])


@pytest.mark.parametrize("event,owner", [(SEND_MESSAGE, COMPOSE), (SELECT_CONVERSATION, CONVERSATIONS)])
def test_user_events_are_east_ports_on_owner(elk_graph, event, owner):
    node = _find_node(elk_graph["elk"], owner)
    assert node["layoutOptions"]["elk.portConstraints"] == "FIXED_POS"
    (port,) = [p for p in node["ports"] if p["id"] == event]
    assert port["layoutOptions"] == {"elk.port.side": "EAST"}
    # The port box straddles the owner's right border.
    assert port["x"] + port["width"] // 2 == node["width"]
    assert elk_graph["elements"][event]["kind"] == "event"
    assert elk_graph["elements"][event]["eventKind"] == "user"
    assert elk_graph["elements"][event]["owner"] == owner


def test_compound_nodes_nest_components_under_container(elk_graph):
    page = _find_node(elk_graph["elk"], CHAT_PAGE)
    assert [c["id"] for c in page["children"]] == sorted([COMPOSE, CONVERSATIONS, THREAD])
    for n in [page] + page["children"]:
        assert n["layoutOptions"]["elk.algorithm"] == "fixed"
        assert n["layoutOptions"]["elk.padding"] == "[top=0,left=0,bottom=0,right=0]"
        assert n["layoutOptions"]["elk.nodeSize.fixedGraphSize"] is True


def test_action_flow_bottom_run_stays_inside_container(diagram):
    (page,) = [c for c in diagram["containers"] if c["iri"] == CHAT_PAGE]
    assert (page["x"], page["y"], page["w"], page["h"]) == (20, 20, 820, 312)
    lowest = max(c["y"] + c["h"] for c in diagram["components"])
    flow = max((f for f in diagram["flows"] if f.get("points")), key=lambda f: max(y for _, y in f["points"]))
    pts = flow["points"]
    runs = [a[1] for a, b in zip(pts, pts[1:]) if a[1] == b[1] and a[1] > lowest]
    assert runs, flow
    for y in runs:
        assert y < page["y"] + page["h"]


def test_elk_round_trip_reproduces_python_geometry(diagram, elk_graph):
    nodes, ports = _abs_nodes(elk_graph["elk"])
    for key in ("containers", "components", "actions"):
        for el in diagram[key]:
            assert nodes[el["iri"]] == (el["x"], el["y"], el["w"], el["h"]), el["iri"]
    for n in diagram["notes"]:
        assert nodes[f"note::{n['kind']}::{n['for']}"] == (n["x"], n["y"], n["w"], n["h"])
    assert diagram["events"]
    for e in diagram["events"]:
        owner, px, py, pw, ph = ports[e["iri"]]
        assert owner == e["owner"]
        assert (px + pw // 2, py + ph // 2) == (e["cx"], e["cy"])
        assert (pw, ph) == (2 * e["r"], 2 * e["r"])


def test_elk_edge_sections_follow_python_points(diagram, elk_graph):
    edges = {e["id"]: e for e in elk_graph["elk"]["edges"]}
    assert len(edges) == len(diagram["flows"])
    for f in diagram["flows"]:
        fid = f["iri"] or f"flow::action::{f['from']}::{f['to']}"
        (sec,) = edges[fid]["sections"]
        assert sec["id"] == f"{fid}::s0"
        pts = [sec["startPoint"]] + sec["bendPoints"] + [sec["endPoint"]]
        assert [[p["x"], p["y"]] for p in pts] == f["points"]
        assert edges[fid]["sources"] == [f["from"]] and edges[fid]["targets"] == [f["to"]]
        assert elk_graph["elements"][fid]["points"] == f["points"]


def test_action_flow_runs_from_send_message_port(elk_graph):
    fid = f"flow::action::{SEND_MESSAGE}::{SEND_PROCESS}"
    (edge,) = [e for e in elk_graph["elk"]["edges"] if e["id"] == fid]
    assert edge["sources"] == [SEND_MESSAGE] and edge["targets"] == [SEND_PROCESS]
    el = elk_graph["elements"][fid]
    assert el["kind"] == "flow" and el["flowKind"] == "action" and el["iri"] == SEND_PROCESS


def test_elements_cover_exactly_nodes_ports_and_edges(elk_graph):
    nodes, ports = _abs_nodes(elk_graph["elk"])
    ids = set(nodes) | set(ports) | {e["id"] for e in elk_graph["elk"]["edges"]}
    assert set(elk_graph["elements"]) == ids
    assert {e["kind"] for e in elk_graph["elements"].values()} == {
        "container", "component", "event", "action", "flow", "note"
    }
    for el in elk_graph["elements"].values():
        assert all(k in el for k in ("kind", "iri", "label", "layer", "seams"))


def test_elements_carry_draw_data(diagram, elk_graph):
    els = elk_graph["elements"]
    assert els[CHAT_PAGE]["title"] == "[L] Chat Page" and els[CHAT_PAGE]["markers"] == ["[L]"]
    assert els[COMPOSE]["stereotype"] == "«Form»"
    assert els[COMPOSE]["fields"] == by_iri(diagram["components"])[COMPOSE]["fields"]
    (action,) = diagram["actions"]
    assert els[SEND_PROCESS]["points"][0] == [action["points"][0][0] - action["x"], action["points"][0][1] - action["y"]]
    assert all(0 <= x <= action["w"] and 0 <= y <= action["h"] for x, y in els[SEND_PROCESS]["points"])
    notes = [e for e in els.values() if e["kind"] == "note"]
    assert {n["noteKind"] for n in notes} == {"activation", "bindings"}
    assert all(n["text"] == n["label"] and n["seams"] == [] for n in notes)


def test_activation_note_layer_matches_template_rule(diagram, elk_graph):
    owners = by_iri(diagram["components"] + diagram["containers"])
    for n in diagram["notes"]:
        el = elk_graph["elements"][f"note::{n['kind']}::{n['for']}"]
        if n["kind"] == "bindings":
            assert el["layer"] == "interaction"
            continue
        seam = next((s for s in owners[n["for"]]["seams"] if s["target"] == n["state"]), None)
        assert el["layer"] == (seam["targetLayer"] if seam else "lifecycle")
        assert el["connector"] == n["connector"]


def test_elk_coordinates_are_ints(elk_graph):
    def walk(obj, path="elk"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("x", "y", "width", "height", "r"):
                    yield path + "." + k, v
                elif k in ("points", "connector"):
                    for pt in v:
                        yield from ((path + "." + k, n) for n in pt)
                else:
                    yield from walk(v, path + "." + k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from walk(v, f"{path}[{i}]")

    numbers = list(walk(elk_graph))
    assert numbers
    assert [(p, v) for p, v in numbers if type(v) is not int] == []


def test_non_ifml_model_yields_empty_elk_root():
    g = ifml.ifml_elk_graph(ifml.ifml_diagram(f"{CHAT}chat_architecture"))
    assert g["elk"]["children"] == [] and g["elk"]["edges"] == []
    assert g["elements"] == {}


def test_undrawn_owner_event_and_pointless_flow_are_skipped(diagram):
    # Boundary: an event owned by an action (cx = cy = 0) gets no port, and a
    # flow without points (or touching it) gets no edge.
    d = {**diagram, "events": diagram["events"] + [
        {"iri": "urn:sys", "label": "sys", "layer": "interaction", "seams": [], "owner": SEND_PROCESS,
         "kind": "system", "cx": 0, "cy": 0, "r": 8}
    ], "flows": diagram["flows"] + [
        {"iri": "urn:f1", "label": "f1", "layer": "interaction", "seams": [], "kind": "navigation",
         "from": "urn:sys", "to": COMPOSE, "bindings": [], "points": [[0, 0], [5, 5]]},
        {"iri": "urn:f2", "label": "f2", "layer": "interaction", "seams": [], "kind": "navigation",
         "from": SEND_MESSAGE, "to": THREAD, "bindings": [], "points": []},
    ]}
    g = ifml.ifml_elk_graph(d)
    assert "urn:sys" not in g["elements"] and "urn:f1" not in g["elements"] and "urn:f2" not in g["elements"]
    _, ports = _abs_nodes(g["elk"])
    assert "urn:sys" not in ports


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_view_json_ifml_unchanged_by_elk_graph(client):
    resp = client.get(f"/view/{quote(CHAT_IFML, safe='')}?format=json")
    assert resp.status_code == 200
    body = resp.json()
    keys = set(_all_keys(body["ifml"]))
    assert "elk" not in keys and "elements" not in keys
    assert "ifml_canvas" not in body
    assert set(body["ifml"]) == {
        "model", "label", "layer", "width", "height",
        "containers", "components", "events", "actions", "flows", "notes",
    }
