"""Per-gap assertions for the M004 vocabulary slice.

docs/generation/golden/gaps.md lists what the chat-app graph could not say
during the golden dry run (GAP-01..GAP-22) and the ADR-0007 spike
(GAP-23..GAP-27). For each gap the slice closes, this module pins the graph
fact a generator or the runtime worker reads to produce the line: an
exact-row SPARQL query over the ontologies plus examples/chat-app/chat-app.trig
(design rule 2: every predicate must earn a query). Tests are named
test_gap_NN_<topic>.
"""

import re
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
PREFIX dash:   <http://datashapes.org/dash#>
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
        (rdflib.URIRef("https://example.org/chat/list_conversations_op"),),
        (rdflib.URIRef("https://example.org/chat/message_thread_op"),),
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
        (CHAT.chat_ui, 1),
        (CHAT.chat_api, 1),
        (CHAT.llm_gateway, 1),
        (CHAT.message_db, 1),
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
        (
            CHAT.chat_api,
            lit("DB_URL"),
            rdflib.URIRef("https://secrets.example.org/chat/prod/db-url"),
            lit("chat-prod-db-url"),
        ),
        (
            CHAT.chat_api,
            lit("LLM_API_KEY"),
            rdflib.URIRef("https://secrets.example.org/chat/prod/llm-key"),
            lit("chat-prod-llm-key"),
        ),
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
        (
            'deploy:configuration [ deploy:binding [ deploy:key "K" ; deploy:value "x" ; deploy:serviceOf :svc ] ]',
            BINDING_MSG,
        ),
        (
            'deploy:configuration [ deploy:binding [ deploy:key "K" ; deploy:value "x" ; deploy:secretName "n" ] ]',
            SECRET_NAME_MSG,
        ),
    ],
    ids=[
        "artifact-no-reference",
        "port-string",
        "port-out-of-range",
        "port-missing",
        "published-port-zero",
        "volume-no-mount",
        "volume-relative-mount",
        "healthcheck-no-probe",
        "binding-no-value",
        "binding-two-values",
        "secret-name-without-ref",
    ],
)
def test_deploy_shapes_have_teeth(facts, message):
    """Each malformed deploy fact trips its own deploy shape, and nothing else."""
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{BAD_PREFIXES}\n:svc a arch:Container ; {facts} .", format="turtle")
    assert shacl_messages(data) == {message}


# --- GAP-08/11/15/18/21: communication contract for the route and page goldens


def test_gap_08_paths(chat_model):
    rows = select(
        chat_model,
        """SELECT ?op ?method ?template ?variable ?property WHERE {
               ?op comm:path ?t . ?t a hydra:IriTemplate ; hydra:template ?template .
               OPTIONAL { ?op hydra:method ?method }
               OPTIONAL { ?t hydra:mapping ?m . ?m a hydra:IriTemplateMapping ;
                             hydra:variable ?variable ; hydra:property ?property }
           }""",
    )
    messages = "/conversations/{conversation}/messages"
    assert rows == {
        (CHAT.send_message_op, lit("POST"), lit(messages), lit("conversation"), CHAT.id),
        (CHAT.message_thread_op, lit("GET"), lit(messages), lit("conversation"), CHAT.id),
        (CHAT.list_conversations_op, lit("GET"), lit("/conversations"), None, None),
        (CHAT.completion_op, lit("POST"), lit("/v1/chat/completions"), None, None),
        (CHAT.stream_events, None, lit("/conversations/{conversation}/stream"), lit("conversation"), CHAT.id),
    }
    # Every template variable is mapped: no {name} in a template lacks a hydra:variable.
    for _op, _method, template, variable, _prop in rows:
        names = set(re.findall(r"{(\w+)}", str(template)))
        assert names == ({str(variable)} if variable else set()), template


