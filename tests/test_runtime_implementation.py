"""ADR-0012 in the runtime (M014/S02 T02): every operation a service task
seam:invokes is resolved at Runtime.load against its seam:implementedBy kind,
and the worker dispatches on that kind. Each load-time model fault raises
ResolutionError(subject, predicate) as the ADR's table says; run-time faults
fail the instance and name the operation and implementation kind.

Models are the chat app copied to tmp_path with one textual edit each;
handler packages are written to tmp_path too."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import threading
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import ResolutionError, Runtime  # noqa: E402
from seams_runtime.handlers import HANDLERS_ENV  # noqa: E402
from seams_runtime.model import COMM, SEAM  # noqa: E402
from seams_runtime.store import SQLiteStore  # noqa: E402
from seams_runtime.telemetry import element_attributes  # noqa: E402

CHAT_DIR = ROOT / "examples" / "chat-app"
CHAT = "https://example.org/chat/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PROCESS = ":send_message_process"
SHORT = {"role": "user", "content": "Hello, which provider?"}
TOKENS = ["Hel", "lo"]

LLM_IMPL = ':completion_impl a comm:LLMCompletion ; rdfs:label "LLM completion" .'
COMPLETION_DECL = "        seam:implementedBy :completion_impl .\n"
GATEWAY_BINDING = 'deploy:binding [ deploy:key "LLM_GATEWAY_URL" ;\n                                                deploy:serviceOf :llm_gateway ] ] ;'
SEND_RETURNS = "seam:acceptsShape :MessageShape ;\n        seam:returnsShape :MessageShape ;\n        seam:mediaKind seam:UIFragment ;"


def chat_model(tmp_path: Path, *edits: tuple[str, str]) -> Path:
    """The chat app's model files in ``tmp_path/app`` with each (old, new) applied once."""
    app = tmp_path / "app"
    app.mkdir()
    for name in ("chat-app.trig", "chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_DIR / name, app / name)
    trig = app / "chat-app.trig"
    text = trig.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    trig.write_text(text, encoding="utf-8")
    return trig


def python_handler(handler: str, op: str = ":send_message_op") -> tuple[str, str]:
    """An edit declaring ``op`` seam:implementedBy a comm:PythonHandler ``handler``."""
    return (
        LLM_IMPL,
        f"{LLM_IMPL}\n    {op} seam:implementedBy :py_impl .\n"
        f'    :py_impl a comm:PythonHandler ; rdfs:label "python handler" ; comm:handler "{handler}" .',
    )


def handlers_package(root: Path, files: dict[str, str]) -> Path:
    """A handlers package at ``root`` (``__init__.py`` plus ``files``)."""
    root.mkdir(parents=True, exist_ok=True)
    files = {"__init__.py": "", **files}
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


class FakeLLM:
    def __init__(self):
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        chunks = [{"choices": [{"delta": {"content": t}}]} for t in TOKENS]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def load(trig: Path, tmp_path: Path, llm: FakeLLM | None = None, **kw) -> Runtime:
    llm = llm if llm is not None else FakeLLM()
    kw.setdefault("llm_base_url", "http://llm-gateway.test")
    return Runtime.load(
        trig, store=SQLiteStore(tmp_path / "seams.sqlite"), llm_transport=httpx.MockTransport(llm), **kw
    )


def run(rt: Runtime, payload=SHORT) -> dict:
    async def main():
        inst = await rt.start_process(PROCESS, payload, correlation_key="c1")
        return await inst.wait()

    return asyncio.run(main())


def row(result: dict, bpmn_id: str) -> dict:
    return next(r for r in result["trace"] if r["task"] == bpmn_id)


def load_error(trig: Path, tmp_path: Path, **kw) -> ResolutionError:
    with pytest.raises(ResolutionError) as info:
        load(trig, tmp_path, **kw)
    return info.value


# ── load: the ADR-0012 error table ───────────────────────────────────────────


def test_chat_app_resolves_its_declared_llm_call(tmp_path):
    rt = load(chat_model(tmp_path), tmp_path)
    impl, target = rt.implementations[rt.model.curie(":completion_op")]
    assert impl.kind == COMM.LLMCompletion and target is None
    assert rt.implementations[rt.model.curie(":send_message_op")] == (None, None)


def test_remote_operation_without_implementation(tmp_path):
    trig = chat_model(tmp_path, (COMPLETION_DECL, "        .\n"))
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "completion_op", str(SEAM.implementedBy))
    assert "declares no implementation" in err.detail


