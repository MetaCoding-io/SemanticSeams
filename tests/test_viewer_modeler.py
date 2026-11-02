"""BPMN and DMN modelers in the viewer's edit mode (ADR-0017, ADR-0002 rule 5, M019/S04).

With SEAMS_EDIT=1 the shell loads the bpmn.io modeler bundles instead of the viewers,
and a BPMN or DMN view carries the modeler bar. Save posts the modeler's XML and the
ids it renamed to POST /edit/payload/{model}: each rename moves the seam edges of the
lifted IRI, the XML is written as given, and one /edit/undo gives every file its bytes
back. A save the writer refuses is a 409 naming the fact and leaves every byte alone.

These tests edit a tmp copy of the expense tutorial's chapter 9. The models and the
ids are found by querying the loaded model, not by naming domain IRIs.
"""

import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import seams
from fastapi.testclient import TestClient
from rdflib import BNode, URIRef
from seams import DEC

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import seams_edit  # noqa: E402
from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-09"
SUFFIXES = (".trig", ".bpmn", ".dmn")
MODELER_BUNDLES = ("bpmn-modeler.production.min.js", "dmn-modeler.production.min.js")
VIEWER_BUNDLES = ("bpmn-navigated-viewer.production.min.js", "dmn-navigated-viewer.production.min.js")


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
    """A copy of chapter 9 loaded in the viewer with edit mode on."""
    copy = _copy(tmp_path / "chapter-09")
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy)
    return copy


@pytest.fixture
def client(model) -> TestClient:
    return TestClient(viewer_app.app)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.suffix in SUFFIXES}


def _lifted(ds, model_iri: URIRef) -> set[URIRef]:
    prefix = f"{model_iri}#"
    return {t for q in ds.quads() for t in (q[0], q[2]) if isinstance(t, URIRef) and str(t).startswith(prefix)}


def _quads_naming(ds, iri: URIRef) -> list:
    return [q for q in ds.quads() if iri in (q[0], q[2])]


def _bound(ds, model_iri: URIRef) -> dict[str, list]:
    """Payload id -> the decisions of the model that ``dec:payloadElement`` binds to it."""
    found: dict[str, list] = {}
    for d in sorted(ds.subjects(validation.SEAM.inModel, model_iri), key=str):
        for o in ds.objects(d, DEC.payloadElement):
            found.setdefault(str(o), []).append(d)
    return found


def _target(path: Path, notation) -> tuple[URIRef, Path, str]:
    """The first model of ``notation`` with a payload and an id the seams graph names,
    as (model IRI, payload path, id): a lifted ``modelIRI#id``, else (DMN) an id a
    decision's ``dec:payloadElement`` binds."""
    m = seams.load(path)
    for model_iri in sorted(m.ds.subjects(validation.SEAM.notation, notation), key=str):
        if not isinstance(model_iri, URIRef) or m.ds.value(model_iri, validation.SEAM.renderPayload) is None:
            continue
        named = sorted(str(t).partition("#")[2] for t in _lifted(m.ds, model_iri)) or sorted(_bound(m.ds, model_iri))
        if named:
            return model_iri, m.payload_path(model_iri), named[0]
    raise AssertionError(f"no {notation} model with an id the seams graph names in the chapter")


def _renamed(xml: str, old: str, new: str) -> str:
    """What the modeler would save after renaming ``old``: every whole-token use of
    the id (its ``id``, each reference and ``#old`` href) written as ``new``."""
    return re.sub(rf"(?<![\w.\-]){re.escape(old)}(?![\w.\-])", new, xml)


def _view(iri: URIRef) -> str:
    return f"/view/{quote(str(iri), safe='')}"


def _save(iri: URIRef) -> str:
    return f"/edit/payload/{quote(str(iri), safe='')}"


NOTATIONS = pytest.mark.parametrize("notation", validation.LIFTED_NOTATIONS, ids=["bpmn", "dmn"])


