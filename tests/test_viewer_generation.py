"""The generation view's trace index (backlog T3, M020/S02, ADR-0019).

viewer.generation joins seams.lock, the <output>.trace.json sidecars and the
templates they cite. On the committed chat app every traced output loads with
no notice; IRIs are read from the committed sidecars, never named here. Broken
projects are built in tmp_path: each bad file is one notice naming it.
"""

import json
import sys
from pathlib import Path

import pytest

from seams_gen.registry import discover

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import generation  # noqa: E402

CHAT = ROOT / "examples" / "chat-app"
CHAT_API = "generated/chat_api.py"


@pytest.fixture(autouse=True)
def clear_cache():
    generation._clear_cache()
    yield
    generation._clear_cache()


def _locked_paths(base: Path) -> list[str]:
    lock = json.loads((base / "seams.lock").read_text(encoding="utf-8"))
    return sorted(o["path"] for o in lock["outputs"] if not o["path"].endswith(".trace.json"))


def _project(tmp_path: Path, generator: str = "fastapi", sidecar: str | None = None) -> Path:
    """A one-output project: seams.lock naming out.py, the output, and ``sidecar`` when given."""
    entry = {"path": "out.py", "generator": generator, "sources": []}
    (tmp_path / "seams.lock").write_text(json.dumps({"lockfile_version": 1, "outputs": [entry]}), encoding="utf-8")
    (tmp_path / "out.py").write_text("a = 1\n", encoding="utf-8")
    if sidecar is not None:
        (tmp_path / "out.py.trace.json").write_text(sidecar, encoding="utf-8")
    return tmp_path


def _sidecar(lines: list[dict], version: int = 1) -> str:
    return json.dumps({"generator": "fastapi", "lines": lines, "output": "out.py", "trace_version": version})


# -- the committed chat app ----------------------------------------------------


def test_chat_app_outputs_load_without_notices():
    index = generation.get_index(CHAT)
    assert index.notices == ()
    assert [o.path for o in index.outputs] == _locked_paths(CHAT)
    for out in index.outputs:
        assert out.traced
        assert out.text == (CHAT / out.path).read_text(encoding="utf-8")
        assert out.lines, out.path
        assert [tl.line for tl in out.lines] == sorted(tl.line for tl in out.lines)


def test_chat_api_lines_match_its_sidecar():
    sidecar = json.loads((CHAT / f"{CHAT_API}.trace.json").read_text(encoding="utf-8"))
    out = generation.get_index(CHAT).output(CHAT_API)
    assert out is not None and out.generator == sidecar["generator"]
    assert [(tl.line, list(tl.templates), list(tl.terms)) for tl in out.lines] == [
        (e["line"], e["templates"], e["terms"]) for e in sidecar["lines"]
    ]
    first = sidecar["lines"][0]
    assert out.line(first["line"]) is not None
    assert out.line(10_000) is None


def test_fanout_of_an_iri_from_chat_api_trace():
    sidecar = json.loads((CHAT / f"{CHAT_API}.trace.json").read_text(encoding="utf-8"))
    iri = sidecar["lines"][0]["terms"][0]
    expected_api = sorted(e["line"] for e in sidecar["lines"] if iri in e["terms"])

    index = generation.get_index(CHAT)
    citing = index.citing(iri)
    assert citing == tuple(sorted(citing))
    assert [line for path, line in citing if path == CHAT_API] == expected_api
    # every pair is a line whose trace cites the IRI, and every such line is listed
    for out in index.outputs:
        lines = [tl.line for tl in out.lines if iri in tl.terms]
        assert [line for path, line in citing if path == out.path] == lines
    assert list(index.fanout) == sorted(index.fanout)
    assert index.citing("https://example.invalid/never-traced") == ()


def test_cited_templates_resolve_to_their_source():
    index = generation.get_index(CHAT)
    cited = {o.rpartition(":")[0] for out in index.outputs for tl in out.lines for o in tl.templates}
    assert sorted(index.templates) == sorted(cited)
    for name, text in index.templates.items():
        assert text == (ROOT / "seams_gen" / "templates" / name).read_text(encoding="utf-8")
    for out in index.outputs:
        for tl in out.lines:
            for origin in tl.templates:
                name, _, number = origin.rpartition(":")
                assert 1 <= int(number) <= len(index.templates[name].splitlines()), origin


