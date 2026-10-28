"""Per-gap assertions for the M004 vocabulary slice.

docs/generation/golden/gaps.md lists what the chat-app graph could not say
during the golden dry run (GAP-01..GAP-22) and the ADR-0007 spike
(GAP-23..GAP-27). For each gap the slice closes, this module pins the graph
fact a generator or the runtime worker reads to produce the line: an
exact-row SPARQL query over the ontologies plus examples/chat-app/chat-app.trig
(design rule 2: every predicate must earn a query). Tests are named
test_gap_NN_<topic>.
"""

from pathlib import Path

import pytest
import rdflib

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
CHAT_APP_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"

PREFIXES = """
PREFIX :       <https://example.org/chat/>
PREFIX rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>
PREFIX sh:     <http://www.w3.org/ns/shacl#>
PREFIX hydra:  <http://www.w3.org/ns/hydra/core#>
PREFIX odrl:   <http://www.w3.org/ns/odrl/2/>
PREFIX seam:   <https://w3id.org/seams/seam#>
PREFIX arch:   <https://w3id.org/seams/arch#>
PREFIX ifml:   <https://w3id.org/seams/ifml#>
PREFIX deploy: <https://w3id.org/seams/deploy#>
PREFIX comm:   <https://w3id.org/seams/comm#>
PREFIX proc:   <https://w3id.org/seams/proc#>
PREFIX dec:    <https://w3id.org/seams/dec#>
PREFIX state:  <https://w3id.org/seams/state#>
"""


@pytest.fixture(scope="session")
def chat_model() -> rdflib.Graph:
    """Union graph of ontology/*.ttl plus every named graph of the chat-app TriG."""
    ds = rdflib.Dataset()
    for path in ONTOLOGY_FILES:
        ds.default_graph.parse(path, format="turtle")
    ds.parse(CHAT_APP_TRIG, format="trig")
    g = rdflib.Graph()
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def ask(graph: rdflib.Graph, query: str) -> bool:
    return bool(graph.query(PREFIXES + query).askAnswer)


def select(graph: rdflib.Graph, query: str) -> set[tuple]:
    return {tuple(row) for row in graph.query(PREFIXES + query)}


def test_fixture_loads_ontology_and_chat_app(chat_model):
    assert ask(chat_model, "ASK { :chat_api a arch:Container }"), "chat-app TriG not loaded"
    # The ontology half of the union is present too, not just the instance data.
    assert ask(chat_model, "ASK { seam:exposes a rdf:Property }"), "ontology/*.ttl not loaded"
    assert select(chat_model, "SELECT ?op WHERE { :chat_api seam:exposes ?op }") == {
        (rdflib.URIRef("https://example.org/chat/send_message_op"),),
        (rdflib.URIRef("https://example.org/chat/stream_events"),),
    }
