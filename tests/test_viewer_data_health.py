"""The viewer's data-health view (ADR-0036, M029/S05/T04).

GET /data-health runs the attached profile's instance-data rules, through
seams_runtime's public data_health, on the SQLite store named by
SEAMS_VIEWER_STORE, opened read-only. The fixture store holds two payments of
one expense of chapter 11, written with SQLiteStore in tmp_path, so the DDD
profile's paid-once rule gives one warning. The rule's message is read from
data_health, never repeated here. Validation is cached by id(ds), so the cache
is cleared around every test (MEM010).
"""

import html
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import ModelGraph, SQLiteStore, StoreUnavailable, data_health  # noqa: E402
from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"
CHAT_APP = ROOT / "examples" / "chat-app" / "chat-app.trig"
PAYMENT_SHAPE = "https://example.org/expenses/PaymentShape"
HX = {"hx-request": "true"}


@pytest.fixture(autouse=True)
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model after the test, with no store set."""
    original = viewer_app.MODEL_PATH
    monkeypatch.delenv(viewer_app.STORE_ENV, raising=False)
    validation._clear_cache()
    yield
    viewer_app.configure(original)


def _payment(store: SQLiteStore, id: str, expense: str, reference: str) -> None:
    data = {"reference": reference, "paid_on": "2026-10-05", "expense": expense}
    store.put_entity(id, PAYMENT_SHAPE, data, correlation_key=expense)


@pytest.fixture
def two_payments(tmp_path) -> Path:
    """A chapter-11 store where expense e1 is paid twice and e2 once."""
    path = tmp_path / "seams.sqlite"
    store = SQLiteStore(path)
    _payment(store, "p1", "e1", "PAY-1")
    _payment(store, "p2", "e1", "PAY-2")
    _payment(store, "p3", "e2", "PAY-3")
    return path


def open_viewer(model: Path, monkeypatch, store: Path | None = None) -> TestClient:
    if store is not None:
        monkeypatch.setenv(viewer_app.STORE_ENV, str(store))
    viewer_app.configure(model)
    return TestClient(viewer_app.app)


def expected(store: Path):
    """The findings seams_runtime's own data_health gives for the store."""
    profile = viewer_app.get_profile()
    assert profile is not None
    return data_health(ModelGraph(CHAPTER), SQLiteStore(store, read_only=True), profile.shapes)


def test_the_view_lists_the_paid_twice_warning(two_payments, monkeypatch):
    client = open_viewer(CHAPTER, monkeypatch, two_payments)
    r = client.get("/data-health")
    assert r.status_code == 200
    [finding] = expected(two_payments)
    assert finding.severity == "Warning" and "e1" in finding.message and "e2" not in finding.message
    page = r.text
    # the full page keeps the shell: the header and the model health panel
    assert '<header><a class="header-home"' in page and "health-panel" in page
    assert 'data-state="ok"' in page
    assert html.escape(finding.message) in page
    assert f'<tr data-shape="{finding.shape}">' in page
    assert page.count("<tr data-shape=") == 1
    assert "1 warning<" in page


def test_the_json_matches_the_runtime_findings_and_is_sorted(tmp_path, two_payments, monkeypatch):
    store = SQLiteStore(two_payments)
    _payment(store, "p4", "e2", "PAY-4")
    client = open_viewer(CHAPTER, monkeypatch, two_payments)
    body = client.get("/data-health", params={"format": "json"}).json()
    findings = expected(two_payments)
    assert len(findings) == 2
    assert body["state"] == "ok" and body["count"] == 2
    assert body["store"] == str(two_payments.resolve())
    assert body["findings"] == [
        {"shape": f.shape, "focus": f.focus, "message": f.message, "severity": f.severity} for f in sorted(findings)
    ]
    assert [f["message"] for f in body["findings"]] == sorted(f["message"] for f in body["findings"])


def test_an_htmx_request_gets_the_fragment_alone(two_payments, monkeypatch):
    client = open_viewer(CHAPTER, monkeypatch, two_payments)
    r = client.get("/data-health", headers=HX)
    assert r.status_code == 200
    [finding] = expected(two_payments)
    assert '<section class="data-health" id="data-health" data-state="ok">' in r.text
    assert html.escape(finding.message) in r.text
    assert "<header>" not in r.text and "<html" not in r.text and "health-panel" not in r.text


def test_no_store_configured_is_an_empty_state(monkeypatch):
    client = open_viewer(CHAPTER, monkeypatch)
    for headers in ({}, HX):
        r = client.get("/data-health", headers=headers)
        assert r.status_code == 200
        assert 'data-state="no-store"' in r.text
        assert "No store configured" in r.text and viewer_app.STORE_ENV in r.text
        assert "<tr data-shape=" not in r.text
    assert client.get("/data-health", params={"format": "json"}).json()["findings"] == []


def test_a_store_that_breaks_no_rule_has_no_warnings(tmp_path, monkeypatch):
    path = tmp_path / "seams.sqlite"
    _payment(SQLiteStore(path), "p1", "e1", "PAY-1")
    client = open_viewer(CHAPTER, monkeypatch, path)
    r = client.get("/data-health", headers=HX)
    assert 'data-state="ok"' in r.text and "No warnings" in r.text
    assert "<tr data-shape=" not in r.text


def test_a_model_without_a_profile_has_no_rules(two_payments, monkeypatch):
    client = open_viewer(CHAT_APP, monkeypatch, two_payments)
    body = client.get("/data-health", params={"format": "json"}).json()
    assert body["state"] == "no-profile" and body["findings"] == []
    assert "attaches no profile" in client.get("/data-health", headers=HX).text


def test_a_missing_store_file_is_an_error_and_is_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "absent.sqlite"
    client = open_viewer(CHAPTER, monkeypatch, missing)
    r = client.get("/data-health", headers=HX)
    assert r.status_code == 200
    assert 'data-state="error"' in r.text and "no SQLite file" in r.text
    assert not missing.exists()


def test_a_sqlite_file_that_is_no_seams_store_is_an_error(tmp_path, monkeypatch):
    other = tmp_path / "other.sqlite"
    with sqlite3.connect(other) as con:
        con.execute("CREATE TABLE notes(id TEXT)")
    client = open_viewer(CHAPTER, monkeypatch, other)
    body = client.get("/data-health", params={"format": "json"}).json()
    assert body["state"] == "error" and "no entities table" in body["error"]
    with sqlite3.connect(other) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"notes"}


def test_a_stored_entity_its_contract_refuses_is_an_error(tmp_path, monkeypatch):
    path = tmp_path / "seams.sqlite"
    SQLiteStore(path).put_entity("p1", PAYMENT_SHAPE, {"reference": "PAY-1", "paid_on": "not a date", "expense": "e1"})
    client = open_viewer(CHAPTER, monkeypatch, path)
    body = client.get("/data-health", params={"format": "json"}).json()
    assert body["state"] == "error" and body["error"] and body["findings"] == []


def test_the_view_writes_nothing_to_the_store(two_payments, monkeypatch):
    before = two_payments.read_bytes()
    client = open_viewer(CHAPTER, monkeypatch, two_payments)
    assert client.get("/data-health").status_code == 200
    assert two_payments.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        _payment(SQLiteStore(two_payments, read_only=True), "p9", "e9", "PAY-9")


def test_a_read_only_store_needs_an_existing_file(tmp_path):
    with pytest.raises(StoreUnavailable):
        SQLiteStore(tmp_path / "absent.sqlite", read_only=True)
    assert not (tmp_path / "absent.sqlite").exists()
