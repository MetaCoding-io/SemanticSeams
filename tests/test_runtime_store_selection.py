"""Runtime.load opens the store the model declares (M011/S03, ADR-0011).

The chat app declares PostgreSQL behind chat_api's DB_URL binding; expenses
chapter 07 declares no store, so it gets embedded SQLite at SEAMS_DB. The
PostgresStore the runtime would open is replaced by a recorder, except in the
tests that need SEAMS_TEST_POSTGRES_URL (skipped without it, see conftest).
"""

import logging
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seams_runtime import ResolutionError, Runtime, SQLiteStore
from seams_runtime import runtime as runtime_module
from seams_runtime.host import build_app
from seams_runtime.model import DEPLOY
from seams_runtime.store import redact
from tests.conftest import postgres_url

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "examples" / "chat-app" / "chat-app.trig"
CH07 = ROOT / "examples" / "expenses" / "chapter-07" / "expenses.trig"
C = "https://example.org/chat/"

ENV = ("DB_URL", "DB_URL_FILE", "SEAMS_DB", "SEAMS_STORE_OVERRIDE", "SEAMS_MODEL")


class RecordingPostgresStore:
    """Stands in for PostgresStore: records the URL, connects to nothing."""

    kind = "postgresql"
    urls: list[str] = []

    def __init__(self, url: str):
        self.url = url
        self.location = redact(url)
        RecordingPostgresStore.urls.append(url)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def recorder(monkeypatch):
    RecordingPostgresStore.urls = []
    monkeypatch.setattr(runtime_module, "PostgresStore", RecordingPostgresStore)
    return RecordingPostgresStore


# ── declared PostgreSQL ──────────────────────────────────────────────────────


def test_postgres_without_a_connection_string_fails_naming_both_variables(recorder):
    with pytest.raises(ResolutionError) as info:
        Runtime.load(CHAT)
    err = info.value
    assert err.subject == C + "chat_api"
    assert err.predicate == str(DEPLOY.connectsTo)
    assert "DB_URL" in err.detail and "DB_URL_FILE" in err.detail
    assert recorder.urls == []


def test_db_url_names_the_postgres_store(recorder, monkeypatch, caplog):
    monkeypatch.setenv("DB_URL", "postgresql://seams:s3cret@db:5432/chat")
    with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
        rt = Runtime.load(CHAT)
    assert recorder.urls == ["postgresql://seams:s3cret@db:5432/chat"]
    assert rt.store.kind == "postgresql" and rt.store_override is False
    assert str(rt.store_plan.store) == C + "message_db" and rt.store_plan.key == "DB_URL"
    assert "postgresql://seams:***@db:5432/chat" in caplog.text
    assert "s3cret" not in caplog.text


def test_db_url_file_is_read_and_stripped(recorder, monkeypatch, tmp_path):
    secret = tmp_path / "db_url"
    secret.write_text("postgresql://seams:pw@db/chat\n")
    monkeypatch.setenv("DB_URL_FILE", str(secret))
    rt = Runtime.load(CHAT)
    assert recorder.urls == ["postgresql://seams:pw@db/chat"]
    assert rt.store.kind == "postgresql"


def test_db_url_wins_over_db_url_file(recorder, monkeypatch, tmp_path):
    secret = tmp_path / "db_url"
    secret.write_text("postgresql://from-file/chat")
    monkeypatch.setenv("DB_URL_FILE", str(secret))
    monkeypatch.setenv("DB_URL", "postgresql://from-env/chat")
    Runtime.load(CHAT)
    assert recorder.urls == ["postgresql://from-env/chat"]


def test_a_missing_db_url_file_fails_at_load(recorder, monkeypatch, tmp_path):
    monkeypatch.setenv("DB_URL_FILE", str(tmp_path / "absent"))
    with pytest.raises(FileNotFoundError):
        Runtime.load(CHAT)


# ── undeclared and overridden ────────────────────────────────────────────────


def test_an_undeclared_model_gets_sqlite_at_seams_db(recorder, monkeypatch, tmp_path):
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "env.sqlite"))
    rt = Runtime.load(CH07)
    assert isinstance(rt.store, SQLiteStore)
    assert rt.store.path == tmp_path / "env.sqlite"
    assert rt.store_plan.declared is False and rt.store_override is False
    assert recorder.urls == []


def test_the_override_gives_sqlite_and_warns(recorder, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    with caplog.at_level(logging.WARNING, logger="seams_runtime.runtime"):
        rt = Runtime.load(CHAT, db_path=tmp_path / "o.sqlite")
    assert isinstance(rt.store, SQLiteStore) and rt.store.path == tmp_path / "o.sqlite"
    assert rt.store_override is True
    assert recorder.urls == []
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "SEAMS_STORE_OVERRIDE" in warning.getMessage() and C + "message_db" in warning.getMessage()


def test_an_unknown_override_is_refused(recorder, monkeypatch):
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "mongodb")
    with pytest.raises(ValueError, match="SEAMS_STORE_OVERRIDE"):
        Runtime.load(CHAT)


