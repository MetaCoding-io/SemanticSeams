"""seams.review_check (M017/S04, backlog R1): model review checks.

Each check gets a minimal inline TriG model and the test asserts the exact
findings. A model that declares its classes and properties yields none, and the
chat app yields the findings section 5.1 of
docs/research/2026-10-31-data-centric-model-and-copilot.md lists.
"""

from pathlib import Path

import pytest
import seams
from example_models import example_models
from seams import ReviewFinding, review_findings
from seams.review_check import (
    lifecycle_label_findings,
    shape_class_findings,
    target_class_findings,
    undeclared_path_findings,
)

ROOT = Path(__file__).resolve().parent.parent
CHAT = "https://example.org/chat/"
EX = "https://example.org/ex/"
SH = "http://www.w3.org/ns/shacl#"

PREFIXES = """\
@prefix :     <https://example.org/ex/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
"""

#: A model every check passes: classes targeted, properties declared, the
#: status a state IRI, and the lifecycle labels nowhere in a sh:in.
CLEAN = """
<urn:seams:graph:model:shapes> {
    :Order a owl:Class .
    :Line a owl:Class .
    :status a owl:ObjectProperty .
    :hasLine a owl:ObjectProperty .
    :note a owl:DatatypeProperty .
    :OrderShape a sh:NodeShape ; sh:targetClass :Order ;
        sh:property [ sh:path :status ; sh:in ( :s_open :s_closed ) ] ;
        sh:property [ sh:path :hasLine ; sh:class :Line ] ;
        sh:property [ sh:path [ sh:inversePath :hasLine ] ; sh:maxCount 1 ] ;
        sh:property [ sh:path :note ; sh:in ( "open" "urgent" ) ] .
    :LineShape a sh:NodeShape ; sh:targetClass :Line .
}
<urn:seams:graph:model:order_lifecycle> {
    :order_lifecycle a state:StateMachine ; state:hasState :s_open , :s_closed .
    :s_open a state:State ; rdfs:label "open" .
    :s_closed a state:State ; rdfs:label "closed" .
}
<urn:seams:graph:seams> {
    :OrderShape seam:lifecycle :order_lifecycle .
}
"""


def _load(tmp_path: Path, body: str) -> seams.Model:
    trig = tmp_path / "model.trig"
    trig.write_text(PREFIXES + body)
    return seams.load(trig)


def _edit(old: str, new: str) -> str:
    assert old in CLEAN, old
    return CLEAN.replace(old, new, 1)


def test_a_model_that_declares_its_facts_yields_no_finding(tmp_path: Path) -> None:
    assert review_findings(_load(tmp_path, CLEAN)) == []


# ── lifecycle labels copied into sh:in ──


def test_sh_in_copying_the_lifecycle_state_labels_is_a_finding(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit("sh:in ( :s_open :s_closed )", 'sh:in ( "closed" "open" )'))
    assert review_findings(model) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{EX}status",
            "sh:in on status copies the rdfs:labels of order_lifecycle's states, so it can drift "
            "from the lifecycle; use the state IRIs (s_closed, s_open)",
        )
    ]


def test_sh_in_with_a_value_that_is_no_state_label_is_not_a_finding(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit("sh:in ( :s_open :s_closed )", 'sh:in ( "open" "archived" )'))
    assert lifecycle_label_findings(model) == []


def test_a_shape_without_a_lifecycle_is_not_checked_for_labels(tmp_path: Path) -> None:
    body = _edit("sh:in ( :s_open :s_closed )", 'sh:in ( "open" )').replace(
        ":OrderShape seam:lifecycle :order_lifecycle .", ""
    )
    assert lifecycle_label_findings(_load(tmp_path, body)) == []


def test_a_looping_sh_in_list_is_read_up_to_where_it_loops(tmp_path: Path) -> None:
    body = _edit(
        "sh:in ( :s_open :s_closed )",
        'sh:in :broken ] .\n    :broken rdf:first "open" ; rdf:rest :broken .\n'
        "    :OrderShape sh:property [ sh:path :other",
    ).replace(":status a owl:ObjectProperty .", ":status a owl:ObjectProperty . :other a rdf:Property .")
    assert review_findings(_load(tmp_path, body)) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{EX}status",
            "sh:in on status copies the rdfs:labels of order_lifecycle's states, so it can drift "
            "from the lifecycle; use the state IRIs (s_open)",
        )
    ]


# ── sh:class pointing at a shape ──


def test_sh_class_naming_a_node_shape_is_a_finding(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit("sh:class :Line", "sh:class :LineShape"))
    assert review_findings(model) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{EX}hasLine",
            "sh:class on hasLine is LineShape, a sh:NodeShape, not a class; declare the class "
            "and give the shape sh:targetClass",
        )
    ]


