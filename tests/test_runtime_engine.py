"""Pins seams_runtime's engine (graph-bound Spiff parser, DMN input/output
bindings, serialization), its SQLite store and its SSE channel bus
(M004/S03 T04, D013) against examples/chat-app/chat-app.trig."""

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest
from rdflib import RDFS, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SpiffWorkflow.util.task import TaskState  # noqa: E402

from seams_runtime import ModelGraph, ResolutionError  # noqa: E402
from seams_runtime.channels import ChannelBus, sse_frame  # noqa: E402
from seams_runtime.engine import Engine  # noqa: E402
from seams_runtime.model import DEC  # noqa: E402
from seams_runtime.store import Store  # noqa: E402

CHAT_DIR = ROOT / "examples" / "chat-app"
TRIG = CHAT_DIR / "chat-app.trig"
CHAT = "https://example.org/chat/"
PROCESS = ":send_message_process"
DECISION = URIRef(CHAT + "routing_decision")
SHAPE = CHAT + "MessageShape"
SHORT = {"role": "user", "content": "Hello, which provider?"}
LONG = {"role": "user", "content": "x" * 4001}


@pytest.fixture(scope="module")
def model():
    return ModelGraph(TRIG)


@pytest.fixture(scope="module")
def engine(model):
    return Engine(model)


@pytest.fixture
def fresh():
    """A private model copy for tests that mutate the graph."""
    return ModelGraph(TRIG)


# ── driver: what the T05 worker does, minus its handlers ──────────────────────


def _step(engine, wf, entity, trace):
    """Advance one element; False when nothing is runnable."""
    started = [t for t in wf.get_tasks(state=TaskState.STARTED) if engine.is_service_task(t)]
    if started:
        task = started[0]
        task.data.setdefault("handled", []).append(task.task_spec.bpmn_id)
        task.complete()
        trace.append(task.task_spec.bpmn_id)
        return True
    ready = [t for t in wf.get_tasks(state=TaskState.READY) if not t.task_spec.manual]
    if not ready:
        return False
    task = ready[0]
    engine.run_task(task, entity)
    if task.state != TaskState.STARTED and task.task_spec.bpmn_id is not None:
        trace.append(task.task_spec.bpmn_id)
    return True


def _drive(engine, wf, entity, *, stop_after=None):
    trace = []
    while _step(engine, wf, entity, trace):
        if stop_after is not None and trace and trace[-1] == stop_after:
            break
    return trace


def _final(wf) -> dict:
    return {k: v for k, v in wf.last_task.data.items() if not k.startswith("_")}


# ── parser binding ───────────────────────────────────────────────────────────


def test_process_id_comes_from_the_process_label(engine):
    assert engine.process_id(PROCESS) == "send_message_process"


def test_parser_binds_route_to_provider_through_payload_element(engine):
    wf = engine.new_workflow(PROCESS)
    spec = wf.spec.task_specs["route_to_provider"]
    assert engine.is_business_rule(wf.get_tasks(spec_name="route_to_provider")[0])
    assert spec.dmnEngine.decision_table.id == "routing_table"  # routing_decision's table
    b = engine.binding("route_to_provider")
    assert b.decision == DECISION and b.decision_id == "routing_decision"
    assert b.dmn_path == CHAT_DIR / "routing.dmn"


def test_payload_element_nope_fails_at_parse_time(fresh):
    ctx = next(c for _s, _p, _o, c in fresh.ds.quads((DECISION, DEC.payloadElement, None)))
    fresh.ds.remove((DECISION, DEC.payloadElement, None))
    fresh.ds.graph(ctx).add((DECISION, DEC.payloadElement, Literal("nope")))
    with pytest.raises(ResolutionError) as exc:
        Engine(fresh).new_workflow(PROCESS)
    assert exc.value.subject == str(DECISION)
    assert exc.value.predicate == str(DEC.payloadElement)
    assert "'nope'" in str(exc.value)


def test_unknown_process_is_resolution_error(engine):
    with pytest.raises(ResolutionError):
        engine.new_workflow(":routing_decision")


def test_process_id_falls_back_to_single_executable_process(fresh):
    proc = fresh.curie(PROCESS)
    fresh.ds.remove((proc, RDFS.label, None))
    fresh.ds.add((proc, RDFS.label, Literal("No Such Process")))
    # Falls back to the single executable process.
    assert Engine(fresh).process_id(PROCESS) == "send_message_process"


# ── input / output bindings ──────────────────────────────────────────────────


def test_evaluate_inputs_measures_content_length(engine):
    b = engine.binding("route_to_provider")
    assert engine.evaluate_inputs(b, {"role": "user", "content": "x" * 4001}) == {
        "message_role": "user", "message_length": 4001,
    }


