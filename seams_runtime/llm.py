"""Streaming client for an OpenAI-compatible completion endpoint.

The worker calls ``LLMClient.stream_completion`` for a ``seam:invokes``
operation implemented by a container other than the one running the process.
The path is the operation's ``comm:path`` template. The base URL is the
constructor's ``base_url`` when given, else the value of the environment
variable named by the executing container's ``deploy:binding`` whose
``deploy:serviceOf`` is the implementing container (``LLM_GATEWAY_URL`` in
the chat app); the worker resolves that key and passes it in.

Every failure (connection error, timeout, HTTP status >= 400, a ``data:``
line that is not JSON, a stream that ends before ``[DONE]``) is raised as
``LLMError`` naming the URL, so the worker can apply the lifecycle's error
transition.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

import httpx

from .errors import RuntimeModelError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class LLMError(RuntimeModelError):
    """The remote completion call failed (502 to the caller)."""

    http_status = 502

    def __init__(self, url: str, reason: str):
        self.url = str(url)
        self.reason = reason
        super().__init__(f"completion call to {self.url} failed: {reason}")

    def _fields(self) -> dict:
        return {"url": self.url, "reason": self.reason}


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url
        self.transport = transport
        self.timeout = timeout

    def resolve_base_url(self, env_key: str | None) -> str:
        """The constructor override, else ``os.environ[env_key]``."""
        if self.base_url:
            return self.base_url
        value = os.environ.get(env_key, "").strip() if env_key else ""
        if not value:
            raise LLMError(f"${env_key}", f"no base URL: set {env_key} or pass llm_base_url")
        return value

    async def stream_completion(
        self, path: str, messages: list[dict], model: str | None = None, *, base_url: str | None = None
    ) -> AsyncIterator[str]:
        """POST ``{"model", "messages", "stream": true}`` and yield each
        ``choices[0].delta.content`` until ``data: [DONE]``."""
        url = (base_url or self.base_url or "").rstrip("/") + "/" + path.lstrip("/")
        body = {"messages": messages, "stream": True}
        if model is not None:
            body["model"] = model
        log.info("streaming completion from %s (model=%s, %d message(s))", url, model, len(messages))
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
                async with client.stream("POST", url, json=body, headers={"Accept": "text/event-stream"}) as resp:
                    if resp.status_code >= 400:
                        detail = (await resp.aread())[:200].decode("utf-8", "replace")
                        raise LLMError(url, f"HTTP {resp.status_code}: {detail}")
                    done = False
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            done = True
                            break
                        try:
                            chunk = json.loads(data)
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        except (ValueError, AttributeError, IndexError, TypeError) as exc:
                            raise LLMError(url, f"malformed stream chunk {data[:80]!r}: {exc}") from exc
                        content = delta.get("content")
                        if content:
                            yield content
                    if not done:
                        raise LLMError(url, "stream ended before data: [DONE]")
        except httpx.HTTPError as exc:
            raise LLMError(url, f"{type(exc).__name__}: {exc}") from exc
