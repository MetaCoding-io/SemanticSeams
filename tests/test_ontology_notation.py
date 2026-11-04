"""The ontology notation (ADR-0022): seam:Ontology, gist vendored and pinned, imports
resolved offline by version IRI, and the typed ``model.ontologies`` view.

Models are inline TriG; the vendored ontology is the committed
``ontology/vendor/gistCore14.0.0.ttl``, copied into a temporary ontology directory
when a test needs another vendored file beside it."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pyshacl
import pytest
import seams
from rdflib import OWL, RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH
from seams import ImportStatus, ResolutionError, Superclass, VendoredOntology

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
VENDOR = ONTOLOGY / "vendor"
GIST_FILE = VENDOR / "gistCore14.0.0.ttl"
GIST_ONTOLOGY = URIRef("https://w3id.org/semanticarts/ontology/gistCore")
GIST_14_0 = URIRef("https://w3id.org/semanticarts/ontology/gistCore14.0.0")
GIST = Namespace("https://w3id.org/semanticarts/ns/ontology/gist/")
SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
EX = Namespace("https://example.org/expenses/")
ONTO = EX.expense_ontology

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix gist: <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix :     <https://example.org/expenses/> .
"""

# Classes written out of IRI order, so the view's sort is what orders them.
CLASSES = """
    :Payment a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Payment" ;
        skos:definition "Money the company transfers to reimburse an expense." ;
        seam:inModel :expense_ontology .

    :Expense a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Expense" ;
        skos:definition "Money an employee spent on the company's behalf and asks to have reimbursed." ;
        seam:inModel :expense_ontology .

    :TravelExpense a owl:Class ;
        rdfs:subClassOf :Expense , gist:Transation ;
        rdfs:label "Travel expense" ;
        seam:inModel :expense_ontology .

    :Approval a owl:Class ;
        rdfs:subClassOf gist:Determination ;
        rdfs:label "Approval" ;
        seam:inModel :expense_ontology .

    :amount a owl:DatatypeProperty ;
        rdfs:domain :Expense ;
        rdfs:label "amount" ;
        seam:inModel :expense_ontology .
"""


def ontology_trig(imports: str = "<https://w3id.org/semanticarts/ontology/gistCore14.0.0>", body: str = CLASSES) -> str:
    return f"""{PREFIXES}
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports {imports} .
{body}}}
"""


def write(tmp_path: Path, text: str, name: str = "model.trig") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def import_error(path: Path, ontology_dir: Path = ONTOLOGY) -> ResolutionError:
    with pytest.raises(ResolutionError) as err:
        seams.load(path, ontology_dir=ontology_dir)
    return err.value


# ── the vocabulary and the vendored file ──


def test_seam_ontology_is_a_notation_in_seam_1_1() -> None:
    vocabulary = Graph().parse(ONTOLOGY / "seam.ttl")
    assert (SEAM.Ontology, RDF.type, SEAM.Notation) in vocabulary
    assert seams.shipped_versions(ONTOLOGY)["seam"] == (1, 1)


def test_the_vendored_gist_matches_its_recorded_checksum() -> None:
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith(f"| `{GIST_FILE.name}`"))
    recorded = re.findall(r"`([0-9a-f]{64})`", row)
    assert recorded == [hashlib.sha256(GIST_FILE.read_bytes()).hexdigest()], "never edit a vendored file by hand"
    assert f"`{GIST_14_0}`" in row


def test_the_vendored_gist_keeps_its_licence() -> None:
    header = Graph().parse(GIST_FILE)
    licence = header.value(GIST_ONTOLOGY, GIST.license)
    assert licence == Literal(
        "https://creativecommons.org/licenses/by/4.0/", datatype=URIRef("http://www.w3.org/2001/XMLSchema#anyURI")
    )


def test_vendored_ontologies_are_indexed_by_their_header() -> None:
    assert seams.vendored_ontologies(ONTOLOGY) == (VendoredOntology(GIST_ONTOLOGY, GIST_14_0, GIST_FILE.resolve()),)


def test_no_vendor_directory_vendors_nothing(tmp_path: Path) -> None:
    assert seams.vendored_ontologies(tmp_path) == ()


def test_a_vendored_file_without_one_version_iri_is_refused(tmp_path: Path) -> None:
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "two.ttl").write_text(
        "<urn:o> a <http://www.w3.org/2002/07/owl#Ontology> ;\n"
        "    <http://www.w3.org/2002/07/owl#versionIRI> <urn:o1> , <urn:o2> .\n",
        encoding="utf-8",
    )
    with pytest.raises(ResolutionError) as err:
        seams.vendored_ontologies(tmp_path)
    assert (err.value.subject, err.value.predicate) == ("urn:o", str(OWL.versionIRI))
    assert err.value.detail == "expected one owl:versionIRI in vendor/two.ttl, found urn:o1, urn:o2"


