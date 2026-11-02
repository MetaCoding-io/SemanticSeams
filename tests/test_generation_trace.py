"""Line-level generation traces (ADR-0019, M020/S01).

The traced built-in generators (htmx, fastapi, compose, dockerfile) render
the same bytes with and without sentinels, give every non-blank line a
template origin, and trace deterministically; a template whose output the
sentinels change, or a value already holding a sentinel character, raises
GeneratorError naming the template and line.
"""

import json
from pathlib import Path

import jinja2
import pytest

from seams_gen import GeneratorError
from seams_gen.builtin import BUILTINS
from seams_gen.trace import (
    CLOSE,
    OPEN,
    TRACE_VERSION,
    Trace,
    TraceLine,
    TracingEnvironment,
    render_trace_json,
    trace_template,
)

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples/chat-app/chat-app.trig",
    "chapter-08": ROOT / "examples/expenses/chapter-08/expenses.trig",
}
TRACED = [g for g in BUILTINS if g.trace is not None]


def _traces(generator, trig: Path) -> tuple[dict[str, str], dict[str, Trace]]:
    view = generator.extract(trig, trig.parent / "generated")
    assert generator.trace is not None
    return generator.render(view), generator.trace(view)


def test_the_built_in_generators_with_a_trace():
    assert sorted(g.name for g in TRACED) == ["compose", "dockerfile", "fastapi", "htmx"]


@pytest.mark.parametrize("model", sorted(MODELS))
@pytest.mark.parametrize("generator", TRACED, ids=lambda g: g.name)
def test_a_trace_covers_every_non_blank_line_of_each_file(generator, model):
    files, traces = _traces(generator, MODELS[model])
    assert sorted(traces) == sorted(files)
    for name, trace in traces.items():
        assert (trace.output, trace.generator) == (name, generator.name)
        non_blank = [n for n, line in enumerate(files[name].split("\n"), start=1) if line.strip()]
        assert [line.line for line in trace.lines] == non_blank, name
        for line in trace.lines:
            assert line.templates, f"{name}:{line.line}"
            assert all(":" in origin and origin.split(":")[0].endswith(".j2") for origin in line.templates)
            assert list(line.terms) == sorted(set(line.terms))
            assert all(term.startswith(("http://", "https://", "urn:")) for term in line.terms)


@pytest.mark.parametrize("generator", TRACED, ids=lambda g: g.name)
def test_tracing_leaves_the_output_byte_for_byte(generator):
    trig = MODELS["chat-app"]
    view = generator.extract(trig, trig.parent / "generated")
    before = generator.render(view)
    assert generator.trace is not None
    generator.trace(view)
    assert generator.render(view) == before
    assert generator.generate(trig, trig.parent / "generated") == before
    assert not any(OPEN in text or CLOSE in text for text in before.values())


def test_every_non_blank_chat_page_line_has_a_template_origin():
    htmx = next(g for g in TRACED if g.name == "htmx")
    files, traces = _traces(htmx, MODELS["chat-app"])
    page = traces["chat_page.html"]
    lines = files["chat_page.html"].split("\n")
    assert len(page.lines) == sum(1 for line in lines if line.strip())
    assert all(line.templates for line in page.lines)
    assert page.lines[0].templates == ("htmx_page.html.j2:7",)
    # a component's lines: the page's include line first, then the component template's line
    nested = [line for line in page.lines if len(line.templates) > 1]
    assert nested
    assert all(line.templates[0].startswith("htmx_page.html.j2:") for line in nested)
    assert all(line.templates[1].startswith("htmx_component.html.j2:") for line in nested)
    # an item partial included by a component: three levels, outermost first
    assert any(len(line.templates) == 3 and line.templates[2].startswith("htmx_item.html.j2:") for line in nested)
    assert "https://example.org/chat/chat_page" in page.terms