def test_gap_11_read_operations(chat_model):
    rows = select(
        chat_model,
        """SELECT ?op ?shape ?kind WHERE {
               :chat_api seam:exposes ?op . :chat_ui seam:consumes ?op .
               ?op a hydra:Operation ; hydra:method "GET" ;
                   seam:returnsShape ?shape ; seam:mediaKind ?kind .
           }""",
    )
    assert rows == {
        (CHAT.list_conversations_op, CHAT.ConversationShape, rdflib.URIRef("https://w3id.org/seams/seam#UIFragment")),
        (CHAT.message_thread_op, CHAT.MessageShape, rdflib.URIRef("https://w3id.org/seams/seam#UIFragment")),
    }
    # Identifier convention: the shape addressed in the URL has exactly one string :id.
    ident = select(
        chat_model,
        """SELECT ?shape ?dt ?min ?max WHERE {
               ?shape sh:property ?p . ?p sh:path :id ; sh:datatype ?dt ;
                      sh:minCount ?min ; sh:maxCount ?max .
           }""",
    )
    assert ident == {(CHAT.ConversationShape, rdflib.XSD.string, lit(1), lit(1))}
    # The component -> read-operation link is seam:rendersComponent (T04), not a new term.
    assert not ask(chat_model, "ASK { ?c seam:readsVia ?op }")


def test_gap_15_channel_transport(chat_model):
    rows = select(
        chat_model,
        """SELECT ?ch ?transport ?event ?template WHERE {
               :chat_api seam:exposes ?ch . :chat_ui seam:consumes ?ch .
               ?ch a comm:Channel ; comm:transport ?transport ; comm:eventName ?event ;
                   comm:path/hydra:template ?template .
               ?transport a comm:Transport .
           }""",
    )
    comm = rdflib.Namespace("https://w3id.org/seams/comm#")
    assert rows == {(CHAT.stream_events, comm.SSE, lit("token"), lit("/conversations/{conversation}/stream"))}
    # Token events are declared (D046): the invoking service task itself
    # seam:publishesTo the channel, beside the throw event that ends the stream.
    streamed = select(
        chat_model,
        """SELECT ?task ?ch WHERE {
               ?task a proc:ServiceTask ; seam:invokes ?op ; seam:publishesTo ?ch .
               ?ch a comm:Channel .
           }""",
    )
    bpmn = rdflib.Namespace("https://example.org/chat/chat_bpmn#")
    # persist_user_msg invokes :send_message_op but declares no channel, so it does not stream.
    assert streamed == {(bpmn.invoke_llm, CHAT.stream_events)}


PUBLISHES_TO_MSG = "Only a proc:MessageThrowEvent or a proc:ServiceTask seam:publishesTo a channel (D046)."
PUB_PREFIXES = """
@prefix :      <https://example.org/bad/> .
@prefix comm:  <https://w3id.org/seams/comm#> .
@prefix proc:  <https://w3id.org/seams/proc#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
:ch a comm:Channel .
"""


@pytest.mark.parametrize(
    "facts, messages",
    [
        (":t a proc:ServiceTask ; seam:publishesTo :ch .", set()),
        (":e a proc:MessageThrowEvent ; seam:publishesTo :ch .", set()),
        (":t a proc:UserTask ; seam:publishesTo :ch .", {PUBLISHES_TO_MSG}),
        (":t seam:publishesTo :ch .", {PUBLISHES_TO_MSG}),
    ],
    ids=["service-task", "throw-event", "user-task", "untyped-element"],
)
def test_publishes_to_subject_is_throw_event_or_service_task(facts, messages):
    """D046: seam:publishesTo's subject is a message throw event or a service
    task (the delta publisher); anything else fails conformance."""
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{PUB_PREFIXES}\n{facts}", format="turtle")
    assert shacl_messages(data) == messages


def test_gap_18_request_encoding(chat_model):
    rows = select(
        chat_model,
        """SELECT ?op ?method ?media WHERE {
               ?op a hydra:Operation ; hydra:method ?method .
               OPTIONAL { ?op comm:requestMediaType ?media }
           }""",
    )
    assert rows == {
        (CHAT.send_message_op, lit("POST"), lit("application/x-www-form-urlencoded")),
        (CHAT.completion_op, lit("POST"), lit("application/json")),
        (CHAT.list_conversations_op, lit("GET"), None),
        (CHAT.message_thread_op, lit("GET"), None),
    }


