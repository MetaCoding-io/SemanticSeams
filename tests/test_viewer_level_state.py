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
    assert levels.C4_LEVELS["L4"].question == "Where does this architecture hand off to UI and process?"


def test_json_levels_for_c4_model(client):
    body = _view_json(client, CHAT_ARCHITECTURE)
    assert [lv["id"] for lv in body["levels"]] == ["L1", "L2", "L3", "L4"]
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
    assert [s["id"] for s in summaries] == ["L1", "L2", "L3", "L4"]
    by_id = {s["id"]: s for s in summaries}
    assert by_id["L1"]["empty"] is False
    assert by_id["L1"]["nodeCount"] == 1
    assert by_id["L2"]["empty"] is True
    assert by_id["L3"]["empty"] is True
    assert by_id["L4"]["empty"] is True


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
    assert [lv for _, lv in toggle] == ["L1", "L2", "L3", "L4"]
    for href, lv in toggle:
        assert href.endswith(f"&level={lv}")
    others = _view_hrefs(_without_toggle(html))
    assert others, "expected breadcrumb links into /view/"
    for href in others:
        assert "level=L1" in href, href
        assert "level=L2" not in href and "level=L3" not in href and "level=L4" not in href


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


def _level_cards(html):
    start = html.index('<section id="level-cards"')
    return html[start:html.index("</section>", start)]


def _card_tags(section):
    return re.findall(r'<a class="level-card[^"]*"[^>]*>', section)


def test_level_cards_render_questions_in_order(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "level=L1")
    section = _level_cards(html)
    assert 'class="level-cards"' in section
    assert "<h3>Levels</h3>" in section
    tags = _card_tags(section)
    assert [re.search(r'data-level="(L\d)"', t).group(1) for t in tags] == ["L1", "L2", "L3", "L4"]
    for lv in ("L1", "L2", "L3", "L4"):
        assert html_lib.escape(levels.C4_LEVELS[lv].question) in section
    assert all('data-empty="false"' in t for t in tags)
    assert [t for t in tags if 'aria-current="true"' in t] == [tags[0]]
    for tag, lv in zip(tags, ("L1", "L2", "L3", "L4")):
        href = html_lib.unescape(re.search(r'href="([^"]*)"', tag).group(1))
        hx = html_lib.unescape(re.search(r'hx-get="([^"]*)"', tag).group(1))
        assert href == hx and href.endswith(f"&level={lv}")
        assert 'hx-target="#view-content"' in tag and 'hx-push-url="true"' in tag


def test_level_cards_sit_before_questions(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "level=L2")
    cards_at = html.index('<section id="level-cards"')
    if 'id="query-catalog"' in html:
        assert cards_at < html.index('id="query-catalog"')
    # Same column as the catalog: inside the canvas, before the inspector.
    assert html.index('class="view-canvas"') < cards_at < html.index('<aside class="inspector">')


def test_canvas_navigation_carries_level(client):
    html = _fragment(client, CHAT_ARCHITECTURE, "level=L1")
    calls = re.findall(r"seamsNavigate\(([^;]*)\);", html)
    assert calls
    for call in calls:
        assert '"L1"' in call, call


def test_canvas_navigation_carries_level_through_non_c4(client):
    path = quote(CHAT_ARCHITECTURE, safe="")
    html = _fragment(client, CONVERSATION_SHAPE, f"path={path}&level=L1")
    for call in re.findall(r"seamsNavigate\(([^;]*)\);", html):
        assert '"L1"' in call, call


def test_page_seams_navigate_accepts_level(client):
    resp = client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}?level=L1")
    assert resp.status_code == 200
    assert "window.seamsNavigate = function (iri, pathQs, level)" in resp.text
    assert '"&level=" + encodeURIComponent(level)' in resp.text


def test_empty_level_card_is_greyed_and_inert(client, monkeypatch):
    real = viewer_app.level_summaries

    def fake(model_iri):
        out = [dict(s) for s in real(model_iri)]
        out[-1]["empty"] = True
        return out

    monkeypatch.setattr(viewer_app, "level_summaries", fake)
    html = _fragment(client, CHAT_ARCHITECTURE, "level=L1")
    tags = _card_tags(_level_cards(html))
    last = list(levels.C4_LEVELS)[-1]
    l3 = [t for t in tags if f'data-level="{last}"' in t]
    assert len(l3) == 1
    card = l3[0]
    assert "level-empty" in card
    assert 'aria-disabled="true"' in card
    assert 'data-empty="true"' in card
    assert "hx-get" not in card and "href=" not in card
    # The toggle link for the last level gets the same inert treatment.
    nav = html[html.index('class="level-toggle"'):html.index("</nav>", html.index('class="level-toggle"'))]
    toggle_l3 = re.search(rf'<a [^>]*data-level="{last}"[^>]*>', nav).group(0)
    assert "level-empty" in toggle_l3 and 'aria-disabled="true"' in toggle_l3
    assert "hx-get" not in toggle_l3 and "href=" not in toggle_l3


def test_non_c4_view_has_no_level_cards(client):
    html = _fragment(client, CONVERSATION_SHAPE)
    assert 'id="level-cards"' not in html


def test_browser_history_reloads_views_instead_of_restoring_snapshots(client):
    # Back/Forward must re-render from the server: the canvases are drawn by
    # scripts, so an htmx localStorage snapshot restores blank diagrams.
    html = client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}").text
    assert '"historyCacheSize": 0' in html
    assert '"refreshOnHistoryMiss": true' in html
    # htmx ignores popstate for entries without {htmx: true}: the landing entry
    # and every canvas click must carry it, or Back changes only the URL.
    assert 'history.replaceState({ htmx: true }, "", location.href)' in html
    assert 'history.pushState({ htmx: true }, "", url)' in html
    assert "history.pushState({}," not in html


def test_disambiguation_landing_hides_notation_and_no_renderer_note(client):
    route_to_provider = "https://example.org/chat/chat_bpmn#route_to_provider"
    html = client.get(f"/view/{quote(route_to_provider, safe='')}").text
    assert 'id="disambiguation"' in html
    assert "(none)" not in html
    assert "No renderer yet" not in html
