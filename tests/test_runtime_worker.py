"""seams_runtime's generic worker and Runtime facade, end to end against
examples/chat-app/chat-app.trig (M004/S03 T05, D013): a sent message starts a
process instance; the worker validates, guards the lifecycle, routes through
routing.dmn and streams the (mocked) LLM reply. Dispatch comes only from graph
facts, so the trace is asserted in IRIs."""

import ast
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import (  # noqa: E402
    ContractViolation,
    Instance,
    ModelHashMismatch,
    Runtime,
    RuntimeModelError,
    model_hash,
)

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
GOLDEN_API = ROOT / "docs" / "generation" / "golden" / "chat_api.py"
CHAT = "https://example.org/chat/"
BPMN = "https://example.org/chat/chat_bpmn#"
PROCESS = ":send_message_process"
TOKENS = ["Hel", "lo", " there"]
SHORT = {"role": "user", "content": "Hello, which provider?"}
LONG = {"role": "user", "content": "x" * 4001}


class FakeLLM:
    """An OpenAI-compatible streaming endpoint behind httpx.MockTransport."""

    def __init__(self, tokens=TOKENS, fail: Exception | None = None):
        self.tokens = tokens
        self.fail = fail
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((str(request.url), json.loads(request.content)))
        if self.fail is not None:
            raise self.fail
        chunks = [{"choices": [{"delta": {"content": t}}]} for t in self.tokens]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    @property
    def transport(self):
        return httpx.MockTransport(self)


def make_runtime(tmp_path, llm=None, **kw) -> Runtime:
    llm = llm if llm is not None else FakeLLM()
    kw.setdefault("llm_base_url", "http://llm-gateway.test")
    return Runtime.load(TRIG, db_path=tmp_path / "seams.sqlite", llm_transport=llm.transport, **kw)


async def _frames(sub, until_event: str, timeout: float = 5.0) -> list[str]:
    out = []
    while True:
        frame = await asyncio.wait_for(sub.__anext__(), timeout)
        out.append(frame)
        if frame.startswith(f"event: {until_event}\n"):
            return out


def _row(result, bpmn_id):
    return next(r for r in result["trace"] if r["task"] == bpmn_id)


# ── the demo: a short message ────────────────────────────────────────────────


def test_short_message_runs_to_complete(tmp_path):
    llm = FakeLLM()
    rt = make_runtime(tmp_path, llm)

    async def main():
        sub_c1 = rt.subscribe(":stream_events", "c1")
        sub_c2 = rt.subscribe(":stream_events", "c2")
        inst = await rt.start_process(PROCESS, SHORT, correlation_key="c1")
        assert isinstance(inst, Instance) and inst.correlation_key == "c1"
        result = await inst.wait()
        frames = await _frames(sub_c1, "stream.events")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub_c2.__anext__(), 0.05)
        return result, frames

    result, frames = asyncio.run(main())
    assert result["status"] == "complete", result["error"]
    assert result["variables"]["provider"] == "default-provider"
    assert result["history"]["Message"] == ["composing", "sending", "streaming", "complete"]

    order = [r["task"] for r in result["trace"]]
    expected = ["persist_user_msg", "route_to_provider", "invoke_llm", "persist_response",
                "stream_complete_event"]
    assert [t for t in order if t in expected] == expected

    persist = _row(result, "persist_user_msg")
    assert persist["invokes"] == CHAT + "send_message_op"
    assert persist["container"] == CHAT + "chat_api" and persist["in_process"] is True
    assert persist["fires"] == CHAT + "t_send"
    assert _row(result, "route_to_provider")["decision"] == CHAT + "routing_decision"
    invoke = _row(result, "invoke_llm")
    assert invoke["invokes"] == CHAT + "completion_op"
    assert invoke["container"] == CHAT + "llm_gateway" and invoke["in_process"] is False
    assert invoke["path"] == "/v1/chat/completions"
    assert _row(result, "persist_response")["fires"] == CHAT + "t_finish"

    url, body = llm.requests[0]
    assert url == "http://llm-gateway.test/v1/chat/completions"
    assert body["stream"] is True and body["model"] == "default-provider"
    assert body["messages"] == [{"role": "user", "content": SHORT["content"]}]

    tokens = [f for f in frames if f.startswith("event: token\n")]
    assert [json.loads(f.split("data: ", 1)[1])["content"] for f in tokens] == TOKENS
    assert [json.loads(f.split("data: ", 1)[1])["seq"] for f in tokens] == [0, 1, 2]
    assert frames[-1].startswith("event: stream.events\n")
    assert frames.index(frames[-1]) == len(tokens)

    msgs = rt.query(":MessageShape", conversation="c1")
    assert [(m["data"]["role"], m["data"]["content"]) for m in msgs] == [
        ("user", SHORT["content"]), ("assistant", "".join(TOKENS))]
    assert {m["status"] for m in msgs} == {"complete"}
    assert rt.query(":MessageShape", conversation="c2") == []
    assert rt.store.get_instance(result["instance"])["status"] == "complete"


