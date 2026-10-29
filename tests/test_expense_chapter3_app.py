"""Expense tutorial chapter 3 checkpoint: the screens (docs/tutorials/expenses/).

examples/expenses/chapter-03/generated/ is committed so the reader can compare
their own output. The drift tests regenerate both generators into tmp_path and
compare file sets and bytes with the committed copy (helpers shared with
tests/test_generated_outputs_current.py). The app tests serve the committed
route module with seams_runtime.host in process, pointed at the chapter 3 model
and templates by SEAMS_MODEL / SEAMS_TEMPLATES and at a temp store by SEAMS_DB:
the form page renders, invalid input is a 422 naming the violated paths and
stores nothing, and valid input is stored and listed.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from expense_app import commands  # noqa: E402
from seams_runtime.host import build_app  # noqa: E402
from test_generated_outputs_current import (  # noqa: E402
    HAND_WRITTEN,
    assert_current,
    committed_files,
    regenerate,
)

CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"
TRIG = CHAPTER / "expenses.trig"
GENERATED = CHAPTER / "generated"
TEMPLATES = GENERATED / "templates"
ROUTES = GENERATED / "expense_api.py"

COMMANDS = commands("chapter-03")

VALID = {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"}


# ── drift ────────────────────────────────────────────────────────────────────


def test_route_module_is_current(tmp_path):
    assert_current(regenerate("fastapi", TRIG, tmp_path), committed_files(GENERATED, HAND_WRITTEN),
                   GENERATED, COMMANDS["fastapi"])


def test_templates_are_current(tmp_path):
    assert_current(regenerate("htmx", TRIG, tmp_path), committed_files(TEMPLATES),
                   TEMPLATES, COMMANDS["htmx"])


def test_generated_readme_names_the_regenerate_commands():
    readme = (GENERATED / "README.md").read_text(encoding="utf-8")
    assert "Do not edit" in readme
    for command in COMMANDS.values():
        assert command in readme


def test_seed_is_empty():
    assert (CHAPTER / "seed.json").read_text(encoding="utf-8").strip() == "{}"


# ── the app, in process ──────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", str(TRIG))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(TEMPLATES))
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "seams.sqlite"))
    monkeypatch.setenv("SEAMS_SEED", str(CHAPTER / "seed.json"))
    app = build_app(ROUTES)
    with TestClient(app) as c:
        yield c, app.state.runtime


def test_landmark_page_has_the_form(client):
    c, _runtime = client
    r = c.get("/")
    assert r.status_code == 200, r.text
    assert r.text.lstrip().startswith("<!doctype html>")
    assert '<form id="expense_form"' in r.text and 'hx-post="/expenses"' in r.text
    for name in ("description", "amount", "date"):
        assert f'name="{name}"' in r.text
    assert 'name="id"' not in r.text  # the runtime assigns it
    assert '<li class="expense">' not in r.text


@pytest.mark.parametrize("data, paths", [
    ({**VALID, "description": ""}, ["description"]),
    ({**VALID, "amount": "-5"}, ["amount"]),
    ({**VALID, "description": "", "amount": "-5"}, ["amount", "description"]),
    ({**VALID, "amount": "0"}, ["amount"]),
    ({**VALID, "date": "yesterday"}, ["date"]),
    ({**VALID, "amount": "lots"}, ["amount"]),
    ({**VALID, "approved": "yes"}, ["approved"]),
], ids=["empty-description", "negative-amount", "both", "zero-amount", "bad-date", "bad-amount",
        "unknown-field"])
def test_invalid_input_is_rejected_naming_the_path(client, data, paths):
    c, runtime = client
    r = c.post("/expenses", data=data)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation"
    assert detail["shape"] == "https://example.org/expenses/ExpenseShape"
    assert sorted(res["path"] for res in detail["results"]) == paths
    assert runtime.query(":ExpenseShape") == []


def test_valid_input_is_stored_and_listed(client):
    c, runtime = client
    r = c.post("/expenses", data=VALID)
    assert r.status_code == 200, r.text
    assert r.text.strip().startswith('<li class="expense">')
    assert '<span class="description">Train to Leeds</span>' in r.text
    assert '<span class="amount">42.50</span>' in r.text
    (stored,) = runtime.query(":ExpenseShape")
    assert stored["data"]["id"] == stored["id"]
    assert f'<span class="id">{stored["id"]}</span>' in r.text

    r = c.get("/expenses")
    assert r.status_code == 200, r.text
    assert '<span class="description">Train to Leeds</span>' in r.text
    r = c.get("/")
    assert '<span class="description">Train to Leeds</span>' in r.text


def test_each_submission_is_a_new_expense(client):
    c, runtime = client
    for _ in range(2):
        assert c.post("/expenses", data=VALID).status_code == 200
    ids = [e["id"] for e in runtime.query(":ExpenseShape")]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert c.get("/expenses").text.count('<li class="expense">') == 2
