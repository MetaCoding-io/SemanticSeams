"""The SemPKM Mental Model generator (M024/S03, backlog O5, ADR-0026).

Every model but chapter 10 is inline TriG built from ``model()``: a versioned
ontology model importing gist 14.0.0, an expense shape with a datatype field, a
category field, a flattened ``sh:node`` field and a ``seam:`` fact, a message
shape with no target class, and an IFML model with a list and a details view of
expenses and a form. Chapter 10 is read as committed; it states the
``owl:versionInfo "1.0.0"`` ADR-0026 section 4 gives it. Each negative case breaks one fact and asserts
the error names the subject, the predicate and the detail."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import seams
import yaml
from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH

from seams_gen import GeneratorError
from seams_gen.__main__ import main
from seams_gen.builtin import mentalmodel
from seams_gen.mentalmodel import extract_mentalmodel, mentalmodel_sources, render_mentalmodel

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
CHAPTER_10 = ROOT / "examples" / "expenses" / "chapter-10" / "expenses.trig"
EX = Namespace("https://example.org/expenses/")
OTHER = Namespace("https://example.org/other/")
SEAM = Namespace("https://w3id.org/seams/seam#")
IFML = Namespace("https://w3id.org/seams/ifml#")
PROV = Namespace("http://www.w3.org/ns/prov#")
VOCAB = Namespace("urn:sempkm:vocab:")
GIST_14 = "https://w3id.org/semanticarts/ontology/gistCore14.0.0"
NS = "urn:sempkm:model:expense-ontology:"
FILES = [
    "manifest.yaml",
    "ontology/expense-ontology.jsonld",
    "shapes/expense-ontology.jsonld",
    "views/expense-ontology.jsonld",
]
# The subjects SemPKM's validator accepts besides the archive's namespace.
ALLOWED = (NS, "http://www.w3.org/", "http://purl.org/dc/", "https://schema.org/", "http://xmlns.com/foaf/")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix gist:  <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix ifml:  <https://w3id.org/seams/ifml#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix :      <https://example.org/expenses/> .
@prefix other: <https://example.org/other/> .
"""

HEADER = """
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionInfo "1.0.0" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .
"""

ONTOLOGY_BODY = """
    :Expense a owl:Class ; rdfs:subClassOf gist:Transaction ; rdfs:label "Expense" ;
        seam:inModel :expense_ontology .
    :ExpenseState a owl:Class ; rdfs:subClassOf gist:Category ; rdfs:label "Expense state" ;
        seam:inModel :expense_ontology .
    :s_draft     a :ExpenseState ; rdfs:label "draft"     ; seam:inModel :expense_ontology .
    :s_submitted a :ExpenseState ; rdfs:label "submitted" ; seam:inModel :expense_ontology .
"""

SHAPES_BODY = """
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        sh:property [ sh:path gist:description ; sh:name "description" ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
        sh:property [ sh:path gist:hasMagnitude ; sh:name "amount" ; sh:node :MoneyShape ;
                      sh:maxCount 1 ; sh:order 1 ] ;
        sh:property [ sh:path :status ; sh:class :ExpenseState ; sh:maxCount 1 ; sh:order 2 ] ;
        seam:inModel :expense_data .
    :MoneyShape a sh:NodeShape ; rdfs:label "Money" ; sh:class gist:Magnitude ;
        sh:property [ sh:path gist:numericValue ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ;
        sh:property [ sh:path gist:hasUnitOfMeasure ; sh:hasValue :USD ] ;
        seam:inModel :expense_data .
    :NotificationShape a sh:NodeShape ; rdfs:label "Notification" ;
        sh:property [ sh:path :message ; sh:datatype xsd:string ] ;
        seam:inModel :expense_data .
"""

IFML_BODY = """
    :expense_list a ifml:List ; rdfs:label "My Expenses" ; seam:inModel :expense_ui .
    :expense_details a ifml:Details ; rdfs:label "Expense" ; seam:inModel :expense_ui .
    :expense_form a ifml:Form ; rdfs:label "New expense" ; seam:inModel :expense_ui .
"""

SEAMS_BODY = """
    :expense_list seam:reads :ExpenseShape .
    :expense_details seam:reads :ExpenseShape .
    :expense_form seam:writes :ExpenseShape .
    :ExpenseShape seam:lifecycle :expense_lifecycle .
"""


