"""Domain and bounded-context shapes (ADR-0030 section 6, M028/S03).

Every dataset is inline TriG built from ``dataset()``: an architecture model declaring
two domains and two contexts, and five models the contexts own between them. The
dataset conforms; each negative case breaks one fact and asserts the one violation by
focus node, result path and shape, so a finding names the element and the predicate as
``seams check`` prints it. A dataset with no context is one implicit context and
conforms with every model unowned.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
from rdflib import RDF, RDFS, Dataset, Graph, Namespace, URIRef
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
EX = Namespace("https://example.org/expenses/")
ARCH = Namespace("https://w3id.org/seams/arch#")
SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
INVERSE_CONTAINS = "inverse arch:contains"
INVERSE_OWNS = "inverse seam:owns"

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix :     <https://example.org/expenses/> .
"""

DOMAINS = """
    :expense_management a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_system , :expense_context .
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context .
    :expense_system a arch:System ; rdfs:label "Expenses" ; arch:contains :expense_api .
    :expense_api a arch:Container ; rdfs:label "Expense API" .
"""

CONTEXTS = """
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" .
"""

MODELS = """
    :expense_architecture a seam:Model ; seam:notation seam:C4 .
    :expense_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> .
    :finance_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/expenses/finance_ontology/1.0> .
    :expense_data a seam:Model ; seam:notation seam:ShapeGraph .
    :finance_data a seam:Model ; seam:notation seam:ShapeGraph .
"""

OWNS = """
    :expense_context seam:owns :expense_ontology , :expense_data .
    :finance_context seam:owns :finance_ontology , :finance_data .
"""


def dataset(
    domains: str = DOMAINS, contexts: str = CONTEXTS, models: str = MODELS, owns: str = OWNS, extra: str = ""
) -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_architecture> {{{domains}{contexts}}}\n"
        + f"\n<urn:seams:graph:seams> {{{models}{owns}{extra}}}\n"
    )


