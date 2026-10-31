"""Process.nodes()/tasks()/gateways()/lanes() (M010/S04): the BPMN walk joined to the graph."""

import dataclasses
import shutil
from pathlib import Path

import pytest
import seams
from lxml import etree
from seams import SEAM, FlowNode

ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = ROOT / "examples/chat-app"
CHAT = CHAT_DIR / "chat-app.trig"
CH08_DIR = ROOT / "examples/expenses/chapter-08"
CH08 = CH08_DIR / "expenses.trig"

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

APPROVAL_ORDER = [
    "start",
    "persist_expense",
    "route_expense",
    "route_gateway",
    "approve_expense",
    "finance_approve_expense",
    "decision_gateway",
    "record_approval",
    "pay_expense",
    "record_rejection",
    "approved_end",
    "rejected_end",
]
PAYOUT_ORDER = [
    "payout_requested",
    "schedule_payout",
    "choose_payout",
    "method_gateway",
    "add_to_batch",
    "send_now",
    "paid_out",
]


@pytest.fixture(scope="module")
def chat() -> seams.Model:
    return seams.load(CHAT)


@pytest.fixture(scope="module", params=[CH08, CH08_DIR], ids=["file", "dir"])
def ch08(request: pytest.FixtureRequest) -> seams.Model:
    return seams.load(request.param)


def _process(m: seams.Model, pid: str) -> seams.Process:
    return m.processes.for_bpmn_process(pid).only()


def _node(p: seams.Process, bpmn_id: str) -> FlowNode:
    return next(n for n in p.nodes() if n.bpmn_id == bpmn_id)


def test_chat_tasks_in_flow_order(chat: seams.Model) -> None:
    p = _process(chat, "send_message_process")
    assert [t.bpmn_id for t in p.tasks()] == ["persist_user_msg", "route_to_provider", "invoke_llm", "persist_response"]
    assert all(t.node.is_task for t in p.tasks())


def test_chat_nodes_include_unlifted_events(chat: seams.Model) -> None:
    p = _process(chat, "send_message_process")
    ids = [n.bpmn_id for n in p.nodes()]
    assert {"start", "end", "stream_complete_event"} <= set(ids)
    assert ids[0] == "start" and ids[-1] == "end"
    start = _node(p, "start")
    assert start.element is None
    assert start.kind is None
    assert start.invokes is None and start.decided_by is None and start.completed_on is None and start.fires is None
    assert start.iri == p.element_iri("start")
    for edge, predicate in [
        (start.reads, SEAM.reads),
        (start.writes, SEAM.writes),
        (start.publishes_to, SEAM.publishesTo),
        (start.subscribes_to, SEAM.subscribesTo),
    ]:
        assert len(edge) == 0
        assert edge.subject == str(start.iri) and edge.predicate == str(predicate)
    assert _node(p, "stream_complete_event").tag == "intermediateThrowEvent"


def test_chat_lifted_node_is_the_interned_element(chat: seams.Model) -> None:
    p = _process(chat, "send_message_process")
    persist = _node(p, "persist_user_msg")
    assert persist.element is chat.processes.element("persist_user_msg").only()
    assert persist.kind == persist.element.kind
    assert persist.name == "Persist User Message"


def test_business_rule_task_reaches_its_decision_table(chat: seams.Model) -> None:
    route = _node(_process(chat, "send_message_process"), "route_to_provider")
    assert route.decided_by is not None
    assert route.decided_by.table.hit_policy == "FIRST"


def test_ch08_flow_orders(ch08: seams.Model) -> None:
    assert [n.bpmn_id for n in _process(ch08, "approval_process").nodes()] == APPROVAL_ORDER
    assert [n.bpmn_id for n in _process(ch08, "payout_process").nodes()] == PAYOUT_ORDER


def test_user_task_completed_on(ch08: seams.Model) -> None:
    approve = _node(_process(ch08, "approval_process"), "approve_expense")
    expected = ch08.processes.element("approve_expense").only().completed_on
    assert expected is not None
    assert approve.completed_on is expected


def test_message_start_event_starts_from_channel(ch08: seams.Model) -> None:
    payout = _process(ch08, "payout_process")
    start = _node(payout, "payout_requested")
    expected = payout.channel_starts.only().channel
    assert start.starts_from is not None
    assert start.starts_from.iri == expected.iri
    assert _node(payout, "schedule_payout").starts_from is None


def test_gateway_paths(ch08: seams.Model) -> None:
    approval = _process(ch08, "approval_process")
    gw = _node(approval, "route_gateway")
    assert gw.element is None
    assert [g.bpmn_id for g in approval.gateways()] == ["route_gateway", "decision_gateway"]
    assert sorted(f.name or "" for f in gw.paths) == ["auto", "finance", "manager"]
    assert gw.paths == gw.outgoing
    assert {f.target for f in gw.paths} == {"record_approval", "approve_expense", "finance_approve_expense"}
    assert all(f.source == "route_gateway" for f in gw.paths)
    assert [g.bpmn_id for g in _process(ch08, "payout_process").gateways()] == ["method_gateway"]


def _check_walk(m: seams.Model) -> None:
    for p in m.processes:
        nodes = p.nodes()
        lifted = [n.element for n in nodes if n.element is not None]
        for el in p.elements():
            assert sum(1 for x in lifted if x is el) == 1, el.iri
        assert nodes is p.nodes()
        assert p.tasks() is p.tasks() and p.gateways() is p.gateways()
        with pytest.raises(dataclasses.FrozenInstanceError):
            nodes[0].element = None  # type: ignore[misc]
        assert p.lanes() == ()
        assert all(n.lane is None for n in nodes)


def test_every_lifted_element_appears_once_chat(chat: seams.Model) -> None:
    _check_walk(chat)


def test_every_lifted_element_appears_once_ch08(ch08: seams.Model) -> None:
    _check_walk(ch08)


def test_lanes_from_a_copied_model(tmp_path: Path) -> None:
    copy = tmp_path / "chat-app"
    shutil.copytree(CHAT_DIR, copy)
    bpmn = copy / "chat_process.bpmn"
    tree = etree.parse(str(bpmn))
    process = next(el for el in tree.getroot() if etree.QName(el).localname == "process")
    lane_set = etree.Element(f"{{{BPMN_NS}}}laneSet", id="lanes")
    for lane_id, name, refs in [
        ("lane_api", "API", ["start", "persist_user_msg", "route_to_provider"]),
        ("lane_llm", "LLM", ["invoke_llm", "persist_response"]),
    ]:
        lane = etree.SubElement(lane_set, f"{{{BPMN_NS}}}lane", id=lane_id, name=name)
        for ref in refs:
            etree.SubElement(lane, f"{{{BPMN_NS}}}flowNodeRef").text = ref
    process.insert(0, lane_set)
    tree.write(str(bpmn), xml_declaration=True, encoding="UTF-8")

    m = seams.load(copy / "chat-app.trig")
    p = _process(m, "send_message_process")
    assert [(lane.id, lane.name) for lane in p.lanes()] == [("lane_api", "API"), ("lane_llm", "LLM")]
    assert p.lanes()[1].node_ids == ("invoke_llm", "persist_response")
    persist = _node(p, "persist_user_msg")
    assert persist.lane is not None and persist.lane.id == "lane_api"
    assert _node(p, "invoke_llm").lane == p.lanes()[1]
    assert _node(p, "end").lane is None
