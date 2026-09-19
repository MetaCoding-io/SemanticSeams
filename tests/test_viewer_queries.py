"""Tests for the canned query catalog + engine (S03 T01).

Execution-level tests run viewer.queries against the real viewer Dataset
(viewer.app.get_graph(): chat-app.trig only, default_union=True) and pin the
same chat-app benchmark rows as tests/test_acceptance.py lines 309-343 —
proving the instance-level property paths need no ontology union.
"""

import sys
from pathlib import Path

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