def model(
    header: str = HEADER,
    ontology: str = ONTOLOGY_BODY,
    shapes: str = SHAPES_BODY,
    ifml: str = IFML_BODY,
    links: str = SEAMS_BODY,
) -> str:
    return f"""{PREFIXES}
<urn:seams:graph:model:expense_ontology> {{
{header}{ontology}}}

<urn:seams:graph:model:expense_data> {{
    :expense_data a seam:Model ; seam:notation seam:ShapeGraph ; rdfs:label "Expense Data" .
{shapes}}}

<urn:seams:graph:model:expense_ui> {{
    :expense_ui a seam:Model , ifml:InteractionModel ; seam:notation seam:IFML ; rdfs:label "Expense UI" .
{ifml}}}

<urn:seams:graph:seams> {{
{links}}}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "model.trig"
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path: Path, text: str) -> seams.Model:
    return seams.load(write(tmp_path, text), ontology_dir=ONTOLOGY)


def files(tmp_path: Path, text: str = "") -> dict[str, str]:
    return render_mentalmodel(extract_mentalmodel(load(tmp_path, text or model())))


def graph(text: str) -> Graph:
    return Graph().parse(data=text, format="json-ld")


def nodes(tmp_path: Path, kind: str, text: str = "") -> dict[str, dict[str, Any]]:
    """The ``@graph`` nodes of the ``kind`` file, by ``@id``."""
    document = json.loads(files(tmp_path, text)[f"{kind}/expense-ontology.jsonld"])
    return {n["@id"]: n for n in document["@graph"]}


def error(tmp_path: Path, text: str) -> GeneratorError:
    m = load(tmp_path, text)
    with pytest.raises(GeneratorError) as err:
        extract_mentalmodel(m)
    return err.value


def chapter_10() -> seams.Model:
    """Chapter 10 as committed."""
    return seams.Model(CHAPTER_10)


# ── the package (ADR-0026 sections 1 and 4) ──


def test_the_package_is_the_manifest_and_three_entrypoints(tmp_path: Path) -> None:
    assert list(files(tmp_path)) == FILES


def test_manifest_keys_values_and_order(tmp_path: Path) -> None:
    text = files(tmp_path)["manifest.yaml"]
    assert text == (
        'modelId: "expense-ontology"\n'
        'version: "1.0.0"\n'
        'name: "Expense Ontology"\n'
        'namespace: "urn:sempkm:model:expense-ontology:"\n'
        "entrypoints:\n"
        '  ontology: "ontology/expense-ontology.jsonld"\n'
        '  shapes: "shapes/expense-ontology.jsonld"\n'
        '  views: "views/expense-ontology.jsonld"\n'
    )
    manifest = yaml.safe_load(text)
    assert manifest["entrypoints"] == {k: f"{k}/expense-ontology.jsonld" for k in ("ontology", "shapes", "views")}
    assert manifest["namespace"] == f"urn:sempkm:model:{manifest['modelId']}:"


def test_a_comment_is_the_description_after_the_name(tmp_path: Path) -> None:
    comment = 'Expenses: "claims", approvals and payments.\nSecond line.'
    header = HEADER.replace(
        'rdfs:label "Expense Ontology" ;', f'rdfs:label "Expense Ontology" ; rdfs:comment """{comment}""" ;'
    )
    text = files(tmp_path, model(header=header))["manifest.yaml"]
    assert list(yaml.safe_load(text)) == ["modelId", "version", "name", "description", "namespace", "entrypoints"]
    assert yaml.safe_load(text)["description"] == comment


def test_a_version_that_yaml_would_read_as_a_number_stays_a_string(tmp_path: Path) -> None:
    header = HEADER.replace('rdfs:label "Expense Ontology"', 'rdfs:label "1.0"')
    assert yaml.safe_load(files(tmp_path, model(header=header))["manifest.yaml"])["name"] == "1.0"


def test_the_ontology_node_states_its_facts_and_gist(tmp_path: Path) -> None:
    (node,) = nodes(tmp_path, "ontology").values()
    assert node == {
        "@id": f"{NS}expense_ontology",
        "@type": str(OWL.Ontology),
        str(RDFS.label): "Expense Ontology",
        str(OWL.versionInfo): "1.0.0",
        str(OWL.imports): {"@id": GIST_14},
        str(PROV.wasDerivedFrom): {"@id": "https://example.org/expenses/expense_ontology/1.0"},
    }


def test_the_shapes_are_the_target_classed_ones_and_the_shapes_they_reach(tmp_path: Path) -> None:
    found = nodes(tmp_path, "shapes")
    assert list(found) == [f"{NS}ExpenseShape", f"{NS}MoneyShape"]
    expense = found[f"{NS}ExpenseShape"]
    assert expense["@type"] == str(SH.NodeShape)
    assert expense[str(PROV.wasDerivedFrom)] == {"@id": str(EX.ExpenseShape)}
    assert expense[str(SH.targetClass)] == {"@id": str(EX.Expense)}
    assert not [key for key in expense if key.startswith(str(SEAM))]


def test_property_shapes_are_in_field_order_and_sh_node_is_the_package_iri(tmp_path: Path) -> None:
    props = nodes(tmp_path, "shapes")[f"{NS}ExpenseShape"][str(SH.property)]
    assert [p[str(SH.path)]["@id"] for p in props] == [
        "https://w3id.org/semanticarts/ns/ontology/gist/description",
        "https://w3id.org/semanticarts/ns/ontology/gist/hasMagnitude",
        str(EX.status),
    ]
    assert props[0][str(SH.name)] == "description"
    assert props[0][str(SH.order)] == {"@type": "http://www.w3.org/2001/XMLSchema#integer", "@value": "0"}
    assert props[1][str(SH.node)] == {"@id": f"{NS}MoneyShape"}
    assert props[2][str(SH["class"])] == {"@id": str(EX.ExpenseState)}


def test_one_table_view_per_list_or_details_that_reads_a_shape(tmp_path: Path) -> None:
    found = nodes(tmp_path, "views")
    assert list(found) == [f"{NS}expense_details", f"{NS}expense_list"]
    view = found[f"{NS}expense_list"]
    assert view["@type"] == str(VOCAB.ViewSpec)
    assert view[str(RDFS.label)] == "My Expenses"
    assert view[str(PROV.wasDerivedFrom)] == {"@id": str(EX.expense_list)}
    assert view[str(VOCAB.targetClass)] == {"@id": str(EX.Expense)}
    assert view[str(VOCAB.rendererType)] == "table"
    assert view[str(VOCAB.columns)] == "description,amount,status"


def test_the_query_selects_each_column_and_follows_a_flattened_field(tmp_path: Path) -> None:
    query = nodes(tmp_path, "views")[f"{NS}expense_list"][str(VOCAB.sparqlQuery)]
    gist = "https://w3id.org/semanticarts/ns/ontology/gist/"
    assert query == (
        f"SELECT ?s ?description ?amount ?status WHERE {{ ?s a <{EX.Expense}> . "
        f"OPTIONAL {{ ?s <{gist}description> ?description }} "
        f"OPTIONAL {{ ?s <{gist}hasMagnitude> [ <{gist}numericValue> ?amount ] }} "
        f"OPTIONAL {{ ?s <{EX.status}> ?status }} }}"
    )


def test_the_query_runs_and_reads_a_flattened_value(tmp_path: Path) -> None:
    gist = Namespace("https://w3id.org/semanticarts/ns/ontology/gist/")
    data = Graph()
    money = BNode()
    data.add((EX.e1, RDF.type, EX.Expense))
    data.add((EX.e1, gist.description, Literal("Taxi")))
    data.add((EX.e1, gist.hasMagnitude, money))
    data.add((money, gist.numericValue, Literal("42.50")))
    data.add((EX.e2, RDF.type, EX.Expense))
    query = nodes(tmp_path, "views")[f"{NS}expense_list"][str(VOCAB.sparqlQuery)]
    rows = sorted(data.query(query), key=lambda r: str(r[0]))
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (EX.e1, Literal("Taxi"), Literal("42.50"), None),
        (EX.e2, None, None, None),
    ]


def test_every_document_parses_and_every_subject_is_one_sempkm_accepts(tmp_path: Path) -> None:
    for name, text in files(tmp_path).items():
        if name.endswith(".jsonld"):
            g = graph(text)
            assert len(g) > 0
            subjects = {s for s in g.subjects() if not isinstance(s, BNode)}
            assert subjects and all(str(s).startswith(ALLOWED) for s in subjects), name


def test_json_ld_has_no_context_sorted_keys_and_a_trailing_newline(tmp_path: Path) -> None:
    for name, text in files(tmp_path).items():
        if name.endswith(".jsonld"):
            document = json.loads(text)
            assert list(document) == ["@graph"]
            assert text == json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            ids = [n["@id"] for n in document["@graph"]]
            assert ids == sorted(ids)


def test_same_model_same_bytes(tmp_path: Path) -> None:
    path = write(tmp_path, model())
    first = mentalmodel.generate(path, tmp_path)
    second = mentalmodel.generate(path, tmp_path)
    assert first == second and list(first) == FILES


def test_sources_match_files_and_name_model_elements(tmp_path: Path) -> None:
    found = mentalmodel_sources(load(tmp_path, model()))
    assert list(found) == FILES
    assert found["manifest.yaml"] == (str(EX.expense_ontology),)
    assert found["shapes/expense-ontology.jsonld"] == tuple(
        sorted(map(str, (EX.Expense, EX.ExpenseShape, EX.MoneyShape)))
    )
    assert found["views/expense-ontology.jsonld"] == tuple(
        sorted(map(str, (EX.Expense, EX.ExpenseShape, EX.expense_details, EX.expense_list)))
    )
    path = write(tmp_path, model())
    assert mentalmodel.generate(path, tmp_path).keys() == mentalmodel.sources(path, tmp_path).keys()


def test_the_cli_writes_the_package_directories(tmp_path: Path) -> None:
    path = write(tmp_path, model())
    out = tmp_path / "mental-model"
    assert main(["mentalmodel", str(path), "--out", str(out)]) == 0
    written = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert written == FILES


# ── chapter 10 ──


def test_chapter_10_package() -> None:
    m = chapter_10()
    out = render_mentalmodel(extract_mentalmodel(m))
    assert list(out) == FILES
    manifest = yaml.safe_load(out["manifest.yaml"])
    assert (manifest["modelId"], manifest["version"], manifest["name"]) == (
        "expense-ontology",
        "1.1.0",  # chapter 10 adds :Vendor (ADR-0027), so the version moves
        "Expense Ontology",
    )
    for name in FILES[1:]:
        g = graph(out[name])
        assert all(str(s).startswith(ALLOWED) for s in g.subjects() if not isinstance(s, BNode)), name
    views = {s for s in graph(out["views/expense-ontology.jsonld"]).subjects(RDF.type, VOCAB.ViewSpec)}
    expected = {
        c.iri for c in m.interfaces.components() if (IFML.List in c.types or IFML.Details in c.types) and c.reads
    }
    assert views == {URIRef(f"{NS}{c.split('/')[-1]}") for c in map(str, expected)}
    assert len(views) == 5
    shapes = set(graph(out["shapes/expense-ontology.jsonld"]).subjects(RDF.type, SH.NodeShape))
    assert {URIRef(f"{NS}{n}") for n in ("ExpenseShape", "ApprovalShape", "PaymentShape", "VendorShape")} <= shapes


def test_chapter_10_is_the_same_bytes_twice() -> None:
    assert render_mentalmodel(extract_mentalmodel(chapter_10())) == render_mentalmodel(
        extract_mentalmodel(chapter_10())
    )


# ── faults (ADR-0026 section 10) ──


def _fault(err: GeneratorError, subject: object, predicate: object, detail: str) -> None:
    assert (err.subject, err.predicate) == (str(subject), str(predicate))
    assert detail in err.detail


def test_no_ontology_model(tmp_path: Path) -> None:
    header = HEADER.replace("seam:notation seam:Ontology", "seam:notation seam:ShapeGraph")
    ontology = ONTOLOGY_BODY.replace("seam:inModel :expense_ontology", "seam:inModel :expense_data")
    shapes = SHAPES_BODY.replace("sh:targetClass :Expense ;", "")
    text = model(header=header, ontology=ontology, shapes=shapes)
    _fault(error(tmp_path, text), SEAM.Ontology, SEAM.notation, "there is none")


def test_two_ontology_models(tmp_path: Path) -> None:
    second = """
    other:other_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology ;
        rdfs:label "Other" ; owl:versionIRI <https://example.org/other/1.0> .