def test_long_message_routes_to_long_context_provider(tmp_path):
    llm = FakeLLM()
    rt = make_runtime(tmp_path, llm)

    async def main():
        return await (await rt.start_process(PROCESS, LONG, correlation_key="c1")).wait()

    result = asyncio.run(main())
    assert result["status"] == "complete"
    assert result["variables"]["provider"] == "long-context-provider"
    assert llm.requests[0][1]["model"] == "long-context-provider"


def test_base_url_comes_from_the_deploy_binding_env_var(tmp_path, monkeypatch):
    """:chat_api deploy:binding [deploy:key "LLM_GATEWAY_URL"; deploy:serviceOf :llm_gateway]."""
    llm = FakeLLM()
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://from-env.test/")
    rt = make_runtime(tmp_path, llm, llm_base_url=None)

    async def main():
        return await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()

    assert asyncio.run(main())["status"] == "complete"
    assert llm.requests[0][0] == "http://from-env.test/v1/chat/completions"


# ── negative paths ───────────────────────────────────────────────────────────


def test_malformed_payload_is_rejected_before_any_instance(tmp_path):
    rt = make_runtime(tmp_path)
    bad = {"role": "user"}  # no :content (sh:minCount 1)
    with pytest.raises(ContractViolation) as v:
        rt.validate(":MessageShape", bad)
    assert v.value.http_status == 422
    assert any(r["path"] == "content" and r["constraint"] == "MinCountConstraintComponent"
               for r in v.value.results)

    async def main():
        await rt.start_process(PROCESS, bad, correlation_key="c1")

    with pytest.raises(ContractViolation) as v2:
        asyncio.run(main())
    assert v2.value.operation == CHAT + "send_message_op"
    assert rt.store.list_instances() == []
    assert rt.query(":MessageShape", conversation="c1") == []


def test_unknown_field_is_rejected_at_start(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await rt.start_process(PROCESS, {**SHORT, "provider": "x"}, correlation_key="c1")

    with pytest.raises(ContractViolation) as v:
        asyncio.run(main())
    assert v.value.results[0]["constraint"] == "unknown-field"


@pytest.mark.parametrize("llm", [
    FakeLLM(fail=httpx.ConnectError("connection refused")),
    FakeLLM(fail=httpx.ReadTimeout("timed out")),
], ids=["connect-error", "timeout"])
def test_llm_transport_error_fails_via_t_fail_send(tmp_path, llm):
    rt = make_runtime(tmp_path, llm)

    async def main():
        sub = rt.subscribe(":stream_events", "c1")
        result = await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()
        rest = [f async for f in sub]  # the scope is closed on failure
        return result, rest

    result, rest = asyncio.run(main())
    assert result["status"] == "failed"
    assert result["lifecycle"] == {"Message": "failed"}
    assert result["history"]["Message"] == ["composing", "sending", "failed"]
    assert result["trace"][-1]["fires"] == CHAT + "t_fail_send"
    assert result["error"]["type"] == "LLMError" and result["error"]["http_status"] == 502
    assert rest == []
    (user,) = rt.query(":MessageShape", conversation="c1")
    assert user["status"] == "failed" and user["data"]["role"] == "user"
    assert rt.store.get_instance(result["instance"])["status"] == "failed"


def _http_response(status, body, headers=None):
    return lambda request: httpx.Response(status, text=body, headers=headers or {})


@pytest.mark.parametrize("handler,reason", [
    (_http_response(500, "upstream exploded"), "HTTP 500"),
    (_http_response(200, "data: {not json}\n\n"), "malformed stream chunk"),
    (_http_response(200, 'data: {"choices": [{"delta": {"content": "a"}}]}\n\n'), "before data: [DONE]"),
], ids=["http-500", "bad-chunk", "no-done"])
def test_llm_bad_responses_fail_the_instance(tmp_path, handler, reason):
    rt = Runtime.load(TRIG, db_path=tmp_path / "s.sqlite", llm_transport=httpx.MockTransport(handler),
                      llm_base_url="http://llm.test")

    async def main():
        return await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()

    result = asyncio.run(main())
    assert result["status"] == "failed"
    assert reason in result["error"]["reason"]
    assert result["lifecycle"] == {"Message": "failed"}


def test_missing_base_url_fails_naming_the_env_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    rt = make_runtime(tmp_path, llm_base_url=None)

    async def main():
        return await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()

    result = asyncio.run(main())
    assert result["status"] == "failed"
    assert "LLM_GATEWAY_URL" in result["error"]["message"]


def test_decision_without_output_fails_with_the_model_error(tmp_path):
    # Spiff wraps errors raised inside a business-rule task in a
    # WorkflowTaskException; the worker records the ResolutionError beneath it.
    from rdflib import Literal, URIRef

    from seams_runtime.model import DEC
    rt = make_runtime(tmp_path)
    node = rt.model.ds.value(URIRef(CHAT + "routing_decision"), DEC.output)
    [(_s, _p, _o, ctx)] = list(rt.model.ds.quads((node, DEC.variable, None, None)))
    rt.model.ds.remove((node, DEC.variable, None, ctx))
    rt.model.ds.add((node, DEC.variable, Literal("Nope"), ctx))

    async def main():
        return await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()

    result = asyncio.run(main())
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ResolutionError", result["error"]
    assert "'routing_decision' produced no 'Nope'" in result["error"]["message"]
    assert result["lifecycle"] == {"Message": "failed"}


def test_model_error_is_found_through_the_exception_chain():
    from seams_runtime import ResolutionError
    from seams_runtime.worker import Worker
    inner = ResolutionError(CHAT + "d", "dec:output", "no output")
    try:
        try:
            raise inner
        except ResolutionError as e:
            raise RuntimeError("wrapped") from e
    except RuntimeError as outer:
        assert Worker._model_error(outer) is inner
    plain = ValueError("plain")
    assert Worker._model_error(plain) is plain


def test_model_hash_is_enforced(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMS_ALLOW_HASH_MISMATCH", raising=False)
    with pytest.raises(ModelHashMismatch) as e:
        make_runtime(tmp_path, model_hash="sha256:0000")
    assert e.value.expected == "sha256:0000" and e.value.actual == model_hash(TRIG)
    assert make_runtime(tmp_path, model_hash="sha256:0000", allow_hash_mismatch=True)
    assert make_runtime(tmp_path, model_hash=model_hash(TRIG))
    monkeypatch.setenv("SEAMS_ALLOW_HASH_MISMATCH", "1")
    assert make_runtime(tmp_path, model_hash="sha256:0000")


def test_db_path_defaults_to_seams_db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "env.sqlite"))
    rt = Runtime.load(TRIG)
    assert rt.store.path == tmp_path / "env.sqlite"