def test_evaluate_inputs_missing_field_names_from_path(engine):
    b = engine.binding("route_to_provider")
    with pytest.raises(ResolutionError) as exc:
        engine.evaluate_inputs(b, {"role": "user"})
    assert exc.value.subject == CHAT + "content"
    assert exc.value.predicate == str(DEC.fromPath)


def test_evaluate_inputs_length_of_non_sized_value(engine):
    b = engine.binding("route_to_provider")
    with pytest.raises(ResolutionError) as exc:
        engine.evaluate_inputs(b, {"role": "user", "content": 42})
    assert exc.value.predicate == str(DEC.measure)


def test_unknown_measure_raises(fresh):
    node = next(n for n in fresh.ds.objects(DECISION, DEC.input)
                if fresh.ds.value(n, DEC.measure) is not None)
    ctx = next(c for _s, _p, _o, c in fresh.ds.quads((node, DEC.measure, None)))
    fresh.ds.remove((node, DEC.measure, None))
    fresh.ds.graph(ctx).add((node, DEC.measure, DEC.WordCount))
    eng = Engine(fresh)
    with pytest.raises(ResolutionError) as exc:
        eng.evaluate_inputs(eng.binding("route_to_provider"), LONG)
    assert exc.value.predicate == str(DEC.measure)
    assert "WordCount" in str(exc.value)


def test_map_outputs_provider_to_provider(engine):
    b = engine.binding("route_to_provider")
    data = {"Provider": "default-provider", "other": 1}
    assert engine.map_outputs(b, data) == {"provider": "default-provider"}
    assert data["provider"] == "default-provider" and data["other"] == 1


def test_map_outputs_missing_output_raises(engine):
    with pytest.raises(ResolutionError) as exc:
        engine.map_outputs(engine.binding("route_to_provider"), {})
    assert exc.value.predicate == str(DEC.output)


def test_business_rule_task_without_entity_raises(engine):
    wf = engine.new_workflow(PROCESS)
    _drive(engine, wf, SHORT, stop_after="persist_user_msg")
    task = wf.get_tasks(state=TaskState.READY)[0]
    assert task.task_spec.bpmn_id == "route_to_provider"
    with pytest.raises(ResolutionError):
        engine.run_task(task, None)


# ── driving workflows ────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity, provider", [
    (SHORT, "default-provider"),
    (LONG, "long-context-provider"),
    ({"role": "user", "content": "x" * 4000}, "default-provider"),
    ({"role": "system", "content": "x" * 5000}, "default-provider"),
])
def test_drive_to_end_routes_by_graph_bindings(engine, entity, provider):
    wf = engine.new_workflow(PROCESS)
    trace = _drive(engine, wf, entity)
    assert wf.is_completed()
    assert trace == ["start", "persist_user_msg", "route_to_provider", "invoke_llm",
                     "persist_response", "stream_complete_event", "end"]
    data = _final(wf)
    assert data["provider"] == provider
    assert data["message_length"] == len(entity["content"])
    assert data["handled"] == ["persist_user_msg", "invoke_llm", "persist_response"]


def test_serialize_store_restore_finishes_with_same_data(model, tmp_path):
    db = tmp_path / "state.sqlite"
    baseline = Engine(model)
    wf_b = baseline.new_workflow(PROCESS)
    _drive(baseline, wf_b, LONG)

    eng = Engine(model)
    wf = eng.new_workflow(PROCESS)
    _drive(eng, wf, LONG, stop_after="route_to_provider")
    Store(db).save_state("i-1", PROCESS, eng.serialize(wf), correlation_key="c-1", status="running")
    del wf

    eng2, store2 = Engine(ModelGraph(TRIG)), Store(db)
    restored = eng2.deserialize(store2.load_state("i-1"))
    assert not restored.is_completed()
    trace = _drive(eng2, restored, LONG)
    assert trace[0] == "invoke_llm"
    assert restored.is_completed()
    assert _final(restored) == _final(wf_b)
    assert _final(restored)["provider"] == "long-context-provider"


# ── store ────────────────────────────────────────────────────────────────────


def test_store_state_round_trip_and_listing(tmp_path):
    s = Store(tmp_path / "s.db")
    s.save_state("a", PROCESS, '{"x":1}', correlation_key="c1", status="running")
    s.save_state("b", PROCESS, '{"x":2}', correlation_key="c2", status="done")
    s.save_state("a", PROCESS, '{"x":3}', correlation_key="c1", status="done")
    assert s.load_state("a") == '{"x":3}'
    assert [r["instance_id"] for r in s.list_instances(correlation_key="c1")] == ["a"]
    assert {r["instance_id"] for r in s.list_instances()} == {"a", "b"}
    assert "state" not in s.list_instances()[0]
    with pytest.raises(LookupError):
        s.load_state("missing")


