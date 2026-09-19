"""Tests for the canned query catalog + engine (S03 T01).

Execution-level tests run viewer.queries against the real viewer Dataset
(viewer.app.get_graph(): chat-app.trig only, default_union=True) and pin the
same chat-app benchmark rows as tests/test_acceptance.py lines 309-343 —
proving the instance-level property paths need no ontology union.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from rdflib import RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import queries  # noqa: E402
from viewer.app import get_graph  # noqa: E402

CHAT = "https://example.org/chat/"
MESSAGE_SHAPE = CHAT + "MessageShape"
DB01 = CHAT + "db01"
S_COMPOSING = CHAT + "s_composing"

EXPECTED_NAMES = ["what-writes-shape", "impact-of-node", "what-moves-state"]


def test_catalog_has_three_queries():
    assert list(queries.QUERIES) == EXPECTED_NAMES
    for name, q in queries.QUERIES.items():
        assert q.name == name
        assert q.label
        assert q.question
        assert q.focusVariable
        assert q.focusType


def test_execute_what_writes_shape_chat_app():
    result = queries.execute_query(get_graph(), "what-writes-shape", MESSAGE_SHAPE)
    assert result["queryName"] == "what-writes-shape"
    assert result["focusIri"] == MESSAGE_SHAPE
    assert result["bindings"] == {"shape": MESSAGE_SHAPE}
    assert result["columns"] == ["event", "writer"]
    assert result["resultCount"] == 2
    assert {(r["event"], r["writer"]) for r in result["rows"]} == {
        (CHAT + "send_message", CHAT + "chat_bpmn#persist_user_msg"),
        (CHAT + "send_message", CHAT + "chat_bpmn#persist_response"),
    }


def test_execute_impact_of_node_chat_app():
    result = queries.execute_query(get_graph(), "impact-of-node", DB01)
    assert result["columns"] == ["impacted"]
    assert result["resultCount"] == 4
    assert {r["impacted"] for r in result["rows"]} == {
        CHAT + "message_db",
        CHAT + "chat_api",
        CHAT + "chat_ui",
        CHAT + "send_message_process",
    }


def test_execute_what_moves_state_chat_app():
    result = queries.execute_query(get_graph(), "what-moves-state", S_COMPOSING)
    assert result["columns"] == ["task", "transition", "toState"]
    assert result["resultCount"] == 1
    assert {(r["task"], r["transition"], r["toState"]) for r in result["rows"]} == {
        (CHAT + "chat_bpmn#persist_user_msg", CHAT + "t_send", CHAT + "s_sending"),
    }


def test_unknown_query_name_raises():
    with pytest.raises(KeyError):
        queries.load_query("no-such-query")
    with pytest.raises(KeyError):
        queries.execute_query(get_graph(), "no-such-query", MESSAGE_SHAPE)
    # Path-traversal shape must fail on the catalog check, not the filesystem.
    with pytest.raises(KeyError):
        queries.load_query("../../etc/passwd")


def test_non_applicable_focus_returns_empty():
    result = queries.execute_query(get_graph(), "what-moves-state", MESSAGE_SHAPE)
    assert result["resultCount"] == 0
    assert result["rows"] == []
    assert "truncated" not in result


def test_is_applicable_type_rules():
    graph = get_graph()
    applicability = {
        focus: [
            name
            for name, q in queries.QUERIES.items()
            if queries.is_applicable(graph, focus, q)
        ]
        for focus in (MESSAGE_SHAPE, DB01, S_COMPOSING)
    }
    assert applicability == {
        MESSAGE_SHAPE: ["what-writes-shape"],
        DB01: ["impact-of-node"],
        S_COMPOSING: ["what-moves-state"],
    }


# --- T02: JSON endpoint tests (TestClient over viewer.app) -----------------


def _client():
    from fastapi.testclient import TestClient

    from viewer.app import app

    return TestClient(app)


def _query_url(query_name: str, focus_iri: str) -> str:
    # Same encoding convention as href_for() in viewer/app.py.
    return f"/queries/{query_name}/{quote(focus_iri, safe='')}"


def test_queries_endpoint_lists_catalog():
    resp = _client().get("/queries")
    assert resp.status_code == 200
    body = resp.json()
    assert [entry["name"] for entry in body] == EXPECTED_NAMES
    for entry in body:
        assert set(entry) == {"name", "label", "question", "focusVariable", "focusType"}
        assert all(entry[k] for k in entry)
        q = queries.QUERIES[entry["name"]]
        assert entry["focusType"] == str(q.focusType)


def test_query_endpoint_what_writes_shape():
    resp = _client().get(_query_url("what-writes-shape", MESSAGE_SHAPE))
    assert resp.status_code == 200
    body = resp.json()
    assert body["queryName"] == "what-writes-shape"
    assert body["focusIri"] == MESSAGE_SHAPE
    assert body["resultCount"] == 2
    assert {(r["event"], r["writer"]) for r in body["rows"]} == {
        (CHAT + "send_message", CHAT + "chat_bpmn#persist_user_msg"),
        (CHAT + "send_message", CHAT + "chat_bpmn#persist_response"),
    }


def test_query_endpoint_impact_of_node():
    resp = _client().get(_query_url("impact-of-node", DB01))
    assert resp.status_code == 200
    body = resp.json()
    assert body["resultCount"] == 4
    assert {r["impacted"] for r in body["rows"]} == {
        CHAT + "message_db",
        CHAT + "chat_api",
        CHAT + "chat_ui",
        CHAT + "send_message_process",
    }


def test_query_endpoint_what_moves_state():
    resp = _client().get(_query_url("what-moves-state", S_COMPOSING))
    assert resp.status_code == 200
    body = resp.json()
    assert body["resultCount"] == 1
    assert {(r["task"], r["transition"], r["toState"]) for r in body["rows"]} == {
        (CHAT + "chat_bpmn#persist_user_msg", CHAT + "t_send", CHAT + "s_sending"),
    }


def test_query_endpoint_unknown_query_404():
    resp = _client().get(_query_url("no-such-query", MESSAGE_SHAPE))
    assert resp.status_code == 404


def test_query_endpoint_non_applicable_focus_empty():
    resp = _client().get(_query_url("what-moves-state", MESSAGE_SHAPE))
    assert resp.status_code == 200
    body = resp.json()
    assert body["resultCount"] == 0
    assert body["rows"] == []


def test_query_endpoint_reports_bindings_metadata():
    resp = _client().get(_query_url("what-writes-shape", MESSAGE_SHAPE))
    assert resp.status_code == 200
    body = resp.json()
    assert body["bindings"] == {"shape": MESSAGE_SHAPE}
    assert body["columns"] == ["event", "writer"]
    assert isinstance(body["durationMs"], (int, float))


# --- T03: HTML fragment tests (catalog buttons + results table) ------------

# MessageShape carries seam:detailedBy chat_data_shapes, so /view/{MessageShape}
# auto-navigates into the shapes model (ADR-0005) and never lands on the shape
# itself. ConversationShape is a sh:NodeShape with no navigation edges — it
# self-lands, so it carries the catalog-button assertions.
CONVERSATION_SHAPE = CHAT + "ConversationShape"
ROOT_MODEL = CHAT + "chat_architecture"


def _view_fragment(iri: str):
    return _client().get(
        f"/view/{quote(iri, safe='')}", headers={"hx-request": "true"}
    )


def test_fragment_shows_query_buttons_for_shape():
    resp = _view_fragment(CONVERSATION_SHAPE)
    assert resp.status_code == 200
    html = resp.text
    assert 'id="query-catalog"' in html
    assert 'data-query-name="what-writes-shape"' in html
    assert 'hx-target="#query-results"' in html
    assert '<div id="query-results"></div>' in html


def test_fragment_hides_inapplicable_queries():
    html = _view_fragment(CONVERSATION_SHAPE).text
    assert 'data-query-name="impact-of-node"' not in html
    assert 'data-query-name="what-moves-state"' not in html


def test_fragment_no_catalog_for_untyped_element():
    # The root C4 model is a seam:Model — none of the three focus types apply.
    html = _view_fragment(ROOT_MODEL).text
    assert 'id="query-catalog"' not in html
    assert 'id="query-results"' not in html


def test_query_results_fragment_renders_table():
    from viewer.app import label as iri_label

    resp = _client().get(
        _query_url("what-writes-shape", MESSAGE_SHAPE),
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    html = resp.text
    assert 'id="query-results-table"' in html
    assert "<th>event</th>" in html
    assert "<th>writer</th>" in html
    # Cells show human-readable labels; raw IRIs appear only in href attributes.
    assert ">" + iri_label(CHAT + "send_message") + "<" in html
    assert ">" + iri_label(CHAT + "chat_bpmn#persist_user_msg") + "<" in html
    assert ">" + CHAT + "send_message<" not in html
    # ?format=html must reach the same HTML branch as the hx-request header.
    html_via_param = _client().get(
        _query_url("what-writes-shape", MESSAGE_SHAPE) + "?format=html"
    ).text
    assert 'id="query-results-table"' in html_via_param


def test_query_results_fragment_empty_state():
    resp = _client().get(
        _query_url("what-moves-state", MESSAGE_SHAPE),
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "No results" in html
    assert "query-results-table" not in html


def test_focus_types_match_model_declarations():
    """The catalog's focusType constants are the exact rdf:type declarations
    the chat-app model uses — guards against ontology-IRI drift."""
    graph = get_graph()
    expected = {
        MESSAGE_SHAPE: queries.QUERIES["what-writes-shape"].focusType,
        DB01: queries.QUERIES["impact-of-node"].focusType,
        S_COMPOSING: queries.QUERIES["what-moves-state"].focusType,
    }
    for iri, focus_type in expected.items():
        assert (URIRef(iri), RDF.type, focus_type) in graph
