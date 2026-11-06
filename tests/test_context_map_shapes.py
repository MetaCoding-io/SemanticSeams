"""Context-map relationship shapes (ADR-0032, M029/S01).

Every dataset is inline TriG built from ``dataset()``: an architecture model declaring
two domains, three contexts and one ``arch:ContextRelationship`` (expense upstream of
finance, conformist), and the models the contexts own. The dataset conforms; each
negative case breaks one fact and asserts the one violation by focus node, result path
and shape, and the messages are asserted exactly, so a finding names the relationship
and the predicate as ``seams check`` prints it. A dataset with contexts and no
relationship is a context map with no lines and conforms.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
from rdflib import RDF, Dataset, Graph, Namespace, URIRef
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
VOCABULARY = Graph().parse(ONTOLOGY / "arch.ttl")
EX = Namespace("https://example.org/expenses/")
ARCH = Namespace("https://w3id.org/seams/arch#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix :     <https://example.org/expenses/> .
"""

CONTEXTS = """
    :expense_management a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_context , :travel_context .
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" .
    :travel_context a arch:BoundedContext ; rdfs:label "Travel" .
    :expense_system a arch:System ; rdfs:label "Expenses" ; arch:contains :expense_api .
    :expense_api a arch:Container ; rdfs:label "Expense API" .
"""

RELATIONSHIPS = """
    :expense_to_finance a arch:ContextRelationship ;
        arch:upstream :expense_context ;
        arch:downstream :finance_context ;
        arch:relationshipType arch:Conformist .
"""

SEAMS = """
    :expense_architecture a seam:Model ; seam:notation seam:C4 .
    :expense_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> .
    :finance_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/finance_ontology/1.0> .
    :travel_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/travel_ontology/1.0> .
    :expense_context seam:owns :expense_ontology .
    :finance_context seam:owns :finance_ontology .
    :travel_context seam:owns :travel_ontology .
"""


def dataset(relationships: str = RELATIONSHIPS) -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_architecture> {{{CONTEXTS}{relationships}}}\n"
        + f"\n<urn:seams:graph:seams> {{{SEAMS}}}\n"
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
    return "-" if term is None else str(term).removeprefix(str(EX)).removeprefix(str(ARCH)).removeprefix(str(SEAMSH))


def violations(trig: str) -> set[tuple[str, str, str]]:
    """(focus node, result path, owning node shape) for every result."""
    report = validate(trig)
    found: set[tuple[str, str, str]] = set()
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
            )
        )
    return found


def messages(trig: str) -> list[str]:
    return sorted(str(m) for m in validate(trig).objects(None, SH.resultMessage))


UPSTREAM = "An arch:ContextRelationship has exactly one arch:upstream, an arch:BoundedContext."
DOWNSTREAM = "An arch:ContextRelationship has exactly one arch:downstream, an arch:BoundedContext."
TYPE = (
    "An arch:ContextRelationship has exactly one arch:relationshipType: arch:CustomerSupplier, "
    "arch:Conformist, arch:AntiCorruptionLayer, arch:PublishedLanguage or arch:SharedKernel."
)
DISTINCT = "An arch:ContextRelationship's arch:upstream and arch:downstream are two different contexts."
ONE_PER_PAIR = "Two contexts have at most one arch:ContextRelationship between them, in either direction."
TERMS = "Only an arch:ContextRelationship has an arch:upstream, arch:downstream or arch:relationshipType."


def second(upstream: str, downstream: str, kind: str = "arch:CustomerSupplier") -> str:
    return f"""
    :second a arch:ContextRelationship ;
        arch:upstream {upstream} ;
        arch:downstream {downstream} ;
        arch:relationshipType {kind} .
"""


# ── conforming ──


def test_one_relationship_between_two_contexts_conforms() -> None:
    assert violations(dataset()) == set()


def test_contexts_with_no_relationship_conform() -> None:
    assert violations(dataset(relationships="")) == set()


def test_every_relationship_type_conforms() -> None:
    for kind in ("CustomerSupplier", "Conformist", "AntiCorruptionLayer", "PublishedLanguage", "SharedKernel"):
        assert violations(dataset(RELATIONSHIPS.replace("arch:Conformist", f"arch:{kind}"))) == set(), kind


def test_relationships_over_different_pairs_conform() -> None:
    assert violations(dataset(RELATIONSHIPS + second(":expense_context", ":travel_context"))) == set()


# ── upstream and downstream ──


