"""Expense tutorial chapter 10: the expenses live in SemPKM (M024/S02, ADR-0025).

examples/expenses/chapter-10 is chapter 9 plus a deploy:SemPKM store, the
triplestore it arch:dependsOn, :expense_api's SEMPKM_URL (deploy:connectsTo)
and SEMPKM_TOKEN (deploy:authenticatesTo) bindings, and :ExpenseShape
seam:storedIn the store. These tests check that the checkpoint passes
``seams check`` and resolves to that store plan, and that the chapter's
committed route module stores and reads expenses through SemPKM. The SemPKM
is tests/test_runtime_sempkm_store.py's fake behind httpx.MockTransport, which
applies commands and answers SPARQL the way SemPKM's handlers do. The
relational half (process state, user tasks, approvals) runs on a temp SQLite
store injected in place of the declared PostgreSQL.
"""

import logging
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml
from rdflib import RDF, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402
from seams_cli.__main__ import main  # noqa: E402
from test_runtime_sempkm_store import DATA, TOKEN, URL, FakeSemPKM  # noqa: E402

from seams_runtime import ModelGraph, Runtime, SplitStore, SQLiteStore  # noqa: E402
from seams_runtime.host import build_app  # noqa: E402
from seams_runtime.model import DEPLOY  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-10"
TRIG = CHAPTER / "expenses.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
# 250.00 routes to the manager's approval task (approval_routing, chapter 5 on)
EXPENSE = {"description": "Train to Leeds", "amount": "250.00", "date": "2026-10-01"}
EMPLOYEE = {"X-Forwarded-User": "employee"}
MANAGER = {"X-Forwarded-User": "manager"}
ENV = ("SEMPKM_URL_FILE", "SEMPKM_TOKEN_FILE", "SEAMS_STORE_OVERRIDE", "SEAMS_DEV_USER", "SEAMS_SEED", "DATABASE_URL")


def test_the_checkpoint_passes_seams_check():
    assert main(["check", "--project", str(CHAPTER)]) == 0


def test_expenses_resolve_to_the_sempkm_store_and_the_rest_to_postgresql():
    plan = ModelGraph(TRIG).store_plan()
    assert (plan.kind, plan.store) == (DEPLOY.PostgreSQL, URIRef(EX + "expense_db"))
    assert plan.sempkm is not None
    assert plan.sempkm.store == URIRef(EX + "expense_pkm")
    assert plan.sempkm.container == URIRef(EX + "expense_api")
    assert (plan.sempkm.key, plan.sempkm.token_key) == ("SEMPKM_URL", "SEMPKM_TOKEN")
    assert plan.sempkm.shapes == (URIRef(EX + "ExpenseShape"),)


