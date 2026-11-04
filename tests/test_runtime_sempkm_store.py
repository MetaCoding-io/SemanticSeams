"""The SemPKM entity store (M024/S02, ADR-0025 sections 3-7 and 11).

``SemPKMStore`` sends the commands of one entity in one ``POST /api/commands``
request and reads entities back with ``POST /api/sparql``; ``SplitStore``
keeps process state, user tasks and each entity's index row (correlation key,
instance, status) in the relational store. The SemPKM here is a fake behind
``httpx.MockTransport`` that applies commands the way SemPKM's handlers do
(minted IRIs, JSON values typed by their JSON type, edges as resources with
source, predicate and target, one commit per request) and answers SPARQL by
running the query with rdflib, so the query text the store builds is executed.
"""

import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from rdflib import RDF, XSD, Graph, Literal, URIRef
from rdflib.namespace import SH
from seams import SemPKMPlan

from seams_runtime import (
    ContractViolation,
    Identity,
    ModelGraph,
    ResolutionError,
    Runtime,
    SemPKMStore,
    SplitStore,
    SQLiteStore,
    StoreReplyInvalid,
    StoreUnavailable,
)
from seams_runtime.host import build_app, store_health
from seams_runtime.model import DEPLOY, SEAM
from seams_runtime.sempkm import EDGE_PREDICATE, EDGE_SOURCE, EDGE_TARGET

ROOT = Path(__file__).resolve().parents[1]
CH09 = ROOT / "examples" / "expenses" / "chapter-09"
T = "https://example.org/sempkm/"
EX = "https://example.org/expenses/"
URL = "http://pkm.test:8000"
TOKEN = "s3cret-service-t0ken"
DATA = "https://pkm.test/data/"

ENV = ("SEMPKM_URL", "SEMPKM_URL_FILE", "SEMPKM_TOKEN", "SEMPKM_TOKEN_FILE", "SEAMS_STORE_OVERRIDE", "SEAMS_MODEL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


# ── a fake SemPKM ────────────────────────────────────────────────────────────


def _value(value):
    """SemPKM's handlers/object_create.py _to_rdf_value."""
    if isinstance(value, str):
        if value.startswith(("http://", "https://", "urn:")):
            return URIRef(value)
        if len(value) >= 19 and value[4:5] == "-" and value[7:8] == "-" and "T" in value:
            return Literal(value, datatype=XSD.dateTime)
        if len(value) == 10 and value[4:5] == "-" and value[7:8] == "-" and value[:4].isdigit():
            return Literal(value, datatype=XSD.date)
        return Literal(value)
    return Literal(value)


class FakeSemPKM:
    """Commands, SPARQL and health over one rdflib graph (the current state)."""

    def __init__(self, token: str = TOKEN):
        self.token = token
        self.graph = Graph()
        self.requests: list[httpx.Request] = []
        self.minted = 0
        self.answer = None  # a callable(request) -> Response | None that pre-empts the fake
        self.healthy = True

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def posts(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST" and r.url.path == path]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.answer is not None:
            answered = self.answer(request)
            if answered is not None:
                return answered
        if request.url.path == "/api/health":
            status = "healthy" if self.healthy else "degraded"
            return httpx.Response(200, json={"status": status, "services": {"api": "up"}})
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "Invalid or expired token"})
        body = json.loads(request.content)
        if request.url.path == "/api/commands":
            return self.commands(body if isinstance(body, list) else [body])
        if request.url.path == "/api/sparql":
            result = self.graph.query(body["query"])
            return httpx.Response(
                200, content=result.serialize(format="json"), headers={"content-type": "application/json"}
            )
        return httpx.Response(404, json={"detail": "Not Found"})

    def mint(self, kind: str) -> str:
        self.minted += 1
        return f"{DATA}{kind}/{self.minted:04d}"

    def commands(self, commands: list[dict]) -> httpx.Response:
        """All commands of one request commit together, or none does."""
        inserts, deletes, results, slots = [], [], [], {}
        for cmd in commands:
            params = cmd["params"]
            if cmd["command"] == "object.create":
                iri = self.mint(params["type"].rsplit("/", 1)[-1])
                s = URIRef(iri)
                inserts.append((s, RDF.type, URIRef(params["type"])))
                for p, v in params["properties"].items():
                    for item in v if isinstance(v, list) else [v]:
                        inserts.append((s, URIRef(p), _value(item)))
                if cmd.get("slot"):
                    slots[cmd["slot"]] = iri
            elif cmd["command"] == "edge.create":
                ends = {}
                for end in ("source", "target"):
                    ref = params[end]
                    if ref.startswith("@slot:"):
                        if ref[6:] not in slots:
                            return httpx.Response(400, json={"error": f"Unresolved slot reference: {ref}"})
                        ref = slots[ref[6:]]
                    ends[end] = URIRef(ref)
                iri = self.mint("edge")
                e = URIRef(iri)
                inserts += [
                    (e, RDF.type, URIRef("urn:sempkm:Edge")),
                    (e, EDGE_SOURCE, ends["source"]),
                    (e, EDGE_TARGET, ends["target"]),
                    (e, EDGE_PREDICATE, URIRef(params["predicate"])),
                ]
            elif cmd["command"] == "object.patch":
                iri = params["iri"]
                for p, v in params["properties"].items():
                    deletes += list(self.graph.triples((URIRef(iri), URIRef(p), None)))
                    inserts.append((URIRef(iri), URIRef(p), _value(v)))
            else:
                return httpx.Response(400, json={"error": f"Unknown command type: {cmd['command']}"})
            results.append({"iri": iri, "event_iri": "urn:sempkm:event:1", "command": cmd["command"]})
        for t in deletes:
            self.graph.remove(t)
        for t in inserts:
            self.graph.add(t)
        return httpx.Response(
            200, json={"results": results, "event_iri": "urn:sempkm:event:1", "timestamp": "2026-11-04T00:00:00Z"}
        )


