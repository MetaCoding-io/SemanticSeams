"""A shape's lifecycle derived through sh:targetClass in packages/seams (ADR-0031, M028/S04).

Each case loads a minimal inline TriG model: an ``:Order`` class, an ``:OrderShape``
that targets it and an ``:order_lifecycle``. The seams graph names the lifecycle on the
shape (the compatible form) or on the class (the preferred form); the views, the graph
helpers and the review check answer the same either way.
"""

from pathlib import Path

import pytest
from seams import ModelGraph, ResolutionError, ReviewFinding
from seams.review_check import lifecycle_label_findings

EX = "https://example.org/ex/"
SEAM_LIFECYCLE = "https://w3id.org/seams/seam#lifecycle"

PREFIXES = """\
@prefix :     <https://example.org/ex/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
"""

MODEL = """
<urn:seams:graph:model:shapes> {
    :Order a owl:Class .
    :status a owl:ObjectProperty .
    :OrderShape a sh:NodeShape ; sh:targetClass :Order ;
        sh:property [ sh:path :status ; sh:in ( :s_open :s_closed ) ] .
    :NoteShape a sh:NodeShape .
}
<urn:seams:graph:model:order_lifecycle> {
    :order_lifecycle a state:StateMachine ; state:initial :s_open ;
        state:hasState :s_open , :s_closed ; state:hasTransition :t_close .
    :s_open a state:State ; rdfs:label "open" .
    :s_closed a state:State ; rdfs:label "closed" .
    :t_close a state:Transition ; state:from :s_open ; state:to :s_closed .
    :other_lifecycle a state:StateMachine ; state:initial :s_new ; state:hasState :s_new .
    :s_new a state:State ; rdfs:label "new" .
}
<urn:seams:graph:seams> {
    SEAMS
}
"""

ON_SHAPE = ":OrderShape seam:lifecycle :order_lifecycle ."
ON_CLASS = ":Order seam:lifecycle :order_lifecycle ."


def _load(tmp_path: Path, seams_graph: str, model: str = MODEL) -> ModelGraph:
    trig = tmp_path / "model.trig"
    trig.write_text(PREFIXES + model.replace("SEAMS", seams_graph))
    return ModelGraph(trig)


@pytest.mark.parametrize("form", [ON_SHAPE, ON_CLASS, ON_SHAPE + "\n" + ON_CLASS], ids=["shape", "class", "both"])
def test_the_shape_lifecycle_is_its_own_or_its_class(tmp_path: Path, form: str) -> None:
    model = _load(tmp_path, form)
    lifecycle = model.shape(":OrderShape").lifecycle
    assert lifecycle is not None
    assert lifecycle.iri == model.curie(":order_lifecycle")


def test_a_shape_with_no_lifecycle_on_it_or_its_class_has_none(tmp_path: Path) -> None:
    model = _load(tmp_path, ON_CLASS)
    assert model.shape(":NoteShape").lifecycle is None
    assert not model.has_lifecycle(":NoteShape")


@pytest.mark.parametrize("form", [ON_SHAPE, ON_CLASS], ids=["shape", "class"])
def test_lifecycle_shapes_are_the_shapes_whose_lifecycle_it_is(tmp_path: Path, form: str) -> None:
    model = _load(tmp_path, form)
    lifecycle = model.lifecycles.by_iri(":order_lifecycle")
    assert lifecycle.shapes.iris() == (model.curie(":OrderShape"),)
    shape = lifecycle.shape
    assert shape is not None and shape.iri == model.curie(":OrderShape")


def test_lifecycle_shapes_from_the_class_are_sorted_by_iri(tmp_path: Path) -> None:
    second = MODEL.replace(":NoteShape a sh:NodeShape .", ":AnOrderShape a sh:NodeShape ; sh:targetClass :Order .")
    model = _load(tmp_path, ON_CLASS, second)
    shapes = model.lifecycles.by_iri(":order_lifecycle").shapes
    assert shapes.iris() == (model.curie(":AnOrderShape"), model.curie(":OrderShape"))


def test_graph_helpers_follow_the_class_lifecycle(tmp_path: Path) -> None:
    model = _load(tmp_path, ON_CLASS)
    assert model.has_lifecycle(":OrderShape")
    found = model.lifecycle_for(":OrderShape")
    assert found.iri == model.curie(":order_lifecycle")
    assert found.initial == "open"
    assert model.lifecycle_shape(":t_close") == model.curie(":OrderShape")


def test_two_effective_lifecycles_raise_naming_both(tmp_path: Path) -> None:
    model = _load(tmp_path, ON_CLASS + "\n:OrderShape seam:lifecycle :other_lifecycle .")
    with pytest.raises(ResolutionError) as raised:
        _ = model.shape(":OrderShape").lifecycle
    error = raised.value
    assert error.subject == f"{EX}OrderShape"
    assert error.predicate == SEAM_LIFECYCLE
    assert error.detail == (
        "more than one effective lifecycle, its own or its sh:targetClass's: :order_lifecycle, :other_lifecycle"
    )


def test_review_check_reads_the_lifecycle_through_the_class(tmp_path: Path) -> None:
    model = _load(tmp_path, ON_CLASS, MODEL.replace("sh:in ( :s_open :s_closed )", 'sh:in ( "closed" "open" )'))
    assert lifecycle_label_findings(model) == [
        ReviewFinding(
            f"{EX}OrderShape",
            f"{EX}status",
            "sh:in on status copies the rdfs:labels of order_lifecycle's states, so it can drift "
            "from the lifecycle; use the state IRIs (s_closed, s_open)",
        )
    ]


def test_review_check_with_two_lifecycles_does_not_raise(tmp_path: Path) -> None:
    body = MODEL.replace("sh:in ( :s_open :s_closed )", 'sh:in ( "closed" "open" )')
    model = _load(tmp_path, ON_CLASS + "\n:OrderShape seam:lifecycle :other_lifecycle .", body)
    assert [f.subject for f in lifecycle_label_findings(model)] == [f"{EX}OrderShape"]
