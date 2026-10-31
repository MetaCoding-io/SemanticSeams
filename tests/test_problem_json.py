"""Generated routes return validated problem+json (ADR-0013, M014/S04/T02).

A copy of the chat app whose :send_message_op declares three error statuses
(hydra:possibleStatus, each with a comm:errorCode, a hydra:statusCode and a
seam:returnsShape error shape) is generated and served. The route lists each
status as an application/problem+json response, one generated problem_handler
answers an OperationError raised while serving the route with the declared
status and a body validated against its error shape, and a body that does not
conform, or a code the operation does not declare, is a 500 naming the fault.
The chat app itself declares no errors, so its generated module is unchanged
(the golden test in tests/test_fastapi_generator.py).
"""

import ast
import shutil
from pathlib import Path

import pytest
import rdflib
from fastapi.testclient import TestClient

from seams_gen import GeneratorError, extract_routes, generate_routes
from seams_gen.__main__ import main as seams_gen_main
from seams_runtime import ContractViolation, HeaderAuthenticator, ModelGraph, OperationError, ResolutionError, Runtime
from seams_runtime.contracts import problem_body
from seams_runtime.host import build_app
from seams_runtime.model import COMM, HYDRA, SEAM
from tests.test_error_vocabulary import ontology, violating_shapes
from tests.test_runtime_worker import FakeLLM

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "examples" / "chat-app"
TRIG = CHAT_DIR / "chat-app.trig"
PAYLOADS = ("chat_process.bpmn", "routing.dmn")
MOUNTED = "/model/chat-app.trig"
USER = {"X-Forwarded-User": "ann"}
CHAT = "https://example.org/chat/"
OP = CHAT + "send_message_op"
PROBLEM_JSON = "application/problem+json"

SEAMS_ANCHOR = "<urn:seams:graph:seams> {\n"
SHAPES_ANCHOR = '    :chat_data_shapes a seam:Model ; rdfs:label "Chat Data Model" .\n'

# Comm facts and the status -> shape seams sit in the seams graph, as the chat
# app's operations do; the error shapes sit in its shapes graph.
ERRORS = """
    :send_message_op hydra:possibleStatus :send_rejected , :send_blocked , :send_throttled .
    :send_rejected a hydra:Status ; rdfs:label "Message rejected" ;
        hydra:statusCode 422 ; comm:errorCode "send-rejected" ;
        seam:returnsShape :SendProblemShape .
    :send_blocked a hydra:Status ; rdfs:label "Sender blocked" ;
        hydra:statusCode 422 ; comm:errorCode "send-blocked" ;
        seam:returnsShape :BlockedProblemShape .
    :send_throttled a hydra:Status ; rdfs:label "Too many messages" ;
        hydra:statusCode 429 ; comm:errorCode "send-throttled" ;
        seam:returnsShape :SendProblemShape .
"""
SHAPES = """
    :SendProblemShape a sh:NodeShape ; rdfs:label "Send problem" ;
        sh:property [ sh:path comm:title ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:status ; sh:datatype xsd:integer ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:detail ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
                    [ sh:path :limit ; sh:datatype xsd:integer ; sh:maxCount 1 ] ;
        seam:inModel :chat_data_shapes .
    :BlockedProblemShape a sh:NodeShape ; rdfs:label "Blocked problem" ;
        sh:property [ sh:path comm:title ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:status ; sh:datatype xsd:integer ; sh:minCount 1 ; sh:maxCount 1 ] ,
                    [ sh:path comm:detail ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
        seam:inModel :chat_data_shapes .
"""


def write_model(tmp_path, errors=ERRORS, shapes=SHAPES) -> Path:
    """The chat app plus ``errors`` (seams graph) and ``shapes`` (shapes graph)."""
    for name in PAYLOADS:
        shutil.copy(CHAT_DIR / name, tmp_path / name)
    text = TRIG.read_text(encoding="utf-8")
    for anchor, extra in ((SEAMS_ANCHOR, errors), (SHAPES_ANCHOR, shapes)):
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, anchor + extra)
    trig = tmp_path / TRIG.name
    trig.write_text(text, encoding="utf-8")
    return trig


@pytest.fixture
def trig(tmp_path):
    return write_model(tmp_path)


def _send(trig):
    module = extract_routes(ModelGraph.load(trig)).modules[0]
    return next(e for e in module.endpoints if e.name == "send_message"), module


# ── the model: the shapes accept it, the views read it ─────────────────────


def _union(path) -> rdflib.Graph:
    g = ontology()
    for triple in rdflib.Dataset().parse(path, format="trig").triples((None, None, None)):
        g.add(triple)
    return g


def test_fixture_model_passes_the_shapes_as_the_chat_app_does(trig):
    assert violating_shapes(_union(trig)) == violating_shapes(_union(TRIG))


def test_operation_view_lists_its_error_statuses(trig):
    op = ModelGraph.load(trig).operations.by_iri(OP)
    assert [str(s.iri) for s in op.errors] == [CHAT + "send_blocked", CHAT + "send_rejected", CHAT + "send_throttled"]
    throttled = op.error("send-throttled")
    assert throttled.status_code == 429
    assert throttled.error_code == "send-throttled"
    assert str(throttled.returns.iri) == CHAT + "SendProblemShape"
    assert [str(o.iri) for o in throttled.operations] == [OP]


