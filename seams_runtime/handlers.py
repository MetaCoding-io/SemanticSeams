"""The handlers package and the call-out clients for ADR-0012 implementations.

A ``comm:PythonHandler`` names a function by a dotted ``comm:handler`` path
relative to one **handlers package**: the directory ``SEAMS_HANDLERS`` names,
else ``handlers/`` beside the model file. ``HandlersPackage`` imports that
directory under one package name (derived from its absolute path, so two
runtimes on two packages never share modules) and resolves a path only inside
it: every segment is a Python identifier, the segments before the last name a
module of the package, and the last names the function. ``"notify.notify_manager"``
is ``notify_manager`` in ``handlers/notify.py``; a single segment is an
attribute of the package's ``__init__``.

Every fault resolving a handler is a model fault and raises
``ResolutionError(implementation, comm:handler)``: no package, a module that
does not import (the original exception chained, so the traceback still points
at the line), a missing attribute or one that is not callable.

Faults while running are not model faults: ``HandlerError`` (a handler raised,
or returned something its operation cannot accept) and ``EndpointError`` (an
HTTP endpoint call failed) fail the instance as ``LLMError`` does.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import ModuleType

import httpx

from .errors import ResolutionError, RuntimeModelError
from .model import COMM

log = logging.getLogger(__name__)

HANDLERS_ENV = "SEAMS_HANDLERS"
DEFAULT_HANDLERS = "handlers"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def handlers_dir(model_path, override=None) -> Path:
    """``override``, else ``SEAMS_HANDLERS``, else ``handlers/`` beside the model file."""
    if override is not None:
        return Path(override)
    env = os.environ.get(HANDLERS_ENV)
    if env:
        return Path(env)
    return Path(model_path).resolve().parent / DEFAULT_HANDLERS


class HandlersPackage:
    """The handlers package at ``path``, imported on the first ``resolve``."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        digest = hashlib.sha256(str(self.path).encode("utf-8")).hexdigest()[:12]
        self.name = f"seams_handlers_{digest}"
        self._package: ModuleType | None = None

    def _import_package(self, implementation) -> ModuleType:
        if self._package is not None:
            return self._package
        init = self.path / "__init__.py"
        if not init.is_file():
            source = f" (from {HANDLERS_ENV})" if os.environ.get(HANDLERS_ENV) else ""
            raise ResolutionError(
                implementation, COMM.handler, f"no handlers package at {self.path}{source}: {init.name} not found"
            )
        existing = sys.modules.get(self.name)
        if existing is not None and list(getattr(existing, "__path__", [])) == [str(self.path)]:
            self._package = existing
            return existing
        spec = importlib.util.spec_from_file_location(self.name, init, submodule_search_locations=[str(self.path)])
        if spec is None or spec.loader is None:  # pragma: no cover - a file path always gives a spec
            raise ResolutionError(implementation, COMM.handler, f"cannot import the handlers package at {self.path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[self.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            del sys.modules[self.name]
            raise ResolutionError(
                implementation, COMM.handler, f"the handlers package {init} failed to import: {exc!r}"
            ) from exc
        log.info("handlers package %s imported as %s", self.path, self.name)
        self._package = module
        return module

    def resolve(self, implementation, handler: str):
        """The callable ``handler`` (a dotted path) names inside the package."""
        segments = handler.split(".")
        if not all(s.isidentifier() for s in segments):
            raise ResolutionError(
                implementation, COMM.handler, f"{handler!r} is not a dotted path of identifiers inside the package"
            )
        package = self._import_package(implementation)
        module = package
        if len(segments) > 1:
            dotted = ".".join(segments[:-1])
            try:
                module = importlib.import_module(f"{self.name}.{dotted}")
            except Exception as exc:
                raise ResolutionError(
                    implementation,
                    COMM.handler,
                    f"module {dotted!r} of the handlers package {self.path} failed to import: {exc!r}",
                ) from exc
        name = segments[-1]
        if not hasattr(module, name):
            where = self.path / (segments[0] if len(segments) == 1 else "/".join(segments[:-1]) + ".py")
            raise ResolutionError(implementation, COMM.handler, f"{handler!r}: {where} has no attribute {name!r}")
        target = getattr(module, name)
        if not callable(target):
            raise ResolutionError(
                implementation, COMM.handler, f"{handler!r} is a {type(target).__name__}, not a callable"
            )
        return target


class HandlerError(RuntimeModelError):
    """A Python handler raised, or returned what its operation cannot accept (500)."""

    http_status = 500

    def __init__(self, operation, handler: str, reason: str):
        self.operation = str(operation)
        self.handler = handler
        self.reason = reason
        super().__init__(f"handler {handler!r} for {self.operation} failed: {reason}")

    def _fields(self) -> dict:
        return {"operation": self.operation, "handler": self.handler, "reason": self.reason}


class EndpointError(RuntimeModelError):
    """The HTTP endpoint call failed (502): no base URL, a connection error or
    timeout, a non-2xx status, or a body that is not JSON."""

    http_status = 502

    def __init__(self, url: str, reason: str):
        self.url = str(url)
        self.reason = reason
        super().__init__(f"endpoint call to {self.url} failed: {reason}")

    def _fields(self) -> dict:
        return {"url": self.url, "reason": self.reason}


class EndpointClient:
    """POSTs an entity as JSON to a comm:HTTPEndpoint (ADR-0012). The base URL
    is the constructor's ``base_url`` when given, else the value of the
    environment variable the executing container's deploy:binding to the
    exposing container names, as for ``LLMClient``."""

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
        if self.base_url:
            return self.base_url
        value = os.environ.get(env_key, "").strip() if env_key else ""
        if not value:
            raise EndpointError(f"${env_key}", f"no base URL: set {env_key} or pass http_base_url")
        return value

    async def post(self, base_url: str, path: str, entity: dict) -> object:
        """The decoded JSON body of a 2xx answer; ``EndpointError`` otherwise."""
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
        log.info("posting entity to %s", url)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
                resp = await client.post(url, json=entity, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise EndpointError(url, f"{type(exc).__name__}: {exc}") from exc
        if not 200 <= resp.status_code < 300:
            raise EndpointError(url, f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise EndpointError(url, f"response is not JSON: {resp.text[:80]!r}") from exc