def test_viewer_bundles_and_no_route_without_seams_edit(tmp_path, monkeypatch, restore_viewer):
    copy = _copy(tmp_path / "chapter-09")
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(copy)
    model_iri, payload, _ = _target(copy, validation.SEAM.BPMN)
    client = TestClient(viewer_app.app)
    page = client.get(_view(model_iri)).text
    assert all(b in page for b in VIEWER_BUNDLES)
    assert not any(b in page for b in MODELER_BUNDLES)
    assert 'id="modeler-bar"' not in page
    before = _snapshot(copy)
    response = client.post(_save(model_iri), json={"xml": payload.read_text(), "renames": []})
    assert response.status_code in (404, 405)
    assert _snapshot(copy) == before


@NOTATIONS
def test_modeler_bundles_and_bar_only_in_edit_mode(client, model, notation):
    model_iri, _, _ = _target(model, notation)
    page = client.get(_view(model_iri)).text
    assert all(b in page for b in MODELER_BUNDLES)
    assert not any(b in page for b in VIEWER_BUNDLES)
    assert 'id="modeler-bar"' in page
    assert f'data-save="{_save(model_iri)}"' in page
    # Fragment swaps carry the bar too; the bundles stay in the shell.
    fragment = client.get(_view(model_iri), headers={"hx-request": "true"}).text
    assert 'id="modeler-bar"' in fragment
    assert not any(b in fragment for b in MODELER_BUNDLES)


def test_non_payload_view_has_no_modeler_bar(client, model):
    root = viewer_app.root_iri()
    page = client.get(_view(URIRef(root))).text
    assert 'id="modeler-bar"' not in page
    response = client.post(_save(URIRef(root)), json={"xml": "<x/>", "renames": []})
    assert response.status_code == 404


