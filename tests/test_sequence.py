"""The as-designed sequence deriver (backlog U1, R008, D047): seams_gen.sequence
against the chat app's send_message event, its golden, and the gaps it
reports when a fact it needs is removed from an in-memory copy of the model."""

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
    d, text = _mutated(
        tmp_path,
        "        seam:submitsTo :send_message_op ;\n        seam:governedBy :user_send_policy .",
        "        seam:submitsTo :send_message_op .",
    )
    assert "send_message has no seam:governedBy policy, so no actor" in d.gaps
    assert not any(p.actor for p in d.participants)
    assert d.messages[0].line == "chat_ui->>chat_ui: send_message"


def test_unlifted_task_is_a_gap(tmp_path):
    text = CHAT.read_text(encoding="utf-8")
    old = "<https://example.org/chat/chat_bpmn#route_to_provider> a proc:BusinessRuleTask ;"
    assert old in text
    d, rendered = _mutated(tmp_path, old, "<https://example.org/chat/chat_bpmn#route_to_provider>")
    assert "BPMN node route_to_provider has no graph element" in d.gaps
    assert "routing_decision" not in rendered
