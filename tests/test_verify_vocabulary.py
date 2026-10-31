"""Tests for the scenario and example vocabulary (M015/S03, ADR-0014).

ontology/verify.ttl adds verify:Scenario, verify:DecisionExample and the properties
that state a scenario, a decision example and a shape example. The "Scenarios and
examples" section of ontology/shapes/seam-shapes.ttl constrains them: each shape is a
fault the tests generator would otherwise reject (principle 5). Models are validated
with the ontology files merged in, as tests/validate_chat_app.py does. The ADR's
turtle example is itself the conforming fixture.
"""

import re
from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, RDFS, BNode, Literal, Namespace, URIRef
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
VERIFY_FILE = ROOT / "ontology" / "verify.ttl"
ADR = ROOT / "docs" / "adr" / "0014-scenarios-and-derived-tests.md"

VERIFY = Namespace("https://w3id.org/seams/verify#")
SEAM = Namespace("https://w3id.org/seams/seam#")
PROC = Namespace("https://w3id.org/seams/proc#")
DEC = Namespace("https://w3id.org/seams/dec#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")
EX = Namespace("https://example.org/expenses/")
APPROVE = URIRef("https://example.org/expenses/approval_bpmn#approve_expense")
APPROVED_END = URIRef("https://example.org/expenses/approval_bpmn#approved_end")

SCENARIO = EX.manager_approved
DECISION_EXAMPLE = EX.routes_mid_amounts_to_manager

CLASSES = [VERIFY.Scenario, VERIFY.DecisionExample]
PROPERTIES = [
    VERIFY.process,
    VERIFY.actor,
    VERIFY.given,
    VERIFY.field,
    VERIFY.value,
    VERIFY.step,
    VERIFY.task,
    VERIFY.expectState,
    VERIFY.expectEndEvent,
    VERIFY.decision,
    VERIFY.expectOutput,
    VERIFY.validExample,
    VERIFY.invalidExample,
]


def adr_text() -> str:
    return ADR.read_text(encoding="utf-8")


def ontology() -> rdflib.Graph:
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    return g


def model() -> rdflib.Graph:
    """The ontology plus the ADR's turtle example: a scenario, a decision example and a
    pair of shape examples, with the facts they point at."""
    blocks = re.findall(r"```turtle\n(.*?)```", adr_text(), re.DOTALL)
    assert len(blocks) == 1
    g = ontology()
    g.parse(data=blocks[0], format="turtle")
    return g


def violating_shapes(g: rdflib.Graph) -> set:
    """The shapes (named ones, or the named parent of a property shape) that report."""
    shapes_graph = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    conforms, results, _ = pyshacl.validate(g, shacl_graph=shapes_graph, inference="none")
    if conforms:
        return set()
    named = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        source = results.value(result, SH.sourceShape)
        parent = shapes_graph.value(predicate=SH.property, object=source)
        named.add(parent if parent is not None else source)
    return named


def given(g: rdflib.Graph, subject, field):
    return next(n for n in g.objects(subject, VERIFY.given) if g.value(n, VERIFY.field) == field)


def step(g: rdflib.Graph):
    [first] = Collection(g, g.value(SCENARIO, VERIFY.step))
    return first


def rename(g: rdflib.Graph, old, new) -> None:
    """Move every triple of ``old`` (as subject or object) onto ``new``."""
    for p, o in list(g.predicate_objects(old)):
        g.remove((old, p, o))
        g.add((new, p, o))
    for s, p in list(g.subject_predicates(old)):
        g.remove((s, p, old))
        g.add((s, p, new))


# ---------------------------------------------------------------- ontology


@pytest.mark.parametrize("term", CLASSES + PROPERTIES)
def test_terms_are_labelled_and_commented(term):
    g = rdflib.Graph().parse(VERIFY_FILE, format="turtle")
    assert g.value(term, RDFS.label) is not None
    assert g.value(term, RDFS.comment) is not None


def test_verify_file_declares_exactly_these_terms():
    """Vocabulary is earned (principle 4): nothing beyond what ADR-0014 lists."""
    g = rdflib.Graph().parse(VERIFY_FILE, format="turtle")
    assert set(g.subjects(RDF.type, RDFS.Class)) == set(CLASSES)
    assert set(g.subjects(RDF.type, RDF.Property)) == set(PROPERTIES)


def test_namespace_follows_the_other_ontology_files():
    g = rdflib.Graph().parse(VERIFY_FILE, format="turtle")
    assert (URIRef("https://w3id.org/seams/verify"), RDF.type, rdflib.OWL.Ontology) in g


def test_no_verify_term_is_a_seam_predicate():
    """Scenario facts are test data, not navigation edges: none has a reveal mode."""
    g = ontology()
    assert not [p for p in PROPERTIES if g.value(p, SEAM.reveal) is not None]


# ---------------------------------------------------------------- SHACL: conforming


