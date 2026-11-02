"""Structural edit routes in the generation view (backlog T5, M021/S02): viewer.app.

Each test copies the chat app, and the compose files it generates at the
repository root, into tmp_path with the same layout (as
tests/test_viewer_generation_writeback.py), points the viewer at the copy with
configure() and posts whole edited outputs to /generation/structural/preview and
/apply. The removal edit is spliced from what the generator emits for the model
without the parameter; the facts asserted are read from the copied model.
"""

import difflib
import re
import shutil
import sys
from html import unescape
from pathlib import Path
from urllib.parse import quote

import pytest
import seams
from fastapi.testclient import TestClient
from rdflib import RDF, URIRef
from seams_cli import generate_project, load_project

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_edit import Patch  # noqa: E402
from viewer import app as viewer_app  # noqa: E402
from viewer import generation, structural, validation, writeback  # noqa: E402

CHAT = ROOT / "examples" / "chat-app"
PAGE = "generated/templates/chat_page.html"
IFML = "https://w3id.org/seams/ifml#"
HAS_PARAMETER = URIRef(IFML + "hasParameter")
FORM = URIRef(IFML + "Form")
WRITES = URIRef("https://w3id.org/seams/seam#writes")
PREVIEW = "/generation/structural/preview"
APPLY = "/generation/structural/apply"