@pytest.mark.parametrize("environment", ["development", "production"])
def test_compose_runs_sempkm_and_its_triplestore_from_the_model(environment):
    compose = yaml.safe_load((CHAPTER / f"compose.{environment}.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert sorted(services) == ["employee_portal", "expense_api", "expense_db", "expense_pkm", "expense_triplestore"]
    pkm, triplestore, api = services["expense_pkm"], services["expense_triplestore"], services["expense_api"]
    assert pkm["image"] == "ghcr.io/metacoding-io/sempkm-api:1.0.0"
    assert pkm["depends_on"] == {"expense_triplestore": {"condition": "service_healthy"}}
    assert pkm["volumes"] == ["expense_pkm_data:/app/data"] and "/api/health" in " ".join(pkm["healthcheck"]["test"])
    assert triplestore["image"] == "eclipse/rdf4j-workbench:5.0.1"
    assert triplestore["volumes"] == ["expense_triplestore_data:/var/rdf4j"]
    # the API starts after both stores; the URL is an entry, the token a secret file
    assert set(api["depends_on"]) == {"expense_db", "expense_pkm"}
    assert api["environment"]["SEMPKM_TOKEN_FILE"] == "/run/secrets/sempkm_token"
    assert "SEMPKM_TOKEN" not in api["environment"] and "sempkm_token" in api["secrets"]
    secret = compose["secrets"]["sempkm_token"]
    if environment == "production":
        assert api["environment"]["SEMPKM_URL"] == "http://expense_pkm:8000"
        assert secret == {"name": "expenses-prod-sempkm-token", "external": True}
    else:
        assert api["environment"]["SEMPKM_URL"] == "${SEMPKM_URL:-http://expense_pkm:8000}"
        assert secret == {"file": "${SEMPKM_TOKEN_FILE:-../../../docker/local-secrets/expense_sempkm_token}"}


@pytest.fixture
def fake() -> FakeSemPKM:
    return FakeSemPKM()


@pytest.fixture
def served(fake, tmp_path, monkeypatch):
    """(TestClient, Runtime) for the chapter's committed route module, its
    SemPKM store on the fake and its relational store on temp SQLite."""
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SEAMS_MODEL", str(TRIG))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(CHAPTER / "generated" / "templates"))
    monkeypatch.setenv("SEMPKM_URL", URL)
    monkeypatch.setenv("SEMPKM_TOKEN", TOKEN)
    load = Runtime.load.__func__

    def load_on_fakes(cls, *args, **kw):
        kw.setdefault("store", SQLiteStore(tmp_path / "state.sqlite"))
        kw.setdefault("sempkm_transport", fake.transport)
        return load(cls, *args, **kw)

    monkeypatch.setattr(Runtime, "load", classmethod(load_on_fakes))
    app = build_app(CHAPTER / "generated" / "expense_api.py")
    with TestClient(app) as client:
        yield client, app.state.runtime


def _until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {predicate.__doc__}")


def _waiting(runtime, key="e1"):
    """the approval instance of ``key`` waits on a task"""
    rows = [r for r in runtime.store.list_instances(correlation_key=key) if r["process"] == EX + "approval_process"]
    return rows and rows[-1]["status"] == "waiting"


def test_a_submitted_expense_is_stored_and_read_through_sempkm(served, fake):
    client, runtime = served
    assert isinstance(runtime.store, SplitStore)
    r = client.post("/expenses/e1", data=EXPENSE, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    _until(lambda: _waiting(runtime))

    # The expense is one SemPKM object of the shape's target class, under a minted IRI.
    [iri] = list(fake.graph.subjects(RDF.type, URIRef(EX + "Expense")))
    assert str(iri).startswith(DATA + "Expense/")
    assert fake.graph.value(iri, URIRef(EX + "description")) == Literal("Train to Leeds")
    assert fake.graph.value(iri, URIRef(EX + "status")) == URIRef(EX + "s_submitted")
    # Only the expense went to SemPKM, in one request per write.
    sent = [c for batch in fake.posts("/api/commands") for c in batch]
    assert {c["params"].get("type") for c in sent if c["command"] == "object.create"} == {EX + "Expense"}

    # The relational store holds the index row, not the data.
    [row] = runtime.store.relational.query(URIRef(EX + "ExpenseShape"))
    assert (row["id"], row["data"], row["correlation_key"]) == (str(iri), {}, "e1")

    # The routes read it back through SPARQL.
    r = client.get("/expenses/e1")
    assert r.status_code == 200, r.text
    assert '<span class="description">Train to Leeds</span>' in r.text
    assert '<span class="description">Train to Leeds</span>' in client.get("/expenses").text
    assert fake.posts("/api/sparql")


def test_approving_patches_the_expense_in_sempkm_and_keeps_the_approval_relational(served, fake):
    client, runtime = served
    assert client.post("/expenses/e1", data=EXPENSE, headers=EMPLOYEE).status_code == 200
    _until(lambda: _waiting(runtime))
    [row] = client.get("/tasks", headers={**MANAGER, "Accept": "application/json"}).json()["tasks"]
    assert row["task"] == TASK and row["entity"]["description"] == "Train to Leeds"

    r = client.post("/expenses/e1/approval", data={"decision": "approved", "comment": "fine"}, headers=MANAGER)
    assert r.status_code == 200, r.text

    def approved():
        """the expense is approved in SemPKM"""
        [iri] = list(fake.graph.subjects(RDF.type, URIRef(EX + "Expense")))
        return fake.graph.value(iri, URIRef(EX + "status")) == URIRef(EX + "s_approved")

    _until(approved)
    assert not list(fake.graph.subjects(RDF.type, URIRef(EX + "Approval")))
    [approval] = runtime.store.relational.query(URIRef(EX + "ApprovalShape"))
    assert approval["data"]["decision"] == "approved"


def test_an_invalid_expense_is_refused_before_sempkm_is_called(served, fake):
    client, _ = served
    r = client.post("/expenses/e1", data={"amount": "250.00", "date": "2026-10-01"}, headers=EMPLOYEE)
    assert r.status_code == 422, r.text
    assert fake.posts("/api/commands") == []


def test_reading_while_sempkm_is_down_answers_503_naming_the_store(served, fake):
    client, _ = served
    fake.answer = lambda request: httpx.Response(503, text="down")
    r = client.get("/expenses")
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["store"] == EX + "expense_pkm"
    assert TOKEN not in r.text


def test_healthz_reports_the_sempkm_store_without_the_token(served, fake, caplog):
    client, _ = served
    with caplog.at_level(logging.DEBUG):
        r = client.get("/healthz")
    store = r.json()["store"]
    assert store["sempkm"] == {"kind": "SemPKM", "container": EX + "expense_pkm", "reachable": True, "override": False}
    fake.healthy = False
    assert client.get("/healthz").json()["store"]["sempkm"]["reachable"] is False
    assert TOKEN not in r.text and TOKEN not in caplog.text
