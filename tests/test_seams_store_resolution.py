"""ModelGraph.store_plan (M011/S03): the store the runtime uses, from graph facts (ADR-0011)."""

from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from seams import DEPLOY, SEAM, SUPPORTED_STORE_KINDS, ModelGraph, ResolutionError, StorePlan

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"
CH07 = ROOT / "examples/expenses/chapter-07/expenses.trig"
CH08 = ROOT / "examples/expenses/chapter-08/expenses.trig"

C = "https://example.org/chat/"
X = "https://example.org/expenses/"
T = "https://example.org/store/"

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/store/> .
"""

# A runtime container (:api executes :p and exposes :op, which writes
# :MessageShape) plus the pieces each case adds.
BASE = """
    :p a proc:Process ; rdfs:label "P" .
    :op a comm:Operation ; rdfs:label "Op" .
    :MessageShape a sh:NodeShape ; rdfs:label "Message" .
    :op seam:writes :MessageShape .
    :api a arch:Container ; rdfs:label "API" ;
        seam:executes :p ;
        seam:exposes :op {binding} .
"""


def binding(*stores: str, key: str = "DB_URL") -> str:
    """deploy:configuration on :api with one connecting binding per store."""
    if not stores:
        return ""
    parts = " ;\n".join(
        f'deploy:binding [ deploy:key "{key}{i or ""}" ; deploy:value "x" ; deploy:connectsTo :{s} ]'
        for i, s in enumerate(stores)
    )
    return f"; deploy:configuration [ a deploy:Configuration ; {parts} ]"


def plan_of(tmp_path: Path, extra: str, *stores: str, base: str = BASE) -> StorePlan:
    path = tmp_path / "model.trig"
    path.write_text(f"{PREFIXES}\n:g {{\n{base.format(binding=binding(*stores))}\n{extra}\n}}\n")
    return ModelGraph(path).store_plan()


def raises(tmp_path: Path, extra: str, *stores: str, base: str = BASE) -> ResolutionError:
    with pytest.raises(ResolutionError) as info:
        plan_of(tmp_path, extra, *stores, base=base)
    return info.value


PG = ":db a arch:Container ; deploy:storeKind deploy:PostgreSQL ."
STORED = ":MessageShape seam:storedIn :db ."


# ── the example models ──────────────────────────────────────────────────────


def test_chat_app_resolves_its_postgres_store():
    assert ModelGraph(CHAT).store_plan() == StorePlan(
        DEPLOY.PostgreSQL, URIRef(C + "message_db"), URIRef(C + "chat_api"), "DB_URL", declared=True
    )


def test_expenses_chapter_08_resolves_its_postgres_store():
    assert ModelGraph(CH08).store_plan() == StorePlan(
        DEPLOY.PostgreSQL, URIRef(X + "expense_db"), URIRef(X + "expense_api"), "DATABASE_URL", declared=True
    )


def test_expenses_chapter_07_declares_no_store_and_gets_embedded_sqlite():
    assert ModelGraph(CH07).store_plan() == StorePlan(DEPLOY.SQLite, None, None, None, declared=False)


def test_supported_kinds_and_exports():
    assert SUPPORTED_STORE_KINDS == (DEPLOY.PostgreSQL, DEPLOY.SQLite)
    assert seams.StorePlan is StorePlan


# ── the views the plan reads ────────────────────────────────────────────────


def test_views_expose_the_store_facts():
    model = seams.load(CHAT)
    api = model.architecture.containers().by_iri(":chat_api")
    db = model.architecture.containers().by_iri(":message_db")
    [conn] = api.connecting_bindings
    assert (conn.key, conn.connects_to) == ("DB_URL", db)
    assert conn.kinds == (DEPLOY.secretRef,)  # connectsTo is not a value source
    assert db.store_kinds == (DEPLOY.PostgreSQL,)
    assert api.store_kinds == ()
    assert db.stored_shapes.iris() == (URIRef(C + "ConversationShape"), URIRef(C + "MessageShape"))
    assert model.shapes.by_iri(":MessageShape").stored_in.iris() == (db.iri,)
    assert all(b.connects_to is None for b in db.bindings)


# ── fixtures that resolve ───────────────────────────────────────────────────


def test_declared_sqlite_store_resolves_without_a_key(tmp_path: Path):
    extra = ":db a arch:Container ; deploy:storeKind deploy:SQLite .\n" + STORED
    assert plan_of(tmp_path, extra) == StorePlan(DEPLOY.SQLite, URIRef(T + "db"), None, None, declared=True)


def test_inline_postgres_store_resolves(tmp_path: Path):
    plan = plan_of(tmp_path, f"{PG}\n{STORED}", "db")
    assert plan == StorePlan(DEPLOY.PostgreSQL, URIRef(T + "db"), URIRef(T + "api"), "DB_URL", declared=True)


# ── the error contract (ADR-0011): each row names subject and predicate ────


def test_store_without_a_store_kind(tmp_path: Path):
    err = raises(tmp_path, f":db a arch:Container .\n{STORED}", "db")
    assert (err.subject, err.predicate) == (T + "db", str(DEPLOY.storeKind))
    assert "found none" in err.detail


def test_store_with_two_store_kinds(tmp_path: Path):
    extra = f":db a arch:Container ; deploy:storeKind deploy:PostgreSQL , deploy:SQLite .\n{STORED}"
    err = raises(tmp_path, extra, "db")
    assert (err.subject, err.predicate) == (T + "db", str(DEPLOY.storeKind))


def test_unsupported_store_kind(tmp_path: Path):
    extra = f":db a arch:Container ; deploy:storeKind deploy:MongoDB .\n{STORED}"
    err = raises(tmp_path, extra, "db")
    assert (err.subject, err.predicate) == (T + "db", str(DEPLOY.storeKind))
    assert "unsupported" in err.detail


def test_postgres_store_without_a_connecting_binding(tmp_path: Path):
    err = raises(tmp_path, f"{PG}\n{STORED}")
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.connectsTo))


def test_postgres_store_with_no_runtime_container_names_the_store(tmp_path: Path):
    base = ':MessageShape a sh:NodeShape ; rdfs:label "Message" .{binding}'
    err = raises(tmp_path, f"{PG}\n{STORED}", base=base)
    assert (err.subject, err.predicate) == (T + "db", str(DEPLOY.connectsTo))


def test_written_shape_with_no_stored_in(tmp_path: Path):
    err = raises(tmp_path, PG, "db")
    assert (err.subject, err.predicate) == (T + "MessageShape", str(SEAM.storedIn))


def test_written_shape_stored_elsewhere(tmp_path: Path):
    extra = f"{PG}\n:other a arch:Container ; deploy:storeKind deploy:PostgreSQL .\n:MessageShape seam:storedIn :other ."
    err = raises(tmp_path, extra, "db")
    assert (err.subject, err.predicate) == (T + "MessageShape", str(SEAM.storedIn))


def test_one_container_bound_to_two_stores(tmp_path: Path):
    extra = f"{PG}\n:other a arch:Container ; deploy:storeKind deploy:PostgreSQL .\n{STORED}"
    err = raises(tmp_path, extra, "db", "other")
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.connectsTo))


def test_two_runtime_containers_connecting_to_different_stores(tmp_path: Path):
    extra = f"""{PG}
    :other a arch:Container ; deploy:storeKind deploy:PostgreSQL .
    {STORED}
    :q a proc:Process ; rdfs:label "Q" .
    :worker a arch:Container ; rdfs:label "Worker" ; seam:executes :q ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "DB_URL" ; deploy:value "x" ; deploy:connectsTo :other ] ] .
    """
    err = raises(tmp_path, extra, "db")
    assert (err.subject, err.predicate) == (T + "worker", str(DEPLOY.connectsTo))
    assert "one store per model" in err.detail


def test_written_shapes_split_across_stores_without_a_connection(tmp_path: Path):
    extra = f"""
    :db a arch:Container ; deploy:storeKind deploy:SQLite .
    :other a arch:Container ; deploy:storeKind deploy:SQLite .
    :NoteShape a sh:NodeShape ; rdfs:label "Note" .
    :op seam:writes :NoteShape .
    {STORED}
    :NoteShape seam:storedIn :other .
    """
    err = raises(tmp_path, extra)
    assert (err.subject, err.predicate) == (T + "NoteShape", str(SEAM.storedIn))
