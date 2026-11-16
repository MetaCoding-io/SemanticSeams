"""The Structurizr DSL export (M033/S01, backlog X9, ADR-0044).

The goldens are the chat app's and expense chapter 11's workspaces. Regenerate
them deliberately with ``uv run python tests/test_structurizr_export.py``. A
copy of the chat app with one more container shows the gaps and the
identifier-collision fault.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDF, URIRef

from seams_gen import GeneratorError
from seams_gen.builtin import structurizr
from seams_gen.c4 import extract_c4, identifier
from seams_gen.sources import SOURCES
from seams_gen.structurizr import FILE, render_structurizr
from seams_gen.testing import assert_deterministic

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples" / "chat-app" / "chat-app.trig",
    "chapter-11": ROOT / "examples" / "expenses" / "chapter-11",
}
GOLDEN = ROOT / "tests" / "golden" / "structurizr"
CHAT = "https://example.org/chat/"
OTHER = "https://example.org/other/"


def _workspace(model: Path) -> str:
    return render_structurizr(extract_c4(seams.load(model)))[FILE]


def _chat_copy(tmp_path: Path, extra: str) -> Path:
    """A copy of the chat app with ``extra`` added to its architecture graph."""
    app = Path(shutil.copytree(MODELS["chat-app"].parent, tmp_path / "chat-app"))
    trig = app / "chat-app.trig"
    block = f"\n<urn:seams:graph:model:chat_architecture> {{\n{extra}\n}}\n"
    trig.write_text(trig.read_text(encoding="utf-8") + block, encoding="utf-8")
    return trig


@pytest.mark.parametrize("name", list(MODELS))
def test_workspace_matches_the_golden(name):
    assert _workspace(MODELS[name]) == (GOLDEN / f"{name}.dsl").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", list(MODELS))
def test_generate_is_deterministic(name):
    assert_deterministic(structurizr, MODELS[name])


@pytest.mark.parametrize("name", list(MODELS))
def test_registered_generator_writes_the_workspace(name):
    model = MODELS[name]
    files = structurizr.generate(model, model.parent)
    assert files == {FILE: _workspace(model)}
    assert SOURCES["structurizr"](model, model.parent).keys() == files.keys()


def test_chat_app_facts():
    c4 = extract_c4(seams.load(MODELS["chat-app"]))
    assert [p.identifier for p in c4.people] == ["authenticated_user"]
    (system,) = c4.systems
    assert not system.external
    assert [c.identifier for c in system.containers] == ["chat_api", "chat_ui", "llm_gateway", "message_db"]
    pairs = {(r.source_id, r.destination_id): r.label for r in c4.relationships}
    assert pairs[("authenticated_user", "chat_ui")] == "send_message"
    assert pairs[("chat_api", "message_db")] == "depends on"
    assert "send_message_op" in pairs[("chat_ui", "chat_api")]
    assert any(g.startswith("select_conversation has no seam:governedBy policy") for g in c4.gaps)
    assert CHAT + "user_send_policy" in c4.sources


def test_chapter_11_external_system_has_tags_and_no_context_view():
    text = _workspace(MODELS["chapter-11"])
    c4 = extract_c4(seams.load(MODELS["chapter-11"]))
    assert [(s.identifier, s.external) for s in c4.systems] == [("expense_system", False), ("sempkm", True)]
    assert 'tags "External"' in text
    assert "systemContext sempkm" not in text
    assert 'container sempkm "sempkm-containers"' in text
    assert c4.gaps == ()


def test_every_gap_is_a_comment_line(tmp_path):
    trig = _chat_copy(
        tmp_path,
        f'    <{OTHER}orphan> a arch:Container ; rdfs:label "Orphan" .\n'
        f'    <{OTHER}bare> a arch:Container ; rdfs:label "Bare" .\n'
        f"    <{CHAT}chat_system> arch:contains <{OTHER}bare> .",
    )
    c4 = extract_c4(seams.load(trig))
    assert "container orphan is arch:contains'ed by no arch:System, so it is left out" in c4.gaps
    assert "container bare has no arch:technology" in c4.gaps
    assert "orphan" not in [c.identifier for c in c4.containers]
    text = render_structurizr(c4)[FILE]
    for gap in c4.gaps:
        assert f"# gap: {gap}\n" in text
    assert 'bare = container "Bare"\n' in text


def test_colliding_identifiers_raise(tmp_path):
    trig = _chat_copy(
        tmp_path,
        f'    <{OTHER}chat_api> a arch:Container ; rdfs:label "Other API" ; arch:technology "x" .\n'
        f"    <{CHAT}chat_system> arch:contains <{OTHER}chat_api> .",
    )
    with pytest.raises(GeneratorError) as err:
        extract_c4(seams.load(trig))
    assert err.value.subject == OTHER + "chat_api"
    assert err.value.predicate == str(RDF.type)
    assert 'both have the C4 identifier "chat_api"' in str(err.value)


@pytest.mark.parametrize(
    ("iri", "expected"), [(CHAT + "chat_api", "chat_api"), (CHAT + "a-b.c", "a_b_c"), (CHAT + "9lives", "_9lives")]
)
def test_identifier(iri, expected):
    assert identifier(URIRef(iri)) == expected


if __name__ == "__main__":  # regenerate the goldens, deliberately
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        (GOLDEN / f"{name}.dsl").write_text(_workspace(model), encoding="utf-8")
    sys.exit(0)
