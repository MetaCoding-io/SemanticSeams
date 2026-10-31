"""Tests for the C4 zoom levels (M006/S02, ADR-0008): viewer/levels.py config,
the compound c4_graph_data() projection (parent field, no contains edges,
rollup edges only at L1) and the ?level= param / "level" field on /view.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from rdflib import URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import levels  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
CHAT_SYSTEM = f"{CHAT}chat_system"
PROD = f"{CHAT}production"
# Development contains no deployment node (ADR-0015), so no edge reaches it.
DEV = f"{CHAT}development"
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
    assert list(levels.C4_LEVELS) == ["L1", "L2", "L3", "L4"]
    assert levels.DEFAULT_LEVEL == "L2"
    l1, l2, l3, l4 = levels.C4_LEVELS.values()
    assert l1.classes < l2.classes <= l3.classes == l4.classes
    assert set(l2.edge_rules) < set(l3.edge_rules) == set(l4.edge_rules)
    assert l1.rollup and not l2.rollup and not l3.rollup and not l4.rollup
    assert l4.exposed_elements and l4.nest
    assert not any(lv.nest for lv in (l1, l2, l3))
    assert l4.title == "Seams"


def test_load_rollup_reads_fixed_query():
    assert levels.ROLLUP_QUERY_PATH.name == "c4-l1-rollup.rq"
    rows = levels.load_rollup(viewer_app.get_graph())
    assert rows == [(CHAT_SYSTEM, PROD, "deployed to")]


def test_l1_system_context():
    nodes, edges, parents, triples = _graph("L1")
    assert parents == {CHAT_SYSTEM: None, DEV: None, PROD: None}
    assert triples == [(CHAT_SYSTEM, PROD, "deployed to")]
    assert edges[0]["kind"] == "rollup"


def test_l2_nests_containers_and_nodes():
    nodes, edges, parents, triples = _graph("L2")
    for c in CONTAINERS:
        assert parents[c] == CHAT_SYSTEM
    for n in DEPLOY_NODES:
        assert parents[n] == PROD
    assert parents[CHAT_SYSTEM] is None and parents[PROD] is None and parents[DEV] is None
    assert set(parents) == CONTAINERS | DEPLOY_NODES | {CHAT_SYSTEM, DEV, PROD}
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


@pytest.mark.parametrize("level", ["L1", "L2", "L3", "L4"])
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


@pytest.mark.parametrize("level", ["L1", "L2", "L3", "L4"])
def test_output_is_deterministic_and_sorted(level):
    first = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    second = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    assert first == second
    nodes, edges = first
    assert [(n["parent"] or "", n["id"]) for n in nodes] == sorted((n["parent"] or "", n["id"]) for n in nodes)
    assert [(e["from"], e["to"], e["label"]) for e in edges] == sorted((e["from"], e["to"], e["label"]) for e in edges)


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


# --- T03: ELK + SVG renderer and the level toggle ---


def _fragment(client, iri, query=""):
    resp = client.get(f"/view/{quote(iri, safe='')}{query}", headers={"hx-request": "true"})
    assert resp.status_code == 200
    return resp.text


def test_c4_fragment_uses_elk(client):
    html = _fragment(client, CHAT_ARCHITECTURE)
    assert "ELK" in html
    assert "INCLUDE_CHILDREN" in html
    assert '"elk.randomSeed"' in html
    assert "container.seamsLayout" in html
    assert "new vis.Network" not in html
    # Pan/zoom is buttons + drag only; the wheel must keep scrolling the page.
    assert 'addEventListener("wheel"' not in html
    assert "addEventListener('wheel'" not in html


def test_c4_fragment_level_toggle(client):
    import re

    html = _fragment(client, CHAT_ARCHITECTURE, "?level=L3")
    nav = html[html.index('class="level-toggle"') : html.index("</nav>", html.index('class="level-toggle"'))]
    links = re.findall(r'<a href="([^"]*)" hx-get="([^"]*)"', nav)
    assert [h for h, _ in links] == [g for _, g in links]
    assert [h.rsplit("level=", 1)[1] for h, _ in links] == ["L1", "L2", "L3", "L4"]
    assert nav.count('hx-target="#view-content"') == 4
    assert nav.count('hx-push-url="true"') == 4
    current = re.findall(r'data-level="(L\d)"[^>]*aria-current="true"', nav)
    assert current == ["L3"]


def test_c4_fragment_unknown_level_marks_default_active(client):
    import re

    html = _fragment(client, CHAT_ARCHITECTURE, "?level=bogus")
    nav = html[html.index('class="level-toggle"') : html.index("</nav>", html.index('class="level-toggle"'))]
    assert re.findall(r'data-level="(L\d)"[^>]*aria-current="true"', nav) == ["L2"]


def test_non_c4_fragment_has_no_level_toggle(client):
    html = _fragment(client, f"{CHAT}message_lifecycle", "?level=L1")
    assert 'class="level-toggle"' not in html
    assert "new vis.Network" in html


def test_full_page_loads_elkjs(client):
    resp = client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert '<script src="https://unpkg.com/elkjs@0.9.3/lib/elk.bundled.js"></script>' in resp.text


# --- M007/S02 T03: L4 nests nest-mode seam targets (seam:presents, seam:executes) ---

CHAT_IFML = f"{CHAT}chat_ifml"
SEND_MESSAGE_PROCESS = f"{CHAT}send_message_process"


def _by_id(level):
    nodes, _ = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, level)
    return {n["id"]: n for n in nodes}


def test_l4_nests_presents_target():
    n = _by_id("L4")[CHAT_IFML]
    assert n["parent"] == f"{CHAT}chat_ui"
    assert n["nestedVia"] == "seam:presents"
    assert n["layer"] == "interaction"


def test_l4_nests_executes_target():
    n = _by_id("L4")[SEND_MESSAGE_PROCESS]
    assert n["parent"] == f"{CHAT}chat_api"
    assert n["nestedVia"] == "seam:executes"
    assert n["layer"] == "process"


def test_l4_nests_top_level_members_of_the_nested_models():
    nodes = _by_id("L4")
    ifml_children = [n for n in nodes.values() if n["parent"] == CHAT_IFML]
    bpmn_children = [n for n in nodes.values() if n["parent"] == SEND_MESSAGE_PROCESS]
    assert ifml_children and all(n["layer"] == "interaction" for n in ifml_children)
    assert bpmn_children and all(n["layer"] == "process" for n in bpmn_children)
    assert f"{CHAT}chat_page" in {n["id"] for n in ifml_children}
    # Only top-level members: nothing nested inside chat_page is lifted.
    graph = viewer_app.get_graph()
    held = {str(o) for o in graph.objects(URIRef(f"{CHAT}chat_page"), viewer_app.IFML.contains)}
    assert held and not held & set(nodes)
    # Members are nested cards, not seam targets themselves.
    assert all(n["nestedVia"] is None for n in ifml_children + bpmn_children)


def test_l4_draws_no_nested_model_edges():
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L4")
    _, l3_edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L3")
    assert edges == l3_edges
    # Nesting is shown by parent, never as a presents/executes edge.
    assert all(e["kind"] not in {"seam:presents", "seam:executes"} for e in edges)


def test_no_nested_nodes_below_l4():
    for level in ("L1", "L2", "L3"):
        nodes = _by_id(level)
        assert CHAT_IFML not in nodes and SEND_MESSAGE_PROCESS not in nodes
        assert all(n["nestedVia"] is None for n in nodes.values())


def test_l4_non_nested_nodes_have_null_nested_via():
    nodes = _by_id("L4")
    nested = {n["id"] for n in nodes.values() if n["nestedVia"]}
    assert nested == {CHAT_IFML, SEND_MESSAGE_PROCESS}


def test_view_json_accepts_l4(client):
    body = _view_json(client, CHAT_ARCHITECTURE, "&level=L4")
    assert body["level"] == "L4"
    assert body["warnings"] == []
    l4 = next(lv for lv in body["levels"] if lv["id"] == "L4")
    assert l4["empty"] is False and l4["nodeCount"] > 0


def test_l4_fragment_carries_nested_via(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "?level=L4")
    assert 'data-level="L4"' in html
    assert '"nestedVia": "seam:presents"' in html
    assert '"nestedVia": "seam:executes"' in html
    assert "data-nested-via" in html


def test_l4_legend_counts_nested_types():
    nodes, edges = viewer_app.c4_graph_data(CHAT_ARCHITECTURE, "L4")
    entries = {e["type"]: e for e in viewer_app.legend.legend_entries(nodes, set())}
    assert entries["ifml:InteractionModel"]["count"] == 1
    assert entries["proc:Process"]["count"] == 1
    kept, _ = viewer_app.legend.contract_hidden(nodes, edges, {"proc:ServiceTask"})
    assert all(n["type"] != "proc:ServiceTask" for n in kept)
