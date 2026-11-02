"""Line-level generation traces (ADR-0019, M020/S01).

The traced built-in generators (htmx, fastapi, compose, dockerfile) render
the same bytes with and without sentinels, give every non-blank line a
template origin, and trace deterministically; a template whose output the
sentinels change, or a value already holding a sentinel character, raises
GeneratorError naming the template and line.

The traces agree with the golden markers (docs/generation/golden/): on every
golden line that matches a generated line once its marker is stripped, each
model element (a subject of the model) a `[graph: ...]` marker cites is in
the line's trace terms or in its enclosing view object's, and each `[fixed]` line has a template origin.
"""

import difflib
import json
import sys
from pathlib import Path

import jinja2
import pytest
from rdflib import Dataset, URIRef

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
    view_iris,
)

ROOT = Path(__file__).resolve().parent.parent
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from test_golden_outputs import CHAT, GOLDEN, IRI, MARKER, PREFIXES, TERM  # noqa: E402

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


class _Derived(_View):
    def __init__(self, iri: str, label: str, origins: tuple[str, ...]):
        super().__init__(iri, label)
        self.origins = origins


def test_a_value_carries_its_object_s_iri_and_origins_and_a_fallback_takes_them_too():
    v = _Derived("https://x/v", "hello", ("https://x/a", "https://x/b"))
    trace = _trace({"t.j2": "{{ v.label }}\nfixed\n"}, "t.j2", v=v)
    assert trace.lines[0].terms == ("https://x/a", "https://x/b", "https://x/v")
    assert view_iris(v) == ("https://x/v", "https://x/a", "https://x/b")
    # origins without an iri are no view object's
    assert view_iris(type("O", (), {"iri": "", "origins": ("https://x/a",)})()) == ()


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


# ── traces against the golden markers ──────────────────────────────────────

# golden file -> (generator, the file name it renders)
GOLDEN_OUTPUTS = {
    "chat_page.html": ("htmx", "chat_page.html"),
    "chat_api.py": ("fastapi", "chat_api.py"),
    "compose.development.yaml": ("compose", "compose.development.yaml"),
    "compose.production.yaml": ("compose", "compose.production.yaml"),
}
# A golden line must match a generated line for its marker to be checked; the
# rest are the goldens' known divergences from today's output.
MIN_ALIGNED = 0.85
# Cited elements the generator does not read for that line, so no trace can
# honestly name them (docs/backlog.md, T1 question): the golden explains the
# route's whole-component partial by the htmx side's ifml:Replace flow.
KNOWN_GAPS = {("chat_api.py", 31, ":select_to_thread")}


def _strip_marker(line: str) -> str:
    """A golden line without its marker: a marker-only trailing comment goes
    with its comment, a marker inside an existing comment goes alone."""
    m = MARKER.search(line)
    assert m, line
    before, after = line[: m.start()].rstrip(), line[m.end() :]
    for opener, closer in (("{#", "#}"), ("#", "")):
        if before.endswith(opener) and after.strip() == closer:
            return before[: -len(opener)].rstrip()
    return before + after


def _model_iri(token: str, elements: set[str]) -> str | None:
    """The full IRI of a cited model element: `:local` or `<iri>` in the chat
    namespace naming a subject of the model. None for a vocabulary term, prose
    or an IRI the model only uses as an object (an undeclared sh:path, which
    `seams check` flags), since trace terms and lock sources are elements."""
    if m := IRI.match(token):
        iri = m["iri"]
    elif (m := TERM.match(token)) and m["prefix"] == "":
        iri = CHAT + m["local"]
    else:
        assert not (m and m["prefix"] not in PREFIXES), f"unknown prefix in {token!r}"
        return None
    return iri if iri.startswith(CHAT) and iri in elements else None


def _enclosing_terms(trace: Trace) -> dict[tuple[str, ...], set[str]]:
    """{include chain: the terms of its lines}. A line-level trace records no
    loop scope (ADR-0019; value-level spans wait for backlog T2), so a line's
    enclosing view object's terms are those of the include it is in."""
    scopes: dict[tuple[str, ...], set[str]] = {}
    for line in trace.lines:
        scopes.setdefault(line.templates[:-1], set()).update(line.terms)
    return scopes