def test_gap_21_handler_names(chat_model):
    """Rule (comm.ttl comment): identifier = IRI local name minus a trailing _op."""
    exposed = select(chat_model, "SELECT ?x WHERE { :chat_api seam:exposes ?x }")
    names = {re.sub(r"_op$", "", str(x).removeprefix(str(CHAT))) for (x,) in exposed}
    assert names == {"send_message", "list_conversations", "message_thread", "stream_events"}
    assert all(n.isidentifier() for n in names)
    # The rule needs no term.
    assert not ask(chat_model, "ASK { ?x seam:codeName ?name }")


# --- GAP-09/10/17/19/20: UI seams for the page and route goldens -------------

IFML = rdflib.Namespace("https://w3id.org/seams/ifml#")


def test_gap_09_event_submits_to_operation(chat_model):
    """Which route does this UI event call, and which policies must it enforce?"""
    rows = select(
        chat_model,
        """SELECT ?event ?op ?method ?template ?policy WHERE {
               ?event a ifml:Event ; seam:submitsTo ?op .
               ?op a hydra:Operation ; hydra:method ?method ;
                   comm:path/hydra:template ?template .
               OPTIONAL { ?op seam:governedBy ?policy }
           }""",
    )
    assert rows == {
        (
            CHAT.send_message,
            CHAT.send_message_op,
            lit("POST"),
            lit("/conversations/{conversation}/messages"),
            CHAT.user_send_policy,
        ),
    }
    # The event still names the process it starts; the operation's handler starts it.
    assert ask(chat_model, "ASK { :send_message seam:triggers :send_message_process }")


def test_gap_10_swap_and_trigger(chat_model):
    triggers = select(chat_model, "SELECT ?event ?dom WHERE { ?event a ifml:Event ; ifml:trigger ?dom }")
    assert triggers == {
        (CHAT.select_conversation, lit("click")),
        (CHAT.send_message, lit("submit")),
    }
    # Swap rule (ifml:swap comment): Replace targets #<component>, Append/Prepend
    # targets #<component>_items.
    flows = select(
        chat_model,
        """SELECT ?flow ?event ?swap ?target WHERE {
               ?flow a ifml:NavigationFlow ; ifml:source ?event ; ifml:target ?c ; ifml:swap ?swap .
               BIND(CONCAT("#", STRAFTER(STR(?c), STR(:)),
                           IF(?swap = ifml:Replace, "", "_items")) AS ?target)
           }""",
    )
    assert flows == {
        (CHAT.select_to_thread, CHAT.select_conversation, IFML.Replace, lit("#message_thread")),
        (CHAT.send_to_thread, CHAT.send_message, IFML.Append, lit("#message_thread_items")),
    }
    # Channel rule: a consumed channel subscription appends; no flow lands it.
    assert select(chat_model, "SELECT ?ch WHERE { :chat_ui seam:consumes ?ch . ?ch a comm:Channel }") == {
        (CHAT.stream_events,),
    }
    assert not ask(chat_model, "ASK { ?flow ifml:source :stream_events }")


def test_gap_17_page_route_and_title(chat_model):
    rows = select(
        chat_model,
        """SELECT ?page ?path ?title WHERE {
               ?page a ifml:ViewContainer ; ifml:isLandmark true ;
                     ifml:path ?path ; ifml:title ?title .
           }""",
    )
    assert rows == {(CHAT.chat_page, lit("/"), rdflib.Literal("Chat", lang="en"))}
    # The user-facing title is not the modeller label.
    assert ask(chat_model, 'ASK { :chat_page rdfs:label "Chat Page" }')


