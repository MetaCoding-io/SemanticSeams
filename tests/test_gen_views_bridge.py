"""The seams_gen view bridge (M010/S05): view ``ResolutionError``s surface as
``GeneratorError`` naming the same subject and predicate, with the generators'
"expected exactly one" wording, and extract_page and fragment_for read seams
views (any ``seams.Model``) rather than raw triples."""

from pathlib import Path

import pytest
import seams
from rdflib import Dataset, Literal, URIRef
from seams import IFML, SEAM, Many, ResolutionError

from seams_gen import GeneratorError, extract_page, fragment_for
from seams_gen._views import label, only, optional, required, view_errors

ROOT = Path(__file__).resolve().parent.parent
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHAT = "https://example.org/chat/"
IFML_GRAPH = URIRef("urn:seams:graph:model:chat_ifml")


def _dataset() -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(TRIG), format="trig")
    return ds


def _iri(local: str) -> URIRef:
    return URIRef(CHAT + local)


def test_only_and_optional_name_the_many_fact():
    model = seams.load(TRIG)
    page = model.interfaces.landmark()
    empty = Many((), page.iri, IFML.hasEvent)
    with pytest.raises(GeneratorError) as err:
        only(empty, "the page's event")
    assert (err.value.subject, err.value.predicate) == (str(page.iri), str(IFML.hasEvent))
    assert err.value.detail == "the page's event: expected exactly one, found none"
    parts = page.components()
    assert len(parts) > 1
    with pytest.raises(GeneratorError) as err:
        optional(parts)
    assert err.value.detail.startswith("expected at most one, found " + str(parts[0].iri))
    assert optional(empty) is None
    assert only(Many(parts[:1], page.iri, IFML.contains)) is parts[0]


def test_required_and_strict_label():
    model = seams.load(TRIG)
    assert required("x", "s", "p") == "x"
    with pytest.raises(GeneratorError, match="expected exactly one, found none"):
        required(None, CHAT + "chat_page", IFML.title)
    with pytest.raises(GeneratorError) as err:
        label(model, "urn:unlabelled")
    assert err.value.subject == "urn:unlabelled" and err.value.predicate.endswith("#label")


def test_view_errors_keeps_subject_and_predicate():
    with pytest.raises(GeneratorError) as err, view_errors():
        raise ResolutionError(CHAT + "x", IFML.swap, "expected exactly one, found none")
    assert (err.value.subject, err.value.predicate, err.value.detail) == (
        CHAT + "x",
        str(IFML.swap),
        "expected exactly one, found none",
    )
    assert isinstance(err.value.__cause__, ResolutionError)


def test_non_integer_order_is_a_generator_error():
    ds = _dataset()
    for g in ds.graphs():
        g.remove((_iri("message_thread"), IFML.order, None))
    ds.graph(IFML_GRAPH).add((_iri("message_thread"), IFML.order, Literal("second")))
    with pytest.raises(GeneratorError) as err:
        extract_page(seams.Model(TRIG, dataset=ds))
    assert (err.value.subject, err.value.predicate) == (CHAT + "message_thread", str(IFML.order))


def test_plain_model_and_operation_view_are_accepted():
    model = seams.load(TRIG)
    op = model.operations.by_iri(":send_message_op")
    assert fragment_for(model, op) == fragment_for(model, op.iri)
    assert extract_page(model).curie == ":chat_page"
    # an operation rendering two components names (operation, seam:rendersComponent)
    ds = _dataset()
    ds.graph(URIRef("urn:seams:graph:seams")).add((op.iri, SEAM.rendersComponent, _iri("conversation_list")))
    with pytest.raises(GeneratorError) as err:
        fragment_for(seams.Model(TRIG, dataset=ds), op.iri)
    assert (err.value.subject, err.value.predicate) == (str(op.iri), str(SEAM.rendersComponent))
