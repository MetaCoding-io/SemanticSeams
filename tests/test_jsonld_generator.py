"""The JSON-LD context generator (M023/S05, backlog O3, ADR-0024).

Every model is inline TriG built from ``model()``: an ontology with an expense class,
a category of expense states and one of approval outcomes, and a shapes graph whose
:ExpenseShape has one field of each kind ADR-0024 section 2 names (datatype, plain,
category, sh:in of IRIs, sh:in of literals, flattened sh:node, reference). A payload
read through a generated context with rdflib's JSON-LD parser shows the triples a
client gets. Each negative case breaks one fact and asserts the error names the
subject, the predicate and the detail."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import seams
from rdflib import RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH

from seams_gen import GeneratorError
from seams_gen.builtin import jsonld
from seams_gen.jsonld import extract_jsonld, jsonld_sources, render_jsonld

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
CHAPTER_9 = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"
EX = Namespace("https://example.org/expenses/")
OTHER = Namespace("https://example.org/other/")
GIST = Namespace("https://w3id.org/semanticarts/ns/ontology/gist/")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix gist:  <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix :      <https://example.org/expenses/> .
@prefix other: <https://example.org/other/> .
"""

ONTOLOGY_BODY = """
    :Expense a owl:Class ; rdfs:subClassOf gist:Transaction ; rdfs:label "Expense" ;
        seam:inModel :expense_ontology .
    :Note a owl:Class ; rdfs:label "Note" ; seam:inModel :expense_ontology .
    :ExpenseState a owl:Class ; rdfs:subClassOf gist:Category ; rdfs:label "Expense state" ;
        seam:inModel :expense_ontology .
    :Outcome a owl:Class ; rdfs:subClassOf gist:Category ; rdfs:label "Outcome" ;
        seam:inModel :expense_ontology .
    :s_submitted a :ExpenseState ; rdfs:label "submitted" ; seam:inModel :expense_ontology .
    :s_draft     a :ExpenseState ; rdfs:label "draft"     ; seam:inModel :expense_ontology .
    :o_rejected  a :Outcome ; rdfs:label "rejected" ; seam:inModel :expense_ontology .
    :o_approved  a :Outcome ; rdfs:label "approved" ; seam:inModel :expense_ontology .
"""

EXPENSE_SHAPE = """
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        sh:property [ sh:path gist:description ; sh:name "description" ; sh:datatype xsd:string ;
                      sh:maxCount 1 ; sh:order 0 ] ;
        sh:property [ sh:path gist:hasMagnitude ; sh:name "amount" ; sh:node :MoneyShape ;
                      sh:maxCount 1 ; sh:order 1 ] ;
        sh:property [ sh:path :paidOn ; sh:name "paid_on" ; sh:datatype xsd:date ; sh:order 2 ] ;
        sh:property [ sh:path :status ; sh:class :ExpenseState ; sh:maxCount 1 ; sh:order 3 ] ;
        sh:property [ sh:path :verdict ; sh:in ( :o_rejected :o_approved ) ; sh:order 4 ] ;
        sh:property [ sh:path :priority ; sh:in ( "low" "high" ) ; sh:datatype xsd:string ; sh:order 5 ] ;
        sh:property [ sh:path :note ; sh:class :Note ; sh:order 6 ] ;
        sh:property [ sh:path :tag ; sh:order 7 ] ;
        seam:inModel :expense_data .
"""

MONEY_SHAPE = """
    :MoneyShape a sh:NodeShape ; rdfs:label "Money" ; sh:class gist:Magnitude ;
        sh:property [ sh:path gist:numericValue ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ;
        sh:property [ sh:path gist:hasUnitOfMeasure ; sh:hasValue :USD ] ;
        seam:inModel :expense_data .
"""

# A message shape: no sh:targetClass, so no context.
NOTIFICATION_SHAPE = """
    :NotificationShape a sh:NodeShape ; rdfs:label "Notification" ;
        sh:property [ sh:path :message ; sh:datatype xsd:string ] ;
        seam:inModel :expense_data .
"""

SHAPES_BODY = EXPENSE_SHAPE + MONEY_SHAPE + NOTIFICATION_SHAPE

XSD_ = "http://www.w3.org/2001/XMLSchema#"


