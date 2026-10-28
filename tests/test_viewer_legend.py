"""Tests for the C4 legend and click-to-hide contraction (M006/S04, D010):
viewer/legend.py's pure parse_hide / legend_entries / contract_hidden, plus
their behaviour on the chat architecture through c4_graph_data().
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import legend  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
PROD = f"{CHAT}prod"
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
    out_nodes, out_edges = legend.contract_hidden(
        nodes, [edge("a", "h"), edge("h", "b")], ["x:H"]
    )
    assert [n["id"] for n in out_nodes] == ["a", "b"]
    assert out_edges == [
        {"from": "a", "to": "b", "label": "uses", "kind": "contracted", "via": ["h"]}
    ]


def test_multi_hop_chain_mixes_labels():
    nodes = [node("a"), node("h1", "x:H"), node("h2", "x:H"), node("b")]
    edges = [edge("a", "h1", "calls"), edge("h1", "h2", "uses"), edge("h2", "b", "calls")]
    _, out_edges = legend.contract_hidden(nodes, edges, ["x:H"])
    assert out_edges == [
        {"from": "a", "to": "b", "label": "calls / uses", "kind": "contracted", "via": ["h1", "h2"]}
    ]


def test_hidden_node_without_visible_predecessor_drops_its_edges():
    nodes = [node("h", "x:H"), node("b")]
    assert legend.contract_hidden(nodes, [edge("h", "b")], ["x:H"]) == ([node("b")], [])


def test_collapse_into_visible_ancestor():
    nodes = [node("env"), node("h", "x:H", parent="env"), node("c")]
    out_nodes, out_edges = legend.contract_hidden(
        nodes, [edge("c", "h", "deployed to")], ["x:H"]
    )
    assert [n["id"] for n in out_nodes] == ["c", "env"]
    assert out_edges == [
        {"from": "c", "to": "env", "label": "deployed to", "kind": "contracted", "via": ["h"]}
    ]


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
    assert out_edges == [
        {"from": "a", "to": "b", "label": "uses", "kind": "contracted", "via": ["h1", "h2"]}
    ]


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
    assert all(
        e["kind"] == "contracted" for e in out_edges if e["to"] == PROD
    )


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
