"""Latency budget shapes (ADR-0043, M032/S02).

Every dataset is inline TriG: one ``nfr:LatencyBudget`` on the expense tutorial's
approve-expense operation, in the architecture model's graph. The budget conforms with
and without a percentile; each negative case breaks one fact and asserts the one
violation by focus node, result path and owning shape, and its message exactly, so the
finding names the predicate as ``seams check`` prints it. A dataset with no budget is
unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import pytest
from rdflib import RDF, Dataset, Graph, Namespace
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
EX = Namespace("https://example.org/expenses/")
NFR = Namespace("https://w3id.org/seams/nfr#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix nfr:   <https://w3id.org/seams/nfr#> .
@prefix :      <https://example.org/expenses/> .
"""

OPERATION = """
    :approve_expense_op a hydra:Operation ; rdfs:label "Approve Expense" .
"""

BUDGET = """
    :approve_budget a nfr:LatencyBudget ;
        nfr:budgetOf :approve_expense_op ;
        nfr:maxMilliseconds 300 ;
        nfr:percentile 95 .
"""

BUDGET_OF = (
    "A nfr:LatencyBudget has exactly one nfr:budgetOf, the IRI of the BPMN flow node or "
    "hydra:Operation it bounds (ADR-0043)."
)
MAX = "A nfr:LatencyBudget has exactly one nfr:maxMilliseconds, a number greater than 0 (ADR-0043)."
PERCENTILE = (
    "A nfr:LatencyBudget has at most one nfr:percentile, a number greater than 0 and at most 100; "
    "absent means 100 (ADR-0043)."
)
NODE = (
    "Only a nfr:LatencyBudget carries nfr:budgetOf, nfr:maxMilliseconds or nfr:percentile, "
    "and a budget is an IRI (ADR-0043)."
)


def dataset(budgets: str = BUDGET) -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_architecture> {{{budgets}}}\n<urn:seams:graph:seams> {{{OPERATION}}}\n"
    )


def validate(trig: str) -> Graph:
    """The SHACL report for ``trig``'s quads and the vocabularies in one graph, as
    ``seams check`` validates."""
    ds = Dataset()
    ds.parse(data=trig, format="trig")
    data = Graph()
    for vocabulary in sorted(ONTOLOGY.glob("*.ttl")):
        data.parse(vocabulary)
    for s, p, o, _graph in ds.quads((None, None, None, None)):
        data.add((s, p, o))
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=SHAPES, inference="none")
    assert isinstance(report, Graph)
    return report


def _name(term: object) -> str:
    return "-" if term is None else str(term).removeprefix(str(EX)).removeprefix(str(NFR)).removeprefix(str(SEAMSH))


