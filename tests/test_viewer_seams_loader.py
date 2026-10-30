"""The viewer loads its model through seams.load (M010/S06): ModelStore is
gone, get_graph() is the seams Model's Dataset, and SEAMS_MODEL may name a
directory of TriG files as well as a single file.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import seams  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

CHAPTER_08 = ROOT / "examples" / "expenses" / "chapter-08"


@pytest.fixture(autouse=True)
def restore_viewer(monkeypatch):
    """Each test starts and ends on the default model with empty caches."""
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    validation._clear_cache()
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    yield
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    validation._clear_cache()


def test_model_store_is_gone():
    assert not hasattr(viewer_app, "ModelStore")
    assert not hasattr(viewer_app, "_store")


def test_get_graph_is_the_seams_model_dataset():
    model = viewer_app.get_model()
    assert isinstance(model, seams.Model)
    assert model.path == viewer_app.DEFAULT_MODEL_PATH.resolve()
    assert viewer_app.get_graph() is model.ds
    assert viewer_app.get_model() is model


def test_directory_model_loads_and_serves_its_root():
    viewer_app.configure(CHAPTER_08)
    model = viewer_app.get_model()
    assert model.is_directory
    assert viewer_app.MODEL_DIR == CHAPTER_08.resolve()
    root = viewer_app.root_iri()
    client = TestClient(viewer_app.app)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == f"/view/{quote(root, safe='')}"
    assert client.get(resp.headers["location"]).status_code == 200


def test_file_model_base_dir_is_its_parent():
    viewer_app.configure(CHAPTER_08 / "expenses.trig")
    assert viewer_app.MODEL_DIR == CHAPTER_08.resolve()
    assert not viewer_app.get_model().is_directory


def test_configure_clears_the_conformance_cache():
    validation._cache[0] = {"conforms": True}
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    assert validation._cache == {}


def test_configure_drops_the_loaded_model():
    first = viewer_app.get_model()
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    assert viewer_app.get_model() is not first


def test_missing_directory_names_path(tmp_path):
    missing = tmp_path / "no-such-dir"
    viewer_app.configure(missing)
    with pytest.raises(FileNotFoundError, match="viewer model not found"):
        viewer_app.get_model()


def test_empty_directory_is_an_error(tmp_path):
    viewer_app.configure(tmp_path)
    with pytest.raises(FileNotFoundError, match=r"no \*\.trig files"):
        viewer_app.get_model()
