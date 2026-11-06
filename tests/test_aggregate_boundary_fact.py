"""The aggregate transaction boundary as a model fact (ADR-0035, M029/S04/T02).

``seam:aggregateMember`` goes from an aggregate (an ``owl:Class`` or ``sh:NodeShape``
with a ``seam:lifecycle``) to each ``sh:NodeShape`` it commits together. The seam
shapes check the fact: each negative case breaks one fact of an inline TriG dataset and
asserts its one violation by focus node, result path, owning shape and exact message.
The typed view ``model.aggregates`` lists the members by IRI, and chapter 11 declares
one member per aggregate, the facts its seams graph states.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import pytest
import seams
from rdflib import RDF, RDFS, Dataset, Graph, Namespace, URIRef
from rdflib.namespace import SH
from seams import ResolutionError

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
CHAPTER_11 = ROOT / "examples" / "expenses" / "chapter-11"
EX = Namespace("https://example.org/expenses/")
SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
@prefix :      <https://example.org/expenses/> .
"""

# An order aggregate on the class, with its own shape and a line shape of
# another class; and a payment aggregate on the class.
ONTOLOGY_GRAPH = """
    :orders_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/orders_ontology/1.0> .
    :Order a owl:Class ; rdfs:label "Order" ; seam:inModel :orders_ontology .
    :Line a owl:Class ; rdfs:label "Line" ; seam:inModel :orders_ontology .
    :Payment a owl:Class ; rdfs:label "Payment" ; seam:inModel :orders_ontology .
"""

SHAPES_GRAPH = """
    :orders_data a seam:Model ; seam:notation seam:ShapeGraph .
    :OrderShape a sh:NodeShape ; sh:targetClass :Order ; seam:inModel :orders_data .
    :LineShape a sh:NodeShape ; sh:targetClass :Line ; seam:inModel :orders_data .
    :PaymentShape a sh:NodeShape ; sh:targetClass :Payment ; seam:inModel :orders_data .
"""

LIFECYCLES = """
    :order_lifecycle a seam:Model , state:StateMachine ; seam:notation seam:Statechart ;
        state:initial :s_open ; state:hasState :s_open .
    :s_open a state:State ; rdfs:label "open" .
    :payment_lifecycle a seam:Model , state:StateMachine ; seam:notation seam:Statechart ;
        state:initial :s_due ; state:hasState :s_due .
    :s_due a state:State ; rdfs:label "due" .
"""

SEAMS = """
    :Order seam:lifecycle :order_lifecycle ;
        seam:aggregateMember :OrderShape , :LineShape .
    :Payment seam:lifecycle :payment_lifecycle .
"""

NOT_AN_AGGREGATE = (
    "Only an aggregate, an owl:Class or sh:NodeShape with a seam:lifecycle, has a seam:aggregateMember (ADR-0035)."
)
NOT_A_SHAPE = "seam:aggregateMember points at a sh:NodeShape."
TWO_AGGREGATES = (
    "A sh:NodeShape is the seam:aggregateMember of at most one aggregate; "
    f"it is a member of {EX.Order} and {EX.Payment}."
)


def dataset(seams_graph: str = SEAMS) -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:orders_ontology> {{{ONTOLOGY_GRAPH}}}\n"
        + f"\n<urn:seams:graph:model:orders_data> {{{SHAPES_GRAPH}}}\n"
        + f"\n<urn:seams:graph:model:order_lifecycle> {{{LIFECYCLES}}}\n"
        + f"\n<urn:seams:graph:seams> {{{seams_graph}}}\n"
    )


