"""Tests for the viewer's derived event storm (backlog B4): the /storm/{process}
route (JSON and the HTML fragment) on the expense tutorial's chapter 10, its
404 for an element that is no process and triggers none, and the Storm links
on the views of a process, its triggering event and its IFML model.
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
from viewer import validation  # noqa: E402

CH10 = ROOT / "examples" / "expenses" / "chapter-10" / "expenses.trig"
GOLDEN = ROOT / "tests" / "golden" / "storm" / "approval_process.md"
EX = "https://example.org/expenses/"
APPROVAL = f"{EX}approval_process"
PAYOUT = f"{EX}payout_process"
SUBMIT = f"{EX}submit_expense"
HX = {"hx-request": "true"}


def storm_url(iri: str, query: str = "") -> str:
    return f"/storm/{quote(iri, safe='')}{query}"


def view_url(iri: str) -> str:
    return f"/view/{quote(iri, safe='')}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    viewer_app.configure(CH10)
    try:
        yield TestClient(viewer_app.app)
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


def test_approval_json_matches_golden(client):
    resp = client.get(storm_url(APPROVAL))
    assert resp.status_code == 200
    body = resp.json()
    assert body["process"] == APPROVAL
    assert body["label"] == "Expense Approval"
    assert body["markdown"] == GOLDEN.read_text()
    assert [s["name"] for s in body["steps"]][:3] == ["Submit Expense", "Persist Expense", "Route Expense"]
    assert [s["index"] for s in body["steps"]] == list(range(1, len(body["steps"]) + 1))
    first = body["steps"][0]
    assert first["iri"] == SUBMIT
    assert [(e["kind"], e["step"]) for e in first["entries"]] == [("actor", 1), ("command", 1)]
    decision = body["steps"][2]["entries"]
    assert decision == [
        {"kind": "decision", "step": 3, "iri": f"{EX}approval_routing", "text": "Route Approval (`approval_routing`)"}
    ]
    last = body["steps"][-1]["entries"]
    assert ("process started", PAYOUT) in [(e["kind"], e["iri"]) for e in last]
    assert all(e["kind"] == "read model" and e["step"] is None for e in body["readModels"])
    assert f"{EX}expense_list" in [e["iri"] for e in body["readModels"]]
    assert body["gaps"] == [
        "ApprovalShape has no read model: no ifml page or component seam:reads it",
        "NotificationShape has no read model: no ifml page or component seam:reads it",
    ]


def test_triggering_event_gives_the_process_storm(client):
    by_event = client.get(storm_url(SUBMIT)).json()
    assert by_event == client.get(storm_url(APPROVAL)).json()


def test_storm_json_is_deterministic(client):
    assert client.get(storm_url(PAYOUT)).content == client.get(storm_url(PAYOUT)).content


@pytest.mark.parametrize(
    "query, headers",
    [("?format=html", {}), ("", HX)],
    ids=["format-html", "hx-request"],
)
def test_storm_html_fragment(client, query, headers):
    resp = client.get(storm_url(APPROVAL, query), headers=headers)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert f'<div class="storm-results" data-process="{APPROVAL}">' in html
    assert "<h3>Storm: Expense Approval</h3>" in html
    assert f'data-step="1" data-iri="{SUBMIT}"' in html
    assert f'data-kind="decision" data-iri="{EX}approval_routing">decision: Route Approval' in html
    assert "<li>ApprovalShape has no read model: no ifml page or component seam:reads it</li>" in html
    assert f'class="storm-json" href="{storm_url(APPROVAL)}"' in html


@pytest.mark.parametrize(
    "iri",
    [f"{EX}no_such_process", f"{EX}expense_api", f"{EX}approve_form", f"{EX}ExpenseShape"],
    ids=["unknown", "container", "form", "shape"],
)
def test_storm_not_a_process_is_404(client, iri):
    for query in ("", "?format=html"):
        resp = client.get(storm_url(iri, query))
        assert resp.status_code == 404
        assert (
            resp.json()["detail"] == f"{iri}: proc:Process: no such proc:Process, or ifml:Event that seam:triggers one"
        )


def test_event_triggering_no_process_is_404(client):
    iri = f"{EX}submit_approval"
    resp = client.get(storm_url(iri))
    assert resp.status_code == 404
    assert resp.json()["detail"] == f"{iri}: seam:triggers: ifml:Event triggers no proc:Process"


@pytest.mark.parametrize(
    "clicked, process",
    [(APPROVAL, APPROVAL), (SUBMIT, APPROVAL), (PAYOUT, PAYOUT), (f"{EX}expense_ifml", APPROVAL)],
    ids=["process", "triggering-event", "channel-started-process", "ifml-model"],
)
def test_focus_fragment_links_its_storm(client, clicked, process):
    resp = client.get(view_url(clicked), headers=HX)
    assert resp.status_code == 200
    html = resp.text
    assert 'id="storm-catalog"' in html
    assert f'class="storm-link" data-process="{process}"' in html
    assert f'hx-get="{storm_url(process, "?format=html")}"' in html
    assert 'id="storm-view"' in html


def test_unrelated_view_has_no_storm_catalog(client):
    resp = client.get(view_url(viewer_app.root_iri()), headers=HX)
    assert resp.status_code == 200
    assert 'id="storm-catalog"' not in resp.text


def test_view_json_contract_unchanged(client):
    body = client.get(f"{view_url(APPROVAL)}?format=json").json()
    assert "storm_processes" not in body
    assert "stormProcesses" not in body
