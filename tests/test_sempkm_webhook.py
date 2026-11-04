"""The SemPKM webhook receiver and its generated route (M024/S04, ADR-0027 sections 3 to 9).

SemPKM POSTs ``{"event_type", "event_iri", "command", "timestamp"}`` to the
channel's comm:path. The receiver reads the event back with the service token
(SemPKM signs nothing, so this is what authenticates a delivery), reads the
changed objects of the accepted shape's class, validates them, and starts each
subscribed process once per (process, event, object), the object's IRI as
correlation key. The SemPKM here is a fake behind ``httpx.MockTransport``: its
current state is an rdflib default graph and each event a named graph, and it
runs the SPARQL the store sends, refusing a ``GRAPH`` query that is not
``all_graphs`` and an ``all_graphs`` query from a token whose user is not an
owner, as SemPKM does.
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rdflib import RDF, Dataset, Literal, URIRef
from seams import COMM, SEAM, load

from seams_gen import GeneratorError
from seams_gen.fastapi import extract_routes, render_routes
from seams_runtime import ResolutionError, Runtime, SQLiteStore
from seams_runtime.host import load_routes
from seams_runtime.sempkm import EVENT_AFFECTED, EVENT_CLASS

ROOT = Path(__file__).resolve().parents[1]
BPMN = (ROOT / "tests" / "fixtures" / "channel_start" / "payout.bpmn").read_text()
T = "https://example.org/hooks/"
CHANNEL = URIRef(T + "vendor_changes")
PROCESS = T + "vendor_check_process"
SHAPE = T + "VendorShape"
PKM = T + "pkm"
URL = "http://pkm.test:8000"
TOKEN = "s3cret-webhook-t0ken"
DATA = "https://pkm.test/data/"
ACME = DATA + "Vendor/0001"
GLOBEX = DATA + "Vendor/0002"
EVENT = "urn:sempkm:event:5f0c2d7e-8a51-4c3b-9d7e-1a2b3c4d5e6f"
ENV = ("SEMPKM_URL", "SEMPKM_URL_FILE", "SEMPKM_TOKEN", "SEMPKM_TOKEN_FILE", "SEAMS_STORE_OVERRIDE", "SEAMS_MODEL")

# The ADR-0027 section 1 example (as in test_sempkm_webhook_model.py), its
# accepted shape with an id and a required name.
MODEL = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/hooks/> .

<urn:seams:graph:model:hooks_architecture> {
    :hooks_architecture a seam:Model ; rdfs:label "Hooks Architecture" .
    :system a arch:System ; rdfs:label "Hooks" ; arch:contains :api , :pkm ;
        seam:inModel :hooks_architecture .
    :pkm a arch:Container ; rdfs:label "PKM" ; deploy:storeKind deploy:SemPKM ;
        seam:inModel :hooks_architecture .
    :api a arch:Container ; rdfs:label "API" ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ] ,
                [ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm-token> ;
                  deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ] ] ;
        seam:inModel :hooks_architecture .
    :vendor_changes a comm:Channel ; rdfs:label "vendor changed in SemPKM" ;
        comm:transport comm:SemPKMWebhook ;
        comm:eventName "object.changed" ;
        comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/vendor-changes" ] ;
        seam:inModel :hooks_architecture .
}

<urn:seams:graph:model:hooks_data> {
    :hooks_data a seam:Model ; rdfs:label "Hooks Data" .
    :VendorShape a sh:NodeShape ; rdfs:label "Vendor" ;
        sh:targetClass :Vendor ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
        sh:property [ sh:path :name ; sh:name "name" ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
        seam:inModel :hooks_data .
}

<urn:seams:graph:model:hooks_ontology> {
    :hooks_ontology a seam:Model , owl:Ontology ; rdfs:label "Hooks Ontology" .
    :Vendor a owl:Class ; rdfs:label "Vendor" ; seam:inModel :hooks_ontology .
}

<urn:seams:graph:model:payout_bpmn> {
    :payout_bpmn a seam:Model ; rdfs:label "Vendor check (BPMN)" .
    :vendor_check_process a proc:Process ; rdfs:label "Vendor check" ;
        seam:inModel :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#payment_received> a proc:MessageCatchEvent ;
        rdfs:label "Vendor changed" ;
        seam:inModel :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#pay_expense> a proc:ServiceTask ;
        rdfs:label "Check vendor" ;
        seam:inModel :payout_bpmn .
}

<urn:seams:graph:seams> {
    :api seam:exposes :vendor_changes ;
        seam:executes :vendor_check_process .
    :vendor_changes seam:acceptsShape :VendorShape .
    :VendorShape seam:storedIn :pkm .
    :vendor_check_process seam:detailedBy :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#payment_received> seam:subscribesTo :vendor_changes .
    :payout_bpmn seam:renderPayload <payout.bpmn> .
    :hooks_ontology seam:notation seam:Ontology .
}
"""


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SEMPKM_URL", URL)
    monkeypatch.setenv("SEMPKM_TOKEN", TOKEN)


