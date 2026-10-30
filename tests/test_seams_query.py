"""seams SPARQL helper and canned questions (M010/S03 T03)."""

from importlib import resources
from pathlib import Path

import pytest
import seams
from rdflib import Literal, URIRef
from seams.sparql import PREFIXES, load_question, question_names

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"
DOCS_QUERIES = ROOT / "docs/queries"

C = "https://example.org/chat/"


@pytest.fixture(scope="module")
def chat() -> seams.Model:
    return seams.load(CHAT)


def test_question_names_match_docs_queries():
    assert question_names() == sorted(p.stem for p in DOCS_QUERIES.glob("*.rq"))
    assert "complexity" not in "".join(question_names())


@pytest.mark.parametrize("name", sorted(p.stem for p in DOCS_QUERIES.glob("*.rq")))
def test_bundled_question_is_byte_identical_to_docs(name: str):
    bundled = (resources.files("seams") / "queries" / f"{name}.rq").read_bytes()
    assert bundled == (DOCS_QUERIES / f"{name}.rq").read_bytes()
    assert load_question(name) == (DOCS_QUERIES / f"{name}.rq").read_text(encoding="utf-8")


def test_impact_of_node_matches_viewer(chat: seams.Model):
    rows = chat.question("impact-of-node", node=":db01")
    # The same rows tests/test_viewer_queries.py pins for viewer.queries.execute_query.
    assert [r["impacted"] for r in rows] == [
        URIRef(C + "ConversationShape"),
        URIRef(C + "MessageShape"),
        URIRef(C + "chat_api"),
        URIRef(C + "chat_ui"),
        URIRef(C + "message_db"),
        URIRef(C + "send_message_process"),
    ]
    assert chat.question("impact-of-node", node=URIRef(C + "db01")) == rows
    assert chat.question("impact-of-node", node=C + "db01") == rows

    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from viewer.app import get_graph
    from viewer.queries import execute_query

    viewer_rows = execute_query(get_graph(), "impact-of-node", C + "db01")["rows"]
    assert {str(r["impacted"]) for r in rows} == {r["impacted"] for r in viewer_rows}


def test_what_writes_shape(chat: seams.Model):
    rows = chat.question("what-writes-shape", shape=":MessageShape")
    assert [(r["event"], r["writer"]) for r in rows] == [
        (URIRef(C + "send_message"), URIRef(C + "chat_bpmn#persist_response")),
        (URIRef(C + "send_message"), URIRef(C + "chat_bpmn#persist_user_msg")),
    ]


def test_sparql_needs_no_prefix_lines(chat: seams.Model):
    rows = chat.sparql("SELECT ?p WHERE { ?p a ifml:ViewContainer }")
    assert rows == [{"p": URIRef(C + "chat_page")}]
    assert set(PREFIXES) >= {"seam", "comm", "dec", "proc", "state", "hydra", "odrl", "deploy", "ifml", "arch"}
    assert set(PREFIXES) >= {"rdf", "rdfs", "sh", "xsd"}


def test_sparql_order_by_wins_over_default_sort(chat: seams.Model):
    query = "SELECT ?c WHERE { ?c a arch:Container }"
    default = chat.sparql(query)
    assert default == sorted(default, key=lambda r: str(r["c"]))
    assert len(default) > 1
    assert chat.sparql(query + " ORDER BY DESC(?c)") == default[::-1]


def test_sparql_literal_binding(chat: seams.Model):
    rows = chat.sparql("SELECT ?s WHERE { ?s rdfs:label ?l }", l=Literal("no such label"))
    assert rows == []


@pytest.mark.parametrize("name", ["../secrets", "no-such", "", "Impact-Of-Node", "impact-of-node.rq", "/etc/passwd"])
def test_unknown_question_raises(chat: seams.Model, name: str):
    with pytest.raises(KeyError, match="available: c4-l1-rollup"):
        chat.question(name)


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
        "# comment\nPREFIX ex: <https://example.org/x#>\n  delete where { ?s ?p ?o }",
        "DROP ALL",
        "LOAD <file:///etc/passwd>",
    ],
)
def test_update_is_refused(chat: seams.Model, query: str):
    before = len(chat.ds)
    with pytest.raises(ValueError, match="read-only"):
        chat.sparql(query)
    assert len(chat.ds) == before


def test_unbound_prefix_in_binding_raises(chat: seams.Model):
    with pytest.raises(seams.ResolutionError):
        chat.question("impact-of-node", node="nope:db01")


def test_non_select_rows_refused(chat: seams.Model):
    with pytest.raises(ValueError, match="SELECT"):
        chat.sparql("ASK { ?s ?p ?o }")