def test_two_implementations(tmp_path):
    trig = chat_model(
        tmp_path,
        (COMPLETION_DECL, "        seam:implementedBy :completion_impl , :other_impl .\n"),
        (LLM_IMPL, f'{LLM_IMPL}\n    :other_impl a comm:HTTPEndpoint ; rdfs:label "other" .'),
    )
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "completion_op", str(SEAM.implementedBy))


@pytest.mark.parametrize(
    "decl",
    [
        ':completion_impl rdfs:label "LLM completion" .',
        ':completion_impl a comm:LLMCompletion , comm:HTTPEndpoint ; rdfs:label "LLM completion" .',
        ':completion_impl a comm:Pigeon ; rdfs:label "LLM completion" .',
    ],
    ids=["no-kind", "two-kinds", "unknown-kind"],
)
def test_bad_kind(tmp_path, decl):
    err = load_error(chat_model(tmp_path, (LLM_IMPL, decl)), tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "completion_impl", RDF_TYPE)


def test_python_handler_on_a_remote_operation(tmp_path):
    trig = chat_model(
        tmp_path,
        (LLM_IMPL, ':completion_impl a comm:PythonHandler ; rdfs:label "h" ; comm:handler "chat.complete" .'),
    )
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "completion_op", str(SEAM.exposes))
    assert "runs in the runtime" in err.detail


@pytest.mark.parametrize("kind", ["LLMCompletion", "HTTPEndpoint"])
def test_remote_kind_on_an_in_process_operation(tmp_path, kind):
    trig = chat_model(
        tmp_path,
        (
            LLM_IMPL,
            f'{LLM_IMPL}\n    :send_message_op seam:implementedBy :x .\n    :x a comm:{kind} ; rdfs:label "x" .',
        ),
    )
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "send_message_op", str(SEAM.exposes))
    assert "also seam:executes" in err.detail


@pytest.mark.parametrize("kind", ["LLMCompletion", "HTTPEndpoint"])
def test_remote_kind_without_a_service_binding(tmp_path, kind):
    trig = chat_model(
        tmp_path,
        (GATEWAY_BINDING, 'deploy:binding [ deploy:key "LLM_GATEWAY_URL" ] ] ;'),
        (LLM_IMPL, f':completion_impl a comm:{kind} ; rdfs:label "c" .'),
    )
    # llm_base_url does not excuse the model: the binding is a model fact
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "completion_op", str(SEAM.exposes))
    assert "deploy:serviceOf" in err.detail
    assert isinstance(err.__cause__, ResolutionError)


@pytest.mark.parametrize(
    "decl",
    [
        ':py_impl a comm:PythonHandler ; rdfs:label "h" .',
        ':py_impl a comm:PythonHandler ; rdfs:label "h" ; comm:handler "a.b" , "a.c" .',
        ':py_impl a comm:PythonHandler ; rdfs:label "h" ; comm:handler "../evil" .',
    ],
    ids=["no-handler", "two-handlers", "not-identifiers"],
)
def test_bad_handler_literal(tmp_path, decl):
    trig = chat_model(
        tmp_path, (LLM_IMPL, f"{LLM_IMPL}\n    :send_message_op seam:implementedBy :py_impl .\n    {decl}")
    )
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "py_impl", str(COMM.handler))


def test_no_handlers_package(tmp_path):
    err = load_error(chat_model(tmp_path, python_handler("echo.shout")), tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "py_impl", str(COMM.handler))
    assert "no handlers package" in err.detail and str(tmp_path / "app" / "handlers") in err.detail


def test_a_model_fault_opens_no_store(tmp_path):
    trig = chat_model(tmp_path, (COMPLETION_DECL, "        .\n"))
    db = tmp_path / "never.sqlite"
    with pytest.raises(ResolutionError):
        Runtime.load(trig, db_path=db)
    assert not db.exists()


def test_a_module_that_fails_to_import_is_chained(tmp_path):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"echo.py": "import no_such_module_anywhere\n"})
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "py_impl", str(COMM.handler))
    assert isinstance(err.__cause__, ModuleNotFoundError)


def test_a_package_that_fails_to_import_is_chained(tmp_path):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"__init__.py": "raise RuntimeError('boom')\n"})
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "py_impl", str(COMM.handler))
    assert isinstance(err.__cause__, RuntimeError) and str(err.__cause__) == "boom"


