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

The chapter also writes the SemPKM Mental Model of its ontology (M024/S03,
ADR-0026) to generated/mental-model. The committed package must equal a fresh
render, and with SEAMS_E2E=1 the chapter's own compose stack installs it into
its SemPKM through ``POST /api/models/install``.

A change made in SemPKM starts a process (M024/S04, ADR-0027): the chapter's
:vendor_changes channel is a comm:SemPKMWebhook channel, and the
:vendor_review_process subscribes to it. Posting SemPKM's object.changed
delivery to the committed route starts the review for the changed vendor,
which the receiver reads back from the fake (its events are named graphs).
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml
from rdflib import RDF, Dataset, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402
from seams import Model  # noqa: E402
from seams_cli.__main__ import main  # noqa: E402
from test_runtime_sempkm_store import DATA, TOKEN, URL, FakeSemPKM  # noqa: E402

from seams_gen.mentalmodel import extract_mentalmodel, render_mentalmodel  # noqa: E402
from seams_runtime import ModelGraph, Runtime, SplitStore, SQLiteStore  # noqa: E402
from seams_runtime.host import build_app  # noqa: E402
from seams_runtime.model import DEPLOY  # noqa: E402
from seams_runtime.sempkm import EVENT_AFFECTED, EVENT_CLASS  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-10"
TRIG = CHAPTER / "expenses.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
# 250.00 routes to the manager's approval task (approval_routing, chapter 5 on)
EXPENSE = {"description": "Train to Leeds", "amount": "250.00", "date": "2026-10-01"}
EMPLOYEE = {"X-Forwarded-User": "employee"}
MANAGER = {"X-Forwarded-User": "manager"}
MENTAL_MODEL = CHAPTER / "generated" / "mental-model"
ENV = ("SEMPKM_URL_FILE", "SEMPKM_TOKEN_FILE", "SEAMS_STORE_OVERRIDE", "SEAMS_DEV_USER", "SEAMS_SEED", "DATABASE_URL")


def test_the_checkpoint_passes_seams_check():
    assert main(["check", "--project", str(CHAPTER)]) == 0


def test_expenses_and_vendors_resolve_to_the_sempkm_store_and_the_rest_to_postgresql():
    plan = ModelGraph(TRIG).store_plan()
    assert (plan.kind, plan.store) == (DEPLOY.PostgreSQL, URIRef(EX + "expense_db"))
    assert plan.sempkm is not None
    assert plan.sempkm.store == URIRef(EX + "expense_pkm")
    assert plan.sempkm.container == URIRef(EX + "expense_api")
    assert (plan.sempkm.key, plan.sempkm.token_key) == ("SEMPKM_URL", "SEMPKM_TOKEN")
    # expenses, and the vendors finance keeps in SemPKM (ADR-0027)
    assert plan.sempkm.shapes == (URIRef(EX + "ExpenseShape"), URIRef(EX + "VendorShape"))


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


class EventsSemPKM(FakeSemPKM):
    """The store fake plus SemPKM's event graphs: an all_graphs SPARQL query
    runs over them, as SemPKM's does for its owner-role service token."""

    def __init__(self):
        super().__init__()
        self.events = Dataset()

    def event(self, event: str, *affected: str) -> None:
        g = self.events.graph(URIRef(event))
        g.add((URIRef(event), RDF.type, EVENT_CLASS))
        for iri in affected:
            g.add((URIRef(event), EVENT_AFFECTED, URIRef(iri)))

    def handle(self, request: httpx.Request) -> httpx.Response:
        if (
            self.answer is None
            and request.url.path == "/api/sparql"
            and request.headers.get("authorization") == f"Bearer {TOKEN}"
            and json.loads(request.content).get("all_graphs")
        ):
            self.requests.append(request)
            result = self.events.query(json.loads(request.content)["query"])
            return httpx.Response(
                200, content=result.serialize(format="json"), headers={"content-type": "application/json"}
            )
        return super().handle(request)


@pytest.fixture
def fake() -> EventsSemPKM:
    return EventsSemPKM()


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


# ── a change in SemPKM starts a process (M024/S04, ADR-0027) ──

VENDOR_REVIEW = EX + "vendor_review_process"
EVENT = "urn:sempkm:event:5f0c2d7e-8a51-4c3b-9d7e-1a2b3c4d5e6f"