def test_store_query_filters_by_correlation_key_and_fields(tmp_path):
    s = Store(tmp_path / "s.db")
    s.put_entity("m1", SHAPE, {"role": "user", "content": "a"}, correlation_key="c1")
    s.put_entity("m2", SHAPE, {"role": "assistant", "content": "b"}, correlation_key="c1")
    s.put_entity("m3", SHAPE, {"role": "user", "content": "c"}, correlation_key="c2")
    s.put_entity("x1", CHAT + "ConversationShape", {"title": "t"}, correlation_key="c1")
    assert [e["id"] for e in s.query(SHAPE, correlation_key="c1")] == ["m1", "m2"]
    assert [e["id"] for e in s.query(SHAPE, correlation_key="c1", role="user")] == ["m1"]
    assert [e["id"] for e in s.query(SHAPE, role="user")] == ["m1", "m3"]
    assert s.query(SHAPE, correlation_key="nope") == []
    assert s.query(SHAPE, no_such_field="x") == []


def test_store_update_keeps_created_order(tmp_path):
    s = Store(tmp_path / "s.db")
    first = s.put_entity("m1", SHAPE, {"content": "a"}, status="sent")
    s.put_entity("m2", SHAPE, {"content": "b"})
    updated = s.put_entity("m1", SHAPE, {"content": "a2"}, status="streaming")
    assert updated["created"] == first["created"]
    assert updated["data"] == {"content": "a2"} and updated["status"] == "streaming"
    assert [e["id"] for e in s.query(SHAPE)] == ["m1", "m2"]
    assert s.get_entity("missing") is None


def test_store_is_safe_across_threads(tmp_path):
    s = Store(tmp_path / "s.db")

    async def main():
        await asyncio.gather(*(
            asyncio.to_thread(s.put_entity, f"m{i}", SHAPE, {"n": i}, correlation_key="c")
            for i in range(20)
        ))

    asyncio.run(main())
    assert sorted(e["data"]["n"] for e in s.query(SHAPE, correlation_key="c")) == list(range(20))


# ── channel bus ──────────────────────────────────────────────────────────────

CH = CHAT + "stream_channel"


async def _collect(sub):
    return [frame async for frame in sub]


def test_sse_frame_format():
    assert sse_frame("token", {"seq": 0, "t": "hi"}) == 'event: token\ndata: {"seq": 0, "t": "hi"}\n\n'
    with pytest.raises(ValueError):
        sse_frame("bad\nevent", {})
    with pytest.raises(ValueError):
        sse_frame("", {})


def test_publish_subscribe_order_and_scope_isolation():
    async def main():
        bus = ChannelBus()
        a, b = bus.subscribe(CH, "conv-a"), bus.subscribe(CH, "conv-b")
        for i in range(3):
            bus.publish(CH, "conv-a", "token", {"seq": i})
        bus.publish(CH, "conv-b", "done", {"seq": 99})
        bus.close(CH, "conv-a")
        bus.close(CH, "conv-b")
        return await _collect(a), await _collect(b)

    got_a, got_b = asyncio.run(main())
    assert got_a == [f'event: token\ndata: {{"seq": {i}}}\n\n' for i in range(3)]
    assert got_b == ['event: done\ndata: {"seq": 99}\n\n']


def test_backlog_replay_is_bounded_and_closed_scope_ends():
    async def main():
        bus = ChannelBus(backlog=2)
        for i in range(5):
            bus.publish(CH, "s", "token", {"seq": i})
        bus.close(CH, "s")
        late = bus.subscribe(CH, "s")
        return await _collect(late), bus.subscriber_count(CH, "s")

    frames, count = asyncio.run(main())
    assert [json.loads(f.split("data: ", 1)[1]) for f in frames] == [{"seq": 3}, {"seq": 4}]
    assert count == 0


def test_publish_from_worker_thread_reaches_subscriber():
    async def main():
        bus = ChannelBus()
        sub = bus.subscribe(CH, "s")

        def worker():
            for i in range(10):
                bus.publish(CH, "s", "token", {"seq": i})
            bus.close(CH, "s")

        t = threading.Thread(target=worker)
        t.start()
        frames = await asyncio.wait_for(_collect(sub), timeout=5)
        t.join()
        return frames

    frames = asyncio.run(main())
    assert [json.loads(f.split("data: ", 1)[1])["seq"] for f in frames] == list(range(10))


def test_slow_subscriber_is_evicted_not_blocking():
    async def main():
        bus = ChannelBus(backlog=1, queue_size=3)
        slow = bus.subscribe(CH, "s")
        for i in range(10):
            bus.publish(CH, "s", "token", {"seq": i})
        frames = await asyncio.wait_for(_collect(slow), timeout=5)
        return frames, bus.subscriber_count(CH, "s")

    frames, count = asyncio.run(main())
    assert frames == [] and count == 0


def test_unsubscribed_close_stops_delivery():
    async def main():
        bus = ChannelBus()
        sub = bus.subscribe(CH, "s")
        sub.close()
        bus.publish(CH, "s", "token", {})
        return bus.subscriber_count(CH, "s")

    assert asyncio.run(main()) == 0
