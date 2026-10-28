"""Tests for the C4 zoom levels (M006/S02, ADR-0008): viewer/levels.py config,
the compound c4_graph_data() projection (parent field, no contains edges,
rollup edges only at L1) and the ?level= param / "level" field on /view.
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
from viewer import levels  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
CHAT_SYSTEM = f"{CHAT}chat_system"
PROD = f"{CHAT}prod"
CONTAINERS = {f"{CHAT}{c}" for c in ("chat_ui", "chat_api", "llm_gateway", "message_db")}
DEPLOY_NODES = {f"{CHAT}{n}" for n in ("web01", "app01", "db01")}


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def _graph(level):
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    parents = {n["id"]: n["parent"] for n in nodes}
    triples = [(e["from"], e["to"], e["label"]) for e in edges]
    return nodes, edges, parents, triples


def _view_json(client, iri, query=""):
    resp = client.get(f"/view/{quote(iri, safe='')}?format=json{query}")
    assert resp.status_code == 200
    return resp.json()


def test_level_config():
    assert list(levels.C4_LEVELS) == ["L1", "L2", "L3"]
    assert levels.DEFAULT_LEVEL == "L2"
    l1, l2, l3 = levels.C4_LEVELS.values()
    assert l1.classes < l2.classes <= l3.classes
    assert set(l2.edge_rules) < set(l3.edge_rules)
    assert l1.rollup and not l2.rollup and not l3.rollup


def test_load_rollup_reads_fixed_query():
    assert levels.ROLLUP_QUERY_PATH.name == "c4-l1-rollup.rq"
    rows = levels.load_rollup(viewer_app.get_graph())
    assert rows == [(CHAT_SYSTEM, PROD, "deployed to")]


def test_l1_system_context():
    nodes, edges, parents, triples = _graph("L1")
    assert parents == {CHAT_SYSTEM: None, PROD: None}
    assert triples == [(CHAT_SYSTEM, PROD, "deployed to")]
    assert edges[0]["kind"] == "rollup"


def test_l2_nests_containers_and_nodes():
    nodes, edges, parents, triples = _graph("L2")
    for c in CONTAINERS:
        assert parents[c] == CHAT_SYSTEM
    for n in DEPLOY_NODES:
        assert parents[n] == PROD
    assert parents[CHAT_SYSTEM] is None and parents[PROD] is None
    assert set(parents) == CONTAINERS | DEPLOY_NODES | {CHAT_SYSTEM, PROD}
    depends = {(f, t) for f, t, lbl in triples if lbl == "depends on"}
    assert depends == {
        (f"{CHAT}chat_ui", f"{CHAT}chat_api"),
        (f"{CHAT}chat_api", f"{CHAT}message_db"),
        (f"{CHAT}chat_api", f"{CHAT}llm_gateway"),
    }
    deployed = {(f, t) for f, t, lbl in triples if lbl == "deployed to"}
    assert deployed == {
        (f"{CHAT}chat_ui", f"{CHAT}web01"),
        (f"{CHAT}chat_api", f"{CHAT}app01"),
        (f"{CHAT}llm_gateway", f"{CHAT}app01"),
        (f"{CHAT}message_db", f"{CHAT}db01"),
    }


@pytest.mark.parametrize("level", ["L1", "L2", "L3"])
def test_no_contains_edges(level):
    _, edges, _, triples = _graph(level)
    assert all(lbl != "contains" for _, _, lbl in triples)
    assert all(e["kind"] != "arch:contains" for e in edges)


@pytest.mark.parametrize("level", ["L2", "L3"])
def test_rollup_edges_only_at_l1(level):
    _, edges, _, triples = _graph(level)
    assert all(e["kind"] != "rollup" for e in edges)
    # The system-level rollup edge is not drawn once containers are visible.
    assert (CHAT_SYSTEM, PROD, "deployed to") not in triples


def test_l3_nests_exposed_operations():
    nodes, edges, parents, triples = _graph("L3")
    assert parents[f"{CHAT}send_message_op"] == f"{CHAT}chat_api"
    assert parents[f"{CHAT}stream_events"] == f"{CHAT}chat_api"
    assert parents[f"{CHAT}completion_op"] == f"{CHAT}llm_gateway"
    assert (f"{CHAT}chat_ui", f"{CHAT}send_message_op", "consumes") in triples
    # Exposure is shown by nesting, never as an edge.
    assert all(e["kind"] != "seam:exposes" for e in edges)
    op = next(n for n in nodes if n["id"] == f"{CHAT}send_message_op")
    assert {"label", "typeLabel", "description", "layer", "seams"} <= op.keys()


def test_l2_has_no_operations():
    _, _, parents, triples = _graph("L2")
    assert f"{CHAT}send_message_op" not in parents
    assert all(lbl != "consumes" for _, _, lbl in triples)


@pytest.mark.parametrize("level", ["L1", "L2", "L3"])
def test_output_is_deterministic_and_sorted(level):
    first = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    second = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    assert first == second
    nodes, edges = first
    assert [(n["parent"] or "", n["id"]) for n in nodes] == sorted((n["parent"] or "", n["id"]) for n in nodes)
    assert [(e["from"], e["to"], e["label"]) for e in edges] == sorted(
        (e["from"], e["to"], e["label"]) for e in edges
    )


def test_default_level_signature():
    assert viewer_app.c4_graph_data(CHAT_ARCHITECTURE) == viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L2")


def test_view_json_level_default_and_explicit(client):
    assert _view_json(client, CHAT_ARCHITECTURE)["level"] == "L2"
    body = _view_json(client, CHAT_ARCHITECTURE, "&level=L1")
    assert body["level"] == "L1"
    assert body["warnings"] == []


def test_view_json_unknown_level_falls_back_with_warning(client):
    body = _view_json(client, CHAT_ARCHITECTURE, "&level=bogus")
    assert body["level"] == "L2"
    assert {"message": "Unknown level 'bogus'; showing L2"} in body["warnings"]


def test_html_unknown_level_still_renders(client):
    resp = client.get(
        f"/view/{quote(CHAT_ARCHITECTURE, safe='')}?level=bogus",
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "Unknown level" in resp.text


def test_non_c4_view_has_no_level(client):
    # ConversationShape self-lands (MEM012); an explicit level is ignored.
    body = _view_json(client, f"{CHAT}ConversationShape", "&level=L1")
    assert body["level"] is None
    assert body["warnings"] == []
