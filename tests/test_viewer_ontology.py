"""The viewer's class view and ontology health (ADR-0022 sections 5 and 6, M023/S03).

Each test copies expense chapter 1 into tmp_path, appends an inline seam:Ontology
graph importing the committed vendored gist, and points the viewer at the copy.
The viewer loads with the import check off, so a broken import is a health fact,
not a model that does not open.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import ontologygraph, validation  # noqa: E402

CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01"
CHAPTER_09 = ROOT / "examples" / "expenses" / "chapter-09"
EX = "https://example.org/expenses/"
ONTOLOGY = f"{EX}expense_ontology"
GIST = "https://w3id.org/semanticarts/ns/ontology/gist/"
GIST_14_0 = "https://w3id.org/semanticarts/ontology/gistCore14.0.0"
GIST_14_1 = "https://w3id.org/semanticarts/ontology/gistCore14.1.0"
OWL_IMPORTS = "http://www.w3.org/2002/07/owl#imports"
SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"

# Classes written out of IRI order; TravelExpense's gist:Transation is the typo.
ONTOLOGY_GRAPH = """
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <{imports}> .

    :Payment a owl:Class ;
        rdfs:subClassOf <https://w3id.org/semanticarts/ns/ontology/gist/Transaction> ;
        rdfs:label "Payment" ;
        seam:inModel :expense_ontology .

    :Expense a owl:Class ;
        rdfs:subClassOf <https://w3id.org/semanticarts/ns/ontology/gist/Transaction> ;
        rdfs:label "Expense" ;
        <http://www.w3.org/2004/02/skos/core#definition> "Money an employee spent and asks to have reimbursed." ;
        seam:inModel :expense_ontology .

    :TravelExpense a owl:Class ;
        rdfs:subClassOf :Expense , <https://w3id.org/semanticarts/ns/ontology/gist/Transation> ;
        rdfs:label "Travel expense" ;
        seam:inModel :expense_ontology .

    :amount a owl:DatatypeProperty ;
        rdfs:domain :Expense ;
        rdfs:range xsd:decimal ;
        rdfs:label "amount" ;
        seam:inModel :expense_ontology .
}}
"""


@pytest.fixture(autouse=True)
def restore_viewer():
    """Point the viewer back at its model afterwards; the conformance cache is
    keyed by id(ds), so clear it on both sides (MEM010)."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    viewer_app.configure(original)


def open_viewer(tmp_path: Path, imports: str = GIST_14_0) -> TestClient:
    app_dir = Path(shutil.copytree(CHAPTER_01, tmp_path / "chapter-01"))
    trig = app_dir / "expenses.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + ONTOLOGY_GRAPH.format(imports=imports), encoding="utf-8")
    viewer_app.configure(trig)
    return TestClient(viewer_app.app)


def view(client: TestClient, iri: str, fragment: bool = False):
    headers = {"Accept": "text/html", **({"hx-request": "true"} if fragment else {})}
    return client.get(f"/view/{quote(iri, safe='')}", headers=headers)


def view_json(client: TestClient, iri: str) -> dict:
    response = client.get(f"/view/{quote(iri, safe='')}", headers={"Accept": "application/json"})
    assert response.status_code == 200
    return response.json()


# ── the class view projection ──


def test_class_view_draws_classes_properties_and_superclasses(tmp_path):
    open_viewer(tmp_path)
    nodes, edges = ontologygraph.ontology_graph_data(ONTOLOGY)
    by_id = {n["id"]: n for n in nodes}
    assert [n["id"] for n in nodes] == [
        f"{EX}Expense",
        f"{EX}Payment",
        f"{EX}TravelExpense",
        f"{GIST}Transaction",
        f"{GIST}Transation",
        f"{EX}Expense::property::{viewer_app.qname(viewer_app.URIRef(EX + 'amount'))}",
    ]
    expense = by_id[f"{EX}Expense"]
    assert (expense["label"], expense["typeLabel"], expense["layer"]) == ("Expense", "Class", "data")
    assert expense["description"] == "Money an employee spent and asks to have reimbursed."
    prop = nodes[-1]
    assert (prop["parent"], prop["label"], prop["navigateTo"]) == (f"{EX}Expense", "amount", f"{EX}amount")
    assert prop["description"].startswith("→ ")
    assert edges == [
        {"from": f"{EX}Expense", "to": f"{GIST}Transaction", "label": "subClassOf"},
        {"from": f"{EX}Payment", "to": f"{GIST}Transaction", "label": "subClassOf"},
        {"from": f"{EX}TravelExpense", "to": f"{EX}Expense", "label": "subClassOf"},
        {"from": f"{EX}TravelExpense", "to": f"{GIST}Transation", "label": "subClassOf"},
    ]


