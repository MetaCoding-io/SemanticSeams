"""The viewer's edit mode (ADR-0017, backlog I2, M019/S03).

Edit mode is off unless SEAMS_EDIT=1 when the viewer starts or configure() runs.
These tests copy the expense tutorial's chapter 8 to tmp_path, switch edit mode on
with monkeypatch and configure(), and edit the copy through the routes: the form
comes from the shapes, a save is a seams_edit patch, undo gives the original bytes,
and a value that breaks the shapes is saved and flagged on the health badge.

Target elements are found by querying the seam shapes, not by naming domain IRIs.
"""

import difflib
import logging
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import rdflib
from fastapi.testclient import TestClient
from rdflib import RDF, RDFS, XSD, Literal, URIRef
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import editing, validation  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-08"
SHAPES = rdflib.Graph().parse(ROOT / "ontology" / "shapes" / "seam-shapes.ttl", format="turtle")


def _copy(dest: Path) -> Path:
    shutil.copytree(CHAPTER, dest, ignore=shutil.ignore_patterns("generated"))
    return dest


@pytest.fixture
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model, edit mode off, after the test."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(original)


@pytest.fixture
def model(tmp_path, monkeypatch, restore_viewer) -> Path:
    """A copy of chapter 8 loaded in the viewer with edit mode on."""
    copy = _copy(tmp_path / "chapter-08")
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy)
    return copy


@pytest.fixture
def client(model) -> TestClient:
    return TestClient(viewer_app.app)


def _trig(model: Path) -> Path:
    (trig,) = sorted(model.glob("*.trig"))
    return trig


def _edit(iri: str) -> str:
    return f"/edit/{quote(iri, safe='')}"


def _integer_target(ds: rdflib.Dataset) -> tuple[str, str]:
    """An element with an xsd:integer value for a path some seam shape gives at most
    one xsd:integer, through sh:targetSubjectsOf of that path."""
    found = []
    for shape, path in SHAPES.subject_objects(SH.targetSubjectsOf):
        for prop in SHAPES.objects(shape, SH.property):
            if (
                SHAPES.value(prop, SH.path) == path
                and SHAPES.value(prop, SH.datatype) == XSD.integer
                and SHAPES.value(prop, SH.maxCount) == Literal(1)
            ):
                found += [
                    (str(s), str(path))
                    for s, o in ds.subject_objects(path)
                    if isinstance(o, Literal) and o.datatype == XSD.integer
                ]
    assert found, "chapter 8 has no element with a shaped xsd:integer value"
    return sorted(found)[0]


def _label_target(ds: rdflib.Dataset) -> str:
    """An element some seam shape gives exactly one rdfs:label, through
    sh:targetObjectsOf."""
    found = []
    for shape, predicate in SHAPES.subject_objects(SH.targetObjectsOf):
        if any(SHAPES.value(prop, SH.path) == RDFS.label for prop in SHAPES.objects(shape, SH.property)):
            found += [str(o) for o in ds.objects(None, predicate) if (o, RDFS.label, None) in ds]
    assert found, "chapter 8 has no element with a shaped rdfs:label"
    return sorted(found)[0]


def _iri_field_target(ds: rdflib.Dataset) -> tuple[str, str]:
    """An element with an editable IRI-valued text field."""
    for s in sorted({s for s in ds.subjects(RDF.type, None) if isinstance(s, URIRef)}, key=str):
        for f in editing.form_fields(ds, str(s)):
            if f.iri_valued and f.editable and f.kind == "text":
                return str(s), f.path
    raise AssertionError("chapter 8 has no element with an IRI-valued field")


def _changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0))
    removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
    added = [line for line in diff if line.startswith("+") and not line.startswith("+++")]
    return removed, added


# (a) off by default


def test_edit_routes_absent_without_seams_edit(tmp_path, monkeypatch, restore_viewer):
    copy = _copy(tmp_path / "chapter-08")
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(copy)
    client = TestClient(viewer_app.app)
    iri = _label_target(viewer_app.get_graph())
    before = _trig(copy).read_bytes()

    assert viewer_app.edit_enabled() is False
    assert client.get(_edit(iri)).status_code == 404
    assert client.post(_edit(iri), data={"field": str(RDFS.label), "value": "x"}).status_code == 404
    assert client.post("/edit/undo").status_code == 404
    assert _trig(copy).read_bytes() == before


def test_seams_edit_other_than_1_keeps_edit_mode_off(tmp_path, monkeypatch, restore_viewer):
    monkeypatch.setenv(viewer_app.EDIT_ENV, "true")
    viewer_app.configure(_copy(tmp_path / "chapter-08"))
    assert viewer_app.edit_enabled() is False
    assert TestClient(viewer_app.app).post("/edit/undo").status_code == 404


def test_configure_toggles_the_edit_routes(model, monkeypatch):
    assert viewer_app.edit_enabled() is True
    monkeypatch.delenv(viewer_app.EDIT_ENV)
    viewer_app.configure(model)
    assert viewer_app.edit_enabled() is False
    assert not [r for r in viewer_app.app.router.routes if getattr(r, "path", "").startswith("/edit")]


