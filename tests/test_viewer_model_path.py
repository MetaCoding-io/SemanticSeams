"""Tests for the viewer's configurable model (SEAMS_MODEL) and its derived
root IRI (the model's single C4 seam:Model, or SEAMS_VIEWER_ROOT).
"""

import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

CHAT_APP = ROOT / "examples" / "chat-app"
CHAT_ARCHITECTURE = "https://example.org/chat/chat_architecture"
CHAT_BPMN = "https://example.org/chat/chat_bpmn"
CHAT_IFML = "https://example.org/chat/chat_ifml"


@pytest.fixture(autouse=True)
def restore_viewer(monkeypatch):
    """Each test starts and ends on the default model with empty caches."""
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    viewer_app.configure(original)
    validation._clear_cache()


def copy_model(dest: Path, extra: str = "") -> Path:
    dest.mkdir(parents=True)
    trig = dest / "other.trig"
    trig.write_text((CHAT_APP / "chat-app.trig").read_text() + extra)
    for name in ("chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_APP / name, dest / name)
    return trig


def payload_url(iri: str) -> str:
    return f"/payload/{quote(iri, safe='')}"


def test_default_model_and_root():
    assert viewer_app.model_path_from_env() == viewer_app.DEFAULT_MODEL_PATH
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    assert viewer_app.root_iri() == CHAT_ARCHITECTURE
    resp = TestClient(viewer_app.app).get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == f"/view/{quote(CHAT_ARCHITECTURE, safe='')}"


def test_empty_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv(viewer_app.MODEL_ENV, "")
    assert viewer_app.model_path_from_env() == viewer_app.DEFAULT_MODEL_PATH


def test_seams_model_loads_a_copied_model(monkeypatch, tmp_path):
    trig = copy_model(tmp_path / "other_app")
    monkeypatch.setenv(viewer_app.MODEL_ENV, str(trig))
    viewer_app.configure(viewer_app.model_path_from_env())
    assert viewer_app.MODEL_PATH == trig.resolve()
    assert viewer_app.MODEL_DIR == trig.parent.resolve()

    client = TestClient(viewer_app.app)
    payload_iri = viewer_app.render_payload_of(CHAT_BPMN)
    assert payload_iri == (trig.parent / "chat_process.bpmn").resolve().as_uri()
    resp = client.get(payload_url(payload_iri))
    assert resp.status_code == 200
    assert resp.content == (trig.parent / "chat_process.bpmn").read_bytes()

    readme = (ROOT / "README.md").resolve().as_uri()
    assert client.get(payload_url(readme)).status_code == 404
    # The chat app's own payload is outside the new model's directory too.
    original = (CHAT_APP / "chat_process.bpmn").resolve().as_uri()
    assert client.get(payload_url(original)).status_code == 404

    resp = client.get("/", follow_redirects=False)
    assert resp.headers["location"] == f"/view/{quote(CHAT_ARCHITECTURE, safe='')}"
    assert client.get(f"/view/{quote(CHAT_ARCHITECTURE, safe='')}").status_code == 200


def test_missing_seams_model_names_path_and_env(monkeypatch, tmp_path):
    missing = tmp_path / "nope.trig"
    monkeypatch.setenv(viewer_app.MODEL_ENV, str(missing))
    viewer_app.configure(viewer_app.model_path_from_env())
    with pytest.raises(FileNotFoundError) as exc:
        viewer_app.get_graph()
    assert str(missing) in str(exc.value)
    assert viewer_app.MODEL_ENV in str(exc.value)


def test_seams_viewer_root_overrides_derived_root(monkeypatch):
    monkeypatch.setenv(viewer_app.ROOT_ENV, CHAT_IFML)
    viewer_app.configure(viewer_app.DEFAULT_MODEL_PATH)
    assert viewer_app.root_iri() == CHAT_IFML
    resp = TestClient(viewer_app.app).get("/", follow_redirects=False)
    assert resp.headers["location"] == f"/view/{quote(CHAT_IFML, safe='')}"


def test_two_c4_models_is_an_error_naming_both(tmp_path):
    second = "https://example.org/chat/second_architecture"
    trig = copy_model(
        tmp_path / "two_c4",
        "\n<https://example.org/chat/g_second> {\n"
        f"    <{second}> a <https://w3id.org/seams/seam#Model> ;\n"
        "        <https://w3id.org/seams/seam#notation> <https://w3id.org/seams/seam#C4> .\n"
        "}\n",
    )
    viewer_app.configure(trig)
    with pytest.raises(RuntimeError) as exc:
        viewer_app.root_iri()
    message = str(exc.value)
    assert CHAT_ARCHITECTURE in message
    assert second in message
    assert viewer_app.ROOT_ENV in message


def test_no_c4_model_is_an_error(tmp_path):
    trig = tmp_path / "empty.trig"
    trig.write_text("<https://example.org/x> <https://example.org/p> <https://example.org/y> .\n")
    viewer_app.configure(trig)
    with pytest.raises(RuntimeError, match="found: none"):
        viewer_app.root_iri()
