"""The Store contract, run on both backends (M011/S03).

Every test taking ``make_store`` runs once on ``SQLiteStore`` and once on
``PostgresStore``; the postgres run skips without ``SEAMS_TEST_POSTGRES_URL``
(see tests/conftest.py).
"""

import asyncio
import logging
import os

import psycopg
import pytest

from seams_runtime import PostgresStore, SQLiteStore, Store
from seams_runtime.store import redact

CHAT = "https://example.org/chat/"
PROCESS = ":send_message_process"
SHAPE = CHAT + "MessageShape"
TASK = CHAT + "approve_task"


def _task(task=TASK, ck="c1", bpmn_id="Approve"):
    return {"task": task, "bpmn_id": bpmn_id, "process": CHAT + "expense_process", "correlation_key": ck}


# ── interface ────────────────────────────────────────────────────────────────


def test_store_is_the_backend_interface(make_store, store_backend):
    s = make_store()
    assert isinstance(s, Store)
    assert s.kind == {"sqlite": "sqlite", "postgres": "postgresql"}[store_backend]
    assert s.location in repr(s)


# ── workflow state ───────────────────────────────────────────────────────────


def test_state_save_load_and_replace(make_store):
    s = make_store()
    s.save_state("a", PROCESS, '{"x":1}', correlation_key="c1", status="running")
    assert s.load_state("a") == '{"x":1}'
    s.save_state("a", PROCESS, '{"x":3}', correlation_key="c1", status="done")
    assert s.load_state("a") == '{"x":3}'
    meta = s.get_instance("a")
    assert meta is not None
    assert set(meta) == {"instance_id", "process", "correlation_key", "status", "updated"}
    assert (meta["instance_id"], meta["process"], meta["correlation_key"], meta["status"]) == (
        "a",
        PROCESS,
        "c1",
        "done",
    )
    assert isinstance(meta["updated"], float)


def test_missing_instance(make_store):
    s = make_store()
    assert s.get_instance("missing") is None
    with pytest.raises(LookupError, match="missing"):
        s.load_state("missing")


def test_state_survives_reopening_the_store(make_store):
    make_store("state.sqlite").save_state("a", PROCESS, "{}", correlation_key="c1", status="running")
    assert make_store("state.sqlite").load_state("a") == "{}"
    assert make_store("other.sqlite").get_instance("a") is None


def test_list_instances_orders_by_update_and_filters_by_correlation_key(make_store):
    s = make_store()
    s.save_state("a", PROCESS, '{"x":1}', correlation_key="c1", status="running")
    s.save_state("b", PROCESS, '{"x":2}', correlation_key="c2", status="done")
    s.save_state("c", PROCESS, '{"x":4}', correlation_key="c1", status="running")
    s.save_state("a", PROCESS, '{"x":3}', correlation_key="c1", status="done")
    assert [r["instance_id"] for r in s.list_instances()] == ["b", "c", "a"]
    assert [r["instance_id"] for r in s.list_instances(correlation_key="c1")] == ["c", "a"]
    assert s.list_instances(correlation_key="nope") == []
    assert all("state" not in r and "seq" not in r for r in s.list_instances())


# ── entities ─────────────────────────────────────────────────────────────────


def test_put_entity_update_keeps_created(make_store):
    s = make_store()
    first = s.put_entity("m1", SHAPE, {"content": "a"}, correlation_key="c1", instance_id="i1", status="sent")
    assert first == {
        "id": "m1",
        "shape": SHAPE,
        "correlation_key": "c1",
        "instance_id": "i1",
        "data": {"content": "a"},
        "status": "sent",
        "created": first["created"],
    }
    s.put_entity("m2", SHAPE, {"content": "b"})
    updated = s.put_entity("m1", SHAPE, {"content": "a2"}, correlation_key="c1", status="streaming")
    assert updated["created"] == first["created"]
    assert updated["data"] == {"content": "a2"} and updated["status"] == "streaming"
    assert updated["instance_id"] is None
    assert [e["id"] for e in s.query(SHAPE)] == ["m1", "m2"]
    assert s.get_entity("m1") == updated
    assert s.get_entity("missing") is None


def test_entity_data_round_trips_in_sorted_key_order(make_store):
    s = make_store()
    data = {"zeta": 1, "a": [1, 2.5, None], "mid": {"y": True, "b": "x"}, "longer_key": "é"}
    stored = s.put_entity("e1", SHAPE, data)
    assert stored["data"] == data
    assert list(stored["data"]) == sorted(data)
    assert list(stored["data"]["mid"]) == ["b", "y"]


def test_query_filters_by_correlation_key_and_fields(make_store):
    s = make_store()
    s.put_entity("m1", SHAPE, {"role": "user", "content": "a"}, correlation_key="c1")
    s.put_entity("m2", SHAPE, {"role": "assistant", "content": "b"}, correlation_key="c1")
    s.put_entity("m3", SHAPE, {"role": "user", "content": "c"}, correlation_key="c2")
    s.put_entity("x1", CHAT + "ConversationShape", {"title": "t"}, correlation_key="c1")
    assert [e["id"] for e in s.query(SHAPE)] == ["m1", "m2", "m3"]
    assert [e["id"] for e in s.query(SHAPE, correlation_key="c1")] == ["m1", "m2"]
    assert [e["id"] for e in s.query(SHAPE, correlation_key="c1", role="user")] == ["m1"]
    assert [e["id"] for e in s.query(SHAPE, role="user")] == ["m1", "m3"]
    assert s.query(SHAPE, correlation_key="nope") == []
    assert s.query(SHAPE, no_such_field="x") == []
    assert s.query(CHAT + "NoShape") == []
    assert all("seq" not in e for e in s.query(SHAPE))