def findings(trig: str) -> set[tuple[str, str, str, str]]:
    """(focus node, result path, owning node shape, message) for every result."""
    report = validate(trig)
    found: set[tuple[str, str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property or SPARQL constraint is a blank node: report the node shape that owns it.
        owner = next(iter(SHAPES.subjects(SH.property, shape)), None) or next(  # type: ignore[arg-type]
            iter(SHAPES.subjects(SH.sparql, shape)),  # type: ignore[arg-type]
            shape,
        )
        found.add(
            (
                _name(report.value(result, SH.focusNode)),
                _name(report.value(result, SH.resultPath)),
                _name(owner),
                str(report.value(result, SH.resultMessage)),
            )
        )
    return found


def test_a_valid_budget_conforms() -> None:
    assert findings(dataset()) == set()


def test_a_budget_without_a_percentile_conforms() -> None:
    assert findings(dataset(BUDGET.replace(" ;\n        nfr:percentile 95 .", " ."))) == set()


@pytest.mark.parametrize("bound", ["300", "0.5", '"250.25"^^xsd:decimal'])
def test_any_positive_decimal_bound_conforms(bound: str) -> None:
    assert findings(dataset(BUDGET.replace("nfr:maxMilliseconds 300", f"nfr:maxMilliseconds {bound}"))) == set()


@pytest.mark.parametrize("percentile", ["100", "0.1", "50"])
def test_a_percentile_in_range_conforms(percentile: str) -> None:
    assert findings(dataset(BUDGET.replace("nfr:percentile 95", f"nfr:percentile {percentile}"))) == set()


def test_a_dataset_with_no_budget_is_unaffected() -> None:
    assert findings(dataset("")) == set()


def test_a_budget_without_budget_of_fails_naming_the_predicate() -> None:
    trig = dataset(BUDGET.replace("        nfr:budgetOf :approve_expense_op ;\n", ""))
    assert findings(trig) == {("approve_budget", "budgetOf", "LatencyBudgetShape", BUDGET_OF)}


def test_a_literal_budget_of_fails_naming_the_predicate() -> None:
    trig = dataset(BUDGET.replace("nfr:budgetOf :approve_expense_op", 'nfr:budgetOf "approve_expense_op"'))
    assert findings(trig) == {("approve_budget", "budgetOf", "LatencyBudgetShape", BUDGET_OF)}


def test_two_elements_in_one_budget_fail() -> None:
    trig = dataset(
        BUDGET.replace("nfr:budgetOf :approve_expense_op", "nfr:budgetOf :approve_expense_op , :submit_expense_op")
    )
    assert findings(trig) == {("approve_budget", "budgetOf", "LatencyBudgetShape", BUDGET_OF)}


@pytest.mark.parametrize("bound", ["0", "-5", "0.0", '"fast"'])
def test_a_non_positive_or_non_numeric_bound_fails_naming_the_predicate(bound: str) -> None:
    trig = dataset(BUDGET.replace("nfr:maxMilliseconds 300", f"nfr:maxMilliseconds {bound}"))
    assert findings(trig) == {("approve_budget", "maxMilliseconds", "LatencyBudgetShape", MAX)}


def test_a_budget_without_a_bound_fails_naming_the_predicate() -> None:
    trig = dataset(BUDGET.replace("        nfr:maxMilliseconds 300 ;\n", ""))
    assert findings(trig) == {("approve_budget", "maxMilliseconds", "LatencyBudgetShape", MAX)}


@pytest.mark.parametrize("percentile", ["0", "150", "100.5", "-1", '"p95"'])
def test_a_percentile_out_of_range_fails_naming_the_predicate(percentile: str) -> None:
    trig = dataset(BUDGET.replace("nfr:percentile 95", f"nfr:percentile {percentile}"))
    assert findings(trig) == {("approve_budget", "percentile", "LatencyBudgetShape", PERCENTILE)}


def test_two_percentiles_fail() -> None:
    trig = dataset(BUDGET.replace("nfr:percentile 95", "nfr:percentile 95 , 99"))
    assert findings(trig) == {("approve_budget", "percentile", "LatencyBudgetShape", PERCENTILE)}


def test_an_untyped_subject_of_a_budget_predicate_fails() -> None:
    trig = dataset(BUDGET.replace(":approve_budget a nfr:LatencyBudget ;", ":approve_budget"))
    assert findings(trig) == {("approve_budget", "-", "LatencyBudgetShape", NODE)}


def test_two_budgets_of_one_element_at_one_percentile_fail_naming_the_element() -> None:
    other = BUDGET.replace(":approve_budget", ":approve_budget_again").replace("300", "500")
    trig = dataset(BUDGET + other)
    detail = "another nfr:LatencyBudget bounds https://example.org/expenses/approve_expense_op at the same nfr:percentile; an element has at most one budget per percentile (ADR-0043)."
    assert findings(trig) == {
        ("approve_budget", "budgetOf", "LatencyBudgetShape", f"https://example.org/expenses/approve_budget: {detail}"),
        (
            "approve_budget_again",
            "budgetOf",
            "LatencyBudgetShape",
            f"https://example.org/expenses/approve_budget_again: {detail}",
        ),
    }


def test_an_absent_percentile_counts_as_100() -> None:
    p100 = BUDGET.replace("nfr:percentile 95", "nfr:percentile 100")
    absent = BUDGET.replace(":approve_budget", ":approve_budget_max").replace(" ;\n        nfr:percentile 95 .", " .")
    assert {f[0] for f in findings(dataset(p100 + absent))} == {"approve_budget", "approve_budget_max"}


def test_budgets_of_one_element_at_different_percentiles_conform() -> None:
    other = BUDGET.replace(":approve_budget", ":approve_budget_p50").replace("nfr:percentile 95", "nfr:percentile 50")
    assert findings(dataset(BUDGET + other)) == set()
