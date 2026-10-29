"""The expense tutorial pages show the checkpoints CI checks (M009/S03).

docs/tutorials/expenses/NN-*.md walks the reader through chapter NN. Every
```trig block on a page is a verbatim excerpt of that chapter's checkpoint,
examples/expenses/chapter-NN/expenses.trig (compared line by line with
surrounding whitespace stripped and blank lines ignored), and the page links
the checkpoint. Chapter 3 shows the generator commands
tests/test_expense_chapter3_app.py runs, and the host command with the
environment its app fixture sets. Chapter 2 shows the deliberate mistake
tests/test_expense_checkpoints.py replays.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_expense_chapter3_app import COMMANDS  # noqa: E402
from test_expense_checkpoints import CHAPTER_2_MISTAKE_TEXT  # noqa: E402

PAGES_DIR = ROOT / "docs" / "tutorials" / "expenses"
EXPENSES = ROOT / "examples" / "expenses"
PAGES = sorted(PAGES_DIR.glob("[0-9][0-9]-*.md"))
PAGE_IDS = [p.stem for p in PAGES]
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```", re.S | re.M)


def chapter_of(page: Path) -> str:
    return f"chapter-{page.name[:2]}"


def blocks(page: Path, lang: str | None = None) -> list[str]:
    return [body for info, body in FENCE.findall(page.read_text(encoding="utf-8"))
            if lang is None or info.strip() == lang]


def normalised(text: str) -> list[str]:
    return [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]


def contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def code_lines(page: Path) -> set[str]:
    return {ln.strip() for body in blocks(page) for ln in body.splitlines() if ln.strip()}


def test_pages_cover_chapters_1_to_3():
    assert [chapter_of(p) for p in PAGES] == ["chapter-01", "chapter-02", "chapter-03"]
    assert (PAGES_DIR / "index.md").is_file()
    for page in PAGES:
        assert (EXPENSES / chapter_of(page) / "expenses.trig").is_file(), page.name


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_every_trig_block_is_an_excerpt_of_the_checkpoint(page):
    checkpoint = normalised((EXPENSES / chapter_of(page) / "expenses.trig").read_text(encoding="utf-8"))
    trig_blocks = blocks(page, "trig")
    assert trig_blocks, f"{page.name} shows no ```trig block"
    missing = [body for body in trig_blocks if not contains_run(checkpoint, normalised(body))]
    assert not missing, (f"{page.name}: these ```trig blocks are not verbatim in "
                         f"examples/expenses/{chapter_of(page)}/expenses.trig:\n" + "\n---\n".join(missing))


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_links_its_checkpoint(page):
    target = f"examples/expenses/{chapter_of(page)}/expenses.trig"
    links = re.findall(r"\]\(([^)\s]+)\)", page.read_text(encoding="utf-8"))
    resolved = {(page.parent / link.split("#")[0]).resolve() for link in links if not re.match(r"[a-z]+:|/", link)}
    assert (ROOT / target).resolve() in resolved, f"{page.name} does not link {target}"


def test_chapter_3_shows_the_generator_commands_the_app_test_runs():
    page = PAGES_DIR / "03-screens.md"
    missing = [c for c in COMMANDS.values() if c not in code_lines(page)]
    assert not missing, f"03-screens.md lacks the generator commands: {missing}"


def test_chapter_3_runs_the_host_as_the_app_test_does():
    text = "\n".join(blocks(PAGES_DIR / "03-screens.md", "sh"))
    assert "SEAMS_MODEL=examples/expenses/chapter-03/expenses.trig" in text
    assert "SEAMS_TEMPLATES=examples/expenses/chapter-03/generated/templates" in text
    assert "SEAMS_DB=" in text
    assert "python -m seams_runtime.host --routes examples/expenses/chapter-03/generated/expense_api.py" in text


def test_chapter_2_shows_the_mistake_as_a_diff():
    page = PAGES_DIR / "02-data.md"
    diffs = blocks(page, "diff")
    assert any(f"-    {CHAPTER_2_MISTAKE_TEXT}" in body for body in diffs), \
        "02-data.md must show deleting the mistake's triple in a ```diff block"
    assert CHAPTER_2_MISTAKE_TEXT in page.read_text(encoding="utf-8")
