"""Tests for C4 level state in the URL (M006/S03): the level is carried on
every /view link (seam edges, candidates, breadcrumbs, root) including through
non-C4 views, and level_summaries() reports per-level counts and empty flags
on the additive "levels" field of /view.
"""

import html as html_lib
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import rdflib
from rdflib import RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import levels  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_ARCHITECTURE = f"{CHAT}chat_architecture"
CONVERSATION_SHAPE = f"{CHAT}ConversationShape"
HX = {"hx-request": "true"}


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


def _view_hrefs(html):
    return [html_lib.unescape(h) for h in re.findall(r'href="(/view/[^"]*)"', html)]


def _without_toggle(html):
    return re.sub(r'<a [^>]*data-level="L\d"[^>]*>', "", html)


def test_level_questions_configured():
    assert levels.C4_LEVELS["L1"].question == "Which systems talk to each other, and where do they run?"
    assert levels.C4_LEVELS["L2"].question == "Which containers make up the system, and where are they deployed?"
    assert levels.C4_LEVELS["L3"].question == "Which operations does each container expose and consume?"


def test_json_levels_for_c4_model(client):
    body = _view_json(client, CHAT_ARCHITECTURE)
    assert [lv["id"] for lv in body["levels"]] == ["L1", "L2", "L3"]
    for lv in body["levels"]:
        assert lv["question"] == levels.C4_LEVELS[lv["id"]].question
        assert lv["title"] == levels.C4_LEVELS[lv["id"]].title
        assert lv["nodeCount"] > 0
        assert lv["edgeCount"] >= 0
        assert lv["empty"] is False


def test_json_levels_empty_for_non_c4(client):
    body = _view_json(client, CONVERSATION_SHAPE)
    assert body["levels"] == []


def test_level_summaries_marks_empty_levels(monkeypatch):
    seam = rdflib.Namespace("https://w3id.org/seams/seam#")
    arch = rdflib.Namespace("https://w3id.org/seams/arch#")
    model = URIRef("https://example.org/tiny/model")
    system = URIRef("https://example.org/tiny/system")
    ds = rdflib.Dataset()
    ds.add((model, seam.notation, seam.C4))
    ds.add((system, RDF.type, arch.System))
    ds.add((system, seam.inModel, model))
    monkeypatch.setattr(viewer_app, "get_graph", lambda: ds)

    summaries = viewer_app.level_summaries(str(model))
    assert [s["id"] for s in summaries] == ["L1", "L2", "L3"]
    by_id = {s["id"]: s for s in summaries}
    assert by_id["L1"]["empty"] is False
    assert by_id["L1"]["nodeCount"] == 1
    assert by_id["L2"]["empty"] is True
    assert by_id["L3"]["empty"] is True


def test_level_summaries_no_nodes_is_empty(monkeypatch):
    ds = rdflib.Dataset()
    monkeypatch.setattr(viewer_app, "get_graph", lambda: ds)
    summaries = viewer_app.level_summaries("https://example.org/tiny/nothing")
    assert all(s["empty"] and s["nodeCount"] == 0 for s in summaries)


def test_href_for_only_carries_known_levels():
    assert viewer_app.href_for(CHAT_ARCHITECTURE, [], "L1").endswith("&level=L1")
    assert "level=" not in viewer_app.href_for(CHAT_ARCHITECTURE, [])
    assert "level=" not in viewer_app.href_for(CHAT_ARCHITECTURE, [], "bogus")


def test_c4_fragment_carries_level_on_every_link(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "level=L1")
    toggle = [
        (html_lib.unescape(h), lv) for h, lv in re.findall(r'<a href="([^"]*)"[^>]*data-level="(L\d)"', html)
    ]
    assert [lv for _, lv in toggle] == ["L1", "L2", "L3"]
    for href, lv in toggle:
        assert href.endswith(f"&level={lv}")
    others = _view_hrefs(_without_toggle(html))
    assert others, "expected breadcrumb links into /view/"
    for href in others:
        assert "level=L1" in href, href
        assert "level=L2" not in href and "level=L3" not in href


def test_level_carried_through_non_c4_view(client):
    path = quote(CHAT_ARCHITECTURE, safe="")
    html = _fragment(client, CONVERSATION_SHAPE, f"path={path}&level=L1")
    arch_href = f"/view/{quote(CHAT_ARCHITECTURE, safe='')}?"
    back = [h for h in _view_hrefs(html) if h.startswith(arch_href)]
    assert back, "expected a breadcrumb back to chat_architecture"
    for href in back:
        assert "level=L1" in href
    # Every other /view link from the non-C4 view keeps the level too.
    for href in _view_hrefs(html):
        assert "level=L1" in href, href


def test_bogus_level_on_non_c4_view_carries_nothing(client):
    path = quote(CHAT_ARCHITECTURE, safe="")
    html = _fragment(client, CONVERSATION_SHAPE, f"path={path}&level=bogus")
    assert "level=" not in html
    assert "bogus" not in "".join(_view_hrefs(html))


def test_bogus_level_on_c4_carries_effective_level(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "level=bogus")
    hrefs = _view_hrefs(html)
    assert hrefs
    assert not any("bogus" in h for h in hrefs)
    others = _view_hrefs(_without_toggle(html))
    assert others
    for href in others:
        assert "level=L2" in href, href


def test_new_tab_landing_keeps_level(client):
    body = _view_json(client, CHAT_ARCHITECTURE, "&level=L1")
    assert body["level"] == "L1"
