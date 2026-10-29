"""Pins seams_runtime's SHACL contract validation and lifecycle guard
(M004/S03 T02, ADR-0007) against examples/chat-app/chat-app.trig, including
D015: :content sh:maxLength 16000 keeps routing.dmn's `> 4000` rule reachable."""

import json
import sys
from pathlib import Path

import pytest
from rdflib import URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import (  # noqa: E402
    ContractViolation,
    LifecycleGuard,
    LifecycleViolation,
    ModelGraph,
    ResolutionError,
    validate,
)
from seams_runtime.contracts import MAX_ECHO, shape_contract, to_rdf  # noqa: E402

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHAT = "https://example.org/chat/"
SHAPE = CHAT + "MessageShape"


@pytest.fixture(scope="module")
def model():
    return ModelGraph(TRIG)


def violation(model, payload) -> ContractViolation:
    with pytest.raises(ContractViolation) as exc:
        validate(model, ":MessageShape", payload)
    return exc.value


def only(v: ContractViolation, path: str) -> dict:
    hits = [r for r in v.results if r["path"] == path]
    assert len(hits) == 1, v.results
    return hits[0]


# ── contracts ───────────────────────────────────────────────────────────────


def test_valid_payload_passes_and_normalises(model):
    assert validate(model, ":MessageShape", {"content": "hi", "role": "user"}) == {
        "content": "hi", "role": "user",
    }


def test_full_payload_with_status_and_timestamp_passes(model):
    payload = {"content": "hi", "role": "user", "status": "sending",
               "timestamp": "2026-10-28T12:00:00Z"}
    assert validate(model, ":MessageShape", payload) == payload


def test_multidict_single_values_become_str(model):
    class MultiDict(dict):
        def getlist(self, key):
            return self[key]

    out = validate(model, ":MessageShape", MultiDict(content=["hi"], role=["user"]))
    assert out == {"content": "hi", "role": "user"}
    assert all(isinstance(v, str) for v in out.values())


def test_omitted_field_takes_its_sh_default_value(model):
    # the compose form posts only content; :role's sh:defaultValue "user" fills it
    assert validate(model, ":MessageShape", {"content": "hi"}) == {"content": "hi", "role": "user"}
    assert validate(model, ":MessageShape", {"content": "hi", "role": "assistant"})["role"] == "assistant"
    assert shape_contract(model, ":MessageShape").defaults == {"role": "user"}


def test_default_value_does_not_satisfy_other_constraints(model):
    # only :role has a default: a payload with no content still fails sh:minCount
    v = violation(model, {})
    assert only(v, "content")["constraint"] == "MinCountConstraintComponent"


def test_missing_content_is_min_count(model):
    v = violation(model, {"role": "user"})
    assert v.shape == SHAPE
    r = only(v, "content")
    assert r["constraint"] == "MinCountConstraintComponent"
    assert r["shape"] == SHAPE


def test_content_over_16000_is_max_length(model):
    v = violation(model, {"content": "x" * 16001})
    r = only(v, "content")
    assert (r["shape"], r["constraint"]) == (SHAPE, "MaxLengthConstraintComponent")
    assert len(r["value"]) < MAX_ECHO + 40  # the 16001-char value is not echoed whole


def test_content_at_16000_passes(model):
    validate(model, ":MessageShape", {"content": "x" * 16000})


def test_long_user_message_validates_d015(model):
    """routing.dmn sends `> 4000` to the long-context provider; validation must
    let such a message through, or that rule is unreachable."""
    out = validate(model, ":MessageShape", {"content": "x" * 4001, "role": "user"})
    assert len(out["content"]) == 4001


def test_status_outside_lifecycle_labels_is_in(model):
    r = only(violation(model, {"content": "a", "status": "bogus"}), "status")
    assert (r["shape"], r["constraint"], r["value"]) == (SHAPE, "InConstraintComponent", "bogus")


def test_bad_timestamp_names_timestamp_and_datatype(model):
    v = violation(model, {"content": "a", "timestamp": "notadate"})
    r = only(v, "timestamp")
    assert (r["shape"], r["constraint"], r["value"]) == (SHAPE, "DatatypeConstraintComponent", "notadate")


