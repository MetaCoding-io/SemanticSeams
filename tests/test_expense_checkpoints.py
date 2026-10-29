"""Checkpoint tests for the expense approval tutorial (docs/tutorials/expenses/).

Each examples/expenses/chapter-NN/expenses.trig is a cumulative copy of the
model at the end of chapter NN (D026). Every checkpoint that exists is checked:
it parses, conforms to seam-shapes.ttl, keeps seam predicates in the seams
graph, keeps every named graph of the chapter before it, and opens in the
viewer at its C4 model with a conforming health panel. A new chapter directory
joins the parametrization without editing this file.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import rdflib
from rdflib import Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from validate_chat_app import (  # noqa: E402
    ONTOLOGY_FILES,
    check_isolation,
    check_shacl,
    union_graph,
)
from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

EXPENSES = ROOT / "examples" / "expenses"
CHAPTERS = sorted(p.parent for p in EXPENSES.glob("chapter-*/expenses.trig"))
CHAPTER_IDS = [p.name for p in CHAPTERS]

SEAM = Namespace("https://w3id.org/seams/seam#")
EX = Namespace("https://example.org/expenses/")
DEFAULT_GRAPH = URIRef("urn:x-rdflib:default")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
EXPENSE_ARCHITECTURE = str(EX.expense_architecture)

# Chapter 2's deliberate mistake, quoted by the chapter 2 tutorial page: the
# reader forgets to give the new data model its notation. ModelShape (every
# seam:Model has exactly one seam:notation) rejects it with :expense_data as
# the sh:focusNode.
CHAPTER_2_MISTAKE_GRAPH = SEAMS_GRAPH
CHAPTER_2_MISTAKE_TRIPLE = (EX.expense_data, SEAM.notation, SEAM.ShapeGraph)
CHAPTER_2_MISTAKE_TEXT = ":expense_data seam:notation seam:ShapeGraph ."


def load_checkpoint(chapter: Path) -> rdflib.Dataset:
    """The checkpoint plus the ontology in the default graph, as
    validate_chat_app.load_chat_app_dataset loads the chat app."""
    ds = rdflib.Dataset()
    for p in ONTOLOGY_FILES:
        ds.default_graph.parse(p, format="turtle")
    ds.parse(chapter / "expenses.trig", format="trig")
    return ds


def named_graphs(ds: rdflib.Dataset) -> set[URIRef]:
    return {
        g.identifier
        for g in ds.graphs()
        if g.identifier != DEFAULT_GRAPH and len(g) > 0
    }


@pytest.fixture
def restore_viewer(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    viewer_app.configure(original)
    validation._clear_cache()


def test_chapters_one_and_two_exist():
    assert {"chapter-01", "chapter-02"} <= set(CHAPTER_IDS), CHAPTER_IDS


@pytest.mark.parametrize("chapter", CHAPTERS, ids=CHAPTER_IDS)
def test_checkpoint_parses_into_named_graphs(chapter):
    ds = load_checkpoint(chapter)
    graphs = named_graphs(ds)
    assert URIRef("urn:seams:graph:model:expense_architecture") in graphs
    assert SEAMS_GRAPH in graphs


@pytest.mark.parametrize("chapter", CHAPTERS, ids=CHAPTER_IDS)
def test_checkpoint_conforms_to_shapes(chapter):
    assert check_shacl(union_graph(load_checkpoint(chapter))) == []


@pytest.mark.parametrize("chapter", CHAPTERS, ids=CHAPTER_IDS)
def test_checkpoint_keeps_seam_predicates_in_seams_graph(chapter):
    assert check_isolation(load_checkpoint(chapter)) == []


@pytest.mark.parametrize("chapter", CHAPTERS[1:], ids=CHAPTER_IDS[1:])
def test_checkpoint_keeps_previous_chapters_graphs(chapter):
    previous = CHAPTERS[CHAPTERS.index(chapter) - 1]
    missing = named_graphs(load_checkpoint(previous)) - named_graphs(load_checkpoint(chapter))
    assert not missing, f"{chapter.name} dropped {sorted(map(str, missing))}"


@pytest.mark.parametrize("chapter", CHAPTERS, ids=CHAPTER_IDS)
def test_checkpoint_opens_in_viewer(chapter, restore_viewer):
    viewer_app.configure(chapter / "expenses.trig")
    client = TestClient(viewer_app.app)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    view = f"/view/{quote(EXPENSE_ARCHITECTURE, safe='')}"
    assert resp.headers["location"] == view
    assert client.get(view).status_code == 200
    conformance = validation.get_model_conformance(viewer_app.get_graph())
    assert conformance["conforms"], conformance["violations"]


def test_chapter_2_mistake_names_the_model():
    ds = load_checkpoint(EXPENSES / "chapter-02")
    graph = ds.graph(CHAPTER_2_MISTAKE_GRAPH)
    assert CHAPTER_2_MISTAKE_TRIPLE in graph
    graph.remove(CHAPTER_2_MISTAKE_TRIPLE)
    errors = check_shacl(union_graph(ds))
    assert errors, "removing the notation should break conformance"
    report = errors[0]
    assert f"Focus Node: <{EX.expense_data}>" in report
    assert "seam:notation" in report or str(SEAM.notation) in report


def test_chapter_2_mistake_text_is_in_the_checkpoint():
    """The quoted line T04's prose shows is literally in the file."""
    text = (EXPENSES / "chapter-02" / "expenses.trig").read_text()
    assert CHAPTER_2_MISTAKE_TEXT in text