def model(shapes: str = SHAPES_BODY, ontology: str = ONTOLOGY_BODY) -> str:
    return f"""{PREFIXES}
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .
{ontology}}}

<urn:seams:graph:model:expense_data> {{
    :expense_data a seam:Model ; seam:notation seam:ShapeGraph ; rdfs:label "Expense Data" .
{shapes}}}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "model.trig"
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path: Path, text: str) -> seams.Model:
    return seams.load(write(tmp_path, text), ontology_dir=ONTOLOGY)


def files(tmp_path: Path, text: str = "") -> dict[str, str]:
    return render_jsonld(extract_jsonld(load(tmp_path, text or model())))


def context(tmp_path: Path, text: str = "", name: str = "ExpenseShape.jsonld") -> dict[str, Any]:
    return json.loads(files(tmp_path, text)[name])["@context"]


def error(tmp_path: Path, text: str) -> GeneratorError:
    m = load(tmp_path, text)
    with pytest.raises(GeneratorError) as err:
        extract_jsonld(m)
    return err.value


def triples(ctx: dict[str, Any], payload: dict[str, Any]) -> set[tuple[object, object, object]]:
    """The triples of ``payload`` read through ``ctx``, the blank subject as None."""
    g = Graph().parse(data=json.dumps({"@context": ctx, **payload}), format="json-ld")
    return {(None if isinstance(s, BNode) else s, p, o) for s, p, o in g}


# ── the context document (ADR-0024 section 2) ──


def test_one_context_per_target_classed_shape(tmp_path: Path) -> None:
    assert list(files(tmp_path)) == ["ExpenseShape.jsonld"]


def test_a_model_without_target_classes_gives_no_files(tmp_path: Path) -> None:
    assert files(tmp_path, model(shapes=NOTIFICATION_SHAPE)) == {}


def test_version_and_target_class_term_no_top_level_vocab(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx["@version"] == 1.1
    assert ctx["Expense"] == str(EX.Expense)
    assert "@vocab" not in ctx
    assert all(not key.startswith("@") or key == "@version" for key in ctx)


def test_datatype_field_is_name_to_path_typed_by_its_datatype(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx["description"] == {"@id": str(GIST.description), "@type": f"{XSD_}string"}
    assert ctx["paid_on"] == {"@id": str(EX.paidOn), "@type": f"{XSD_}date"}


def test_field_without_datatype_members_or_node_has_only_its_id(tmp_path: Path) -> None:
    assert context(tmp_path)["tag"] == {"@id": str(EX.tag)}


def test_category_field_is_vocab_with_labels_scoped_to_members(tmp_path: Path) -> None:
    assert context(tmp_path)["status"] == {
        "@id": str(EX.status),
        "@type": "@vocab",
        "@context": {"draft": str(EX.s_draft), "submitted": str(EX.s_submitted)},
    }


def test_sh_in_of_iris_is_a_category_term(tmp_path: Path) -> None:
    assert context(tmp_path)["verdict"] == {
        "@id": str(EX.verdict),
        "@type": "@vocab",
        "@context": {"approved": str(EX.o_approved), "rejected": str(EX.o_rejected)},
    }


def test_sh_in_of_literals_is_a_datatype_term(tmp_path: Path) -> None:
    assert context(tmp_path)["priority"] == {"@id": str(EX.priority), "@type": f"{XSD_}string"}


def test_flattened_and_reference_fields_map_to_null(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx["amount"] is None
    assert ctx["note"] is None


def test_terms_are_sorted_and_the_text_ends_with_a_newline(tmp_path: Path) -> None:
    text = files(tmp_path)["ExpenseShape.jsonld"]
    assert text.endswith("}\n") and not text.endswith("\n\n")
    keys = list(json.loads(text)["@context"])
    assert keys == sorted(keys)
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_a_payload_read_through_the_context_states_only_triples_the_shape_allows(tmp_path: Path) -> None:
    payload = {
        "description": "Taxi",
        "amount": "42.50",
        "paid_on": "2026-11-04",
        "status": "submitted",
        "verdict": "approved",
        "note": "n1",
        "unknown": "dropped",
    }
    assert triples(context(tmp_path), payload) == {
        (None, GIST.description, Literal("Taxi", datatype=XSD.string)),
        (None, EX.paidOn, Literal("2026-11-04", datatype=XSD.date)),
        (None, EX.status, EX.s_submitted),
        (None, EX.verdict, EX.o_approved),
    }


def test_same_model_same_bytes(tmp_path: Path) -> None:
    path = write(tmp_path, model())
    first = jsonld.generate(path, tmp_path)
    second = jsonld.generate(path, tmp_path)
    assert first == second and first


def test_sources_name_shape_class_paths_and_members(tmp_path: Path) -> None:
    found = jsonld_sources(load(tmp_path, model()))
    assert list(found) == ["ExpenseShape.jsonld"]
    iris = found["ExpenseShape.jsonld"]
    assert iris == tuple(sorted(iris))
    expected = {EX.ExpenseShape, EX.Expense, GIST.description, EX.status, EX.s_draft, EX.o_approved, EX.note}
    assert {str(i) for i in expected} <= set(iris)
    assert str(EX.NotificationShape) not in iris


def test_registered_generator_files_match_its_sources(tmp_path: Path) -> None:
    path = write(tmp_path, model())
    assert jsonld.generate(path, tmp_path).keys() == jsonld.sources(path, tmp_path).keys()


def test_chapter_9_has_the_contexts_adr_0024_names() -> None:
    out = jsonld.generate(CHAPTER_9, CHAPTER_9.parent)
    assert sorted(out) == ["ApprovalShape.jsonld", "ExpenseShape.jsonld", "PaymentShape.jsonld"]
    expense = json.loads(out["ExpenseShape.jsonld"])["@context"]
    assert expense["amount"] == {"@id": str(EX.amount), "@type": f"{XSD_}decimal"}
    assert expense["status"]["@context"]["submitted"] == str(EX.s_submitted)
    payment = json.loads(out["PaymentShape.jsonld"])["@context"]
    assert payment["paid_on"]["@id"] == str(EX.paidOn)


# ── faults (ADR-0024 section 7) ──


def test_two_fields_with_one_explicit_name(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace('sh:name "paid_on"', 'sh:name "description"')
    err = error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.name))
    assert 'both have the name "description"' in err.detail


def test_two_paths_with_one_local_name_and_no_sh_name(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace(
        "sh:property [ sh:path :tag ; sh:order 7 ] ;",
        "sh:property [ sh:path :tag ; sh:order 7 ] ;\n        sh:property [ sh:path other:tag ; sh:order 8 ] ;",
    )
    err = error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.name))
    assert "fields :tag and other:tag" in err.detail


def test_target_class_local_name_is_a_field_name(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace('sh:name "paid_on"', 'sh:name "Expense"')
    err = error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.targetClass))
    assert 'both named "Expense"' in err.detail


def test_two_target_classed_shapes_with_one_local_name(tmp_path: Path) -> None:
    twin = """
    other:ExpenseShape a sh:NodeShape ; sh:targetClass :Expense ;
        sh:property [ sh:path :id ; sh:datatype xsd:string ] ;
        seam:inModel :expense_data .
