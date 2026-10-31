"""viewer/ifml.py derives the IFML diagram from seams model.interfaces
(M010/S06): the view the htmx generator reads, so IFML has one interpretation.
No direct graph traversal is left in the module, chapter-08's two IFML models
render, and a flow the generators would reject raises ResolutionError here too.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import seams  # noqa: E402
from rdflib import Dataset, URIRef  # noqa: E402
from seams import IFML, SEAM, ResolutionError  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import ifml, validation  # noqa: E402

CHAPTER_08 = ROOT / "examples" / "expenses" / "chapter-08"
CHAT = "https://example.org/chat/"
CHAT_IFML = f"{CHAT}chat_ifml"
STEREOTYPES = {IFML.List: "«List»", IFML.Details: "«Details»", IFML.Form: "«Form»"}


@pytest.fixture(autouse=True)
def restore_viewer():
    """Each test starts and ends on the default model with empty caches."""
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    yield
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    validation._clear_cache()


def _ifml_models(model: seams.Model) -> list[str]:
    return sorted(str(s) for s in model.ds.subjects(SEAM.notation, SEAM.IFML))


def test_ifml_module_does_not_traverse_the_graph():
    source = (ROOT / "viewer" / "ifml.py").read_text()
    for call in (".objects(", ".subjects(", ".subject_objects(", ".value(", ".triples(", "get_graph("):
        assert call not in source, call
    assert not re.search(r"\)\s+in\s+graph\b", source)
    assert "app.get_model().interfaces" in source


def test_chapter_08_ifml_models_render_from_the_interfaces_view():
    viewer_app.configure(CHAPTER_08)
    model = viewer_app.get_model()
    models = _ifml_models(model)
    assert models == ["https://example.org/expenses/expense_ifml", "https://example.org/expenses/finance_console"]
    seen: set[str] = set()
    for m in models:
        diagram = ifml.ifml_diagram(m)
        assert diagram["containers"] and diagram["components"], m
        for comp in diagram["components"]:
            view = model.interfaces.components().by_iri(comp["iri"])
            assert view.in_model(m)
            assert comp["stereotype"] == STEREOTYPES[view.types[0]]
            assert comp["iri"] not in seen  # one model's members only
            seen.add(comp["iri"])
        assert diagram["width"] > 0 and diagram["height"] > 0


def test_chat_components_are_the_pages_components():
    model = viewer_app.get_model()
    diagram = ifml.ifml_diagram(CHAT_IFML)
    pages = model.interfaces.pages().where(lambda p: p.in_model(CHAT_IFML))
    expected = {str(c.iri) for p in pages for c in p.components()}
    assert {c["iri"] for c in diagram["components"]} == expected
    assert {c["iri"] for c in diagram["containers"]} == {str(p.iri) for p in pages}


def _broken_chat(edit) -> seams.Model:
    """A copy of the chat model with ``edit`` applied to its Dataset."""
    model = viewer_app.get_model()
    ds = Dataset(default_union=True)
    for prefix, ns in model.ds.namespaces():
        ds.bind(prefix, ns)
    for quad in model.ds.quads((None, None, None, None)):
        ds.add(quad)
    edit(ds)
    return seams.Model(model.path, ds)


def test_flow_without_a_target_raises_resolution_error(monkeypatch):
    flow = URIRef(f"{CHAT}send_to_thread")
    broken = _broken_chat(lambda ds: ds.remove((flow, IFML.target, None)))
    monkeypatch.setattr(viewer_app, "_model", broken)
    with pytest.raises(ResolutionError) as err:
        ifml.ifml_diagram(CHAT_IFML)
    assert (err.value.subject, err.value.predicate) == (str(flow), str(IFML.target))


def test_binding_without_a_source_parameter_raises_resolution_error(monkeypatch):
    flow = URIRef(f"{CHAT}list_to_thread")

    def edit(ds):
        for binding in ds.objects(flow, IFML.binds):
            ds.remove((binding, IFML.sourceParameter, None))

    monkeypatch.setattr(viewer_app, "_model", _broken_chat(edit))
    with pytest.raises(ResolutionError) as err:
        ifml.ifml_diagram(CHAT_IFML)
    assert err.value.predicate == str(IFML.sourceParameter)
