"""Data classification (ADR-0039, backlog X3): a field holds personal data when its
property shape states ``dpv:hasPersonalData`` with a category IRI from W3C DPV.

Every model is inline TriG built from ``model()``: one shape graph whose contact shape
marks two of its three fields as personal data. The positive cases show the annotation
conforms to every seam shape and leaves the typed field view unchanged; each negative
case breaks one fact and asserts the violation names the subject, the predicate and
the field."""

from __future__ import annotations

from pathlib import Path

import pytest
import seams
from rdflib import Graph, Namespace

from seams_gen.testing import shape_violations

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES_FILE = ONTOLOGY / "shapes" / "seam-shapes.ttl"
VOCABULARIES = tuple(sorted(ONTOLOGY.glob("*.ttl")))
EX = Namespace("https://example.org/contacts/")
DPV = Namespace("https://w3id.org/dpv#")
PD = Namespace("https://w3id.org/dpv/pd#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")

CONTACT_SHAPE = """
    :ContactShape a sh:NodeShape ; rdfs:label "Contact" ;
        # A person's name and address identify them (ADR-0039); the note does not.
        sh:property [ sh:path :fullName ; sh:name "name" ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ;
                      dpv:hasPersonalData pd:Name ] ;
        sh:property [ sh:path :email ; sh:datatype xsd:string ;
                      sh:maxCount 1 ; sh:order 1 ;
                      dpv:hasPersonalData pd:EmailAddress ] ;
        sh:property [ sh:path :note ; sh:datatype xsd:string ;
                      sh:maxCount 1 ; sh:order 2 ] ;
        seam:inModel :contact_data .
"""


def model(shapes: str = CONTACT_SHAPE) -> str:
    return f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix dpv:  <https://w3id.org/dpv#> .
@prefix pd:   <https://w3id.org/dpv/pd#> .
@prefix :     <https://example.org/contacts/> .

<urn:seams:graph:model:contact_data> {{
    :contact_data a seam:Model ; seam:notation seam:ShapeGraph ; rdfs:label "Contact Data" .
{shapes}}}
"""


def load(tmp_path: Path, text: str) -> seams.Model:
    path = tmp_path / "model.trig"
    path.write_text(text, encoding="utf-8")
    return seams.load(path, ontology_dir=ONTOLOGY)


def violations(tmp_path: Path, text: str) -> list[tuple[str, str | None, str]]:
    """(focus node, result path, message) of every seam shape violation of the model."""
    return shape_violations(load(tmp_path, text).ds, SHAPES_FILE, VOCABULARIES)


def classification_shapes() -> set[str]:
    shapes = Graph().parse(SHAPES_FILE)
    return {str(s) for s in shapes.subjects(SH.targetSubjectsOf, DPV.hasPersonalData)} | {
        str(SEAMSH.PersonalDataCategoryShape)
    }


# ── positive ──


def test_annotated_fields_conform_to_every_seam_shape(tmp_path: Path) -> None:
    assert violations(tmp_path, model()) == []


def test_the_annotation_is_on_the_property_shapes_with_its_category(tmp_path: Path) -> None:
    ds = load(tmp_path, model()).ds
    marked = sorted(
        (str(ds.value(prop, SH.path)), str(category))
        for prop, category in ds.subject_objects(DPV.hasPersonalData)
        if (EX.ContactShape, SH.property, prop) in ds
    )
    assert marked == [(str(EX.email), str(PD.EmailAddress)), (str(EX.fullName), str(PD.Name))]


def test_the_annotation_leaves_the_fields_unchanged(tmp_path: Path) -> None:
    bare = CONTACT_SHAPE.replace("dpv:hasPersonalData pd:Name", "").replace("dpv:hasPersonalData pd:EmailAddress", "")
    assert bare != CONTACT_SHAPE

    def wire(text: str) -> list[tuple[object, ...]]:
        shape = load(tmp_path, text).shapes.by_iri(EX.ContactShape)
        return [(f.name, f.datatype, f.min_count, f.max_count, f.order) for f in shape.fields()]

    assert wire(model()) == wire(model(bare))
    assert [name for name, *_ in wire(model())] == ["name", "email", "note"]


def test_the_seam_shapes_declare_both_classification_checks() -> None:
    assert classification_shapes() == {
        str(SEAMSH.PersonalDataCategoryShape),
        str(SEAMSH.PersonalDataPlacementShape),
    }


# ── negative ──
# A field without sh:name is named by its path IRI, as in the ADR-0023 shapes.


@pytest.mark.parametrize(
    ("change", "field", "value"),
    [
        (
            ("dpv:hasPersonalData pd:EmailAddress", 'dpv:hasPersonalData "email address"'),
            str(EX.email),
            "email address",
        ),
        (("dpv:hasPersonalData pd:Name", 'dpv:hasPersonalData "pd:Name"'), "name", "pd:Name"),
        (("dpv:hasPersonalData pd:Name", "dpv:hasPersonalData [ rdfs:label 'Name' ]"), "name", ""),
    ],
)
def test_a_category_that_is_not_an_iri_names_shape_predicate_and_field(
    tmp_path: Path, change: tuple[str, str], field: str, value: str
) -> None:
    shapes = CONTACT_SHAPE.replace(*change)
    assert shapes != CONTACT_SHAPE
    found = violations(tmp_path, model(shapes))
    assert len(found) == 1, found
    focus, path, message = found[0]
    assert focus == str(EX.ContactShape)
    assert path == str(DPV.hasPersonalData)
    assert f"field {field} has dpv:hasPersonalData" in message
    assert value in message
    assert "is not an IRI" in message and "ADR-0039" in message


def test_the_annotation_on_a_node_shape_is_misplaced(tmp_path: Path) -> None:
    shapes = CONTACT_SHAPE.replace('rdfs:label "Contact" ;', 'rdfs:label "Contact" ; dpv:hasPersonalData pd:Contact ;')
    assert shapes != CONTACT_SHAPE
    found = violations(tmp_path, model(shapes))
    assert found == [
        (
            str(EX.ContactShape),
            str(DPV.hasPersonalData),
            f"{EX.ContactShape} has dpv:hasPersonalData but is not the sh:property of a shape; "
            "the annotation goes on the property shape of the field that holds the personal data (ADR-0039).",
        )
    ]


def test_the_annotation_on_a_property_shape_without_a_path_is_misplaced(tmp_path: Path) -> None:
    shapes = CONTACT_SHAPE.replace(
        "sh:property [ sh:path :note ; sh:datatype xsd:string ;",
        "sh:property [ dpv:hasPersonalData pd:Name ] ;\n        sh:property [ sh:path :note ; sh:datatype xsd:string ;",
    )
    assert shapes != CONTACT_SHAPE
    found = [v for v in violations(tmp_path, model(shapes)) if "dpv:hasPersonalData" in v[2]]
    assert len(found) == 1, found
    assert found[0][1] == str(DPV.hasPersonalData)
    assert "is not the sh:property of a shape" in found[0][2]