"""
    err = error(tmp_path, model(shapes=SHAPES_BODY + twin))
    assert (err.subject, err.predicate) == (str(OTHER.ExpenseShape), str(SH.targetClass))
    assert "both name the context file ExpenseShape.jsonld" in err.detail


@pytest.mark.parametrize("label", ["a:b", "@id", ""])
def test_a_category_label_that_is_not_a_json_ld_term(tmp_path: Path, label: str) -> None:
    ontology = ONTOLOGY_BODY.replace('rdfs:label "draft"', f'rdfs:label "{label}"')
    err = error(tmp_path, model(ontology=ontology))
    assert (err.subject, err.predicate) == (str(EX.s_draft), str(RDFS.label))
    assert f'status of :ExpenseShape: label "{label}" of :s_draft is not a JSON-LD term' in err.detail


def test_a_view_resolution_error_is_the_generator_error_on_the_same_fact(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:targetClass :Expense", "sh:targetClass :Undeclared")
    err = error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.targetClass))
    assert "is not an owl:Class of a seam:Ontology model" in err.detail


def test_nothing_is_rendered_on_failure(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace('sh:name "paid_on"', 'sh:name "description"')
    path = write(tmp_path, model(shapes=shapes))
    with pytest.raises(GeneratorError):
        jsonld.generate(path, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.trig"]


def test_reference_field_is_exposed_by_the_view(tmp_path: Path) -> None:
    by_name = {f.name: f for f in load(tmp_path, model()).shapes.by_iri(EX.ExpenseShape).fields()}
    assert by_name["note"].reference == URIRef(EX.Note)
    assert by_name["status"].reference is None
    assert by_name["amount"].reference is None
