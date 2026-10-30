"""Channel-started processes (ADR-0010, M009/S07): a message throw event that
publishes on a channel starts every process whose message start event
seam:subscribesTo it, with the publisher's correlation key, entities and
statuses. Runs against tests/fixtures/channel_start: an approval process that
publishes on :payment_channel when a manager approves, and a payout process
that pays the approved expense."""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest
from rdflib import RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import GeneratorError  # noqa: E402
from seams_gen.compose import extract_compose  # noqa: E402
from seams_gen.fastapi import (  # noqa: E402
    Facts,  # noqa: E402
    extract_routes,
    serving_containers,
)
from seams_gen.htmx import extract_page, render_fragments, render_task_forms  # noqa: E402
from seams_runtime import (  # noqa: E402
    HeaderAuthenticator,
    Identity,
    ModelGraph,
    ResolutionError,
    Runtime,
    Store,
)
from seams_runtime.model import COMM, SEAM  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "channel_start"
TRIG = FIXTURE / "expenses.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
APPROVAL = URIRef(EX + "approval_process")
PAYOUT = URIRef(EX + "payout_process")
CHANNEL = URIRef(EX + "payment_channel")
START = URIRef(EX + "payout_bpmn#payment_received")
EXPENSE_SHAPE = URIRef(EX + "ExpenseShape")
EXPENSE = {"description": "Train to Leeds", "amount": "42.50"}
MANAGER = Identity("manager")


def make_runtime(tmp_path, model=None, db="seams.sqlite") -> Runtime:
    model = model if model is not None else ModelGraph.load(TRIG)
    return Runtime(model, Store(tmp_path / db), authenticator=HeaderAuthenticator(), templates_dir=tmp_path)


def fixture_copy(tmp_path, edit) -> Path:
    """The fixture copied into tmp_path with ``edit(trig text)`` applied."""
    for name in ("approval.bpmn", "payout.bpmn"):
        shutil.copy(FIXTURE / name, tmp_path / name)
    trig = tmp_path / "expenses.trig"
    text = TRIG.read_text()
    edited = edit(text)
    assert edited != text
    trig.write_text(edited)
    return trig


async def decide(rt, decision, key="e1"):
    """Submit an expense, then complete the approval with ``decision``."""
    inst = await rt.start_process(":approval_process", EXPENSE, correlation_key=key)
    result = await inst.wait()
    assert result["status"] == "waiting", result["error"]
    inst = await rt.complete_task(TASK, {"decision": decision}, key, MANAGER)
    return await inst.wait()


def published_row(result):
    return next(r for r in result["trace"] if r["task"] == "payment_requested")


# ── the model resolvers ──────────────────────────────────────────────────────


def test_resolvers_name_the_subscribed_start():
    m = ModelGraph.load(TRIG)
    assert m.subscribed_processes(":payment_channel") == [PAYOUT]
    assert m.is_channel_started(":payout_process") is True
    assert m.is_channel_started(":approval_process") is False
    start = m.start_channel(":payout_process")
    assert (start.process, start.event, start.channel) == (PAYOUT, START, CHANNEL)
    # A UI-triggered process is resolved as before.
    assert m.triggering_operation(":approval_process") == URIRef(EX + "submit_expense_op")


def test_start_channel_of_a_ui_triggered_process_names_subscribes_to():
    m = ModelGraph.load(TRIG)
    with pytest.raises(ResolutionError) as err:
        m.start_channel(":approval_process")
    assert str(APPROVAL) in str(err.value) and "subscribesTo" in str(err.value)


def test_a_subscribing_catch_event_that_is_not_the_start_is_ignored():
    m = ModelGraph.load(TRIG)
    pay = URIRef(EX + "payout_bpmn#pay_expense")  # a bpmn:serviceTask, not a startEvent
    m.ds.add((pay, RDF.type, URIRef("https://w3id.org/seams/proc#MessageCatchEvent")))
    m.ds.add((pay, SEAM.subscribesTo, CHANNEL))
    assert m.start_channel(":payout_process").event == START


def test_two_subscribed_starts_are_ambiguous():
    m = ModelGraph.load(TRIG)
    other = URIRef(EX + "other_channel")
    m.ds.add((other, RDF.type, COMM.Channel))
    m.ds.add((START, SEAM.subscribesTo, other))
    for call in (m.is_channel_started, m.start_channel):
        with pytest.raises(ResolutionError) as err:
            call(":payout_process")
        assert str(PAYOUT) in str(err.value) and "subscribesTo" in str(err.value)


# ── the runtime ──────────────────────────────────────────────────────────────


