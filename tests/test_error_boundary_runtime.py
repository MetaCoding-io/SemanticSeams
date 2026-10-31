"""Error boundaries in the runtime (ADR-0013, M014/S04 T03).

A lifted proc:ErrorBoundaryEvent is joined to its BPMN boundary, the task it is
attached to and the error it seam:catches when the runtime loads; a graph that
disagrees with the XML raises ResolutionError naming the boundary. At run time
a declared error the task's operation raises (a Python handler's
OperationError, or an HTTP endpoint's problem+json answer) is routed down the
boundary that catches it, and the trace rows and spans record the code, the
status and the boundary. With no boundary the instance fails as before, its
error naming the code and the status.

The model is the chat app with two error boundaries: "Throttled" on Persist
User Message (:send_message_op's send-throttled), whose path records the
problem, and "Completion down" on Invoke LLM (:completion_op's
completion-down), which goes straight to an end event.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import rdflib
from seams.bpmn import parse_bpmn

from seams_runtime import ResolutionError, Runtime
from seams_runtime.model import COMM, SEAM, ModelGraph
from seams_runtime.telemetry import element_attributes
from tests.test_error_vocabulary import ontology, violating_shapes
from tests.test_runtime_implementation import (
    CHAT,
    CHAT_DIR,
    LLM_IMPL,
    PROCESS,
    SHORT,
    FakeEndpoint,
    FakeLLM,
    chat_model,
    handlers_package,
    load,
    python_handler,
    row,
    run,
)

BPMN = "https://example.org/chat/chat_bpmn#"
PERSIST, INVOKE = BPMN + "persist_user_msg", BPMN + "invoke_llm"
THROTTLED, DOWN = BPMN + "throttled_boundary", BPMN + "completion_down_boundary"
SEND_OP, COMPLETION_OP = CHAT + "send_message_op", CHAT + "completion_op"
PROBLEM_JSON = "application/problem+json"

# ── the model ────────────────────────────────────────────────────────────────

BPMN_ERRORS = """  <bpmn:error id="send_throttled_error" name="Too many messages" errorCode="send-throttled" />
  <bpmn:error id="completion_down_error" name="Completion unavailable" errorCode="completion-down" />
  <bpmn:process id="send_message_process\""""
BPMN_BOUNDARIES = """    <bpmn:boundaryEvent id="throttled_boundary" name="Throttled" attachedToRef="persist_user_msg">
      <bpmn:errorEventDefinition errorRef="send_throttled_error" />
    </bpmn:boundaryEvent>
    <bpmn:serviceTask id="record_problem" name="Record Problem" />
    <bpmn:endEvent id="throttled_end" name="Throttled" />
    <bpmn:boundaryEvent id="completion_down_boundary" name="Completion down" attachedToRef="invoke_llm">
      <bpmn:errorEventDefinition errorRef="completion_down_error" />
    </bpmn:boundaryEvent>
    <bpmn:endEvent id="completion_down_end" name="Completion down" />
    <bpmn:sequenceFlow id="flow_to_record" sourceRef="throttled_boundary" targetRef="record_problem" />
    <bpmn:sequenceFlow id="flow_to_throttled_end" sourceRef="record_problem" targetRef="throttled_end" />
    <bpmn:sequenceFlow id="flow_to_down_end" sourceRef="completion_down_boundary" targetRef="completion_down_end" />
  </bpmn:process>"""