def test_ontology_alone_conforms():
    assert violating_shapes(ontology()) == set()


def test_adr_example_conforms():
    assert violating_shapes(model()) == set()


def test_scenario_with_end_event_only_conforms():
    g = model()
    g.remove((SCENARIO, VERIFY.expectState, None))
    g.add((SCENARIO, VERIFY.expectEndEvent, APPROVED_END))
    assert violating_shapes(g) == set()


def test_scenario_with_no_steps_conforms():
    """The auto-approved scenario completes no user task."""
    g = model()
    g.set((SCENARIO, VERIFY.step, RDF.nil))
    assert violating_shapes(g) == set()


def test_example_nodes_do_not_make_the_model_fail_its_shapes():
    """The invalid example has a negative amount, but no shape targets it."""
    g = model()
    assert (EX.expense_negative_amount, EX.amount, Literal("-5.00", datatype=rdflib.XSD.decimal)) in g
    assert violating_shapes(g) == set()


# ---------------------------------------------------------------- SHACL: scenarios


def test_scenario_without_process_is_flagged():
    g = model()
    g.remove((SCENARIO, VERIFY.process, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_with_two_processes_is_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.process, EX.other_process))
    g.add((EX.other_process, RDF.type, PROC.Process))
    g.add((EX.submit_other, SEAM.triggers, EX.other_process))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_process_that_is_not_a_process_is_flagged():
    g = model()
    g.set((SCENARIO, VERIFY.process, EX.approval_routing))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_process_no_event_triggers_is_flagged():
    """A channel-started process has no UI route to start it from."""
    g = model()
    g.remove((None, SEAM.triggers, EX.approval_process))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_without_actor_is_flagged():
    g = model()
    g.remove((SCENARIO, VERIFY.actor, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_actor_that_is_not_a_party_is_flagged():
    g = model()
    g.set((SCENARIO, VERIFY.actor, EX.approval_process))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_scenario_without_expectation_is_flagged():
    g = model()
    g.remove((SCENARIO, VERIFY.expectState, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_expected_state_that_is_not_a_state_is_flagged():
    g = model()
    g.set((SCENARIO, VERIFY.expectState, EX.manager))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_expected_state_no_shape_has_as_lifecycle_is_flagged():
    g = model()
    g.remove((EX.ExpenseShape, SEAM.lifecycle, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_two_expected_states_are_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.expectState, EX.s_submitted))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_expected_end_event_in_another_model_is_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.expectEndEvent, APPROVED_END))
    g.set((APPROVED_END, SEAM.inModel, EX.payout_bpmn))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_expected_end_event_that_is_not_lifted_is_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.expectEndEvent, EX.unlifted_end))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_literal_end_event_is_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.expectEndEvent, Literal("approved_end")))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_task_that_is_not_a_user_task_is_flagged():
    g = model()
    g.remove((APPROVE, RDF.type, PROC.UserTask))
    g.add((APPROVE, RDF.type, PROC.ServiceTask))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_without_task_is_flagged():
    g = model()
    g.remove((step(g), VERIFY.task, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_without_actor_is_flagged():
    g = model()
    g.remove((step(g), VERIFY.actor, None))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_with_two_actors_is_flagged():
    g = model()
    g.add((step(g), VERIFY.actor, EX.employee))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_task_in_another_model_is_flagged():
    g = model()
    g.set((APPROVE, SEAM.inModel, EX.payout_bpmn))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_step_that_is_not_a_list_is_flagged():
    g = model()
    s = step(g)
    g.set((SCENARIO, VERIFY.step, s))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_two_step_lists_are_flagged():
    g = model()
    g.add((SCENARIO, VERIFY.step, RDF.nil))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_untyped_scenario_is_flagged():
    g = model()
    g.remove((SCENARIO, RDF.type, VERIFY.Scenario))
    assert SEAMSH.ScenarioShape in violating_shapes(g)


def test_blank_node_scenario_is_flagged():
    """Its generated test would have no stable name."""
    g = model()
    rename(g, SCENARIO, BNode())
    assert SEAMSH.ScenarioShape in violating_shapes(g)


# ---------------------------------------------------------------- SHACL: givens


def test_given_without_value_is_flagged():
    g = model()
    g.remove((given(g, SCENARIO, EX.amount), VERIFY.value, None))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_given_with_two_values_is_flagged():
    g = model()
    g.add((given(g, SCENARIO, EX.amount), VERIFY.value, Literal("300.00")))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_given_value_that_is_not_a_literal_is_flagged():
    g = model()
    g.set((given(g, SCENARIO, EX.amount), VERIFY.value, EX.manager))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_given_without_field_is_flagged():
    g = model()
    g.remove((given(g, SCENARIO, EX.amount), VERIFY.field, None))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_given_field_no_shape_declares_is_flagged():
    g = model()
    g.set((given(g, SCENARIO, EX.amount), VERIFY.field, EX.amout))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_step_given_field_no_shape_declares_is_flagged():
    g = model()
    g.set((given(g, step(g), EX.decision), VERIFY.field, EX.verdict))
    assert SEAMSH.GivenShape in violating_shapes(g)


def test_same_field_given_twice_is_flagged():
    g = model()
    extra = BNode()
    g.add((SCENARIO, VERIFY.given, extra))
    g.add((extra, VERIFY.field, EX.amount))
    g.add((extra, VERIFY.value, Literal("300.00")))
    assert SEAMSH.GivenUniqueShape in violating_shapes(g)


# ---------------------------------------------------------------- SHACL: decision examples


def test_decision_example_without_decision_is_flagged():
    g = model()
    g.remove((DECISION_EXAMPLE, VERIFY.decision, None))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_decision_example_decision_that_is_not_a_decision_is_flagged():
    g = model()
    g.set((DECISION_EXAMPLE, VERIFY.decision, EX.approval_process))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_decision_example_given_that_is_no_input_is_flagged():
    g = model()
    extra = BNode()
    g.add((DECISION_EXAMPLE, VERIFY.given, extra))
    g.add((extra, VERIFY.field, EX.description))
    g.add((extra, VERIFY.value, Literal("Train to Leeds")))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_decision_example_missing_an_input_is_flagged():
    g = model()
    g.remove((DECISION_EXAMPLE, VERIFY.given, given(g, DECISION_EXAMPLE, EX.amount)))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_decision_example_without_expected_output_is_flagged():
    g = model()
    g.remove((DECISION_EXAMPLE, VERIFY.expectOutput, None))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_expected_output_naming_no_output_binding_is_flagged():
    g = model()
    out = g.value(DECISION_EXAMPLE, VERIFY.expectOutput)
    g.set((out, DEC.variable, Literal("Routing")))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_expected_output_without_value_is_flagged():
    g = model()
    g.remove((g.value(DECISION_EXAMPLE, VERIFY.expectOutput), VERIFY.value, None))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_expected_output_without_variable_is_flagged():
    g = model()
    g.remove((g.value(DECISION_EXAMPLE, VERIFY.expectOutput), DEC.variable, None))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_untyped_decision_example_is_flagged():
    g = model()
    g.remove((DECISION_EXAMPLE, RDF.type, VERIFY.DecisionExample))
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


def test_blank_node_decision_example_is_flagged():
    g = model()
    rename(g, DECISION_EXAMPLE, BNode())
    assert SEAMSH.DecisionExampleShape in violating_shapes(g)


# ---------------------------------------------------------------- SHACL: shape examples


def test_example_of_something_that_is_not_a_shape_is_flagged():
    g = model()
    g.add((EX.approval_process, VERIFY.validExample, EX.expense_train))
    assert SEAMSH.ShapeExampleShape in violating_shapes(g)


def test_literal_example_is_flagged():
    g = model()
    g.add((EX.ExpenseShape, VERIFY.invalidExample, Literal("not a node")))
    assert SEAMSH.ShapeExampleShape in violating_shapes(g)


def test_blank_node_example_is_flagged():
    g = model()
    rename(g, EX.expense_train, BNode())
    assert SEAMSH.ShapeExampleShape in violating_shapes(g)


def test_example_both_valid_and_invalid_is_flagged():
    g = model()
    g.add((EX.ExpenseShape, VERIFY.invalidExample, EX.expense_train))
    assert SEAMSH.ShapeExampleShape in violating_shapes(g)


# ---------------------------------------------------------------- the ADR and docs


def test_adr_is_accepted():
    assert "**Status:** Accepted" in adr_text()


@pytest.mark.parametrize("heading", ["Context", "What DASH offers", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(heading):
    assert re.search(rf"^##+ {heading}", adr_text(), re.MULTILINE)


@pytest.mark.parametrize(
    "term",
    ["dash:GraphValidationTestCase", "dash:FunctionTestCase", "dash:expectedResult", "dash:InferencingTestCase"],
)
def test_adr_records_why_each_dash_term_was_not_reused(term):
    assert term in adr_text()


@pytest.mark.parametrize(
    "fixed", ["<urn:seams:graph:seams>", "Policy tests need no terms", "generated/tests", "seams.lock"]
)
def test_adr_fixes_graph_policy_derivation_and_layout(fixed):
    assert fixed in adr_text()


def test_adr_is_in_decisions_nav():
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0014", "Scenarios and derived tests", "0014-scenarios-and-derived-tests"]' in config


def test_adr_is_in_adr_index():
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "./0014-scenarios-and-derived-tests" in index


def test_vocabulary_reference_page_lists_verify():
    source = (ROOT / "docs" / "scripts" / "generate.py").read_text(encoding="utf-8")
    assert re.search(r'^VOCABULARIES = \[.*"verify".*\]$', source, re.MULTILINE)