def test_wrong_python_type_is_datatype(model):
    r = only(violation(model, {"content": 5}), "content")
    assert r["constraint"] == "DatatypeConstraintComponent"


def test_unknown_field_is_rejected_not_dropped(model):
    v = violation(model, {"content": "a", "author": "mallory"})
    r = only(v, "author")
    assert (r["shape"], r["constraint"]) == (SHAPE, "unknown-field")
    assert "author" in str(v)


def test_multiple_values_trip_max_count(model):
    class MultiDict(dict):
        def getlist(self, key):
            return self[key]

    v = violation(model, MultiDict(content=["a"], role=["user", "assistant"]))
    assert only(v, "role")["constraint"] == "MaxCountConstraintComponent"


def test_violation_to_dict_is_json_with_422(model):
    v = violation(model, {"role": "user", "status": "bogus", "extra": 1})
    d = json.loads(json.dumps(v.to_dict()))
    assert d["http_status"] == 422
    assert d["type"] == "ContractViolation"
    assert d["shape"] == SHAPE
    assert {r["path"] for r in d["results"]} == {"extra"}  # boundary check runs first


def test_operation_is_carried_into_the_violation(model):
    with pytest.raises(ContractViolation) as exc:
        validate(model, ":MessageShape", {}, operation=CHAT + "send_message_op")
    assert exc.value.operation == CHAT + "send_message_op"
    assert "send_message_op" in str(exc.value)


def test_shape_contract_is_cached_per_model_and_standalone(model):
    c = shape_contract(model, ":MessageShape")
    assert shape_contract(model, URIRef(SHAPE)) is c
    assert set(c.fields) == {"content", "role", "status", "timestamp"}
    # sh:in's rdf:List cells were copied into the standalone shapes graph.
    assert len(list(c.graph.subjects())) > 5
    other = ModelGraph(TRIG)
    assert shape_contract(other, ":MessageShape") is not c


def test_to_rdf_builds_one_node_graph(model):
    g, focus, normalised = to_rdf(model, ":MessageShape", {"content": "hi"})
    assert str(focus).startswith("urn:uuid:")
    assert set(g.subjects()) == {focus}
    assert normalised == {"content": "hi", "role": "user"}  # role's sh:defaultValue


def test_unknown_shape_is_resolution_error(model):
    with pytest.raises(ResolutionError) as exc:
        validate(model, ":NoSuchShape", {"content": "a"})
    assert "NoSuchShape" in str(exc.value)


# ── lifecycle ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def guard(model):
    return LifecycleGuard(model)


def test_initial_state_allows_send(guard):
    tr = guard.check(":MessageShape", None, ":t_send")
    assert tr.iri == URIRef(CHAT + "t_send")
    assert guard.apply(":MessageShape", None, ":t_send") == "sending"
    assert guard.apply(":MessageShape", "composing", ":t_send") == "sending"


def test_send_from_complete_is_lifecycle_violation(guard):
    with pytest.raises(LifecycleViolation) as exc:
        guard.check(":MessageShape", "complete", ":t_send")
    msg = str(exc.value)
    for term in ("t_send", "complete", "composing"):
        assert term in msg
    d = exc.value.to_dict()
    assert d["http_status"] == 409
    assert (d["current_state"], d["expected_from"]) == ("complete", "composing")


def test_on_error_resolves_from_graph(guard):
    assert guard.on_error(":MessageShape", "sending").iri == URIRef(CHAT + "t_fail_send")
    assert guard.on_error(":MessageShape", "streaming").iri == URIRef(CHAT + "t_fail_stream")
    assert guard.on_error(":MessageShape", "complete") is None
    assert guard.on_error(":MessageShape", None) is None  # composing has no error exit


def test_transition_of_another_lifecycle_is_resolution_error(guard):
    with pytest.raises(ResolutionError):
        guard.check(":MessageShape", None, ":no_such_transition")


def test_shape_without_lifecycle_is_resolution_error(guard):
    with pytest.raises(ResolutionError) as exc:
        guard.check(":ConversationShape", None, ":t_send")
    assert "lifecycle" in str(exc.value)