PROC_ANCHOR = '    :chat_bpmn a seam:Model ; rdfs:label "Message Processing (BPMN)" .\n'
LIFTED = """
    <https://example.org/chat/chat_bpmn#throttled_boundary> a proc:ErrorBoundaryEvent ;
        rdfs:label "Throttled" ;
        seam:inModel :chat_bpmn .
    <https://example.org/chat/chat_bpmn#completion_down_boundary> a proc:ErrorBoundaryEvent ;
        rdfs:label "Completion down" ;
        seam:inModel :chat_bpmn .
    <https://example.org/chat/chat_bpmn#record_problem> a proc:ServiceTask ;
        rdfs:label "Record Problem" ;
        seam:inModel :chat_bpmn .
"""
SEAMS_ANCHOR = "<urn:seams:graph:seams> {\n"
ERRORS = """
    :send_message_op hydra:possibleStatus :send_throttled , :send_rejected .
    :send_throttled a hydra:Status ; rdfs:label "Too many messages" ;
        hydra:statusCode 429 ; comm:errorCode "send-throttled" ;
        seam:returnsShape :SendProblemShape .
    :send_rejected a hydra:Status ; rdfs:label "Message rejected" ;
        hydra:statusCode 422 ; comm:errorCode "send-rejected" ;
        seam:returnsShape :SendProblemShape .
    :completion_op hydra:possibleStatus :completion_down .
    :completion_down a hydra:Status ; rdfs:label "Completion unavailable" ;
        hydra:statusCode 503 ; comm:errorCode "completion-down" ;
        seam:returnsShape :SendProblemShape .
    <https://example.org/chat/chat_bpmn#throttled_boundary> seam:catches :send_throttled .
    <https://example.org/chat/chat_bpmn#completion_down_boundary> seam:catches :completion_down .
    <https://example.org/chat/chat_bpmn#record_problem> seam:writes :SendProblemShape .
    :SendProblemShape seam:storedIn :message_db .
"""
SHAPES_ANCHOR = '    :chat_data_shapes a seam:Model ; rdfs:label "Chat Data Model" .\n'
SHAPES = """
    :SendProblemShape a sh:NodeShape ; rdfs:label "Send problem" ;
        sh:property [ sh:path comm:title ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:status ; sh:datatype xsd:integer ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:detail ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
                    [ sh:path :limit ; sh:datatype xsd:integer ; sh:maxCount 1 ] ;
        seam:inModel :chat_data_shapes .
"""

HTTP = (LLM_IMPL, ':completion_impl a comm:HTTPEndpoint ; rdfs:label "completion API" .')

THROTTLE = """
from seams_runtime import OperationError


def send(entity):
    # "raise <code> [<limit>]" raises that error; anything else is sent
    words = entity["content"].split()
    if words[:1] == ["raise"]:
        extensions = {} if len(words) < 3 else {"limit": int(words[2]) if words[2].isdigit() else words[2]}
        raise OperationError(words[1], "slow down", **extensions)
    return dict(entity)
"""


def boundary_model(
    tmp_path: Path, *edits: tuple[str, str], bpmn_edits: tuple[tuple[str, str], ...] = (), handler: bool = True
) -> Path:
    """The chat app plus the two boundaries, then ``edits`` to the TriG and
    ``bpmn_edits`` to the BPMN, each applied once. ``handler`` serves
    :send_message_op with ``send.send`` (THROTTLE)."""
    extra = [
        (PROC_ANCHOR, PROC_ANCHOR + LIFTED),
        (SEAMS_ANCHOR, SEAMS_ANCHOR + ERRORS),
        (SHAPES_ANCHOR, SHAPES_ANCHOR + SHAPES),
    ]
    if handler:
        extra.append(python_handler("send.send"))
    trig = chat_model(tmp_path, *extra)
    _edit(trig, edits)
    bpmn = trig.parent / "chat_process.bpmn"
    _edit(bpmn, (('  <bpmn:process id="send_message_process"', BPMN_ERRORS), ("  </bpmn:process>", BPMN_BOUNDARIES)))
    _edit(bpmn, bpmn_edits)
    if handler:
        handlers_package(trig.parent / "handlers", {"send.py": THROTTLE})
    return trig


def _edit(path: Path, edits) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def says(content: str) -> dict:
    return {**SHORT, "content": content}


def _union(path: Path) -> rdflib.Graph:
    g = ontology()
    for triple in rdflib.Dataset().parse(path, format="trig").triples((None, None, None)):
        g.add(triple)
    return g


def test_the_model_passes_the_shapes_as_the_chat_app_does(tmp_path):
    assert violating_shapes(_union(boundary_model(tmp_path))) == violating_shapes(_union(CHAT_DIR / "chat-app.trig"))


# ── the seams views ──────────────────────────────────────────────────────────


def test_the_views_join_each_boundary_to_its_task_and_error(tmp_path):
    model = ModelGraph.load(boundary_model(tmp_path))
    process = model.processes.by_iri(model.curie(PROCESS))
    found = {
        (str(b.iri), str(b.task.iri), str(b.operation.iri), str(b.status.iri), b.code)
        for b in process.error_boundaries()
    }
    assert found == {
        (THROTTLED, PERSIST, SEND_OP, CHAT + "send_throttled", "send-throttled"),
        (DOWN, INVOKE, COMPLETION_OP, CHAT + "completion_down", "completion-down"),
    }
    node = next(n for n in process.nodes() if str(n.iri) == THROTTLED)
    assert node.kind == "ErrorBoundaryEvent" and str(node.catches.iri) == CHAT + "send_throttled"
    assert node.node.attached_to == "persist_user_msg" and node.node.error_ref == "send_throttled_error"
    (bp,) = parse_bpmn(process.bpmn_path)
    assert bp.error("send_throttled_error").code == "send-throttled" and bp.error("nope") is None