# ── a fake SemPKM ────────────────────────────────────────────────────────────


class FakeSemPKM:
    """SPARQL over one rdflib Dataset: the current state in the default graph,
    each event in its own named graph."""

    def __init__(self):
        self.ds = Dataset()
        self.owner = True
        self.requests: list[httpx.Request] = []
        self.answer = None  # a callable(request) -> Response | None that pre-empts the fake

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def vendor(self, iri: str, name: str | None, cls: str = "Vendor") -> None:
        self.ds.add((URIRef(iri), RDF.type, URIRef(T + cls)))
        if name is not None:
            self.ds.add((URIRef(iri), URIRef(T + "name"), Literal(name)))

    def event(self, event: str, *affected: str) -> None:
        g = self.ds.graph(URIRef(event))
        g.add((URIRef(event), RDF.type, EVENT_CLASS))
        for iri in affected:
            g.add((URIRef(event), EVENT_AFFECTED, URIRef(iri)))

    def sparql(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/api/sparql"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.answer is not None:
            answered = self.answer(request)
            if answered is not None:
                return answered
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "Invalid or expired token"})
        if request.url.path != "/api/sparql":
            return httpx.Response(404, json={"detail": "Not Found"})
        body = json.loads(request.content)
        all_graphs = body.get("all_graphs", False)
        if all_graphs and not self.owner:
            return httpx.Response(403, json={"detail": "Requires owner role for all_graphs"})
        if "GRAPH" in body["query"] and not all_graphs:
            return httpx.Response(403, json={"detail": "GRAPH clauses need all_graphs"})
        result = self.ds.query(body["query"])
        return httpx.Response(
            200, content=result.serialize(format="json"), headers={"content-type": "application/json"}
        )


@pytest.fixture
def fake() -> FakeSemPKM:
    return FakeSemPKM()


def write_model(tmp_path: Path, text: str = MODEL) -> Path:
    (tmp_path / "payout.bpmn").write_text(BPMN)
    trig = tmp_path / "model.trig"
    trig.write_text(text)
    return trig


def runtime(tmp_path, fake, **kw) -> Runtime:
    kw.setdefault("store", SQLiteStore(tmp_path / f"{uuid.uuid4().hex}.sqlite"))
    return Runtime.load(write_model(tmp_path), sempkm_transport=fake.transport, templates_dir=tmp_path, **kw)


def delivery(event_type="object.changed", event=EVENT, command="object.patch") -> bytes:
    return json.dumps(
        {"event_type": event_type, "event_iri": event, "command": command, "timestamp": "2026-11-04T09:30:00+00:00"}
    ).encode()


def receive(rt: Runtime, body) -> tuple[int, dict, str]:
    async def main():
        resp = await rt.receive_webhook(":vendor_changes", body)
        for inst in list(rt.instances.values()):
            await inst.wait()
        return resp

    resp = asyncio.run(main())
    return resp.status_code, json.loads(resp.body), resp.headers["content-type"]


# ── a delivery that starts the subscribed process ────────────────────────────


