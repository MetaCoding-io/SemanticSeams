"""seams_runtime.host serves a CLI-generated route module (M004/S07/T02): the
landmark page at its ifml:path with the seeded conversations and the selected
thread, the RuntimeModelError -> JSON mapping, /healthz and an idempotent,
validated startup seed. Runtime.load is redirected exactly as in
tests/test_generated_app.py (repo model, temp store and templates, header
auth, FakeLLM)."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seams_gen.__main__ import main as seams_gen_main
from seams_runtime import ContractViolation, HeaderAuthenticator, ResolutionError, Runtime
from seams_runtime.host import build_app, seed_store
from tests.test_runtime_worker import FakeLLM

ROOT = Path(__file__).resolve().parents[1]
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
SEED = ROOT / "examples" / "chat-app" / "seed.json"
MOUNTED = "/model/chat-app.trig"
USER = {"X-Forwarded-User": "ann"}


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    out = tmp_path / "app"
    assert seams_gen_main(["fastapi", str(TRIG), "--out", str(out)]) == 0
    assert seams_gen_main(["htmx", str(TRIG), "--out", str(out / "templates")]) == 0
    original = Runtime.load

    def load(cls, trig_path, model_hash=None, **kw):
        assert str(trig_path) == MOUNTED, trig_path
        return original(TRIG, model_hash=model_hash, db_path=tmp_path / "seams.sqlite",
                        templates_dir=out / "templates", authenticator=HeaderAuthenticator(),
                        llm_transport=FakeLLM().transport, llm_base_url="http://llm-gateway.test")

    monkeypatch.setattr(Runtime, "load", classmethod(load))
    monkeypatch.setenv("SEAMS_SEED", str(SEED))
    return out


@pytest.fixture
def client(app_dir):
    app = build_app(app_dir / "chat_api.py")
    with TestClient(app) as c:
        yield c, app.state.runtime


def _seed_ids():
    return sorted(item["id"] for item in json.loads(SEED.read_text())[":ConversationShape"])


def _wait_complete(runtime, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        instances = list(runtime.instances.values())
        if instances and all(i.task is not None and i.task.done() for i in instances):
            return instances
        time.sleep(0.05)
    pytest.fail(f"workflow instances did not finish within {timeout}s: {runtime.instances}")


def test_landmark_page_lists_seeded_conversations(client):
    c, runtime = client
    r = c.get("/")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.lstrip().startswith("<!doctype html>")  # Jinja comments stripped
    first = _seed_ids()[0]
    for cid in _seed_ids():
        assert f'hx-get="/conversations/{cid}/messages"' in r.text
    assert f'hx-post="/conversations/{first}/messages"' in r.text
    assert f'data-conversation="{first}"' in r.text  # empty thread, composing: visible
    assert '<li class="message">' not in r.text

    other = _seed_ids()[1]
    r = c.get("/", params={"conversation": other})
    assert f'hx-post="/conversations/{other}/messages"' in r.text


def test_send_then_page_shows_user_message_and_reply(client):
    c, runtime = client
    cid = _seed_ids()[0]
    # role is sent explicitly, as in tests/test_generated_app.py; see the xfail below
    r = c.post(f"/conversations/{cid}/messages", data={"role": "user", "content": "hello host"},
               headers=USER)
    assert r.status_code == 200, r.text
    (instance,) = _wait_complete(runtime)
    assert instance.task.exception() is None
    assert instance.result["status"] == "complete", instance.result

    stored = runtime.query(":MessageShape", conversation=cid)
    reply = [m["data"]["content"] for m in stored if m["data"].get("role") == "assistant"]
    assert reply and reply[-1]
    for route in ("/", f"/?conversation={cid}", f"/conversations/{cid}/messages"):
        r = c.get(route)
        assert r.status_code == 200, (route, r.text)
        assert "<p>hello host</p>" in r.text, route
        assert f"<p>{reply[-1]}</p>" in r.text, route
    # another conversation's page does not show the thread
    r = c.get("/", params={"conversation": _seed_ids()[1]})
    assert "hello host" not in r.text


def test_send_with_only_the_compose_form_fields_completes(client):
    # the compose form posts only content: :routing_decision's dec:input reads
    # :role, which MessageShape's sh:defaultValue "user" supplies
    c, runtime = client
    r = c.post(f"/conversations/{_seed_ids()[0]}/messages", data={"content": "hi"}, headers=USER)
    assert r.status_code == 200, r.text
    assert '<span class="role">user</span>' in r.text
    (instance,) = _wait_complete(runtime)
    assert instance.result["status"] == "complete", instance.result


def test_runtime_errors_map_to_json(client):
    c, runtime = client
    cid = _seed_ids()[0]
    r = c.post(f"/conversations/{cid}/messages", data={"content": ""}, headers=USER)
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"]["type"] == "ContractViolation"
    r = c.post(f"/conversations/{cid}/messages", data={"content": "hi", "bogus": "x"}, headers=USER)
    assert r.status_code == 422 and r.json()["detail"]["results"][0]["constraint"] == "unknown-field"
    r = c.post(f"/conversations/{cid}/messages", data={"content": "hi"})
    assert r.status_code == 401, r.text
    assert runtime.instances == {}


def test_healthz(client):
    c, runtime = client
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model_hash": runtime.model.hash}


def test_second_startup_does_not_duplicate_seed(app_dir):
    for _ in range(2):
        app = build_app(app_dir / "chat_api.py")
        with TestClient(app):
            rows = app.state.runtime.query(":ConversationShape")
    assert sorted(r["id"] for r in rows) == _seed_ids()
    assert seed_store(app.state.runtime, SEED) == 0


def test_invalid_seed_item_fails_startup(app_dir, tmp_path, monkeypatch):
    bad = tmp_path / "bad-seed.json"
    bad.write_text(json.dumps({":ConversationShape": [
        {"id": "ok", "title": "fine"}, {"id": "broken", "title": "x", "colour": "red"}]}))
    monkeypatch.setenv("SEAMS_SEED", str(bad))
    app = build_app(app_dir / "chat_api.py")
    with pytest.raises(ContractViolation) as info:
        with TestClient(app):
            pass
    assert "[1]" in info.value.focus and "broken" in info.value.focus
    assert info.value.results[0]["constraint"] == "unknown-field"
    assert app.state.runtime.query(":ConversationShape") == []  # nothing written


def test_page_without_ifml_path_is_a_resolution_error(app_dir):
    app = build_app(app_dir / "chat_api.py")
    model = app.state.runtime.model
    from seams_runtime.model import IFML
    model.ds.remove((model.landmark_page(), IFML.path, None))
    with pytest.raises(ResolutionError, match="ifml#path"):
        model.page_path(model.landmark_page())
    with pytest.raises(ResolutionError, match="ifml#path"):
        build_app(app_dir / "chat_api.py").state.runtime.model.page_path(":nope")


def test_host_names_no_model_terms():
    src = (ROOT / "seams_runtime" / "host.py").read_text()
    code = re.sub(r'""".*?"""|#.*', "", src, flags=re.S)
    assert not re.search(r'"(:\w+|\w+Shape)"', code)
    assert "conversation" not in code.lower()


def test_host_help_exits_zero():
    r = subprocess.run([sys.executable, "-m", "seams_runtime.host", "--help"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "--routes" in r.stdout and "SEAMS_ROUTES" in r.stdout