# ── load: the graph and the XML must agree ───────────────────────────────────


def test_the_chat_app_has_no_boundaries(tmp_path):
    assert load(chat_model(tmp_path), tmp_path).boundaries == {}


def test_boundaries_resolve_at_load(tmp_path):
    rt = load(boundary_model(tmp_path), tmp_path)
    assert {(str(t), c): str(b.iri) for (t, c), b in rt.boundaries.items()} == {
        (PERSIST, "send-throttled"): THROTTLED,
        (INVOKE, "completion-down"): DOWN,
    }


UNLIFT = (
    "    <https://example.org/chat/chat_bpmn#throttled_boundary> a proc:ErrorBoundaryEvent ;\n"
    '        rdfs:label "Throttled" ;\n        seam:inModel :chat_bpmn .\n',
    "",
)
GHOST = '    <https://example.org/chat/chat_bpmn#ghost> a proc:ErrorBoundaryEvent ; rdfs:label "Ghost" ; seam:inModel :chat_bpmn .\n'
UNCATCH = ("    <https://example.org/chat/chat_bpmn#throttled_boundary> seam:catches :send_throttled .\n", "")


@pytest.mark.parametrize(
    "edits, bpmn_edits, subject, predicate, needle",
    [
        ((UNLIFT, UNCATCH), (), THROTTLED, SEAM.catches, "declares it as " + CHAT + "send_throttled"),
        (
            (UNLIFT, UNCATCH),
            (('errorCode="send-throttled"', 'errorCode="send-unknown"'),),
            THROTTLED,
            SEAM.catches,
            "declares no hydra:possibleStatus with it",
        ),
        (
            (),
            (('errorCode="send-throttled"', 'errorCode="send-rejected"'),),
            THROTTLED,
            SEAM.catches,
            "has errorCode 'send-rejected', but " + CHAT + "send_throttled has comm:errorCode 'send-throttled'",
        ),
        (
            ((UNCATCH[0], UNCATCH[0].replace(":send_throttled", ":completion_down")),),
            (),
            THROTTLED,
            SEAM.catches,
            "is not an error",
        ),
        ((UNCATCH,), (), THROTTLED, SEAM.catches, "catches exactly one error"),
        (
            ((UNCATCH[0], UNCATCH[0].replace(":send_throttled .", ":send_throttled , :send_rejected .")),),
            (),
            THROTTLED,
            SEAM.catches,
            "expected exactly one",
        ),
        (
            (),
            (('<bpmn:errorEventDefinition errorRef="send_throttled_error" />', "<bpmn:errorEventDefinition />"),),
            THROTTLED,
            "bpmn:errorEventDefinition",
            "catch-all",
        ),
        (
            (),
            (('errorRef="send_throttled_error"', 'errorRef="no_such_error"'),),
            THROTTLED,
            "bpmn:errorRef",
            "names no bpmn:error",
        ),
        ((), ((' errorCode="send-throttled"', ""),), THROTTLED, "bpmn:errorCode", "has no errorCode"),
        (
            (),
            (('attachedToRef="persist_user_msg"', 'attachedToRef="persist_response"'),),
            THROTTLED,
            SEAM.catches,
            "seam:invokes no operation",
        ),
        (
            (),
            (('attachedToRef="invoke_llm"', 'attachedToRef="persist_user_msg"'),),
            DOWN,
            SEAM.catches,
            "is not an error",
        ),
        (
            ((PROC_ANCHOR, PROC_ANCHOR + GHOST),),
            (),
            BPMN + "ghost",
            SEAM.catches,
            "no bpmn:boundaryEvent",
        ),
    ],
    ids=[
        "not-lifted",
        "undeclared-code-not-lifted",
        "code-mismatch",
        "status-of-another-operation",
        "catches-nothing",
        "catches-two",
        "catch-all",
        "unknown-error-ref",
        "error-without-code",
        "lifted-on-a-task-that-invokes-nothing",
        "attached-to-the-wrong-task",
        "lifted-but-not-in-the-xml",
    ],
)
def test_a_boundary_the_xml_disagrees_with_is_a_load_fault(tmp_path, edits, bpmn_edits, subject, predicate, needle):
    trig = boundary_model(tmp_path, *edits, bpmn_edits=bpmn_edits)
    with pytest.raises(ResolutionError) as info:
        load(trig, tmp_path)
    err = info.value
    assert (err.subject, err.predicate) == (subject, str(predicate)), err
    assert needle in err.detail