def _golden_misses(
    name: str, golden: str, output: str, trace: Trace, elements: set[str]
) -> tuple[set[tuple[str, int, str]], float]:
    """The (golden file, golden line, cited token)s whose element the trace
    does not name, a `[fixed]` line without a template origin as token
    "[fixed]"; and the fraction of golden lines that matched an output line."""
    gold = [(n, line) for n, line in enumerate(golden.split("\n"), start=1) if line.strip()]
    lines = output.split("\n")
    by_line = {line.line: line for line in trace.lines}
    scopes = _enclosing_terms(trace)
    matcher = difflib.SequenceMatcher(None, [_strip_marker(line) for _, line in gold], lines, autojunk=False)
    misses: set[tuple[str, int, str]] = set()
    aligned = 0
    for a, b, size in matcher.get_matching_blocks():
        for i in range(size):
            number, line = gold[a + i]
            traced = by_line.get(b + i + 1)
            aligned += 1
            marker = MARKER.search(line)
            assert marker
            if marker[1] == "fixed":
                if traced is None or not traced.templates:
                    misses.add((name, number, "[fixed]"))
                continue
            if not marker[1].startswith("graph: "):
                continue
            for token in marker[1][len("graph: ") :].split():
                iri = _model_iri(token, elements)
                if iri is None:
                    continue
                if traced is None or (iri not in traced.terms and iri not in scopes[traced.templates[:-1]]):
                    misses.add((name, number, token))
    return misses, aligned / len(gold)


@pytest.fixture(scope="module")
def chat_elements() -> set[str]:
    ds = Dataset()
    ds.parse(MODELS["chat-app"], format="trig")
    return {str(s) for s, _, _, _ in ds.quads((None, None, None, None)) if isinstance(s, URIRef)}


@pytest.fixture(scope="module")
def chat_traces() -> dict[str, tuple[dict[str, str], dict[str, Trace]]]:
    by_name = {g.name: g for g in TRACED}
    return {name: _traces(by_name[name], MODELS["chat-app"]) for name in {g for g, _ in GOLDEN_OUTPUTS.values()}}


@pytest.mark.parametrize("golden", sorted(GOLDEN_OUTPUTS))
def test_the_traces_name_every_element_the_golden_markers_cite(golden, chat_traces, chat_elements):
    generator, output = GOLDEN_OUTPUTS[golden]
    files, traces = chat_traces[generator]
    misses, aligned = _golden_misses(
        golden, (GOLDEN / golden).read_text(), files[output], traces[output], chat_elements
    )
    assert aligned >= MIN_ALIGNED, f"{golden}: only {aligned:.0%} of its lines match the generated {output}"
    known = {gap for gap in KNOWN_GAPS if gap[0] == golden}
    assert misses == known, f"{golden}: unexplained {sorted(misses - known)}, closed {sorted(known - misses)}"


def test_the_golden_comparison_reports_an_untraced_element_and_an_originless_fixed_line():
    golden = "a  # [graph: :chat_page ifml:title]\nb  # [graph: :other]\nc  # [fixed]\n"
    trace = Trace(
        "x.py",
        "t",
        (
            TraceLine(1, ("t.j2:1",), ("https://example.org/chat/chat_page",)),
            TraceLine(2, ("t.j2:2",), ()),
        ),
    )
    misses, aligned = _golden_misses("x.py", golden, "a\nb\nc\n", trace, {CHAT + "chat_page", CHAT + "other"})
    assert misses == {("x.py", 2, ":other"), ("x.py", 3, "[fixed]")}
    assert aligned == 1


def test_the_golden_comparison_takes_the_enclosing_include_s_terms():
    golden = "{# [graph: :page] #}\n  x  {# [graph: :part] #}\n  y  {# [graph: :part] #}\n"
    trace = Trace(
        "x.html",
        "t",
        (
            TraceLine(1, ("p.j2:1",), ("https://example.org/chat/page",)),
            TraceLine(2, ("p.j2:2", "c.j2:1"), ("https://example.org/chat/part",)),
            TraceLine(3, ("p.j2:2", "c.j2:2"), ()),
        ),
    )
    elements = {CHAT + "page", CHAT + "part"}
    assert _golden_misses("x.html", golden, "\n  x\n  y\n", trace, elements) == (set(), 1.0)
    # the page's term is not in the include's scope
    other = Trace("x.html", "t", (*trace.lines[:2], TraceLine(3, ("p.j2:3",), ())))
    golden_page = "{# [graph: :page] #}\n  x  {# [graph: :part] #}\n  y  {# [graph: :part] #}\n"
    assert _golden_misses("x.html", golden_page, "\n  x\n  y\n", other, elements)[0] == {("x.html", 3, ":part")}


def test_the_golden_comparison_skips_a_cited_iri_the_model_declares_no_element_for():
    golden = "a  # [graph: :undeclared_path]\n"
    trace = Trace("x.py", "t", (TraceLine(1, ("t.j2:1",), ()),))
    assert _golden_misses("x.py", golden, "a\n", trace, set()) == (set(), 1.0)
    assert _golden_misses("x.py", golden, "a\n", trace, {CHAT + "undeclared_path"})[0] == {
        ("x.py", 1, ":undeclared_path")
    }


def test_a_marker_strips_with_its_own_comment_or_alone():
    assert _strip_marker("  <li>  {# [graph: :x] #}") == "  <li>"
    assert _strip_marker("{# page :p [graph: :p] #}") == "{# page :p #}"
    assert _strip_marker("name: x  # [graph: :x]") == "name: x"
    assert _strip_marker("# Route module for :x  # [graph: :x]") == "# Route module for :x"
