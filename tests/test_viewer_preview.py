"""The edit-mode live preview (backlog I3, M019/S05).

These tests copy the expense tutorial's chapter 3, with its generated outputs and
seams.lock, to tmp_path, load the copy in the viewer with edit mode on, and read
GET /edit/preview: the project's generators re-run in lenient mode, in memory. The
panel lists what they would write, flags lenient faults, and nothing on disk changes.

Outputs are compared with the committed generated files, not named.
"""

import logging
import re
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import preview, validation  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"
# Dropping the container's seam:exposes leaves no serving container, which the
# fastapi generator reports as a GeneratorError (lenient: a fault).
EXPOSES = re.compile(r"^\s*:\w+ seam:exposes [^\n]*\.\n", re.MULTILINE)


@pytest.fixture
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model, edit mode off, after the test."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(original)


@pytest.fixture
def app_dir(tmp_path) -> Path:
    return Path(shutil.copytree(CHAPTER, tmp_path / "chapter-03"))


@pytest.fixture
def client(app_dir, monkeypatch, restore_viewer) -> TestClient:
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(app_dir / "expenses.trig")
    return TestClient(viewer_app.app)


def _tree(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def _break(app_dir: Path) -> None:
    trig = app_dir / "expenses.trig"
    text, count = EXPOSES.subn("", trig.read_text(encoding="utf-8"))
    assert count == 1
    trig.write_text(text, encoding="utf-8")
    viewer_app.reload_model()


def test_preview_lists_the_outputs_the_project_commits(app_dir):
    facts = preview.preview(app_dir / "expenses.trig", app_dir)
    assert facts["error"] is None
    assert facts["faults"] == [] and facts["lenient"] is False
    assert facts["project"] == "chapter-03/seams.toml"
    committed = _tree(app_dir)
    assert {f["generator"] for f in facts["files"]} == {"fastapi", "htmx"}
    for f in facts["files"]:
        assert f["text"].encode("utf-8") == committed[f["path"]], f["path"]


def test_preview_panel_lists_the_htmx_page_output(client, app_dir):
    response = client.get("/edit/preview")
    assert response.status_code == 200
    html = response.text
    assert 'id="preview-panel"' in html and 'data-lenient="false"' in html
    assert "hx-swap-oob" not in html
    htmx = [f for f in preview.preview(app_dir / "expenses.trig", app_dir)["files"] if f["generator"] == "htmx"]
    assert htmx
    for f in htmx:
        assert f'data-path="{f["path"]}"' in html


def test_preview_writes_nothing(client, app_dir):
    before = _tree(app_dir)
    assert client.get("/edit/preview").status_code == 200
    _break(app_dir)
    after_break = _tree(app_dir)
    assert client.get("/edit/preview").status_code == 200
    assert _tree(app_dir) == after_break
    assert {k: v for k, v in after_break.items() if k != "expenses.trig"} == {
        k: v for k, v in before.items() if k != "expenses.trig"
    }


def test_a_broken_edit_gives_faults_and_flags_the_panel(client, app_dir):
    _break(app_dir)
    facts = preview.preview(app_dir / "expenses.trig", app_dir)
    assert facts["lenient"] is True
    assert [f["generator"] for f in facts["faults"]] == ["fastapi"]
    assert {"generator", "subject", "predicate", "detail"} == set(facts["faults"][0])
    assert all(f["generator"] == "htmx" for f in facts["files"])
    html = client.get("/edit/preview").text
    assert 'data-lenient="true"' in html
    assert "1 fault(s)" in html
    assert facts["faults"][0]["detail"] in html


def test_a_model_without_a_project_says_no_project(tmp_path, monkeypatch, restore_viewer):
    copy = tmp_path / "bare"
    copy.mkdir()
    shutil.copy(CHAPTER / "expenses.trig", copy / "expenses.trig")
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy / "expenses.trig")
    response = TestClient(viewer_app.app).get("/edit/preview")
    assert response.status_code == 200
    assert "no project" in response.text
    assert 'data-lenient="false"' in response.text
    assert list(copy.iterdir()) == [copy / "expenses.trig"]


def test_a_malformed_project_names_the_file(app_dir):
    (app_dir / "seams.toml").write_text("generators = 3\n", encoding="utf-8")
    facts = preview.preview(app_dir / "expenses.trig", app_dir)
    assert facts["files"] == [] and facts["project"] is None
    assert facts["error"].startswith("no project: ") and "seams.toml" in facts["error"]
    assert "`generators`" in facts["error"]


def test_the_route_is_absent_without_edit_mode(app_dir, monkeypatch, restore_viewer):
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(app_dir / "expenses.trig")
    assert TestClient(viewer_app.app).get("/edit/preview").status_code == 404


def test_the_preview_is_sorted_and_the_same_on_two_calls(client, app_dir):
    first = preview.preview(app_dir / "expenses.trig", app_dir)
    paths = [f["path"] for f in first["files"]]
    assert paths == sorted(paths)
    assert preview.preview(app_dir / "expenses.trig", app_dir) == first
    assert client.get("/edit/preview").text == client.get("/edit/preview").text


def test_oob_marks_the_panel_for_an_out_of_band_swap(client):
    html = client.get("/edit/preview", params={"oob": "true"}).text
    assert 'id="preview-panel"' in html and 'hx-swap-oob="true"' in html


def test_each_preview_is_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        client.get("/edit/preview")
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("preview ")]
    assert re.fullmatch(r"preview chapter-03/seams\.toml: \d+ output\(s\), 0 fault\(s\) in \d+\.\d\ds", line)
