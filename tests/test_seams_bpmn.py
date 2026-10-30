"""seams.bpmn (M010/S04): BPMN processes read with lxml, in flow order."""

import dataclasses
from pathlib import Path

import pytest
from seams import ResolutionError
from seams.bpmn import BpmnProcess, parse_bpmn

ROOT = Path(__file__).resolve().parent.parent
CHAT_BPMN = ROOT / "examples/chat-app/chat_process.bpmn"
CH08_DIR = ROOT / "examples/expenses/chapter-08"

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"


def _only(path: Path) -> BpmnProcess:
    (process,) = parse_bpmn(path)
    return process


def _ids(process: BpmnProcess) -> list[str]:
    return [n.id for n in process.nodes]


def _write_bpmn(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "p.bpmn"
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="defs">\n'
        f'  <bpmn:process id="p" name="P">\n{body}\n  </bpmn:process>\n'
        f"</bpmn:definitions>\n"
    )
    return path


def _flow(flow_id: str, source: str, target: str) -> str:
    return f'<bpmn:sequenceFlow id="{flow_id}" sourceRef="{source}" targetRef="{target}" />'


def test_chat_flow_order() -> None:
    process = _only(CHAT_BPMN)
    assert process.id == "send_message_process"
    assert _ids(process) == [
        "start",
        "persist_user_msg",
        "route_to_provider",
        "invoke_llm",
        "persist_response",
        "stream_complete_event",
        "end",
    ]
    stream = process.node("stream_complete_event")
    assert stream.tag == "intermediateThrowEvent"
    assert stream.is_event and not stream.is_task and not stream.is_gateway
    assert [n.id for n in process.nodes if n.is_task] == [
        "persist_user_msg",
        "route_to_provider",
        "invoke_llm",
        "persist_response",
    ]
    assert process.lanes == ()
    assert all(n.lane_id is None for n in process.nodes)


