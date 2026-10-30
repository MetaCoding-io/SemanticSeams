"""Tests for the C4 legend and click-to-hide contraction (M006/S04, D010):
viewer/legend.py's pure parse_hide / legend_entries / contract_hidden, plus
their behaviour on the chat architecture through c4_graph_data().
"""

import html as html_lib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import legend  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
PROD = f"{CHAT}prod"
APP01 = f"{CHAT}app01"
CONVERSATION_SHAPE = f"{CHAT}ConversationShape"
HX = {"hx-request": "true"}
CONTAINERS = {f"{CHAT}{c}" for c in ("chat_ui", "chat_api", "llm_gateway", "message_db")}


def node(id, type="x:A", parent=None, layer="architecture"):
    return {"id": id, "type": type, "typeLabel": type.split(":")[1], "layer": layer, "parent": parent}


def edge(frm, to, label="uses", kind="x:uses"):
    return {"from": frm, "to": to, "label": label, "kind": kind}


def triples(edges):
    return [(e["from"], e["to"], e["label"]) for e in edges]


# --- parse_hide -------------------------------------------------------------


def test_parse_hide_sorts_and_dedupes_valid_tokens():
    assert legend.parse_hide("arch:Foo, hydra:Operation,arch:Foo") == (
        ["arch:Foo", "hydra:Operation"],
        [],
    )


def test_parse_hide_rejects_malformed_tokens():
    valid, rejected = legend.parse_hide("<script>,nocolon,arch:Ok,:x,1a:b,a:")
    assert valid == ["arch:Ok"]
    assert rejected == ["<script>", "nocolon", ":x", "1a:b", "a:"]


def test_parse_hide_empty():
    assert legend.parse_hide("") == ([], [])
    assert legend.parse_hide(" , ,") == ([], [])


# --- legend_entries ---------------------------------------------------------


def test_legend_counts_unfiltered_nodes_and_flags_hidden():
    nodes = [node("a", "x:B"), node("b", "x:A"), node("c", "x:A")]
    assert legend.legend_entries(nodes, ["x:A"]) == [
        {"type": "x:A", "label": "A", "layer": "architecture", "count": 2, "hidden": True},
        {"type": "x:B", "label": "B", "layer": "architecture", "count": 1, "hidden": False},
    ]


# --- contract_hidden ----------------------------------------------------------


def test_empty_hidden_set_returns_input_unchanged():
    nodes = [node("a"), node("b")]
    edges = [edge("a", "b")]
    assert legend.contract_hidden(nodes, edges, []) == (nodes, edges)
    # A hidden type no node has is also a no-op.
    assert legend.contract_hidden(nodes, edges, ["x:Nope"]) == (nodes, edges)


def test_chain_contraction():
    nodes = [node("a"), node("h", "x:H"), node("b")]
    out_nodes, out_edges = legend.contract_hidden(nodes, [edge("a", "h"), edge("h", "b")], ["x:H"])
    assert [n["id"] for n in out_nodes] == ["a", "b"]
    assert out_edges == [{"from": "a", "to": "b", "label": "uses", "kind": "contracted", "via": ["h"]}]


def test_multi_hop_chain_mixes_labels():
    nodes = [node("a"), node("h1", "x:H"), node("h2", "x:H"), node("b")]
    edges = [edge("a", "h1", "calls"), edge("h1", "h2", "uses"), edge("h2", "b", "calls")]
    _, out_edges = legend.contract_hidden(nodes, edges, ["x:H"])
    assert out_edges == [{"from": "a", "to": "b", "label": "calls / uses", "kind": "contracted", "via": ["h1", "h2"]}]


def test_hidden_node_without_visible_predecessor_drops_its_edges():
    nodes = [node("h", "x:H"), node("b")]
    assert legend.contract_hidden(nodes, [edge("h", "b")], ["x:H"]) == ([node("b")], [])


def test_collapse_into_visible_ancestor():
    nodes = [node("env"), node("h", "x:H", parent="env"), node("c")]
    out_nodes, out_edges = legend.contract_hidden(nodes, [edge("c", "h", "deployed to")], ["x:H"])
    assert [n["id"] for n in out_nodes] == ["c", "env"]
    assert out_edges == [{"from": "c", "to": "env", "label": "deployed to", "kind": "contracted", "via": ["h"]}]


