"""Executable acceptance test for the Seams ontologies + checkout example.

The CI form of the prose claims in README.md and examples/checkout.ttl:

1. every Turtle file parses;
2. the checkout model conforms to ontology/shapes/seam-shapes.ttl;
3. the shapes actually reject bad seams (a vacuously-green shapes file is
   exactly the silent regression this suite exists to prevent);
4. every non-reserved seam predicate is exercised by the example;
5. the canned queries in docs/queries/ return exactly the expected rows —
   the flagship cross-layer traversals can never silently return zero rows again.
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
EXAMPLE_FILE = ROOT / "examples" / "checkout.ttl"
QUERIES_DIR = ROOT / "docs" / "queries"

SEAM = Namespace("https://w3id.org/seams/seam#")
SHOP = Namespace("https://example.org/shop/")

# Fragment-IRI elements (Turtle prefixes cannot abbreviate a '#' in a local name)
PERSIST_TASK = URIRef("https://example.org/shop/order_bpmn#persist_task")
FULFILL_TASK = URIRef("https://example.org/shop/fulfillment_bpmn#fulfill_task")

# Reserved for profiles/planning; deliberately unexercised until those land.
RESERVED_PREDICATES = {SEAM.conformsTo, SEAM.realizes}


def load(*paths: Path) -> rdflib.Graph:
    g = rdflib.Graph()
    for p in paths:
        g.parse(p, format="turtle")
    return g


@pytest.fixture(scope="session")
def model() -> rdflib.Graph:
    """Ontologies merged with the example: sh:class and the queries need the
    rdfs:subClassOf triples (e.g. proc:ServiceTask -> proc:Task) in the data."""
    return load(*ONTOLOGY_FILES, EXAMPLE_FILE)


def canned(name: str) -> str:
    return (QUERIES_DIR / name).read_text()


@pytest.mark.parametrize(
    "path", [*ONTOLOGY_FILES, SHAPES_FILE, EXAMPLE_FILE], ids=lambda p: p.name
)
def test_turtle_parses(path):
    load(path)


def test_model_conforms_to_seam_shapes(model):
    conforms, _, report = pyshacl.validate(
        model, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    assert conforms, report


def test_seam_shapes_have_teeth():
    bad = load(*ONTOLOGY_FILES)
    bad.parse(
        data="""
        @prefix seam: <https://w3id.org/seams/seam#> .
        @prefix proc: <https://w3id.org/seams/proc#> .
        @prefix ex:   <https://example.org/bad/> .

        ex:model a seam:Model .                    # missing seam:notation
        ex:task a proc:ServiceTask ;
            seam:decidedBy ex:not_a_decision .     # only BusinessRuleTasks are decidedBy
        """,
        format="turtle",
    )
    conforms, _, _ = pyshacl.validate(
        bad, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    assert not conforms, "shapes accepted a Model without notation and a ServiceTask with seam:decidedBy"


def test_every_nonreserved_seam_predicate_is_exercised():
    declared = {
        p
        for p in load(ROOT / "ontology" / "seam.ttl").subjects(RDF.type, RDF.Property)
        if str(p).startswith(str(SEAM))
    }
    used = {
        p for p in load(EXAMPLE_FILE).predicates() if str(p).startswith(str(SEAM))
    }
    missing = declared - RESERVED_PREDICATES - used
    assert not missing, (
        f"seam predicates never exercised by checkout.ttl: {sorted(missing)}"
    )


def test_what_writes_shape(model):
    """The flagship traversal: UI event -> process -> tasks -> shape, including
    the async hop through the order.events channel into fulfillment."""
    rows = model.query(
        canned("what-writes-shape.rq"), initBindings={"shape": SHOP.OrderShape}
    )
    assert {(r.event, r.writer) for r in rows} == {
        (SHOP.submit_order, PERSIST_TASK),
        (SHOP.submit_order, FULFILL_TASK),
    }


def test_impact_of_node(model):
    """'What breaks if db01 goes away' — must reach containers AND processes,
    and must NOT depend on deploy:dependsOn (startup ordering)."""
    rows = model.query(
        canned("impact-of-node.rq"), initBindings={"node": SHOP.db01}
    )
    assert {r.impacted for r in rows} == {
        SHOP.order_db,
        SHOP.order_api,
        SHOP.web_ui,
        SHOP.order_process,
        SHOP.fulfillment_process,
    }


def test_what_moves_state(model):
    """Which tasks may move an Order out of 'submitted'? t_cancel has no firing
    task on purpose — that absence is an M2 model-health warning, not an error."""
    rows = model.query(
        canned("what-moves-state.rq"), initBindings={"state": SHOP.s_submitted}
    )
    assert {(r.task, r.transition, r.toState) for r in rows} == {
        (FULFILL_TASK, SHOP.t_fulfill, SHOP.s_fulfilled),
    }