# ── the load check ──


def test_a_gist_import_resolves_and_stays_out_of_the_dataset(tmp_path: Path) -> None:
    path = write(tmp_path, ontology_trig())
    model = seams.load(path, ontology_dir=ONTOLOGY)
    vendored = VendoredOntology(GIST_ONTOLOGY, GIST_14_0, GIST_FILE.resolve())
    assert model.imports == (vendored,)
    assert model.import_statuses == (ImportStatus(ONTO, GIST_14_0, vendored, ""),)
    assert model.import_statuses[0].resolved and model.import_statuses[0].error is None
    unchecked = seams.load(path, ontology_dir=ONTOLOGY, check_imports=False)
    assert len(model.ds) == len(unchecked.ds)
    assert (GIST.Transaction, RDF.type, OWL.Class) not in model.ds
    assert model.hash == seams.model_hash(path)


def test_an_unknown_import_is_refused(tmp_path: Path) -> None:
    err = import_error(write(tmp_path, ontology_trig("<https://example.org/other/1.0>")))
    assert (err.subject, err.predicate) == (str(ONTO), str(OWL.imports))
    assert err.detail == "imports <https://example.org/other/1.0>, which no file in ontology/vendor/ declares"


@pytest.mark.parametrize(
    ("imported", "detail"),
    [
        ("gistCore14.1.0", "imports gistCore14.1.0; the vendored version is gistCore14.0.0"),
        ("gistCore", "imports gistCore; the vendored version is gistCore14.0.0"),
    ],
)
def test_a_wrong_gist_version_is_refused(tmp_path: Path, imported: str, detail: str) -> None:
    err = import_error(write(tmp_path, ontology_trig(f"<https://w3id.org/semanticarts/ontology/{imported}>")))
    assert (err.subject, err.predicate, err.detail) == (str(ONTO), str(OWL.imports), detail)


def test_a_vocabulary_version_import_is_misplaced(tmp_path: Path) -> None:
    err = import_error(write(tmp_path, ontology_trig("<https://w3id.org/seams/seam/1.1>")))
    assert err.detail == (
        "imports <https://w3id.org/seams/seam/1.1>; declare vocabulary versions in the manifest graph (ADR-0021)"
    )


def test_two_vendored_versions_are_both_named(tmp_path: Path) -> None:
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY, ontology_dir)
    text = GIST_FILE.read_text(encoding="utf-8").replace("gistCore14.0.0>", "gistCore14.1.0>", 1)
    (ontology_dir / "vendor" / "gistCore14.1.0.ttl").write_text(text, encoding="utf-8")
    path = write(tmp_path, ontology_trig("<https://w3id.org/semanticarts/ontology/gistCore15.0.0>"))
    err = import_error(path, ontology_dir)
    assert err.detail == "imports gistCore15.0.0; the vendored versions are gistCore14.0.0, gistCore14.1.0"
    resolved = seams.load(write(tmp_path, ontology_trig(), "ok.trig"), ontology_dir=ontology_dir)
    assert [v.version for v in resolved.imports] == [GIST_14_0]


def test_the_first_fault_in_sorted_order_is_raised(tmp_path: Path) -> None:
    imports = "<https://example.org/z/1.0> , <https://example.org/a/1.0> , <https://w3id.org/semanticarts/ontology/gistCore14.0.0>"
    path = write(tmp_path, ontology_trig(imports))
    for _ in range(3):
        assert import_error(path).detail.startswith("imports <https://example.org/a/1.0>,")
    statuses = seams.load(path, ontology_dir=ONTOLOGY, check_imports=False).import_statuses
    assert [str(s.imported) for s in statuses] == [
        "https://example.org/a/1.0",
        "https://example.org/z/1.0",
        str(GIST_14_0),
    ]
    assert [s.resolved for s in statuses] == [False, False, True]
    error = statuses[0].error
    assert error is not None and (error.subject, error.predicate) == (str(ONTO), str(OWL.imports))


def test_imports_of_other_notations_are_not_ontology_imports(tmp_path: Path) -> None:
    text = f"""{PREFIXES}
<urn:seams:graph:model:data> {{
    :data a seam:Model ; seam:notation seam:ShapeGraph ; rdfs:label "Data" ;
        owl:imports <https://example.org/other/1.0> .
}}
"""
    model = seams.load(write(tmp_path, text), ontology_dir=ONTOLOGY)
    assert (model.imports, model.import_statuses, tuple(model.ontologies)) == ((), (), ())


# ── the typed view ──