def test_visible_children_reparent_to_nearest_visible_ancestor():
    nodes = [
        node("root"),
        node("mid", "x:H", parent="root"),
        node("leaf", parent="mid"),
        node("top", "x:H"),
        node("orphan", parent="top"),
    ]
    out_nodes, _ = legend.contract_hidden(nodes, [], ["x:H"])
    parents = {n["id"]: n["parent"] for n in out_nodes}
    assert parents == {"root": None, "leaf": "root", "orphan": None}
    # Sorted by (parent or "", id), as c4_graph_data sorts.
    assert [n["id"] for n in out_nodes] == ["orphan", "root", "leaf"]


def test_self_loops_and_ancestor_edges_are_dropped():
    nodes = [
        node("sys"),
        node("c", parent="sys"),
        node("h1", "x:H", parent="c"),
        node("h2", "x:H", parent="c"),
        node("h3", "x:H", parent="sys"),
    ]
    edges = [edge("h1", "h2"), edge("c", "h1"), edge("h3", "c")]
    _, out_edges = legend.contract_hidden(nodes, edges, ["x:H"])
    # h1->h2 collapses to c->c, c->h1 to c->c, h3->c to sys->c (ancestor edge).
    assert out_edges == []


def test_rerouted_edges_dedupe_and_merge_via():
    nodes = [node("a"), node("h1", "x:H"), node("h2", "x:H"), node("b")]
    edges = [edge("a", "h1"), edge("h1", "b"), edge("a", "h2"), edge("h2", "b"), edge("a", "b")]
    _, out_edges = legend.contract_hidden(nodes, edges, ["x:H"])
    # The direct a->b "uses" edge wins the dedupe over the rerouted ones.
    assert out_edges == [edge("a", "b")]

    _, out_edges = legend.contract_hidden(nodes, edges[:4], ["x:H"])
    assert out_edges == [{"from": "a", "to": "b", "label": "uses", "kind": "contracted", "via": ["h1", "h2"]}]


def test_untouched_edges_keep_their_kind():
    nodes = [node("a"), node("b"), node("h", "x:H")]
    edges = [edge("a", "b", kind="arch:dependsOn"), edge("a", "h")]
    _, out_edges = legend.contract_hidden(nodes, edges, ["x:H"])
    assert out_edges == [edge("a", "b", kind="arch:dependsOn")]


# --- chat model through c4_graph_data ----------------------------------------


def test_nodes_carry_primary_type_qname():
    nodes, _ = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L2")
    types = {n["id"]: n["type"] for n in nodes}
    assert types[f"{CHAT}chat_api"] == "arch:Container"
    assert types[f"{CHAT}app01"] == "arch:DeploymentNode"


def test_l2_hide_deployment_nodes_contracts_deployments_to_prod():
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L2")
    out_nodes, out_edges = legend.contract_hidden(nodes, edges, ["arch:DeploymentNode"])
    assert not [n for n in out_nodes if n["type"] == "arch:DeploymentNode"]
    deployed = {e["from"] for e in out_edges if e["to"] == PROD and e["label"] == "deployed to"}
    assert deployed == CONTAINERS
    assert all(e["kind"] == "contracted" for e in out_edges if e["to"] == PROD)


def test_l3_hide_operations_reattaches_consumes_to_container():
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L3")
    out_nodes, out_edges = legend.contract_hidden(nodes, edges, ["hydra:Operation"])
    assert not [n for n in out_nodes if n["type"] == "hydra:Operation"]
    assert (f"{CHAT}chat_ui", f"{CHAT}chat_api", "consumes") in triples(out_edges)


def test_l2_legend_counts():
    nodes, _ = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L2")
    counts = {e["type"]: e["count"] for e in legend.legend_entries(nodes, [])}
    assert counts["arch:Container"] == 4
    assert counts["arch:DeploymentNode"] == 3


# --- /view endpoint: ?hide= and the legend (T02) -----------------------------


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def _view_json(client, iri, query=""):
    resp = client.get(f"/view/{quote(iri, safe='')}?format=json{query}")
    assert resp.status_code == 200
    return resp.json()


def _fragment(client, iri, query=""):
    resp = client.get(f"/view/{quote(iri, safe='')}?{query}", headers=HX)
    assert resp.status_code == 200
    return resp.text


def _canvas_data(html):
    nodes = json.loads(re.search(r"var nodeData = (.*?);\n", html).group(1))
    edges = json.loads(re.search(r"var edgeData = (.*?);\n", html).group(1))
    return nodes, edges


