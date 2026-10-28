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


CHAT = rdflib.Namespace("https://example.org/chat/")
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"


def lit(value) -> rdflib.Literal:
    return rdflib.Literal(value)


# --- GAP-01..07: deploy vocabulary for the compose golden -------------------


def test_every_chat_container_has_exactly_one_artifact(chat_model):
    rows = select(
        chat_model,
        """SELECT ?c (COUNT(?a) AS ?n) WHERE {
               :chat_system arch:contains ?c . ?c a arch:Container .
               OPTIONAL { ?c deploy:artifact ?a }
           } GROUP BY ?c""",
    )
    assert {(c, int(n)) for c, n in rows} == {
        (CHAT.chat_ui, 1), (CHAT.chat_api, 1), (CHAT.llm_gateway, 1), (CHAT.message_db, 1),
    }


def test_gap_01_images(chat_model):
    rows = select(
        chat_model,
        """SELECT ?c ?ref ?ver WHERE {
               :chat_system arch:contains ?c .
               ?c deploy:artifact ?a . ?a a deploy:Artifact ;
                  deploy:reference ?ref ; deploy:version ?ver .
           }""",
    )
    assert rows == {
        (CHAT.chat_ui, lit("ghcr.io/example/chat-ui"), lit("latest")),
        (CHAT.chat_api, lit("ghcr.io/example/chat-api"), lit("0.3.1")),
        (CHAT.llm_gateway, lit("ghcr.io/example/llm-gateway"), lit("latest")),
        (CHAT.message_db, lit("postgres"), lit("16")),
    }


def test_gap_02_ports(chat_model):
    rows = select(
        chat_model,
        """SELECT ?c ?container ?published WHERE {
               ?c deploy:port ?p . ?p a deploy:Port ; deploy:containerPort ?container .
               OPTIONAL { ?p deploy:publishedPort ?published }
           }""",
    )
    # Unbound publishedPort (None) renders as compose `expose`; message_db has no port.
    assert rows == {
        (CHAT.chat_ui, lit(8000), lit(8080)),
        (CHAT.chat_api, lit(8000), None),
        (CHAT.llm_gateway, lit(8000), None),
    }


def test_gap_03_volumes(chat_model):
    rows = select(
        chat_model,
        """SELECT ?c ?name ?path WHERE {
               ?c deploy:volume ?v . ?v a deploy:Volume ;
                  deploy:volumeName ?name ; deploy:mountPath ?path .
           }""",
    )
    assert rows == {(CHAT.message_db, lit("message_db_data"), lit("/var/lib/postgresql/data"))}


def test_gap_04_placement_rule(chat_model):
    """Rule (deploy:placement comment): seam:deployedTo renders as
    node.labels.seams.node == <node rdfs:label>."""
    rows = select(
        chat_model,
        """SELECT ?c ?constraint WHERE {
               :chat_system arch:contains ?c .
               ?c seam:deployedTo ?node . ?node a arch:DeploymentNode ; rdfs:label ?label .
               BIND(CONCAT("node.labels.seams.node == ", STR(?label)) AS ?constraint)
           }""",
    )
    assert rows == {
        (CHAT.chat_ui, lit("node.labels.seams.node == web01")),
        (CHAT.chat_api, lit("node.labels.seams.node == app01")),
        (CHAT.llm_gateway, lit("node.labels.seams.node == app01")),
        (CHAT.message_db, lit("node.labels.seams.node == db01")),
    }
    # No honoured-placement flag was needed: the rule always applies.
    assert not ask(chat_model, "ASK { ?env deploy:honoursPlacement ?flag }")


def test_gap_05_secret_names(chat_model):
    rows = select(
        chat_model,
        """SELECT ?c ?key ?ref ?name WHERE {
               ?c deploy:configuration/deploy:binding ?b .
               ?b deploy:key ?key ; deploy:secretRef ?ref ; deploy:secretName ?name .
           }""",
    )
    assert rows == {
        (CHAT.chat_api, lit("DB_URL"),
         rdflib.URIRef("https://secrets.example.org/chat/prod/db-url"), lit("chat-prod-db-url")),
        (CHAT.chat_api, lit("LLM_API_KEY"),
         rdflib.URIRef("https://secrets.example.org/chat/prod/llm-key"), lit("chat-prod-llm-key")),
    }
    # Every secretRef binding is named, so no compose secret lacks a source.
    assert not ask(
        chat_model,
        "ASK { ?b deploy:secretRef ?ref FILTER NOT EXISTS { ?b deploy:secretName ?n } }",
    )


