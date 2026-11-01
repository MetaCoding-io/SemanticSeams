"""Layer mode data (M008/S03, backlog item 11): viewer/layers.py projects the
loaded model onto six layers with their within-layer edges, lists the seams
that cross layers (tagged with their reveal mode), and warns about elements in
no layer instead of dropping them. GET /layers serves the same JSON.
"""

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
from rdflib import URIRef  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import layers, validation  # noqa: E402

CHAPTER_08 = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
SIX = ["architecture", "interaction", "process", "decision", "data", "lifecycle"]


@pytest.fixture(autouse=True)
def restore_viewer():
    """Each test starts and ends on the default model with empty caches."""
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    yield
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    validation._clear_cache()


def _cross_layer_seam_triples() -> set[tuple[str, str, str]]:
    """Seam triples with both ends in a layer and the two layers different,
    counted straight from the graph."""
    graph = viewer_app.get_graph()
    found = set()
    for s, p, o in graph.triples((None, None, None)):
        if not isinstance(o, URIRef) or not viewer_app.is_seam_predicate(p):
            continue
        a, b = viewer_app.layer_of(str(s)), viewer_app.layer_of(str(o))
        if "other" not in (a, b) and a != b:
            found.add((str(s), viewer_app.qname(p), str(o)))
    return found


def test_chat_app_has_six_layers_in_stacking_order():
    data = layers.build_layers()
    assert [lay["id"] for lay in data["layers"]] == SIX
    for lay in data["layers"]:
        assert len(lay["models"]) == 1, lay["id"]
        assert lay["nodes"], lay["id"]
        model = lay["models"][0]
        assert model["href"].startswith("/view/https%3A%2F%2Fexample.org%2Fchat%2F")
        assert all(viewer_app.layer_of(n["iri"]) == lay["id"] for n in lay["nodes"])


def test_layer_order_covers_every_notation_layer():
    assert sorted(layers.LAYER_ORDER) == sorted(set(viewer_app.LAYER_BY_NOTATION.values()))


def test_seams_are_exactly_the_cross_layer_seam_triples():
    data = layers.build_layers()
    got = {(s["source"], s["predicate"], s["target"]) for s in data["seams"]}
    assert got == _cross_layer_seam_triples()
    assert len(data["seams"]) == len(got)
    for s in data["seams"]:
        assert s["sourceLayer"] != s["targetLayer"]
        assert s["sourceLayer"] in SIX and s["targetLayer"] in SIX
        assert s["reveal"] in {"open", "nest", "layer"}
    # Every reveal mode is included, not only the inspector-only layer seams.
    assert {s["reveal"] for s in data["seams"]} == {"open", "nest", "layer"}


def test_within_layer_edges_join_nodes_of_that_layer():
    data = layers.build_layers()
    assert any(lay["edges"] for lay in data["layers"])
    for lay in data["layers"]:
        ids = {n["iri"] for n in lay["nodes"]}
        for e in lay["edges"]:
            assert e["from"] in ids and e["to"] in ids, (lay["id"], e)
            assert e["label"] != "rdf:type"


def test_everything_is_sorted():
    data = layers.build_layers()
    keys = [(s["source"], s["predicate"], s["target"]) for s in data["seams"]]
    assert keys == sorted(keys)
    for lay in data["layers"]:
        assert [n["iri"] for n in lay["nodes"]] == sorted(n["iri"] for n in lay["nodes"])
        assert [m["iri"] for m in lay["models"]] == sorted(m["iri"] for m in lay["models"])
        edge_keys = [(e["from"], e["to"], e["label"]) for e in lay["edges"]]
        assert edge_keys == sorted(edge_keys)
    assert [w["iri"] for w in data["warnings"]] == sorted(w["iri"] for w in data["warnings"])


def test_build_is_deterministic_across_reloads():
    first = json.dumps(layers.build_layers())
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    assert json.dumps(layers.build_layers()) == first


def test_other_elements_land_in_warnings():
    data = layers.build_layers()
    drawn = {n["iri"] for lay in data["layers"] for n in lay["nodes"]}
    warned = {w["iri"] for w in data["warnings"]}
    # chat_api's operations sit in no model, so their seams cannot be drawn.
    op = "https://example.org/chat/send_message_op"
    assert viewer_app.layer_of(op) == "other"
    assert op in warned and op not in drawn
    assert not warned & drawn
    assert all(w["message"] for w in data["warnings"])
    seam_ends = {s["source"] for s in data["seams"]} | {s["target"] for s in data["seams"]}
    assert not warned & seam_ends


