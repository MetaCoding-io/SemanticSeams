"""Pins seams_runtime's model loading, model hash, graph resolvers and typed
errors (M004/S03 T01, D013) against examples/chat-app/chat-app.trig."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from rdflib import Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import (  # noqa: E402
    ContractViolation,
    LifecycleViolation,
    ModelGraph,
    ModelHashMismatch,
    PolicyDenied,
    ResolutionError,
    model_hash,
)
from seams_runtime.model import DEC, ODRL, SEAM  # noqa: E402

CHAT_DIR = ROOT / "examples" / "chat-app"
TRIG = CHAT_DIR / "chat-app.trig"
CHAT = "https://example.org/chat/"
BPMN = CHAT + "chat_bpmn#"


@pytest.fixture(scope="module")
def model():
    return ModelGraph(TRIG)


@pytest.fixture
def fresh():
    """A private copy for tests that mutate the graph."""
    return ModelGraph(TRIG)


def _copy_chat(tmp_path) -> Path:
    dst = tmp_path / "chat-app"
    shutil.copytree(CHAT_DIR, dst)
    return dst / "chat-app.trig"


# ── model hash ──────────────────────────────────────────────────────────────

def test_hash_is_deterministic_and_prefixed(model):
    h = model_hash(TRIG)
    assert h.startswith("sha256:") and len(h) == len("sha256:") + 64
    assert model_hash(TRIG) == h
    assert model.hash == h


def test_hash_of_identical_copy_is_equal(tmp_path):
    assert model_hash(_copy_chat(tmp_path)) == model_hash(TRIG)


@pytest.mark.parametrize("name", ["chat-app.trig", "chat_process.bpmn", "routing.dmn"])
def test_hash_changes_when_one_byte_of_any_covered_file_changes(tmp_path, name):
    trig = _copy_chat(tmp_path)
    target = trig.parent / name
    data = bytearray(target.read_bytes())
    # Flip the case of one letter that no IRI depends on: the TriG's leading
    # comment, or the first name="..." attribute of the BPMN/DMN.
    i = 2 if name.endswith(".trig") else data.index(b'name="') + len(b'name="')
    data[i:i + 1] = bytes(data[i:i + 1]).swapcase()
    target.write_bytes(bytes(data))
    assert model_hash(trig) != model_hash(TRIG)


def test_hash_fails_with_resolution_error_when_payload_missing(tmp_path):
    trig = _copy_chat(tmp_path)
    (trig.parent / "routing.dmn").unlink()
    with pytest.raises(ResolutionError) as exc:
        model_hash(trig)
    assert exc.value.subject == CHAT + "routing_dmn"
    assert exc.value.predicate == str(SEAM.renderPayload)


# ── term helpers ────────────────────────────────────────────────────────────

def test_curie_expands_default_prefix_and_passes_full_iris(model):
    assert model.curie(":send_message_op") == URIRef(CHAT + "send_message_op")
    assert model.curie(CHAT + "x") == URIRef(CHAT + "x")
    assert model.curie("seam:fires") == SEAM.fires


def test_curie_with_unknown_prefix_is_resolution_error(model):
    with pytest.raises(ResolutionError):
        model.curie("nope:x")


def test_task_iri_is_derived_from_the_bpmn_model(model):
    assert model.task_iri("invoke_llm") == URIRef(BPMN + "invoke_llm")


# ── resolvers against the real model ────────────────────────────────────────

def test_decision_binding_route_to_provider(model):
    b = model.decision_binding("route_to_provider")
    assert b.dmn_path == CHAT_DIR / "routing.dmn"
    assert b.decision_id == "routing_decision"
    assert b.decision == URIRef(CHAT + "routing_decision")
    assert b.model == URIRef(CHAT + "routing_dmn")
    assert [(i.variable, i.from_path, i.measure) for i in b.inputs] == [
        ("message_length", "content", DEC.Length),
        ("message_role", "role", None),
    ]
    assert [(o.variable, o.process_variable) for o in b.outputs] == [("Provider", "provider")]


def test_invoke_llm_goes_to_remote_llm_gateway(model):
    op = model.invoked_operation("invoke_llm")
    assert op == URIRef(CHAT + "completion_op")
    c = model.implementing_container(op, ":send_message_process")
    assert c.iri == URIRef(CHAT + "llm_gateway")
    assert c.in_process is False
    assert model.operation_path(op).template == "/v1/chat/completions"


def test_persist_user_msg_is_in_process_on_chat_api(model):
    op = model.invoked_operation("persist_user_msg")
    assert op == URIRef(CHAT + "send_message_op")
    c = model.implementing_container(op, ":send_message_process")
    assert c.iri == URIRef(CHAT + "chat_api")
    assert c.in_process is True
    path = model.operation_path(op)
    assert path.template == "/conversations/{conversation}/messages"
    assert path.variables == ("conversation",)
    assert path.mappings[0].property == "id"


def test_fired_transition_and_transitions_from(model):
    iri, src, dst, trigger = model.fired_transition("persist_user_msg")
    assert (iri, src, dst, trigger) == (URIRef(CHAT + "t_send"), "composing", "sending", "send")
    errors = model.transitions_from("sending", "error")
    assert [t.iri for t in errors] == [URIRef(CHAT + "t_fail_send")]
    assert errors[0].to_state == "failed"
    assert model.transitions_from("complete") == []


def test_read_and_written_shapes(model):
    assert model.read_shapes("route_to_provider") == [URIRef(CHAT + "MessageShape")]
    assert model.written_shapes("persist_user_msg") == [URIRef(CHAT + "MessageShape")]
    assert model.written_shapes("invoke_llm") == []


def test_process_and_correlation_key(model):
    p = model.process_for(":send_message_process")
    assert p.model == URIRef(CHAT + "chat_bpmn")
    assert p.bpmn_path == CHAT_DIR / "chat_process.bpmn"
    assert model.correlation_key(p.iri) == "conversation"


def test_channel_for_stream_complete_event(model):
    ch = model.channel_for_event("stream_complete_event")
    assert (ch.iri, ch.label, ch.event_name) == (URIRef(CHAT + "stream_events"), "stream.events", "token")


def test_lifecycle_for_message_shape(model):
    lc = model.lifecycle_for(":MessageShape")
    assert lc.iri == URIRef(CHAT + "message_lifecycle")
    assert lc.initial == "composing"
    assert sorted(lc.states.values()) == ["complete", "composing", "failed", "sending", "streaming"]


def test_policies_for_send_message_op(model):
    [policy] = model.policies_for(":send_message_op")
    assert policy.iri == URIRef(CHAT + "user_send_policy")
    [perm] = policy.permissions
    assert perm.target == URIRef(CHAT + "send_message_op")
    assert perm.action == ODRL.use
    assert perm.assignee == URIRef(CHAT + "authenticated_user")
    assert ODRL.PartyCollection in perm.assignee_types


def test_shape_graph_is_the_data_shapes_graph(model):
    g = model.shape_graph()
    assert g.identifier == URIRef("urn:seams:graph:model:chat_data_shapes")
    assert (URIRef(CHAT + "MessageShape"), None, None) in g


# ── negatives: missing hops name the IRI and predicate ──────────────────────

def test_missing_decided_by(fresh):
    task = fresh.task_iri("route_to_provider")
    fresh.ds.remove((task, SEAM.decidedBy, None))
    with pytest.raises(ResolutionError) as exc:
        fresh.decision_binding("route_to_provider")
    assert exc.value.subject == str(task)
    assert exc.value.predicate == str(SEAM.decidedBy)
    assert str(task) in str(exc.value) and str(SEAM.decidedBy) in str(exc.value)


def test_missing_payload_element(fresh):
    decision = URIRef(CHAT + "routing_decision")
    fresh.ds.remove((decision, DEC.payloadElement, None))
    with pytest.raises(ResolutionError) as exc:
        fresh.decision_binding("route_to_provider")
    assert exc.value.subject == str(decision)
    assert exc.value.predicate == str(DEC.payloadElement)


def test_payload_element_not_in_dmn(fresh):
    decision = URIRef(CHAT + "routing_decision")
    ctx = next(c for _s, _p, _o, c in fresh.ds.quads((decision, DEC.payloadElement, None)))
    fresh.ds.remove((decision, DEC.payloadElement, None))
    fresh.ds.graph(ctx).add((decision, DEC.payloadElement, Literal("nope")))
    with pytest.raises(ResolutionError) as exc:
        fresh.decision_binding("route_to_provider")
    assert exc.value.subject == str(decision)
    assert exc.value.predicate == str(DEC.payloadElement)
    assert "'nope'" in str(exc.value) and "routing_decision" in str(exc.value)


def test_missing_invokes_and_fires(model):
    with pytest.raises(ResolutionError) as exc:
        model.invoked_operation("route_to_provider")
    assert exc.value.predicate == str(SEAM.invokes)
    assert exc.value.subject == BPMN + "route_to_provider"
    with pytest.raises(ResolutionError) as exc:
        model.fired_transition("stream_complete_event")
    assert exc.value.predicate == str(SEAM.fires)


def test_unexposed_operation_and_ungoverned_operation(model):
    with pytest.raises(ResolutionError) as exc:
        model.implementing_container(":no_such_op")
    assert exc.value.predicate == str(SEAM.exposes)
    with pytest.raises(ResolutionError) as exc:
        model.policies_for(":completion_op")
    assert exc.value.subject == CHAT + "completion_op"
    assert exc.value.predicate == str(SEAM.governedBy)


def test_process_for_non_process(model):
    with pytest.raises(ResolutionError) as exc:
        model.process_for(":send_message_op")
    assert "proc:Process" in str(exc.value)


def test_no_shape_graph(fresh):
    from rdflib.namespace import RDF, SH

    fresh.ds.remove((None, RDF.type, SH.NodeShape))
    with pytest.raises(ResolutionError):
        fresh.shape_graph()


# ── typed errors ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("err, status", [
    (ResolutionError(URIRef(CHAT + "x"), SEAM.fires, "d"), 500),
    (ModelHashMismatch("sha256:a", "sha256:b", TRIG), 500),
    (ContractViolation(URIRef(CHAT + "MessageShape"),
                       [{"path": "content", "constraint": "MinCountConstraintComponent",
                         "value": None, "message": "m"}],
                       operation=URIRef(CHAT + "send_message_op")), 422),
    (LifecycleViolation(URIRef(CHAT + "m1"), URIRef(CHAT + "t_send"), "complete", "composing"), 409),
    (PolicyDenied(URIRef(CHAT + "user_send_policy"), URIRef(CHAT + "send_message_op"), 401, "no identity"), 401),
    (PolicyDenied(URIRef(CHAT + "user_send_policy"), None, 403, "no permission"), 403),
])
def test_errors_are_json_safe_with_http_status(err, status):
    d = err.to_dict()
    assert err.http_status == status == d["http_status"]
    assert d["type"] == type(err).__name__
    assert d["message"] == str(err)
    json.dumps(d)


def test_error_messages_name_their_terms():
    v = LifecycleViolation(CHAT + "m1", CHAT + "t_send", "complete", "composing")
    assert all(s in str(v) for s in ("t_send", "complete", "composing"))
    c = ContractViolation(CHAT + "MessageShape", [{"path": "content", "constraint": "MaxLength"}])
    assert "MessageShape" in str(c) and "content: MaxLength" in str(c)
    assert c.to_dict()["results"][0]["path"] == "content"


def test_policy_denied_rejects_other_statuses():
    with pytest.raises(ValueError):
        PolicyDenied("p", "o", 500, "x")
