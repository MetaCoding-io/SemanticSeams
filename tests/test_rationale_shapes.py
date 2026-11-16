"""Decision-record shapes (ADR-0045, M033/S02).

Every dataset is inline TriG built from ``dataset()``: an architecture model with one
system and two containers, and two ``arch:DecisionRecord``s in the
architecture model's graph. One record references a container and the operation it
exposes; the other references a BPMN flow node IRI that no seam names, so it has no
triples of its own. The dataset conforms; each negative case breaks one fact and asserts the one
violation by focus node, result path and shape, and the messages are asserted exactly,
so a finding names the record and the predicate as ``seams check`` prints it.
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
ARCH = Namespace("https://w3id.org/seams/arch#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
DCTERMS_NS = "http://purl.org/dc/terms/"

PREFIXES = """\
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix hydra:   <http://www.w3.org/ns/hydra/core#> .
@prefix seam:    <https://w3id.org/seams/seam#> .
@prefix arch:    <https://w3id.org/seams/arch#> .
@prefix :        <https://example.org/expenses/> .
"""

ARCHITECTURE = """
    :expense_system a arch:System ; rdfs:label "Expenses" ;
        arch:contains :expense_api , :expense_db .
    :expense_api a arch:Container ; rdfs:label "Expense API" ; arch:technology "FastAPI" ;
        arch:dependsOn :expense_db .
    :expense_db a arch:Container ; rdfs:label "Expense DB" ; arch:technology "SQLite" .
    :submit_expense a hydra:Operation ; rdfs:label "Submit expense" ; hydra:method "POST" .
"""

ADR_0012 = """
    :adr_0012 a arch:DecisionRecord ;
        rdfs:label "Store expenses in SQLite" ;
        dcterms:identifier "ADR-0012" ;
        rdfs:seeAlso <https://example.org/docs/adr/0012-sqlite-store.md> ;
        dcterms:references :expense_db , :submit_expense .
"""

ADR_0013 = """
    :adr_0013 a arch:DecisionRecord ;
        rdfs:label "Approve large expenses by hand" ;
        dcterms:identifier "ADR-0013" ;
        dcterms:references <https://example.org/expenses/expense_process#approve_task> .
"""

SEAMS = """
    :expense_architecture a seam:Model ; seam:notation seam:C4 .
    :expense_api seam:exposes :submit_expense .