def test_a_relationship_needs_an_upstream() -> None:
    broken = RELATIONSHIPS.replace("arch:upstream :expense_context ;", "")
    assert violations(dataset(broken)) == {("expense_to_finance", "upstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [UPSTREAM]


def test_a_relationship_has_one_upstream() -> None:
    broken = RELATIONSHIPS.replace(
        "arch:upstream :expense_context ;", "arch:upstream :expense_context , :travel_context ;"
    )
    assert violations(dataset(broken)) == {("expense_to_finance", "upstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [UPSTREAM]


def test_an_upstream_that_is_not_a_context_is_refused() -> None:
    broken = RELATIONSHIPS.replace("arch:upstream :expense_context ;", "arch:upstream :expense_system ;")
    assert violations(dataset(broken)) == {("expense_to_finance", "upstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [UPSTREAM]


def test_a_relationship_needs_a_downstream() -> None:
    broken = RELATIONSHIPS.replace("arch:downstream :finance_context ;", "")
    assert violations(dataset(broken)) == {("expense_to_finance", "downstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [DOWNSTREAM]


def test_a_downstream_that_is_not_a_context_is_refused() -> None:
    broken = RELATIONSHIPS.replace("arch:downstream :finance_context ;", "arch:downstream :finance ;")
    assert violations(dataset(broken)) == {("expense_to_finance", "downstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [DOWNSTREAM]


def test_a_context_is_not_upstream_of_itself() -> None:
    broken = RELATIONSHIPS.replace("arch:downstream :finance_context ;", "arch:downstream :expense_context ;")
    assert violations(dataset(broken)) == {("expense_to_finance", "downstream", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [DISTINCT]


# ── relationship type ──


def test_a_relationship_needs_a_type() -> None:
    broken = RELATIONSHIPS.replace(" ;\n        arch:relationshipType arch:Conformist", "")
    assert violations(dataset(broken)) == {("expense_to_finance", "relationshipType", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [TYPE]


def test_a_relationship_has_one_type() -> None:
    broken = RELATIONSHIPS.replace("arch:Conformist", "arch:Conformist , arch:SharedKernel")
    assert violations(dataset(broken)) == {("expense_to_finance", "relationshipType", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [TYPE]


def test_a_type_is_one_of_the_five() -> None:
    broken = RELATIONSHIPS.replace("arch:Conformist", ":SeparateWays")
    assert violations(dataset(broken)) == {("expense_to_finance", "relationshipType", "ContextRelationshipShape")}
    assert messages(dataset(broken)) == [TYPE]


# ── one relationship per pair ──


def test_two_relationships_over_one_pair_are_refused() -> None:
    broken = RELATIONSHIPS + second(":expense_context", ":finance_context")
    assert violations(dataset(broken)) == {
        ("expense_to_finance", "upstream", "ContextRelationshipShape"),
        ("second", "upstream", "ContextRelationshipShape"),
    }
    assert messages(dataset(broken)) == [ONE_PER_PAIR, ONE_PER_PAIR]


def test_the_pair_is_unordered() -> None:
    broken = RELATIONSHIPS + second(":finance_context", ":expense_context")
    assert violations(dataset(broken)) == {
        ("expense_to_finance", "upstream", "ContextRelationshipShape"),
        ("second", "upstream", "ContextRelationshipShape"),
    }
    assert messages(dataset(broken)) == [ONE_PER_PAIR, ONE_PER_PAIR]


# ── the terms belong to a relationship ──


def test_upstream_on_something_that_is_not_a_relationship_is_refused() -> None:
    broken = RELATIONSHIPS + "    :finance_context arch:upstream :expense_context .\n"
    assert violations(dataset(broken)) == {("finance_context", "-", "ContextRelationshipTermsShape")}
    assert messages(dataset(broken)) == [TERMS]


def test_a_type_on_something_that_is_not_a_relationship_is_refused() -> None:
    broken = RELATIONSHIPS + "    :expense_system arch:relationshipType arch:Conformist .\n"
    assert violations(dataset(broken)) == {("expense_system", "-", "ContextRelationshipTermsShape")}
    assert messages(dataset(broken)) == [TERMS]


# ── vocabulary ──


def test_the_shapes_are_declared() -> None:
    for name in ("ContextRelationshipShape", "ContextRelationshipTermsShape"):
        assert (URIRef(SEAMSH[name]), RDF.type, SH.NodeShape) in SHAPES, name


def test_the_relationship_types_are_the_five_individuals() -> None:
    kinds = sorted(str(s).removeprefix(str(ARCH)) for s in VOCABULARY.subjects(RDF.type, ARCH.RelationshipType))
    assert kinds == ["AntiCorruptionLayer", "Conformist", "CustomerSupplier", "PublishedLanguage", "SharedKernel"]
