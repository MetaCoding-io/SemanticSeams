"""The generation view's trace index (backlog T3, M020/S02, ADR-0019).

viewer.generation joins seams.lock, the <output>.trace.json sidecars and the
templates they cite. On the committed chat app every traced output loads with
no notice; IRIs are read from the committed sidecars, never named here. Broken
projects are built in tmp_path: each bad file is one notice naming it.
"""

import json
import sys
from html import escape
from pathlib import Path
from urllib.parse import quote

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


# -- the generation view route (T02) ----------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from viewer import app as viewer_app

    return TestClient(viewer_app.app)


def _url(iri: str, query: str = "") -> str:
    return f"/generation/{quote(iri, safe='')}{query}"


def _api_sidecar() -> dict:
    return json.loads((CHAT / f"{CHAT_API}.trace.json").read_text(encoding="utf-8"))


def _attrs(entry: dict) -> str:
    return (
        f'data-line="{entry["line"]}" data-template="{" ".join(entry["templates"])}" '
        f'data-terms="{" ".join(sorted(set(entry["terms"])))}"'
    )


def _api_iri() -> str:
    """A term of chat_api.py's trace that other outputs cite too, so the fan-out spans files."""
    index = generation.get_index(CHAT)
    terms = sorted({t for e in _api_sidecar()["lines"] for t in e["terms"]})
    spanning = [t for t in terms if len({p for p, _ in index.citing(t)}) > 1]
    assert spanning, "a chat_api.py term is cited by more than one output"
    return spanning[0]


def test_generation_view_has_three_panes_with_trace_attributes(client):
    iri = _api_iri()
    citing = generation.get_index(CHAT).citing(iri)
    first_output, first_line = citing[0]
    resp = client.get(_url(iri))
    assert resp.status_code == 200
    body = resp.text
    for pane in ("pane-model", "pane-template", "pane-output"):
        assert f'id="{pane}"' in body
    assert f'data-output="{first_output}"' in body
    # the element heads the model pane, and the first citing line is selected
    assert f'class="term focus" data-term="{iri}"' in body
    assert f'class="oline cites on" id="L{first_line}"' in body
    assert "generation-notices" not in body
    sidecar = json.loads((CHAT / f"{first_output}.trace.json").read_text(encoding="utf-8"))
    for entry in sidecar["lines"]:
        assert _attrs(entry) in body, entry["line"]


def test_generation_view_template_pane_marks_the_selected_lines_origins(client):
    iri = _api_iri()
    entry = next(e for e in _api_sidecar()["lines"] if iri in e["terms"])
    resp = client.get(_url(iri, f"?output={quote(CHAT_API, safe='')}&line={entry['line']}"))
    assert resp.status_code == 200
    body = resp.text
    assert _attrs(entry) in body
    assert f'data-output="{CHAT_API}"' in body
    for origin in entry["templates"]:
        assert f'class="tline on" data-origin="{origin}"' in body
    name = entry["templates"][0].rpartition(":")[0]
    source = (ROOT / "seams_gen" / "templates" / name).read_text(encoding="utf-8")
    assert body.count(f'data-origin="{name}:') == len(source.splitlines())


def test_generation_view_fanout_lists_every_citing_line(client):
    iri = _api_iri()
    citing = generation.get_index(CHAT).citing(iri)
    body = client.get(_url(iri)).text
    assert body.count('class="fanout-entry') == len(citing)
    for path, line in citing:
        href = _url(iri, f"?output={quote(path, safe='')}&line={line}")
        assert f'href="{escape(href)}" data-output="{path}" data-line="{line}"' in body
    assert body.count("fanout-entry selected") == 1


def test_generation_view_follows_a_fanout_link_into_another_output(client):
    iri = _api_iri()
    path, line = next((p, n) for p, n in generation.get_index(CHAT).citing(iri) if p != CHAT_API)
    body = client.get(_url(iri, f"?output={quote(path, safe='')}&line={line}")).text
    assert f'data-output="{path}"' in body
    assert f'class="oline cites on" id="L{line}"' in body


@pytest.mark.parametrize("query", ["?output=no/such/file.py&line=3", "?output=generated/chat_api.py&line=99999"])
def test_generation_view_ignores_an_unknown_output_or_line(client, query):
    iri = _api_iri()
    citing = generation.get_index(CHAT).citing(iri)
    resp = client.get(_url(iri, query))
    assert resp.status_code == 200
    shown = CHAT_API if "chat_api" in query else citing[0][0]
    first = next(n for p, n in citing if p == shown)
    assert f'data-output="{shown}"' in resp.text
    assert f'id="L{first}"' in resp.text and ' on" id="L' in resp.text


