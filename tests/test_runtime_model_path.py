"""SEAMS_MODEL takes precedence over Runtime.load's trig_path (M009/S01)."""

import logging
import shutil
from pathlib import Path

import pytest

from seams_runtime import ModelHashMismatch, Runtime, model_hash
from seams_runtime.runtime import ALLOW_MISMATCH_ENV, MODEL_ENV

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "examples" / "chat-app"
TRIG = APP / "chat-app.trig"
PAYLOADS = ("chat_process.bpmn", "routing.dmn")


def _committed_hash() -> str:
    for line in (APP / "generated" / "chat_api.py").read_text().splitlines():
        if line.startswith("MODEL_HASH = "):
            return line.split('"')[1]
    raise AssertionError("no MODEL_HASH in chat_api.py")


def _copy_model(tmp_path: Path, extra: str = "") -> Path:
    other = tmp_path / "other"
    other.mkdir()
    target = other / "other.trig"
    target.write_text(TRIG.read_text() + extra)
    for name in PAYLOADS:
        shutil.copy(APP / name, other / name)
    return target


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_MISMATCH_ENV, raising=False)
    # the chat app declares PostgreSQL; these tests need only some store
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")


def test_unset_env_uses_argument(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
        runtime = Runtime.load(TRIG, model_hash=_committed_hash(), db_path=tmp_path / "db.sqlite")
    assert runtime.model.path == TRIG.resolve()
    assert "from argument" in caplog.text


def test_empty_env_uses_argument(tmp_path, monkeypatch):
    monkeypatch.setenv(MODEL_ENV, "")
    runtime = Runtime.load(TRIG, db_path=tmp_path / "db.sqlite")
    assert runtime.model.path == TRIG.resolve()


def test_env_overrides_argument(tmp_path, monkeypatch, caplog):
    copy = _copy_model(tmp_path)
    monkeypatch.setenv(MODEL_ENV, str(copy))
    with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
        runtime = Runtime.load("/model/chat-app.trig", model_hash=model_hash(copy), db_path=tmp_path / "db.sqlite")
    assert runtime.model.path == copy.resolve()
    assert f"model path {copy} from {MODEL_ENV}" in caplog.text


def test_env_model_with_other_hash_is_refused(tmp_path, monkeypatch):
    copy = _copy_model(tmp_path, extra='\n<urn:test:extra> <urn:test:p> "different" .\n')
    assert model_hash(copy) != _committed_hash()
    monkeypatch.setenv(MODEL_ENV, str(copy))
    with pytest.raises(ModelHashMismatch):
        Runtime.load("/model/chat-app.trig", model_hash=_committed_hash(), db_path=tmp_path / "db.sqlite")


def test_env_model_with_other_hash_allowed(tmp_path, monkeypatch):
    copy = _copy_model(tmp_path, extra='\n<urn:test:extra> <urn:test:p> "different" .\n')
    monkeypatch.setenv(MODEL_ENV, str(copy))
    monkeypatch.setenv(ALLOW_MISMATCH_ENV, "1")
    runtime = Runtime.load("/model/chat-app.trig", model_hash=_committed_hash(), db_path=tmp_path / "db.sqlite")
    assert runtime.model.path == copy.resolve()


def test_missing_env_model_names_path_and_var(tmp_path, monkeypatch):
    missing = tmp_path / "nowhere" / "absent.trig"
    monkeypatch.setenv(MODEL_ENV, str(missing))
    with pytest.raises(FileNotFoundError) as exc:
        Runtime.load(TRIG, db_path=tmp_path / "db.sqlite")
    assert str(missing) in str(exc.value)
    assert MODEL_ENV in str(exc.value)
    assert not (tmp_path / "db.sqlite").exists()


def test_missing_argument_model_names_path(tmp_path):
    missing = tmp_path / "absent.trig"
    with pytest.raises(FileNotFoundError) as exc:
        Runtime.load(missing, db_path=tmp_path / "db.sqlite")
    assert str(missing) in str(exc.value)
    assert MODEL_ENV not in str(exc.value)