def test_sh_class_naming_a_class_that_is_also_a_shape_is_still_a_finding(tmp_path: Path) -> None:
    """:Line is an owl:Class and an implicit-target sh:NodeShape: the target
    class check passes it, but sh:class still points at a shape."""
    model = _load(tmp_path, _edit(":Line a owl:Class .", ":Line a owl:Class , sh:NodeShape ."))
    assert shape_class_findings(model) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{EX}hasLine",
            "sh:class on hasLine is Line, a sh:NodeShape, not a class; declare the class "
            "and give the shape sh:targetClass",
        )
    ]


# ── shapes without a target class ──


def test_a_shape_without_sh_target_class_is_a_finding(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit(" sh:targetClass :Order ;", ""))
    assert review_findings(model) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{SH}targetClass",
            "OrderShape has no sh:targetClass, so it says what a form holds but not what class of thing it describes",
        )
    ]


def test_a_shape_that_is_itself_a_class_needs_no_target_class(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit(":Line a owl:Class .", ":Line a owl:Class . :Note a rdfs:Class , sh:NodeShape ."))
    assert target_class_findings(model) == []


# ── undeclared paths ──


def test_a_sh_path_nothing_declares_is_a_finding(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit(":note a owl:DatatypeProperty .", ""))
    assert review_findings(model) == [
        ReviewFinding(
            f"{EX}note",
            f"{SH}path",
            "note is a sh:path (used by OrderShape), but no rdf:type rdf:Property, owl:ObjectProperty, "
            "owl:DatatypeProperty or owl:AnnotationProperty declares it",
        )
    ]


def test_an_inverse_path_is_skipped_but_its_property_is_checked(tmp_path: Path) -> None:
    model = _load(tmp_path, _edit(":hasLine a owl:ObjectProperty .", ":hasLine a owl:AnnotationProperty ."))
    assert undeclared_path_findings(model) == []


# ── the examples ──


def test_the_chat_app_findings_are_the_research_notes() -> None:
    """Section 5.1: MessageShape's status sh:in, sh:class :MessageShape, both
    shapes without a target class, and all seven paths undeclared."""
    findings = review_findings(seams.load(ROOT / "examples/chat-app/chat-app.trig"))
    paths = ["content", "hasMessage", "id", "role", "status", "timestamp", "title"]
    undeclared = [
        ReviewFinding(
            f"{CHAT}{p}",
            f"{SH}path",
            f"{p} is a sh:path (used by {'ConversationShape' if p in ('hasMessage', 'id', 'title') else 'MessageShape'}),"
            " but no rdf:type rdf:Property, owl:ObjectProperty, owl:DatatypeProperty or owl:AnnotationProperty"
            " declares it",
        )
        for p in paths
    ]
    assert findings == sorted(
        [
            ReviewFinding(
                f"{CHAT}MessageShape",
                f"{CHAT}status",
                "sh:in on status copies the rdfs:labels of message_lifecycle's states, so it can drift from the "
                "lifecycle; use the state IRIs (s_composing, s_sending, s_streaming, s_complete, s_failed)",
            ),
            ReviewFinding(
                f"{CHAT}ConversationShape",
                f"{CHAT}hasMessage",
                "sh:class on hasMessage is MessageShape, a sh:NodeShape, not a class; declare the class and give "
                "the shape sh:targetClass",
            ),
            ReviewFinding(
                f"{CHAT}ConversationShape",
                f"{SH}targetClass",
                "ConversationShape has no sh:targetClass, so it says what a form holds but not what class of "
                "thing it describes",
            ),
            ReviewFinding(
                f"{CHAT}MessageShape",
                f"{SH}targetClass",
                "MessageShape has no sh:targetClass, so it says what a form holds but not what class of thing it "
                "describes",
            ),
            *undeclared,
        ]
    )


def test_chapter_8_flags_both_copied_status_lists() -> None:
    """Section 5.1: ExpenseShape and PaymentShape status repeat their lifecycles."""
    model = seams.load(ROOT / "examples/expenses/chapter-08/expenses.trig")
    assert [(f.subject, f.fact) for f in lifecycle_label_findings(model)] == [
        ("https://example.org/expenses/ExpenseShape", "https://example.org/expenses/status"),
        ("https://example.org/expenses/PaymentShape", "https://example.org/expenses/status"),
    ]


@pytest.mark.parametrize("model", example_models(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_example_is_reviewed_without_raising(model: Path) -> None:
    findings = review_findings(seams.load(model))
    assert findings == sorted(findings)
    assert all(isinstance(f, ReviewFinding) for f in findings)