def test_undeclared_code_names_the_operation_and_comm_error_code(trig):
    op = ModelGraph.load(trig).operations.by_iri(OP)
    with pytest.raises(ResolutionError) as err:
        op.error("send-lost")
    assert err.value.subject == OP and err.value.predicate == str(COMM.errorCode)
    assert "send-rejected" in err.value.detail


def test_chat_app_operations_declare_no_errors():
    assert all(not op.errors for op in ModelGraph.load(TRIG).operations)


# ── the generator: problem+json responses and one problem handler ─────────


def test_responses_are_grouped_by_status_code_with_shape_schemas(trig):
    send, module = _send(trig)
    assert [x.code for x in send.errors] == [422, 429]
    shared, throttled = send.errors
    assert shared.description == "Sender blocked; Message rejected"
    assert shared.facts == (
        ':send_blocked hydra:statusCode 422 ; comm:errorCode "send-blocked" ; seam:returnsShape :BlockedProblemShape',
        ':send_rejected hydra:statusCode 422 ; comm:errorCode "send-rejected" ; seam:returnsShape :SendProblemShape',
    )
    assert set(ast.literal_eval(shared.content)[PROBLEM_JSON]["schema"]) == {"oneOf"}
    schema = ast.literal_eval(throttled.content)[PROBLEM_JSON]["schema"]
    assert schema == {
        "type": "object",
        "properties": {
            "detail": {"type": "string"},
            "limit": {"type": "integer"},
            "status": {"type": "integer"},
            "title": {"type": "string"},
        },
        "required": ["status", "title"],
        "additionalProperties": False,
    }
    assert module.problem_routes == (("send_message", ":send_message_op"),)
    assert all(not e.errors for e in module.endpoints if e.name != "send_message")


def test_generated_module_declares_responses_and_one_problem_handler(trig):
    text = generate_routes(trig)
    tree = ast.parse(text)
    assert "from seams_runtime import OperationError, Runtime" in text
    assert "from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse" in text
    assert '# :send_throttled hydra:statusCode 429 ; comm:errorCode "send-throttled"' in text
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    assert [h.name for h in handlers][-1] == "problem_handler"
    banned = (ast.If, ast.IfExp, ast.Match, ast.For, ast.AsyncFor, ast.While, ast.Try)
    assert not [f"{h.name}:{n.lineno}" for h in handlers for n in ast.walk(h) if isinstance(n, banned)]


def test_chat_app_module_has_no_problem_handler():
    text = generate_routes(TRIG)
    assert "problem_handler" not in text and "OperationError" not in text and "responses=" not in text


def test_status_label_with_quotes_stays_a_valid_literal(tmp_path):
    trig = write_model(tmp_path, errors=ERRORS.replace('"Too many messages"', '"Too many \\"messages\\""'))
    module = ast.parse(generate_routes(trig))
    descriptions = [
        n.value for n in ast.walk(module) if isinstance(n, ast.Constant) and str(n.value).startswith("Too many")
    ]
    assert descriptions == ['Too many "messages"']


def test_generation_with_errors_is_deterministic(trig):
    assert generate_routes(trig) == generate_routes(trig)


@pytest.mark.parametrize(
    "old, new, subject, predicate",
    [
        (
            '"send-blocked" ;\n        seam:returnsShape :BlockedProblemShape .',
            '"send-blocked" .',
            "send_blocked",
            SEAM.returnsShape,
        ),
        (
            'hydra:statusCode 429 ; comm:errorCode "send-throttled"',
            'comm:errorCode "send-throttled"',
            "send_throttled",
            HYDRA.statusCode,
        ),
    ],
    ids=["no-error-shape", "no-status-code"],
)
def test_incomplete_error_status_fails_generation_naming_it(tmp_path, old, new, subject, predicate):
    assert ERRORS.count(old) == 1
    trig = write_model(tmp_path, errors=ERRORS.replace(old, new))
    with pytest.raises(GeneratorError) as err:
        generate_routes(trig)
    assert err.value.subject == CHAT + subject and err.value.predicate == str(predicate)


# ── the body: built from the model, validated against the error shape ─────


def test_problem_body_takes_title_and_status_from_the_model(trig):
    model = ModelGraph.load(trig)
    status, body = problem_body(model, ":send_message_op", "send-throttled", "slow down", {"limit": 5})
    assert status == 429
    assert body == {"title": "Too many messages", "status": 429, "detail": "slow down", "limit": 5}