# ── restart ──────────────────────────────────────────────────────────────────


def test_restart_resumes_from_the_checkpoint(tmp_path):
    first_llm, second_llm = FakeLLM(), FakeLLM()
    first = make_runtime(tmp_path, first_llm)

    async def run_first():
        inst = await first.start_process(PROCESS, LONG, correlation_key="c1",
                                         stop_after="route_to_provider")
        return await inst.wait()

    stopped = asyncio.run(run_first())
    assert stopped["status"] == "stopped"
    assert stopped["trace"][-1]["task"] == "route_to_provider"
    assert first_llm.requests == []
    del first  # the process is gone; only SQLite remains

    second = make_runtime(tmp_path, second_llm)
    assert second.store.get_instance(stopped["instance"])["status"] == "stopped"

    async def run_second():
        return await (await second.resume(stopped["instance"])).wait()

    done = asyncio.run(run_second())
    assert done["status"] == "complete"
    assert done["variables"]["provider"] == "long-context-provider"
    assert second_llm.requests[0][1]["model"] == "long-context-provider"
    assert done["history"]["Message"] == ["composing", "sending", "streaming", "complete"]
    assert len(second.query(":MessageShape", conversation="c1")) == 2


def test_resume_unknown_instance(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await rt.resume("nope")

    with pytest.raises(LookupError):
        asyncio.run(main())


# ── the generated-code contract ──────────────────────────────────────────────


def test_golden_chat_api_calls_only_runtime_methods():
    tree = ast.parse(GOLDEN_API.read_text())
    used = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "runtime"}
    assert used >= {"policy", "validate", "start_process", "query", "subscribe", "render_fragment"}
    for name in sorted(used):
        assert callable(getattr(Runtime, name, None)), name
    assert callable(Runtime.load)


def test_fastapi_route_smoke(tmp_path):
    from fastapi import Depends, FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from seams_runtime import HeaderAuthenticator

    rt = make_runtime(tmp_path, authenticator=HeaderAuthenticator())
    app = FastAPI()

    @app.exception_handler(RuntimeModelError)
    async def _model_error(_request, exc: RuntimeModelError):
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.to_dict()})

    @app.post("/conversations/{conversation}/messages",
              dependencies=[Depends(rt.policy(":user_send_policy"))])
    async def send_message(conversation: str, request: Request):
        message = rt.validate(":MessageShape", await request.form())
        result = await (await rt.start_process(PROCESS, message, correlation_key=conversation)).wait()
        return {"message": message, "status": result["status"]}

    client = TestClient(app)
    url = "/conversations/c1/messages"
    assert client.post(url, data={"role": "user", "content": "hi"}).status_code == 401

    r = client.post(url, data={"role": "user", "content": ""}, headers={"X-Forwarded-User": "ann"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation" and detail["shape"] == CHAT + "MessageShape"
    assert detail["results"][0]["path"] == "content"

    r = client.post(url, data={"role": "user", "content": "hi"}, headers={"X-Forwarded-User": "ann"})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": {"role": "user", "content": "hi"}, "status": "complete"}
