"""Runtime.render_fragment / FragmentRenderer (M004/S05, D017).

Hand-written template fixtures in tmp_path, so these tests do not depend on
the seams_gen output.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seams_runtime import ResolutionError, Runtime  # noqa: E402
from seams_runtime.fragments import FragmentRenderer, flatten  # noqa: E402

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"

TEMPLATES = {
    "message_thread_item.html": "<li>{{ message.content }}|{{ message.status }}|{{ message.id }}"
    "|{{ message_state }}|{{ extra }}</li>",
    "message_thread.html": "{{ message_state }}:{% for m in messages %}[{{ m.content }}/{{ m.status }}]"
    "{% endfor %}:{{ conversation }}",
    "conversation_list.html": "{% for c in conversations %}<a>{{ c.id }}={{ c.title }}</a>{% endfor %}"
    "{{ conversation_state is defined }}",
}


@pytest.fixture
def templates(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    for name, body in TEMPLATES.items():
        (d / name).write_text(body)
    return d


@pytest.fixture
def runtime(tmp_path, templates):
    return Runtime.load(TRIG, db_path=tmp_path / "seams.sqlite", templates_dir=templates)


def _html(response) -> str:
    assert isinstance(response, HTMLResponse)
    return response.body.decode()


def test_item_partial_binds_message(runtime):
    ctx = runtime.fragments.context("message_thread_item.html", {"content": "hi", "role": "user"})
    assert ctx["message"] == {"content": "hi", "role": "user"}
    assert "messages" not in ctx
    assert ctx["message_state"] == "composing"
    out = _html(runtime.render_fragment("message_thread_item.html", {"content": "hi"}))
    assert out == "<li>hi|||composing|</li>"  # lenient Undefined for status/id/extra


def test_component_partial_binds_list_and_initial_state(runtime):
    ctx = runtime.fragments.context("message_thread.html", [])
    assert ctx == {"messages": [], "message_state": "composing"}


def test_component_state_is_last_item_status(runtime):
    rows = [{"content": "a", "status": "complete"}, {"content": "b", "status": "streaming"}, {"content": "c"}]
    ctx = runtime.fragments.context("message_thread.html", rows)
    assert ctx["message_state"] == "streaming"
    assert (
        _html(runtime.render_fragment("message_thread.html", rows, conversation="c1"))
        == "streaming:[a/complete][b/streaming][c/]:c1"
    )


def test_conversation_list_has_no_state(runtime):
    ctx = runtime.fragments.context("conversation_list.html", [{"id": "c1", "title": "T"}])
    assert ctx == {"conversations": [{"id": "c1", "title": "T"}]}
    assert _html(runtime.render_fragment("conversation_list.html", [{"id": "c1", "title": "T"}])) == "<a>c1=T</a>False"


def test_store_rows_are_flattened(runtime):
    runtime.store.put_entity(
        "m1", runtime.model.curie(":MessageShape"), {"content": "x"}, correlation_key="c1", status="complete"
    )
    runtime.store.put_entity(
        "m2",
        runtime.model.curie(":MessageShape"),
        {"content": "y", "status": "streaming"},
        correlation_key="c1",
        status="complete",
    )
    rows = runtime.query(":MessageShape", conversation="c1")
    ctx = runtime.fragments.context("message_thread.html", rows)
    assert [(m["id"], m["content"], m["status"]) for m in ctx["messages"]] == [
        ("m1", "x", "complete"),
        ("m2", "y", "streaming"),
    ]  # payload status wins
    assert ctx["message_state"] == "streaming"
    assert flatten({"content": "plain"}) == {"content": "plain"}


def test_extra_params_reach_template_and_win(runtime):
    out = _html(
        runtime.render_fragment("message_thread_item.html", {"content": "hi"}, extra="E", message_state="override")
    )
    assert out == "<li>hi|||override|E</li>"


def test_html_is_escaped(runtime):
    out = _html(runtime.render_fragment("message_thread_item.html", {"content": "<script>x</script>"}))
    assert "<script>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out


@pytest.mark.parametrize(
    "name", ["../etc/passwd.html", "nope.html", "nope_item.html", "/etc/passwd", "message_thread/../../x.html", ""]
)
def test_unknown_name_raises_without_reading_files(runtime, monkeypatch, name):
    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(f), real_open(f, *a, **k))[1])
    with pytest.raises(ResolutionError) as err:
        runtime.render_fragment(name, [])
    assert repr(name) in err.value.detail
    assert "rendersComponent" in err.value.predicate
    assert opened == []
    runtime.render_fragment("message_thread.html", [])  # control: the spy does see template reads
    assert [Path(f).name for f in opened] == ["message_thread.html"]


def test_component_without_template_file_raises_template_not_found(runtime, templates):
    (templates / "conversation_list.html").unlink()
    import jinja2

    with pytest.raises(jinja2.TemplateNotFound):
        runtime.render_fragment("conversation_list.html", [])


def test_seams_templates_env_is_honoured(tmp_path, templates, monkeypatch):
    monkeypatch.setenv("SEAMS_TEMPLATES", str(templates))
    rt = Runtime.load(TRIG, db_path=tmp_path / "seams.sqlite")
    assert rt.templates_dir == templates
    assert _html(rt.render_fragment("conversation_list.html", [])) == "False"


def test_templates_default_and_argument_precedence(tmp_path, templates, monkeypatch):
    monkeypatch.delenv("SEAMS_TEMPLATES", raising=False)
    assert Runtime.load(TRIG, db_path=tmp_path / "a.sqlite").templates_dir == Path("templates")
    monkeypatch.setenv("SEAMS_TEMPLATES", str(tmp_path / "elsewhere"))
    rt = Runtime.load(TRIG, db_path=tmp_path / "b.sqlite", templates_dir=templates)
    assert rt.templates_dir == templates


def test_renderer_standalone(runtime, templates):
    r = FragmentRenderer(runtime.model, templates)
    frag = r.resolve("message_thread_item.html")
    assert frag.item and frag.template == "message_thread_item.html"
    assert str(frag.shape).endswith("MessageShape")