def test_a_line_inside_an_include_takes_its_component_s_terms():
    htmx = next(g for g in TRACED if g.name == "htmx")
    _, traces = _traces(htmx, MODELS["chat-app"])
    page = traces["chat_page.html"]
    component_lines = [line for line in page.lines if line.templates[-1].startswith("htmx_component.html.j2:")]
    assert all("https://example.org/chat/chat_page" not in line.terms for line in component_lines)
    assert {"https://example.org/chat/conversation_list"} <= {t for line in component_lines for t in line.terms}


@pytest.mark.parametrize("generator", TRACED, ids=lambda g: g.name)
def test_tracing_is_deterministic(generator):
    _, first = _traces(generator, MODELS["chat-app"])
    _, second = _traces(generator, MODELS["chat-app"])
    assert {n: render_trace_json(t) for n, t in first.items()} == {n: render_trace_json(t) for n, t in second.items()}


def test_the_trace_json_format():
    trace = Trace("page.html", "htmx", (TraceLine(1, ("a.j2:1", "b.j2:2"), ("https://x/b", "https://x/c")),))
    text = render_trace_json(trace)
    assert text.endswith("}\n")
    assert json.loads(text) == {
        "generator": "htmx",
        "lines": [{"line": 1, "templates": ["a.j2:1", "b.j2:2"], "terms": ["https://x/b", "https://x/c"]}],
        "output": "page.html",
        "trace_version": TRACE_VERSION,
    }
    assert list(json.loads(text)) == sorted(json.loads(text))
    assert trace.terms == ("https://x/b", "https://x/c")


class _View:
    def __init__(self, iri: str, label: str):
        self.iri = iri
        self.label = label


def _env(templates: dict[str, str]) -> TracingEnvironment:
    return TracingEnvironment(
        loader=jinja2.DictLoader(templates), trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True
    )


def _trace(templates: dict[str, str], name: str, **context) -> Trace:
    expected = jinja2.Environment(
        loader=jinja2.DictLoader(templates), trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True
    )
    text = expected.get_template(name).render(context)
    return trace_template(_env(templates), name, context, output="out.txt", generator="t", expected=text)


def test_terms_come_from_values_read_off_an_iri_carrying_object():
    trace = _trace(
        {"t.j2": "fixed\n{{ v.label }}\n{% if v %}\n{# comment #}\n  {{ 'x' }}\n{% endif %}\n"},
        "t.j2",
        v=_View("https://x/v", "hello"),
    )
    assert trace.lines == (
        TraceLine(1, ("t.j2:1",), ()),
        TraceLine(2, ("t.j2:2",), ("https://x/v",)),
        TraceLine(3, ("t.j2:5",), ()),
    )


def test_a_multi_line_value_traces_each_of_its_lines_to_the_expression():
    trace = _trace({"t.j2": "a {{ v.label }} b\n"}, "t.j2", v=_View("https://x/v", "one\ntwo"))
    assert [(line.line, line.templates) for line in trace.lines] == [(1, ("t.j2:1",)), (2, ("t.j2:1",))]


def test_a_value_holding_a_sentinel_character_raises():
    with pytest.raises(GeneratorError) as e:
        _trace({"t.j2": "ok\n{{ v.label }}\n"}, "t.j2", v=_View("https://x/v", f"bad{OPEN}"))
    assert e.value.subject == "t.j2"
    assert "line 2 of out.txt already holds a trace sentinel character" in e.value.detail


def test_a_template_whose_output_the_sentinels_change_raises():
    # a filter block reverses the text it wraps, sentinels included
    templates = {"t.j2": "ok\nx{% filter reverse %}abc{% endfilter %}y\n"}
    with pytest.raises(GeneratorError) as e:
        _trace(templates, "t.j2")
    assert e.value.subject == "t.j2:2"
    assert "differs from the normal render at line 2" in e.value.detail


def test_a_trace_against_a_different_expected_text_raises():
    templates = {"t.j2": "one\ntwo\n"}
    with pytest.raises(GeneratorError) as e:
        trace_template(_env(templates), "t.j2", {}, output="out.txt", generator="t", expected="one\nTWO\n")
    assert e.value.subject == "t.j2:2"
