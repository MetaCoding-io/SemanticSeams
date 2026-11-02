"""Write-back routes in the generation view (backlog T4, M021/S01): viewer.app.

Each test copies the chat app, and the compose files it generates at the
repository root, into tmp_path with the same layout (as tests/test_viewer_writeback.py),
points the viewer at the copy with configure() and posts edited output lines to
/generation/writeback/preview and /apply. Line numbers are found by searching the
output text; the facts asserted are read from the copied model.
"""

import re
import shutil
import sys
from html import unescape
from pathlib import Path
from urllib.parse import quote

import pytest
import seams
from fastapi.testclient import TestClient
from rdflib import RDFS, Literal, URIRef
from seams_cli import generate_project, load_project

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import generation, validation  # noqa: E402

CHAT = ROOT / "examples" / "chat-app"
PAGE = "generated/templates/chat_page.html"
LIST = "generated/templates/conversation_list.html"
IFML_TITLE = URIRef("https://w3id.org/seams/ifml#title")
PREVIEW = "/generation/writeback/preview"
APPLY = "/generation/writeback/apply"


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


def _line(project: Path, output: str, needle: str) -> tuple[int, str]:
    lines = (project / output).read_text(encoding="utf-8").splitlines()
    found = [(n, t) for n, t in enumerate(lines, start=1) if needle in t]
    assert len(found) == 1, f"{needle!r} is on {len(found)} lines of {output}"
    return found[0]


def _title(project: Path, text: str) -> tuple[URIRef, Literal]:
    model = seams.load(project / "chat-app.trig")
    page, title = next((s, o) for s, o in model.ds.subject_objects(IFML_TITLE) if f">{o}<" in text)
    assert isinstance(page, URIRef) and isinstance(title, Literal)
    return page, title


def _form(output: str, line: int, text: str, iri: str = "") -> dict[str, str]:
    return {"output": output, "line": str(line), "text": text, "iri": iri}


def _status(html: str) -> str:
    match = re.search(r'id="writeback-result"\s+data-status="(\w+)"', html)
    assert match, html
    return match.group(1)


def test_writeback_routes_are_not_mounted_without_edit_mode(project: Path, monkeypatch):
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(project / "chat-app.trig")
    client = TestClient(viewer_app.app)
    line, text = _line(project, PAGE, "<title>")
    for route in (PREVIEW, APPLY):
        assert client.post(route, data=_form(PAGE, line, text + "x")).status_code in (404, 405)
    page, _title_value = _title(project, text)
    view = client.get(f"/generation/{quote(str(page), safe='')}?output={quote(PAGE, safe='')}&line={line}")
    assert view.status_code == 200
    assert 'id="writeback-form"' not in view.text


def test_generation_view_offers_the_selected_line_for_editing(client: TestClient, project: Path):
    line, text = _line(project, PAGE, "<title>")
    page, _title_value = _title(project, text)
    view = client.get(f"/generation/{quote(str(page), safe='')}?output={quote(PAGE, safe='')}&line={line}")
    assert view.status_code == 200
    form = view.text[view.text.index('id="writeback-form"') :]
    assert f'name="line" value="{line}"' in form
    assert f'name="output" value="{PAGE}"' in form
    value = re.search(r'id="writeback-text" name="text" value="([^"]*)"', form)
    assert value and unescape(value.group(1)) == text
    assert 'hx-post="/generation/writeback/preview"' in form


def test_preview_shows_the_patch_triple_and_writes_nothing(client: TestClient, project: Path, tmp_path: Path):
    before = _snapshot(tmp_path)
    line, text = _line(project, PAGE, "<title>")
    page, title = _title(project, text)

    response = client.post(PREVIEW, data=_form(PAGE, line, text.replace(f">{title}<", ">Inbox<")))

    assert response.status_code == 200
    assert _status(response.text) == "drafted"
    assert f'data-subject="{page}"' in response.text
    assert f'data-predicate="{IFML_TITLE}"' in response.text
    assert unescape(Literal("Inbox", lang=title.language).n3()) in unescape(response.text)
    assert "No other output line changes." in response.text
    assert 'hx-post="/generation/writeback/apply"' in response.text
    assert _snapshot(tmp_path) == before