def _delivery(event: str = EVENT, event_type: str = "object.changed") -> bytes:
    """SemPKM's webhook body (ADR-0027 section 4)"""
    return json.dumps(
        {
            "event_type": event_type,
            "event_iri": event,
            "command": "object.patch",
            "timestamp": "2026-11-04T09:30:00+00:00",
        }
    ).encode()


def _vendor(fake: FakeSemPKM, name: str) -> str:
    """a vendor finance keeps in SemPKM: an object of the shape's target class"""
    iri = fake.mint("Vendor")
    fake.graph.add((URIRef(iri), RDF.type, URIRef(EX + "Vendor")))
    fake.graph.add((URIRef(iri), URIRef(EX + "name"), Literal(name)))
    return iri


def test_the_vendor_channel_resolves_to_the_review_process_and_the_api():
    graph = ModelGraph(TRIG)
    [channel] = graph.webhook_channels()
    assert channel.iri == URIRef(EX + "vendor_changes")
    assert (channel.event_name, channel.path) == ("object.changed", "/sempkm/vendor-changes")
    assert (channel.shape, channel.target_class) == (URIRef(EX + "VendorShape"), URIRef(EX + "Vendor"))
    assert (channel.store, channel.container) == (URIRef(EX + "expense_pkm"), URIRef(EX + "expense_api"))
    assert channel.processes == (URIRef(VENDOR_REVIEW),)


def test_a_vendor_changed_in_sempkm_starts_the_vendor_review(served, fake, caplog):
    client, runtime = served
    acme = _vendor(fake, "Acme Travel")
    fake.event(EVENT, acme)
    with caplog.at_level(logging.INFO):
        r = client.post("/sempkm/vendor-changes", content=_delivery(), headers={"content-type": "application/json"})
    assert r.status_code == 202, r.text
    answer = r.json()
    assert (answer["channel"], answer["event"], answer["skipped"]) == (EX + "vendor_changes", EVENT, [])
    [started] = answer["started"]
    assert (started["process"], started["object"]) == (VENDOR_REVIEW, acme)

    def reviewed():
        """the vendor review of the changed vendor completes"""
        rows = runtime.store.list_instances(correlation_key=acme)
        return rows and rows[-1]["status"] == "complete" and rows

    [row] = _until(reviewed)
    assert (row["instance_id"], row["process"]) == (started["instance"], VENDOR_REVIEW)
    # the receiver only read SemPKM: the event, then the vendor; it wrote nothing
    assert fake.posts("/api/commands") == []
    event_read, vendor_read = fake.posts("/api/sparql")
    assert event_read["all_graphs"] is True and f"<{EX}Vendor>" in vendor_read["query"]
    logged = " ".join(r.getMessage() for r in caplog.records if r.name == "seams_runtime.webhooks")
    for part in (EX + "vendor_changes", "object.changed", acme, started["instance"]):
        assert part in logged
    assert TOKEN not in caplog.text

    # the same delivery again starts nothing new (ADR-0027 section 5)
    again = client.post("/sempkm/vendor-changes", content=_delivery(), headers={"content-type": "application/json"})
    assert again.status_code == 202 and again.json()["started"] == answer["started"]
    assert len(runtime.store.list_instances(correlation_key=acme)) == 1


def test_the_apps_own_expense_write_starts_no_review(served, fake):
    """SemPKM sends object.changed for the runtime's own expense writes too;
    an expense is not a vendor, so it drops out (ADR-0027 section 7)."""
    client, runtime = served
    assert client.post("/expenses/e1", data=EXPENSE, headers=EMPLOYEE).status_code == 200
    _until(lambda: _waiting(runtime))
    [expense] = list(fake.graph.subjects(RDF.type, URIRef(EX + "Expense")))
    fake.event(EVENT, str(expense))
    r = client.post("/sempkm/vendor-changes", content=_delivery(), headers={"content-type": "application/json"})
    assert r.status_code == 202, r.text
    assert r.json()["started"] == [] and EX + "Vendor" in r.json()["ignored"]
    assert [row["process"] for row in runtime.store.list_instances()] == [EX + "approval_process"]


