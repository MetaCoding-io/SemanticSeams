"""The PlantUML export of the derived sequence and storm views (M033/S01, backlog X9, ADR-0044).

The goldens are every file the generator writes for the chat app and expense
chapter 11. Regenerate them deliberately with
``uv run python tests/test_plantuml_export.py``. The export only prints what
``seams_gen.sequence.derive`` and ``seams_gen.storm.derive`` return, so the
tests also compare it with them line by line.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDF

from seams_gen import GeneratorError, sequence, storm
from seams_gen.builtin import plantuml
from seams_gen.plantuml import extract_plantuml, render_plantuml, sequence_text, storm_text
from seams_gen.sources import SOURCES
from seams_gen.testing import assert_deterministic

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples" / "chat-app" / "chat-app.trig",
    "chapter-11": ROOT / "examples" / "expenses" / "chapter-11",
}
GOLDEN = ROOT / "tests" / "golden" / "plantuml"
CHAT = "https://example.org/chat/"
OTHER = "https://example.org/other/"


def _files(model: Path) -> dict[str, str]:
    return render_plantuml(extract_plantuml(seams.load(model)))


def _golden(name: str) -> dict[str, str]:
    root = GOLDEN / name
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.puml"))}


@pytest.mark.parametrize("name", list(MODELS))
def test_files_match_the_goldens(name):
    assert _files(MODELS[name]) == _golden(name)


def test_goldens_hold_the_planned_diagrams():
    assert set(_golden("chat-app")) == {"sequence/send_message.puml", "storm/send_message_process.puml"}
    chapter = set(_golden("chapter-11"))
    assert "storm/approval_process.puml" in chapter
    assert "sequence/submit_expense--manager--approved.puml" in chapter


@pytest.mark.parametrize("name", list(MODELS))
def test_generate_is_deterministic(name):
    assert_deterministic(plantuml, MODELS[name])


@pytest.mark.parametrize("name", list(MODELS))
def test_every_file_is_one_startuml_block(name):
    for file, text in _files(MODELS[name]).items():
        lines = text.splitlines()
        assert lines[0] == "@startuml", file
        assert lines[-1] == "@enduml", file
        assert text.endswith("@enduml\n"), file
        assert text.count("@startuml") == text.count("@enduml") == 1, file


@pytest.mark.parametrize("name", list(MODELS))
def test_registered_generator_and_sources(name):
    model = MODELS[name]
    files = plantuml.generate(model, model.parent)
    assert files == _files(model)
    sources = SOURCES["plantuml"](model, model.parent)
    assert sources.keys() == files.keys()
    assert all(iris and list(iris) == sorted(set(iris)) for iris in sources.values())


def test_one_file_per_sequence_path_and_per_process():
    m = seams.load(MODELS["chapter-11"])
    files = _files(MODELS["chapter-11"])
    diagrams = sequence.derive(m, ":submit_expense")
    assert {f for f in files if f.startswith("sequence/")} == {
        f"sequence/{sequence.file_name(d).removesuffix('.mmd')}.puml" for d in diagrams
    }
    assert {f for f in files if f.startswith("storm/")} == {
        "storm/approval_process.puml",
        "storm/payout_process.puml",
        "storm/vendor_review_process.puml",
    }


def test_sequence_prints_the_derived_messages_in_order():
    m = seams.load(MODELS["chat-app"])
    (diagram,) = sequence.derive(m, ":send_message")
    text = sequence_text(diagram)
    assert 'actor "Authenticated users" as authenticated_user\n' in text
    assert 'participant "Chat API" as chat_api\n' in text
    body = [line for line in text.splitlines() if " : " in line]
    assert len(body) == len(diagram.messages)
    for line, message in zip(body, diagram.messages, strict=True):
        arrow = {"call": "->", "reply": "-->"}.get(message.kind)
        expected = (
            f"note over {message.sender} : {message.text}"
            if arrow is None
            else f"{message.sender} {arrow} {message.receiver} : {message.text}"
        )
        assert line == expected
    assert "chat_ui -> chat_api : POST send_message_op [MessageShape]\n" in text
    assert "chat_api --> chat_ui : message_thread fragment\n" in text
    assert "note over chat_api : start send_message_process\n" in text
    assert "->>" not in text and "Note over" not in text and "%%" not in text


def test_storm_prints_each_step_and_read_model():
    m = seams.load(MODELS["chapter-11"])
    derived = storm.derive(m, "approval_process")
    text = storm_text(derived)
    for step in derived.steps:
        assert f":{step.index}. {step.name} (" in text
    for entry in derived.read_models:
        assert f"  - {entry.text.replace('`', '')}\n" in text
    assert "`" not in text.split("' derived from", 1)[1].split("\n", 1)[1]
    assert text.index("start\n") < text.index("stop\n") < text.index("legend right\n")


def test_gaps_are_comment_lines():
    files = _files(MODELS["chapter-11"])
    m = seams.load(MODELS["chapter-11"])
    derived = storm.derive(m, "approval_process")
    assert derived.gaps
    for gap in derived.gaps:
        assert f"' gap: {gap}\n" in files["storm/approval_process.puml"]
    for d in sequence.derive(m, ":submit_expense"):
        text = files[f"sequence/{d.name}.puml"]
        assert [line.removeprefix("' gap: ") for line in text.splitlines() if line.startswith("' gap: ")] == list(
            d.gaps
        )


def test_storm_with_no_step_still_has_start_and_stop():
    m = seams.load(MODELS["chat-app"])
    derived = storm.derive(m, "send_message_process")
    empty = type(derived)(derived.process, derived.label, (), (), (), (), (), (), (), (), (), ("a gap",))
    text = storm_text(empty)
    assert "start\n' No step of the process has a fact to show.\nstop\n" in text
    assert "legend" not in text and "' gap: a gap\n" in text


def test_label_quotes_do_not_break_participant_names(tmp_path):
    app = Path(shutil.copytree(MODELS["chat-app"].parent, tmp_path / "chat-app"))
    trig = app / "chat-app.trig"
    text = trig.read_text(encoding="utf-8").replace('"Chat API"', '"Chat \\"API\\""', 1)
    trig.write_text(text, encoding="utf-8")
    files = _files(trig)
    assert "participant \"Chat 'API'\" as chat_api\n" in files["sequence/send_message.puml"]


def test_two_processes_with_one_local_name_raise(tmp_path):
    app = Path(shutil.copytree(MODELS["chat-app"].parent, tmp_path / "chat-app"))
    trig = app / "chat-app.trig"
    source = trig.read_text(encoding="utf-8")
    other = f'    <{OTHER}send_message_process> a proc:Process ; rdfs:label "Other" ; seam:inModel :chat_bpmn .'
    block = f"\n<urn:seams:graph:model:chat_bpmn> {{\n{other}\n}}\n"
    trig.write_text(source + block, encoding="utf-8")
    with pytest.raises(GeneratorError) as err:
        plantuml.generate(trig, trig.parent)
    assert err.value.subject == OTHER + "send_message_process"
    assert err.value.predicate == str(RDF.type)
    assert "storm/send_message_process.puml" in err.value.detail


if __name__ == "__main__":  # regenerate the goldens, deliberately
    for name, model in MODELS.items():
        root = GOLDEN / name
        if root.exists():
            shutil.rmtree(root)
        for file, text in _files(model).items():
            path = root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    sys.exit(0)
