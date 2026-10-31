"""Tests for the error vocabulary (M014/S04, ADR-0013).

ontology/comm.ttl adds comm:errorCode and the five RFC 9457 member properties,
ontology/proc.ttl adds proc:ErrorBoundaryEvent and ontology/seam.ttl adds
seam:catches. ontology/shapes/seam-shapes.ttl constrains them and widens
seamsh:ReturnsShapeShape to hydra:Status. Models are validated with the ontology
files merged in, as tests/validate_chat_app.py does. The ADR's turtle example is
itself the conforming fixture.
"""

import re
from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, RDFS, BNode, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
ADR = ROOT / "docs" / "adr" / "0013-error-shapes-and-boundaries.md"

SEAM = Namespace("https://w3id.org/seams/seam#")
COMM = Namespace("https://w3id.org/seams/comm#")
PROC = Namespace("https://w3id.org/seams/proc#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")
EX = Namespace("https://example.org/expenses/")
BOUNDARY = URIRef("https://example.org/expenses/approval_bpmn#notify_failed_boundary")

NEW_TERMS = [
    COMM.errorCode,
    COMM.type,
    COMM.title,
    COMM.status,
    COMM.detail,
    COMM.instance,
    PROC.ErrorBoundaryEvent,
    SEAM.catches,
]


def adr_text() -> str:
    return ADR.read_text(encoding="utf-8")


def ontology() -> rdflib.Graph:
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    return g


def model() -> rdflib.Graph:
    """The ontology plus the ADR's turtle example: an operation, its error status and
    error shape, and the lifted boundary that catches it."""
    blocks = re.findall(r"```turtle\n(.*?)```", adr_text(), re.DOTALL)
    assert len(blocks) == 1
    g = ontology()
    g.parse(data=blocks[0], format="turtle")
    return g


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


def problem_property(g: rdflib.Graph, path):
    return next(p for p in g.objects(EX.NotifyProblemShape, SH.property) if g.value(p, SH.path) == path)


# ---------------------------------------------------------------- ontology


@pytest.mark.parametrize("term", NEW_TERMS)
def test_new_terms_are_labelled_and_commented(term):
    g = ontology()
    assert g.value(term, RDFS.comment) is not None
    if term != PROC.ErrorBoundaryEvent:  # proc classes carry comments only, like their siblings
        assert g.value(term, RDFS.label) is not None


def test_catches_is_a_layer_seam():
    g = ontology()
    assert (SEAM.catches, RDF.type, RDF.Property) in g
    assert g.value(SEAM.catches, SEAM.reveal) == SEAM.Layer


@pytest.mark.parametrize("member", ["type", "title", "status", "detail", "instance"])
def test_problem_members_are_named_by_their_rfc9457_member(member):
    """contracts.py names a field by its sh:path local name, so the local name is the JSON key."""
    assert (COMM[member], RDF.type, RDF.Property) in ontology()


# ---------------------------------------------------------------- SHACL


def test_ontology_alone_conforms():
    assert violating_shapes(ontology()) == set()


def test_adr_example_conforms():
    assert violating_shapes(model()) == set()


def test_status_without_error_code_needs_no_error_shape():
    """A plain hydra:Status (no comm:errorCode) is not an error status."""
    g = ontology()
    g.add((EX.op, RDF.type, HYDRA.Operation))
    g.add((EX.op, HYDRA.possibleStatus, EX.ok))
    g.add((EX.ok, RDF.type, HYDRA.Status))
    g.add((EX.ok, HYDRA.statusCode, Literal(200)))
    assert violating_shapes(g) == set()


@pytest.mark.parametrize("code", ["", "-leading-dash", "has space", "7up"])
def test_malformed_error_code_is_flagged(code):
    g = model()
    g.set((EX.notify_failed, COMM.errorCode, Literal(code)))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_two_error_codes_on_one_status_are_flagged():
    g = model()
    g.add((EX.notify_failed, COMM.errorCode, Literal("second-code")))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


