"""The class lifecycle and publishing transitions in the seam shapes (ADR-0031, M028/S04).

Every dataset is inline TriG built from ``dataset()``: an ontology declaring
``:Expense`` as an ``owl:Class``, a shapes graph whose ``:ExpenseShape`` targets it,
the expense lifecycle and a seams graph in which the class names the lifecycle. The
dataset conforms; each negative case breaks one fact and asserts the one violation by
focus node, result path and shape, plus its message, as ``seams check`` prints it.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
from rdflib import RDF, Dataset, Graph, Namespace
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
EX = Namespace("https://example.org/expenses/")
SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
@prefix comm:  <https://w3id.org/seams/comm#> .
@prefix ifml:  <https://w3id.org/seams/ifml#> .
@prefix :      <https://example.org/expenses/> .
"""

ONTOLOGY_GRAPH = """
    :expense_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> .
    :Expense a owl:Class ; rdfs:label "Expense" ; seam:inModel :expense_ontology .
    :Payment a owl:Class ; rdfs:label "Payment" ; seam:inModel :expense_ontology .
"""

SHAPES_GRAPH = """
    :expense_data a seam:Model ; seam:notation seam:ShapeGraph .
    :ExpenseShape a sh:NodeShape ; sh:targetClass :Expense ; seam:inModel :expense_data .
"""

LIFECYCLE = """
    :expense_lifecycle a seam:Model , state:StateMachine ; seam:notation seam:Statechart ;
        state:initial :s_submitted ;
        state:hasState :s_submitted , :s_approved ;
        state:hasTransition :t_approve .
    :s_submitted a state:State ; rdfs:label "submitted" .
    :s_approved a state:State ; rdfs:label "approved" .
    :t_approve a state:Transition ; state:source :s_submitted ; state:target :s_approved .
"""

SEAMS = """
    :Expense seam:lifecycle :expense_lifecycle .
"""

LIFECYCLE_MESSAGE = "Only an owl:Class or a sh:NodeShape carries a seam:lifecycle (ADR-0031)."
TWO_LIFECYCLES_MESSAGE = (
    "A sh:NodeShape has at most one effective seam:lifecycle, its own or that of its sh:targetClass; "
    f"it reaches {EX.expense_lifecycle} and {EX.payment_lifecycle}."
)
PAYMENT_LIFECYCLE = """
    :payment_lifecycle a seam:Model , state:StateMachine ; seam:notation seam:Statechart ;
        state:initial :s_paid ; state:hasState :s_paid .
    :s_paid a state:State ; rdfs:label "paid" .
"""


def dataset(lifecycle: str = LIFECYCLE, shapes: str = SHAPES_GRAPH, seams: str = SEAMS, extra: str = "") -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_ontology> {{{ONTOLOGY_GRAPH}}}\n"
        + f"\n<urn:seams:graph:model:expense_data> {{{shapes}}}\n"
        + f"\n<urn:seams:graph:model:expense_lifecycle> {{{lifecycle}}}\n"
        + f"\n<urn:seams:graph:seams> {{{seams}{extra}}}\n"
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