def test_model_in_no_layer_is_warned_not_dropped(monkeypatch):
    graph = viewer_app.get_graph()
    dmn = "https://example.org/chat/routing_dmn"
    without_dmn = {k: v for k, v in viewer_app.LAYER_BY_NOTATION.items() if k != "dmn"}
    monkeypatch.setattr(viewer_app, "LAYER_BY_NOTATION", without_dmn)
    data = layers.build_layers()
    assert "decision" not in [lay["id"] for lay in data["layers"]]
    warned = {w["iri"] for w in data["warnings"]}
    assert dmn in warned
    members = {str(s) for s in graph.subjects(viewer_app.SEAM.inModel, URIRef(dmn))}
    assert members and members <= warned


def test_chapter_08_puts_several_models_on_one_layer():
    viewer_app.configure(CHAPTER_08)
    data = layers.build_layers()
    by_id = {lay["id"]: lay for lay in data["layers"]}
    assert list(by_id) == SIX
    assert [m["iri"] for m in by_id["interaction"]["models"]] == [
        "https://example.org/expenses/expense_ifml",
        "https://example.org/expenses/finance_console",
    ]
    for lid in ("process", "decision", "lifecycle"):
        assert len(by_id[lid]["models"]) == 2, lid
    got = {(s["source"], s["predicate"], s["target"]) for s in data["seams"]}
    assert got == _cross_layer_seam_triples()


def test_layers_route_serves_the_json():
    client = TestClient(viewer_app.app)
    resp = client.get("/layers", headers={"accept": "application/json"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == json.loads(json.dumps(layers.build_layers()))
    assert client.get("/layers?format=json").json()["layers"][0]["id"] == "architecture"


# --- Stacked-plane page (T02) ---------------------------------------------


def _layers_page() -> str:
    resp = TestClient(viewer_app.app).get("/layers", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    return resp.text


def test_layers_page_draws_six_planes_in_order():
    html = _layers_page()
    found = re.findall(r'<g class="layer-plane" data-layer="([a-z]+)"', html)
    assert found == SIX


def test_layers_page_draws_every_seam_with_its_ends():
    html = _layers_page()
    data = layers.build_layers()
    lines = re.findall(
        r'<line class="layer-seam" data-source="([^"]+)" data-target="([^"]+)"[^>]*data-reveal="([a-z]+)"', html
    )
    assert lines == [(s["source"], s["target"], s["reveal"]) for s in data["seams"]]
    # Every seam end is drawn, as an element card or a model link in a plane title.
    drawn = set(re.findall(r'class="layer-(?:node|plane-model)" href="[^"]+" data-iri="([^"]+)"', html))
    assert {iri for s, t, _ in lines for iri in (s, t)} <= drawn


def test_layers_page_plane_titles_open_the_first_model_flat():
    html = _layers_page()
    for lay in layers.build_layers()["layers"]:
        title = re.search(
            r'<g class="layer-plane" data-layer="'
            + lay["id"]
            + r'">.*?<g class="layer-plane-title">\s*<a href="([^"]+)">',
            html,
            re.S,
        )
        assert title, lay["id"]
        assert title.group(1) == lay["models"][0]["href"]


def test_layers_page_lists_every_model_of_a_layer():
    viewer_app.configure(CHAPTER_08)
    html = _layers_page()
    plane = html.split('<g class="layer-plane" data-layer="interaction">', 1)[1].split('<g class="layer-edges">', 1)[0]
    hrefs = re.findall(r'class="layer-plane-model" href="([^"]+)"', plane)
    assert hrefs == [
        "/view/https%3A%2F%2Fexample.org%2Fexpenses%2Fexpense_ifml",
        "/view/https%3A%2F%2Fexample.org%2Fexpenses%2Ffinance_console",
    ]


def test_layers_page_lists_elements_in_no_layer():
    html = _layers_page()
    warned = re.findall(r'<li data-iri="([^"]+)">', html.split('class="warning layers-warnings"', 1)[1])
    assert warned == [w["iri"] for w in layers.build_layers()["warnings"]]
    assert "https://example.org/chat/send_message_op" in warned


def test_page_header_links_to_layer_mode():
    client = TestClient(viewer_app.app)
    for url in ("/layers", f"/view/{quote(viewer_app.root_iri(), safe='')}"):
        html = client.get(url).text
        header = html.split("<header>", 1)[1].split("</header>", 1)[0]
        assert 'href="/layers"' in header, url