def _untraced_model_iri() -> str:
    """An element of the chat model that no generated line cites."""
    from rdflib import URIRef

    from viewer import app as viewer_app

    fanout = generation.get_index(CHAT).fanout
    subjects = sorted({str(s) for s in viewer_app.get_graph().subjects() if isinstance(s, URIRef)})
    uncited = [s for s in subjects if s not in fanout]
    assert uncited, "the chat model has an element no output cites"
    return uncited[0]


@pytest.mark.parametrize("which", ["unknown", "untraced"])
def test_generation_view_of_an_uncited_iri_is_a_notice(client, which):
    iri = "https://example.invalid/never-traced" if which == "unknown" else _untraced_model_iri()
    resp = client.get(_url(iri))
    assert resp.status_code == 200
    assert 'id="generation-notices"' in resp.text
    assert f"<code>{iri}</code>: no generated line cites this element" in resp.text
    assert 'id="generation-panes"' not in resp.text
    assert "fanout-entry" not in resp.text


def test_generation_view_names_a_missing_sidecar(client, tmp_path, monkeypatch):
    from viewer import app as viewer_app

    lines = [{"line": 1, "templates": [], "terms": ["https://example.invalid/a"]}]
    base = _project(tmp_path, sidecar=_sidecar(lines))
    (base / "seams.lock").write_text(
        json.dumps(
            {
                "lockfile_version": 1,
                "outputs": [
                    {"path": "out.py", "generator": "fastapi", "sources": []},
                    {"path": "other.py", "generator": "fastapi", "sources": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    (base / "other.py").write_text("b = 2\n", encoding="utf-8")
    monkeypatch.setattr(viewer_app, "MODEL_DIR", base)
    resp = client.get(_url("https://example.invalid/a"))
    assert resp.status_code == 200
    assert '<li class="notice" data-file="other.py.trace.json"><code>other.py.trace.json</code>' in resp.text
    assert 'data-output="out.py"' in resp.text
    assert 'data-line="1" data-template="" data-terms="https://example.invalid/a"' in resp.text


def test_generation_view_names_a_malformed_sidecar(client, tmp_path, monkeypatch):
    from viewer import app as viewer_app

    monkeypatch.setattr(viewer_app, "MODEL_DIR", _project(tmp_path, sidecar="{not json"))
    resp = client.get(_url("https://example.invalid/a"))
    assert resp.status_code == 200
    assert 'data-file="out.py.trace.json"' in resp.text
    assert "trace sidecar is malformed" in resp.text


# -- the inspector's Generated section (T03) -------------------------------------


def _view_url(iri: str) -> str:
    return f"/view/{quote(iri, safe='')}"


def _lands_on_itself(iri: str) -> bool:
    """GET /view/{iri} focuses ``iri`` itself: no detail views, no navigation target."""
    from viewer import app as viewer_app

    nav = viewer_app.resolve_navigation(iri)
    return not nav["candidates"] and (nav["target"] or iri) == iri


def _self_landing_api_iri() -> str:
    """A chat_api.py term that /view lands on itself (MEM012) and other outputs cite too."""

    index = generation.get_index(CHAT)
    terms = sorted({t for e in _api_sidecar()["lines"] for t in e["terms"]})
    landing = [t for t in terms if _lands_on_itself(t) and len({p for p, _ in index.citing(t)}) > 1]
    assert landing, "a chat_api.py term self-lands and is cited by more than one output"
    return landing[0]


def test_generated_rows_count_each_outputs_citing_lines():
    iri = _self_landing_api_iri()
    index = generation.get_index(CHAT)
    rows = generation.generated(index, iri, lambda out, n: f"{out}#{n}")
    citing = index.citing(iri)
    assert [r.output for r in rows] == sorted({p for p, _ in citing})
    for row in rows:
        own = [n for p, n in citing if p == row.output]
        assert row.lines == len(own)
        assert row.href == f"{row.output}#{own[0]}"
        assert row.generator == next(o.generator for o in index.outputs if o.path == row.output)


def test_generated_rows_are_empty_for_an_uncited_iri():
    rows = generation.generated(generation.get_index(CHAT), "https://example.invalid/never-traced", lambda o, n: "")
    assert rows == ()


@pytest.mark.parametrize("hx", [False, True])
def test_inspector_lists_the_outputs_citing_the_element(client, hx):
    iri = _self_landing_api_iri()
    rows = generation.generated(
        generation.get_index(CHAT), iri, lambda out, n: _url(iri, f"?output={quote(out, safe='')}&line={n}")
    )
    resp = client.get(_view_url(iri), headers={"hx-request": "true"} if hx else {})
    assert resp.status_code == 200
    body = resp.text
    assert f"<code>{iri}</code>" in body  # the element landed on itself
    assert 'id="generated"' in body
    assert f'<h4><a href="{escape(_url(iri))}">Generated</a></h4>' in body
    assert body.count('class="generated-row"') == len(rows)
    for row in rows:
        assert f'href="{escape(row.href)}" data-output="{row.output}" data-lines="{row.lines}"' in body


def test_inspector_link_opens_the_generation_view_on_that_output(client):
    iri = _self_landing_api_iri()
    row = generation.generated(
        generation.get_index(CHAT), iri, lambda out, n: _url(iri, f"?output={quote(out, safe='')}&line={n}")
    )[-1]
    resp = client.get(row.href)
    assert resp.status_code == 200
    assert f'data-output="{row.output}"' in resp.text


def test_inspector_omits_generated_when_no_line_cites_the_element(client, tmp_path, monkeypatch):
    from viewer import app as viewer_app

    iri = _self_landing_api_iri()
    monkeypatch.setattr(viewer_app, "MODEL_DIR", _project(tmp_path, sidecar=_sidecar([])))
    resp = client.get(_view_url(iri))
    assert resp.status_code == 200
    assert f"<code>{iri}</code>" in resp.text
    assert 'id="generated"' not in resp.text
    assert "generated-row" not in resp.text


# -- seams propose drafts in the generation view (M022/S05) ------------------------

CHAPTER_09 = ROOT / "examples" / "expenses" / "chapter-09"
DRAFT_TASK = "https://example.org/expenses/approval_bpmn#notify_manager"
DRAFT_PATH = "handlers/notify.py"


def _drafted(tmp_path: Path, monkeypatch, extra: object = None) -> Path:
    """A chapter 9 copy whose seams.lock records handlers/notify.py as a current draft, viewed by the viewer."""
    import hashlib
    import shutil

    import seams

    from viewer import app as viewer_app

    base = tmp_path / "chapter-09"
    shutil.copytree(CHAPTER_09, base, ignore=shutil.ignore_patterns("__pycache__"))
    model = seams.load(base / "expenses.trig")
    record = {
        "context_hash": seams.context_for(model, DRAFT_TASK).context_hash,
        "path": DRAFT_PATH,
        "provider": "fake",
        "sha256": hashlib.sha256((base / DRAFT_PATH).read_bytes()).hexdigest(),
        "task": DRAFT_TASK,
        "template": "handler.j2",
    }
    lock_file = base / "seams.lock"
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    lock["drafts"] = [record] + ([extra] if extra is not None else [])
    lock_file.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(viewer_app, "MODEL_DIR", base)
    monkeypatch.setattr(viewer_app, "_model", model)
    return base


def _draft_state(client) -> str:
    html = client.get(f"/generation/{quote(DRAFT_TASK, safe='')}").text
    assert 'id="generation-drafts"' in html
    assert f"<code>{DRAFT_PATH}</code>" in html and "fake · handler.j2" in html
    return html.split('data-state="', 1)[1].split('"', 1)[0]


def test_generation_view_shows_a_current_draft(client, tmp_path, monkeypatch):
    base = _drafted(tmp_path, monkeypatch)
    assert [d.task for d in generation.get_index(base).drafts] == [DRAFT_TASK]
    assert _draft_state(client) == "current"


def test_generation_view_shows_an_edited_draft_as_hand_edited(client, tmp_path, monkeypatch):
    base = _drafted(tmp_path, monkeypatch)
    (base / DRAFT_PATH).write_text("# edited\n", encoding="utf-8")
    assert _draft_state(client) == "hand-edited"


def test_generation_view_shows_a_draft_whose_context_changed_as_stale(client, tmp_path, monkeypatch):
    import seams

    from viewer import app as viewer_app

    base = _drafted(tmp_path, monkeypatch)
    trig = base / "expenses.trig"
    trig.write_text(
        trig.read_text(encoding="utf-8").replace('rdfs:label "Notification"', 'rdfs:label "Notice"'), encoding="utf-8"
    )
    monkeypatch.setattr(viewer_app, "_model", seams.load(trig))
    assert _draft_state(client) == "stale"


def test_a_malformed_draft_is_a_notice_and_never_raises(client, tmp_path, monkeypatch):
    base = _drafted(tmp_path, monkeypatch, extra={"task": 7})
    index = generation.get_index(base)
    assert [d.task for d in index.drafts] == [DRAFT_TASK]
    assert [(n.file, n.message.startswith("`drafts[1]`")) for n in index.notices] == [("seams.lock", True)]
    assert _draft_state(client) == "current"