@pytest.mark.parametrize(
    "handler, body, needle",
    [
        ("echo.shout", "def whisper(entity):\n    return None\n", "no attribute 'shout'"),
        ("echo.shout", "shout = 3\n", "not a callable"),
        ("os.system", "", "failed to import"),  # resolved inside the package, never the stdlib
    ],
    ids=["missing-attribute", "not-callable", "outside-package"],
)
def test_handler_that_does_not_resolve(tmp_path, handler, body, needle):
    trig = chat_model(tmp_path, python_handler(handler))
    handlers_package(trig.parent / "handlers", {"echo.py": body})
    err = load_error(trig, tmp_path)
    assert (err.subject, err.predicate) == (CHAT + "py_impl", str(COMM.handler))
    assert needle in err.detail


def test_seams_handlers_names_the_package(tmp_path, monkeypatch):
    trig = chat_model(tmp_path, python_handler("shout"))
    elsewhere = handlers_package(tmp_path / "owned", {"__init__.py": "def shout(entity):\n    return None\n"})
    monkeypatch.setenv(HANDLERS_ENV, str(elsewhere))
    rt = load(trig, tmp_path)
    _, target = rt.implementations[rt.model.curie(":send_message_op")]
    assert target.__name__ == "shout" and target.__module__.startswith("seams_handlers_")


# ── run: Python handlers ─────────────────────────────────────────────────────

SYNC_SHOUT = """
import threading

calls = []

def shout(entity):
    calls.append((dict(entity), threading.get_ident()))
    return {"role": entity["role"], "content": entity["content"].upper()}
"""

ASYNC_SHOUT = """
import asyncio

async def shout(entity):
    await asyncio.sleep(0)
    return {"role": entity["role"], "content": entity["content"] + "!"}
"""


def test_a_sync_handler_runs_in_a_thread_and_its_result_persists(tmp_path):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"echo.py": SYNC_SHOUT})
    llm = FakeLLM()
    rt = load(trig, tmp_path, llm)
    result = run(rt)
    assert result["status"] == "complete", result["error"]

    persist = row(result, "persist_user_msg")
    assert persist["implementation"] == "PythonHandler" and persist["handler"] == "echo.shout"
    assert "path" not in persist
    _, target = rt.implementations[rt.model.curie(":send_message_op")]
    (entity, ident), *_ = sys.modules[target.__module__].calls
    assert entity == SHORT  # the plain payload: no id, no lifecycle status
    assert ident != threading.get_ident()

    stored = [m["data"]["content"] for m in rt.query(":MessageShape", conversation="c1")]
    assert stored[0] == SHORT["content"].upper()
    # the handler's entity is the one the next task sends on
    assert llm.requests[0]["messages"][0]["content"] == SHORT["content"].upper()
    assert row(result, "invoke_llm")["implementation"] == "LLMCompletion"


def test_an_async_handler_is_awaited(tmp_path):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"echo.py": ASYNC_SHOUT})
    rt = load(trig, tmp_path)
    result = run(rt)
    assert result["status"] == "complete", result["error"]
    stored = [m["data"]["content"] for m in rt.query(":MessageShape", conversation="c1")]
    assert stored[0] == SHORT["content"] + "!"


def _failed(result: dict, op: str, kind: str) -> dict:
    assert result["status"] == "failed"
    err = result["error"]
    assert err["operation"] == CHAT + op and err["implementation"] == kind
    return err


def test_a_handler_that_raises_fails_the_instance(tmp_path):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"echo.py": "def shout(entity):\n    raise ValueError('no')\n"})
    err = _failed(run(load(trig, tmp_path)), "send_message_op", "PythonHandler")
    assert err["type"] == "HandlerError" and err["handler"] == "echo.shout"
    assert "ValueError: no" in err["message"]


@pytest.mark.parametrize(
    "body, error",
    [
        ("def shout(entity):\n    return None\n", "HandlerError"),
        ("def shout(entity):\n    return ['a']\n", "HandlerError"),
        ("def shout(entity):\n    return {'mood': 'loud'}\n", "ContractViolation"),
    ],
    ids=["none-for-a-returns-shape", "not-a-dict", "violates-returns-shape"],
)
def test_a_handler_result_the_operation_cannot_accept(tmp_path, body, error):
    trig = chat_model(tmp_path, python_handler("echo.shout"))
    handlers_package(trig.parent / "handlers", {"echo.py": body})
    err = _failed(run(load(trig, tmp_path)), "send_message_op", "PythonHandler")
    assert err["type"] == error


