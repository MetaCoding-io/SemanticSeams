"""The shared live-update bus and store-backed resume (ADR-0038, M030/S03).

Two ``PostgresChannelBus`` on one schema stand in for two replicas: a frame
published on one reaches subscribers of both, the backlog replays from
``channel_frames``, a close ends streams on both, an oversize frame travels
by id, and the listener reconnects. Two runtimes on one PostgreSQL store
complete a user task started on the other, and only one of them can claim
it. The PostgreSQL runs need ``SEAMS_TEST_POSTGRES_URL`` (tests/conftest.py).
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from seams_runtime import HeaderAuthenticator, Identity, PostgresStore, Runtime, TaskNotOpen
from seams_runtime.channels import ChannelBus, PostgresChannelBus, bus_for
from seams_runtime.store import NOTIFY_LIMIT
from tests.conftest import postgres_url

ROOT = Path(__file__).resolve().parents[1]
TRIG = ROOT / "tests" / "fixtures" / "channel_start" / "expenses.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
EXPENSE = {"description": "Train to Leeds", "amount": "42.50"}
MANAGER = Identity("manager")
CHANNEL = EX + "payment_channel"
WAIT = 5.0


@pytest.fixture
def schema():
    """A fresh postgres schema name, dropped at teardown."""
    name = f"seams_test_{uuid.uuid4().hex[:12]}"
    yield name
    with psycopg.connect(postgres_url(), autocommit=True) as con:
        con.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture
def buses(schema):
    """``buses(n, **options)``: n buses, each on its own store of one schema (n replicas)."""
    made: list[PostgresChannelBus] = []

    def make(n: int = 2, **options) -> list[PostgresChannelBus]:
        for _ in range(n):
            made.append(PostgresChannelBus(PostgresStore(postgres_url(), schema=schema), **options))
        return made[-n:]

    yield make
    for bus in made:
        bus.stop()


async def next_frame(sub) -> str:
    return await asyncio.wait_for(sub.__anext__(), WAIT)


async def ends(sub) -> bool:
    try:
        await asyncio.wait_for(sub.__anext__(), WAIT)
    except StopAsyncIteration:
        return True
    return False


def data_of(frame: str) -> dict:
    return json.loads(frame.split("data: ", 1)[1])


# ── the bus follows the store kind ───────────────────────────────────────────


def test_bus_for_follows_the_store_kind(make_store, store_backend):
    bus = bus_for(make_store())
    try:
        if store_backend == "sqlite":
            assert type(bus) is ChannelBus
            assert bus.health() == {"kind": "in-process"}
        else:
            assert isinstance(bus, PostgresChannelBus)
            health = bus.health()
            assert health["kind"] == "postgresql"
            assert health["listening"] is True
            assert health["name"].startswith("seams_seams_test_")
    finally:
        bus.stop()


def test_listener_logs_its_channel(buses, caplog):
    caplog.set_level(logging.INFO, logger="seams_runtime.channels")
    (bus,) = buses(1)
    assert f"channel listen {bus.name}" in caplog.text


# ── delivery across buses ────────────────────────────────────────────────────


def test_a_frame_published_on_one_bus_reaches_subscribers_of_both(buses):
    a, b = buses(2)

    async def run():
        on_a, on_b = a.subscribe(CHANNEL, "c1"), b.subscribe(CHANNEL, "c1")
        other = b.subscribe(CHANNEL, "c2")
        frame = a.publish(CHANNEL, "c1", "token", {"seq": 0})
        assert await next_frame(on_b) == frame
        assert await next_frame(on_a) == frame  # the publisher delivers through its own listener
        b.publish(CHANNEL, "c1", "token", {"seq": 1})
        assert data_of(await next_frame(on_a)) == {"seq": 1}
        assert data_of(await next_frame(on_b)) == {"seq": 1}
        await asyncio.sleep(0.3)
        assert on_a._queue.empty() and on_b._queue.empty()  # each frame once
        assert other._queue.empty()  # never across scopes
        for sub in (on_a, on_b, other):
            sub.close()

    asyncio.run(run())


def test_schemas_do_not_share_frames(buses, schema):
    (a,) = buses(1)
    elsewhere = f"{schema}_other"
    bus = PostgresChannelBus(PostgresStore(postgres_url(), schema=elsewhere))
    try:
        assert bus.name != a.name

        async def run():
            sub = bus.subscribe(CHANNEL, "c1")
            a.publish(CHANNEL, "c1", "token", {"seq": 0})
            await asyncio.sleep(0.5)
            assert sub._queue.empty()
            sub.close()

        asyncio.run(run())
    finally:
        bus.stop()
        with psycopg.connect(postgres_url(), autocommit=True) as con:
            con.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(elsewhere)))


def test_the_backlog_replays_from_the_table_bounded_per_scope(buses):
    a, b = buses(2, backlog=2)

    async def run():
        for seq in range(3):
            a.publish(CHANNEL, "c1", "token", {"seq": seq})
        a.publish(CHANNEL, "c2", "token", {"seq": 9})
        sub = b.subscribe(CHANNEL, "c1")
        assert [data_of(await next_frame(sub))["seq"] for _ in range(2)] == [1, 2]
        a.publish(CHANNEL, "c1", "token", {"seq": 3})
        assert data_of(await next_frame(sub)) == {"seq": 3}
        await asyncio.sleep(0.3)
        assert sub._queue.empty()  # replayed frames arriving live are not repeated
        sub.close()

    asyncio.run(run())
    assert [r["frame"] is not None for r in a.store.channel_backlog(CHANNEL, "c1")] == [True, True]


def test_close_ends_streams_on_every_bus_and_a_publish_reopens(buses):
    a, b = buses(2)

    async def run():
        sub = b.subscribe(CHANNEL, "c1")
        a.publish(CHANNEL, "c1", "token", {"seq": 0})
        assert data_of(await next_frame(sub)) == {"seq": 0}
        a.close(CHANNEL, "c1")
        assert await ends(sub)
        assert b.subscriber_count(CHANNEL, "c1") == 0
        assert await ends(b.subscribe(CHANNEL, "c1"))  # a closed scope ends a later subscriber at once
        a.publish(CHANNEL, "c1", "token", {"seq": 1})
        reopened = b.subscribe(CHANNEL, "c1")
        assert data_of(await next_frame(reopened)) == {"seq": 1}
        reopened.close()

    asyncio.run(run())


def test_an_oversize_frame_travels_by_id(buses):
    a, b = buses(2)
    content = "x" * (NOTIFY_LIMIT + 100)

    async def run():
        sub = b.subscribe(CHANNEL, "c1")
        frame = a.publish(CHANNEL, "c1", "token", {"content": content})
        assert len(frame.encode()) > NOTIFY_LIMIT
        assert await next_frame(sub) == frame
        sub.close()

    asyncio.run(run())


# ── failure paths ────────────────────────────────────────────────────────────


def test_a_notified_id_with_no_row_is_logged_as_dropped(buses, caplog):
    (bus,) = buses(1)
    caplog.set_level(logging.INFO, logger="seams_runtime.channels")
    bus._receive(json.dumps({"id": 987654321}))
    assert "channel dropped 987654321" in caplog.text


def test_a_malformed_notification_is_ignored(buses, caplog):
    (bus,) = buses(1)
    caplog.set_level(logging.INFO, logger="seams_runtime.channels")
    bus._receive("not json")
    bus._receive(json.dumps({"channel": CHANNEL}))
    assert caplog.text.count("ignoring a malformed notification") == 2
    assert bus.listening


def test_the_listener_reconnects_after_losing_its_connection(buses, caplog):
    caplog.set_level(logging.INFO, logger="seams_runtime.channels")
    a, b = buses(2, poll=0.1)
    with psycopg.connect(postgres_url(), autocommit=True) as con:
        killed = con.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query = %s AND pid <> pg_backend_pid()",
            (f'LISTEN "{b.name}"',),
        ).fetchall()
    assert killed
    deadline = time.monotonic() + WAIT
    while b.reconnects == 0 or not b.listening:
        assert time.monotonic() < deadline, "the listener did not reconnect"
        time.sleep(0.05)
    assert f"channel reconnect {b.name}" in caplog.text

    async def run():
        sub = b.subscribe(CHANNEL, "c1")
        a.publish(CHANNEL, "c1", "token", {"seq": 0})
        assert data_of(await next_frame(sub)) == {"seq": 0}
        sub.close()

    asyncio.run(run())


# ── runtimes sharing one store ───────────────────────────────────────────────


@pytest.fixture
def runtimes(schema, tmp_path):
    """``runtimes(n)``: n runtimes loaded on stores of one postgres schema."""
    made: list[Runtime] = []

    def make(n: int = 2) -> list[Runtime]:
        for _ in range(n):
            store = PostgresStore(postgres_url(), schema=schema)
            made.append(Runtime.load(TRIG, store=store, authenticator=HeaderAuthenticator(), templates_dir=tmp_path))
        return made[-n:]

    yield make
    for rt in made:
        rt.stop()


def test_runtime_load_picks_the_shared_bus(runtimes):
    (rt,) = runtimes(1)
    assert isinstance(rt.bus, PostgresChannelBus)
    assert rt.worker.bus is rt.bus


def test_a_user_task_started_on_one_runtime_completes_on_the_other(runtimes):
    a, b = runtimes(2)

    async def run():
        started = await a.start_process(":approval_process", EXPENSE, correlation_key="e1")
        assert (await started.wait())["status"] == "waiting"
        assert started.id not in b.instances
        done = await b.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        assert done.id == started.id
        result = await done.wait()
        assert result["status"] == "complete", result["error"]
        tasks = [r["task"] for r in result["trace"]]
        assert tasks.count("approve_expense") == 1 and "payment_requested" in tasks
        with pytest.raises(TaskNotOpen):
            await a.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        assert b.store.get_instance(started.id)["status"] == "complete"

    asyncio.run(run())


def test_a_stale_cached_instance_is_reloaded_from_the_store(runtimes):
    a, b = runtimes(2)

    async def run():
        started = await a.start_process(":approval_process", EXPENSE, correlation_key="e1")
        await started.wait()
        # b moves the instance on, then a is asked for it: a's cached copy is stale
        b.store.save_state(started.id, started.process, b.store.load_state(started.id).replace("Leeds", "York"))
        reloaded = await a._waiting_instance(started.id)
        assert reloaded is not started
        assert "York" in a.engine.serialize(reloaded.workflow)
        assert await a._waiting_instance(reloaded.id) is not None

    asyncio.run(run())


def test_two_runtimes_completing_one_task_run_it_once(runtimes):
    a, b = runtimes(2)

    async def run():
        started = await a.start_process(":approval_process", EXPENSE, correlation_key="e1")
        await started.wait()
        outcomes = await asyncio.gather(
            a.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER),
            b.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER),
            return_exceptions=True,
        )
        refused = [o for o in outcomes if isinstance(o, TaskNotOpen)]
        won = [o for o in outcomes if not isinstance(o, BaseException)]
        assert (len(won), len(refused)) == (1, 1), outcomes
        result = await won[0].wait()
        assert [r["task"] for r in result["trace"]].count("approve_expense") == 1

    asyncio.run(run())


def test_a_frame_published_by_one_runtime_streams_from_the_other(runtimes):
    a, b = runtimes(2)

    async def run():
        sub = b.subscribe(":payment_channel", "e1")
        started = await a.start_process(":approval_process", EXPENSE, correlation_key="e1")
        await started.wait()
        done = await a.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        await done.wait()
        assert data_of(await next_frame(sub))["instance"] == started.id
        sub.close()

    asyncio.run(run())


def test_a_failed_completion_reopens_the_claimed_task(make_store, tmp_path, monkeypatch):
    rt = Runtime.load(TRIG, store=make_store(), authenticator=HeaderAuthenticator(), templates_dir=tmp_path)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("handler exploded")

    async def run():
        started = await rt.start_process(":approval_process", EXPENSE, correlation_key="e1")
        await started.wait()
        with monkeypatch.context() as patch:
            patch.setattr(rt.worker, "complete_user_task", boom)
            with pytest.raises(RuntimeError, match="handler exploded"):
                await rt.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        assert rt.store.get_user_task(TASK, "e1") is not None  # the claim was undone
        done = await rt.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        assert (await done.wait())["status"] == "complete"

    try:
        asyncio.run(run())
    finally:
        rt.stop()