# (b) the form comes from the shapes


def test_form_lists_the_shaped_properties(client):
    ds = viewer_app.get_graph()
    iri, path = _integer_target(ds)
    fields = {f.path: f for f in editing.form_fields(ds, iri)}
    assert fields[path].datatype == str(XSD.integer)
    assert fields[path].max_count == 1
    assert fields[path].values == tuple(str(o) for o in ds.objects(URIRef(iri), URIRef(path)))

    response = client.get(_edit(iri))
    assert response.status_code == 200
    assert 'class="edit-form"' in response.text
    for f in fields.values():
        assert f'data-path="{f.path}"' in response.text


def test_form_fields_are_deterministic(client):
    ds = viewer_app.get_graph()
    iri, _ = _integer_target(ds)
    assert editing.form_fields(ds, iri) == editing.form_fields(ds, iri)
    first = client.get(_edit(iri)).text
    viewer_app.reload_model()
    assert client.get(_edit(iri)).text == first


def test_form_of_an_unknown_element_is_404(client):
    assert client.get(_edit("https://example.org/no-such-element")).status_code == 404


# (c) a save is a one-line patch, and the view shows it


def test_save_changes_one_line_and_the_form_shows_it(client, model, caplog):
    trig = _trig(model)
    before = trig.read_text()
    iri, path = _integer_target(viewer_app.get_graph())
    old = viewer_app.get_graph().value(URIRef(iri), URIRef(path))
    new = str(int(old) + 40)

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = client.post(_edit(iri), data={"field": path, "value": new})
    assert response.status_code == 200
    assert 'class="edit-saved"' in response.text
    assert f"{trig.name} (+1 &minus;1)" in response.text

    removed, added = _changed_lines(before, trig.read_text())
    assert len(removed) == 1 and len(added) == 1
    assert str(old) in removed[0] and new in added[0]
    assert viewer_app.get_graph().value(URIRef(iri), URIRef(path)) == Literal(int(new))
    assert f'value="{new}"' in client.get(_edit(iri)).text
    assert any(iri in r.message and trig.name in r.message and "+1 -1" in r.message for r in caplog.records)


def test_saved_label_shows_in_the_view(client, model):
    iri = _label_target(viewer_app.get_graph())
    response = client.post(_edit(iri), data={"field": str(RDFS.label), "value": "Renamed In Edit Mode"})
    assert response.status_code == 200
    view = client.get(f"/view/{quote(iri, safe='')}?format=json").json()
    assert view["@id"] == iri
    assert view["label"] == "Renamed In Edit Mode"
    assert '"Renamed In Edit Mode"' in _trig(model).read_text()