def test_the_view_lists_classes_sorted_with_labels_definitions_and_superclasses(tmp_path: Path) -> None:
    model = seams.load(write(tmp_path, ontology_trig()), ontology_dir=ONTOLOGY)
    ontology = model.ontologies.only()
    assert ontology.iri == ONTO and ontology.label == "Expense Ontology"
    assert ontology.version_iri == URIRef("https://example.org/expenses/expense_ontology/1.0")
    assert ontology.imports == (GIST_14_0,)
    classes = ontology.classes()
    assert [c.iri for c in classes] == [EX.Approval, EX.Expense, EX.Payment, EX.TravelExpense]
    assert [c.label for c in classes] == ["Approval", "Expense", "Payment", "Travel expense"]
    expense = classes.by_iri(":Expense")
    assert expense.definition == "Money an employee spent on the company's behalf and asks to have reimbursed."
    assert classes.by_iri(":Approval").definition is None
    assert expense.model == ONTO
    assert expense.superclasses == (
        Superclass(GIST.Transaction, "Transaction", "An exchange or transfer of goods, services, or funds.", GIST_14_0),
    )
    determination = classes.by_iri(":Approval").superclasses[0]
    assert (determination.iri, determination.label, determination.source) == (
        GIST.Determination,
        "Determination",
        GIST_14_0,
    )
    travel = classes.by_iri(":TravelExpense").superclasses
    assert [(s.iri, s.label, s.source) for s in travel] == [
        (EX.Expense, "Expense", ONTO),
        (GIST.Transation, "Transation", None),
    ]
    assert expense.properties.iris() == (EX.amount,)


def test_an_unresolved_import_leaves_gist_superclasses_without_a_source(tmp_path: Path) -> None:
    path = write(tmp_path, ontology_trig("<https://w3id.org/semanticarts/ontology/gistCore14.1.0>"))
    model = seams.load(path, ontology_dir=ONTOLOGY, check_imports=False)
    expense = model.ontologies.only().classes().by_iri(":Expense")
    assert expense.superclasses == (Superclass(GIST.Transaction, "Transaction", None, None),)


def test_the_view_is_the_same_on_every_load(tmp_path: Path) -> None:
    path = write(tmp_path, ontology_trig())

    def snapshot() -> list[tuple[str, str, str | None, tuple[Superclass, ...]]]:
        model = seams.load(path, ontology_dir=ONTOLOGY)
        return [(str(c.iri), c.label, c.definition, c.superclasses) for c in model.ontologies.only().classes()]

    assert snapshot() == snapshot() == snapshot()


def test_a_model_without_an_ontology_has_none(tmp_path: Path) -> None:
    model = seams.load(ROOT / "examples" / "expenses" / "chapter-08")
    assert tuple(model.ontologies) == () and model.imports == ()


# ── the shapes ──


def _violations(path: Path) -> set[tuple[str, str]]:
    data = Graph()
    for quad_graph in seams.load(path, ontology_dir=ONTOLOGY, check_imports=False).ds.graphs():
        data += quad_graph
    for vocabulary in sorted(ONTOLOGY.glob("*.ttl")):
        data.parse(vocabulary)
    shapes = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=shapes, inference="none")
    assert isinstance(report, Graph)
    found: set[tuple[str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property shape is a blank node: report the node shape that owns it.
        owner = next(iter(shapes.subjects(SH.property, shape)), shape)
        found.add((str(report.value(result, SH.focusNode)), str(owner)))
    return found


def test_the_ontology_conforms_to_the_seam_shapes(tmp_path: Path) -> None:
    assert _violations(write(tmp_path, ontology_trig())) == set()


def test_a_class_needs_a_label_and_its_model(tmp_path: Path) -> None:
    body = CLASSES + "\n    :Bare a owl:Class .\n"
    assert _violations(write(tmp_path, ontology_trig(body=body))) == {(str(EX.Bare), str(SEAMSH.OntologyClassShape))}


def test_an_ontology_needs_exactly_one_version_iri(tmp_path: Path) -> None:
    none = ontology_trig().replace("owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;", "")
    assert _violations(write(tmp_path, none)) == {(str(ONTO), str(SEAMSH.OntologyModelShape))}
    two = ontology_trig().replace(
        "owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;",
        "owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> , <https://example.org/v2> ;",
    )
    assert _violations(write(tmp_path, two)) == {(str(ONTO), str(SEAMSH.OntologyModelShape))}
    untyped = ontology_trig().replace("a seam:Model , owl:Ontology ;", "a seam:Model ;")
    assert _violations(write(tmp_path, untyped)) == {(str(ONTO), str(SEAMSH.OntologyModelShape))}
