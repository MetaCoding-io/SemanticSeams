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


# ── personal-data-screens-by-role (ADR-0039) ──

CHAPTER_11 = ROOT / "examples/expenses/chapter-11"
E = "https://example.org/expenses/"
K = "https://example.org/clinic/"
PD = "https://w3id.org/dpv/pd#"


def test_personal_data_screens_by_role_chapter_11_rows():
    model = seams.load(CHAPTER_11)
    # The one marked field (the notification's recipient) is on a shape no screen reads.
    assert model.question("personal-data-screens-by-role") == []
    assert model.question("personal-data-screens-by-role", shape=":NotificationShape") == []

    # Test-side fact: mark the expense's description as a name. Every screen reading the
    # expense then appears, with the roles its events, operations or user tasks grant.
    data = model.ds.graph(URIRef("urn:seams:graph:model:expense_data"))
    sh = "http://www.w3.org/ns/shacl#"
    field = next(
        f
        for f in data.objects(URIRef(E + "ExpenseShape"), URIRef(sh + "property"))
        if data.value(f, URIRef(sh + "path")) == URIRef(E + "description")
    )
    data.add((field, URIRef("https://w3id.org/dpv#hasPersonalData"), URIRef(PD + "Name")))
    rows = model.question("personal-data-screens-by-role", shape=":ExpenseShape")
    assert [(r.get("role"), r["screen"], r["property"], r["category"]) for r in rows] == [
        (None, URIRef(E + "payouts_page"), URIRef(E + "description"), URIRef(PD + "Name")),
        (URIRef(E + "employee"), URIRef(E + "expenses_page"), URIRef(E + "description"), URIRef(PD + "Name")),
        (URIRef(E + "finance"), URIRef(E + "approvals_page"), URIRef(E + "description"), URIRef(PD + "Name")),
        (URIRef(E + "manager"), URIRef(E + "approvals_page"), URIRef(E + "description"), URIRef(PD + "Name")),
    ]
    assert model.question("personal-data-screens-by-role", shape=":PaymentShape") == []


# A complete model: four screens read the patient shape (governed by event, by
# operation, by user task, and not at all); the note shape is read but unmarked; the
# appointment shape is marked but read by no screen; the visit shape carries its
# annotation on the node shape, which the query (and PersonalDataPlacementShape) ignores.
CLINIC = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix ifml: <https://w3id.org/seams/ifml#> .
@prefix proc: <https://w3id.org/seams/proc#> .
@prefix odrl: <http://www.w3.org/ns/odrl/2/> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix dpv:  <https://w3id.org/dpv#> .
@prefix pd:   <https://w3id.org/dpv/pd#> .
@prefix :     <https://example.org/clinic/> .

<urn:seams:graph:model:clinic_data> {
    :PatientShape a sh:NodeShape ; rdfs:label "Patient" ;
        sh:property [ sh:path :fullName ; sh:datatype xsd:string ; dpv:hasPersonalData pd:Name ] ;
        sh:property [ sh:path :email ; sh:datatype xsd:string ;
                      dpv:hasPersonalData pd:EmailAddress , pd:Contact ] ;
        sh:property [ sh:path :ward ; sh:datatype xsd:string ] .
    :NoteShape a sh:NodeShape ; rdfs:label "Note" ;
        sh:property [ sh:path :text ; sh:datatype xsd:string ] .
    :AppointmentShape a sh:NodeShape ; rdfs:label "Appointment" ;
        sh:property [ sh:path :phone ; sh:datatype xsd:string ; dpv:hasPersonalData pd:TelephoneNumber ] .
    :VisitShape a sh:NodeShape ; rdfs:label "Visit" ; dpv:hasPersonalData pd:Name ;
        sh:property [ sh:path :visitor ; sh:datatype xsd:string ] .
}