def test_preview_lists_every_other_line_the_patch_changes(client: TestClient, project: Path):
    line, text = _line(project, PAGE, 'aria-label="Conversations"')
    list_line, _list_text = _line(project, LIST, 'aria-label="Conversations"')

    response = client.post(PREVIEW, data=_form(PAGE, line, text.replace('"Conversations"', '"Conversations list"')))

    assert _status(response.text) == "drafted"
    assert f'data-predicate="{RDFS.label}"' in response.text
    effects = re.findall(r'class="effect" data-output="([^"]+)" data-line="(\d+)"', response.text)
    assert effects == [(LIST, str(list_line))]


def test_preview_refusal_names_the_fact(client: TestClient, project: Path):
    line, text = _line(project, PAGE, "<title>")

    response = client.post(PREVIEW, data=_form(PAGE, line, text.replace("</title>", " & more</title>")))

    assert response.status_code == 200
    assert _status(response.text) == "refused"
    assert f'<code class="predicate">{IFML_TITLE}</code>' in response.text
    assert f"{PAGE} line {line}" in unescape(response.text)
    assert "Apply to the model" not in response.text


@pytest.mark.parametrize("data", [{"output": PAGE, "line": "x", "text": "y"}, {"line": "1", "text": "y"}, {}])
def test_malformed_forms_are_bad_requests(client: TestClient, data: dict[str, str]):
    for route in (PREVIEW, APPLY):
        assert client.post(route, data=data).status_code == 400


def test_apply_changes_the_label_and_regenerates_to_the_edit(client: TestClient, project: Path):
    trig = project / "chat-app.trig"
    line, text = _line(project, PAGE, "<title>")
    page, title = _title(project, text)
    edited = text.replace(f">{title}<", ">Inbox<")
    original = (project / PAGE).read_text(encoding="utf-8").splitlines()

    response = client.post(APPLY, data=_form(PAGE, line, edited))

    assert response.status_code == 200
    assert _status(response.text) == "applied"
    model = seams.load(trig)
    assert list(model.ds.objects(page, IFML_TITLE)) == [Literal("Inbox", lang=title.language)]
    assert viewer_app.get_graph().value(page, IFML_TITLE) == Literal("Inbox", lang=title.language)
    regenerated = generate_project(load_project(project), trig, lenient=True)
    lines = regenerated.files[project / PAGE].text.splitlines()
    expected = [edited if n == line else t for n, t in enumerate(original, start=1)]
    assert len(lines) == len(expected)
    differ = [(w, g) for w, g in zip(expected, lines, strict=True) if w != g]
    new_hex = model.hash.removeprefix("sha256:")
    assert all(new_hex in g for _w, g in differ)  # only the model-hash lines differ


def test_refused_apply_leaves_the_files_byte_identical(client: TestClient, project: Path, tmp_path: Path):
    before = _snapshot(tmp_path)
    line, text = _line(project, PAGE, "<title>")

    response = client.post(APPLY, data=_form(PAGE, line, text.replace("</title>", " & more</title>")))

    assert _status(response.text) == "refused"
    assert _snapshot(tmp_path) == before
    assert not viewer_app._undo_stack


def test_undo_restores_the_model_after_an_apply(client: TestClient, project: Path, tmp_path: Path):
    before = _snapshot(tmp_path)
    line, text = _line(project, PAGE, "<title>")
    _page, title = _title(project, text)

    applied = client.post(APPLY, data=_form(PAGE, line, text.replace(f">{title}<", ">Inbox<")))
    assert _status(applied.text) == "applied"
    assert _snapshot(tmp_path) != before

    undone = client.post("/edit/undo")
    assert undone.status_code == 200
    assert undone.json()["undone"] is True
    assert _snapshot(tmp_path) == before