def violations(trig: str) -> set[tuple[str, str, str, str]]:
    """(focus node, result path, owning node shape, message) for every result, with the
    vocabularies merged into the data as ``seams check`` validates."""
    ds = Dataset()
    ds.parse(data=trig, format="trig")
    data = Graph()
    for vocabulary in sorted(ONTOLOGY.glob("*.ttl")):
        data.parse(vocabulary)
    for s, p, o, _graph in ds.quads((None, None, None, None)):
        data.add((s, p, o))
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=SHAPES, inference="none")
    assert isinstance(report, Graph)
    found: set[tuple[str, str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property shape is a blank node: report the node shape that owns it.
        owner = next(iter(SHAPES.subjects(SH.property, shape)), shape)  # type: ignore[arg-type]
        path = report.value(result, SH.resultPath)
        found.add(
            (
                str(report.value(result, SH.focusNode)).removeprefix(str(EX)),
                "-" if path is None else str(path).removeprefix(str(SEAM)),
                str(owner).removeprefix(str(SEAMSH)),
                str(report.value(result, SH.resultMessage)),
            )
        )
    return found


def load(tmp_path: Path, seams_graph: str = SEAMS) -> seams.Model:
    trig = tmp_path / "model.trig"
    trig.write_text(dataset(seams_graph), encoding="utf-8")
    return seams.load(trig)


# ── The term ──


def test_the_term_is_in_seam_1_5_and_is_a_layer_seam() -> None:
    vocabulary = Graph().parse(ONTOLOGY / "seam.ttl")
    assert (SEAM.aggregateMember, RDF.type, RDF.Property) in vocabulary
    assert vocabulary.value(SEAM.aggregateMember, SEAM.reveal) == SEAM.Layer
    assert str(vocabulary.value(SEAM.aggregateMember, RDFS.label)) == "aggregate member"
    # 1.5 added it; 1.6 (ADR-0037 seam:schedules) is a compatible widening that keeps it.
    assert seams.shipped_versions(ONTOLOGY)["seam"] == (1, 6)


# ── The seam shapes ──


def test_an_aggregate_with_members_conforms() -> None:
    assert violations(dataset()) == set()


def test_an_aggregate_on_a_shape_conforms() -> None:
    seams_graph = "\n    :OrderShape seam:lifecycle :order_lifecycle ; seam:aggregateMember :OrderShape .\n"
    assert violations(dataset(seams_graph)) == set()


def test_a_subject_with_no_lifecycle_fails() -> None:
    seams_graph = SEAMS + "    :Line seam:aggregateMember :PaymentShape .\n"
    assert violations(dataset(seams_graph)) == {("Line", "lifecycle", "AggregateMemberShape", NOT_AN_AGGREGATE)}


def test_a_member_that_is_not_a_shape_fails() -> None:
    seams_graph = SEAMS + "    :Payment seam:aggregateMember :s_due .\n"
    assert violations(dataset(seams_graph)) == {("Payment", "aggregateMember", "AggregateMemberShape", NOT_A_SHAPE)}


def test_a_shape_in_two_aggregates_fails_naming_both() -> None:
    seams_graph = SEAMS + "    :Payment seam:aggregateMember :LineShape .\n"
    assert violations(dataset(seams_graph)) == {("LineShape", "aggregateMember", "OneAggregateShape", TWO_AGGREGATES)}


# ── The typed view ──


def test_the_view_lists_the_aggregates_and_their_members_by_iri(tmp_path: Path) -> None:
    model = load(tmp_path)
    # :Payment names a lifecycle but no members: it declares no boundary.
    assert model.aggregates.iris() == (EX.Order,)
    order = model.aggregates.by_iri(":Order")
    assert order.members.iris() == (EX.LineShape, EX.OrderShape)
    assert order.lifecycle is not None and order.lifecycle.iri == EX.order_lifecycle
    shapes = model.shapes
    assert shapes.by_iri(":LineShape").aggregate == order
    assert shapes.by_iri(":PaymentShape").aggregate is None


def test_a_model_with_no_member_has_no_aggregate(tmp_path: Path) -> None:
    assert load(tmp_path, "\n    :Order seam:lifecycle :order_lifecycle .\n").aggregates == ()


def test_a_shape_in_two_aggregates_raises_naming_the_fact(tmp_path: Path) -> None:
    model = load(tmp_path, SEAMS + "    :Payment seam:aggregateMember :LineShape .\n")
    with pytest.raises(ResolutionError) as err:
        _ = model.shapes.by_iri(":LineShape").aggregate
    assert err.value.subject == str(EX.LineShape)
    assert err.value.predicate == str(SEAM.aggregateMember)
    assert err.value.detail == "a member of more than one aggregate: :Order, :Payment"


# ── Chapter 11 ──


def test_chapter_11_declares_one_member_per_aggregate_in_the_seams_graph() -> None:
    ds = Dataset()
    for trig in sorted(CHAPTER_11.glob("*.trig")):
        ds.parse(trig, format="trig")
    facts = sorted((str(s), str(o), str(g)) for s, _p, o, g in ds.quads((None, SEAM.aggregateMember, None, None)))
    assert facts == [
        (str(EX.Expense), str(EX.ExpenseShape), str(SEAMS_GRAPH)),
        (str(EX.Payment), str(EX.PaymentShape), str(SEAMS_GRAPH)),
    ]


def test_chapter_11_aggregates_through_the_view() -> None:
    model = seams.load(CHAPTER_11)
    assert [(a.iri, a.members.iris()) for a in model.aggregates] == [
        (EX.Expense, (EX.ExpenseShape,)),
        (EX.Payment, (EX.PaymentShape,)),
    ]
    # The approval is in another store, so it is another aggregate's business.
    assert model.shapes.by_iri(":ApprovalShape").aggregate is None