def test_a_dangling_attached_to_ref_names_the_boundary(tmp_path):
    trig = boundary_model(tmp_path, bpmn_edits=(('attachedToRef="persist_user_msg"', 'attachedToRef="nowhere"'),))
    with pytest.raises(ResolutionError) as info:
        load(trig, tmp_path)
    assert (info.value.subject, info.value.predicate) == ("chat_process.bpmn#throttled_boundary", "bpmn:attachedToRef")


def test_a_boundary_fault_opens_no_store(tmp_path):
    trig = boundary_model(tmp_path, UNCATCH)
    db = tmp_path / "never.sqlite"
    with pytest.raises(ResolutionError):
        Runtime.load(trig, db_path=db)
    assert not db.exists()


def test_a_plain_boundary_on_a_task_that_invokes_nothing_is_not_a_seam(tmp_path):
    """Not lifted and not on an invoking task: ordinary BPMN, nothing to check."""
    trig = boundary_model(
        tmp_path,
        UNLIFT,
        UNCATCH,
        bpmn_edits=(('attachedToRef="persist_user_msg"', 'attachedToRef="persist_response"'),),
    )
    rt = load(trig, tmp_path)
    assert [str(b.iri) for b in rt.boundaries.values()] == [DOWN]


# ── run: a Python handler's OperationError ───────────────────────────────────


def test_a_caught_error_goes_down_the_boundary(tmp_path):
    llm = FakeLLM()
    rt = load(boundary_model(tmp_path), tmp_path, llm)
    result = run(rt, says("raise send-throttled 5"))
    assert result["status"] == "complete", result["error"]
    assert result["error"] is None

    tasks = [r["task"] for r in result["trace"]]
    assert tasks == ["start", "persist_user_msg", "throttled_boundary", "record_problem", "throttled_end"]
    persist = row(result, "persist_user_msg")
    assert persist["error"] == {"code": "send-throttled", "status": CHAT + "send_throttled", "operation": SEND_OP}
    assert persist["boundary"] == THROTTLED
    assert "writes" not in persist and "status" not in persist  # no writes, no transition
    assert row(result, "throttled_boundary")["caught"] == "send-throttled"

    # the problem body is the current entity of the error shape, so the error path persists it
    (problem,) = rt.query(":SendProblemShape", conversation="c1")
    assert problem["data"] == {"title": "Too many messages", "status": 429, "detail": "slow down", "limit": 5}
    assert rt.query(":MessageShape", conversation="c1") == []
    # :t_send never fired, so the message is still in its initial status; the happy path never ran
    assert result["lifecycle"] == {"Message": "composing"} and llm.requests == []


def test_the_happy_path_is_unchanged(tmp_path):
    result = run(load(boundary_model(tmp_path), tmp_path))
    assert result["status"] == "complete", result["error"]
    assert [r["task"] for r in result["trace"]] == [
        "start",
        "persist_user_msg",
        "route_to_provider",
        "invoke_llm",
        "persist_response",
        "stream_complete_event",
        "end",
    ]
    assert not any("error" in r or "boundary" in r or "caught" in r for r in result["trace"])


def test_spans_carry_the_error_and_the_boundary(tmp_path):
    result = run(load(boundary_model(tmp_path), tmp_path), says("raise send-throttled 5"))
    attrs = element_attributes(row(result, "persist_user_msg"))
    assert attrs["seams.error.code"] == "send-throttled"
    assert attrs["seams.error.status"] == CHAT + "send_throttled"
    assert attrs["seams.boundary"] == THROTTLED
    assert element_attributes(row(result, "throttled_boundary"))["seams.caught"] == "send-throttled"


def test_a_declared_error_no_boundary_catches_fails_the_instance(tmp_path):
    result = run(load(boundary_model(tmp_path), tmp_path), says("raise send-rejected"))
    assert result["status"] == "failed"
    err = result["error"]
    assert err["type"] == "HandlerError" and "OperationError: send-rejected" in err["message"]
    assert (err["operation"], err["implementation"]) == (SEND_OP, "PythonHandler")
    assert (err["code"], err["status"]) == ("send-rejected", CHAT + "send_rejected")


def test_an_undeclared_code_fails_the_instance_naming_it(tmp_path):
    result = run(load(boundary_model(tmp_path), tmp_path), says("raise send-lost"))
    assert result["status"] == "failed"
    err = result["error"]
    assert err["type"] == "ResolutionError"
    assert (err["subject"], err["predicate"]) == (SEND_OP, str(COMM.errorCode))
    assert err["code"] == "send-lost" and "status" not in err


