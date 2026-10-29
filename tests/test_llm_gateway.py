"""seams_gateway: stub stream contract, upstream proxying, key handling, errors, logging."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from seams_gateway import GatewayConfig, build_app
from seams_gateway.app import parse_aliases
from seams_runtime import LLMClient, LLMError

SECRET = "sk-test-SECRET-do-not-log-123"
UPSTREAM = "https://upstream.test/v1"
MESSAGES = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello there"}]


def upstream_sse(*tokens: str) -> bytes:
    out = b"".join(b"data: " + json.dumps({"choices": [{"delta": {"content": t}}]}).encode() + b"\n\n"
                   for t in tokens)
    return out + b"data: [DONE]\n\n"


class Recorder:
    """An httpx MockTransport handler that records requests and answers with a canned response."""

    def __init__(self, status=200, body=None, content_type="text/event-stream"):
        self.requests: list[httpx.Request] = []
        self.status, self.content_type = status, content_type
        self.body = upstream_sse("Hi", " you") if body is None else body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body, headers={"content-type": self.content_type})

    def sent(self, i=0) -> dict:
        return json.loads(self.requests[i].content)


def upstream_app(handler, **cfg):
    config = GatewayConfig(api_key=SECRET, upstream_base_url=UPSTREAM + "/", **cfg)
    return build_app(config, transport=httpx.MockTransport(handler))


async def collect(app, messages, model):
    llm = LLMClient(transport=httpx.ASGITransport(app=app))
    return [d async for d in llm.stream_completion("/v1/chat/completions", messages, model,
                                                   base_url="http://gateway")]


# ── stub mode ──

def test_stub_stream_parses_with_runtime_llm_client():
    app = build_app(GatewayConfig())
    tokens = asyncio.run(collect(app, MESSAGES, "any-logical-name"))
    assert len(tokens) > 1
    assert "".join(tokens) == "Stub reply to: hello there"


def test_stub_raw_format_ends_with_done():
    with TestClient(build_app(GatewayConfig())) as client:
        resp = client.post("/v1/chat/completions", json={"messages": MESSAGES, "stream": True})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    lines = [ln for ln in resp.text.splitlines() if ln]
    assert lines[-1] == "data: [DONE]"
    first = json.loads(lines[0][len("data: "):])
    assert first["choices"][0]["delta"]["content"] == "Stub "


def test_stub_forced_even_with_key():
    handler = Recorder()
    app = upstream_app(handler, force_stub=True)
    tokens = asyncio.run(collect(app, MESSAGES, None))
    assert "".join(tokens).startswith("Stub reply to:")
    assert handler.requests == []


def test_empty_key_file_means_stub(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("  \n")
    assert GatewayConfig.from_env({"LLM_API_KEY_FILE": str(key_file)}).mode == "stub"
    assert GatewayConfig.from_env({}).mode == "stub"
    assert GatewayConfig.from_env({"LLM_API_KEY_FILE": str(tmp_path / "missing")}).mode == "stub"
    assert GatewayConfig.from_env({"LLM_API_KEY": "k", "LLM_GATEWAY_STUB": "1"}).mode == "stub"


def test_healthz_reports_mode():
    with TestClient(build_app(GatewayConfig())) as client:
        assert client.get("/healthz").json() == {"status": "ok", "mode": "stub"}
    with TestClient(upstream_app(Recorder())) as client:
        body = client.get("/healthz").json()
    assert body["mode"] == "upstream" and body["upstream"] == UPSTREAM + "/chat/completions"
    assert SECRET not in json.dumps(body)


# ── upstream mode ──

def test_upstream_carries_bearer_key_and_default_model():
    handler = Recorder()
    tokens = asyncio.run(collect(upstream_app(handler), MESSAGES, None))
    assert tokens == ["Hi", " you"]
    req = handler.requests[0]
    assert str(req.url) == UPSTREAM + "/chat/completions"
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    sent = handler.sent()
    assert sent["model"] == "gpt-4o-mini"
    assert sent["messages"] == MESSAGES and sent["stream"] is True


def test_upstream_model_from_env_default_request_and_override():
    handler = Recorder()
    asyncio.run(collect(upstream_app(handler, default_model="m-default"), MESSAGES, None))
    asyncio.run(collect(upstream_app(handler), MESSAGES, "gpt-4o"))
    asyncio.run(collect(upstream_app(handler, model_override="llama3.1:8b"), MESSAGES, "gpt-4o"))
    assert [handler.sent(i)["model"] for i in range(3)] == ["m-default", "gpt-4o", "llama3.1:8b"]


def test_upstream_model_aliases_map_logical_names():
    handler = Recorder()
    app = upstream_app(handler, model_aliases=parse_aliases("small=gpt-4o-mini, *=gpt-4o"))
    asyncio.run(collect(app, MESSAGES, "small"))
    asyncio.run(collect(app, MESSAGES, "anything-else"))
    assert [handler.sent(i)["model"] for i in range(2)] == ["gpt-4o-mini", "gpt-4o"]


def test_parse_aliases_rejects_malformed():
    assert parse_aliases("") == {}
    with pytest.raises(ValueError):
        parse_aliases("no-equals-sign")
    with pytest.raises(ValueError):
        parse_aliases("a=")


def test_upstream_stream_is_relayed_verbatim():
    raw = upstream_sse("x", "y") + b": keep-alive comment\n\n"
    with TestClient(upstream_app(Recorder(body=raw))) as client:
        resp = client.post("/v1/chat/completions", json={"messages": MESSAGES, "stream": True})
    assert resp.status_code == 200 and resp.content == raw


def test_key_read_from_file(tmp_path):
    key_file = tmp_path / "llm_api_key"
    key_file.write_text(SECRET + "\n")
    config = GatewayConfig.from_env({"LLM_API_KEY_FILE": str(key_file), "UPSTREAM_BASE_URL": UPSTREAM})
    assert config.mode == "upstream" and config.api_key == SECRET
    assert SECRET not in repr(config)
    handler = Recorder()
    asyncio.run(collect(build_app(config, transport=httpx.MockTransport(handler)), MESSAGES, None))
    assert handler.requests[0].headers["authorization"] == f"Bearer {SECRET}"


def test_env_key_wins_over_file(tmp_path):
    key_file = tmp_path / "k"
    key_file.write_text("from-file")
    assert GatewayConfig.from_env({"LLM_API_KEY": "from-env", "LLM_API_KEY_FILE": str(key_file)}).api_key == "from-env"


# ── errors ──

def test_upstream_401_passes_through():
    handler = Recorder(status=401, body=b'{"error":{"message":"bad key"}}', content_type="application/json")
    with TestClient(upstream_app(handler)) as client:
        resp = client.post("/v1/chat/completions", json={"messages": MESSAGES, "stream": True})
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["upstream"] == UPSTREAM + "/chat/completions"
    assert "bad key" in err["detail"]
    assert SECRET not in resp.text
    with pytest.raises(LLMError, match="HTTP 401"):
        asyncio.run(collect(upstream_app(handler), MESSAGES, None))


def test_connection_error_gives_502():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    with TestClient(upstream_app(refuse)) as client:
        resp = client.post("/v1/chat/completions", json={"messages": MESSAGES})
    assert resp.status_code == 502
    assert resp.json()["error"]["upstream"] == UPSTREAM + "/chat/completions"


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"messages": "hi"}', b"{}"])
def test_malformed_request_is_400(payload):
    handler = Recorder()
    with TestClient(upstream_app(handler)) as client:
        resp = client.post("/v1/chat/completions", content=payload,
                           headers={"content-type": "application/json"})
    assert resp.status_code == 400
    assert handler.requests == []


# ── logging ──

def test_key_never_logged(caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    key_file = tmp_path / "k"
    key_file.write_text(SECRET)
    config = GatewayConfig.from_env({"LLM_API_KEY_FILE": str(key_file), "UPSTREAM_BASE_URL": UPSTREAM})
    ok = Recorder()
    asyncio.run(collect(build_app(config, transport=httpx.MockTransport(ok)), MESSAGES, "gpt-4o"))
    denied = Recorder(status=401, body=b"{}", content_type="application/json")
    with TestClient(build_app(config, transport=httpx.MockTransport(denied))) as client:
        client.post("/v1/chat/completions", json={"messages": MESSAGES})
    text = caplog.text
    assert "llm gateway mode: upstream " + UPSTREAM + "/chat/completions" in text
    assert "model=gpt-4o messages=2" in text
    assert SECRET not in text


def test_stub_mode_logged_at_startup(caplog):
    caplog.set_level(logging.INFO, logger="seams_gateway")
    build_app(GatewayConfig())
    assert "llm gateway mode: stub (no API key)" in caplog.text
