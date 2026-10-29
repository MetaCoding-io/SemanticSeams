"""The htmx fragment partials (M004/S05/T01, GAP-19, D017): the chat app's
UIFragment operations name exactly three partials, each is the page header
plus the page's own lines for that component (or its Details item), each is a
working Jinja2 template, and the name follows the shared fragment_for rule.
"""

import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
from rdflib import Dataset, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import (  # noqa: E402
    GeneratorError, extract_page, fragment_for, generate_fragments, generate_page, render_fragments,
)
from seams_gen.htmx import IFML, TEMPLATE_DIR  # noqa: E402
from seams_runtime import ModelGraph  # noqa: E402

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHAT = "https://example.org/chat/"
SEAM = "https://w3id.org/seams/seam#"
NAMES = {"conversation_list.html", "message_thread.html", "message_thread_item.html"}


def _dataset() -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(TRIG), format="trig")
    return ds


def _model(ds=None) -> ModelGraph:
    return ModelGraph(TRIG, dataset=ds if ds is not None else _dataset())


def _op(local):
    return URIRef(CHAT + local)


# ── the chat app's partials ───────────────────────────────────────────────


def test_chat_app_has_exactly_three_fragments():
    assert set(generate_fragments(TRIG)) == NAMES


def test_fragment_for_names_each_operation():
    model = _model()
    assert fragment_for(model, _op("send_message_op")) == (
        "message_thread_item.html", URIRef(CHAT + "message_thread"), "item")
    assert fragment_for(model, _op("message_thread_op")) == (
        "message_thread.html", URIRef(CHAT + "message_thread"), "component")
    assert fragment_for(model, _op("list_conversations_op")) == (
        "conversation_list.html", URIRef(CHAT + "conversation_list"), "component")


def _page_lines():
    return generate_page(TRIG).splitlines(keepends=True)


def _block_body(component: str) -> str:
    lines = _page_lines()
    start = lines.index("  {% block " + component + " %}\n")
    end = next(i for i in range(start, len(lines)) if lines[i] == "  {% endblock %}\n")
    return "".join(lines[start + 1:end])


def _details_item(component: str) -> str:
    body = _block_body(component).splitlines(keepends=True)
    loop = next(i for i, line in enumerate(body) if line.lstrip().startswith("{% for "))
    end = next(i for i in range(loop, len(body)) if body[i].strip() == "{% endfor %}")
    item = body[loop + 1:end]
    assert item[0].lstrip().startswith("<li") and item[-1].strip() == "</li>"
    return "".join(item)


@pytest.mark.parametrize("name, body, operation", [
    ("conversation_list.html", lambda: _block_body("conversation_list"),
     "component partial of ifml:List :conversation_list, rendered by :list_conversations_op"),
    ("message_thread.html", lambda: _block_body("message_thread"),
     "component partial of ifml:Details :message_thread, rendered by :message_thread_op"),
    ("message_thread_item.html", lambda: _details_item("message_thread"),
     "item partial of ifml:Details :message_thread, rendered by :send_message_op"),
])
def test_fragment_is_header_plus_page_lines(name, body, operation):
    page_header = "".join(_page_lines()[:2])
    expected = page_header + "{# " + operation + " #}\n" + body()
    assert generate_fragments(TRIG)[name] == expected


def test_fragments_are_deterministic():
    assert generate_fragments(TRIG) == generate_fragments(TRIG)
    assert extract_page(_model()).fragments == extract_page(_model()).fragments
    page = extract_page(ModelGraph.load(TRIG))
    assert render_fragments(page) == generate_fragments(TRIG)


def test_no_template_has_domain_literals():
    for path in sorted(TEMPLATE_DIR.glob("*.j2")):
        text = path.read_text(encoding="utf-8").lower()
        for word in ("chat", "conversation", "message"):
            assert word not in text, f"{path.name} hard-codes {word!r}"


# ── each partial is a working Jinja2 template ─────────────────────────────

MESSAGE = {"content": "hello", "role": "user", "status": "sent", "timestamp": "2026-10-28T10:00"}


def _render(name: str, **context) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(generate_fragments(TRIG)[name]).render(**context)


def test_item_fragment_renders_one_message():
    html = _render("message_thread_item.html", message=MESSAGE)
    assert html.count('<li class="message">') == 1
    assert "<p>hello</p>" in html
    assert '<time datetime="2026-10-28T10:00">' in html


def test_thread_fragment_renders_inside_its_guard():
    context = dict(messages=[MESSAGE], conversation="c1")
    html = _render("message_thread.html", message_state="composing", **context)
    assert 'id="message_thread"' in html and "<p>hello</p>" in html
    assert 'sse-connect="/conversations/c1/stream"' in html
    assert 'id="message_thread"' not in _render("message_thread.html", message_state="sending", **context)