@pytest.fixture(autouse=True)
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model, edit mode off, after the test."""
    original = viewer_app.MODEL_PATH
    generation._clear_cache()
    validation._clear_cache()
    yield
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(original)
    generation._clear_cache()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The chat app at tmp_path/examples/chat-app, its compose files at tmp_path."""
    copy = tmp_path / "examples" / "chat-app"
    shutil.copytree(CHAT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    for compose in sorted(ROOT.glob("compose.*.yaml*")):
        shutil.copyfile(compose, tmp_path / compose.name)
    return copy


@pytest.fixture
def client(project: Path, monkeypatch) -> TestClient:
    """The viewer on the copy, edit mode on."""
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(project / "chat-app.trig")
    return TestClient(viewer_app.app)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _page(project: Path) -> str:
    return (project / PAGE).read_text(encoding="utf-8")


def _form_parameter(project: Path) -> tuple[URIRef, URIRef, Patch]:
    """The chat page's form that writes a shape, its one parameter, and the patch
    dropping that parameter."""
    ds = seams.load(project / "chat-app.trig").ds
    ((form, _shape),) = [(s, o) for s, o in ds.subject_objects(WRITES) if (s, RDF.type, FORM) in ds]
    (param,) = ds.objects(form, HAS_PARAMETER)
    ((graph,),) = {(g,) for _s, _p, _o, g in ds.quads((form, HAS_PARAMETER, param, None))}
    assert isinstance(form, URIRef) and isinstance(param, URIRef) and isinstance(graph, URIRef)
    removes = [*ds.quads((param, None, None, None)), (form, HAS_PARAMETER, param, graph)]
    return form, param, Patch(removes=removes)


def _removed(project: Path, patch: Patch) -> str:
    """The committed page with the form block the generator writes without the
    parameter spliced in: every changed line but the model-hash lines."""
    old_hex = seams.load(project / "chat-app.trig").hash.removeprefix("sha256:")
    regenerated = writeback.regenerate(project, project / "chat-app.trig", patch, PAGE, "output")
    old = _page(project).splitlines(keepends=True)
    new = regenerated.texts[PAGE].splitlines(keepends=True)
    new_hex = regenerated.new_hash.removeprefix("sha256:")
    ops = [
        op
        for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if op[0] != "equal" and not all(new_hex in line for line in new[op[3] : op[4]])
    ]
    assert len(ops) == 1, ops
    _tag, i1, i2, j1, j2 = ops[0]
    return "".join(old[:i1] + [line.replace(new_hex, old_hex) for line in new[j1:j2]] + old[i2:])


def _two_blocks(project: Path) -> str:
    """The page with two separate lines changed: always refused."""
    lines = _page(project).splitlines(keepends=True)
    title = next(n for n, t in enumerate(lines) if "<title>" in t)
    lines[title] = lines[title].replace("</title>", " now</title>")
    lines[-1] = lines[-1].rstrip("\n") + " \n"
    return "".join(lines)


def _form(output: str, text: str, iri: str = "") -> dict[str, str]:
    return {"output": output, "text": text, "iri": iri}


def _status(html: str) -> str:
    match = re.search(r'id="writeback-result"\s+data-status="(\w+)"', html)
    assert match, html
    return match.group(1)


def _view(client: TestClient, iri: URIRef) -> str:
    response = client.get(f"/generation/{quote(str(iri), safe='')}?output={quote(PAGE, safe='')}")
    assert response.status_code == 200
    return response.text


def test_structural_routes_are_not_mounted_without_edit_mode(project: Path, monkeypatch):
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(project / "chat-app.trig")
    client = TestClient(viewer_app.app)
    form, _param, _patch = _form_parameter(project)
    for route in (PREVIEW, APPLY):
        assert client.post(route, data=_form(PAGE, _page(project))).status_code in (404, 405)
    assert 'id="structural-form"' not in _view(client, form)


def test_generation_view_offers_the_whole_output_for_editing(client: TestClient, project: Path):
    form, _param, _patch = _form_parameter(project)
    html = _view(client, form)
    editor = html[html.index('id="structural-form"') :]
    assert f'hx-post="{PREVIEW}"' in editor
    assert f'name="output" value="{PAGE}"' in editor
    text = re.search(r'id="structural-text" name="text"[^>]*>\n(.*?)</textarea>', editor, re.S)
    assert text and unescape(text.group(1)) == _page(project)


def test_preview_of_a_removal_shows_the_patch_and_effects_and_writes_nothing(
    client: TestClient, project: Path, tmp_path: Path
):
    form, param, patch = _form_parameter(project)
    edited = _removed(project, patch)
    expected = structural.propose(
        generation.get_index(project), viewer_app.get_graph(), project, project / "chat-app.trig", PAGE, edited
    )
    generation._clear_cache()
    before = _snapshot(tmp_path)

    response = client.post(PREVIEW, data=_form(PAGE, edited, str(form)))

    assert response.status_code == 200
    assert _status(response.text) == "drafted"
    assert 'data-kind="remove"' in response.text
    assert f'data-parameter="{param}"' in response.text
    assert f'data-form="{form}"' in response.text
    signs = re.findall(r'class="quad" data-sign="([^"]+)"', response.text)
    assert signs == ["−"] * len(patch.removes)
    effects = re.findall(r'class="effect" data-output="([^"]+)" data-line="(\d+)"', response.text)
    assert effects == [(e.output, str(e.line)) for e in expected.effects]
    assert f'hx-post="{APPLY}"' in response.text
    assert _snapshot(tmp_path) == before


def test_apply_removes_the_parameter_and_regenerates_to_the_edit(client: TestClient, project: Path):
    trig = project / "chat-app.trig"
    form, param, patch = _form_parameter(project)
    edited = _removed(project, patch)

    # a browser posts a textarea with CRLF line ends
    response = client.post(APPLY, data=_form(PAGE, edited.replace("\n", "\r\n")))

    assert response.status_code == 200
    assert _status(response.text) == "applied"
    model = seams.load(trig)
    assert not list(model.ds.quads((param, None, None, None)))
    assert (form, HAS_PARAMETER, param) not in viewer_app.get_graph()
    assert len(viewer_app._undo_stack) == 1
    regenerated = generate_project(load_project(project), trig, lenient=True).files[project / PAGE].text
    want, got = edited.splitlines(), regenerated.splitlines()
    assert len(want) == len(got)
    new_hex = model.hash.removeprefix("sha256:")
    assert all(new_hex in g for w, g in zip(want, got, strict=True) if w != g)  # only the model-hash lines differ

    undone = client.post("/edit/undo")
    assert undone.json()["undone"] is True
    assert list(seams.load(trig).ds.quads((param, None, None, None)))


@pytest.mark.parametrize("route", [PREVIEW, APPLY])
def test_a_refusal_names_the_fact_and_writes_nothing(client: TestClient, project: Path, tmp_path: Path, route: str):
    before = _snapshot(tmp_path)

    response = client.post(route, data=_form(PAGE, _two_blocks(project)))

    assert response.status_code == 200
    assert _status(response.text) == "refused"
    assert '<code class="predicate">lines</code>' in response.text
    assert "changes 2" in unescape(response.text)
    assert "Apply to the model" not in response.text
    assert _snapshot(tmp_path) == before
    assert not viewer_app._undo_stack


def test_an_unknown_output_is_refused(client: TestClient):
    response = client.post(PREVIEW, data=_form("generated/templates/nothing.html", "x\n"))
    assert _status(response.text) == "refused"
    assert '<code class="predicate">output</code>' in response.text


@pytest.mark.parametrize("data", [{"text": "y"}, {"output": PAGE}, {}])
def test_malformed_forms_are_bad_requests(client: TestClient, data: dict[str, str]):
    for route in (PREVIEW, APPLY):
        assert client.post(route, data=data).status_code == 400