def test_gap_06_plain_and_derived_config(chat_model):
    plain = select(
        chat_model,
        """SELECT ?c ?key ?value WHERE {
               ?c deploy:configuration ?cfg . ?cfg a deploy:Configuration ; deploy:binding ?b .
               ?b deploy:key ?key ; deploy:value ?value .
           }""",
    )
    assert plain == {
        (CHAT.llm_gateway, lit("UPSTREAM_BASE_URL"), lit("https://api.openai.com/v1")),
        (CHAT.message_db, lit("POSTGRES_DB"), lit("chat")),
    }
    # Derived binding: value is http://<service name>:<containerPort> of the target.
    derived = select(
        chat_model,
        """SELECT ?c ?key ?url WHERE {
               ?c deploy:configuration/deploy:binding ?b .
               ?b deploy:key ?key ; deploy:serviceOf ?target .
               ?target deploy:port/deploy:containerPort ?port .
               BIND(CONCAT("http://", STRAFTER(STR(?target), STR(:)), ":", STR(?port)) AS ?url)
           }""",
    )
    assert derived == {(CHAT.chat_api, lit("LLM_GATEWAY_URL"), lit("http://llm_gateway:8000"))}


def test_gap_07_startup_and_health(chat_model):
    order = select(chat_model, "SELECT ?c ?dep WHERE { ?c deploy:dependsOn ?dep }")
    assert order == {(CHAT.chat_ui, CHAT.chat_api), (CHAT.chat_api, CHAT.message_db)}
    # depends_on comes from deploy:dependsOn alone: :chat_api arch:dependsOn
    # :llm_gateway is a design-time dependency with no startup edge.
    assert ask(chat_model, "ASK { :chat_api arch:dependsOn :llm_gateway }")
    assert not ask(chat_model, "ASK { :chat_api deploy:dependsOn :llm_gateway }")
    health = select(
        chat_model,
        """SELECT ?c ?probe ?interval WHERE {
               ?c deploy:healthcheck ?h . ?h a deploy:Healthcheck ;
                  deploy:probe ?probe ; deploy:interval ?interval .
           }""",
    )
    assert health == {(CHAT.message_db, lit("pg_isready -U postgres"), lit("5s"))}


BAD_PREFIXES = """
@prefix :       <https://example.org/bad/> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
"""

ARTIFACT_MSG = "A deploy:artifact has exactly one string deploy:reference."
PORT_MSG = "A deploy:port has exactly one integer deploy:containerPort in 1..65535."
PUBLISHED_MSG = "deploy:publishedPort is at most one integer in 1..65535."
MOUNT_MSG = "A deploy:volume has exactly one absolute deploy:mountPath."
PROBE_MSG = "A deploy:healthcheck has exactly one string deploy:probe."
BINDING_MSG = "A deploy:binding takes exactly one of deploy:value, deploy:secretRef or deploy:serviceOf."
SECRET_NAME_MSG = (
    "deploy:secretName names the platform secret for a deploy:secretRef binding; "
    "a binding with a secretName must carry a secretRef."
)


def shacl_messages(data: rdflib.Graph) -> set[str]:
    import pyshacl

    conforms, report, _ = pyshacl.validate(data, shacl_graph=str(SHAPES_FILE), inference="none")
    messages = {str(m) for m in report.objects(None, rdflib.SH.resultMessage)}
    assert conforms == (not messages)
    return messages


def test_deploy_shapes_accept_chat_app(chat_model):
    assert shacl_messages(chat_model) == set()


@pytest.mark.parametrize(
    "facts, message",
    [
        ('deploy:artifact [ a deploy:Artifact ; deploy:version "1" ]', ARTIFACT_MSG),
        ('deploy:port [ a deploy:Port ; deploy:containerPort "8000" ]', PORT_MSG),
        ("deploy:port [ a deploy:Port ; deploy:containerPort 70000 ]", PORT_MSG),
        ("deploy:port [ a deploy:Port ]", PORT_MSG),
        ("deploy:port [ a deploy:Port ; deploy:containerPort 8000 ; deploy:publishedPort 0 ]", PUBLISHED_MSG),
        ('deploy:volume [ a deploy:Volume ; deploy:volumeName "data" ]', MOUNT_MSG),
        ('deploy:volume [ a deploy:Volume ; deploy:volumeName "data" ; deploy:mountPath "var/data" ]', MOUNT_MSG),
        ('deploy:healthcheck [ a deploy:Healthcheck ; deploy:interval "5s" ]', PROBE_MSG),
        ('deploy:configuration [ deploy:binding [ deploy:key "K" ] ]', BINDING_MSG),
        ('deploy:configuration [ deploy:binding [ deploy:key "K" ; deploy:value "x" ; deploy:serviceOf :svc ] ]',
         BINDING_MSG),
        ('deploy:configuration [ deploy:binding [ deploy:key "K" ; deploy:value "x" ; deploy:secretName "n" ] ]',
         SECRET_NAME_MSG),
    ],
    ids=[
        "artifact-no-reference", "port-string", "port-out-of-range", "port-missing",
        "published-port-zero", "volume-no-mount", "volume-relative-mount", "healthcheck-no-probe",
        "binding-no-value", "binding-two-values", "secret-name-without-ref",
    ],
)
def test_deploy_shapes_have_teeth(facts, message):
    """Each malformed deploy fact trips its own deploy shape, and nothing else."""
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{BAD_PREFIXES}\n:svc a arch:Container ; {facts} .", format="turtle")
    assert shacl_messages(data) == {message}
