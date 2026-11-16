"""The LikeC4 export (M033/S01, backlog X9, ADR-0044).

The goldens are the chat app's and expense chapter 11's models. Regenerate
them deliberately with ``uv run python tests/test_likec4_export.py``. A copy
of the chat app with more containers shows the gaps, and the identifier
collision is the shared extract's fault, raised before LikeC4 renders.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDF

from seams_gen import GeneratorError
from seams_gen.builtin import likec4
from seams_gen.c4 import extract_c4
from seams_gen.likec4 import FILE, render_likec4
from seams_gen.sources import SOURCES
from seams_gen.testing import assert_deterministic

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples" / "chat-app" / "chat-app.trig",
    "chapter-11": ROOT / "examples" / "expenses" / "chapter-11",
}
GOLDEN = ROOT / "tests" / "golden" / "likec4"
CHAT = "https://example.org/chat/"
OTHER = "https://example.org/other/"


def _model(model: Path) -> str:
    return render_likec4(extract_c4(seams.load(model)))[FILE]


def _chat_copy(tmp_path: Path, extra: str) -> Path:
    """A copy of the chat app with ``extra`` added to its architecture graph."""
    app = Path(shutil.copytree(MODELS["chat-app"].parent, tmp_path / "chat-app"))
    trig = app / "chat-app.trig"
    block = f"\n<urn:seams:graph:model:chat_architecture> {{\n{extra}\n}}\n"
    trig.write_text(trig.read_text(encoding="utf-8") + block, encoding="utf-8")
    return trig


@pytest.mark.parametrize("name", list(MODELS))
def test_model_matches_the_golden(name):
    assert _model(MODELS[name]) == (GOLDEN / f"{name}.c4").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", list(MODELS))
def test_generate_is_deterministic(name):
    assert_deterministic(likec4, MODELS[name])


@pytest.mark.parametrize("name", list(MODELS))
def test_registered_generator_writes_the_model(name):
    model = MODELS[name]
    files = likec4.generate(model, model.parent)
    assert files == {FILE: _model(model)}
    sources = SOURCES["likec4"](model, model.parent)
    assert sources.keys() == files.keys()
    assert sources[FILE] == SOURCES["structurizr"](model, model.parent)["workspace.dsl"]


def test_sections_and_nesting():
    text = _model(MODELS["chat-app"])
    for section in ("specification {\n", "model {\n", "views {\n"):
        assert section in text
    assert "  element person\n  element system\n  element container\n  tag external\n" in text
    assert "  chat_system = system '" in text
    assert "    chat_api = container '" in text
    assert "  authenticated_user -> chat_system.chat_ui 'send_message'\n" in text
    assert "  chat_system.chat_api -> chat_system.message_db 'depends on'\n" in text
    assert "  view index {\n    include *\n  }\n" in text
    assert "  view chat_system_view of chat_system {\n" in text


def test_chapter_11_external_system_is_tagged():
    text = _model(MODELS["chapter-11"])
    assert "  sempkm = system 'SemPKM' {\n    #external\n" in text
    assert "      technology 'FastAPI'\n" in text
    assert "  chat_system" not in text
    assert "// gap:" not in text


def test_every_gap_is_a_comment_line(tmp_path):
    trig = _chat_copy(
        tmp_path,
        f'    <{OTHER}orphan> a arch:Container ; rdfs:label "Orphan" .\n'
        f"    <{OTHER}bare> a arch:Container ; rdfs:label \"Bare 'quoted'\" .\n"
        f"    <{CHAT}chat_system> arch:contains <{OTHER}bare> .",
    )
    c4 = extract_c4(seams.load(trig))
    text = render_likec4(c4)[FILE]
    assert c4.gaps
    for gap in c4.gaps:
        assert f"// gap: {gap}\n" in text
    assert "orphan" not in text.split("model {", 1)[1]
    assert "    bare = container 'Bare \\'quoted\\''\n" in text  # no technology, no body


def test_colliding_identifiers_raise_before_render(tmp_path):
    trig = _chat_copy(
        tmp_path,
        f'    <{OTHER}chat_api> a arch:Container ; rdfs:label "Other API" ; arch:technology "x" .\n'
        f"    <{CHAT}chat_system> arch:contains <{OTHER}chat_api> .",
    )
    with pytest.raises(GeneratorError) as err:
        likec4.generate(trig, trig.parent)
    assert err.value.subject == OTHER + "chat_api"
    assert err.value.predicate == str(RDF.type)


if __name__ == "__main__":  # regenerate the goldens, deliberately
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        (GOLDEN / f"{name}.c4").write_text(_model(model), encoding="utf-8")
    sys.exit(0)