"""
    _fault(
        error(tmp_path, model(header=HEADER + second)),
        OTHER.other_ontology,
        SEAM.notation,
        "found :expense_ontology, other:other_ontology",
    )


@pytest.mark.parametrize("local", ["x", "9expenses", "expense.ontology", "e" * 65])
def test_a_model_id_sempkm_refuses(tmp_path: Path, local: str) -> None:
    text = model().replace(":expense_ontology", f":{local}").replace("expense_ontology/1.0", f"{local}/1.0")
    _fault(error(tmp_path, text), EX[local], RDF.type, "must match [a-z][a-z0-9-]*")


@pytest.mark.parametrize(
    ("version", "found"),
    [("", "none"), ('owl:versionInfo "1.0" ;', '"1.0"'), ('owl:versionInfo "1.0.0", "2.0.0" ;', '"1.0.0", "2.0.0"')],
)
def test_version_info_missing_repeated_or_not_semver(tmp_path: Path, version: str, found: str) -> None:
    header = HEADER.replace('owl:versionInfo "1.0.0" ;', version)
    _fault(
        error(tmp_path, model(header=header)), EX.expense_ontology, OWL.versionInfo, f"MAJOR.MINOR.PATCH, found {found}"
    )


@pytest.mark.parametrize("label", ["", 'rdfs:label "A", "B" ;', f'rdfs:label "{"n" * 201}" ;'])
def test_label_missing_repeated_or_too_long(tmp_path: Path, label: str) -> None:
    header = HEADER.replace('rdfs:label "Expense Ontology" ;', label)
    _fault(
        error(tmp_path, model(header=header)), EX.expense_ontology, RDFS.label, "one rdfs:label of 1 to 200 characters"
    )


@pytest.mark.parametrize("comment", ['rdfs:comment "A", "B" ;', f'rdfs:comment "{"c" * 2001}" ;'])
def test_comment_repeated_or_too_long(tmp_path: Path, comment: str) -> None:
    header = HEADER.replace('rdfs:label "Expense Ontology" ;', f'rdfs:label "Expense Ontology" ; {comment}')
    _fault(
        error(tmp_path, model(header=header)),
        EX.expense_ontology,
        RDFS.comment,
        "at most one rdfs:comment of at most 2000",
    )


def test_another_gist_version(tmp_path: Path) -> None:
    gist_13 = "https://w3id.org/semanticarts/ontology/gistCore13.0.0"
    m = load(tmp_path, model())
    m.ds.graph(URIRef("urn:seams:graph:model:expense_ontology")).add(
        (EX.expense_ontology, OWL.imports, URIRef(gist_13))
    )
    with pytest.raises(GeneratorError) as err:
        extract_mentalmodel(m)
    _fault(err.value, EX.expense_ontology, OWL.imports, f"imports {gist_13}; a Mental Model states {GIST_14}")


def test_two_package_nodes_with_one_local_name(tmp_path: Path) -> None:
    ifml = IFML_BODY + '    other:ExpenseShape a ifml:Details ; rdfs:label "Twin" ; seam:inModel :expense_ui .\n'
    links = SEAMS_BODY + "    other:ExpenseShape seam:reads :ExpenseShape .\n"
    _fault(
        error(tmp_path, model(ifml=ifml, links=links)), OTHER.ExpenseShape, RDF.type, "both would be the package node"
    )


def test_a_view_reading_two_shapes(tmp_path: Path) -> None:
    links = SEAMS_BODY + "    :expense_list seam:reads :NotificationShape .\n"
    _fault(error(tmp_path, model(links=links)), EX.expense_list, SEAM.reads, "reads :ExpenseShape, :NotificationShape")


def test_a_view_reading_a_shape_without_a_target_class(tmp_path: Path) -> None:
    links = SEAMS_BODY.replace(
        ":expense_details seam:reads :ExpenseShape", ":expense_details seam:reads :NotificationShape"
    )
    _fault(error(tmp_path, model(links=links)), EX.NotificationShape, SH.targetClass, "by the shape's sh:targetClass")


def test_a_field_name_that_is_not_a_sparql_variable(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:path :status ;", "sh:path <https://example.org/expenses/paid-on> ;")
    _fault(error(tmp_path, model(shapes=shapes)), EX.ExpenseShape, SH.name, 'the field name "paid-on"')


def test_a_view_resolution_error_is_the_generator_error_on_the_same_fact(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:targetClass :Expense", "sh:targetClass :Undeclared")
    _fault(
        error(tmp_path, model(shapes=shapes)),
        EX.ExpenseShape,
        SH.targetClass,
        "is not an owl:Class of a seam:Ontology model",
    )


def test_nothing_is_written_on_failure(tmp_path: Path) -> None:
    path = write(tmp_path, model(header=HEADER.replace('owl:versionInfo "1.0.0" ;', "")))
    out = tmp_path / "mental-model"
    assert main(["mentalmodel", str(path), "--out", str(out)]) == 2
    assert not out.exists()
