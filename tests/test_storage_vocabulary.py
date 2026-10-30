"""Tests for the storage vocabulary (M011/S02, ADR-0011).

ontology/seam.ttl adds seam:storedIn, ontology/deploy.ttl adds deploy:storeKind,
deploy:StoreKind with deploy:PostgreSQL and deploy:SQLite, and deploy:connectsTo.
ontology/shapes/seam-shapes.ttl constrains them. Models are validated with the
ontology files merged in, as tests/validate_chat_app.py does.
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, RDFS, BNode, Literal, Namespace

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"

SEAM = Namespace("https://w3id.org/seams/seam#")
ARCH = Namespace("https://w3id.org/seams/arch#")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")
EX = Namespace("https://example.org/store/")


def ontology() -> rdflib.Graph:
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    return g


def minimal_model() -> rdflib.Graph:
    """A shape stored in a PostgreSQL store, and an API binding that connects to it."""
    g = ontology()
    g.add((EX.MessageShape, RDF.type, SH.NodeShape))
    g.add((EX.MessageShape, SEAM.storedIn, EX.message_db))
    g.add((EX.message_db, RDF.type, ARCH.Container))
    g.add((EX.message_db, DEPLOY.storeKind, DEPLOY.PostgreSQL))
    g.add((EX.api, RDF.type, ARCH.Container))
    config, binding = BNode(), BNode()
    g.add((EX.api, DEPLOY.configuration, config))
    g.add((config, RDF.type, DEPLOY.Configuration))
    g.add((config, DEPLOY.binding, binding))
    g.add((binding, DEPLOY.key, Literal("DATABASE_URL")))
    g.add((binding, DEPLOY.secretRef, EX["secrets/database-url"]))
    g.add((binding, DEPLOY.connectsTo, EX.message_db))
    return g


def binding_of(g: rdflib.Graph):
    return next(g.subjects(DEPLOY.connectsTo, EX.message_db))


def violating_shapes(g: rdflib.Graph) -> set:
    """The shapes (named ones, or the named parent of a property shape) that report."""
    shapes_graph = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    conforms, results, _ = pyshacl.validate(g, shacl_graph=shapes_graph, inference="none")
    if conforms:
        return set()
    named = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        source = results.value(result, SH.sourceShape)
        parent = shapes_graph.value(predicate=SH.property, object=source)
        named.add(parent if parent is not None else source)
    return named


# ---------------------------------------------------------------- ontology


def test_stored_in_is_a_layer_seam_labelled_stored_in():
    g = ontology()
    assert (SEAM.storedIn, RDF.type, RDF.Property) in g
    assert g.value(SEAM.storedIn, SEAM.reveal) == SEAM.Layer
    assert g.value(SEAM.storedIn, RDFS.label) == Literal("stored in")


@pytest.mark.parametrize("kind", [DEPLOY.PostgreSQL, DEPLOY.SQLite])
def test_store_kinds_are_typed(kind):
    g = ontology()
    assert (kind, RDF.type, DEPLOY.StoreKind) in g
    assert g.value(kind, RDFS.label) is not None
    assert g.value(kind, RDFS.comment) is not None


@pytest.mark.parametrize("term", [DEPLOY.StoreKind, DEPLOY.storeKind, DEPLOY.connectsTo, SEAM.storedIn])
def test_new_terms_are_labelled_and_commented(term):
    g = ontology()
    assert g.value(term, RDFS.label) is not None
    assert g.value(term, RDFS.comment) is not None


def test_store_kind_ranges():
    g = ontology()
    assert g.value(DEPLOY.storeKind, RDFS.domain) == ARCH.Container
    assert g.value(DEPLOY.storeKind, RDFS.range) == DEPLOY.StoreKind
    assert g.value(DEPLOY.connectsTo, RDFS.range) == ARCH.Container


# ---------------------------------------------------------------- SHACL


def test_ontology_alone_conforms():
    # deploy:PostgreSQL is a deploy:StoreKind, not a store: no shape targets it.
    assert violating_shapes(ontology()) == set()


def test_minimal_model_conforms():
    assert violating_shapes(minimal_model()) == set()


def test_sqlite_store_conforms():
    g = minimal_model()
    g.set((EX.message_db, DEPLOY.storeKind, DEPLOY.SQLite))
    assert violating_shapes(g) == set()


def test_stored_in_from_a_non_shape():
    g = minimal_model()
    g.add((EX.api, SEAM.storedIn, EX.message_db))
    assert violating_shapes(g) == {SEAMSH.StoredInShape}


def test_stored_in_to_a_non_container():
    g = minimal_model()
    g.add((EX.other_db, DEPLOY.storeKind, DEPLOY.PostgreSQL))  # a kind, but no arch:Container type
    g.set((EX.MessageShape, SEAM.storedIn, EX.other_db))
    assert SEAMSH.StoredInShape in violating_shapes(g)


def test_two_stored_in():
    g = minimal_model()
    g.add((EX.archive_db, RDF.type, ARCH.Container))
    g.add((EX.archive_db, DEPLOY.storeKind, DEPLOY.SQLite))
    g.add((EX.MessageShape, SEAM.storedIn, EX.archive_db))
    assert violating_shapes(g) == {SEAMSH.StoredInShape}


def test_store_without_a_kind():
    g = minimal_model()
    g.remove((EX.message_db, DEPLOY.storeKind, None))
    assert violating_shapes(g) == {SEAMSH.StoreShape}


def test_connects_to_target_without_a_kind():
    g = minimal_model()
    g.add((EX.cache, RDF.type, ARCH.Container))
    g.set((binding_of(g), DEPLOY.connectsTo, EX.cache))
    assert violating_shapes(g) == {SEAMSH.StoreShape}


def test_unknown_store_kind():
    g = minimal_model()
    g.set((EX.message_db, DEPLOY.storeKind, DEPLOY.MySQL))
    assert violating_shapes(g) == {SEAMSH.StoreKindShape}


def test_two_store_kinds():
    g = minimal_model()
    g.add((EX.message_db, DEPLOY.storeKind, DEPLOY.SQLite))
    assert violating_shapes(g) == {SEAMSH.StoreKindShape}


def test_store_kind_on_a_non_container():
    g = minimal_model()
    g.add((EX.MessageShape, DEPLOY.storeKind, DEPLOY.SQLite))
    assert violating_shapes(g) == {SEAMSH.StoreKindShape}


def test_connects_to_a_non_store():
    g = minimal_model()
    g.set((binding_of(g), DEPLOY.connectsTo, EX.MessageShape))
    assert violating_shapes(g) == {SEAMSH.BindingShape, SEAMSH.StoreShape}


def test_connects_to_two_stores():
    g = minimal_model()
    g.add((EX.archive_db, RDF.type, ARCH.Container))
    g.add((EX.archive_db, DEPLOY.storeKind, DEPLOY.SQLite))
    g.add((binding_of(g), DEPLOY.connectsTo, EX.archive_db))
    assert violating_shapes(g) == {SEAMSH.BindingShape}


def test_connects_to_does_not_replace_the_value_source():
    # connectsTo sits beside the value; a binding still needs secretRef, value or serviceOf.
    g = minimal_model()
    g.remove((binding_of(g), DEPLOY.secretRef, None))
    assert violating_shapes(g) == {SEAMSH.BindingShape}
