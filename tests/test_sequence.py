"""The as-designed sequence deriver (backlog U1, R008, D047): seams_gen.sequence
against the chat app's send_message event, its golden, and the gaps it
reports when a fact it needs is removed from an in-memory copy of the model;
the expenses chapter-08 submit_expense event, one golden per gateway path;
and the loop and parallel-fork gaps of synthetic BPMN."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import seams
from rdflib import RDFS, URIRef

from seams_gen import GeneratorError
from seams_gen.sequence import derive, file_name, render

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "examples" / "chat-app"
CHAT = CHAT_DIR / "chat-app.trig"
GOLDEN = ROOT / "docs" / "generation" / "sequences" / "chat-app" / "send_message.mmd"
EXPENSES = ROOT / "examples" / "expenses"
EXPENSE_GOLDENS = ROOT / "docs" / "generation" / "sequences" / "expenses"
EXPENSE_NAMES = [
    "submit_expense--auto.mmd",
    "submit_expense--manager--approved.mmd",
    "submit_expense--manager--rejected.mmd",
    "submit_expense--finance--approved.mmd",
    "submit_expense--finance--rejected.mmd",
]

#: The words a message line adds itself; everything else comes from a graph term.
FIXED = {"Note", "over", "start", "writes", "fragment", "DMN", "policy", "returns", "deltas", "event"}


@pytest.fixture(scope="module")
def chat():
    return seams.load(CHAT)


@pytest.fixture(scope="module")
def diagram(chat):
    (d,) = derive(chat, ":send_message")
    return d


def _mutated(tmp_path: Path, old: str, new: str = ""):
    """The chat app with ``old`` replaced in its TriG, BPMN and DMN alongside."""
    text = CHAT.read_text(encoding="utf-8")
    assert old in text, old
    (tmp_path / "chat-app.trig").write_text(text.replace(old, new), encoding="utf-8")
    for payload in ("chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_DIR / payload, tmp_path / payload)
    (d,) = derive(seams.load(tmp_path / "chat-app.trig"), ":send_message")
    return d, render(d)


def test_golden(diagram):
    assert file_name(diagram) == "send_message.mmd"
    assert render(diagram) == GOLDEN.read_bytes().decode("utf-8")


def test_header_and_no_gaps(diagram):
    lines = render(diagram).splitlines()
    assert lines[:3] == [
        "sequenceDiagram",
        "    %% derived from https://example.org/chat/send_message",
        "    %% path: single",
    ]
    assert diagram.gaps == ()
    assert "%% gap:" not in render(diagram)


def test_every_message_traces_to_the_model(chat, diagram):
    ds = chat.ds
    for message in diagram.messages:
        allowed = set(FIXED)
        for term in message.terms:
            assert isinstance(term, URIRef)
            assert (term, None, None) in ds or (None, None, term) in ds, term
            allowed.add(seams.local_name(term))
            allowed.update(re.findall(r"\w+", str(ds.value(term, RDFS.label) or "")))
            allowed.update(re.findall(r"\w+", " ".join(str(o) for o in ds.objects(term, None))))
        words = re.findall(r"[A-Za-z_]\w*", message.line)
        assert set(words) <= allowed, (message.line, set(words) - allowed)


def test_participants_and_delta_arrow(diagram):
    ids = [p.id for p in diagram.participants]
    assert ids == ["authenticated_user", "chat_ui", "chat_api", "message_db", "llm_gateway"]
    assert diagram.participants[0].actor
    lines = [m.line for m in diagram.messages]
    call = lines.index("chat_api->>llm_gateway: invoke_llm, completion_op [MessageShape]")
    assert lines[call + 1] == "llm_gateway-->>chat_api: completion_op returns [MessageShape]"
    assert lines[call + 2] == "chat_api-->>chat_ui: stream_events (token deltas)"
    assert "chat_api-->>chat_ui: stream_events (stream.events event)" == lines[-1]


def test_no_fragments(diagram):
    text = render(diagram)
    for keyword in ("alt", "opt", "par", "loop", "end"):
        assert not re.search(rf"^\s*{keyword}\b", text, re.M), keyword


def test_unknown_event_raises(chat):
    for name in (":no_such_event", "no_such_event", "https://example.org/chat/no_such_event", "nope:x"):
        with pytest.raises(GeneratorError, match="no such ifml:Event"):
            derive(chat, name)


def test_local_name_and_full_iri_select_the_same_event(chat, diagram):
    assert render(derive(chat, "send_message")[0]) == render(diagram)
    assert render(derive(chat, "https://example.org/chat/send_message")[0]) == render(diagram)


def test_missing_stored_in_is_a_gap(tmp_path):
    d, text = _mutated(tmp_path, "    :MessageShape seam:storedIn :message_db .\n")
    assert "MessageShape written by persist_user_msg has no seam:storedIn" in d.gaps
    assert "MessageShape written by persist_response has no seam:storedIn" in d.gaps
    assert "    %% gap: MessageShape written by persist_user_msg has no seam:storedIn" in text
    assert "message_db" not in text


def test_invoked_operation_without_exposing_container_is_a_gap(tmp_path):
    d, text = _mutated(
        tmp_path,
        "    :llm_gateway seam:exposes :completion_op ;\n        seam:deployedTo :app01 .",
        "    :llm_gateway seam:deployedTo :app01 .",
    )
    assert "completion_op invoked by invoke_llm has no seam:exposes container" in d.gaps
    assert "llm_gateway" not in text


def test_missing_publishes_to_draws_no_delta_arrow(tmp_path):
    d, text = _mutated(
        tmp_path,
        "        seam:publishesTo :stream_events ;\n        seam:reads :MessageShape ;\n",
        "        seam:reads :MessageShape ;\n",
    )
    assert "deltas" not in text
    assert "stream_events (stream.events event)" in text
    assert d.gaps == ()


def test_channel_without_consumer_is_a_gap(tmp_path):
    d, text = _mutated(tmp_path, ":message_thread_op ,\n                      :stream_events ;", ":message_thread_op ;")
    assert "stream_events published by invoke_llm has no seam:consumes container or subscriber" in d.gaps
    assert "stream_events published by stream_complete_event has no seam:consumes container or subscriber" in d.gaps
    assert "stream_events (" not in text


def test_missing_policy_is_an_actor_gap(tmp_path):
    # The actor comes from the policies on the event and on its operation
    # (research note section 2), so both edges go.
    old = (
        "        seam:submitsTo :send_message_op ;\n        seam:governedBy :user_send_policy .\n\n"
        "    # Operation → component whose partial the UIFragment response renders\n"
        "    :send_message_op seam:rendersComponent :message_thread ;\n        seam:governedBy :user_send_policy ."
    )
    new = "        seam:submitsTo :send_message_op .\n\n    :send_message_op seam:rendersComponent :message_thread ."
    d, text = _mutated(tmp_path, old, new)
    assert "send_message has no seam:governedBy policy or on send_message_op, so no actor" in d.gaps
    assert not any(p.actor for p in d.participants)
    assert d.messages[0].line == "chat_ui->>chat_ui: send_message"


def test_unlifted_task_is_a_gap(tmp_path):
    text = CHAT.read_text(encoding="utf-8")
    old = "<https://example.org/chat/chat_bpmn#route_to_provider> a proc:BusinessRuleTask ;"
    assert old in text
    d, rendered = _mutated(tmp_path, old, "<https://example.org/chat/chat_bpmn#route_to_provider>")
    assert "BPMN node route_to_provider has no graph element" in d.gaps
    assert "routing_decision" not in rendered


# ── gateway paths: expenses chapter 08 ──


@pytest.fixture(scope="module")
def expense_diagrams():
    return derive(seams.load(EXPENSES / "chapter-08" / "expenses.trig"), ":submit_expense")


def _lines(d):
    return [m.line for m in d.messages]


def test_expenses_one_golden_per_path(expense_diagrams):
    assert [file_name(d) for d in expense_diagrams] == EXPENSE_NAMES
    for d in expense_diagrams:
        assert render(d) == (EXPENSE_GOLDENS / file_name(d)).read_bytes().decode("utf-8"), file_name(d)
        assert d.gaps == ()
    assert sorted(p.name for p in EXPENSE_GOLDENS.iterdir()) == sorted(EXPENSE_NAMES)


def test_expenses_path_header(expense_diagrams):
    lines = render(expense_diagrams[1]).splitlines()
    assert lines[2] == "    %% path: manager, approved"
    assert expense_diagrams[1].path == ("manager", "approved")
    assert expense_diagrams[1].name == "submit_expense--manager--approved"
    assert "Note over expense_api: Route?: manager" in _lines(expense_diagrams[1])
    assert "Note over expense_api: Decision?: approved" in _lines(expense_diagrams[1])


def test_expenses_no_fragments(expense_diagrams):
    for d in expense_diagrams:
        for keyword in ("alt", "opt", "par", "loop", "end"):
            assert not re.search(rf"^\s*{keyword}\b", render(d), re.M), (file_name(d), keyword)


def test_manager_paths_have_manager_and_store(expense_diagrams):
    for d in expense_diagrams:
        ids = [p.id for p in d.participants]
        assert "expense_db" in ids
        if "manager" in d.path:
            assert "manager" in ids
            assert next(p for p in d.participants if p.id == "manager").actor
            assert "manager->>employee_portal: approve_expense on approve_form" in _lines(d)
            assert "employee_portal->>expense_api: complete approve_expense [ApprovalShape]" in _lines(d)
        else:
            assert "manager" not in ids


def test_approved_paths_start_the_payout_process(expense_diagrams):
    for d in expense_diagrams:
        started = "expense_api-->>expense_api: payouts starts payout_process" in _lines(d)
        assert started == ("rejected" not in d.path), file_name(d)


def test_chapter_07_reports_stored_in_gaps():
    for d in derive(seams.load(EXPENSES / "chapter-07" / "expenses.trig"), ":submit_expense"):
        assert "ExpenseShape written by persist_expense has no seam:storedIn" in d.gaps
        assert not any("->>expense_db" in line for line in _lines(d))
        assert "%% gap: ExpenseShape written by persist_expense has no seam:storedIn" in render(d)


def test_user_task_without_policy_or_form_is_a_gap(tmp_path):
    src = EXPENSES / "chapter-08"
    text = (src / "expenses.trig").read_text(encoding="utf-8")
    for old in (
        "    <https://example.org/expenses/approval_bpmn#approve_expense> seam:governedBy :manager_approval_policy .\n",
        "                          odrl:target <https://example.org/expenses/approval_bpmn#approve_expense> ;\n",
        "        seam:completedOn :approve_form ;\n",
    ):
        assert old in text, old
        text = text.replace(old, "")
    for payload in src.iterdir():
        if payload.suffix in (".bpmn", ".dmn"):
            shutil.copy(payload, tmp_path / payload.name)
    (tmp_path / "expenses.trig").write_text(text, encoding="utf-8")
    d = derive(seams.load(tmp_path / "expenses.trig"), ":submit_expense")[1]
    assert "user task approve_expense has no seam:governedBy policy with an odrl:assignee, so no actor" in d.gaps
    assert "user task approve_expense has no seam:completedOn form" in d.gaps
    assert "manager" not in [p.id for p in d.participants]


# ── synthetic BPMN: loops and parallel forks ──

_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="defs"
                  targetNamespace="https://example.org/chat/chat_bpmn">
  <bpmn:process id="send_message_process" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:{tag} id="g" name="G"><bpmn:incoming>f1</bpmn:incoming><bpmn:incoming>f_back</bpmn:incoming>
      <bpmn:outgoing>f_a</bpmn:outgoing><bpmn:outgoing>f_b</bpmn:outgoing></bpmn:{tag}>
    <bpmn:task id="a"><bpmn:incoming>f_a</bpmn:incoming><bpmn:outgoing>f_back</bpmn:outgoing></bpmn:task>
    <bpmn:endEvent id="e"><bpmn:incoming>f_b</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="g" />
    <bpmn:sequenceFlow id="f_a" name="again" sourceRef="g" targetRef="a" />
    <bpmn:sequenceFlow id="f_back" sourceRef="a" targetRef="g" />
    <bpmn:sequenceFlow id="f_b" sourceRef="g" targetRef="e" />
  </bpmn:process>
</bpmn:definitions>
"""