def test_a_problem_body_the_error_shape_rejects_fails_the_instance(tmp_path):
    result = run(load(boundary_model(tmp_path), tmp_path), says("raise send-throttled many"))
    assert result["status"] == "failed"
    err = result["error"]
    assert err["type"] == "ContractViolation" and err["shape"] == CHAT + "SendProblemShape"
    assert err["operation"] == CHAT + "send_throttled"  # the violation names the status
    assert err["code"] == "send-throttled"


def test_any_other_handler_exception_still_fails_the_instance(tmp_path):
    trig = boundary_model(tmp_path)
    handlers_package(trig.parent / "handlers", {"send.py": "def send(entity):\n    raise ValueError('no')\n"})
    result = run(load(trig, tmp_path))
    assert result["status"] == "failed" and result["error"]["type"] == "HandlerError"
    assert "code" not in result["error"]


def test_a_caught_error_survives_a_restart_between_the_throw_and_the_boundary(tmp_path):
    rt = load(boundary_model(tmp_path), tmp_path)

    async def main():
        inst = await rt.start_process(
            PROCESS, says("raise send-throttled 5"), correlation_key="c1", stop_after="persist_user_msg"
        )
        stopped = await inst.wait()
        resumed = await rt.resume(inst.id)
        return stopped, await resumed.wait()

    stopped, result = asyncio.run(main())
    assert stopped["status"] == "stopped" and row(stopped, "persist_user_msg")["boundary"] == THROTTLED
    assert result["status"] == "complete", result["error"]
    # the READY boundary runs first; the STARTED task is never dispatched again
    assert [r["task"] for r in result["trace"]] == [
        "start",
        "persist_user_msg",
        "throttled_boundary",
        "record_problem",
        "throttled_end",
    ]
    (problem,) = rt.query(":SendProblemShape", conversation="c1")
    assert problem["data"]["limit"] == 5


# ── run: an HTTP endpoint's problem+json answer ──────────────────────────────


def _http(tmp_path: Path, response: httpx.Response):
    endpoint = FakeEndpoint(response)
    rt = load(
        boundary_model(tmp_path, HTTP, handler=False),
        tmp_path,
        http_transport=endpoint.transport,
        http_base_url="http://api.test",
    )
    return run(rt)


def test_a_problem_json_answer_with_a_declared_status_is_caught(tmp_path):
    problem = {"title": "Service Unavailable", "status": 503, "detail": "gateway down"}
    result = _http(tmp_path, httpx.Response(503, json=problem, headers={"content-type": PROBLEM_JSON}))
    assert result["status"] == "complete", result["error"]
    assert [r["task"] for r in result["trace"]] == [
        "start",
        "persist_user_msg",
        "route_to_provider",
        "invoke_llm",
        "completion_down_boundary",
        "completion_down_end",
    ]
    invoke = row(result, "invoke_llm")
    assert invoke["error"] == {
        "code": "completion-down",
        "status": CHAT + "completion_down",
        "operation": COMPLETION_OP,
    }
    assert invoke["boundary"] == DOWN and "status" not in invoke  # :t_stream was not fired
    assert row(result, "completion_down_boundary")["caught"] == "completion-down"
    assert result["history"] == {"Message": ["composing", "sending"]}  # never "streaming"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="down"),
        httpx.Response(503, json={"title": "x"}),  # application/json, not problem+json
        httpx.Response(500, json={"title": "x", "status": 500}, headers={"content-type": PROBLEM_JSON}),
        httpx.Response(503, json=["x"], headers={"content-type": PROBLEM_JSON}),
    ],
    ids=["not-json", "plain-json", "undeclared-status", "not-an-object"],
)
def test_any_other_non_2xx_answer_still_fails_the_instance(tmp_path, response):
    result = _http(tmp_path, response)
    assert result["status"] == "failed"
    err = result["error"]
    assert err["type"] == "EndpointError" and (err["operation"], err["implementation"]) == (
        COMPLETION_OP,
        "HTTPEndpoint",
    )
    assert "code" not in err


def test_a_problem_json_answer_the_error_shape_rejects_fails_the_instance(tmp_path):
    problem = {"title": "x", "status": 503, "retry": "soon"}  # an extension the shape does not declare
    result = _http(tmp_path, httpx.Response(503, json=problem, headers={"content-type": PROBLEM_JSON}))
    assert result["status"] == "failed"
    err = result["error"]
    assert err["type"] == "ContractViolation" and err["code"] == "completion-down"
    assert err["operation"] == CHAT + "completion_down"