@pytest.mark.parametrize(
    "returned, status", [("None", "complete"), ("{'role': 'user', 'content': 'x'}", "failed")], ids=["none", "dict"]
)
def test_no_returns_shape_means_the_handler_returns_none(tmp_path, returned, status):
    no_returns = SEND_RETURNS.replace("        seam:returnsShape :MessageShape ;\n", "")
    trig = chat_model(tmp_path, python_handler("echo.shout"), (SEND_RETURNS, no_returns))
    handlers_package(trig.parent / "handlers", {"echo.py": f"def shout(entity):\n    return {returned}\n"})
    result = run(load(trig, tmp_path))
    assert result["status"] == status, result["error"]
    if status == "failed":
        assert result["error"]["type"] == "HandlerError"
        assert "no seam:returnsShape" in result["error"]["message"]


# ── run: HTTP endpoints ──────────────────────────────────────────────────────


class FakeEndpoint:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((str(request.url), json.loads(request.content)))
        return self.response

    @property
    def transport(self):
        return httpx.MockTransport(self)


def http_model(tmp_path: Path) -> Path:
    return chat_model(tmp_path, (LLM_IMPL, ':completion_impl a comm:HTTPEndpoint ; rdfs:label "completion API" .'))


def test_http_endpoint_posts_the_entity_and_persists_the_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.test/")
    endpoint = FakeEndpoint(httpx.Response(200, json={"role": "assistant", "content": "posted"}))
    rt = load(http_model(tmp_path), tmp_path, http_transport=endpoint.transport)
    result = run(rt)
    assert result["status"] == "complete", result["error"]
    # the base URL is the executing container's deploy:serviceOf binding
    assert endpoint.requests == [("http://gateway.test/v1/chat/completions", SHORT)]
    invoke = row(result, "invoke_llm")
    assert invoke["implementation"] == "HTTPEndpoint" and invoke["path"] == "/v1/chat/completions"
    assert "tokens" not in invoke and "handler" not in invoke
    stored = [(m["data"]["role"], m["data"]["content"]) for m in rt.query(":MessageShape", conversation="c1")]
    assert stored == [("user", SHORT["content"]), ("assistant", "posted")]


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(503, text="down"), "EndpointError"),
        (httpx.Response(200, text="not json"), "EndpointError"),
        (httpx.Response(200, json=["a list"]), "EndpointError"),
        (httpx.Response(200, json={"mood": "loud"}), "ContractViolation"),
    ],
    ids=["non-2xx", "non-json", "not-an-object", "bad-shape"],
)
def test_http_endpoint_failures_fail_the_instance(tmp_path, response, error):
    endpoint = FakeEndpoint(response)
    rt = load(http_model(tmp_path), tmp_path, http_transport=endpoint.transport, http_base_url="http://api.test")
    err = _failed(run(rt), "completion_op", "HTTPEndpoint")
    assert err["type"] == error


def test_http_endpoint_without_a_base_url_fails_the_instance(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    endpoint = FakeEndpoint(httpx.Response(200, json={}))
    err = _failed(
        run(load(http_model(tmp_path), tmp_path, http_transport=endpoint.transport)), "completion_op", "HTTPEndpoint"
    )
    assert err["type"] == "EndpointError" and "LLM_GATEWAY_URL" in err["message"]
    assert endpoint.requests == []


def test_llm_failures_name_the_operation_and_kind(tmp_path):
    class Down(FakeLLM):
        def __call__(self, request):
            return httpx.Response(500, text="down")

    err = _failed(run(load(chat_model(tmp_path), tmp_path, Down())), "completion_op", "LLMCompletion")
    assert err["type"] == "LLMError"


# ── telemetry ────────────────────────────────────────────────────────────────


def test_span_attributes_carry_the_implementation_and_handler():
    attrs = element_attributes({"task": "t", "iri": "urn:t", "implementation": "PythonHandler", "handler": "a.b"})
    assert attrs["seams.implementation"] == "PythonHandler" and attrs["seams.handler"] == "a.b"
    assert "seams.handler" not in element_attributes({"task": "t", "implementation": "runtime"})