def test_a_changed_vendor_starts_the_subscribed_process(tmp_path, fake, caplog):
    fake.vendor(ACME, "Acme")
    fake.event(EVENT, ACME)
    rt = runtime(tmp_path, fake)
    with caplog.at_level(logging.INFO):
        status, body, _ = receive(rt, delivery())
    assert status == 202
    assert body["channel"] == str(CHANNEL)
    assert body["event"] == EVENT
    assert body["skipped"] == []
    [started] = body["started"]
    assert (started["process"], started["object"]) == (PROCESS, ACME)
    inst = rt.instances[started["instance"]]
    assert inst.correlation_key == ACME
    assert inst.result["status"] == "complete"
    seams = inst.workflow.data["seams"]
    assert seams["start"] == {"channel": str(CHANNEL), "event": EVENT, "object": ACME}
    assert seams["current"][SHAPE] == {"id": ACME, "data": {"id": ACME, "name": "Acme"}}
    assert rt.store.get_instance(inst.id)["correlation_key"] == ACME
    # the event is read back with all_graphs, the vendor scoped to its class
    event_read, object_read = fake.sparql()
    assert event_read["all_graphs"] is True and EVENT in event_read["query"]
    assert f"<{T}Vendor>" in object_read["query"] and ACME in object_read["query"]
    # logs name the channel, event type, object and instance; the token appears nowhere
    started_line = next(
        r.getMessage() for r in caplog.records if r.name == "seams_runtime.webhooks" and "started" in r.getMessage()
    )
    for part in (str(CHANNEL), "object.changed", EVENT, ACME, inst.id):
        assert part in started_line
    assert TOKEN not in caplog.text and TOKEN not in json.dumps(body)


def test_the_same_event_starts_each_process_once_per_object(tmp_path, fake):
    fake.vendor(ACME, "Acme")
    fake.event(EVENT, ACME)
    rt = runtime(tmp_path, fake)
    _, first, _ = receive(rt, delivery())
    _, again, _ = receive(rt, delivery(command="object.create"))
    assert again["started"] == first["started"]
    assert len(rt.store.list_instances(ACME)) == 1
    # a later change to the same object is a new event: a new instance, same key
    later = "urn:sempkm:event:00000000-0000-4000-8000-000000000002"
    fake.event(later, ACME)
    _, third, _ = receive(rt, delivery(event=later))
    assert third["started"][0]["instance"] != first["started"][0]["instance"]
    assert len(rt.store.list_instances(ACME)) == 2


def test_each_affected_vendor_starts_by_iri_and_others_drop_out(tmp_path, fake):
    fake.vendor(GLOBEX, "Globex")
    fake.vendor(ACME, "Acme")
    fake.vendor(DATA + "Contract/0001", "A contract", cls="Contract")
    fake.event(EVENT, GLOBEX, DATA + "Contract/0001", ACME)
    status, body, _ = receive(runtime(tmp_path, fake), delivery())
    assert status == 202
    assert [s["object"] for s in body["started"]] == [ACME, GLOBEX]


def test_a_vendor_that_fails_the_shape_is_skipped_and_the_others_start(tmp_path, fake, caplog):
    fake.vendor(ACME, "Acme")
    fake.vendor(GLOBEX, None)  # no name: :VendorShape needs one
    fake.event(EVENT, ACME, GLOBEX)
    with caplog.at_level(logging.WARNING):
        status, body, _ = receive(runtime(tmp_path, fake), delivery())
    assert status == 202
    assert [s["object"] for s in body["started"]] == [ACME]
    [skipped] = body["skipped"]
    assert skipped["object"] == GLOBEX and skipped["reason"] == f"fails {SHAPE} at name"
    assert any(GLOBEX in r.getMessage() and "at name" in r.getMessage() for r in caplog.records)


def test_a_subscriber_that_cannot_start_is_listed_with_its_error(tmp_path, fake, monkeypatch):
    fake.vendor(ACME, "Acme")
    fake.event(EVENT, ACME)
    rt = runtime(tmp_path, fake)

    def broken(*_args, **_kw):
        raise RuntimeError("engine down")

    monkeypatch.setattr(rt, "_start_subscribed", broken)
    status, body, _ = receive(rt, delivery())
    assert status == 202
    [started] = body["started"]
    assert started["instance"] is None
    assert started["error"] == {"type": "RuntimeError", "message": "engine down"}


# ── deliveries that start nothing ────────────────────────────────────────────


def test_another_event_type_is_ignored_without_asking_sempkm(tmp_path, fake, caplog):
    with caplog.at_level(logging.INFO):
        status, body, _ = receive(runtime(tmp_path, fake), delivery(event_type="edge.changed"))
    assert status == 202
    assert body["started"] == [] and "edge.changed" in body["ignored"]
    assert fake.sparql() == []
    assert any(r.levelno == logging.INFO and "ignored" in r.getMessage() for r in caplog.records)