def test_publish_starts_the_subscriber_with_the_key_and_entities(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        result = await decide(rt, "approved")
        assert result["status"] == "complete", result["error"]
        row = published_row(result)
        assert row["published"] == {"channel": str(CHANNEL), "event": "payment requested"}
        [started] = row["started"]
        assert started["process"] == str(PAYOUT)

        sub = rt.instances[started["instance"]]
        assert sub.correlation_key == "e1"
        payout = await sub.wait()
        assert payout["status"] == "complete", payout["error"]
        assert [r["task"] for r in payout["trace"]] == ["payment_received", "pay_expense", "end"]
        assert payout["history"] == {"Expense": ["approved", "paid"]}
        # The copied entity kept its id: the payout updates the approved expense.
        [expense_id] = result["entities"]["Expense"]
        assert payout["entities"] == {"Expense": [expense_id]}
        [stored] = rt.query(":ExpenseShape", expense="e1")
        assert stored["id"] == expense_id
        assert stored["status"] == "paid"
        assert stored["data"]["description"] == EXPENSE["description"]
        # The publisher's state is a copy, not shared.
        assert result["lifecycle"] == {"Expense": "approved"}
        meta = rt.store.get_instance(sub.id)
        assert (meta["process"], meta["correlation_key"], meta["status"]) == (str(PAYOUT), "e1", "complete")

    asyncio.run(main())


def test_a_path_that_publishes_nothing_starts_nothing(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        result = await decide(rt, "rejected")
        assert result["status"] == "complete", result["error"]
        assert not any("published" in r or "started" in r for r in result["trace"])
        assert {i.process for i in rt.instances.values()} == {APPROVAL}
        [stored] = rt.query(":ExpenseShape", expense="e1")
        assert stored["status"] == "rejected"

    asyncio.run(main())


def test_a_failing_subscriber_fails_alone(tmp_path):
    # t_pay now leaves "submitted", but the publisher copies "approved".
    trig = fixture_copy(
        tmp_path,
        lambda t: t.replace(
            ":t_pay a state:Transition ; state:from :s_approved", ":t_pay a state:Transition ; state:from :s_submitted"
        ),
    )
    rt = make_runtime(tmp_path, ModelGraph.load(trig))

    async def main():
        result = await decide(rt, "approved")
        assert result["status"] == "complete", result["error"]
        [started] = published_row(result)["started"]
        payout = await rt.instances[started["instance"]].wait()
        assert payout["status"] == "failed"
        assert payout["error"]["type"] == "LifecycleViolation"
        assert rt.store.get_instance(started["instance"])["status"] == "failed"
        assert rt.store.get_instance(result["instance"])["status"] == "complete"

    asyncio.run(main())


def test_a_subscriber_that_cannot_start_is_recorded_on_the_publisher(tmp_path):
    model = ModelGraph.load(TRIG)
    other = URIRef(EX + "other_channel")
    model.ds.add((other, RDF.type, COMM.Channel))
    model.ds.add((START, SEAM.subscribesTo, other))  # two subscribed starts: ambiguous
    rt = make_runtime(tmp_path, model)

    async def main():
        result = await decide(rt, "approved")
        assert result["status"] == "complete", result["error"]
        [started] = published_row(result)["started"]
        assert started["process"] == str(PAYOUT) and started["instance"] is None
        assert started["error"]["type"] == "ResolutionError"
        assert {i.process for i in rt.instances.values()} == {APPROVAL}

    asyncio.run(main())


def test_start_subscribed_refuses_a_process_that_is_not_channel_started(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        with pytest.raises(ResolutionError):
            await rt.start_subscribed(":approval_process", "e1", {}, {})
        with pytest.raises(ResolutionError):
            await rt.start_subscribed(":payout_process", "", {}, {})
        assert rt.instances == {}

    asyncio.run(main())


def test_a_checkpointed_subscriber_resumes_after_a_restart(tmp_path):
    current = {str(EXPENSE_SHAPE): {"id": "x1", "data": {**EXPENSE, "status": "approved"}}}
    status = {str(EXPENSE_SHAPE): "approved"}

    async def first():
        rt = make_runtime(tmp_path)
        inst = await rt.start_subscribed(":payout_process", "e9", current, status, stop_after="payment_received")
        assert rt.store.get_instance(inst.id)["status"] == "running"  # checkpointed before it ran
        result = await inst.wait()
        assert result["status"] == "stopped", result["error"]
        assert current[str(EXPENSE_SHAPE)]["data"]["status"] == "approved"  # copied, not shared
        return inst.id

    async def second(instance_id):
        rt = make_runtime(tmp_path)  # a fresh runtime: nothing parsed, nothing in memory
        result = await (await rt.resume(instance_id)).wait()
        assert result["status"] == "complete", result["error"]
        assert [r["task"] for r in result["trace"]] == ["payment_received", "pay_expense", "end"]
        assert result["trace"][1]["iri"] == EX + "payout_bpmn#pay_expense"
        assert result["lifecycle"] == {"Expense": "paid"}
        assert rt.store.get_entity("x1")["status"] == "paid"

    instance_id = asyncio.run(first())
    asyncio.run(second(instance_id))


# ── the generators ───────────────────────────────────────────────────────────


def test_generators_skip_the_subscribed_process():
    model = ModelGraph.load(TRIG)
    routes = extract_routes(model)
    [module] = routes.modules
    assert module.id == "expense_api"
    # Only the UI-triggered process gets a start route.
    assert sorted(e.start.process for e in module.endpoints if e.start is not None) == [":approval_process"]
    assert [str(c) for c in serving_containers(Facts(model))] == [EX + "expense_api"]
    page = extract_page(model)
    assert render_fragments(page) and render_task_forms(page)
    assert extract_compose(model, base_dir=FIXTURE)


def test_generator_rejects_an_untriggered_unsubscribed_process():
    model = ModelGraph.load(TRIG)
    model.ds.remove((START, SEAM.subscribesTo, None))
    with pytest.raises(GeneratorError) as err:
        extract_routes(model)
    assert err.value.subject == str(PAYOUT)
    assert "subscribesTo" in err.value.detail and "ADR-0010" in err.value.detail


def test_the_adr_query_finds_the_started_process():
    adr = (ROOT / "docs" / "adr" / "0010-channel-started-processes.md").read_text()
    query = adr.split("```sparql\n", 1)[1].split("```", 1)[0]
    rows = {tuple(map(str, r)) for r in ModelGraph.load(TRIG).ds.query(query)}
    assert rows == {(str(APPROVAL), str(CHANNEL), str(PAYOUT))}