def test_unchanged_values_write_nothing(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, path = _integer_target(viewer_app.get_graph())
    old = str(viewer_app.get_graph().value(URIRef(iri), URIRef(path)))
    response = client.post(_edit(iri), data={"field": path, "value": old})
    assert "(no change)" in response.text
    assert trig.read_bytes() == before
    assert viewer_app._undo_stack == []


# (d) undo gives the original bytes


def test_undo_restores_the_original_bytes(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, path = _integer_target(viewer_app.get_graph())
    label_iri = _label_target(viewer_app.get_graph())
    client.post(_edit(iri), data={"field": path, "value": "77"})
    client.post(_edit(label_iri), data={"field": str(RDFS.label), "value": "Second Edit"})
    assert trig.read_bytes() != before

    first = client.post("/edit/undo")
    assert first.status_code == 200 and first.json()["remaining"] == 1
    assert "Second Edit" not in trig.read_text()
    second = client.post("/edit/undo")
    assert second.status_code == 200 and second.json()["remaining"] == 0
    assert trig.read_bytes() == before
    assert viewer_app.get_graph().value(URIRef(iri), URIRef(path)) != Literal(77)


def test_undo_with_nothing_to_undo_is_409(client):
    assert client.post("/edit/undo").status_code == 409


# (e) a value that breaks the shapes is saved and flagged


def test_wrong_datatype_is_saved_and_flagged(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, path = _integer_target(viewer_app.get_graph())
    assert validation.get_model_conformance(viewer_app.get_graph())["conforms"] is True

    response = client.post(_edit(iri), data={"field": path, "value": "not-a-number"})
    assert response.status_code == 200
    assert 'class="edit-saved"' in response.text
    assert 'data-conforms="false"' in response.text
    assert trig.read_bytes() != before
    assert '"not-a-number"' in trig.read_text()

    conformance = validation.get_model_conformance(viewer_app.get_graph())
    assert conformance["conforms"] is False
    assert any(v["focusNode"] == iri and v["path"] == path for v in conformance["violations"])
    page = client.get(f"/view/{quote(viewer_app.root_iri(), safe='')}")
    assert 'class="health-panel" data-conforms="false"' in page.text


def test_value_over_max_count_is_saved_and_flagged(client, model):
    iri, path = _integer_target(viewer_app.get_graph())
    response = client.post(
        _edit(iri),
        content=f"field={quote(path)}&value=5&value=6",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    values = set(viewer_app.get_graph().objects(URIRef(iri), URIRef(path)))
    assert values == {Literal(5), Literal(6)}
    conformance = validation.get_model_conformance(viewer_app.get_graph())
    assert any(v["focusNode"] == iri and v["path"] == path for v in conformance["violations"])


# writer faults: named in the form, nothing written


def test_malformed_iri_renders_the_patch_error(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, path = _iri_field_target(viewer_app.get_graph())
    response = client.post(_edit(iri), data={"field": path, "value": "not an iri"})
    assert response.status_code == 200
    assert 'class="edit-error"' in response.text
    assert f'data-subject="{iri}"' in response.text
    assert f'data-predicate="{path}"' in response.text
    assert "not an IRI" in response.text
    assert trig.read_bytes() == before
    assert viewer_app._undo_stack == []


def test_unshaped_field_is_400(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, _ = _integer_target(viewer_app.get_graph())
    response = client.post(_edit(iri), data={"field": "https://example.org/unshaped", "value": "x"})
    assert response.status_code == 400
    assert trig.read_bytes() == before


# (f) same model, same edit, same bytes


def test_same_edit_on_fresh_copies_gives_same_bytes(tmp_path, monkeypatch, restore_viewer):
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    results = []
    for name in ("first", "second"):
        copy = _copy(tmp_path / name / "chapter-08")
        viewer_app.configure(copy)
        client = TestClient(viewer_app.app)
        iri, path = _integer_target(viewer_app.get_graph())
        label_iri = _label_target(viewer_app.get_graph())
        client.post(_edit(iri), data={"field": path, "value": "not-a-number"})
        client.post(_edit(label_iri), data={"field": str(RDFS.label), "value": "Same Bytes"})
        results.append(_trig(copy).read_bytes())
    assert results[0] == results[1]
    assert results[0] != (CHAPTER / "expenses.trig").read_bytes()


# T02: the edit control in the view, and the health panel after a save

HX = {"Accept": "text/html", "hx-request": "true"}


def _view(iri: str) -> str:
    return f"/view/{quote(iri, safe='')}"


def test_edit_control_shows_only_in_edit_mode(tmp_path, monkeypatch, restore_viewer):
    copy = _copy(tmp_path / "chapter-08")
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(copy)
    iri, _ = _integer_target(viewer_app.get_graph())
    off = TestClient(viewer_app.app).get(_view(iri), headers=HX)
    assert off.status_code == 200
    assert 'class="edit-open"' not in off.text and 'id="edit-panel"' not in off.text

    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy)
    client = TestClient(viewer_app.app)
    on = client.get(_view(iri), headers=HX)
    focus = client.get(f"{_view(iri)}?format=json").json()["@id"]
    assert editing.form_fields(viewer_app.get_graph(), focus), "the landed element has a form"
    assert f'class="edit-open" hx-get="{_edit(focus)}"' in on.text
    assert 'id="edit-panel"' in on.text
    # The fragment is swapped into #view-content: the health panel stays in the shell.
    assert "health-panel" not in on.text
    assert 'class="edit-undo"' not in on.text


def test_edit_control_absent_for_an_element_no_shape_targets(client, monkeypatch):
    root = viewer_app.root_iri()
    assert 'class="edit-open"' in client.get(_view(root), headers=HX).text
    monkeypatch.setattr(editing, "form_fields", lambda ds, iri: [])
    assert 'class="edit-open"' not in client.get(_view(root), headers=HX).text


def test_save_response_carries_the_refreshed_health_panel(client, model):
    iri, path = _integer_target(viewer_app.get_graph())
    form = client.get(_edit(iri), headers=HX).text
    assert "health-panel" not in form

    response = client.post(_edit(iri), data={"field": path, "value": "not-a-number"}, headers=HX)
    assert response.status_code == 200
    oob = response.text.split('class="health-panel"', 1)[1].split(">", 1)[0]
    assert 'data-conforms="false"' in oob and 'hx-swap-oob="true"' in oob
    count = validation.get_model_conformance(viewer_app.get_graph())["violationCount"]
    assert f"{count} violation(s)" in response.text.split('class="health-panel"', 1)[1]
    assert 'class="edit-undo"' in response.text


def test_writer_fault_sends_no_health_panel(client, model):
    iri, path = _iri_field_target(viewer_app.get_graph())
    response = client.post(_edit(iri), data={"field": path, "value": "not an iri"}, headers=HX)
    assert 'class="edit-error"' in response.text
    assert "health-panel" not in response.text


def test_undo_control_after_a_save_and_htmx_undo_refreshes(client, model):
    trig = _trig(model)
    before = trig.read_bytes()
    iri, path = _integer_target(viewer_app.get_graph())
    client.post(_edit(iri), data={"field": path, "value": "91"})
    view = client.get(_view(iri), headers=HX).text
    assert 'class="edit-undo" hx-post="/edit/undo"' in view

    response = client.post("/edit/undo", headers=HX)
    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
    assert trig.read_bytes() == before
    assert 'class="edit-undo"' not in client.get(_view(iri), headers=HX).text