def test_index_is_cached_and_rebuilds_identically():
    first = generation.get_index(CHAT)
    assert generation.get_index(CHAT) is first
    generation._clear_cache()
    second = generation.get_index(CHAT)
    assert second is not first
    assert second == first


def test_index_holds_no_absolute_paths():
    index = generation.get_index(CHAT)
    for out in index.outputs:
        assert not Path(out.path).is_absolute()
    for notice in index.notices:
        assert str(ROOT) not in notice.message


# -- broken projects -------------------------------------------------------------


def test_missing_sidecar_is_a_notice_naming_it(tmp_path):
    index = generation.get_index(_project(tmp_path))
    assert index.notices == (generation.Notice("out.py.trace.json", "trace sidecar is missing"),)
    out = index.output("out.py")
    assert out is not None and out.text == "a = 1\n" and out.lines == () and out.traced
    assert index.fanout == {}


def test_malformed_json_sidecar_is_a_notice_naming_it(tmp_path):
    index = generation.get_index(_project(tmp_path, sidecar="{not json"))
    assert [n.file for n in index.notices] == ["out.py.trace.json"]
    assert "malformed" in index.notices[0].message
    assert index.output("out.py") is not None


@pytest.mark.parametrize(
    "sidecar",
    [
        _sidecar([], version=2),
        _sidecar([{"line": 0, "templates": [], "terms": []}]),
        _sidecar([{"line": 1, "templates": "x.j2:1", "terms": []}]),
        _sidecar([{"line": 1, "templates": [], "terms": [7]}]),
        _sidecar([{"line": 1, "templates": []}]),
        json.dumps({"trace_version": 1, "lines": {}}),
        json.dumps([1, 2]),
    ],
    ids=["version", "line-zero", "templates-not-list", "term-not-str", "no-terms", "lines-not-list", "not-object"],
)
def test_ill_formed_sidecar_is_a_notice_naming_it(tmp_path, sidecar):
    index = generation.get_index(_project(tmp_path, sidecar=sidecar))
    assert [n.file for n in index.notices] == ["out.py.trace.json"]
    assert index.notices[0].message.startswith("trace sidecar is malformed")
    assert index.output("out.py").lines == ()


def test_unknown_template_is_a_notice_naming_it(tmp_path):
    lines = [{"line": 1, "templates": ["no_such_template.j2:1"], "terms": ["https://example.invalid/a"]}]
    index = generation.get_index(_project(tmp_path, sidecar=_sidecar(lines)))
    assert [n.file for n in index.notices] == ["no_such_template.j2"]
    assert index.templates == {}
    assert index.citing("https://example.invalid/a") == (("out.py", 1),)


def test_missing_output_is_a_notice_naming_it(tmp_path):
    base = _project(tmp_path, sidecar=_sidecar([]))
    (base / "out.py").unlink()
    index = generation.get_index(base)
    assert [n.file for n in index.notices] == ["out.py"]
    assert index.output("out.py").text is None


def test_generator_without_trace_hook_is_untraced_not_missing(tmp_path):
    untraced = sorted(name for name, gen in discover().items() if gen.trace is None)
    assert untraced, "the registry has a generator without a trace hook"
    index = generation.get_index(_project(tmp_path, generator=untraced[0]))
    assert index.notices == ()
    out = index.output("out.py")
    assert out is not None and not out.traced and out.lines == ()


def test_no_lock_is_a_notice(tmp_path):
    index = generation.get_index(tmp_path)
    assert [n.file for n in index.notices] == ["seams.lock"]
    assert index.outputs == ()


def test_malformed_lock_is_a_notice(tmp_path):
    (tmp_path / "seams.lock").write_text('{"outputs": 3}', encoding="utf-8")
    index = generation.get_index(tmp_path)
    assert [n.file for n in index.notices] == ["seams.lock"]
    assert "cannot be read" in index.notices[0].message