@pytest.mark.parametrize("status", [Literal(200), Literal(302), Literal(600), Literal("502")])
def test_error_status_code_outside_4xx_5xx_or_not_integer_is_flagged(status):
    g = model()
    g.set((EX.notify_failed, HYDRA.statusCode, status))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_missing_status_code_is_flagged():
    g = model()
    g.remove((EX.notify_failed, HYDRA.statusCode, None))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_error_status_without_error_shape_is_flagged():
    g = model()
    g.remove((EX.notify_failed, SEAM.returnsShape, None))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_error_shape_without_integer_status_member_is_flagged():
    g = model()
    g.set((problem_property(g, COMM.status), SH.datatype, XSD.string))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_error_shape_without_title_member_is_flagged():
    g = model()
    title = problem_property(g, COMM.title)
    g.remove((EX.NotifyProblemShape, SH.property, title))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_error_status_no_operation_declares_is_flagged():
    g = model()
    g.remove((EX.notify_manager_op, HYDRA.possibleStatus, EX.notify_failed))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_error_code_on_a_non_status_is_flagged():
    g = model()
    g.remove((EX.notify_failed, RDF.type, HYDRA.Status))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


def test_duplicate_error_code_on_one_operation_is_flagged():
    g = model()
    g.add((EX.notify_manager_op, HYDRA.possibleStatus, EX.notify_failed_again))
    for p, o in list(g.predicate_objects(EX.notify_failed)):
        g.add((EX.notify_failed_again, p, o))
    assert SEAMSH.ErrorCodeUniqueShape in violating_shapes(g)


def test_returns_shape_on_something_else_is_flagged():
    g = model()
    g.add((EX.not_an_operation, SEAM.returnsShape, EX.NotifyProblemShape))
    assert SEAMSH.ReturnsShapeShape in violating_shapes(g)


def test_catches_from_a_non_boundary_is_flagged():
    g = model()
    g.remove((BOUNDARY, RDF.type, PROC.ErrorBoundaryEvent))
    assert SEAMSH.CatchesShape in violating_shapes(g)


def test_catching_two_errors_is_flagged():
    g = model()
    g.add((BOUNDARY, SEAM.catches, EX.other_error))
    g.add((EX.other_error, RDF.type, HYDRA.Status))
    assert SEAMSH.CatchesShape in violating_shapes(g)


def test_catching_a_status_with_no_error_code_is_flagged():
    g = model()
    g.set((BOUNDARY, SEAM.catches, EX.ok))
    g.add((EX.ok, RDF.type, HYDRA.Status))
    assert SEAMSH.CatchesShape in violating_shapes(g)


def test_boundary_that_catches_nothing_is_flagged():
    g = model()
    g.remove((BOUNDARY, SEAM.catches, None))
    assert SEAMSH.ErrorBoundaryEventShape in violating_shapes(g)


def test_bnode_status_is_still_checked():
    """A status written as a blank node is targeted like a named one."""
    g = model()
    status = BNode()
    g.add((EX.notify_manager_op, HYDRA.possibleStatus, status))
    g.add((status, RDF.type, HYDRA.Status))
    g.add((status, COMM.errorCode, Literal("other-failure")))
    assert SEAMSH.ErrorStatusShape in violating_shapes(g)


# ---------------------------------------------------------------- the ADR


def test_adr_is_accepted():
    assert "**Status:** Accepted" in adr_text()


@pytest.mark.parametrize("heading", ["Context", "Spike findings", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(heading):
    assert re.search(rf"^##+ {heading}", adr_text(), re.MULTILINE)


def test_adr_is_in_decisions_nav():
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0013", "Error shapes and boundaries", "0013-error-shapes-and-boundaries"]' in config


def test_adr_is_in_adr_index():
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "./0013-error-shapes-and-boundaries" in index
