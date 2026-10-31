"""Operation implementation (M014/S02 T01, ADR-0012).

ontology/seam.ttl adds seam:implementedBy, ontology/comm.ttl the kinds
comm:LLMCompletion, comm:PythonHandler and comm:HTTPEndpoint and comm:handler,
and ontology/shapes/seam-shapes.ttl constrains them. The seams library reads an
operation's implementation with ``ModelGraph.operation_implementation`` and
raises ``ResolutionError(subject, predicate)`` for each model fault of the
ADR's table that the library owns (the runtime owns the where-rule and the
handler import).
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, RDFS, BNode, Literal, Namespace, URIRef
from seams import IMPLEMENTATION_KINDS, Implementation, ModelGraph, ResolutionError
from seams.namespaces import COMM, HYDRA, SEAM

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHAT = Namespace("https://example.org/chat/")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")


@pytest.fixture(scope="module")
def model() -> ModelGraph:
    return ModelGraph(TRIG)


@pytest.fixture
def fresh() -> ModelGraph:
    """A private copy for tests that mutate the graph."""
    return ModelGraph(TRIG)


def declare(m: ModelGraph, impl: URIRef, *kinds: URIRef, handlers: tuple[str, ...] = ()) -> None:
    """Point :completion_op at ``impl`` (replacing its implementation) with these kinds and handlers."""
    ds, g = m.ds, m.ds.graph(SEAMS_GRAPH)
    ds.remove((CHAT.completion_op, SEAM.implementedBy, None, None))
    g.add((CHAT.completion_op, SEAM.implementedBy, impl))
    for kind in kinds:
        g.add((impl, RDF.type, kind))
    for handler in handlers:
        g.add((impl, COMM.handler, Literal(handler)))


# ---------------------------------------------------------------- library


def test_chat_app_completion_is_an_llm_completion(model: ModelGraph) -> None:
    assert model.operation_implementation(":completion_op") == Implementation(
        CHAT.completion_impl, COMM.LLMCompletion, None
    )


def test_in_process_operation_declares_nothing(model: ModelGraph) -> None:
    # The runtime serves :send_message_op itself (ADR-0012 migration).
    assert model.operation_implementation(":send_message_op") is None


def test_operation_view_lists_its_implementation(model: ModelGraph) -> None:
    op = model.operations.by_iri(":completion_op")
    assert op.implemented_by.iris() == (CHAT.completion_impl,)
    assert op.implemented_by.only().label == "LLM completion"


def test_kinds_are_the_three_comm_classes() -> None:
    assert set(IMPLEMENTATION_KINDS) == {COMM.LLMCompletion, COMM.PythonHandler, COMM.HTTPEndpoint}


@pytest.mark.parametrize("kind", [COMM.LLMCompletion, COMM.HTTPEndpoint])
def test_non_python_kinds_carry_no_handler(fresh: ModelGraph, kind: URIRef) -> None:
    declare(fresh, CHAT.impl, kind)
    assert fresh.operation_implementation(CHAT.completion_op) == Implementation(CHAT.impl, kind, None)


@pytest.mark.parametrize("handler", ["notify", "notify.notify_manager", "_pkg.sub_mod.Fn2"])
def test_python_handler_reads_its_dotted_path(fresh: ModelGraph, handler: str) -> None:
    declare(fresh, CHAT.impl, COMM.PythonHandler, handlers=(handler,))
    assert fresh.operation_implementation(CHAT.completion_op) == Implementation(CHAT.impl, COMM.PythonHandler, handler)


def test_two_implementations_name_the_operation(fresh: ModelGraph) -> None:
    declare(fresh, CHAT.impl, COMM.LLMCompletion)
    fresh.ds.graph(SEAMS_GRAPH).add((CHAT.completion_op, SEAM.implementedBy, CHAT.completion_impl))
    with pytest.raises(ResolutionError) as exc:
        fresh.operation_implementation(CHAT.completion_op)
    assert (exc.value.subject, exc.value.predicate) == (str(CHAT.completion_op), str(SEAM.implementedBy))


@pytest.mark.parametrize("node", [Literal("llm"), BNode()])
def test_an_implementation_that_is_not_an_iri_names_the_operation(fresh: ModelGraph, node) -> None:
    declare(fresh, CHAT.impl, COMM.LLMCompletion)
    fresh.ds.remove((CHAT.completion_op, SEAM.implementedBy, None, None))
    fresh.ds.graph(SEAMS_GRAPH).add((CHAT.completion_op, SEAM.implementedBy, node))
    with pytest.raises(ResolutionError) as exc:
        fresh.operation_implementation(CHAT.completion_op)
    assert (exc.value.subject, exc.value.predicate) == (str(CHAT.completion_op), str(SEAM.implementedBy))


@pytest.mark.parametrize(
    "kinds",
    [
        (),
        (COMM.LLMCompletion, COMM.HTTPEndpoint),
        (COMM.Channel,),
        (HYDRA.Operation,),
    ],
    ids=["no-kind", "two-kinds", "channel", "operation"],
)
def test_a_bad_kind_names_the_implementation_and_rdf_type(fresh: ModelGraph, kinds: tuple[URIRef, ...]) -> None:
    declare(fresh, CHAT.impl, *kinds)
    with pytest.raises(ResolutionError) as exc:
        fresh.operation_implementation(CHAT.completion_op)
    assert (exc.value.subject, exc.value.predicate) == (str(CHAT.impl), str(RDF.type))


@pytest.mark.parametrize(
    "handlers",
    [
        (),
        ("a.f", "b.g"),
        ("os/system",),
        (".notify",),
        ("..notify",),
        ("notify..f",),
        ("notify.",),
        ("1notify",),
        ("notify-manager",),
        ("",),
    ],
    ids=["missing", "two", "slash", "leading-dot", "parent", "empty-segment", "trailing-dot", "digit", "dash", "blank"],
)
def test_a_bad_handler_names_the_implementation_and_comm_handler(fresh: ModelGraph, handlers: tuple[str, ...]) -> None:
    declare(fresh, CHAT.impl, COMM.PythonHandler, handlers=handlers)
    with pytest.raises(ResolutionError) as exc:
        fresh.operation_implementation(CHAT.completion_op)
    assert (exc.value.subject, exc.value.predicate) == (str(CHAT.impl), str(COMM.handler))


def test_a_handler_iri_is_not_a_dotted_path(fresh: ModelGraph) -> None:
    declare(fresh, CHAT.impl, COMM.PythonHandler)
    fresh.ds.graph(SEAMS_GRAPH).add((CHAT.impl, COMM.handler, CHAT.notify))
    with pytest.raises(ResolutionError) as exc:
        fresh.operation_implementation(CHAT.completion_op)
    assert exc.value.predicate == str(COMM.handler)


# ---------------------------------------------------------------- shapes

PREFIXES = """
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix comm:  <https://w3id.org/seams/comm#> .
@prefix arch:  <https://w3id.org/seams/arch#> .
@prefix proc:  <https://w3id.org/seams/proc#> .
@prefix :      <https://example.org/impl/> .
"""


def violating_shapes(data: str) -> set[URIRef]:
    """The named shapes (or the named parent of a property shape) that report on
    ``data`` merged with the ontology files."""
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    g.parse(data=PREFIXES + data, format="turtle")
    shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    conforms, results, _ = pyshacl.validate(g, shacl_graph=shapes, inference="none")
    if conforms:
        return set()
    named: set[URIRef] = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        source = results.value(result, SH.sourceShape)
        parent = shapes.value(predicate=SH.property, object=source)
        named.add(parent if parent is not None else source)
    return named


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (":op a hydra:Operation ; seam:implementedBy :i . :i a comm:LLMCompletion .", set()),
        (":op a hydra:Operation ; seam:implementedBy :i . :i a comm:HTTPEndpoint .", set()),
        (
            ':op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler ; comm:handler "notify.notify_manager" .',
            set(),
        ),
        (
            ":op a hydra:Operation ; seam:implementedBy :i , :j . :i a comm:LLMCompletion . :j a comm:HTTPEndpoint .",
            {SEAMSH.ImplementedByShape},
        ),
        (":c a arch:Container ; seam:implementedBy :i . :i a comm:LLMCompletion .", {SEAMSH.ImplementedByShape}),
        (
            ':op a hydra:Operation ; seam:implementedBy "llm" .',
            {SEAMSH.ImplementedByShape, SEAMSH.ImplementationKindShape},
        ),
        (":op a hydra:Operation ; seam:implementedBy :i .", {SEAMSH.ImplementationKindShape}),
        (
            ":op a hydra:Operation ; seam:implementedBy :i . :i a comm:LLMCompletion , comm:HTTPEndpoint .",
            {SEAMSH.ImplementationKindShape},
        ),
        (":op a hydra:Operation ; seam:implementedBy :i . :i a comm:Channel .", {SEAMSH.ImplementationKindShape}),
        (":op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler .", {SEAMSH.PythonHandlerShape}),
        (
            ':op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler ; comm:handler "a.f" , "b.g" .',
            {SEAMSH.PythonHandlerShape},
        ),
        (
            ':op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler ; comm:handler "os/system" .',
            {SEAMSH.PythonHandlerShape},
        ),
        (
            ':op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler ; comm:handler "..notify" .',
            {SEAMSH.PythonHandlerShape},
        ),
        (
            ":op a hydra:Operation ; seam:implementedBy :i . :i a comm:PythonHandler ; comm:handler :notify .",
            {SEAMSH.PythonHandlerShape},
        ),
    ],
    ids=[
        "llm",
        "http",
        "python",
        "two-implementations",
        "not-an-operation",
        "literal",
        "no-kind",
        "two-kinds",
        "bad-kind",
        "no-handler",
        "two-handlers",
        "slash",
        "parent",
        "iri-handler",
    ],
)
def test_implementation_shapes(data: str, expected: set[URIRef]) -> None:
    assert violating_shapes(data) == expected


REMOTE = """
:process a proc:Process ; seam:detailedBy :bpmn .
:bpmn a seam:Model ; seam:notation seam:BPMN ; seam:renderPayload <p.bpmn> .
:task a proc:ServiceTask ; seam:inModel :bpmn ; seam:invokes :op .
:op a hydra:Operation .
:runtime a arch:Container ; seam:executes :process .
"""


def test_a_remote_invoked_operation_without_implementation_violates() -> None:
    assert violating_shapes(REMOTE + ":gateway a arch:Container ; seam:exposes :op .") == {
        SEAMSH.RemoteImplementationShape
    }


def test_a_remote_invoked_operation_with_implementation_conforms() -> None:
    data = (
        REMOTE + ":gateway a arch:Container ; seam:exposes :op . :op seam:implementedBy :i . :i a comm:HTTPEndpoint ."
    )
    assert violating_shapes(data) == set()


def test_an_in_process_operation_needs_no_implementation() -> None:
    assert violating_shapes(REMOTE + ":runtime seam:exposes :op .") == set()


def test_chat_app_without_its_declaration_violates_the_remote_rule(model: ModelGraph) -> None:
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    for s, p, o, _ in model.ds.quads((None, None, None, None)):
        if p != SEAM.implementedBy:
            g.add((s, p, o))
    conforms, results, _ = pyshacl.validate(g, shacl_graph=str(SHAPES_FILE), inference="none")
    assert not conforms
    focus = {
        results.value(r, SH.focusNode)
        for r in results.subjects(RDF.type, SH.ValidationResult)
        if results.value(r, SH.sourceShape) == SEAMSH.RemoteImplementationShape
    }
    assert focus == {CHAT.completion_op}


def test_implemented_by_is_documented_in_the_ontology() -> None:
    g = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        g.parse(p, format="turtle")
    assert g.value(SEAM.implementedBy, RDFS.label) == Literal("implemented by")
    assert g.value(SEAM.implementedBy, SEAM.reveal) == SEAM.Layer
    assert g.value(SEAM.implementedBy, RDFS.domain) == HYDRA.Operation
    for kind in IMPLEMENTATION_KINDS:
        assert (kind, RDF.type, RDFS.Class) in g
    assert (COMM.handler, RDF.type, RDF.Property) in g