"""


def dataset(records: str = ADR_0012 + ADR_0013) -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_architecture> {{{ARCHITECTURE}{records}}}\n"
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
    if term is None:
        return "-"
    text = str(term)
    for prefix, short in (
        (str(EX), ""),
        (str(ARCH), ""),
        (str(SEAMSH), ""),
        (RDFS_NS, "rdfs:"),
        (DCTERMS_NS, "dcterms:"),
    ):
        if text.startswith(prefix):
            return short + text.removeprefix(prefix)
    return text


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


NODE = "An arch:DecisionRecord is an IRI, so the viewer can name and link it (ADR-0045)."
LABEL = "An arch:DecisionRecord has exactly one rdfs:label, a literal (ADR-0045)."
IDENTIFIER = 'An arch:DecisionRecord has exactly one dcterms:identifier, a string such as "ADR-0012" (ADR-0045).'
REFERENCES = "An arch:DecisionRecord dcterms:references at least one model element, each an IRI (ADR-0045)."
SEE_ALSO = "An arch:DecisionRecord has at most one rdfs:seeAlso, the IRI of its document (ADR-0045)."


def duplicate(record: str, identifier: str) -> str:
    return (
        f"{EX}{record}: another arch:DecisionRecord has the dcterms:identifier {identifier}; "
        "a record's identifier is its own (ADR-0045)."
    )


def record(body: str, subject: str = ":adr_0014") -> str:
    return f"\n    {subject} a arch:DecisionRecord ;\n{body} .\n"


# ── conforming ──


def test_records_referencing_a_container_an_operation_and_a_flow_node_conform() -> None:
    assert violations(dataset()) == set()


def test_a_record_with_no_see_also_conforms() -> None:
    assert violations(dataset(ADR_0013)) == set()


def test_a_model_with_no_records_conforms() -> None:
    assert violations(dataset("")) == set()


def test_a_language_tagged_label_conforms() -> None:
    body = '        rdfs:label "Rechnungen in SQLite"@de ;\n        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db'
    assert violations(dataset(ADR_0012 + record(body))) == set()


# ── one fact broken ──


def test_a_record_with_no_label_is_flagged() -> None:
    body = '        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "rdfs:label", "DecisionRecordShape")}
    assert messages(trig) == [LABEL]


def test_a_record_with_two_labels_is_flagged() -> None:
    body = '        rdfs:label "One" , "Two" ;\n        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "rdfs:label", "DecisionRecordShape")}
    assert messages(trig) == [LABEL]


def test_a_label_that_is_an_iri_is_flagged() -> None:
    body = '        rdfs:label :expense_db ;\n        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "rdfs:label", "DecisionRecordShape")}
    assert messages(trig) == [LABEL]


def test_a_record_with_no_identifier_is_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:references :expense_db'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:identifier", "DecisionRecordShape")}
    assert messages(trig) == [IDENTIFIER]


def test_a_record_with_two_identifiers_is_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014" , "ADR-0015" ;\n        dcterms:references :expense_db'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:identifier", "DecisionRecordShape")}
    assert messages(trig) == [IDENTIFIER]


def test_an_identifier_that_is_not_a_string_is_flagged() -> None:
    body = (
        '        rdfs:label "Keep a cache" ;\n        dcterms:identifier 14 ;\n        dcterms:references :expense_db'
    )
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:identifier", "DecisionRecordShape")}
    assert messages(trig) == [IDENTIFIER]


def test_two_records_with_one_identifier_are_each_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0012" ;\n        dcterms:references :expense_api'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {
        ("adr_0012", "dcterms:identifier", "DecisionRecordShape"),
        ("adr_0014", "dcterms:identifier", "DecisionRecordShape"),
    }
    assert messages(trig) == [duplicate("adr_0012", "ADR-0012"), duplicate("adr_0014", "ADR-0012")]


def test_a_record_that_references_nothing_is_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014"'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:references", "DecisionRecordShape")}
    assert messages(trig) == [REFERENCES]


def test_a_reference_that_is_a_literal_is_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db , "the API"'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:references", "DecisionRecordShape")}
    assert messages(trig) == [REFERENCES]


def test_a_reference_that_is_a_blank_node_is_flagged() -> None:
    body = '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014" ;\n        dcterms:references [ rdfs:label "the API" ]'
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "dcterms:references", "DecisionRecordShape")}
    assert messages(trig) == [REFERENCES]


def test_two_see_also_documents_are_flagged() -> None:
    body = (
        '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014" ;\n'
        "        rdfs:seeAlso <https://example.org/docs/a.md> , <https://example.org/docs/b.md> ;\n"
        "        dcterms:references :expense_db"
    )
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "rdfs:seeAlso", "DecisionRecordShape")}
    assert messages(trig) == [SEE_ALSO]


def test_a_see_also_that_is_a_literal_is_flagged() -> None:
    body = (
        '        rdfs:label "Keep a cache" ;\n        dcterms:identifier "ADR-0014" ;\n'
        '        rdfs:seeAlso "docs/adr/0014.md" ;\n        dcterms:references :expense_db'
    )
    trig = dataset(ADR_0012 + record(body))
    assert violations(trig) == {("adr_0014", "rdfs:seeAlso", "DecisionRecordShape")}
    assert messages(trig) == [SEE_ALSO]


def test_a_blank_node_record_is_flagged() -> None:
    blank = (
        '\n    [] a arch:DecisionRecord ;\n        rdfs:label "Keep a cache" ;\n'
        '        dcterms:identifier "ADR-0014" ;\n        dcterms:references :expense_db .\n'
    )
    trig = dataset(ADR_0012 + blank)
    found = violations(trig)
    assert len(found) == 1
    ((_focus, path, shape),) = found
    assert (path, shape) == ("-", "DecisionRecordIriShape")
    assert messages(trig) == [NODE]