@NOTATIONS
def test_save_with_rename_moves_the_seam_edges_and_undo_restores(client, model, notation, caplog):
    model_iri, payload, old = _target(model, notation)
    new = f"{old}_renamed"
    before = _snapshot(model)
    ds = seams.load(model).ds
    old_iri, new_iri = URIRef(f"{model_iri}#{old}"), URIRef(f"{model_iri}#{new}")
    old_edges = sorted(
        (p, o if o != old_iri else new_iri) for _s, p, o, _g in _quads_naming(ds, old_iri) if _s == old_iri
    )
    old_bound = _bound(ds, model_iri).get(old, [])
    assert old_edges or old_bound

    xml = _renamed(payload.read_text(encoding="utf-8"), old, new)
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = client.post(_save(model_iri), json={"xml": xml, "renames": [{"old": old, "new": new}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is True
    touched = {f["file"] for f in body["files"]}
    assert payload.name in touched
    assert any(name.endswith(".trig") for name in touched)
    assert any("payload saved" in r.message and f"{old} -> {new}" in r.message for r in caplog.records)

    assert payload.read_text(encoding="utf-8") == xml
    after = seams.load(model)
    assert _quads_naming(after.ds, old_iri) == []
    assert sorted((p, o) for _s, p, o, _g in _quads_naming(after.ds, new_iri) if _s == new_iri) == old_edges
    assert old not in _bound(after.ds, model_iri)
    assert _bound(after.ds, model_iri).get(new, []) == old_bound
    assert validation.get_lifted_iri_health(after.ds, after.base_dir) == []
    # The view reads the saved model.
    if old_edges:
        assert old not in viewer_app.payload_element_map(str(model_iri))
        assert new in viewer_app.payload_element_map(str(model_iri))

    undone = client.post("/edit/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["remaining"] == 0
    assert _snapshot(model) == before


def test_save_without_renames_writes_the_xml_and_undoes(client, model):
    model_iri, payload, _ = _target(model, validation.SEAM.BPMN)
    before = _snapshot(model)
    xml = payload.read_text(encoding="utf-8").replace("\n", "\n  ", 1)
    response = client.post(_save(model_iri), json={"xml": xml, "renames": []})
    assert response.status_code == 200, response.text
    assert [f["file"] for f in response.json()["files"]] == [payload.name]
    assert payload.read_text(encoding="utf-8") == xml
    assert client.post("/edit/undo").status_code == 200
    assert _snapshot(model) == before


def test_same_xml_writes_nothing_and_pushes_no_undo(client, model):
    model_iri, payload, _ = _target(model, validation.SEAM.BPMN)
    before = _snapshot(model)
    response = client.post(_save(model_iri), json={"xml": payload.read_text(encoding="utf-8"), "renames": []})
    assert response.status_code == 200
    assert response.json()["files"] == []
    assert _snapshot(model) == before
    assert client.post("/edit/undo").status_code == 409


@NOTATIONS
def test_bad_xml_is_409_and_rolls_back_the_renames(client, model, notation):
    model_iri, payload, old = _target(model, notation)
    before = _snapshot(model)
    response = client.post(
        _save(model_iri),
        json={"xml": "<definitions><unclosed></definitions>", "renames": [{"old": old, "new": f"{old}_x"}]},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["subject"] == str(payload.resolve())
    assert error["predicate"].startswith("line ")
    assert "not well-formed" in error["detail"]
    assert _snapshot(model) == before
    assert client.post("/edit/undo").status_code == 409


def test_colliding_rename_is_409_naming_the_id(client, model):
    model_iri, payload, old = _target(model, validation.SEAM.BPMN)
    ids = sorted(set(re.findall(r'\bid="([^"]+)"', payload.read_text(encoding="utf-8"))) - {old})
    before = _snapshot(model)
    response = client.post(
        _save(model_iri), json={"xml": payload.read_text(encoding="utf-8"), "renames": [{"old": old, "new": ids[0]}]}
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["subject"] == f"{model_iri}#{old}"
    assert error["predicate"] == "id"
    assert ids[0] in error["detail"]
    assert _snapshot(model) == before


def test_second_rename_failing_undoes_the_first(client, model):
    model_iri, payload, old = _target(model, validation.SEAM.BPMN)
    before = _snapshot(model)
    renames = [{"old": old, "new": f"{old}_a"}, {"old": "no_such_id_in_payload", "new": "whatever"}]
    response = client.post(_save(model_iri), json={"xml": payload.read_text(encoding="utf-8"), "renames": renames})
    assert response.status_code == 409
    assert "no_such_id_in_payload" in response.json()["error"]["detail"]
    assert _snapshot(model) == before


@pytest.mark.parametrize(
    "body",
    [{"renames": []}, {"xml": 1}, {"xml": "<x/>", "renames": [{"old": "a"}]}, {"xml": "<x/>", "renames": "a"}, ["x"]],
)
def test_malformed_body_is_400(client, model, body):
    model_iri, _, _ = _target(model, validation.SEAM.BPMN)
    before = _snapshot(model)
    assert client.post(_save(model_iri), json=body).status_code == 400
    assert _snapshot(model) == before


def test_combine_folds_successive_edits_into_one_undo(model):
    model_iri, payload, old = _target(model, validation.SEAM.BPMN)
    files = seams.load(model).files
    before = _snapshot(model)
    first = seams_edit.rename_id(files, payload, model_iri, old, f"{old}_1")
    second = seams_edit.rename_id(files, payload, model_iri, f"{old}_1", f"{old}_2")
    combined = seams_edit.combine([first, second])
    assert {e.path.name for e in combined.files} == {e.path.name for e in first.files}
    # The intermediate id cancels out of the folded patch. Quads with a blank node
    # do not: each rename writes the node afresh, under a new label.
    old_iri = URIRef(f"{model_iri}#{old}")
    assert all(old_iri not in (q[0], q[2]) for q in combined.patch.adds)
    named = [q for q in combined.patch.adds + combined.patch.removes if not any(isinstance(t, BNode) for t in q)]
    assert not any(str(t).endswith(f"#{old}_1") for q in named for t in q)
    seams_edit.undo(combined)
    assert _snapshot(model) == before


def test_combine_refuses_a_file_changed_since(model):
    model_iri, payload, old = _target(model, validation.SEAM.BPMN)
    files = seams.load(model).files
    record = seams_edit.rename_id(files, payload, model_iri, old, f"{old}_1")
    payload.write_bytes(payload.read_bytes().replace(f'"{old}_1"'.encode(), b'"changed"'))
    with pytest.raises(seams_edit.PatchError):
        seams_edit.combine([record])
