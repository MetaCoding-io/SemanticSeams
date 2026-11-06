"""An aggregate commits all of its members or none (ADR-0035, M029/S04/T03).

``Store.transaction()`` runs a block of writes on one connection, committed or
rolled back together, on both backends (``make_store`` runs each test on SQLite and on
PostgreSQL; the postgres run skips without ``SEAMS_TEST_POSTGRES_URL``).
``Runtime.write_aggregate`` and the worker write an aggregate's members in one
transaction, and ``Runtime.load`` refuses an aggregate the store cannot commit
atomically. The models are inline: an order aggregate whose members are its own shape
and a line shape of another class.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from rdflib import URIRef

from seams_runtime import AggregateRolledBack, ContractViolation, ResolutionError, Runtime, SQLiteStore, Telemetry
from seams_runtime.worker import Instance, new_state

EX = "https://example.org/orders/"
ORDER = EX + "Order"
ORDER_SHAPE = EX + "OrderShape"
LINE_SHAPE = EX + "LineShape"
NOTE_SHAPE = EX + "NoteShape"
SEAM = "https://w3id.org/seams/seam#"

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix state:  <https://w3id.org/seams/state#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/orders/> .
"""

ONTOLOGY = """
<urn:seams:graph:model:orders_ontology> {
    :orders_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology .
    :Order a owl:Class ; rdfs:label "Order" ; seam:inModel :orders_ontology .
    :Line a owl:Class ; rdfs:label "Line" ; seam:inModel :orders_ontology .
    :Note a owl:Class ; rdfs:label "Note" ; seam:inModel :orders_ontology .
}
<urn:seams:graph:model:orders_data> {
    :orders_data a seam:Model ; seam:notation seam:ShapeGraph .
    :OrderShape a sh:NodeShape ; rdfs:label "Order" ; sh:targetClass :Order ; seam:inModel :orders_data ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
            [ sh:path :title ; sh:name "title" ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
            [ sh:path :status ; sh:name "status" ; sh:datatype xsd:string ; sh:maxCount 1 ] .
    :LineShape a sh:NodeShape ; rdfs:label "Line" ; sh:targetClass :Line ; seam:inModel :orders_data ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
            [ sh:path :sku ; sh:name "sku" ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
            [ sh:path :quantity ; sh:name "quantity" ; sh:datatype xsd:integer ; sh:maxCount 1 ] .
    :NoteShape a sh:NodeShape ; rdfs:label "Note" ; sh:targetClass :Note ; seam:inModel :orders_data ;
        sh:property [ sh:path :text ; sh:name "text" ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] .
}
<urn:seams:graph:model:order_lifecycle> {
    :order_lifecycle a seam:Model , state:StateMachine ; seam:notation seam:Statechart ;
        state:initial :s_open ; state:hasState :s_open .
    :s_open a state:State ; rdfs:label "open" .
}
"""

AGGREGATE = """
    :Order seam:lifecycle :order_lifecycle ;
        seam:aggregateMember :OrderShape , :LineShape .
"""


def trig(seams: str = AGGREGATE) -> str:
    return PREFIXES + ONTOLOGY + f"\n<urn:seams:graph:seams> {{{seams}}}\n"


@pytest.fixture
def model_path(tmp_path):
    path = tmp_path / "orders.trig"
    path.write_text(trig())
    return path


def load(path, store, **kw) -> Runtime:
    return Runtime.load(path, store=store, templates_dir=path.parent, **kw)


ORDER_PAYLOAD = {"title": "Desk"}
LINE_PAYLOAD = {"sku": "D-1", "quantity": "2"}


def fail_on(store, shape: str, *, after_write: bool = False):
    """Make ``store.put_entity`` raise for ``shape``; with ``after_write`` the row is
    written first, so the rollback must also undo the failing write itself."""
    put = store.put_entity

    def failing(id, s, data, **kw):
        if str(s) == shape:
            if after_write:
                put(id, s, data, **kw)
            raise OSError(f"disk full writing {s}")
        return put(id, s, data, **kw)

    store.put_entity = failing


# ── Store.transaction() ──────────────────────────────────────────────────────


def test_a_transaction_commits_its_writes_together(make_store):
    s = make_store()
    with s.transaction():
        s.put_entity("a", LINE_SHAPE, {"sku": "1"})
        row = s.put_entity("b", ORDER_SHAPE, {"title": "x"})
        assert row["data"] == {"title": "x"}  # reads inside the block see its writes
        assert s.get_entity("a") is not None
    assert {r["id"] for r in s.query(LINE_SHAPE)} | {r["id"] for r in s.query(ORDER_SHAPE)} == {"a", "b"}