def test_an_imported_superclass_is_a_read_only_card_labelled_from_the_vendored_file(tmp_path):
    open_viewer(tmp_path)
    nodes, _edges = ontologygraph.ontology_graph_data(ONTOLOGY)
    gist = next(n for n in nodes if n["id"] == f"{GIST}Transaction")
    assert gist["readOnly"] is True
    assert gist["navigateTo"] is None
    assert (gist["layer"], gist["typeLabel"]) == ("other", ontologygraph.IMPORTED_TYPE_LABEL)
    assert gist["label"] == "Transaction"
    assert gist["description"], "gist's skos:definition"


def test_an_undeclared_superclass_is_a_read_only_undeclared_card(tmp_path):
    open_viewer(tmp_path)
    nodes, _edges = ontologygraph.ontology_graph_data(ONTOLOGY)
    typo = next(n for n in nodes if n["id"] == f"{GIST}Transation")
    assert (typo["readOnly"], typo["typeLabel"]) == (True, ontologygraph.UNDECLARED_TYPE_LABEL)
    assert typo["label"] == "Transation"


def test_the_class_view_is_the_same_on_every_call(tmp_path):
    open_viewer(tmp_path)
    assert ontologygraph.ontology_graph_data(ONTOLOGY) == ontologygraph.ontology_graph_data(ONTOLOGY)


def test_a_model_that_is_no_ontology_draws_nothing(tmp_path):
    open_viewer(tmp_path)
    assert ontologygraph.ontology_graph_data(f"{EX}expense_architecture") == ([], [])


# ── the class view page ──


def test_the_ontology_model_renders_the_class_view(tmp_path):
    client = open_viewer(tmp_path)
    response = view(client, ONTOLOGY, fragment=True)
    assert response.status_code == 200
    assert 'id="class-canvas"' in response.text
    assert 'data-notation="ontology"' in response.text
    assert "No renderer yet" not in response.text
    assert view_json(client, ONTOLOGY)["notation"] == "ontology"


def test_a_class_lands_on_its_class_view_highlighted(tmp_path):
    client = open_viewer(tmp_path)
    response = view(client, f"{EX}Payment", fragment=True)
    assert response.status_code == 200
    assert 'id="class-canvas"' in response.text
    assert '"focused": true' in response.text
    assert response.text.count('"focused": true') == 1


# ── ontology health ──


def test_a_resolved_import_is_listed_on_the_full_page_only(tmp_path):
    client = open_viewer(tmp_path)
    page = view(client, viewer_app.root_iri()).text
    assert f'class="health-import" data-import="{GIST_14_0}" data-vendored="{GIST_14_0}"' in page
    assert "Import: gistCore14.0.0 (vendored)" in page
    assert 'class="health-import-error"' not in page
    assert 'class="health-import"' not in view(client, viewer_app.root_iri(), fragment=True).text


def test_the_undeclared_superclass_is_a_warning_and_the_model_still_conforms(tmp_path):
    client = open_viewer(tmp_path)
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    assert health["conforms"] is True
    typo = [w for w in health["warnings"] if w["path"] == SUBCLASS_OF]
    assert typo == [
        {
            "focusNode": f"{EX}TravelExpense",
            "path": SUBCLASS_OF,
            "message": f"{GIST}Transation is declared neither in the ontology nor in a resolved import (a likely typo)",
            "severity": "Warning",
            "sourceShape": None,
        }
    ]
    assert health["ontologyImports"] == [
        {
            "ontology": ONTOLOGY,
            "imported": GIST_14_0,
            "label": "gistCore14.0.0",
            "resolved": True,
            "vendored": GIST_14_0,
            "dataset": None,
            "error": None,
        }
    ]