def test_gap_19_renders_component(chat_model):
    """Operation -> component -> swap of the flow that lands it -> partial name."""
    rows = select(
        chat_model,
        """SELECT ?op ?component ?swap ?partial WHERE {
               :chat_api seam:exposes ?op .
               ?op seam:mediaKind seam:UIFragment ; seam:rendersComponent ?component .
               ?component a/rdfs:subClassOf* ifml:ViewComponent .
               # The flow that lands ?op's response: the one whose event submits
               # to ?op, or, for a GET, one whose event submits to nothing.
               OPTIONAL { ?flow ifml:target ?component ; ifml:swap ?swap ; ifml:source ?event .
                          FILTER(EXISTS { ?event seam:submitsTo ?op }
                                 || (NOT EXISTS { ?event seam:submitsTo ?any }
                                     && EXISTS { ?op hydra:method "GET" })) }
               BIND(CONCAT(STRAFTER(STR(?component), STR(:)),
                           IF(BOUND(?swap) && ?swap != ifml:Replace, "_item", ""), ".html") AS ?partial)
           }""",
    )
    assert rows == {
        (CHAT.send_message_op, CHAT.message_thread, IFML.Append, lit("message_thread_item.html")),
        (CHAT.message_thread_op, CHAT.message_thread, IFML.Replace, lit("message_thread.html")),
        # Loaded with the page: no flow lands it, so it renders the whole component.
        (CHAT.list_conversations_op, CHAT.conversation_list, None, lit("conversation_list.html")),
    }
    # GAP-11's component -> read-operation link is the inverse.
    reads = select(
        chat_model,
        """SELECT ?component ?op WHERE {
               ?component seam:reads ?shape . ?op seam:rendersComponent ?component ;
                   hydra:method "GET" ; seam:returnsShape ?shape .
           }""",
    )
    assert reads == {
        (CHAT.conversation_list, CHAT.list_conversations_op),
        (CHAT.message_thread, CHAT.message_thread_op),
    }


def test_gap_20_policy_on_operation(chat_model):
    rows = select(
        chat_model,
        """SELECT ?op ?policy ?target ?action ?assignee WHERE {
               ?op a hydra:Operation ; seam:governedBy ?policy .
               ?policy a odrl:Policy ; odrl:permission ?perm .
               ?perm a odrl:Permission ; odrl:target ?target ;
                     odrl:action ?action ; odrl:assignee ?assignee .
           }""",
    )
    odrl = rdflib.Namespace("http://www.w3.org/ns/odrl/2/")
    assert rows == {
        (CHAT.send_message_op, CHAT.user_send_policy, CHAT.send_message_op, odrl.use, CHAT.authenticated_user),
    }
    # The route's policy agrees with the event's: derived through seam:submitsTo.
    assert ask(
        chat_model,
        "ASK { :send_message seam:governedBy ?p ; seam:submitsTo ?op . ?op seam:governedBy ?p }",
    )


UI_PREFIXES = """
@prefix :      <https://example.org/bad/> .
@prefix arch:  <https://w3id.org/seams/arch#> .
@prefix ifml:  <https://w3id.org/seams/ifml#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
"""


@pytest.mark.parametrize(
    "facts, message",
    [
        (
            ":e a arch:Container ; seam:submitsTo :op . :op a hydra:Operation .",
            "Only an ifml:Event seam:submitsTo an operation.",
        ),
        (":e a ifml:Event ; seam:submitsTo :c . :c a arch:Container .", "seam:submitsTo points at a hydra:Operation."),
        (
            ":e a ifml:Event ; seam:rendersComponent :v . :v a ifml:List .",
            "Only a hydra:Operation seam:rendersComponent.",
        ),
        (
            ":op a hydra:Operation ; seam:rendersComponent :p . :p a ifml:ViewContainer .",
            "seam:rendersComponent points at an ifml:ViewComponent.",
        ),
        (
            ":f a ifml:NavigationFlow ; ifml:swap :sideways .",
            "ifml:swap is at most one of ifml:Replace, ifml:Append or ifml:Prepend.",
        ),
        (
            ":f a ifml:NavigationFlow ; ifml:swap ifml:Replace , ifml:Append .",
            "ifml:swap is at most one of ifml:Replace, ifml:Append or ifml:Prepend.",
        ),
        (":f a ifml:DataFlow ; ifml:swap ifml:Replace .", "Only an ifml:NavigationFlow carries ifml:swap."),
        (":p ifml:boundTo :content .", "Only an ifml:Parameter is ifml:boundTo a property."),
        (":p a ifml:Parameter ; ifml:boundTo :content , :role .", "ifml:boundTo names at most one property IRI."),
        (':p a ifml:Parameter ; ifml:boundTo "content" .', "ifml:boundTo names at most one property IRI."),
    ],
    ids=[
        "submits-from-non-event",
        "submits-to-non-operation",
        "renders-from-non-operation",
        "renders-non-component",
        "swap-unknown-value",
        "swap-two-values",
        "swap-on-data-flow",
        "bound-from-non-parameter",
        "bound-to-two",
        "bound-to-literal",
    ],
)
def test_ui_seam_shapes_have_teeth(facts, message):
    """Each malformed UI seam fact trips its own shape, and nothing else."""
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{UI_PREFIXES}\n{facts}", format="turtle")
    assert shacl_messages(data) == {message}


