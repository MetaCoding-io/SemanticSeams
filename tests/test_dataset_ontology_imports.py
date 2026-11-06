"""Dataset-local ontology imports (ADR-0030 section 4) and directory models.

An ontology's ``owl:imports`` resolves first to another ``seam:Ontology`` model
of the same Dataset, matched by its ``owl:versionIRI``, then to the files in
``ontology/vendor/``. A model may be a directory of TriG files, one per bounded
context by convention (ADR-0030 section 3), and ``seams.toml`` may name it
``model = "."``.

Models are inline TriG written to a temporary directory: ``expenses.trig`` holds
the expense ontology, ``finance.trig`` the finance ontology it imports."""

from __future__ import annotations

from pathlib import Path

import pytest
import seams
from rdflib import OWL, URIRef
from seams import DatasetOntology, ImportStatus, ResolutionError
from seams_cli.project import load_project, resolve_model

from viewer.ontologygraph import ontology_health

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
EX = "https://example.org/expenses/"
EXPENSE = URIRef(EX + "expense_ontology")
FINANCE = URIRef(EX + "finance_ontology")
FINANCE_1_0 = URIRef(EX + "finance_ontology/1.0")
GIST_14_0 = URIRef("https://w3id.org/semanticarts/ontology/gistCore14.0.0")

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix gist: <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix :     <https://example.org/expenses/> .
"""


def expenses_trig(imports: str = "<https://example.org/expenses/finance_ontology/1.0>") -> str:
    return f"""{PREFIXES}
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.1> ;
        owl:imports {imports} .

    :Expense a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Expense" ;
        seam:inModel :expense_ontology .

    :Reimbursement a owl:Class ;
        rdfs:subClassOf :Payment ;
        rdfs:label "Reimbursement" ;
        seam:inModel :expense_ontology .
}}
"""


FINANCE_TRIG = f"""{PREFIXES}
<urn:seams:graph:model:finance_ontology> {{
    :finance_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Finance Ontology" ;
        owl:versionIRI <https://example.org/expenses/finance_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .

    :Payment a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Payment" ;
        seam:inModel :finance_ontology .
}}
"""


def write_model(tmp_path: Path, expenses: str | None = None, finance: str = FINANCE_TRIG) -> Path:
    directory = tmp_path / "model"
    directory.mkdir()
    (directory / "expenses.trig").write_text(expenses_trig() if expenses is None else expenses, encoding="utf-8")
    (directory / "finance.trig").write_text(finance, encoding="utf-8")
    return directory


def import_error(path: Path) -> ResolutionError:
    with pytest.raises(ResolutionError) as err:
        seams.load(path, ontology_dir=ONTOLOGY)
    return err.value


# ── a directory model ──


def test_a_directory_model_loads_both_files_into_one_dataset(tmp_path: Path) -> None:
    directory = write_model(tmp_path)
    model = seams.load(directory, ontology_dir=ONTOLOGY)
    assert model.is_directory and model.base_dir == directory.resolve()
    assert [p.name for p in model.files] == ["expenses.trig", "finance.trig"]
    assert [o.iri for o in model.ontologies] == [EXPENSE, FINANCE]
    assert seams.model_dir(directory) == directory.resolve()
    assert seams.model_dir(directory / "expenses.trig") == directory.resolve()


def test_editing_either_file_changes_the_directory_hash(tmp_path: Path) -> None:
    directory = write_model(tmp_path)
    before = seams.model_hash(directory)
    finance = directory / "finance.trig"
    finance.write_text(finance.read_text(encoding="utf-8").replace('"Payment"', '"Payout"'), encoding="utf-8")
    assert seams.model_hash(directory) != before


# ── resolution against the dataset ──


def test_an_import_of_a_dataset_ontology_version_resolves_to_that_model(tmp_path: Path) -> None:
    model = seams.load(write_model(tmp_path), ontology_dir=ONTOLOGY)
    local = DatasetOntology(FINANCE, FINANCE_1_0)
    assert model.dataset_imports == (local,)
    # gist, which finance imports, is still the vendored file.
    assert [v.version for v in model.imports] == [GIST_14_0]
    statuses = {(s.ontology, s.imported): s for s in model.import_statuses}
    assert statuses[(EXPENSE, FINANCE_1_0)] == ImportStatus(EXPENSE, FINANCE_1_0, None, "", local)
    assert statuses[(EXPENSE, FINANCE_1_0)].resolved
    assert statuses[(EXPENSE, FINANCE_1_0)].error is None
    assert statuses[(FINANCE, GIST_14_0)].vendored is not None


def test_dataset_ontologies_are_sorted_by_version_iri(tmp_path: Path) -> None:
    model = seams.load(write_model(tmp_path), ontology_dir=ONTOLOGY)
    assert seams.dataset_ontologies(model.ds) == (
        DatasetOntology(EXPENSE, URIRef(EX + "expense_ontology/1.1")),
        DatasetOntology(FINANCE, FINANCE_1_0),
    )


def test_a_class_from_the_imported_dataset_ontology_is_sourced_from_its_model(tmp_path: Path) -> None:
    model = seams.load(write_model(tmp_path), ontology_dir=ONTOLOGY)
    expense = next(o for o in model.ontologies if o.iri == EXPENSE)
    reimbursement = next(c for c in expense.classes() if c.iri == URIRef(EX + "Reimbursement"))
    (payment,) = reimbursement.superclasses
    assert (payment.iri, payment.label, payment.source) == (URIRef(EX + "Payment"), "Payment", FINANCE)


def test_the_viewer_health_entry_names_the_dataset_ontology(tmp_path: Path) -> None:
    model = seams.load(write_model(tmp_path), ontology_dir=ONTOLOGY)
    entry = next(e for e in ontology_health(model) if e["imported"] == str(FINANCE_1_0))
    assert entry == {
        "ontology": str(EXPENSE),
        "imported": str(FINANCE_1_0),
        "label": "finance_ontology 1.0",
        "resolved": True,
        "vendored": None,
        "dataset": str(FINANCE),
        "error": None,
    }


# ── negative paths ──


def test_an_import_of_a_version_the_dataset_does_not_hold_is_refused(tmp_path: Path) -> None:
    path = write_model(tmp_path, expenses_trig("<https://example.org/expenses/finance_ontology/2.0>"))
    err = import_error(path)
    assert (err.subject, err.predicate) == (str(EXPENSE), str(OWL.imports))
    assert err.detail == (
        "imports <https://example.org/expenses/finance_ontology/2.0>; "
        "the dataset's finance_ontology is version <https://example.org/expenses/finance_ontology/1.0>"
    )
    unchecked = seams.load(path, ontology_dir=ONTOLOGY, check_imports=False)
    (status,) = [s for s in unchecked.import_statuses if s.ontology == EXPENSE]
    assert not status.resolved and status.dataset is None
    assert status.error is not None and status.error.detail == err.detail


def test_the_bare_ontology_iri_is_a_version_mismatch(tmp_path: Path) -> None:
    err = import_error(write_model(tmp_path, expenses_trig("<https://example.org/expenses/finance_ontology>")))
    assert (err.subject, err.predicate) == (str(EXPENSE), str(OWL.imports))
    assert err.detail == (
        "imports <https://example.org/expenses/finance_ontology>; "
        "the dataset's finance_ontology is version <https://example.org/expenses/finance_ontology/1.0>"
    )


def test_the_import_does_not_resolve_without_the_other_file(tmp_path: Path) -> None:
    directory = write_model(tmp_path)
    (directory / "finance.trig").unlink()
    err = import_error(directory)
    assert (err.subject, err.predicate) == (str(EXPENSE), str(OWL.imports))
    assert err.detail == (
        "imports <https://example.org/expenses/finance_ontology/1.0>, which no file in ontology/vendor/ declares"
    )


def test_an_ontology_does_not_resolve_its_own_version(tmp_path: Path) -> None:
    path = write_model(tmp_path, expenses_trig("<https://example.org/expenses/expense_ontology/1.1>"))
    err = import_error(path)
    assert (err.subject, err.predicate) == (str(EXPENSE), str(OWL.imports))
    assert err.detail == (
        "imports <https://example.org/expenses/expense_ontology/1.1>, which no file in ontology/vendor/ declares"
    )


# ── seams.toml naming a directory ──


def test_a_project_model_of_dot_is_its_directory(tmp_path: Path) -> None:
    directory = write_model(tmp_path)
    (directory / "seams.toml").write_text('model = "."\n', encoding="utf-8")
    project = load_project(directory)
    model_path = resolve_model(project)
    assert model_path == directory.resolve()
    model = seams.load(model_path, ontology_dir=ONTOLOGY)
    assert [p.name for p in model.files] == ["expenses.trig", "finance.trig"]


def test_a_directory_with_no_trig_files_names_the_path(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match=f"no \\*.trig files in model directory {empty.resolve()}"):
        seams.load(empty, ontology_dir=ONTOLOGY)
