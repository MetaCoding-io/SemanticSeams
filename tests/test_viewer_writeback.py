"""Write-back from output (backlog T4, M021/S01): viewer.writeback.

Each test copies the chat app, and the compose files it generates at the
repository root, into tmp_path with the same layout, then edits one line of a
committed output. Line numbers are found by searching the output text; the
facts asserted are read from the copied model.
"""

import shutil
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDFS, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import generation, writeback  # noqa: E402

CHAT = ROOT / "examples" / "chat-app"
PAGE = "generated/templates/chat_page.html"
LIST = "generated/templates/conversation_list.html"
IFML_TITLE = URIRef("https://w3id.org/seams/ifml#title")


@pytest.fixture(autouse=True)
def clear_cache():
    generation._clear_cache()
    yield
    generation._clear_cache()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The chat app at tmp_path/examples/chat-app, its compose files at tmp_path."""
    copy = tmp_path / "examples" / "chat-app"
    shutil.copytree(CHAT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    for compose in sorted(ROOT.glob("compose.*.yaml*")):
        shutil.copyfile(compose, tmp_path / compose.name)
    return copy


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _line(project: Path, output: str, needle: str) -> tuple[int, str]:
    lines = (project / output).read_text(encoding="utf-8").splitlines()
    found = [(n, t) for n, t in enumerate(lines, start=1) if needle in t]
    assert len(found) == 1, f"{needle!r} is on {len(found)} lines of {output}"
    return found[0]


def _write_back(project: Path, output: str, line: int, text: str) -> writeback.WriteBack:
    model = seams.load(project / "chat-app.trig")
    return writeback.write_back(
        generation.get_index(project), model.ds, project, project / "chat-app.trig", output, line, text
    )


def test_a_title_edit_is_one_triple_and_regenerates_to_the_edit(project: Path):
    line, text = _line(project, PAGE, "<title>")
    model = seams.load(project / "chat-app.trig")
    page, title = next((s, o) for s, o in model.ds.subject_objects(IFML_TITLE) if f">{o}<" in text)
    assert isinstance(title, Literal)
    edited = text.replace(f">{title}<", ">Inbox<")

    result = _write_back(project, PAGE, line, edited)

    assert (result.subject, result.predicate) == (str(page), str(IFML_TITLE))
    assert result.old == title
    assert result.new == Literal("Inbox", lang=title.language)
    assert len(result.patch.removes) == 1 and len(result.patch.adds) == 1
    (removed,) = result.patch.removes
    (added,) = result.patch.adds
    assert removed == (page, IFML_TITLE, title, URIRef(result.graph))
    assert added == (page, IFML_TITLE, Literal("Inbox", lang=title.language), URIRef(result.graph))
    assert result.files == ("chat-app.trig",)
    assert (result.before, result.after) == (text, edited)
    assert result.effects == ()  # the title is written on this line only; hash lines are no effect


def test_effects_list_every_other_output_line_the_patch_changes(project: Path):
    line, text = _line(project, PAGE, 'aria-label="Conversations"')
    edited = text.replace('"Conversations"', '"Conversations list"')

    result = _write_back(project, PAGE, line, edited)

    assert result.predicate == str(RDFS.label)
    list_line, list_text = _line(project, LIST, 'aria-label="Conversations"')
    assert result.effects == (writeback.Effect(LIST, list_line, list_text, edited),)


def test_check_never_writes_the_real_files(project: Path, tmp_path: Path):
    before = _snapshot(tmp_path)
    line, text = _line(project, PAGE, "<title>")
    _write_back(project, PAGE, line, text.replace("</title>", " now</title>"))
    with pytest.raises(writeback.Refusal):
        _write_back(project, PAGE, line, text.replace("</title>", " &amp; more</title>"))
    assert _snapshot(tmp_path) == before


def test_a_span_two_literals_cover_is_refused_listing_both(project: Path):
    line, text = _line(project, PAGE, '<button type="submit">')
    label = text.split(">")[1].split("<")[0]
    with pytest.raises(writeback.Refusal) as err:
        _write_back(project, PAGE, line, text.replace(label, label + "!"))
    assert err.value.subject == f"{PAGE}:{line}"
    model = seams.load(project / "chat-app.trig")
    owners = sorted(str(s) for s in model.ds.subjects(RDFS.label, Literal(label)))
    assert len(owners) >= 2
    for owner in owners:
        assert f"<{owner}>" in err.value.detail
    assert err.value.detail.index(f"<{owners[0]}>") < err.value.detail.index(f"<{owners[1]}>")  # sorted


def test_an_edit_no_literal_covers_is_refused(project: Path):
    line, text = _line(project, PAGE, "<title>")
    with pytest.raises(writeback.Refusal) as err:
        _write_back(project, PAGE, line, text.replace("<title>", "<title lang>"))
    assert err.value.subject == f"{PAGE}:{line}"
    assert "no literal" in err.value.detail


@pytest.mark.parametrize(
    ("line", "text", "detail"),
    [
        (0, "x", "lines"),
        (1, "a\nb", "line break"),
    ],
)
def test_malformed_edits_are_refused(project: Path, line: int, text: str, detail: str):
    with pytest.raises(writeback.Refusal) as err:
        _write_back(project, PAGE, line, text)
    assert detail in err.value.detail


def test_an_unchanged_line_and_an_unknown_output_are_refused(project: Path):
    line, text = _line(project, PAGE, "<title>")
    with pytest.raises(writeback.Refusal, match="same"):
        _write_back(project, PAGE, line, text)
    with pytest.raises(writeback.Refusal, match="no readable output"):
        _write_back(project, "generated/none.html", 1, "x")


def test_a_regeneration_that_differs_from_the_edit_is_refused(project: Path):
    """The template escapes the title, so a raw ``&`` comes back as ``&amp;``."""
    line, text = _line(project, PAGE, "<title>")
    with pytest.raises(writeback.Refusal) as err:
        _write_back(project, PAGE, line, text.replace("</title>", " & more</title>"))
    assert err.value.predicate == str(IFML_TITLE)
    assert f"{PAGE} line {line}" in err.value.detail
    assert "&amp;" in err.value.detail