# GAP-12/13/14/16: form fields and data shapes (T05).

DASH = rdflib.Namespace("http://datashapes.org/dash#")


def test_gap_12_form_fields(chat_model):
    """Form rule: inputs only for properties a form parameter is ifml:boundTo."""
    entered = select(
        chat_model,
        """SELECT ?form ?param ?path WHERE {
               ?form a ifml:Form ; seam:writes ?shape ; ifml:hasParameter ?param .
               ?param ifml:boundTo ?path .
               ?shape sh:property/sh:path ?path .
           }""",
    )
    assert entered == {(CHAT.compose_form, CHAT.message_input, CHAT.content)}
    system_set = select(
        chat_model,
        """SELECT ?path WHERE {
               :compose_form seam:writes ?shape .
               ?shape sh:property/sh:path ?path .
               FILTER NOT EXISTS { :compose_form ifml:hasParameter/ifml:boundTo ?path }
           }""",
    )
    assert system_set == {(CHAT.role,), (CHAT.status,), (CHAT.timestamp,)}
    required = select(
        chat_model,
        """SELECT ?path WHERE {
               :MessageShape sh:property [ sh:path ?path ; sh:minCount ?min ] .
               FILTER(?min >= 1)
           }""",
    )
    assert required == {(CHAT.content,)}
    # Every boundTo lands on a property of a shape its own form writes.
    assert not ask(
        chat_model,
        """ASK { ?form ifml:hasParameter ?param . ?param ifml:boundTo ?path .
                 FILTER NOT EXISTS { ?form seam:writes/sh:property/sh:path ?path } }""",
    )


def test_gap_13_field_presentation(chat_model):
    rows = select(
        chat_model,
        """SELECT ?path ?order ?max ?editor WHERE {
               :MessageShape sh:property ?p .
               ?p sh:path ?path ; sh:order ?order .
               OPTIONAL { ?p sh:maxLength ?max }
               OPTIONAL { ?p dash:editor ?editor }
           }""",
    )
    assert rows == {
        (CHAT.content, lit(0), lit(16000), DASH.TextAreaEditor),
        (CHAT.role, lit(1), None, None),
        (CHAT.status, lit(2), None, None),
        (CHAT.timestamp, lit(3), None, None),
    }


def test_gap_14_status_values(chat_model):
    """sh:in on :status equals the state labels of the shape's lifecycle machine."""
    allowed = select(
        chat_model,
        """SELECT ?v WHERE {
               :MessageShape sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:in ?list ] .
               ?list rdf:rest*/rdf:first ?v .
           }""",
    )
    labels = select(
        chat_model,
        """SELECT ?label WHERE {
               :MessageShape seam:lifecycle ?machine .
               ?machine state:hasState/rdfs:label ?label .
           }""",
    )
    assert allowed == labels
    assert allowed == {(lit(v),) for v in ("composing", "sending", "streaming", "complete", "failed")}


def test_gap_16_state_guard(chat_model):
    """Guard rule: component -> reads shape -> lifecycle -> state label -> template variable."""
    rows = select(
        chat_model,
        """SELECT ?component ?var ?label WHERE {
               ?component seam:visibleWhen ?state ; seam:reads ?shape .
               ?shape seam:lifecycle ?machine .
               ?machine state:hasState ?state .
               ?state rdfs:label ?label .
               BIND(LCASE(STRAFTER(STR(?shape), STR(:))) AS ?local)
               BIND(CONCAT(IF(STRENDS(?local, "shape"),
                              SUBSTR(?local, 1, STRLEN(?local) - 5), ?local), "_state") AS ?var)
           }""",
    )
    assert rows == {
        (CHAT.message_thread, lit("message_state"), lit(label))
        for label in ("composing", "sending", "streaming", "complete")
    }
    # Every guard resolves through that chain: none names a state outside the
    # lifecycle of a shape its component reads.
    assert not ask(
        chat_model,
        """ASK { ?component seam:visibleWhen ?state .
                 FILTER NOT EXISTS { ?component seam:reads/seam:lifecycle/state:hasState ?state } }""",
    )