def test_an_injected_store_is_used_and_a_kind_mismatch_warns(recorder, tmp_path, caplog):
    store = SQLiteStore(tmp_path / "injected.sqlite")
    with caplog.at_level(logging.WARNING, logger="seams_runtime.runtime"):
        rt = Runtime.load(CHAT, store=store)
    assert rt.store is store and rt.store_override is True
    assert "injected sqlite store" in caplog.text
    assert recorder.urls == []


def test_an_injected_store_of_the_declared_kind_does_not_warn(recorder, tmp_path, caplog):
    store = SQLiteStore(tmp_path / "injected.sqlite")
    with caplog.at_level(logging.WARNING, logger="seams_runtime.runtime"):
        rt = Runtime.load(CH07, store=store)
    assert rt.store is store and rt.store_override is False
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    "inject",
    [None, "override", "store"],
    ids=["plain", "override", "injected"],
)
def test_an_unsupported_store_kind_fails_at_load(recorder, monkeypatch, tmp_path, inject):
    bad = tmp_path / "bad.trig"
    text = CHAT.read_text()
    assert "deploy:storeKind deploy:PostgreSQL" in text
    bad.write_text(text.replace("deploy:storeKind deploy:PostgreSQL", "deploy:storeKind deploy:MongoDB"))
    monkeypatch.setenv("DB_URL", "postgresql://db/chat")
    kw = {}
    if inject == "override":
        monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    elif inject == "store":
        kw["store"] = SQLiteStore(tmp_path / "s.sqlite")
    with pytest.raises(ResolutionError) as info:
        Runtime.load(bad, **kw)
    assert info.value.subject == C + "message_db"
    assert info.value.predicate == str(DEPLOY.storeKind)
    assert recorder.urls == []


# ── /healthz ─────────────────────────────────────────────────────────────────


ROUTES = """\
from fastapi import APIRouter

from seams_runtime import Runtime

runtime = Runtime.load({trig!r}, db_path={db!r})
router = APIRouter()
"""


def _app(tmp_path, trig):
    routes = tmp_path / "routes.py"
    routes.write_text(ROUTES.format(trig=str(trig), db=str(tmp_path / "h.sqlite")))
    return build_app(routes)


def test_healthz_reports_the_overridden_store(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    with TestClient(_app(tmp_path, CHAT)) as c:
        body = c.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["store"] == {
        "kind": "sqlite",
        "declared": "PostgreSQL",
        "container": C + "message_db",
        "override": True,
    }


def test_healthz_reports_the_undeclared_default(tmp_path):
    with TestClient(_app(tmp_path, CH07)) as c:
        body = c.get("/healthz").json()
    assert body["store"] == {"kind": "sqlite", "declared": None, "container": None, "override": False}


def test_healthz_reports_the_declared_postgres_store(recorder, monkeypatch, tmp_path):
    monkeypatch.setenv("DB_URL", "postgresql://seams:pw@db/chat")
    with TestClient(_app(tmp_path, CHAT)) as c:
        body = c.get("/healthz").json()
    assert body["store"] == {
        "kind": "postgresql",
        "declared": "PostgreSQL",
        "container": C + "message_db",
        "override": False,
    }
    assert "pw" not in str(body)


# ── a real PostgreSQL (SEAMS_TEST_POSTGRES_URL) ─────────────────────────────


@pytest.fixture
def postgres_schema():
    """A fresh schema on the test database and a URL whose search_path is it."""
    import psycopg
    from psycopg import sql

    url = postgres_url()
    schema = f"seams_select_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as con:
        con.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    sep = "&" if "?" in url else "?"
    yield url, schema, f"{url}{sep}options=-csearch_path%3D{schema}"
    with psycopg.connect(url, autocommit=True) as con:
        con.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def test_db_url_opens_postgres_and_a_write_lands_there(postgres_schema, monkeypatch):
    import psycopg
    from psycopg import sql

    url, schema, scoped = postgres_schema
    monkeypatch.setenv("DB_URL", scoped)
    rt = Runtime.load(CHAT)
    assert rt.store.kind == "postgresql"
    entity = rt.write(":ConversationShape", {"id": "ignored", "title": "Into postgres"})
    with psycopg.connect(url) as con:
        rows = con.execute(sql.SQL("SELECT id, data FROM {}.entities").format(sql.Identifier(schema))).fetchall()
    assert [(row[0], row[1]["title"]) for row in rows] == [(entity["id"], "Into postgres")]