def _path(report: Graph, result: object) -> str:
    path = report.value(result, SH.resultPath)  # type: ignore[arg-type]
    inverse = report.value(path, SH.inversePath) if path is not None else None  # type: ignore[arg-type]
    if inverse is not None:
        return "inverse " + {ARCH.contains: "arch:contains", SEAM.owns: "seam:owns"}[inverse]
    return {RDFS.label: "rdfs:label", ARCH.classification: "arch:classification", SEAM.owns: "seam:owns"}.get(
        path,  # type: ignore[arg-type]
        "-" if path is None else str(path),
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


def violations(trig: str) -> set[tuple[str, str, str]]:
    """(focus node, result path, owning node shape) for every result."""
    report = validate(trig)
    found: set[tuple[str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property shape is a blank node: report the node shape that owns it.
        owner = next(iter(SHAPES.subjects(SH.property, shape)), shape)  # type: ignore[arg-type]
        focus = report.value(result, SH.focusNode)
        found.add((str(focus).removeprefix(str(EX)), _path(report, result), str(owner).removeprefix(str(SEAMSH))))
    return found


def messages(trig: str) -> list[str]:
    return sorted(str(m) for m in validate(trig).objects(None, SH.resultMessage))


# ── conforming ──


def test_two_contexts_in_two_domains_conform() -> None:
    assert violations(dataset()) == set()


def test_a_dataset_with_no_context_is_one_implicit_context() -> None:
    assert violations(dataset(domains="", contexts="", owns="")) == set()


def test_domains_without_contexts_leave_models_unowned() -> None:
    domains = DOMAINS.replace(" , :expense_context", "").replace("arch:contains :finance_context ", "")
    assert violations(dataset(domains=domains, contexts="", owns="")) == set()


# ── DomainShape ──


def test_a_domain_needs_a_classification() -> None:
    domains = DOMAINS.replace("arch:classification arch:Core ;", "")
    assert violations(dataset(domains=domains)) == {("finance", "arch:classification", "DomainShape")}


def test_a_domain_has_one_classification() -> None:
    domains = DOMAINS.replace("arch:classification arch:Core ;", "arch:classification arch:Core , arch:Generic ;")
    assert violations(dataset(domains=domains)) == {("finance", "arch:classification", "DomainShape")}


def test_a_classification_is_one_of_the_three() -> None:
    domains = DOMAINS.replace("arch:classification arch:Core ;", "arch:classification :Strategic ;")
    assert violations(dataset(domains=domains)) == {("finance", "arch:classification", "DomainShape")}


def test_a_domain_needs_one_label() -> None:
    domains = DOMAINS.replace('rdfs:label "Finance" ;', "")
    assert violations(dataset(domains=domains)) == {("finance", "rdfs:label", "DomainShape")}


# ── BoundedContextShape ──


def test_a_context_in_no_domain_is_refused() -> None:
    domains = DOMAINS.replace("arch:contains :finance_context ", "")
    assert violations(dataset(domains=domains)) == {("finance_context", INVERSE_CONTAINS, "BoundedContextShape")}


def test_a_context_in_two_domains_is_refused() -> None:
    domains = DOMAINS.replace("arch:contains :finance_context ", "arch:contains :finance_context , :expense_context ")
    assert violations(dataset(domains=domains)) == {("expense_context", INVERSE_CONTAINS, "BoundedContextShape")}


def test_a_context_needs_one_label() -> None:
    contexts = CONTEXTS.replace(' ; rdfs:label "Payouts"', "")
    assert violations(dataset(contexts=contexts)) == {("finance_context", "rdfs:label", "BoundedContextShape")}


def test_a_context_owning_no_ontology_is_refused() -> None:
    owns = OWNS.replace(":finance_ontology , ", "")
    assert violations(dataset(owns=owns)) == {
        ("finance_context", "seam:owns", "BoundedContextShape"),
        # The ontology is now unowned, which the dataset's contexts refuse.
        ("finance_ontology", "seam:owns", "ModelOwnerShape"),
    }


def test_a_context_owning_two_ontologies_is_refused() -> None:
    owns = OWNS.replace(":expense_ontology , :expense_data .", ":expense_data .").replace(
        ":finance_ontology , :finance_data .", ":expense_ontology , :finance_ontology , :finance_data ."
    )
    assert violations(dataset(owns=owns)) == {
        ("finance_context", "seam:owns", "BoundedContextShape"),
        ("expense_context", "seam:owns", "BoundedContextShape"),
    }


# ── ModelOwnerShape ──


def test_a_model_owned_twice_is_refused() -> None:
    owns = OWNS + "    :finance_context seam:owns :expense_data .\n"
    assert violations(dataset(owns=owns)) == {("expense_data", INVERSE_OWNS, "ModelOwnerShape")}


def test_an_unowned_model_is_refused_once_contexts_are_declared() -> None:
    owns = OWNS.replace(" , :finance_data", "")
    assert violations(dataset(owns=owns)) == {("finance_data", "seam:owns", "ModelOwnerShape")}


def test_the_architecture_model_is_never_owned_and_need_not_be() -> None:
    assert ("expense_architecture", "seam:owns", "ModelOwnerShape") not in violations(dataset())


# ── OwnsTargetShape ──


def test_owning_something_that_is_not_a_model_is_refused() -> None:
    owns = OWNS + "    :finance_context seam:owns :expense_system .\n"
    assert violations(dataset(owns=owns)) == {("expense_system", "-", "OwnsTargetShape")}


# ── messages ──


def test_each_message_names_the_predicate() -> None:
    broken = dataset(
        domains=DOMAINS.replace("arch:classification arch:Core ;", "").replace("arch:contains :finance_context ", ""),
        owns=OWNS.replace(" , :finance_data", "")
        + "    :finance_context seam:owns :expense_system , :expense_data .\n",
    )
    assert messages(broken) == [
        "A seam:Model is seam:owns'ed by at most one arch:BoundedContext.",
        "An arch:BoundedContext is arch:contains'ed by exactly one arch:Domain.",
        "An arch:Domain has exactly one arch:classification: arch:Core, arch:Supporting or arch:Generic.",
        "Once the dataset declares an arch:BoundedContext, every seam:Model whose notation is not seam:C4 is "
        "seam:owns'ed by exactly one.",
        "seam:owns points at a seam:Model.",
    ]


def test_the_shapes_are_declared() -> None:
    for name in ("DomainShape", "BoundedContextShape", "ModelOwnerShape", "OwnsTargetShape"):
        assert (URIRef(SEAMSH[name]), RDF.type, SH.NodeShape) in SHAPES, name