# --- GAP-28: component order within a ViewContainer (M004/S04) ---------------


def test_gap_28_component_order(chat_model):
    """Generators emit a container's components by ascending ifml:order."""
    rows = select(
        chat_model,
        """SELECT ?container ?component ?order WHERE {
               ?container a ifml:ViewContainer ; ifml:contains ?component .
               ?component ifml:order ?order .
           }""",
    )
    assert rows == {
        (CHAT.chat_page, CHAT.conversation_list, lit(0)),
        (CHAT.chat_page, CHAT.message_thread, lit(1)),
        (CHAT.chat_page, CHAT.compose_form, lit(2)),
    }
    # Every component a container holds has an order, so none falls back to
    # graph iteration order.
    assert not ask(
        chat_model,
        """ASK { ?container a ifml:ViewContainer ; ifml:contains ?c .
                 ?c a/rdfs:subClassOf* ifml:ViewComponent .
                 FILTER NOT EXISTS { ?c ifml:order ?n } }""",
    )


ORDER_MSG = "ifml:order is at most one xsd:integer per component."
ORDER_UNIQUE_MSG = "ifml:order is unique among the components of one ViewContainer."


@pytest.mark.parametrize(
    "facts, message",
    [
        (
            ":page a ifml:ViewContainer ; ifml:contains :a , :b . "
            ":a a ifml:List ; ifml:order 0 . :b a ifml:Form ; ifml:order 0 .",
            ORDER_UNIQUE_MSG,
        ),
        (':a a ifml:List ; ifml:order "0" .', ORDER_MSG),
        (":a a ifml:List ; ifml:order 0 , 1 .", ORDER_MSG),
        (":a a ifml:List ; ifml:order 1.5 .", ORDER_MSG),
        (":p a ifml:ViewContainer ; ifml:order 0 .", "Only an ifml:ViewComponent carries ifml:order."),
    ],
    ids=["order-duplicate-in-container", "order-string", "order-two-values", "order-decimal", "order-on-container"],
)
def test_order_shape_has_teeth(facts, message):
    """Each malformed ifml:order fact trips its own shape, and nothing else."""
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{UI_PREFIXES}\n{facts}", format="turtle")
    assert shacl_messages(data) == {message}


def test_order_shape_allows_equal_orders_in_different_containers():
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(
        data=f"""{UI_PREFIXES}
            :p1 a ifml:ViewContainer ; ifml:contains :a . :a a ifml:List ; ifml:order 0 .
            :p2 a ifml:ViewContainer ; ifml:contains :b . :b a ifml:List ; ifml:order 0 .""",
        format="turtle",
    )
    assert shacl_messages(data) == set()


# --- GAP-22..27: runtime bindings the ADR-0007 worker needs ------------------

ROUTING_DMN = ROOT / "examples" / "chat-app" / "routing.dmn"
DMN_NS = {"dmn": "https://www.omg.org/spec/DMN/20191111/MODEL/"}


def dmn_root():
    import xml.etree.ElementTree as ET

    return ET.parse(ROUTING_DMN).getroot()


def test_gap_22_correlation_key(chat_model):
    """The correlation key is an IFML parameter named like the submitted operation's path variable."""
    rows = select(
        chat_model,
        """SELECT ?process ?key ?var WHERE {
               ?event seam:triggers ?process ; seam:submitsTo ?op .
               ?process proc:correlationKey ?key .
               ?key a ifml:Parameter ; rdfs:label ?var .
               ?op comm:path/hydra:mapping/hydra:variable ?var .
           }""",
    )
    assert rows == {(CHAT.send_message_process, CHAT.conversation, lit("conversation"))}
    # The executing container is the one exposing that operation.
    assert ask(
        chat_model,
        "ASK { ?c seam:executes :send_message_process ; seam:exposes :send_message_op }",
    )


def test_gap_23_decision_payload_element(chat_model):
    rows = select(
        chat_model,
        """SELECT ?decision ?id ?payload WHERE {
               ?task seam:decidedBy ?decision .
               ?decision dec:payloadElement ?id ; seam:inModel ?model .
               ?model seam:notation seam:DMN ; seam:renderPayload ?payload .
           }""",
    )
    assert {(decision, pid) for decision, pid, _ in rows} == {(CHAT.routing_decision, lit("routing_decision"))}
    assert [str(payload).rsplit("/", 1)[-1] for _, _, payload in rows] == [ROUTING_DMN.name]
    # The payload declares exactly that decision id: graph and DMN cannot drift.
    ids = {d.get("id") for d in dmn_root().findall("dmn:decision", DMN_NS)}
    assert ids == {"routing_decision"}