<urn:seams:graph:model:clinic_ui> {
    :desk_page a ifml:ViewContainer ; ifml:contains :patient_list , :note_list .
    :patient_list a ifml:List ; ifml:hasEvent :open_patient .
    :note_list a ifml:List .
    :open_patient a ifml:Event .
    :admin_page a ifml:ViewContainer ; ifml:contains :patient_details , :edit_form .
    :patient_details a ifml:Details .
    :edit_form a ifml:Form ; ifml:hasEvent :save_patient .
    :save_patient a ifml:Event .
    :ward_page a ifml:ViewContainer ; ifml:contains :ward_details , :discharge_form .
    :ward_details a ifml:Details .
    :discharge_form a ifml:Form .
    :lobby_page a ifml:ViewContainer ; ifml:contains :lobby_list .
    :lobby_list a ifml:List .
}

<urn:seams:graph:seams> {
    :patient_list seam:reads :PatientShape .
    :note_list seam:reads :NoteShape .
    :patient_details seam:reads :PatientShape .
    :ward_details seam:reads :PatientShape .
    :lobby_list seam:reads :PatientShape , :VisitShape .
    :open_patient seam:governedBy :desk_policy .
    :save_patient seam:submitsTo :save_patient_op .
    :save_patient_op a hydra:Operation ; seam:governedBy :admin_policy .
    :discharge seam:completedOn :discharge_form ; seam:governedBy :nurse_policy .
    :discharge a proc:UserTask .
    :desk_policy a odrl:Policy ; odrl:permission [ a odrl:Permission ; odrl:assignee :receptionist ] .
    :admin_policy a odrl:Policy ; odrl:permission [ a odrl:Permission ; odrl:assignee :admin ] .
    :nurse_policy a odrl:Policy ; odrl:permission [ a odrl:Permission ; odrl:assignee :nurse ] .
}
"""


@pytest.fixture(scope="module")
def clinic(tmp_path_factory: pytest.TempPathFactory) -> seams.Model:
    path = tmp_path_factory.mktemp("clinic") / "clinic.trig"
    path.write_text(CLINIC, encoding="utf-8")
    return seams.load(path, check_versions=False, check_imports=False)


def test_personal_data_screens_by_role_inline_rows(clinic: seams.Model):
    rows = clinic.question("personal-data-screens-by-role")
    assert [(r.get("role"), r["screen"], r["shape"], r["property"], r["category"]) for r in rows] == [
        (None, URIRef(K + "lobby_page"), URIRef(K + "PatientShape"), URIRef(K + "email"), URIRef(PD + "Contact")),
        (None, URIRef(K + "lobby_page"), URIRef(K + "PatientShape"), URIRef(K + "email"), URIRef(PD + "EmailAddress")),
        (None, URIRef(K + "lobby_page"), URIRef(K + "PatientShape"), URIRef(K + "fullName"), URIRef(PD + "Name")),
        (
            URIRef(K + "admin"),
            URIRef(K + "admin_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "Contact"),
        ),
        (
            URIRef(K + "admin"),
            URIRef(K + "admin_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "EmailAddress"),
        ),
        (
            URIRef(K + "admin"),
            URIRef(K + "admin_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "fullName"),
            URIRef(PD + "Name"),
        ),
        (
            URIRef(K + "nurse"),
            URIRef(K + "ward_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "Contact"),
        ),
        (
            URIRef(K + "nurse"),
            URIRef(K + "ward_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "EmailAddress"),
        ),
        (
            URIRef(K + "nurse"),
            URIRef(K + "ward_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "fullName"),
            URIRef(PD + "Name"),
        ),
        (
            URIRef(K + "receptionist"),
            URIRef(K + "desk_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "Contact"),
        ),
        (
            URIRef(K + "receptionist"),
            URIRef(K + "desk_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "email"),
            URIRef(PD + "EmailAddress"),
        ),
        (
            URIRef(K + "receptionist"),
            URIRef(K + "desk_page"),
            URIRef(K + "PatientShape"),
            URIRef(K + "fullName"),
            URIRef(PD + "Name"),
        ),
    ]


@pytest.mark.parametrize(
    "shape",
    [
        ":NoteShape",  # read by a screen, no marked field
        ":AppointmentShape",  # marked field, read by no screen
        ":VisitShape",  # annotation on the node shape, not on a field
        ":desk_page",  # not a shape
    ],
)
def test_personal_data_screens_by_role_no_rows(clinic: seams.Model, shape: str):
    assert clinic.question("personal-data-screens-by-role", shape=shape) == []