def test_approval_flow_order() -> None:
    process = _only(CH08_DIR / "approval.bpmn")
    assert _ids(process) == [
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
    assert [f.id for f in process.flows][:3] == ["flow_to_persist", "flow_to_route", "flow_to_gateway"]


def test_approval_route_gateway_paths() -> None:
    gateway = _only(CH08_DIR / "approval.bpmn").node("route_gateway")
    assert gateway.tag == "exclusiveGateway" and gateway.is_gateway
    assert gateway.paths == gateway.outgoing
    assert [(p.name, p.condition, p.target) for p in gateway.paths] == [
        ("auto", 'route == "auto"', "record_approval"),
        ("manager", 'route == "manager"', "approve_expense"),
        ("finance", 'route == "finance"', "finance_approve_expense"),
    ]
    assert [f.source for f in gateway.incoming] == ["route_expense"]
    record = _only(CH08_DIR / "approval.bpmn").node("record_approval")
    assert [f.id for f in record.incoming] == ["flow_auto", "flow_approved"]
    unconditioned = _only(CH08_DIR / "approval.bpmn").node("start").outgoing[0]
    assert unconditioned.condition is None and unconditioned.name is None


def test_payout_flow_order_and_message_start() -> None:
    process = _only(CH08_DIR / "payout.bpmn")
    assert _ids(process) == [
        "payout_requested",
        "schedule_payout",
        "choose_payout",
        "method_gateway",
        "add_to_batch",
        "send_now",
        "paid_out",
    ]
    start = process.node("payout_requested")
    assert start.tag == "startEvent"
    assert start.event_definitions == ("messageEventDefinition",)
    assert process.node("paid_out").event_definitions == ()
    assert [p.name for p in process.node("method_gateway").paths] == ["batch", "now"]


def test_parsed_values_are_frozen() -> None:
    node = _only(CHAT_BPMN).nodes[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.name = "x"  # type: ignore[misc]


@pytest.mark.parametrize("path", sorted(ROOT.glob("examples/**/*.bpmn")), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_example_parses(path: Path) -> None:
    processes = parse_bpmn(path)
    assert processes
    for process in processes:
        assert len({n.id for n in process.nodes}) == len(process.nodes)
        assert process.nodes


def test_lanes(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        """
    <bpmn:laneSet id="ls">
      <bpmn:lane id="lane_user" name="User">
        <bpmn:flowNodeRef>s</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>a</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="lane_system" name="System">
        <bpmn:flowNodeRef>b</bpmn:flowNodeRef>
        <bpmn:childLaneSet id="cls">
          <bpmn:lane id="lane_inner">
            <bpmn:flowNodeRef>b</bpmn:flowNodeRef>
          </bpmn:lane>
        </bpmn:childLaneSet>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="s" />
    <bpmn:userTask id="a" />
    <bpmn:serviceTask id="b" />
    <bpmn:endEvent id="e" />
    """
        + _flow("f1", "s", "a")
        + _flow("f2", "a", "b")
        + _flow("f3", "b", "e"),
    )
    process = _only(path)
    assert [(lane.id, lane.name, lane.node_ids) for lane in process.lanes] == [
        ("lane_user", "User", ("s", "a")),
        ("lane_system", "System", ("b",)),
        ("lane_inner", None, ("b",)),
    ]
    assert {n.id: n.lane_id for n in process.nodes} == {
        "s": "lane_user",
        "a": "lane_user",
        "b": "lane_inner",
        "e": None,
    }


def test_loop_order_is_deterministic(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        """
    <bpmn:startEvent id="s" />
    <bpmn:userTask id="draft" />
    <bpmn:userTask id="review" />
    <bpmn:exclusiveGateway id="ok" />
    <bpmn:endEvent id="e" />
    """
        + _flow("f1", "s", "draft")
        + _flow("f2", "draft", "review")
        + _flow("f3", "review", "ok")
        + _flow("f4", "ok", "draft")
        + _flow("f5", "ok", "e"),
    )
    first = _ids(_only(path))
    assert first == ["s", "draft", "review", "ok", "e"]
    assert _ids(_only(path)) == first


def test_pure_cycle_releases_first_in_document(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        '<bpmn:task id="x" /><bpmn:task id="y" /><bpmn:task id="z" />'
        + _flow("f1", "z", "x")
        + _flow("f2", "x", "y")
        + _flow("f3", "y", "z"),
    )
    assert _ids(_only(path)) == ["x", "y", "z"]


def test_unreachable_task_in_document_order(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        """
    <bpmn:startEvent id="s" />
    <bpmn:serviceTask id="orphan" />
    <bpmn:serviceTask id="a" />
    <bpmn:endEvent id="e" />
    """
        + _flow("f1", "s", "a")
        + _flow("f2", "a", "e"),
    )
    process = _only(path)
    assert _ids(process) == ["s", "orphan", "a", "e"]
    assert process.node("orphan").incoming == () and process.node("orphan").outgoing == ()


def test_sub_process_nodes_are_walked(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        """
    <bpmn:startEvent id="s" />
    <bpmn:subProcess id="sub">
      <bpmn:startEvent id="sub_s" />
      <bpmn:callActivity id="call" />
      <bpmn:sequenceFlow id="g1" sourceRef="sub_s" targetRef="call" />
    </bpmn:subProcess>
    <bpmn:dataObject id="data" />
    <bpmn:endEvent id="e" />
    """
        + _flow("f1", "s", "sub")
        + _flow("f2", "sub", "e"),
    )
    process = _only(path)
    assert _ids(process) == ["s", "sub", "sub_s", "call", "e"]
    assert process.node("call").is_task
    assert [f.id for f in process.flows] == ["g1", "f1", "f2"]


def test_two_processes_in_document_order(tmp_path: Path) -> None:
    path = tmp_path / "two.bpmn"
    path.write_text(
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="d">'
        '<bpmn:process id="one"><bpmn:task id="t1" /></bpmn:process>'
        '<bpmn:process id="two"><bpmn:task id="t2" /></bpmn:process>'
        "</bpmn:definitions>"
    )
    processes = parse_bpmn(path)
    assert [(p.id, p.name, _ids(p)) for p in processes] == [("one", None, ["t1"]), ("two", None, ["t2"])]
    assert processes[1].nodes[0].process_id == "two"


def test_unknown_target_ref_raises(tmp_path: Path) -> None:
    path = _write_bpmn(tmp_path, '<bpmn:startEvent id="s" />' + _flow("f1", "s", "nowhere"))
    with pytest.raises(ResolutionError, match="bpmn:targetRef") as info:
        parse_bpmn(path)
    assert info.value.subject == "p.bpmn#f1"
    assert "nowhere" in info.value.detail


def test_unknown_source_ref_raises(tmp_path: Path) -> None:
    path = _write_bpmn(tmp_path, '<bpmn:endEvent id="e" />' + _flow("f1", "ghost", "e"))
    with pytest.raises(ResolutionError, match="bpmn:sourceRef"):
        parse_bpmn(path)


def test_ref_to_node_of_another_process_raises(tmp_path: Path) -> None:
    path = tmp_path / "two.bpmn"
    path.write_text(
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="d">'
        '<bpmn:process id="one"><bpmn:task id="t1" /></bpmn:process>'
        '<bpmn:process id="two"><bpmn:task id="t2" />'
        '<bpmn:sequenceFlow id="cross" sourceRef="t2" targetRef="t1" /></bpmn:process>'
        "</bpmn:definitions>"
    )
    with pytest.raises(ResolutionError, match="bpmn:targetRef"):
        parse_bpmn(path)


def test_unknown_lane_flow_node_ref_raises(tmp_path: Path) -> None:
    path = _write_bpmn(
        tmp_path,
        '<bpmn:laneSet><bpmn:lane id="l"><bpmn:flowNodeRef>ghost</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>'
        '<bpmn:task id="t" />',
    )
    with pytest.raises(ResolutionError, match="bpmn:flowNodeRef") as info:
        parse_bpmn(path)
    assert info.value.subject == "p.bpmn#l"