def test_an_object_of_a_class_no_channel_accepts_starts_nothing(tmp_path, fake, caplog):
    fake.vendor(DATA + "Contract/0001", "A contract", cls="Contract")
    fake.event(EVENT, DATA + "Contract/0001")
    rt = runtime(tmp_path, fake)
    with caplog.at_level(logging.INFO):
        status, body, _ = receive(rt, delivery())
    assert status == 202
    assert body["started"] == [] and T + "Vendor" in body["ignored"]
    assert rt.store.list_instances() == []
    assert any(r.levelno == logging.INFO and "ignored" in r.getMessage() for r in caplog.records)


def test_an_event_with_no_affected_object_starts_nothing(tmp_path, fake):
    fake.event(EVENT)
    status, body, _ = receive(runtime(tmp_path, fake), delivery())
    assert status == 202 and body["started"] == []
    assert len(fake.sparql()) == 1  # no object read


# ── failures: problem+json naming the channel ────────────────────────────────


def test_an_unverified_event_is_422_and_starts_nothing(tmp_path, fake, caplog):
    """The plan's "bad signature": SemPKM signs nothing, so a forged delivery is
    one whose event SemPKM does not have (ADR-0027 section 6)."""
    fake.vendor(ACME, "Acme")
    rt = runtime(tmp_path, fake)
    with caplog.at_level(logging.WARNING):
        status, body, ctype = receive(rt, delivery())
    assert status == 422 and ctype == "application/problem+json"
    assert body["title"] == "Unverified event"
    assert body["channel"] == str(CHANNEL) and body["event"] == EVENT and body["store"] == PKM
    assert rt.store.list_instances() == []
    assert len(fake.sparql()) == 1  # nothing in the body is trusted: no object read
    assert any(r.levelno == logging.WARNING and "unverified event" in r.getMessage() for r in caplog.records)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"not json", "not JSON"),
        (b"[1, 2]", "not a JSON object"),
        (json.dumps({"event_iri": EVENT}).encode(), "event_type"),
        (json.dumps({"event_type": "object.changed"}).encode(), "event_iri"),
        (json.dumps({"event_type": "object.changed", "event_iri": 7}).encode(), "event_iri"),
        (json.dumps({"event_type": "object.changed", "event_iri": "https://pkm.test/x"}).encode(), "SemPKM event"),
        (
            json.dumps(
                {"event_type": "object.changed", "event_iri": "urn:sempkm:event:x> } } SELECT * { ?s ?p ?o"}
            ).encode(),
            "SemPKM event",
        ),
    ],
)
def test_a_malformed_delivery_is_400(tmp_path, fake, body, reason):
    status, answer, ctype = receive(runtime(tmp_path, fake), body)
    assert status == 400 and ctype == "application/problem+json"
    assert reason in answer["detail"] and answer["channel"] == str(CHANNEL)
    assert fake.requests == []


def _raise(exc):
    def answer(_request):
        raise exc

    return answer


@pytest.mark.parametrize(
    "answer",
    [
        _raise(httpx.ConnectError("refused")),
        _raise(httpx.ReadTimeout("slow")),
        lambda _r: httpx.Response(429, json={"detail": "Rate limit exceeded"}),
        lambda _r: httpx.Response(500, text="boom"),
    ],
    ids=["unreachable", "timeout", "429", "500"],
)
def test_sempkm_unavailable_is_503_naming_the_store(tmp_path, fake, caplog, answer):
    fake.answer = answer
    rt = runtime(tmp_path, fake)
    with caplog.at_level(logging.ERROR):
        status, body, ctype = receive(rt, delivery())
    assert status == 503 and ctype == "application/problem+json"
    assert body["store"] == PKM and body["channel"] == str(CHANNEL) and body["event"] == EVENT
    assert rt.store.list_instances() == []
    assert any(str(CHANNEL) in r.getMessage() and EVENT in r.getMessage() for r in caplog.records)
    assert TOKEN not in caplog.text and TOKEN not in json.dumps(body)