def test_a_forged_vendor_event_is_422_and_starts_nothing(served, fake):
    client, runtime = served
    _vendor(fake, "Acme Travel")
    r = client.post("/sempkm/vendor-changes", content=_delivery(), headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["store"] == EX + "expense_pkm"
    assert runtime.store.list_instances() == []


# ── the Mental Model (M024/S03, ADR-0026) ──


def test_the_committed_mental_model_is_a_fresh_render_of_the_model():
    fresh = render_mentalmodel(extract_mentalmodel(Model(TRIG)))
    committed = sorted(p.relative_to(MENTAL_MODEL).as_posix() for p in MENTAL_MODEL.rglob("*") if p.is_file())
    assert (
        sorted(fresh)
        == committed
        == [
            "manifest.yaml",
            "ontology/expense-ontology.jsonld",
            "shapes/expense-ontology.jsonld",
            "views/expense-ontology.jsonld",
        ]
    )
    for name, text in fresh.items():
        assert (MENTAL_MODEL / name).read_text(encoding="utf-8") == text, name


def test_seams_lock_records_the_mental_model_from_the_ontology():
    lock = json.loads((CHAPTER / "seams.lock").read_text(encoding="utf-8"))
    outputs = {o["path"]: o for o in lock["outputs"] if o["generator"] == "mentalmodel"}
    assert sorted(p for p in outputs if not p.endswith(".trace.json")) == [
        f"generated/mental-model/{name}"
        for name in ("manifest.yaml", *(f"{kind}/expense-ontology.jsonld" for kind in ("ontology", "shapes", "views")))
    ]
    assert EX + "expense_ontology" in outputs["generated/mental-model/manifest.yaml"]["sources"]


# With SEAMS_E2E=1 nothing skips: a missing docker CLI or a SemPKM that does not
# come up healthy is a failure. Only expense_pkm and its triplestore start; the
# package is copied into the container, because SemPKM installs a directory on
# its own filesystem. Install needs an owner session, which claiming the fresh
# instance with its setup token (data/.setup-token in the container) gives.
PROJECT = yaml.safe_load((CHAPTER / "compose.development.yaml").read_text(encoding="utf-8"))["name"]
IN_CONTAINER = "/tmp/mental-model"
INSTALL = """
import json, sys, urllib.error, urllib.request
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
def post(path, body):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        r = opener.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    return r.status, r.read().decode()
token = open("data/.setup-token").read().strip()
setup = post("/api/auth/setup", {"token": token})
install = post("/api/models/install", {"path": sys.argv[1]})
listed = opener.open("http://127.0.0.1:8000/api/models", timeout=30).read().decode()
print(json.dumps({"setup": setup, "install": install, "listed": listed}))
"""


def _compose(*args, timeout=120, check=True) -> subprocess.CompletedProcess:
    files = ["-f", str(CHAPTER / "compose.development.yaml")]
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT, *files, *args],
        cwd=ROOT,
        timeout=timeout,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(os.environ.get("SEAMS_E2E") != "1", reason="live docker compose test; set SEAMS_E2E=1")
def test_the_chapters_sempkm_installs_the_mental_model():
    if shutil.which("docker") is None:
        pytest.fail("SEAMS_E2E=1 but the docker CLI is not on PATH")
    try:
        up = _compose("up", "-d", "--wait", "expense_pkm", timeout=300, check=False)
        logs = _compose("logs", "--no-color", "expense_pkm", check=False).stdout
        assert up.returncode == 0, f"docker compose up failed:\n{up.stdout}\n{up.stderr}\n{logs}"
        _compose("cp", str(MENTAL_MODEL), f"expense_pkm:{IN_CONTAINER}")
        run = _compose("exec", "-T", "expense_pkm", "python", "-c", INSTALL, IN_CONTAINER, check=False)
        assert run.returncode == 0, f"{run.stdout}\n{run.stderr}"
        answer = json.loads(run.stdout.strip().splitlines()[-1])
        assert answer["setup"][0] == 200, answer["setup"]
        status, body = answer["install"]
        assert status == 201, body
        installed = json.loads(body)
        assert installed["model_id"] == "expense-ontology"
        # SemPKM warns that the package ships no README; ADR-0026 section 4 accepts that.
        assert all("documentation" in w for w in installed["warnings"]), installed["warnings"]
        models = json.loads(answer["listed"])["models"]
        assert [(m["model_id"], m["version"], m["name"]) for m in models if m["model_id"] == "expense-ontology"] == [
            ("expense-ontology", "1.1.0", "Expense Ontology")
        ]
    finally:
        _compose("down", "-v", "--remove-orphans", check=False, timeout=180)