def test_query_field_filters_compare_json_values(make_store):
    s = make_store()
    s.put_entity("n1", SHAPE, {"n": 1, "flag": None})
    s.put_entity("n2", SHAPE, {"n": "1"})
    assert [e["id"] for e in s.query(SHAPE, n=1)] == ["n1"]
    assert [e["id"] for e in s.query(SHAPE, n="1")] == ["n2"]
    assert [e["id"] for e in s.query(SHAPE, flag=None)] == ["n1"]


def test_store_is_safe_across_threads(make_store):
    s = make_store()

    async def main():
        await asyncio.gather(
            *(asyncio.to_thread(s.put_entity, f"m{i}", SHAPE, {"n": i}, correlation_key="c") for i in range(20))
        )

    asyncio.run(main())
    assert sorted(e["data"]["n"] for e in s.query(SHAPE, correlation_key="c")) == list(range(20))


# ── open user tasks ──────────────────────────────────────────────────────────


def test_replace_user_tasks_keeps_created_and_clears(make_store):
    s = make_store()
    s.replace_user_tasks("i1", [_task()])
    [first] = s.list_user_tasks()
    assert set(first) == {"instance_id", "task", "bpmn_id", "process", "correlation_key", "created"}
    s.replace_user_tasks("i1", [_task(), _task(task=CHAT + "review_task", bpmn_id="Review")])
    rows = s.list_user_tasks()
    assert [r["task"] for r in rows] == [TASK, CHAT + "review_task"]
    assert rows[0]["created"] == first["created"]
    s.replace_user_tasks("i1", [])
    assert s.list_user_tasks() == []


def test_replace_user_tasks_touches_only_its_instance(make_store):
    s = make_store()
    s.replace_user_tasks("i1", [_task(ck="c1")])
    s.replace_user_tasks("i2", [_task(ck="c2")])
    s.replace_user_tasks("i1", [])
    assert [r["instance_id"] for r in s.list_user_tasks()] == ["i2"]


def test_get_user_task_picks_the_newest(make_store):
    s = make_store()
    s.replace_user_tasks("i1", [_task(ck="shared")])
    s.replace_user_tasks("i2", [_task(ck="shared")])
    assert s.get_user_task(TASK, "shared")["instance_id"] == "i2"
    # Re-checkpointing the older instance keeps its created, so i2 stays newest.
    s.replace_user_tasks("i1", [_task(ck="shared")])
    assert s.get_user_task(TASK, "shared")["instance_id"] == "i2"
    assert s.get_user_task(TASK, "other") is None
    assert s.get_user_task(CHAT + "no_task", "shared") is None


# ── location and redaction ───────────────────────────────────────────────────


def test_sqlite_location_is_the_path(tmp_path):
    s = SQLiteStore(tmp_path / "s.db")
    assert s.path == tmp_path / "s.db"
    assert s.location == str(tmp_path / "s.db")


def test_postgres_location_redacts_the_password(store_backend):
    if store_backend != "postgres":
        pytest.skip("postgres only")
    url = os.environ["SEAMS_TEST_POSTGRES_URL"]
    s = PostgresStore(url)
    assert s.location == redact(url)
    if "@" in url and ":" in url.split("://", 1)[1].split("@", 1)[0]:
        assert "***" in s.location
        password = url.split("://", 1)[1].split("@", 1)[0].split(":", 1)[1]
        assert password not in s.location and password not in repr(s)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://seams:s3cret@db01:5432/expense_db", "postgresql://seams:***@db01:5432/expense_db"),
        ("postgresql://seams:p%40ss@db01/expense_db", "postgresql://seams:***@db01/expense_db"),
        ("postgresql://seams@db01/expense_db", "postgresql://seams@db01/expense_db"),
        ("postgresql://db01/expense_db?password=s3cret&sslmode=require", None),
        (
            "host=db01 user=seams password=s3cret dbname=expense_db",
            "host=db01 user=seams password=*** dbname=expense_db",
        ),
        ("host=db01 password='s3 cret' dbname=x", "host=db01 password=*** dbname=x"),
    ],
)
def test_redact_strips_the_password(url, expected):
    out = redact(url)
    assert "s3cret" not in out and "s3 cret" not in out and "p%40ss" not in out
    if expected is not None:
        assert out == expected
    else:
        assert "password=***" in out and "sslmode=require" in out


def test_unreachable_postgres_fails_fast_without_leaking_the_password(caplog):
    caplog.set_level(logging.ERROR, logger="seams_runtime.store")
    with pytest.raises(psycopg.OperationalError):
        PostgresStore("postgresql://seams:s3cret@127.0.0.1:1/expense_db", connect_timeout=2)
    assert "postgresql://seams:***@127.0.0.1:1/expense_db" in caplog.text
    assert "s3cret" not in caplog.text
