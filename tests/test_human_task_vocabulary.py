"""seam:completedOn, its shape, the human-task fixture and the query it earns
(M009/S04, ADR-0009, decision D027).

A proc:UserTask seam:completedOn the one ifml:Form a person completes it on; the
screen is the ifml:ViewContainer that contains the form, and the task's
seam:governedBy policies say who may complete it.
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
FIXTURE = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
CHAT_APP_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
QUERY = ROOT / "docs" / "queries" / "screens-to-finish-process.rq"

SEAM = Namespace("https://w3id.org/seams/seam#")
EX = Namespace("https://example.org/expenses/")
CHAT = Namespace("https://example.org/chat/")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
APPROVE_TASK = URIRef("https://example.org/expenses/approval_bpmn#approve_expense")


def load_dataset(trig: Path) -> rdflib.Dataset:
    ds = rdflib.Dataset()
    for path in ONTOLOGY_FILES:
        ds.default_graph.parse(path, format="turtle")
    ds.parse(trig, format="trig")
    return ds


def union(ds: rdflib.Dataset) -> rdflib.Graph:
    g = rdflib.Graph()
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def shacl_messages(data: rdflib.Graph) -> set[str]:
    conforms, report, _ = pyshacl.validate(data, shacl_graph=str(SHAPES_FILE), inference="none")
    messages = {str(m) for m in report.objects(None, rdflib.SH.resultMessage)}
    assert conforms == (not messages)
    return messages


@pytest.fixture(scope="module")
def dataset() -> rdflib.Dataset:
    return load_dataset(FIXTURE)


@pytest.fixture(scope="module")
def model(dataset) -> rdflib.Graph:
    return union(dataset)


# ---------------------------------------------------------------- vocabulary


def test_completed_on_carries_exactly_one_reveal():
    g = rdflib.Graph().parse(ROOT / "ontology" / "seam.ttl", format="turtle")
    assert set(g.objects(SEAM.completedOn, SEAM.reveal)) == {SEAM.Open}


# ---------------------------------------------------------------- fixture


def test_fixture_has_one_graph_per_notation_plus_seams(dataset):
    names = {g.identifier for g in dataset.graphs() if str(g.identifier) != "urn:x-rdflib:default"}
    assert names == {
        URIRef(f"urn:seams:graph:model:{m}")
        for m in ("expense_architecture", "expense_ifml", "approval_bpmn", "expense_data",
                  "expense_lifecycle")
    } | {SEAMS_GRAPH}


def test_fixture_conforms_to_seam_shapes(model):
    assert shacl_messages(model) == set()


def test_fixture_keeps_seam_predicates_in_seams_graph(dataset):
    leaked = [
        (ctx, s, p, o) for s, p, o, ctx in dataset.quads((None, None, None, None))
        if str(p).startswith(str(SEAM)) and p != SEAM.inModel
        and not (p == SEAM.reveal and str(ctx) == "urn:x-rdflib:default")
        and ctx != SEAMS_GRAPH
    ]
    assert not leaked


def test_fixture_bpmn_names_the_user_task(model):
    text = (FIXTURE.parent / "approval.bpmn").read_text()
    assert '<bpmn:userTask id="approve_expense"' in text
    assert (APPROVE_TASK, SEAM.completedOn, EX.approve_form) in model


# ---------------------------------------------------------------- the earned query


def test_query_returns_the_approval_screen(model):
    rows = model.query(QUERY.read_text(), initBindings={"process": EX.approval_process})
    assert {(r.task, r.form, r.screen, r.policy) for r in rows} == {
        (APPROVE_TASK, EX.approve_form, EX.approvals_page, EX.manager_approval_policy),
    }


def test_query_leaves_policy_unbound_for_an_ungoverned_task(model):
    g = rdflib.Graph()
    for t in model:
        if not (t[0] == APPROVE_TASK and t[1] == SEAM.governedBy):
            g.add(t)
    rows = list(g.query(QUERY.read_text(), initBindings={"process": EX.approval_process}))
    assert [(r.task, r.form, r.screen, r.policy) for r in rows] == [
        (APPROVE_TASK, EX.approve_form, EX.approvals_page, None),
    ]


def test_query_finds_no_screens_in_the_chat_app():
    chat = union(load_dataset(CHAT_APP_TRIG))
    assert list(chat.query(QUERY.read_text(), initBindings={"process": CHAT.send_message_process})) == []
    assert list(chat.query(QUERY.read_text())) == []


def test_assignee_answers_which_roles_can_complete(model):
    """The second research question is a one-hop extension, noted in ADR-0009."""
    rows = model.query(
        """PREFIX seam: <https://w3id.org/seams/seam#>
           PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
           SELECT ?role WHERE { ?task seam:governedBy/odrl:permission/odrl:assignee ?role }""",
        initBindings={"task": APPROVE_TASK},
    )
    assert {r.role for r in rows} == {EX.manager}


# ---------------------------------------------------------------- shape teeth

PREFIXES = """
@prefix :      <https://example.org/bad/> .
@prefix arch:  <https://w3id.org/seams/arch#> .
@prefix ifml:  <https://w3id.org/seams/ifml#> .
@prefix proc:  <https://w3id.org/seams/proc#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
"""


@pytest.mark.parametrize(
    "facts, message",
    [
        (":c a arch:Container ; seam:completedOn :f . :f a ifml:Form .",
         "Only a proc:UserTask seam:completedOn a form."),
        (":t a proc:ServiceTask ; seam:completedOn :f . :f a ifml:Form .",
         "Only a proc:UserTask seam:completedOn a form."),
        (":t a proc:UserTask ; seam:completedOn :e . :e a ifml:Event .",
         "seam:completedOn points at one ifml:Form."),
        (":t a proc:UserTask ; seam:completedOn :p . :p a ifml:ViewContainer .",
         "seam:completedOn points at one ifml:Form."),
        (":t a proc:UserTask ; seam:completedOn :f , :g . :f a ifml:Form . :g a ifml:Form .",
         "seam:completedOn points at one ifml:Form."),
    ],
    ids=["from-container", "from-service-task", "to-event", "to-page", "two-forms"],
)
def test_completed_on_shape_has_teeth(facts, message):
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{PREFIXES}\n{facts}", format="turtle")
    assert shacl_messages(data) == {message}


def test_a_user_task_on_one_form_conforms():
    data = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        data.parse(path, format="turtle")
    data.parse(data=f"{PREFIXES}\n:t a proc:UserTask ; seam:completedOn :f . :f a ifml:Form .",
               format="turtle")
    assert shacl_messages(data) == set()