def test_a_raising_transaction_rolls_every_write_back(make_store):
    s = make_store()
    s.put_entity("kept", LINE_SHAPE, {"sku": "0"})
    with pytest.raises(RuntimeError, match="boom"), s.transaction():
        s.put_entity("a", LINE_SHAPE, {"sku": "1"})
        s.put_entity("kept", LINE_SHAPE, {"sku": "changed"})
        raise RuntimeError("boom")
    assert s.get_entity("a") is None
    assert s.get_entity("kept")["data"] == {"sku": "0"}


def test_a_nested_transaction_joins_the_outer_one(make_store):
    s = make_store()
    with pytest.raises(RuntimeError), s.transaction():
        with s.transaction():
            s.put_entity("a", LINE_SHAPE, {"sku": "1"})
        assert s.get_entity("a") is not None  # the inner exit did not commit or close
        raise RuntimeError("outer fails")
    assert s.get_entity("a") is None


def test_outside_a_transaction_each_operation_commits_alone(make_store):
    s = make_store()
    with pytest.raises(RuntimeError), s.transaction():
        raise RuntimeError("nothing written")
    s.put_entity("a", LINE_SHAPE, {"sku": "1"})  # the store is usable again afterwards
    assert make_store().get_entity("a") is not None


# ── Runtime.write_aggregate ──────────────────────────────────────────────────


def test_write_aggregate_stores_both_members(model_path, make_store, caplog):
    rt = load(model_path, make_store())
    with caplog.at_level(logging.INFO, logger="seams_runtime"):
        rows = rt.write_aggregate(":Order", {":OrderShape": ORDER_PAYLOAD, LINE_SHAPE: LINE_PAYLOAD})
    assert sorted(rows) == [LINE_SHAPE, ORDER_SHAPE]
    order, line = rows[ORDER_SHAPE], rows[LINE_SHAPE]
    assert order["data"] == {"id": order["id"], "title": "Desk", "status": "open"} and order["status"] == "open"
    assert line["data"] == {"id": line["id"], "sku": "D-1", "quantity": "2"} and line["status"] is None
    assert [r["id"] for r in rt.query(":OrderShape")] == [order["id"]]
    assert [r["id"] for r in rt.query(":LineShape")] == [line["id"]]
    assert f"committed aggregate {ORDER}: {LINE_SHAPE} {line['id']}, {ORDER_SHAPE} {order['id']}" in caplog.text


def test_a_failing_second_write_rolls_back_the_first(model_path, make_store, caplog):
    store = make_store()
    rt = load(model_path, store)
    fail_on(store, ORDER_SHAPE, after_write=True)  # LineShape sorts first, so OrderShape is the second write
    with caplog.at_level(logging.ERROR), pytest.raises(AggregateRolledBack) as raised:
        rt.write_aggregate(":Order", {":OrderShape": ORDER_PAYLOAD, ":LineShape": LINE_PAYLOAD})
    error = raised.value
    assert str(error) == (
        f"aggregate {ORDER} rolled back: writing {ORDER_SHAPE} failed (OSError: disk full writing {ORDER_SHAPE})"
    )
    assert (error.aggregate, error.shape, error.http_status) == (ORDER, ORDER_SHAPE, 500)
    assert isinstance(error.__cause__, OSError)
    assert error.to_dict()["cause"] == f"OSError: disk full writing {ORDER_SHAPE}"
    assert rt.query(":LineShape") == [] and rt.query(":OrderShape") == []
    assert f"aggregate {ORDER} rolled back: writing {ORDER_SHAPE} failed" in caplog.text
    assert "Desk" not in caplog.text and "D-1" not in caplog.text  # never a payload value


