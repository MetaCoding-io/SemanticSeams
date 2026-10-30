"""The generated route module runs end to end (M004/S05/T04, D017): the CLI
writes chat_api.py and its fragment partials into a temp app directory, the
module is imported with the real model hash (Runtime.load is only redirected
to the repo model, a temp store, the temp templates, header auth and a mocked
LLM), and its router serves the chat flow: 401 without a user, 422 on an
invalid message, the appended item partial on send, a completed workflow
instance, the thread and conversation partials and the SSE stream.
"""

import asyncio
import importlib.util
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from seams_gen.__main__ import main as seams_gen_main
from seams_runtime import HeaderAuthenticator, Runtime, RuntimeModelError, model_hash
from tests.test_runtime_worker import FakeLLM

ROOT = Path(__file__).resolve().parents[1]
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
MOUNTED = "/model/chat-app.trig"
USER = {"X-Forwarded-User": "ann"}
URL = "/conversations/c1/messages"


@pytest.fixture
def generated(tmp_path, monkeypatch):
    """(module, client) for the generated app, inside a running TestClient."""
    app_dir = tmp_path / "app"
    assert seams_gen_main(["fastapi", str(TRIG), "--out", str(app_dir)]) == 0
    assert seams_gen_main(["htmx", str(TRIG), "--out", str(app_dir / "templates")]) == 0
    assert (app_dir / "chat_api.py").is_file()
    assert (app_dir / "templates" / "message_thread_item.html").is_file()

    original = Runtime.load
    loads = []

    def load(cls, trig_path, model_hash=None, **kw):
        assert str(trig_path) == MOUNTED, trig_path
        assert not kw, kw  # the generated module passes only the path and the hash
        loads.append(model_hash)
        # model_hash is passed through unchanged: a mismatch must still raise.
        return original(
            TRIG,
            model_hash=model_hash,
            db_path=tmp_path / "seams.sqlite",
            templates_dir=app_dir / "templates",
            authenticator=HeaderAuthenticator(),
            llm_transport=FakeLLM().transport,
            llm_base_url="http://llm-gateway.test",
        )

    monkeypatch.setattr(Runtime, "load", classmethod(load))
    name = f"generated_chat_api_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(name, app_dir / "chat_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert loads == [module.MODEL_HASH]

    app = FastAPI()
    app.include_router(module.router)

    @app.exception_handler(RuntimeModelError)
    async def _model_error(_request, exc: RuntimeModelError):
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.to_dict()})

    with TestClient(app) as client:
        yield module, client, app


