"""ADR-0017 (M019/S01): the write path is decided before it is built. The ADR answers
the three questions principle 10 leaves to it: comments survive because a patch edits
the source TriG text (the T01 spike is the evidence), the write path is a new
`seams_edit` package outside the read-only `seams` library, and editing is a viewer
mode that is off by default. It is linked from the ADR index and the decisions nav, and
backlog I1 cites it."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0017-write-path-and-editor.md"


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^### {re.escape(heading)}.*?$(.*?)(?=^##)", text, re.MULTILINE | re.DOTALL)
    assert match, heading
    return match.group(1)


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


@pytest.mark.parametrize(
    "heading",
    [
        "Comments: a patch-based text writer over the source TriG",
        "Where the write path lives: a new `seams_edit` package outside `packages/seams`",
        "Where the editor lives: an edit mode of the viewer, off by default",
    ],
)
def test_adr_has_decision_heading(text: str, heading: str) -> None:
    assert f"\n### {heading}\n" in text


def test_comments_decision_cites_the_spike(text: str) -> None:
    section = _section(text, "Comments")
    assert "byte for byte" in section
    assert "tests/test_adr0017_spike.py" in text


def test_spike_the_adr_cites_exists() -> None:
    assert (ROOT / "tests" / "test_adr0017_spike.py").is_file()


def test_write_path_stays_out_of_the_seams_library(text: str) -> None:
    section = _section(text, "Where the write path lives")
    assert "`packages/seams` stays read-only" in section
    assert "public names" in section


def test_editor_is_off_by_default(text: str) -> None:
    section = _section(text, "Where the editor lives")
    assert "starts read-only" in section
    assert "`seams_edit`" in section


@pytest.mark.parametrize("rejected", ["rdfs:comment", "canonical, sorted serialisation", "separate editor app"])
def test_adr_records_rejected_alternative(text: str, rejected: str) -> None:
    alternatives = text.split("## Alternatives Considered", 1)[1].split("## Consequences", 1)[0]
    entry = next(item for item in alternatives.split("\n- ") if rejected in item)
    assert "Rejected" in entry


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0017", "Write path and editor", "0017-write-path-and-editor"]' in config


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    row = next(line for line in index.splitlines() if line.startswith("| [ADR-0017]"))
    assert "0017-write-path-and-editor" in row
    assert row.endswith("| Accepted |")


def test_backlog_i1_cites_adr() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| I1 |"))
    assert "ADR-0017" in row
    assert "ADR accepted (M019/S01)" in row
    assert "writer done (M019/S02)" in row
