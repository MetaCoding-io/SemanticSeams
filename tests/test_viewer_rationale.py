"""The inspector's Why section (backlog X8, M033/S02, ADR-0045).

GET /view of an element some chat-app arch:DecisionRecord references renders
<section id="why"> with the record's identifier and document link; an element
no record references renders none. viewer.rationale.why is also tested on
inline graphs for sorting, the fallbacks and the records it skips.
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path
from urllib.parse import quote

import pytest
from rdflib import RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402
from viewer.rationale import WhyRow, why  # noqa: E402

CHAT = Namespace("https://example.org/chat/")
ARCH = Namespace("https://w3id.org/seams/arch#")
EX = Namespace("https://example.org/why/")
ADR = "https://github.com/MetaCoding-io/SemanticSeams/blob/main/docs/adr/"


@pytest.fixture(autouse=True)
def clear_conformance_cache():
    validation._clear_cache()  # MEM010: id()-keyed cache
    yield


def _html(iri: URIRef) -> str:
    from fastapi.testclient import TestClient

    resp = TestClient(viewer_app.app).get(f"/view/{quote(str(iri), safe='')}", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    return resp.text


# --- the chat app through the viewer ---------------------------------------


def test_chat_app_records_are_read_from_the_model():
    assert why(viewer_app.get_graph(), str(CHAT.message_db)) == [
        WhyRow(
            "ADR-0011",
            "Storage Resolution — the Runtime Stores Data Where the Model Says",
            ADR + "0011-storage-resolution.md",
            str(CHAT.adr_0011),
        ),
        WhyRow(
            "ADR-0038", "Shared Stream Channel and Replicas", ADR + "0038-shared-stream-channel.md", str(CHAT.adr_0038)
        ),
    ]


def test_referenced_element_shows_the_why_section():
    """ConversationShape self-lands (MEM012) and ADR-0011 references it."""
    html = _html(CHAT.ConversationShape)
    assert '<section id="why" class="why" aria-label="Why">' in html
    assert f'data-record="{CHAT.adr_0011}"' in html
    assert f'<a href="{ADR}0011-storage-resolution.md"><code>ADR-0011</code></a>' in html
    assert escape("Storage Resolution — the Runtime Stores Data Where the Model Says") in html


def test_unreferenced_element_has_no_why_section():
    """db01 self-lands (MEM012) and no record references it."""
    html = _html(CHAT.db01)
    assert 'id="why"' not in html
    assert 'aria-label="Why"' not in html


def test_why_section_is_per_view_and_in_the_fragment():
    """Per-view UI lives in fragment.html (MEM009), so an htmx swap carries it too."""
    from fastapi.testclient import TestClient

    resp = TestClient(viewer_app.app).get(
        f"/view/{quote(str(CHAT.ConversationShape), safe='')}", headers={"Accept": "text/html", "HX-Request": "true"}
    )
    assert resp.status_code == 200
    assert '<section id="why" class="why" aria-label="Why">' in resp.text


# --- why() on inline graphs ------------------------------------------------


def _record(
    g: Graph, record: URIRef | BNode, identifier: str | None, label: str | None, doc: str | None, *refs: URIRef
):
    g.add((record, RDF.type, ARCH.DecisionRecord))
    if identifier is not None:
        g.add((record, DCTERMS.identifier, Literal(identifier)))
    if label is not None:
        g.add((record, RDFS.label, Literal(label)))
    if doc is not None:
        g.add((record, RDFS.seeAlso, URIRef(doc)))
    for ref in refs:
        g.add((record, DCTERMS.references, ref))


def test_rows_sort_by_identifier_then_iri():
    g = Graph()
    _record(g, EX.r2, "ADR-0002", "Second", "https://example.org/2.md", EX.thing)
    _record(g, EX.r1b, "ADR-0001", "First again", None, EX.thing)
    _record(g, EX.r1a, "ADR-0001", "First", "https://example.org/1.md", EX.thing, EX.other)
    assert why(g, str(EX.thing)) == [
        WhyRow("ADR-0001", "First", "https://example.org/1.md", str(EX.r1a)),
        WhyRow("ADR-0001", "First again", None, str(EX.r1b)),
        WhyRow("ADR-0002", "Second", "https://example.org/2.md", str(EX.r2)),
    ]
    assert why(g, str(EX.other)) == [WhyRow("ADR-0001", "First", "https://example.org/1.md", str(EX.r1a))]


def test_unreferenced_focus_has_no_rows():
    g = Graph()
    _record(g, EX.r1, "ADR-0001", "First", None, EX.thing)
    assert why(g, str(EX.nothing)) == []
    assert why(Graph(), str(EX.thing)) == []


def test_record_missing_label_and_identifier_falls_back_to_its_iri():
    """A model breaking DecisionRecordShape still says why, naming the record by IRI."""
    g = Graph()
    _record(g, EX.bare, None, None, None, EX.thing)
    assert why(g, str(EX.thing)) == [WhyRow(str(EX.bare), str(EX.bare), None, str(EX.bare))]


def test_literal_see_also_is_not_a_link():
    g = Graph()
    _record(g, EX.r1, "ADR-0001", "First", None, EX.thing)
    g.add((EX.r1, RDFS.seeAlso, Literal("docs/adr/0001.md")))
    assert why(g, str(EX.thing)) == [WhyRow("ADR-0001", "First", None, str(EX.r1))]


def test_untyped_referrer_and_blank_node_record_are_skipped():
    """dcterms:references from anything but an IRI arch:DecisionRecord is not a record."""
    g = Graph()
    g.add((EX.paper, DCTERMS.references, EX.thing))
    g.add((EX.paper, DCTERMS.identifier, Literal("ADR-0009")))
    _record(g, BNode(), "ADR-0003", "Blank", None, EX.thing)
    assert why(g, str(EX.thing)) == []