@pytest.mark.parametrize(
    "code, detail, extensions, path, constraint",
    [
        ("send-rejected", None, {"retry": "later"}, "retry", "unknown-field"),
        ("send-rejected", 42, {}, "detail", "DatatypeConstraintComponent"),
        ("send-rejected", None, {"limit": "five"}, "limit", "DatatypeConstraintComponent"),
        ("send-blocked", None, {}, "detail", "MinCountConstraintComponent"),
    ],
    ids=["unknown-member", "detail-not-a-string", "extension-wrong-type", "required-member-missing"],
)
def test_malformed_body_is_a_contract_violation_naming_the_status(trig, code, detail, extensions, path, constraint):
    model = ModelGraph.load(trig)
    with pytest.raises(ContractViolation) as err:
        problem_body(model, ":send_message_op", code, detail, extensions)
    status = model.operations.by_iri(OP).error(code)
    assert err.value.operation == str(status.iri)
    assert err.value.shape == str(status.returns.iri)
    assert [(r["path"], r["constraint"]) for r in err.value.results] == [(path, constraint)]


def test_operation_error_refuses_members_the_model_states():
    for member in ("title", "status"):
        with pytest.raises(ValueError, match=member):
            OperationError("send-rejected", **{member: "x"})
    err = OperationError("send-rejected", "too long", instance="/messages/1")
    assert (err.code, err.detail, err.extensions) == ("send-rejected", "too long", {"instance": "/messages/1"})


# ── served: the route answers with validated problem+json ─────────────────


@pytest.fixture
def client(trig, tmp_path, monkeypatch):
    out = tmp_path / "app"
    assert seams_gen_main(["fastapi", str(trig), "--out", str(out)]) == 0
    assert seams_gen_main(["htmx", str(trig), "--out", str(out / "templates")]) == 0
    original = Runtime.load

    def load(cls, trig_path, model_hash=None, **kw):
        assert str(trig_path) == MOUNTED, trig_path
        return original(
            trig,
            model_hash=model_hash,
            db_path=tmp_path / "seams.sqlite",
            templates_dir=out / "templates",
            authenticator=HeaderAuthenticator(),
            llm_transport=FakeLLM().transport,
            llm_base_url="http://llm-gateway.test",
        )

    monkeypatch.setattr(Runtime, "load", classmethod(load))
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    app = build_app(out / "chat_api.py")
    with TestClient(app) as c:
        yield c, app


def _raising(monkeypatch, runtime, error):
    """Make the route's runtime call raise ``error``, as code serving it would."""

    async def start_process(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(runtime, "start_process", start_process)


def _post(c):
    return c.post("/conversations/c1/messages", data={"content": "hello"}, headers=USER)


def test_declared_error_answers_with_its_status_and_a_conforming_body(client, monkeypatch):
    c, app = client
    runtime = app.state.runtime
    _raising(monkeypatch, runtime, OperationError("send-throttled", "slow down", limit=5))
    r = _post(c)
    assert r.status_code == 429
    assert r.headers["content-type"] == PROBLEM_JSON
    body = r.json()
    assert body == {"title": "Too many messages", "status": 429, "detail": "slow down", "limit": 5}
    assert runtime.validate(":SendProblemShape", body) == body


def test_two_errors_sharing_a_status_code_keep_their_own_shapes(client, monkeypatch):
    c, app = client
    _raising(monkeypatch, app.state.runtime, OperationError("send-blocked", "account suspended"))
    r = _post(c)
    assert (r.status_code, r.headers["content-type"]) == (422, PROBLEM_JSON)
    assert r.json() == {"title": "Sender blocked", "status": 422, "detail": "account suspended"}


def test_malformed_problem_body_is_a_500_naming_the_status(client, monkeypatch):
    c, app = client
    _raising(monkeypatch, app.state.runtime, OperationError("send-rejected", retry="later"))
    r = _post(c)
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/json"
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation"
    assert detail["operation"] == CHAT + "send_rejected"
    assert [(x["path"], x["constraint"]) for x in detail["results"]] == [("retry", "unknown-field")]


def test_undeclared_code_is_a_500_naming_the_operation(client, monkeypatch):
    c, app = client
    _raising(monkeypatch, app.state.runtime, OperationError("send-lost"))
    r = _post(c)
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert (detail["type"], detail["subject"], detail["predicate"]) == ("ResolutionError", OP, str(COMM.errorCode))


def test_route_without_declared_errors_answers_500(client, monkeypatch):
    c, app = client
    runtime = app.state.runtime

    def query(*_args, **_kwargs):
        raise OperationError("send-rejected")

    monkeypatch.setattr(runtime, "query", query)
    r = c.get("/conversations", headers=USER)
    assert r.status_code == 500
    assert r.json()["detail"]["predicate"] == "hydra:possibleStatus"


def test_openapi_lists_the_problem_json_responses(client):
    _c, app = client
    responses = app.openapi()["paths"]["/conversations/{conversation}/messages"]["post"]["responses"]
    assert set(responses) >= {"422", "429"}
    assert responses["429"]["description"] == "Too many messages"
    schema = responses["429"]["content"][PROBLEM_JSON]["schema"]
    assert schema["required"] == ["status", "title"] and schema["additionalProperties"] is False
    assert len(responses["422"]["content"][PROBLEM_JSON]["schema"]["oneOf"]) == 2


def test_contract_violation_still_answers_422_json(client):
    c, _app = client
    r = c.post("/conversations/c1/messages", data={"content": "hi", "bogus": "x"}, headers=USER)
    assert r.status_code == 422
    assert r.json()["detail"]["type"] == "ContractViolation"