# ── an inline model: an expense with a nested magnitude, a category, a list ──

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix gist:   <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix :       <https://example.org/sempkm/> .
"""

MODEL = """
:g {
    :p a proc:Process ; rdfs:label "P" .
    :op a comm:Operation ; rdfs:label "Op" ; seam:writes :ExpenseShape .
    :pkm a arch:Container ; rdfs:label "PKM" ; deploy:storeKind deploy:SemPKM .
    :api a arch:Container ; rdfs:label "API" ;
        seam:executes :p ; seam:exposes :op ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ] ;
            deploy:binding [ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm> ;
                             deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ] ] .

    :o a seam:Model , owl:Ontology ; seam:notation seam:Ontology .
    :Expense a owl:Class ; rdfs:label "Expense" ; seam:inModel :o .
    :Magnitude a owl:Class ; rdfs:label "Magnitude" ; seam:inModel :o .
    :Other a owl:Class ; rdfs:label "Other" ; seam:inModel :o .
    :ExpenseState a owl:Class ; rdfs:subClassOf gist:Category ; seam:inModel :o .
    :s_draft a :ExpenseState ; rdfs:label "draft" .
    :s_paid a :ExpenseState ; rdfs:label "paid" .
    :USD rdfs:label "US dollar" .

    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        seam:storedIn :pkm ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
            [ sh:path :description ; sh:name "description" ; sh:datatype xsd:string ;
              sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ,
            [ sh:path :amount ; sh:name "amount" ; sh:node :MagnitudeShape ; sh:maxCount 1 ; sh:order 1 ] ,
            [ sh:path :date ; sh:name "date" ; sh:datatype xsd:date ; sh:maxCount 1 ; sh:order 2 ] ,
            [ sh:path :nights ; sh:name "nights" ; sh:datatype xsd:integer ; sh:maxCount 1 ; sh:order 3 ] ,
            [ sh:path :status ; sh:name "status" ; sh:class :ExpenseState ; sh:maxCount 1 ; sh:order 4 ] ,
            [ sh:path :tag ; sh:name "tags" ; sh:datatype xsd:string ; sh:order 5 ] .

    :MagnitudeShape a sh:NodeShape ; sh:targetClass :Magnitude ;
        sh:property [ sh:path :numericValue ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ,
                    [ sh:path :unit ; sh:hasValue :USD ] .
}
"""

SHAPE = URIRef(T + "ExpenseShape")
NOTE = URIRef(T + "NoteShape")  # stored nowhere in particular: relational
TRAIN = {
    "id": "ignored-runtime-id",
    "description": "Train to Leeds",
    "amount": "42.50",
    "date": "2026-10-01",
    "nights": "2",
    "status": "draft",
    "tags": ["rail", "client"],
}


@pytest.fixture
def model(tmp_path) -> ModelGraph:
    path = tmp_path / "model.trig"
    path.write_text(PREFIXES + MODEL)
    return ModelGraph(path)


@pytest.fixture
def fake() -> FakeSemPKM:
    return FakeSemPKM()


@pytest.fixture
def pkm(model, fake) -> SemPKMStore:
    plan = model.store_plan().sempkm
    assert plan is not None
    return SemPKMStore(model, plan, URL + "/", TOKEN, transport=fake.transport)


@pytest.fixture
def split(pkm, tmp_path) -> SplitStore:
    return SplitStore(SQLiteStore(tmp_path / "state.sqlite"), pkm)


# ── what is sent ─────────────────────────────────────────────────────────────


def test_one_entity_is_one_request_of_typed_commands(pkm):
    assert pkm.commands(SHAPE, TRAIN) == [
        {
            "command": "object.create",
            "slot": "entity",
            "params": {
                "type": T + "Expense",
                "properties": {
                    T + "date": "2026-10-01",
                    T + "description": "Train to Leeds",
                    T + "nights": 2,
                    T + "status": T + "s_draft",
                    T + "tag": ["rail", "client"],
                },
            },
        },
        {
            "command": "object.create",
            "slot": "amount.0",
            "params": {"type": T + "Magnitude", "properties": {T + "numericValue": 42.5, T + "unit": T + "USD"}},
        },
        {
            "command": "edge.create",
            "params": {"source": "@slot:entity", "target": "@slot:amount.0", "predicate": T + "amount"},
        },
    ]


def test_the_runtime_id_is_never_sent(pkm):
    sent = json.dumps(pkm.commands(SHAPE, TRAIN))
    assert "ignored-runtime-id" not in sent and T + "id" not in sent


def test_the_read_query_is_scoped_sorted_and_stable(pkm):
    query = pkm.select(SHAPE)
    assert query.splitlines()[0] == ("SELECT ?f_amount ?f_date ?f_description ?f_nights ?f_status ?f_tags ?iri WHERE {")
    assert f"  ?iri a <{T}Expense> ." in query
    assert f"  OPTIONAL {{ ?iri <{T}description> ?f_description . }}" in query
    assert (
        f"  OPTIONAL {{ ?e_amount <urn:sempkm:source> ?iri ; <urn:sempkm:predicate> <{T}amount> ; "
        f"<urn:sempkm:target> ?n_amount . ?n_amount a <{T}Magnitude> ; <{T}numericValue> ?f_amount . }}"
    ) in query
    assert query.endswith("}\nORDER BY ?iri")
    assert "VALUES" not in query
    assert f"<{T}id>" not in query
    assert pkm.select(SHAPE) == query
    by_iri = pkm.select(SHAPE, [DATA + "b", DATA + "a"])
    assert f"  VALUES ?iri {{ <{DATA}a> <{DATA}b> }}" in by_iri


# ── create and read through the fake ─────────────────────────────────────────


def test_create_keeps_the_minted_iri_and_reads_back_the_entity(pkm, fake):
    iri, stored = pkm.create(SHAPE, TRAIN)
    assert iri == DATA + "Expense/0001"
    assert stored["id"] == iri
    [request] = fake.requests
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.url == URL + "/api/commands"
    # parent, nested node and the edge joining them committed together
    e = URIRef(iri)
    [edge] = fake.graph.subjects(EDGE_SOURCE, e)
    node = fake.graph.value(edge, EDGE_TARGET)
    assert fake.graph.value(edge, EDGE_PREDICATE) == URIRef(T + "amount")
    assert (node, RDF.type, URIRef(T + "Magnitude")) in fake.graph
    assert fake.graph.value(e, URIRef(T + "status")) == URIRef(T + "s_draft")
    assert (e, URIRef(T + "amount"), None) not in fake.graph  # no blank node, no inline value

    [(read_iri, data)] = pkm.read(SHAPE)
    assert read_iri == iri
    assert data == {
        "amount": "42.5",
        "date": "2026-10-01",
        "description": "Train to Leeds",
        "id": iri,
        "nights": 2,
        "status": "draft",
        "tags": ["client", "rail"],
    }
    assert pkm.get(iri, SHAPE) == data


def test_reads_never_return_objects_of_other_classes(pkm, fake):
    fake.commands(
        [{"command": "object.create", "params": {"type": T + "Other", "properties": {T + "description": "x"}}}]
    )
    assert pkm.read(SHAPE) == []
    assert pkm.get(DATA + "Other/0001", SHAPE) is None


def test_reading_no_iris_sends_nothing(pkm, fake):
    assert pkm.read(SHAPE, []) == []
    assert fake.requests == []


def test_a_member_iri_outside_the_category_is_read_as_the_iri(pkm, fake):
    iri, _ = pkm.create(SHAPE, {"description": "Taxi", "status": "draft"})
    fake.graph.set((URIRef(iri), URIRef(T + "status"), URIRef(T + "s_unknown")))
    assert pkm.get(iri, SHAPE)["status"] == T + "s_unknown"


# ── the split store ──────────────────────────────────────────────────────────


def test_split_store_indexes_the_entity_and_keeps_its_data_in_sempkm(split, fake):
    row = split.put_entity("uuid-1", SHAPE, TRAIN, correlation_key="e1", instance_id="i1", status="draft")
    iri = DATA + "Expense/0001"
    assert row["id"] == iri and row["data"]["id"] == iri
    assert (row["correlation_key"], row["instance_id"], row["status"]) == ("e1", "i1", "draft")
    index = split.relational.get_entity(iri)
    assert index["data"] == {}  # the domain data lives only in SemPKM
    assert split.relational.get_entity("uuid-1") is None
    assert split.get_entity(iri)["data"]["description"] == "Train to Leeds"
    [listed] = split.query(SHAPE, correlation_key="e1")
    assert listed["id"] == iri and listed["data"]["amount"] == "42.5"
    assert split.query(SHAPE, correlation_key="other") == []


def test_split_store_updates_by_patching_only_what_changed(split, fake):
    row = split.put_entity("uuid-1", SHAPE, TRAIN, correlation_key="e1", status="draft")
    iri = row["id"]
    updated = split.put_entity(iri, SHAPE, {**row["data"], "status": "paid"}, correlation_key="e1", status="paid")
    patch = fake.posts("/api/commands")[-1]
    assert patch == [{"command": "object.patch", "params": {"iri": iri, "properties": {T + "status": T + "s_paid"}}}]
    assert updated["status"] == "paid" and updated["data"]["status"] == "paid"
    assert split.get_entity(iri)["data"]["status"] == "paid"
    assert len(fake.posts("/api/commands")) == 2


def test_a_changed_nested_value_is_not_updated(split, fake):
    row = split.put_entity("uuid-1", SHAPE, TRAIN)
    with pytest.raises(ResolutionError) as info:
        split.put_entity(row["id"], SHAPE, {**row["data"], "amount": "1.00"})
    assert (info.value.subject, info.value.predicate) == (str(SHAPE), T + "amount")
    assert len(fake.posts("/api/commands")) == 1


def test_objects_written_by_others_are_listed_after_the_indexed_ones(split, fake):
    fake.commands(
        [{"command": "object.create", "params": {"type": T + "Expense", "properties": {T + "description": "Hotel"}}}]
    )
    row = split.put_entity("uuid-1", SHAPE, {"description": "Train"}, correlation_key="e1")
    rows = split.query(SHAPE)
    assert [r["id"] for r in rows] == [row["id"], DATA + "Expense/0001"]
    assert rows[1]["correlation_key"] is None and rows[1]["data"] == {
        "description": "Hotel",
        "id": DATA + "Expense/0001",
    }
    assert [r["id"] for r in split.query(SHAPE, description="Hotel")] == [DATA + "Expense/0001"]
    assert split.query(SHAPE, correlation_key="e1") == [rows[0]]


def test_other_shapes_and_process_state_stay_relational(split, fake):
    split.put_entity("n1", NOTE, {"text": "hi"}, correlation_key="e1")
    split.save_state("i1", "urn:p", "{}", correlation_key="e1", status="running")
    split.replace_user_tasks("i1", [{"task": "urn:t", "bpmn_id": "t", "process": "urn:p", "correlation_key": "e1"}])
    assert split.get_entity("n1")["data"] == {"text": "hi"}
    assert split.query(NOTE) == split.relational.query(NOTE)
    assert split.get_instance("i1")["status"] == "running"
    assert split.get_user_task("urn:t", "e1")["bpmn_id"] == "t"
    assert fake.requests == []


def test_an_indexed_entity_gone_from_sempkm_reads_as_missing(split, fake):
    row = split.put_entity("uuid-1", SHAPE, {"description": "Train"})
    fake.graph.remove((URIRef(row["id"]), None, None))
    assert split.get_entity(row["id"]) is None


# ── failures (ADR-0025 section 11) ───────────────────────────────────────────


def _raise(exc):
    def answer(request):
        raise exc

    return answer


@pytest.mark.parametrize(
    "answer, reason",
    [
        (_raise(httpx.ConnectError("refused")), "unreachable (ConnectError)"),
        (_raise(httpx.ReadTimeout("slow")), "timed out"),
        (lambda r: httpx.Response(500, json={"error": "Internal error"}), "answered 500"),
        (lambda r: httpx.Response(503, text="down"), "answered 503"),
        (lambda r: httpx.Response(429, json={"error": "Rate limit exceeded"}), "answered 429"),
    ],
    ids=["unreachable", "timeout", "500", "503", "rate-limited"],
)
def test_an_unavailable_sempkm_is_503_naming_the_store_and_keeps_nothing(split, fake, answer, reason):
    fake.answer = answer
    with pytest.raises(StoreUnavailable) as info:
        split.put_entity("uuid-1", SHAPE, TRAIN, correlation_key="e1")
    err = info.value
    assert err.http_status == 503 and err.store == T + "pkm"
    assert reason in err.reason
    assert split.relational.query(SHAPE) == []
    assert len(fake.graph) == 0
    assert err.problem() == {
        "type": "about:blank",
        "title": "Store unavailable",
        "status": 503,
        "detail": str(err),
        "store": T + "pkm",
    }


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_is_503_and_the_log_names_store_and_scope_not_the_token(pkm, fake, caplog, status):
    fake.answer = lambda r: (
        httpx.Response(status, json={"detail": "Token lacks required scope: commands:execute"})
        if r.url.path == "/api/commands"
        else None
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StoreUnavailable) as info:
            pkm.create(SHAPE, TRAIN)
    assert info.value.http_status == 503
    assert "commands:execute" in info.value.reason
    assert f"SemPKM store {T}pkm refused the service token" in caplog.text
    assert "needs scope commands:execute" in caplog.text
    assert TOKEN not in caplog.text and TOKEN not in str(info.value.to_dict())
    assert TOKEN not in repr(pkm)


def test_a_read_refused_names_the_sparql_scope(pkm, fake, caplog):
    fake.token = "another"
    with caplog.at_level(logging.ERROR, logger="seams_runtime.sempkm"):
        with pytest.raises(StoreUnavailable) as info:
            pkm.read(SHAPE)
    assert "sparql:read" in info.value.reason and "needs scope sparql:read" in caplog.text


@pytest.mark.parametrize(
    "answer, reason",
    [
        (lambda r: httpx.Response(200, json={"results": []}), "object.create returned no IRI"),
        (lambda r: httpx.Response(200, json={"results": [{"iri": ""}]}), "object.create returned no IRI"),
        (lambda r: httpx.Response(200, json={"results": [{"iri": "not an iri"}]}), "is not an IRI"),
        (lambda r: httpx.Response(200, json=["unexpected"]), "object.create returned no IRI"),
        (lambda r: httpx.Response(200, text="<html>"), "the answer is not JSON"),
        (lambda r: httpx.Response(400, json={"error": "Unresolved slot reference"}), "answered 400"),
    ],
    ids=["no-results", "empty-iri", "bad-iri", "not-an-object", "not-json", "rejected"],
)
def test_a_malformed_answer_is_502_and_keeps_nothing(split, fake, answer, reason):
    fake.answer = answer
    with pytest.raises(StoreReplyInvalid) as info:
        split.put_entity("uuid-1", SHAPE, TRAIN)
    assert info.value.http_status == 502 and info.value.store == T + "pkm"
    assert reason in info.value.reason
    assert split.relational.query(SHAPE) == []


def test_unreadable_sparql_results_are_502(pkm, fake):
    fake.answer = lambda r: httpx.Response(200, json={"head": {}}) if r.url.path == "/api/sparql" else None
    with pytest.raises(StoreReplyInvalid) as info:
        pkm.read(SHAPE)
    assert "not SPARQL JSON results" in info.value.reason


def test_reachable_follows_the_health_endpoint(pkm, fake):
    assert pkm.reachable() is True
    assert "authorization" not in fake.requests[-1].headers
    fake.healthy = False
    assert pkm.reachable() is False
    fake.answer = _raise(httpx.ConnectError("refused"))
    assert pkm.reachable() is False


def test_a_stored_shape_without_a_target_class_fails_when_the_store_is_built(model, fake):
    plan = model.store_plan().sempkm
    model.ds.remove((SHAPE, SH.targetClass, None))
    with pytest.raises(ResolutionError) as info:
        SemPKMStore(model, plan, URL, TOKEN, transport=fake.transport)
    assert (info.value.subject, info.value.predicate) == (str(SHAPE), str(SH.targetClass))


def test_a_nested_shape_without_a_target_class_fails_when_the_store_is_built(model, fake):
    plan = model.store_plan().sempkm
    model.ds.remove((URIRef(T + "MagnitudeShape"), SH.targetClass, None))
    with pytest.raises(ResolutionError) as info:
        SemPKMStore(model, plan, URL, TOKEN, transport=fake.transport)
    assert (info.value.subject, info.value.predicate) == (T + "MagnitudeShape", str(SH.targetClass))


def test_a_shape_not_stored_in_sempkm_is_refused(pkm):
    with pytest.raises(ResolutionError) as info:
        pkm.commands(NOTE, {})
    assert (info.value.subject, info.value.predicate) == (str(NOTE), str(SEAM.storedIn))


def test_the_plan_shapes_are_the_ones_built(model, fake):
    plan = model.store_plan().sempkm
    assert plan == SemPKMPlan(URIRef(T + "pkm"), URIRef(T + "api"), "SEMPKM_URL", "SEMPKM_TOKEN", (SHAPE,))
    assert SemPKMStore(model, plan, URL, TOKEN).shapes == (SHAPE,)


# ── Runtime.load on chapter 9 with its expenses in SemPKM ────────────────────

PKM_CONTAINER = """
    :expense_pkm a arch:Container ; rdfs:label "Expense PKM" ;
        arch:technology "SemPKM" ;
        deploy:storeKind deploy:SemPKM ;
        seam:inModel :expense_architecture .

    # Two environments (ADR-0015)."""
PKM_BINDINGS = """deploy:connectsTo :expense_db ] ;
                               deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://expense-pkm:8000" ;
                                                deploy:connectsTo :expense_pkm ] ;
                               deploy:binding [ deploy:key "SEMPKM_TOKEN" ;
                                                deploy:secretRef <https://secrets.example.org/expenses/prod/sempkm> ;
                                                deploy:secretName "expenses-prod-sempkm" ;
                                                deploy:authenticatesTo :expense_pkm ] ] ;"""


def sempkm_chapter(tmp_path) -> Path:
    """Chapter 9 copied into tmp_path with :ExpenseShape stored in a SemPKM store."""
    dest = tmp_path / "chapter"
    shutil.copytree(CH09, dest, ignore=shutil.ignore_patterns("generated", "__pycache__"))
    trig = dest / "expenses.trig"
    text = trig.read_text()
    edits = [
        ("\n    # Two environments (ADR-0015).", PKM_CONTAINER),
        ("deploy:connectsTo :expense_db ] ] ;", PKM_BINDINGS),
        (":ExpenseShape seam:storedIn :expense_db .", ":ExpenseShape seam:storedIn :expense_pkm ."),
    ]
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new, 1)
    trig.write_text(text)
    return trig


