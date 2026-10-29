"""The gateway app: ``POST /v1/chat/completions`` and ``GET /healthz``.

Mode is fixed when the app is built:

- **upstream** when a key is available (``LLM_API_KEY``, else the stripped
  contents of the file ``LLM_API_KEY_FILE`` names) and ``LLM_GATEWAY_STUB``
  is not set. The request goes to ``UPSTREAM_BASE_URL/chat/completions``
  with ``Authorization: Bearer <key>`` and the response streams back
  verbatim. An upstream status >= 400 is passed through with a JSON body
  naming the upstream URL; a transport error is a 502.
- **stub** otherwise: a deterministic OpenAI-format SSE stream echoing the
  last user message, ending in ``data: [DONE]``.

The model sent upstream is ``LLM_MODEL_OVERRIDE`` when set, else the
request's ``model`` mapped through ``LLM_MODEL_ALIASES``
(``name=model,name=model``; ``*`` maps any other requested name), else the
request's ``model``, else ``LLM_MODEL`` (default ``gpt-4o-mini``). Aliases
let a caller send logical names (e.g. a decision table's provider choice)
without the gateway knowing them.

The key is never logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

log = logging.getLogger("seams_gateway")

DEFAULT_UPSTREAM = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
UPSTREAM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
TRUTHY = {"1", "true", "yes", "on"}


def parse_aliases(value: str | None) -> dict[str, str]:
    """``"a=x, b=y"`` -> ``{"a": "x", "b": "y"}``; malformed entries raise ValueError."""
    aliases: dict[str, str] = {}
    for entry in (value or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, target = entry.partition("=")
        if not sep or not name.strip() or not target.strip():
            raise ValueError(f"LLM_MODEL_ALIASES entry {entry!r} is not name=model")
        aliases[name.strip()] = target.strip()
    return aliases


@dataclass(frozen=True)
class GatewayConfig:
    api_key: str | None = field(default=None, repr=False)
    upstream_base_url: str = DEFAULT_UPSTREAM
    default_model: str = DEFAULT_MODEL
    model_override: str | None = None
    model_aliases: Mapping[str, str] = field(default_factory=dict)
    force_stub: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GatewayConfig":
        env = os.environ if env is None else env
        key = (env.get("LLM_API_KEY") or "").strip()
        key_file = (env.get("LLM_API_KEY_FILE") or "").strip()
        if not key and key_file:
            try:
                key = Path(key_file).read_text().strip()
            except OSError as exc:
                log.warning("cannot read LLM_API_KEY_FILE %s (%s); no key", key_file, type(exc).__name__)
        return cls(
            api_key=key or None,
            upstream_base_url=(env.get("UPSTREAM_BASE_URL") or "").strip() or DEFAULT_UPSTREAM,
            default_model=(env.get("LLM_MODEL") or "").strip() or DEFAULT_MODEL,
            model_override=(env.get("LLM_MODEL_OVERRIDE") or "").strip() or None,
            model_aliases=parse_aliases(env.get("LLM_MODEL_ALIASES")),
            force_stub=(env.get("LLM_GATEWAY_STUB") or "").strip().lower() in TRUTHY,
        )

    @property
    def mode(self) -> str:
        return "stub" if self.force_stub or not self.api_key else "upstream"

    @property
    def completions_url(self) -> str:
        return self.upstream_base_url.rstrip("/") + "/chat/completions"

    def resolve_model(self, requested) -> str:
        if self.model_override:
            return self.model_override
        if isinstance(requested, str) and requested:
            return self.model_aliases.get(requested) or self.model_aliases.get("*") or requested
        return self.default_model


def _text(content) -> str:
    """A message's content as text (a string, or OpenAI content parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def stub_tokens(messages: list) -> list[str]:
    last = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"), None)
    reply = "Stub reply to: " + (_text(last.get("content")) if last else "")
    return re.findall(r"\S+\s*", reply)


def _sse(obj) -> bytes:
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def build_app(config: GatewayConfig | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = config or GatewayConfig.from_env()
    if config.mode == "stub":
        reason = "LLM_GATEWAY_STUB set" if config.force_stub else "no API key"
        log.info("llm gateway mode: stub (%s)", reason)
    else:
        log.info("llm gateway mode: upstream %s", config.completions_url)

    app = FastAPI(title="seams llm gateway")
    app.state.config = config

    @app.get("/healthz")
    async def healthz():
        body = {"status": "ok", "mode": config.mode}
        if config.mode == "upstream":
            body["upstream"] = config.completions_url
        return body

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": {"message": "request body is not JSON"}}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return JSONResponse({"error": {"message": "request body needs a messages array"}}, status_code=400)
        messages = body["messages"]
        model = config.resolve_model(body.get("model"))
        log.info("completion request: mode=%s model=%s messages=%d", config.mode, model, len(messages))
        if config.mode == "stub":
            return _stub_response(model, messages)
        return await _upstream_response(config, transport, {**body, "model": model})

    return app


def _stub_response(model: str, messages: list) -> StreamingResponse:
    def chunks():
        for token in stub_tokens(messages):
            yield _sse({"object": "chat.completion.chunk", "model": model,
                        "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]})
        yield _sse({"object": "chat.completion.chunk", "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        yield b"data: [DONE]\n\n"

    return StreamingResponse(chunks(), media_type="text/event-stream")


async def _upstream_response(config: GatewayConfig, transport, body: dict):
    url = config.completions_url
    client = httpx.AsyncClient(transport=transport, timeout=UPSTREAM_TIMEOUT)
    try:
        req = client.build_request("POST", url, json=body, headers={
            "Authorization": f"Bearer {config.api_key}",
            "Accept": "text/event-stream" if body.get("stream") else "application/json",
        })
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("upstream %s unreachable: %s", url, type(exc).__name__)
        return JSONResponse({"error": {"message": f"upstream {url} unreachable: {type(exc).__name__}",
                                       "upstream": url}}, status_code=502)

    if resp.status_code >= 400:
        try:
            detail = (await resp.aread())[:500].decode("utf-8", "replace")
        finally:
            await resp.aclose()
            await client.aclose()
        log.warning("upstream %s returned HTTP %d", url, resp.status_code)
        return JSONResponse({"error": {"message": f"upstream {url} returned HTTP {resp.status_code}",
                                       "upstream": url, "status": resp.status_code, "detail": detail}},
                            status_code=resp.status_code)

    async def relay():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        except httpx.HTTPError as exc:
            log.warning("upstream %s stream broke: %s", url, type(exc).__name__)

    async def close():
        await resp.aclose()
        await client.aclose()

    media_type = resp.headers.get("content-type", "text/event-stream")
    return StreamingResponse(relay(), status_code=resp.status_code, media_type=media_type,
                             background=BackgroundTask(close))