def _synthetic(tmp_path: Path, tag: str):
    shutil.copy(CHAT, tmp_path / "chat-app.trig")
    shutil.copy(CHAT_DIR / "routing.dmn", tmp_path / "routing.dmn")
    (tmp_path / "chat_process.bpmn").write_text(_BPMN.format(tag=tag), encoding="utf-8")
    return derive(seams.load(tmp_path / "chat-app.trig"), ":send_message")


def test_cycle_reports_a_loop_gap_and_terminates(tmp_path):
    # Round the loop once, then the second f_a ends that path.
    diagrams = _synthetic(tmp_path, "exclusiveGateway")
    assert [d.name for d in diagrams] == ["send_message--again--again", "send_message--again--f_b", "send_message--f_b"]
    looped = diagrams[0]
    assert "loop at f_a" in looped.gaps
    assert "%% gap: loop at f_a" in render(looped)
    assert _lines(looped).count("Note over chat_api: G: again") == 2
    assert all("loop at" not in g for d in diagrams[1:] for g in d.gaps)


def test_parallel_gateway_is_a_gap(tmp_path):
    (d,) = _synthetic(tmp_path, "parallelGateway")
    assert "parallel gateway g forks; only flow again is drawn, not f_b" in d.gaps
    assert "loop at f_a" in d.gaps
    assert d.name == "send_message" and d.path == ()