def violations(trig: str) -> set[tuple[str, str, str, str]]:
    """(focus node, result path, owning node shape, message) for every result."""
    report = validate(trig)
    found: set[tuple[str, str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property shape is a blank node: report the node shape that owns it.
        owner = next(iter(SHAPES.subjects(SH.property, shape)), shape)  # type: ignore[arg-type]
        focus = report.value(result, SH.focusNode)
        path = report.value(result, SH.resultPath)
        found.add(
            (
                str(focus).removeprefix(str(EX)),
                "-" if path is None else str(path).removeprefix(str(SEAM)),
                str(owner).removeprefix(str(SEAMSH)),
                str(report.value(result, SH.resultMessage)),
            )
        )
    return found


# ── LifecycleShape ──


def test_a_class_lifecycle_conforms() -> None:
    assert violations(dataset()) == set()


def test_a_shape_lifecycle_still_conforms() -> None:
    assert violations(dataset(seams="\n    :ExpenseShape seam:lifecycle :expense_lifecycle .\n")) == set()


def test_a_subject_neither_class_nor_shape_fails() -> None:
    # A literal cannot be a subject in RDF, so the bad subject is the nearest thing a
    # model can write: an IRI typed as something else, here a state.
    seams = SEAMS + "    :s_submitted seam:lifecycle :expense_lifecycle .\n"
    assert violations(dataset(seams=seams)) == {("s_submitted", "-", "LifecycleShape", LIFECYCLE_MESSAGE)}


def test_an_untyped_subject_fails() -> None:
    seams = SEAMS + "    :Approval seam:lifecycle :expense_lifecycle .\n"
    assert violations(dataset(seams=seams)) == {("Approval", "-", "LifecycleShape", LIFECYCLE_MESSAGE)}


def test_a_lifecycle_that_is_not_a_machine_fails() -> None:
    seams = "\n    :Expense seam:lifecycle :s_submitted .\n"
    assert violations(dataset(seams=seams)) == {
        ("Expense", "lifecycle", "LifecycleShape", "seam:lifecycle points at a state:StateMachine.")
    }


# ── EffectiveLifecycleShape ──


def test_the_same_machine_directly_and_through_the_class_is_one_lifecycle() -> None:
    seams = SEAMS + "    :ExpenseShape seam:lifecycle :expense_lifecycle .\n"
    assert violations(dataset(seams=seams)) == set()


def test_a_direct_and_a_class_lifecycle_fail_with_the_message() -> None:
    seams = SEAMS + "    :ExpenseShape seam:lifecycle :payment_lifecycle .\n"
    found = violations(dataset(lifecycle=LIFECYCLE + PAYMENT_LIFECYCLE, seams=seams))
    assert found == {("ExpenseShape", "lifecycle", "EffectiveLifecycleShape", TWO_LIFECYCLES_MESSAGE)}


def test_two_target_classes_with_lifecycles_fail_with_the_message() -> None:
    shapes = SHAPES_GRAPH + "    :ExpenseShape sh:targetClass :Payment .\n"
    seams = SEAMS + "    :Payment seam:lifecycle :payment_lifecycle .\n"
    found = violations(dataset(lifecycle=LIFECYCLE + PAYMENT_LIFECYCLE, shapes=shapes, seams=seams))
    # TargetClassShape already allows one class (ADR-0023); the lifecycle count is
    # reported beside it, so each fact is named once.
    two_classes = [
        f"{EX.ExpenseShape} names more than one sh:targetClass ({EX[name]} among them); "
        "a shape describes at most one class (ADR-0023)."
        for name in ("Expense", "Payment")
    ]
    assert found == {
        ("ExpenseShape", "lifecycle", "EffectiveLifecycleShape", TWO_LIFECYCLES_MESSAGE),
        *(("ExpenseShape", "-", "TargetClassShape", message) for message in two_classes),
    }


# ── PublishesToShape ──


def test_a_transition_publishes_to_a_channel() -> None:
    extra = "    :payouts a comm:Channel .\n    :t_approve seam:publishesTo :payouts .\n"
    assert violations(dataset(extra=extra)) == set()


def test_a_transition_publishing_to_a_non_channel_fails() -> None:
    extra = "    :t_approve seam:publishesTo :s_approved .\n"
    assert violations(dataset(extra=extra)) == {
        ("t_approve", "publishesTo", "PublishesToShape", "seam:publishesTo points at a comm:Channel.")
    }


# ── visibleWhen and expectState through the class ──

COMPONENT = """
    :approve_button a ifml:ViewComponent , ifml:Details ; seam:reads :ExpenseShape ; seam:visibleWhen {state} .
"""
VISIBLE_WHEN_MESSAGE = (
    "Each seam:visibleWhen state is a state:hasState of the seam:lifecycle of the shape the component "
    "seam:reads, its own or that of its sh:targetClass."
)


def test_visible_when_through_a_class_lifecycle_conforms() -> None:
    assert violations(dataset(extra=COMPONENT.format(state=":s_submitted"))) == set()


def test_visible_when_a_state_outside_the_class_lifecycle_fails() -> None:
    found = violations(dataset(lifecycle=LIFECYCLE + PAYMENT_LIFECYCLE, extra=COMPONENT.format(state=":s_paid")))
    assert found == {("approve_button", "-", "VisibleWhenGuardShape", VISIBLE_WHEN_MESSAGE)}