def test_gap_24_decision_inputs(chat_model):
    rows = select(
        chat_model,
        """SELECT ?var ?path ?measure WHERE {
               :routing_decision dec:input ?b .
               ?b a dec:InputBinding ; dec:variable ?var ; dec:fromPath ?path .
               OPTIONAL { ?b dec:measure ?measure }
           }""",
    )
    assert rows == {
        (lit("message_role"), CHAT.role, None),
        (lit("message_length"), CHAT.content, rdflib.URIRef("https://w3id.org/seams/dec#Length")),
    }
    # Every bound path is a property of a shape the decision reads.
    assert not ask(
        chat_model,
        """ASK { ?d dec:input/dec:fromPath ?path .
                 FILTER NOT EXISTS { ?d seam:reads/sh:property/sh:path ?path } }""",
    )
    # The DMN table's inputExpression texts are exactly the bound variables.
    texts = {
        t.text.strip()
        for t in dmn_root().findall(
            "dmn:decision[@id='routing_decision']/dmn:decisionTable/dmn:input/dmn:inputExpression/dmn:text", DMN_NS
        )
    }
    assert texts == {str(r[0]) for r in rows}


def test_gap_25_decision_output(chat_model):
    rows = select(
        chat_model,
        """SELECT ?var ?pvar WHERE {
               :routing_decision dec:output [ a dec:OutputBinding ; dec:variable ?var ; dec:processVariable ?pvar ] .
           }""",
    )
    assert rows == {(lit("Provider"), lit("provider"))}
    # The DMN output has no name attribute, so its label is the result key.
    outputs = dmn_root().findall("dmn:decision[@id='routing_decision']/dmn:decisionTable/dmn:output", DMN_NS)
    assert [(o.get("name") or o.get("label")) for o in outputs] == ["Provider"]


def test_gap_26_message_name(chat_model):
    """Rule: a throw event's message name is the label of the channel it publishes to."""
    rows = select(
        chat_model,
        """SELECT ?event ?name WHERE {
               ?event a proc:MessageThrowEvent ; seam:publishesTo ?channel .
               ?channel a comm:Channel ; rdfs:label ?name .
           }""",
    )
    assert rows == {(rdflib.URIRef("https://example.org/chat/chat_bpmn#stream_complete_event"), lit("stream.events"))}
    # Every throw event resolves a name (exactly one channel each).
    assert not ask(
        chat_model,
        """ASK { ?event a proc:MessageThrowEvent .
                 FILTER NOT EXISTS { ?event seam:publishesTo/rdfs:label ?name } }""",
    )


def test_gap_27_implementation_binding(chat_model):
    """Rule: an invoked operation is implemented by the container exposing it, at its comm:path."""
    rows = select(
        chat_model,
        """SELECT ?task ?op ?container ?path ?inproc WHERE {
               ?task a proc:ServiceTask ; seam:invokes ?op .
               ?container a arch:Container ; seam:exposes ?op .
               ?op comm:path/hydra:template ?path .
               ?task seam:inModel ?model .
               ?process seam:detailedBy ?model .
               BIND(EXISTS { ?container seam:executes ?process } AS ?inproc)
           }""",
    )
    bpmn = rdflib.Namespace("https://example.org/chat/chat_bpmn#")
    assert rows == {
        (
            bpmn.persist_user_msg,
            CHAT.send_message_op,
            CHAT.chat_api,
            lit("/conversations/{conversation}/messages"),
            lit(True),
        ),
        (bpmn.invoke_llm, CHAT.completion_op, CHAT.llm_gateway, lit("/v1/chat/completions"), lit(False)),
    }
    # No invoked operation is left without exactly one exposing container.
    assert not ask(
        chat_model,
        """ASK { ?task seam:invokes ?op .
                 FILTER NOT EXISTS { ?c seam:exposes ?op } }""",
    )