def load(trig, fake, tmp_path, **kw) -> Runtime:
    kw.setdefault("store", SQLiteStore(tmp_path / f"{uuid.uuid4().hex}.sqlite"))
    return Runtime.load(trig, sempkm_transport=fake.transport, templates_dir=tmp_path, **kw)


@pytest.fixture
def chapter(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMPKM_URL", URL)
    monkeypatch.setenv("SEMPKM_TOKEN", TOKEN)
    return sempkm_chapter(tmp_path)


def test_load_wraps_the_relational_store_and_never_logs_the_token(chapter, fake, tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        rt = load(chapter, fake, tmp_path)
    assert isinstance(rt.store, SplitStore) and rt.store.kind == "sqlite"
    assert rt.store.entities.shapes == (URIRef(EX + "ExpenseShape"),)
    assert rt.store.entities.url == URL
    assert "store service token from SEMPKM_TOKEN" in caplog.text
    assert f"in the SemPKM store {EX}expense_pkm" in caplog.text
    assert TOKEN not in caplog.text


def test_write_stores_the_expense_in_sempkm_under_its_minted_iri(chapter, fake, tmp_path):
    rt = load(chapter, fake, tmp_path)
    row = rt.write(":ExpenseShape", {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"})
    iri = DATA + "Expense/0001"
    assert row["id"] == iri and row["data"]["id"] == iri and row["status"] == "draft"
    [commands] = fake.posts("/api/commands")
    [create] = commands
    assert create["params"]["type"] == EX + "Expense"
    assert create["params"]["properties"] == {
        EX + "amount": 42.5,
        EX + "date": "2026-10-01",
        EX + "description": "Train to Leeds",
        EX + "status": EX + "s_draft",
    }
    [listed] = rt.query(":ExpenseShape")
    assert listed["id"] == iri
    assert listed["data"] == {
        "amount": "42.5",
        "date": "2026-10-01",
        "description": "Train to Leeds",
        "id": iri,
        "status": "draft",
    }


def test_an_invalid_payload_is_422_and_sends_nothing(chapter, fake, tmp_path):
    rt = load(chapter, fake, tmp_path)
    with pytest.raises(ContractViolation):
        rt.write(":ExpenseShape", {"description": "No amount"})
    assert fake.requests == []


def test_a_process_creates_then_patches_the_expense_and_keeps_its_state_relational(chapter, fake, tmp_path):
    from seams_runtime import HeaderAuthenticator

    rt = load(chapter, fake, tmp_path, authenticator=HeaderAuthenticator())
    task = EX + "approval_bpmn#approve_expense"
    # 250.00 routes to the manager (chapter 9's approval_routing)
    expense = {"description": "Train to Leeds", "amount": "250.00", "date": "2026-10-01"}

    async def main():
        inst = await rt.start_process(":approval_process", expense, correlation_key="e1")
        result = await inst.wait()
        assert result["status"] == "waiting", result["error"]
        [iri] = result["entities"]["Expense"]
        assert iri.startswith(DATA + "Expense/")
        [stored] = rt.query(":ExpenseShape", expense="e1")
        assert stored["id"] == iri and stored["status"] == "submitted"
        assert stored["data"]["status"] == "submitted" and stored["instance_id"] == inst.id
        inst = await rt.complete_task(task, {"decision": "approved"}, "e1", Identity("bob", frozenset({"manager"})))
        result = await inst.wait()
        assert result["status"] == "waiting", result["error"]
        assert result["entities"]["Expense"] == [iri]
        return iri

    iri = asyncio.run(main())
    assert fake.graph.value(URIRef(iri), URIRef(EX + "status")) == URIRef(EX + "s_approved")
    assert [list(fake.graph.subjects(RDF.type, URIRef(EX + "Expense")))] == [[URIRef(iri)]]
    # process state, user tasks and the relational shapes never reach SemPKM
    assert rt.store.relational.get_instance(next(iter(rt.instances)))["process"] == EX + "approval_process"
    assert [r["shape"] for r in rt.store.relational.query(URIRef(EX + "ApprovalShape"))] == [EX + "ApprovalShape"]
    assert all(c["command"] in ("object.create", "object.patch") for b in fake.posts("/api/commands") for c in b)


def test_a_failed_sempkm_write_fails_the_instance_with_a_503_naming_the_store(chapter, fake, tmp_path):
    rt = load(chapter, fake, tmp_path)
    fake.answer = lambda r: httpx.Response(503, text="down") if r.url.path == "/api/commands" else None

    async def main():
        inst = await rt.start_process(
            ":approval_process", {"description": "Taxi", "amount": "9.00", "date": "2026-10-01"}, correlation_key="e2"
        )
        return await inst.wait()

    result = asyncio.run(main())
    assert result["status"] == "failed"
    assert (result["error"]["type"], result["error"]["http_status"]) == ("StoreUnavailable", 503)
    assert result["error"]["store"] == EX + "expense_pkm"
    assert rt.store.relational.query(URIRef(EX + "ExpenseShape")) == []


def test_load_without_the_base_url_names_connects_to(chapter, fake, tmp_path, monkeypatch):
    monkeypatch.delenv("SEMPKM_URL")
    with pytest.raises(ResolutionError) as info:
        load(chapter, fake, tmp_path)
    assert (info.value.subject, info.value.predicate) == (EX + "expense_api", str(DEPLOY.connectsTo))
    assert "SEMPKM_URL" in info.value.detail and "SEMPKM_URL_FILE" in info.value.detail


def test_load_without_the_token_names_authenticates_to(chapter, fake, tmp_path, monkeypatch):
    monkeypatch.delenv("SEMPKM_TOKEN")
    with pytest.raises(ResolutionError) as info:
        load(chapter, fake, tmp_path)
    assert (info.value.subject, info.value.predicate) == (EX + "expense_api", str(DEPLOY.authenticatesTo))
    assert "SEMPKM_TOKEN_FILE" in info.value.detail


def test_the_token_can_come_from_a_file(chapter, fake, tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("SEMPKM_TOKEN")
    secret = tmp_path / "token"
    secret.write_text(TOKEN + "\n")
    monkeypatch.setenv("SEMPKM_TOKEN_FILE", str(secret))
    with caplog.at_level(logging.DEBUG):
        rt = load(chapter, fake, tmp_path)
        rt.write(":ExpenseShape", {"description": "Taxi", "amount": "9.00", "date": "2026-10-01"})
    assert fake.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in caplog.text


def test_the_sqlite_override_keeps_the_expenses_in_sqlite_and_warns(chapter, fake, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    monkeypatch.delenv("SEMPKM_TOKEN")  # the override needs neither binding's value
    with caplog.at_level(logging.WARNING, logger="seams_runtime.runtime"):
        rt = Runtime.load(chapter, db_path=tmp_path / "o.sqlite", templates_dir=tmp_path)
    assert isinstance(rt.store, SQLiteStore)
    assert f"the entities of the SemPKM store {EX}expense_pkm stay in embedded SQLite" in caplog.text
    rt.write(":ExpenseShape", {"description": "Taxi", "amount": "9.00", "date": "2026-10-01"})
    assert fake.requests == []
    assert store_health(rt)["sempkm"] == {
        "kind": "SemPKM",
        "container": EX + "expense_pkm",
        "reachable": None,
        "override": True,
    }


# ── the host: /healthz and problem+json ──────────────────────────────────────

ROUTES = """\
from fastapi import APIRouter, Request

from seams_runtime import Runtime, SQLiteStore

runtime = Runtime.load({trig!r}, store=SQLiteStore({db!r}), templates_dir={tmp!r})
router = APIRouter()


@router.post("/expenses")
async def create(request: Request):
    return runtime.write(":ExpenseShape", await request.json())
"""


@pytest.fixture
def client(chapter, fake, tmp_path):
    routes = tmp_path / "routes.py"
    routes.write_text(ROUTES.format(trig=str(chapter), db=str(tmp_path / "h.sqlite"), tmp=str(tmp_path)))
    app = build_app(routes)
    app.state.runtime.store.entities.transport = fake.transport
    with TestClient(app) as c:
        yield c


def test_healthz_reports_the_sempkm_store(client, fake):
    body = client.get("/healthz").json()
    assert body["store"]["sempkm"] == {
        "kind": "SemPKM",
        "container": EX + "expense_pkm",
        "reachable": True,
        "override": False,
    }
    assert body["store"]["kind"] == "sqlite"
    fake.healthy = False
    assert client.get("/healthz").json()["store"]["sempkm"]["reachable"] is False
    assert TOKEN not in json.dumps(body)


def test_a_write_while_sempkm_is_down_answers_503_problem_json(client, fake):
    fake.answer = _raise(httpx.ConnectError("refused"))
    r = client.post("/expenses", json={"description": "Taxi", "amount": "9.00", "date": "2026-10-01"})
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert (body["title"], body["status"], body["store"]) == ("Store unavailable", 503, EX + "expense_pkm")
    assert TOKEN not in r.text


def test_a_write_answered_without_an_iri_is_502(client, fake):
    fake.answer = lambda r: httpx.Response(200, json={"results": []}) if r.url.path == "/api/commands" else None
    r = client.post("/expenses", json={"description": "Taxi", "amount": "9.00", "date": "2026-10-01"})
    assert r.status_code == 502 and r.json()["title"] == "Bad store reply"
    fake.answer = None
    assert (
        client.post("/expenses", json={"description": "Taxi", "amount": "9.00", "date": "2026-10-01"}).status_code
        == 200
    )