def test_list_fragment_renders_links():
    html = _render("conversation_list.html", conversations=[{"id": "c1", "title": "First"}])
    assert 'hx-get="/conversations/c1/messages"' in html and "First" in html


# ── the CLI writes the page and every partial ─────────────────────────────


def test_cli_writes_page_and_fragments(tmp_path):
    out = tmp_path / "out"
    run = subprocess.run([sys.executable, "-m", "seams_gen", "htmx", str(TRIG), "--out", str(out)],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    names = sorted(NAMES | {"chat_page.html"})
    assert run.stdout.splitlines() == [str(out / n) for n in names]
    assert sorted(p.name for p in out.iterdir()) == names
    fragments = generate_fragments(TRIG)
    for name in NAMES:
        assert (out / name).read_bytes() == fragments[name].encode("utf-8")
    assert (out / "chat_page.html").read_bytes() == generate_page(TRIG).encode("utf-8")


# ── mutation: the rule follows the graph ──────────────────────────────────


def _remove(ds, s, p, o=None):
    s, p = URIRef(s), URIRef(p)
    assert (s, p, o) in ds
    for g in ds.graphs():
        g.remove((s, p, o))


@pytest.mark.parametrize("mutate", [
    lambda ds: _remove(ds, CHAT + "send_to_thread", str(IFML.swap)),
    lambda ds: _remove(ds, CHAT + "send_message", SEAM + "submitsTo"),
], ids=["no-append-swap", "no-submitsTo"])
def test_without_the_append_flow_send_names_the_thread(mutate):
    ds = _dataset()
    mutate(ds)
    name, component, kind = fragment_for(_model(ds), _op("send_message_op"))
    assert (name, component, kind) == ("message_thread.html", URIRef(CHAT + "message_thread"), "component")


def test_prepend_swap_also_names_the_item():
    ds = _dataset()
    _remove(ds, CHAT + "send_to_thread", str(IFML.swap))
    ds.graph(URIRef("urn:seams:graph:model:chat_ifml")).add(
        (URIRef(CHAT + "send_to_thread"), IFML.swap, IFML.Prepend))
    assert fragment_for(_model(ds), _op("send_message_op"))[0] == "message_thread_item.html"


# ── negative paths ────────────────────────────────────────────────────────


def _add_seam(ds, s, p, o):
    ds.graph(URIRef("urn:seams:graph:seams")).add((URIRef(s), URIRef(p), URIRef(o)))


def test_second_renders_component_raises():
    ds = _dataset()
    _add_seam(ds, CHAT + "send_message_op", SEAM + "rendersComponent", CHAT + "conversation_list")
    with pytest.raises(GeneratorError) as err:
        fragment_for(_model(ds), _op("send_message_op"))
    assert err.value.subject == CHAT + "send_message_op"
    assert err.value.predicate == SEAM + "rendersComponent"
    with pytest.raises(GeneratorError) as err:
        extract_page(_model(ds))
    assert err.value.predicate == SEAM + "rendersComponent"


def test_no_renders_component_raises():
    ds = _dataset()
    _remove(ds, CHAT + "list_conversations_op", SEAM + "rendersComponent")
    with pytest.raises(GeneratorError) as err:
        fragment_for(_model(ds), _op("list_conversations_op"))
    assert err.value.subject == CHAT + "list_conversations_op"
    assert err.value.predicate == SEAM + "rendersComponent"
    # an operation that renders nothing is not a fragment of the page
    assert "conversation_list.html" not in render_fragments(extract_page(_model(ds)))


def test_item_partial_of_a_list_raises():
    ds = _dataset()
    _remove(ds, CHAT + "send_to_thread", str(IFML.target))
    ds.graph(URIRef("urn:seams:graph:model:chat_ifml")).add(
        (URIRef(CHAT + "send_to_thread"), IFML.target, URIRef(CHAT + "conversation_list")))
    _remove(ds, CHAT + "send_message_op", SEAM + "rendersComponent")
    _add_seam(ds, CHAT + "send_message_op", SEAM + "rendersComponent", CHAT + "conversation_list")
    with pytest.raises(GeneratorError) as err:
        fragment_for(_model(ds), _op("send_message_op"))
    assert err.value.subject == CHAT + "conversation_list"
    assert "ifml:Details" in str(err.value)


def test_fragment_for_rejects_a_non_model():
    with pytest.raises(TypeError):
        fragment_for(TRIG, _op("send_message_op"))

