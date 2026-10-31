"""Tests for the viewer's derived sequence diagrams (M013/S03, D048): the
/sequence/{event} route (JSON and the Mermaid fragment), the Sequences links
on the IFML view and the BPMN view an event click lands on (ADR-0005), and
Mermaid loading once in the page shell (MEM009).
"""

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
from viewer import validation  # noqa: E402

CHAT = "https://example.org/chat/"
CHAT_IFML = f"{CHAT}chat_ifml"
SEND_MESSAGE = f"{CHAT}send_message"
SEQUENCES = ROOT / "docs" / "generation" / "sequences"
EXPENSES_TRIG = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
HX = {"hx-request": "true"}


def sequence_url(iri: str, query: str = "") -> str:
    return f"/sequence/{quote(iri, safe='')}{query}"


@pytest.fixture
def client():
    return TestClient(viewer_app.app)


def test_send_message_json_matches_golden(client):
    resp = client.get(sequence_url(SEND_MESSAGE))
    assert resp.status_code == 200
    body = resp.json()
    assert body["event"] == SEND_MESSAGE
    assert body["label"] == "Send Message"
    assert len(body["diagrams"]) == 1
    diagram = body["diagrams"][0]
    assert diagram["name"] == "send_message"
    assert diagram["path"] == []
    assert diagram["mermaid"] == (SEQUENCES / "chat-app" / "send_message.mmd").read_text()
    assert diagram["gaps"] == [
        line.split("%% gap: ", 1)[1] for line in diagram["mermaid"].splitlines() if "%% gap: " in line
    ]


@pytest.mark.parametrize(
    "query, headers",
    [("?format=html", {}), ("", HX)],
    ids=["format-html", "hx-request"],
)
def test_sequence_html_fragment(client, query, headers):
    resp = client.get(sequence_url(SEND_MESSAGE, query), headers=headers)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert '<pre class="mermaid" data-sequence="send_message">' in html
    assert "-&gt;&gt;" in html
    assert "<h4>single</h4>" in html
    assert "mermaid@11" not in html


@pytest.mark.parametrize(
    "iri",
    [f"{CHAT}no_such_event", f"{CHAT}chat_api"],
    ids=["unknown", "container"],
)
def test_sequence_not_an_event_is_404(client, iri):
    assert client.get(sequence_url(iri)).status_code == 404
    assert client.get(sequence_url(iri, "?format=html")).status_code == 404


def test_ifml_model_fragment_links_send_message(client):
    resp = client.get(f"/view/{quote(CHAT_IFML, safe='')}", headers=HX)
    assert resp.status_code == 200
    html = resp.text
    assert 'id="sequence-catalog"' in html
    assert re.search(rf'class="sequence-link" data-event="{re.escape(SEND_MESSAGE)}"', html)
    assert f'hx-get="{sequence_url(SEND_MESSAGE, "?format=html")}"' in html
    assert 'id="sequence-view"' in html


def test_event_click_lands_on_process_view_with_link(client):
    resp = client.get(f"/view/{quote(SEND_MESSAGE, safe='')}", headers=HX)
    assert resp.status_code == 200
    html = resp.text
    assert 'data-notation="bpmn"' in html or "(bpmn)" in html
    assert f'data-event="{SEND_MESSAGE}"' in html
    assert 'id="sequence-view"' in html


def test_view_json_contract_unchanged(client):
    body = client.get(f"/view/{quote(CHAT_IFML, safe='')}?format=json").json()
    assert "sequence_events" not in body
    assert "sequenceEvents" not in body


def test_unrelated_view_has_no_sequence_catalog(client):
    resp = client.get(f"/view/{quote(viewer_app.root_iri(), safe='')}", headers=HX)
    assert resp.status_code == 200
    assert 'id="sequence-catalog"' not in resp.text


def test_mermaid_loads_in_shell_only(client):
    url = f"/view/{quote(CHAT_IFML, safe='')}"
    assert "mermaid@11" in client.get(url).text
    assert "mermaid@11" not in client.get(url, headers=HX).text


@pytest.fixture
def expenses(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    viewer_app.configure(EXPENSES_TRIG)
    try:
        yield viewer_app
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


def test_expenses_submit_expense_matches_goldens(expenses):
    base = re.search(r"^@prefix :\s+<([^>]+)>", EXPENSES_TRIG.read_text(), re.MULTILINE).group(1)
    event = f"{base}submit_expense"
    resp = TestClient(expenses.app).get(sequence_url(event))
    assert resp.status_code == 200
    diagrams = resp.json()["diagrams"]
    goldens = sorted((SEQUENCES / "expenses").glob("*.mmd"))
    assert len(diagrams) == len(goldens) == 5
    assert sorted(d["name"] + ".mmd" for d in diagrams) == [g.name for g in goldens]
    for d in diagrams:
        assert d["path"], d["name"]
        assert d["mermaid"] == (SEQUENCES / "expenses" / f"{d['name']}.mmd").read_text()
