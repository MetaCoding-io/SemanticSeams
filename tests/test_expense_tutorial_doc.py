"""The expense tutorial pages show the checkpoints CI checks (M009/S03).

docs/tutorials/expenses/NN-*.md walks the reader through chapter NN. Every
```trig block on a page is a verbatim excerpt of that chapter's checkpoint,
examples/expenses/chapter-NN/expenses.trig (compared line by line with
surrounding whitespace stripped and blank lines ignored), every ```xml block
is likewise an excerpt of one of the chapter's BPMN or DMN payload files, and
the page links the checkpoint. The pages are chapters 1, 2, 3... with no gap. Chapter 3 and
every process chapter (4 onward) show the generator commands
tests/expense_app.py names for them, and the host command with the
environment the app tests set. Chapter 2 shows the deliberate mistake
tests/test_expense_checkpoints.py replays, and chapters 5 and 6 show the
edits their app tests make on a copy of the checkpoint. Chapter 8 shows the
docker compose command tests/test_expense_e2e.py runs, the compose generator
command, and the complexity command with the report the checkpoint produces.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from expense_app import commands, host_command  # noqa: E402
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
    return [
        body for info, body in FENCE.findall(page.read_text(encoding="utf-8")) if lang is None or info.strip() == lang
    ]


def normalised(text: str) -> list[str]:
    return [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]


def contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def code_lines(page: Path) -> set[str]:
    return {ln.strip() for body in blocks(page) for ln in body.splitlines() if ln.strip()}


PROCESS_PAGES = [p for p in PAGES if int(p.name[:2]) >= 4]


def test_pages_are_contiguous_chapters_from_1():
    assert len(PAGES) >= 4, PAGE_IDS
    assert [chapter_of(p) for p in PAGES] == [f"chapter-{n:02d}" for n in range(1, len(PAGES) + 1)]
    assert (PAGES_DIR / "index.md").is_file()
    for page in PAGES:
        assert (EXPENSES / chapter_of(page) / "expenses.trig").is_file(), page.name


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_every_trig_block_is_an_excerpt_of_the_checkpoint(page):
    checkpoint = normalised((EXPENSES / chapter_of(page) / "expenses.trig").read_text(encoding="utf-8"))
    trig_blocks = blocks(page, "trig")
    assert trig_blocks, f"{page.name} shows no ```trig block"
    missing = [body for body in trig_blocks if not contains_run(checkpoint, normalised(body))]
    assert not missing, (
        f"{page.name}: these ```trig blocks are not verbatim in "
        f"examples/expenses/{chapter_of(page)}/expenses.trig:\n" + "\n---\n".join(missing)
    )


XML_PAGES = [p for p in PAGES if blocks(p, "xml")]


def test_bpmn_and_dmn_chapters_show_xml():
    assert {"04-process", "05-rules"} <= {p.stem for p in XML_PAGES}, [p.stem for p in XML_PAGES]


@pytest.mark.parametrize("page", XML_PAGES, ids=[p.stem for p in XML_PAGES])
def test_every_xml_block_is_an_excerpt_of_a_payload(page):
    directory = EXPENSES / chapter_of(page)
    payloads = [
        normalised(f.read_text(encoding="utf-8")) for f in sorted([*directory.glob("*.bpmn"), *directory.glob("*.dmn")])
    ]
    missing = [
        body for body in blocks(page, "xml") if not any(contains_run(payload, normalised(body)) for payload in payloads)
    ]
    assert not missing, (
        f"{page.name}: these ```xml blocks are not verbatim in a .bpmn or .dmn "
        f"file of examples/expenses/{chapter_of(page)}/:\n" + "\n---\n".join(missing)
    )


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


@pytest.mark.parametrize("page", PROCESS_PAGES, ids=[p.stem for p in PROCESS_PAGES])
def test_process_chapter_shows_its_generator_and_host_commands(page):
    chapter = chapter_of(page)
    missing = [c for c in commands(chapter).values() if c not in code_lines(page)]
    assert not missing, f"{page.name} lacks the generator commands: {missing}"
    text = "\n".join(blocks(page, "sh"))
    missing = [fragment for fragment in host_command(chapter) if fragment not in text]
    assert not missing, f"{page.name} lacks the host command fragments: {missing}"


def test_chapter_2_shows_the_mistake_as_a_diff():
    page = PAGES_DIR / "02-data.md"
    diffs = blocks(page, "diff")
    assert any(f"-    {CHAPTER_2_MISTAKE_TEXT}" in body for body in diffs), (
        "02-data.md must show deleting the mistake's triple in a ```diff block"
    )
    assert CHAPTER_2_MISTAKE_TEXT in page.read_text(encoding="utf-8")


def test_chapter_5_threshold_diff_is_the_edit_ci_makes():
    from test_expense_process_app import MANAGER_UP_TO_200, MANAGER_UP_TO_1000

    [diff] = blocks(PAGES_DIR / "05-rules.md", "diff")
    removed = [ln[1:] for ln in diff.splitlines() if ln.startswith("-")]
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+")]
    assert len(removed) == len(added) == 1, diff
    dmn = (EXPENSES / "chapter-05" / "approval.dmn").read_text(encoding="utf-8").splitlines()
    assert removed[0] in dmn and MANAGER_UP_TO_1000 in removed[0]
    assert added[0] == removed[0].replace(MANAGER_UP_TO_1000, MANAGER_UP_TO_200)


def test_chapter_6_refusal_diff_is_the_edit_ci_makes():
    from test_expense_lifecycle import FIRES_APPROVE, FIRES_PAY

    [diff] = blocks(PAGES_DIR / "06-lifecycle.md", "diff")
    removed = [ln[1:].strip() for ln in diff.splitlines() if ln.startswith("-")]
    added = [ln[1:].strip() for ln in diff.splitlines() if ln.startswith("+")]
    assert (removed, added) == ([FIRES_APPROVE], [FIRES_PAY]), diff


def test_chapter_8_shows_the_compose_and_complexity_commands():
    """Chapter 8 runs the stack with the two files tests/test_expense_e2e.py
    merges, regenerates compose.yaml as tests/test_expense_compose.py expects,
    and measures the checkpoint tests/test_complexity.py pins."""
    page = PAGES_DIR / "08-growing-up.md"
    app = "examples/expenses/chapter-08"
    lines = code_lines(page)
    assert f"docker compose -f {app}/compose.yaml -f {app}/compose.override.yaml up --build" in lines
    assert f"python -m seams_gen compose {app}/expenses.trig --out {app}" in lines
    assert f"python -m seams_gen.complexity {app}/expenses.trig" in lines
    # the report shown is the one the checkpoint produces now
    from seams_gen.complexity import load_model, measure, report

    shown = report(measure(load_model(ROOT / app / "expenses.trig")))
    assert shown in [body for info, body in FENCE.findall(page.read_text(encoding="utf-8")) if not info.strip()], (
        f"08-growing-up.md must show the report:\n{shown}"
    )
