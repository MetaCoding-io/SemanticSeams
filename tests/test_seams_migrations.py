"""``seams_cli.migrations``: SQL per relational store kind, or a refusal, for breaking stored changes (M031/S03, ADR-0041).

Each test writes a small OLD and NEW TriG pair into tmp_path. ``:ItemShape`` is
seam:storedIn a SQLite container; the cases change its property shapes.
"""

import sqlite3
from pathlib import Path

import pytest
from seams import ModelGraph
from seams_cli.diff import diff_loaded, load_model
from seams_cli.migrations import Migration, Refusal, migrations

from seams_runtime.contracts import to_rdf
from seams_runtime.store import SQLiteStore

EX = "https://example.org/m/"
ITEM_IRI = EX + "ItemShape"
PREFIXES = """\
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/m/> .
"""

DB = ":db a arch:Container ; deploy:storeKind deploy:SQLite .\n"
PKM = ":pkm a arch:Container ; deploy:storeKind deploy:SemPKM .\n"
NAME = "sh:property [ sh:path :name ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ]"
NOTE = 'sh:property [ sh:path :note ; sh:name "remark" ; sh:datatype xsd:string ; sh:maxCount 3 ]'


def _item(*props: str, store: str = ":db", shape: str = ":ItemShape") -> str:
    body = " ;\n    ".join((f"{shape} a sh:NodeShape", f"seam:storedIn {store}", *props))
    return body + " .\n" + DB + PKM


def _trig(body: str) -> str:
    return PREFIXES + "<urn:seams:graph:shapes> {\n" + body + "\n}\n"


def _models(tmp_path: Path, old: str, new: str):
    (tmp_path / "old.trig").write_text(_trig(old), encoding="utf-8")
    (tmp_path / "new.trig").write_text(_trig(new), encoding="utf-8")
    return load_model(tmp_path / "old.trig"), load_model(tmp_path / "new.trig")


def _migrations(tmp_path: Path, old: str, new: str) -> list[Migration | Refusal]:
    a, b = _models(tmp_path, old, new)
    return migrations(a, b, diff_loaded(a, b))


def _required(default: str = "") -> str:
    extra = f" ; sh:defaultValue {default}" if default else ""
    return f"sh:property [ sh:path :count ; sh:datatype xsd:integer ; sh:minCount 1{extra} ]"


def test_removed_property_drops_its_json_key_for_both_kinds(tmp_path):
    found = _migrations(tmp_path, _item(NAME, NOTE), _item(NAME))
    where = f"WHERE shape = '{ITEM_IRI}';"
    assert found == [
        Migration("postgresql", ITEM_IRI, EX + "note", f"UPDATE entities SET data = data - 'remark' {where}"),
        Migration(
            "sqlite", ITEM_IRI, EX + "note", f"UPDATE entities SET data = json_remove(data, '$.\"remark\"') {where}"
        ),
    ]


def test_defaulted_required_add_fills_rows_that_lack_it(tmp_path):
    found = _migrations(tmp_path, _item(NAME), _item(NAME, _required("7")))
    assert found == [
        Migration(
            "postgresql",
            ITEM_IRI,
            EX + "count",
            "UPDATE entities SET data = jsonb_set(data, ARRAY['count'], '7'::jsonb) "
            f"WHERE shape = '{ITEM_IRI}' AND NOT (data ? 'count');",
        ),
        Migration(
            "sqlite",
            ITEM_IRI,
            EX + "count",
            "UPDATE entities SET data = json_set(data, '$.\"count\"', json('7')) "
            f"WHERE shape = '{ITEM_IRI}' AND json_type(data, '$.\"count\"') IS NULL;",
        ),
    ]


def test_required_add_without_default_is_refused_naming_shape_and_path(tmp_path):
    found = _migrations(tmp_path, _item(NAME), _item(NAME, _required()))
    assert found == [
        Refusal("property-added", ITEM_IRI, EX + "count", "no sh:defaultValue to fill the rows that lack it")
    ]


def test_two_defaults_are_refused_naming_sh_default_value(tmp_path):
    two = "sh:property [ sh:path :count ; sh:datatype xsd:integer ; sh:minCount 1 ; sh:defaultValue 1, 2 ]"
    [refusal] = _migrations(tmp_path, _item(NAME), _item(NAME, two))
    assert isinstance(refusal, Refusal)
    assert "sh:defaultValue must be exactly one literal" in refusal.reason


def test_sempkm_stored_shape_is_refused(tmp_path):
    found = _migrations(tmp_path, _item(NAME, NOTE, store=":pkm"), _item(NAME, store=":pkm"))
    assert found == [
        Refusal(
            "property-removed",
            ITEM_IRI,
            EX + "note",
            f"stored in the SemPKM store {EX}pkm; SemPKM data is not rewritten by SQL",
        )
    ]


def test_shape_moved_into_sempkm_is_refused(tmp_path):
    [refusal] = _migrations(tmp_path, _item(NAME, NOTE), _item(NAME, store=":pkm"))
    assert isinstance(refusal, Refusal) and "SemPKM" in refusal.reason