def test_the_cause_status_is_the_rollback_status(model_path, tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite")
    rt = load(model_path, store)
    put = store.put_entity

    def unavailable(id, s, data, **kw):
        if str(s) == ORDER_SHAPE:
            from seams_runtime import StoreUnavailable

            raise StoreUnavailable(EX + "db", "timed out")
        return put(id, s, data, **kw)

    store.put_entity = unavailable
    with pytest.raises(AggregateRolledBack) as raised:
        rt.write_aggregate(":Order", {":OrderShape": ORDER_PAYLOAD, ":LineShape": LINE_PAYLOAD})
    assert raised.value.http_status == 503


def test_an_invalid_payload_writes_nothing(model_path, tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite")
    rt = load(model_path, store)
    with pytest.raises(ContractViolation) as raised:
        rt.write_aggregate(":Order", {":OrderShape": {}, ":LineShape": LINE_PAYLOAD})
    assert raised.value.shape == ORDER_SHAPE
    assert rt.query(":LineShape") == []


def test_a_shape_outside_the_aggregate_is_refused(model_path, tmp_path):
    rt = load(model_path, SQLiteStore(tmp_path / "s.sqlite"))
    with pytest.raises(ResolutionError) as raised:
        rt.write_aggregate(":Order", {":OrderShape": ORDER_PAYLOAD, ":NoteShape": {"text": "hi"}})
    assert str(raised.value) == (
        f"cannot resolve {NOTE_SHAPE}: missing {SEAM}aggregateMember "
        f"(not a member of {ORDER}; its members are {[LINE_SHAPE, ORDER_SHAPE]})"
    )
    assert rt.query(":OrderShape") == []


def test_no_payloads_and_a_non_aggregate_are_refused(model_path, tmp_path):
    rt = load(model_path, SQLiteStore(tmp_path / "s.sqlite"))
    with pytest.raises(ResolutionError) as raised:
        rt.write_aggregate(":Order", {})
    assert str(raised.value) == f"cannot resolve {ORDER}: missing {SEAM}aggregateMember (no member payloads to write)"
    with pytest.raises(ResolutionError) as raised:
        rt.write_aggregate(":Note", {":NoteShape": {"text": "hi"}})
    assert str(raised.value) == (
        f"cannot resolve {EX}Note: missing {SEAM}aggregateMember "
        "(names no member shapes, so it declares no transaction boundary)"
    )


# ── the worker: one element writing two members ──────────────────────────────


def worker_and_instance(rt: Runtime):
    instance = Instance("i1", "c1", URIRef(EX + "p"), SimpleNamespace(data={"seams": new_state(EX + "p", "c1")}))
    st = instance.state
    st["current"][ORDER_SHAPE] = {"id": None, "data": {"title": "Desk"}}
    st["current"][LINE_SHAPE] = {"id": None, "data": {"sku": "D-1"}}
    return rt.worker, instance


def test_the_worker_commits_an_elements_member_writes_together(model_path, make_store):
    rt = load(model_path, make_store())
    worker, instance = worker_and_instance(rt)
    row: dict = {}
    asyncio.run(worker._write(instance, EX + "t", [URIRef(ORDER_SHAPE), URIRef(LINE_SHAPE)], row))
    [order] = rt.store.query(ORDER_SHAPE, correlation_key="c1")
    [line] = rt.store.query(LINE_SHAPE, correlation_key="c1")
    assert row["writes"] == [line["id"], order["id"]]  # member-IRI order
    assert order["instance_id"] == "i1" and order["status"] == "open"
    assert instance.state["written"] == {LINE_SHAPE: [line["id"]], ORDER_SHAPE: [order["id"]]}


def test_a_worker_rollback_keeps_neither_entity_nor_their_state(model_path, make_store):
    store = make_store()
    rt = load(model_path, store)
    worker, instance = worker_and_instance(rt)
    fail_on(store, ORDER_SHAPE)
    with pytest.raises(AggregateRolledBack, match=f"writing {ORDER_SHAPE} failed"):
        asyncio.run(worker._write(instance, EX + "t", [URIRef(ORDER_SHAPE), URIRef(LINE_SHAPE)], {}))
    assert store.query(LINE_SHAPE) == [] and store.query(ORDER_SHAPE) == []
    st = instance.state
    assert st["written"] == {} and st["status"] == {} and st["history"] == {}
    assert st["current"][LINE_SHAPE]["id"] is None


def test_writes_of_one_member_or_no_aggregate_use_no_transaction(model_path, tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite")
    rt = load(model_path, store)
    worker, instance = worker_and_instance(rt)
    instance.state["current"][NOTE_SHAPE] = {"id": None, "data": {"text": "hi"}}

    def no_transaction():
        raise AssertionError("a single write needs no transaction")

    store.transaction = no_transaction  # type: ignore[method-assign]
    row: dict = {}
    asyncio.run(worker._write(instance, EX + "t", [URIRef(NOTE_SHAPE), URIRef(ORDER_SHAPE)], row))
    assert len(row["writes"]) == 2


def test_the_worker_aggregate_commit_is_one_span(model_path, tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    store = SQLiteStore(tmp_path / "s.sqlite")
    rt = load(model_path, store, telemetry=Telemetry(provider.get_tracer("test")))
    worker, instance = worker_and_instance(rt)
    asyncio.run(worker._write(instance, EX + "t", [URIRef(ORDER_SHAPE), URIRef(LINE_SHAPE)], {}))
    fail_on(store, LINE_SHAPE)
    with pytest.raises(AggregateRolledBack):
        rt.write_aggregate(":Order", {":OrderShape": ORDER_PAYLOAD, ":LineShape": LINE_PAYLOAD})
    provider.shutdown()
    ok, failed = exporter.get_finished_spans()
    assert ok.name == failed.name == "seams.aggregate.commit"
    assert dict(ok.attributes) == {
        "seams.aggregate.iri": ORDER,
        "seams.aggregate.members": (LINE_SHAPE, ORDER_SHAPE),
        "seams.store.kind": "sqlite",
        "seams.process.iri": EX + "p",
        "seams.instance.id": "i1",
        "seams.correlation_key": "c1",
    }
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.status.description.startswith("AggregateRolledBack")
    assert failed.attributes["seams.error.type"] == "AggregateRolledBack"
    assert "seams.instance.id" not in failed.attributes


# ── Runtime.load refuses what the store cannot commit atomically ─────────────

PKM = """
<urn:seams:graph:model:orders_architecture> {
    :op a comm:Operation ; rdfs:label "Op" ; seam:writes :OrderShape , :LineShape .
    :pkm a arch:Container ; rdfs:label "PKM" ; deploy:storeKind deploy:SemPKM .
    :api a arch:Container ; rdfs:label "API" ; seam:exposes :op ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ] ;
            deploy:binding [ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm> ;
                             deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ] ] .
}
"""


def test_load_refuses_a_multi_member_aggregate_in_sempkm(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMPKM_URL", raising=False)  # refused before the SemPKM binding is read
    path = tmp_path / "orders.trig"
    stored = AGGREGATE + "    :OrderShape seam:storedIn :pkm .\n    :LineShape seam:storedIn :pkm .\n"
    path.write_text(trig(stored) + PKM)
    with pytest.raises(ResolutionError) as raised:
        load(path, SQLiteStore(tmp_path / "s.sqlite"))
    assert str(raised.value) == (
        f"cannot resolve {ORDER}: missing {SEAM}aggregateMember ({LINE_SHAPE} is stored in the deploy:SemPKM "
        f"store {EX}pkm, which cannot commit more than one entity of an aggregate atomically (ADR-0035); "
        f"its members are {[LINE_SHAPE, ORDER_SHAPE]})"
    )


def test_load_accepts_a_one_member_aggregate_in_sempkm(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMPKM_URL", "http://pkm.test:8000")
    monkeypatch.setenv("SEMPKM_TOKEN", "t0ken")
    path = tmp_path / "orders.trig"
    one = ":Order seam:lifecycle :order_lifecycle ; seam:aggregateMember :OrderShape .\n"
    stored = one + "    :OrderShape seam:storedIn :pkm .\n    :LineShape seam:storedIn :pkm .\n"
    path.write_text(trig(stored) + PKM)
    rt = load(path, SQLiteStore(tmp_path / "s.sqlite"))
    assert [str(a.iri) for a in rt.model.aggregates] == [ORDER]


def test_load_refuses_members_in_two_stores(tmp_path):
    path = tmp_path / "orders.trig"
    two = """
<urn:seams:graph:model:orders_architecture> {
    :op a comm:Operation ; rdfs:label "Op" ; seam:writes :OrderShape .
    :api a arch:Container ; rdfs:label "API" ; seam:exposes :op .
    :db1 a arch:Container ; rdfs:label "DB 1" ; deploy:storeKind deploy:SQLite .
    :db2 a arch:Container ; rdfs:label "DB 2" ; deploy:storeKind deploy:SQLite .
}
"""
    stored = AGGREGATE + "    :OrderShape seam:storedIn :db1 .\n    :LineShape seam:storedIn :db2 .\n"
    path.write_text(trig(stored) + two)
    with pytest.raises(ResolutionError) as raised:
        load(path, SQLiteStore(tmp_path / "s.sqlite"))
    assert str(raised.value) == (
        f"cannot resolve {ORDER}: missing {SEAM}aggregateMember (its members are stored in more than one store, "
        f"{[EX + 'db1', EX + 'db2']}; an aggregate commits in one store transaction (ADR-0035))"
    )


def test_a_model_without_aggregates_loads_as_before(tmp_path):
    path = tmp_path / "orders.trig"
    path.write_text(trig(":Order seam:lifecycle :order_lifecycle .\n"))
    rt = load(path, SQLiteStore(tmp_path / "s.sqlite"))
    assert list(rt.model.aggregates) == []
