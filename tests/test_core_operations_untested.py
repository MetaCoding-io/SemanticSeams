"""The ADR-0030 section 6 coverage query: core operations with no handler and no scenario (M028/S03/T03).

The fixture puts five operations in the core finance context: one no handler
implements and no scenario reaches (the one row), one a comm:PythonHandler
implements, one whose UI event starts a scenario's process, one that completes a
user task a scenario steps through, and one whose handler is not a
comm:PythonHandler (still a row). The supporting expense context's operation is
never a row, nor is a finance operation with no seam:inModel. A dataset with no
domain has no rows.
"""

from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from seams import Operation, core_operations_untested

EX = "https://example.org/fx/"

DOMAINS = """
<urn:seams:graph:model:fx_architecture> {
    :fx_architecture a seam:Model .
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context .
    :expenses a arch:Domain ; rdfs:label "Expenses" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_context .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" .
}
"""

OWNERS = """
    :finance_context seam:owns :finance_ontology , :finance_api , :payout_bpmn .
    :expense_context seam:owns :expense_ontology , :expense_api .
"""

MODELS = """
<urn:seams:graph:model:finance_api> {
    :finance_api a seam:Model .
    :untested_op a hydra:Operation ; seam:inModel :finance_api .
    :handled_op a hydra:Operation ; seam:inModel :finance_api ; seam:implementedBy :handled_impl .
    :started_op a hydra:Operation ; seam:inModel :finance_api .
    :completing_op a hydra:Operation ; seam:inModel :finance_api .
    :llm_op a hydra:Operation ; seam:inModel :finance_api ; seam:implementedBy :llm_impl .
    :handled_impl a comm:PythonHandler ; comm:handler "pay.pay" .
    :llm_impl a comm:LLMCompletion .
}
<urn:seams:graph:model:expense_api> {
    :expense_api a seam:Model .
    :supporting_op a hydra:Operation ; seam:inModel :expense_api .
}
<urn:seams:graph:model:payout_bpmn> {
    :payout_bpmn a seam:Model .
    :payout_process a proc:Process ; seam:inModel :payout_bpmn .
    :pay_task a proc:UserTask ; seam:inModel :payout_bpmn .
}
<urn:seams:graph:seams> {
    :stray_op a hydra:Operation .
    :start_payout seam:submitsTo :started_op ; seam:triggers :payout_process .
    :pay_task seam:completedOn :pay_form .
    :pay_form ifml:hasEvent :submit_pay .
    :submit_pay seam:submitsTo :completing_op .
    :paid a verify:Scenario ;
        verify:process :payout_process ;
        verify:step ( [ verify:task :pay_task ] ) .
%s
}
"""

PREFIXES = """
@prefix :       <https://example.org/fx/> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix ifml:   <https://w3id.org/seams/ifml#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix verify: <https://w3id.org/seams/verify#> .
"""


def load(tmp_path: Path, text: str) -> seams.Model:
    path = tmp_path / "model.trig"
    path.write_text(text, encoding="utf-8")
    return seams.Model(path, check_versions=False, check_imports=False)


@pytest.fixture
def model(tmp_path: Path) -> seams.Model:
    return load(tmp_path, PREFIXES + DOMAINS + MODELS % OWNERS)


def iris(*names: str) -> tuple[URIRef, ...]:
    return tuple(URIRef(EX + n) for n in names)


def test_rows_name_the_core_operations_with_no_handler_and_no_scenario(model: seams.Model):
    rows = model.question("coverage/core-operations-untested")
    assert [(str(r["domain"]), str(r["context"]), str(r["operation"])) for r in rows] == [
        (EX + "finance", EX + "finance_context", EX + "llm_op"),
        (EX + "finance", EX + "finance_context", EX + "untested_op"),
    ]


def test_wrapper_returns_operation_views_sorted(model: seams.Model):
    found = core_operations_untested(model)
    assert found.iris() == iris("llm_op", "untested_op")
    assert all(isinstance(op, Operation) for op in found)


def test_a_python_handler_covers_an_operation(model: seams.Model):
    assert URIRef(EX + "handled_op") not in core_operations_untested(model).iris()


def test_a_scenario_running_the_process_it_starts_covers_an_operation(model: seams.Model):
    assert URIRef(EX + "started_op") not in core_operations_untested(model).iris()


def test_a_scenario_step_on_the_task_it_completes_covers_an_operation(model: seams.Model):
    assert URIRef(EX + "completing_op") not in core_operations_untested(model).iris()


def test_without_the_scenario_the_reached_operations_are_rows(tmp_path: Path):
    text = PREFIXES + DOMAINS + (MODELS % OWNERS).replace(":paid a verify:Scenario", ":paid a :NotAScenario")
    assert core_operations_untested(load(tmp_path, text)).iris() == iris(
        "completing_op", "llm_op", "started_op", "untested_op"
    )


def test_supporting_domain_and_unowned_operations_are_not_rows(model: seams.Model):
    found = core_operations_untested(model).iris()
    assert URIRef(EX + "supporting_op") not in found
    assert URIRef(EX + "stray_op") not in found


def test_binding_a_context_narrows_the_rows(model: seams.Model):
    assert core_operations_untested(model, EX + "finance_context").iris() == iris("llm_op", "untested_op")
    assert core_operations_untested(model, EX + "expense_context").iris() == ()


def test_a_dataset_with_no_domain_has_no_rows(tmp_path: Path):
    assert core_operations_untested(load(tmp_path, PREFIXES + MODELS % OWNERS)) == ()


@pytest.mark.parametrize("trig", ["examples/expenses/chapter-09/expenses.trig", "examples/chat-app/chat-app.trig"])
def test_examples_have_no_core_operations_untested(trig: str):
    root = Path(__file__).resolve().parent.parent
    assert core_operations_untested(seams.load(root / trig)) == ()