def _legend_items(html):
    section = re.search(r'<section id="c4-legend".*?</section>', html, re.S).group(0)
    return {
        t: (html_lib.unescape(href), pressed)
        for href, t, pressed in re.findall(
            r'<a class="c4-legend-item" href="([^"]*)"[^>]*data-type="([^"]*)" aria-pressed="(true|false)"',
            section,
        )
    }


def test_json_legend_and_hidden_types_at_l2(client):
    view = _view_json(client, CHAT_ARCHITECTURE)
    assert view["hiddenTypes"] == []
    counts = {e["type"]: e["count"] for e in view["legend"]}
    assert counts["arch:Container"] == 4
    assert counts["arch:DeploymentNode"] == 3
    assert not any(e["hidden"] for e in view["legend"])

    view = _view_json(client, CHAT_ARCHITECTURE, "&hide=arch:DeploymentNode")
    assert view["hiddenTypes"] == ["arch:DeploymentNode"]
    # Counts stay those of the unfiltered level.
    entry = next(e for e in view["legend"] if e["type"] == "arch:DeploymentNode")
    assert entry == {**entry, "count": 3, "hidden": True}


def test_hide_fragment_drops_hidden_nodes_and_keeps_containers(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "hide=arch:DeploymentNode")
    nodes, edges = _canvas_data(html)
    ids = {n["id"] for n in nodes}
    assert APP01 not in ids
    assert CONTAINERS <= ids
    contracted = {e["from"] for e in edges if e["to"] == PROD and e.get("kind") == "contracted"}
    assert contracted == CONTAINERS


def test_hidden_legend_entry_is_pressed_and_its_href_unhides(client):
    items = _legend_items(_fragment(client, CHAT_ARCHITECTURE, "hide=arch:DeploymentNode"))
    href, pressed = items["arch:DeploymentNode"]
    assert pressed == "true"
    assert "hide=" not in href
    assert "level=L2" in href
    href, pressed = items["arch:Container"]
    assert pressed == "false"
    assert "hide=arch:Container,arch:DeploymentNode" in href


def test_level_toggle_carries_hide_and_descent_links_do_not(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "hide=arch:DeploymentNode")
    toggle = [html_lib.unescape(h) for h in re.findall(r'<a href="([^"]*)"[^>]*data-level="L\d"', html)]
    assert toggle
    for href in toggle:
        assert "hide=arch:DeploymentNode" in href, href
    breadcrumbs = re.search(r'<nav class="breadcrumbs">.*?</nav>', html, re.S).group(0)
    assert "hide=" not in breadcrumbs
    assert "seamsNavigate(n.navigateTo || n.id, " in html
    assert not re.search(r"seamsNavigate\([^)]*hide", html)


def test_href_for_appends_hide_only_when_non_empty():
    assert "hide" not in viewer_app.href_for(CHAT_ARCHITECTURE, [], "L2")
    assert "hide" not in viewer_app.href_for(CHAT_ARCHITECTURE, [], "L2", [])
    assert viewer_app.href_for(CHAT_ARCHITECTURE, [], "L2", ["a:B", "c:D"]).endswith("&hide=a:B,c:D")


def test_malformed_hide_token_warns_without_raw_markup(client):
    view = _view_json(client, CHAT_ARCHITECTURE, f"&hide={quote('<script>,arch:DeploymentNode')}")
    assert view["hiddenTypes"] == ["arch:DeploymentNode"]
    assert any("<script>" in w["message"] for w in view["warnings"])

    html = _fragment(client, CHAT_ARCHITECTURE, f"hide={quote('<script>')}")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html.replace("<script>\n", "")
    assert html.count("<script>") == html.count("<script>\n")


def test_unknown_but_wellformed_hide_token_is_harmless(client):
    view = _view_json(client, CHAT_ARCHITECTURE, "&hide=arch:Nope")
    assert view["hiddenTypes"] == ["arch:Nope"]
    assert not any(e["hidden"] for e in view["legend"])


def test_non_c4_view_has_no_legend(client):
    view = _view_json(client, CONVERSATION_SHAPE, "&hide=arch:DeploymentNode")
    assert view["legend"] == []
    assert view["hiddenTypes"] == []
    assert 'id="c4-legend"' not in _fragment(client, CONVERSATION_SHAPE, "hide=arch:DeploymentNode")


def test_default_view_matches_unfiltered_graph_data(client):
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L2")
    assert legend.contract_hidden(nodes, edges, []) == (nodes, edges)
    assert _canvas_data(_fragment(client, CHAT_ARCHITECTURE)) == (nodes, edges)