def test_a_token_whose_user_is_no_owner_is_503_naming_the_scope_and_role(tmp_path, fake, caplog):
    fake.owner = False
    fake.event(EVENT, ACME)
    with caplog.at_level(logging.ERROR):
        status, body, _ = receive(runtime(tmp_path, fake), delivery())
    assert status == 503 and body["store"] == PKM
    assert "sparql:read" in body["detail"] and "owner role" in body["detail"]
    assert any("owner role" in r.getMessage() for r in caplog.records)
    assert TOKEN not in caplog.text


def test_an_answer_that_is_not_sparql_results_is_502(tmp_path, fake):
    fake.answer = lambda _r: httpx.Response(200, json={"unexpected": True})
    status, body, ctype = receive(runtime(tmp_path, fake), delivery())
    assert status == 502 and ctype == "application/problem+json" and body["store"] == PKM


def test_a_runtime_with_no_sempkm_client_is_503(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    rt = Runtime.load(write_model(tmp_path), db_path=tmp_path / "o.sqlite", templates_dir=tmp_path)
    status, body, _ = receive(rt, delivery())
    assert status == 503 and body["store"] == PKM and "no SemPKM client" in body["detail"]


def test_a_model_fault_fails_at_load_before_a_store_opens(tmp_path, fake):
    text = MODEL.replace('comm:eventName "object.changed" ;', 'comm:eventName "edge.changed" ;')
    db = tmp_path / "never.sqlite"
    with pytest.raises(ResolutionError) as info:
        Runtime.load(write_model(tmp_path, text), db_path=db, sempkm_transport=fake.transport, templates_dir=tmp_path)
    assert (str(info.value.subject), str(info.value.predicate)) == (str(CHANNEL), str(COMM.eventName))
    assert not db.exists()


# ── the generated route ──────────────────────────────────────────────────────


def test_the_generator_emits_one_post_route_from_the_channel_facts(tmp_path):
    routes = extract_routes(load(write_model(tmp_path)))
    [module] = routes.modules
    [endpoint] = module.endpoints
    assert (endpoint.webhook, endpoint.method, endpoint.path, endpoint.event_name) == (
        True,
        "POST",
        "/sempkm/vendor-changes",
        "object.changed",
    )
    text = render_routes(routes)[module.file_name]
    assert '@router.post("/sempkm/vendor-changes", status_code=202, response_class=JSONResponse)' in text
    assert 'return await runtime.receive_webhook(":vendor_changes", await request.body())' in text
    assert "JSONResponse" in text.split("from seams_runtime")[0]
    compile(text, module.file_name, "exec")


@pytest.mark.parametrize(
    ("old", "new", "subject", "predicate"),
    [
        ('comm:eventName "object.changed" ;', "", CHANNEL, COMM.eventName),
        (
            '"/sempkm/vendor-changes" ]',
            '"/sempkm/{vendor}" ; hydra:mapping [ hydra:variable "vendor" ; hydra:property :id ] ]',
            CHANNEL,
            COMM.path,
        ),
        (":VendorShape seam:storedIn :pkm .", "", URIRef(SHAPE), SEAM.storedIn),
    ],
)
def test_the_generator_names_the_fact_the_runtime_names(tmp_path, old, new, subject, predicate):
    assert old in MODEL
    with pytest.raises(GeneratorError) as info:
        extract_routes(load(write_model(tmp_path, MODEL.replace(old, new, 1))))
    assert (str(info.value.subject), str(info.value.predicate)) == (str(subject), str(predicate))


def test_the_generated_route_starts_the_process_over_http(tmp_path, fake, monkeypatch):
    trig = write_model(tmp_path)
    routes = extract_routes(load(trig))
    [module] = routes.modules
    path = tmp_path / module.file_name
    path.write_text(render_routes(routes)[module.file_name])
    monkeypatch.setenv("SEAMS_MODEL", str(trig))
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "route.sqlite"))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(tmp_path))
    generated = load_routes(path)
    generated.runtime.store.entities.transport = fake.transport
    fake.vendor(ACME, "Acme")
    fake.event(EVENT, ACME)
    app = FastAPI()
    app.include_router(generated.router)
    with TestClient(app) as client:
        r = client.post("/sempkm/vendor-changes", content=delivery(), headers={"content-type": "application/json"})
        assert r.status_code == 202
        [started] = r.json()["started"]
        assert started["object"] == ACME and started["instance"]
        r = client.post("/sempkm/vendor-changes", content=b"{}")
        assert r.status_code == 400 and r.headers["content-type"] == "application/problem+json"