def test_removed_shape_is_refused_with_no_path(tmp_path):
    found = _migrations(tmp_path, _item(NAME), DB)
    assert [(r.kind, r.shape, r.path) for r in found] == [("shape-removed", ITEM_IRI, "-")]
    assert isinstance(found[0], Refusal) and "deleting them is not mechanical" in found[0].reason


def test_tightened_datatype_and_cardinality_are_refused(tmp_path):
    tight = NAME.replace("xsd:string", "xsd:integer")
    note = NOTE.replace("sh:maxCount 3", "sh:maxCount 1")
    found = _migrations(tmp_path, _item(NAME, NOTE), _item(tight, note))
    assert [(r.kind, r.path) for r in found] == [("datatype-changed", EX + "name"), ("max-count-changed", EX + "note")]
    assert all(isinstance(r, Refusal) and "a rule the model does not state" in r.reason for r in found)


def test_unstored_shape_and_compatible_changes_give_nothing(tmp_path):
    unstored = f":ItemShape a sh:NodeShape ;\n    {NAME} ;\n    {NOTE} .\n"
    assert _migrations(tmp_path, unstored, unstored.replace(f" ;\n    {NOTE}", "")) == []
    loose = NOTE.replace("sh:maxCount 3", "sh:maxCount 5")
    assert _migrations(tmp_path, _item(NAME, NOTE), _item(NAME, loose)) == []


def test_written_shape_without_store_has_rows(tmp_path):
    written = f":ItemShape a sh:NodeShape ;\n    {NAME} ;\n    {NOTE} .\n:op seam:writes :ItemShape .\n"
    found = _migrations(tmp_path, written, written.replace(f" ;\n    {NOTE}", ""))
    assert [(r.kind, r.path) for r in found] == [("postgresql", EX + "note"), ("sqlite", EX + "note")]


def test_renamed_shape_rewrites_the_rows_under_the_old_iri(tmp_path):
    new = _item(NAME, shape=":ThingShape") + ":ThingShape owl:sameAs :ItemShape .\n"
    found = _migrations(tmp_path, _item(NAME, NOTE), new)
    assert {r.shape for r in found} == {ITEM_IRI}
    assert all(isinstance(r, Migration) and f"shape = '{ITEM_IRI}'" in r.sql for r in found)


def test_quote_in_shape_iri_is_doubled(tmp_path):
    shape = "<https://example.org/m/Item's>"
    found = _migrations(tmp_path, _item(NAME, NOTE, shape=shape), _item(NAME, shape=shape))
    assert [r.shape for r in found] == [EX + "Item's"] * 2
    assert all(isinstance(r, Migration) and "WHERE shape = 'https://example.org/m/Item''s';" in r.sql for r in found)


def test_output_is_sorted_and_deterministic(tmp_path):
    old = _item(NAME, NOTE) + _item(NAME, NOTE, shape=":AlphaShape")
    new = _item(NAME, _required()) + _item(NAME, shape=":AlphaShape")
    first = _migrations(tmp_path, old, new)
    assert first == _migrations(tmp_path, old, new)
    assert [(r.shape, r.path, r.kind) for r in first] == sorted((r.shape, r.path, r.kind) for r in first)
    assert [type(r).__name__ for r in first] == ["Migration", "Migration", "Refusal", "Migration", "Migration"]


@pytest.mark.parametrize(
    ("datatype", "default"),
    [("xsd:integer", "7"), ("xsd:boolean", "true"), ("xsd:string", '"it\'s new"'), ("xsd:decimal", "2.50")],
)
def test_sqlite_sql_rewrites_a_real_store_like_the_runtime_fills_defaults(tmp_path, datatype, default):
    added = f"sh:property [ sh:path :extra ; sh:datatype {datatype} ; sh:minCount 1 ; sh:defaultValue {default} ]"
    old, new = _models(tmp_path, _item(NAME, NOTE), _item(NAME, added))
    found = migrations(old, new, diff_loaded(old, new))
    sqlite = [r.sql for r in found if isinstance(r, Migration) and r.kind == "sqlite"]
    assert len(sqlite) == 2, found

    store = SQLiteStore(tmp_path / "seams.db")
    store.put_entity("a", ITEM_IRI, {"name": "a", "remark": "x"})
    store.put_entity("b", ITEM_IRI, {"name": "b", "extra": "kept"})
    store.put_entity("c", EX + "OtherShape", {"remark": "untouched"})

    con = sqlite3.connect(tmp_path / "seams.db")
    with con:
        for statement in sqlite:
            con.execute(statement)
    con.close()

    store = SQLiteStore(tmp_path / "seams.db")
    filled = to_rdf(ModelGraph(tmp_path / "new.trig"), ITEM_IRI, {"name": "a"})[2]["extra"]
    assert store.get_entity("a")["data"] == {"name": "a", "extra": filled}
    assert store.get_entity("b")["data"] == {"name": "b", "extra": "kept"}
    assert store.get_entity("c")["data"] == {"remark": "untouched"}