def _wait_complete(runtime, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        instances = list(runtime.instances.values())
        if instances and all(i.task is not None and i.task.done() for i in instances):
            return instances
        time.sleep(0.05)
    pytest.fail(f"workflow instances did not finish within {timeout}s: {runtime.instances}")


async def _first_frame(app, path, timeout=5.0):
    """(status, headers, first body chunk) of a streaming GET; then disconnect.

    TestClient buffers the whole body and the SSE scope stays open after the
    process completes (S03 known limitation), so drive the ASGI app directly
    and stop after the first frame."""
    got_frame = asyncio.Event()
    messages = []

    async def receive():
        await got_frame.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            got_frame.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(got_frame.wait(), timeout)
    finally:
        got_frame.set()
        await asyncio.wait_for(task, timeout)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = next(m["body"] for m in messages if m["type"] == "http.response.body" and m.get("body"))
    return start["status"], dict(start["headers"]), body.decode()


def test_generated_module_carries_the_real_model_hash(generated):
    module, _client, _app = generated
    assert module.MODEL_HASH == model_hash(TRIG)
    assert module.runtime.model.hash == model_hash(TRIG)


def test_generated_app_serves_the_chat_flow(generated):
    module, client, app = generated
    runtime = module.runtime

    # boundary: the policy dependency, then the SHACL contract
    r = client.post(URL, data={"role": "user", "content": "hi"})
    assert r.status_code == 401, r.text
    assert runtime.instances == {}

    r = client.post(URL, data={"role": "user", "content": ""}, headers=USER)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["type"] == "ContractViolation"
    assert runtime.instances == {}

    # send: validate, start the instance, append the item partial
    r = client.post(URL, data={"role": "user", "content": "hi"}, headers=USER)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert '<li class="message">' in r.text and "<p>hi</p>" in r.text
    assert "<section" not in r.text  # the item partial, not the thread

    (instance,) = _wait_complete(runtime)
    assert instance.task.exception() is None
    assert instance.result["status"] == "complete", instance.result
    stored = runtime.query(":MessageShape", conversation="c1")
    assert [m["data"]["content"] for m in stored if m["data"].get("role") == "user"] == ["hi"]
    assert stored[-1]["data"]["status"] == "complete"

    # thread: message_thread is seam:visibleWhen every message state but
    # :s_failed, so after the reply completes the thread still renders, with
    # the user's message and the stored reply.
    r = client.get(URL)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "component partial of ifml:Details :message_thread" not in r.text  # Jinja comments stripped
    assert '<section id="message_thread"' in r.text
    assert "<p>hi</p>" in r.text
    assert r.text.count('<li class="message">') == len(stored)

    r = client.get("/conversations")
    assert r.status_code == 200, r.text
    assert "<nav" in r.text

    status, headers, frame = client.portal.call(_first_frame, app, "/conversations/c1/stream")
    assert status == 200
    assert headers[b"content-type"].decode().startswith("text/event-stream")
    assert frame.startswith("event: "), frame


def test_thread_partial_shows_stored_messages_while_composing(generated):
    """The visible branch of the same route: a stored composing message is
    listed in the message_thread section with its content escaped."""
    module, client, _app = generated
    module.runtime.store.put_entity(
        "m1",
        module.runtime.model.curie(":MessageShape"),
        {"role": "user", "content": "<b>draft</b>", "status": "composing"},
        correlation_key="c2",
        status="composing",
    )
    r = client.get("/conversations/c2/messages")
    assert r.status_code == 200, r.text
    assert '<section id="message_thread"' in r.text
    assert 'data-conversation="c2"' in r.text
    assert "&lt;b&gt;draft&lt;/b&gt;" in r.text and "<b>draft</b>" not in r.text


def test_thread_partial_hides_a_failed_conversation(generated):
    """The hidden branch: the latest stored message failed, which is outside
    the thread's seam:visibleWhen states, so the partial renders no section."""
    module, client, _app = generated
    shape = module.runtime.model.curie(":MessageShape")
    module.runtime.store.put_entity(
        "m1", shape, {"role": "user", "content": "hi", "status": "complete"}, correlation_key="c3", status="complete"
    )
    module.runtime.store.put_entity(
        "m2", shape, {"role": "assistant", "content": "oops", "status": "failed"}, correlation_key="c3", status="failed"
    )
    r = client.get("/conversations/c3/messages")
    assert r.status_code == 200, r.text
    assert "<section" not in r.text
    assert "oops" not in r.text


def test_generated_module_refuses_a_different_model_hash(tmp_path, monkeypatch):
    """The wrapper keeps the hash check: a module carrying a stale hash fails to import."""
    from seams_runtime import ModelHashMismatch

    app_dir = tmp_path / "app"
    assert seams_gen_main(["fastapi", str(TRIG), "--out", str(app_dir)]) == 0
    path = app_dir / "chat_api.py"
    path.write_text(path.read_text().replace(model_hash(TRIG), "sha256:" + "0" * 64))
    original = Runtime.load
    monkeypatch.delenv("SEAMS_ALLOW_HASH_MISMATCH", raising=False)
    monkeypatch.setattr(
        Runtime,
        "load",
        classmethod(
            lambda cls, p, model_hash=None, **kw: original(TRIG, model_hash=model_hash, db_path=tmp_path / "s.sqlite")
        ),
    )
    spec = importlib.util.spec_from_file_location(f"stale_chat_api_{tmp_path.name}", path)
    with pytest.raises(ModelHashMismatch):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