def test_a_version_mismatch_is_a_health_fact_and_the_model_still_opens(tmp_path):
    client = open_viewer(tmp_path, imports=GIST_14_1)
    response = view(client, viewer_app.root_iri())
    assert response.status_code == 200
    page = response.text
    assert f'class="health-import-error" role="alert" data-import="{GIST_14_1}"' in page
    assert f'data-subject="{ONTOLOGY}" data-predicate="{OWL_IMPORTS}"' in page
    assert "imports gistCore14.1.0; the vendored version is gistCore14.0.0" in page
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    assert health["ontologyImports"][0]["resolved"] is False
    assert health["ontologyImports"][0]["error"] == {
        "subject": ONTOLOGY,
        "predicate": OWL_IMPORTS,
        "detail": "imports gistCore14.1.0; the vendored version is gistCore14.0.0",
    }
    # The import fault explains the missing gist classes; no superclass warning repeats it.
    assert not [w for w in health["warnings"] if w["path"] == SUBCLASS_OF]
    # The class view still draws the model's own classes.
    assert 'id="class-canvas"' in view(client, ONTOLOGY, fragment=True).text


def test_an_unknown_import_is_a_health_fact(tmp_path):
    client = open_viewer(tmp_path, imports="https://example.org/nowhere/1.0")
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    [status] = health["ontologyImports"]
    assert status["error"]["detail"] == (
        "imports <https://example.org/nowhere/1.0>, which no file in ontology/vendor/ declares"
    )


def test_a_model_without_an_ontology_has_no_import_facts():
    validation._clear_cache()
    viewer_app.configure(CHAPTER_01 / "expenses.trig")
    client = TestClient(viewer_app.app)
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    assert "ontologyImports" not in health
    assert "data-import=" not in view(client, viewer_app.root_iri()).text


def test_a_broken_import_does_not_fail_the_store_or_review_checks(tmp_path):
    """The store and review checks build a ModelGraph over the viewer's Dataset
    with the import check off, so the import fault is reported once, as itself."""
    client = open_viewer(tmp_path, imports=GIST_14_1)
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    assert health["conforms"] is True
    assert not [f for f in health["violations"] + health["warnings"] if "check failed" in f["message"]]


# ── the expense tutorial's ontology (chapter 9) ──


def test_chapter_9_draws_its_ontology_anchored_in_gist_with_a_healthy_import():
    validation._clear_cache()
    viewer_app.configure(CHAPTER_09 / "expenses.trig")
    client = TestClient(viewer_app.app)
    nodes, edges = ontologygraph.ontology_graph_data(ONTOLOGY)
    assert [n["id"] for n in nodes] == [
        f"{EX}Approval",
        f"{EX}ApprovalOutcome",
        f"{EX}Expense",
        f"{EX}ExpenseState",
        f"{EX}Payment",
        f"{GIST}Category",
        f"{GIST}Determination",
        f"{GIST}Transaction",
    ]
    assert all(n["readOnly"] for n in nodes if n["id"].startswith(GIST))
    assert {(e["from"], e["to"]) for e in edges} == {
        (f"{EX}Approval", f"{GIST}Determination"),
        (f"{EX}ApprovalOutcome", f"{GIST}Category"),
        (f"{EX}Expense", f"{GIST}Transaction"),
        (f"{EX}ExpenseState", f"{GIST}Category"),
        (f"{EX}Payment", f"{GIST}Transaction"),
    }
    health = view_json(client, viewer_app.root_iri())["modelConformance"]
    assert health["conforms"] is True
    assert [(s["imported"], s["resolved"]) for s in health["ontologyImports"]] == [(GIST_14_0, True)]
    assert not [w for w in health["warnings"] if w["path"] == SUBCLASS_OF]
    assert 'id="class-canvas"' in view(client, ONTOLOGY, fragment=True).text
