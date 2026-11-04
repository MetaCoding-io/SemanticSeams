"""ADR-0029 (M025/S02): LLM-drafted generators are decided before the code.
The ADR names the command, reuses ADR-0020's provider command, fixes the versioned
prompt, the JSON answer's keys, the three acceptance checks and the cache directory,
and keeps the provider out of CI."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0029-llm-drafted-generators.md"


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize(
    "heading",
    [
        "The command",
        "The provider is ADR-0020's command",
        "The prompt is deterministic and versioned",
        "The answer is one JSON object",
        "Acceptance",
        "The cache",
        "Write nothing on failure",
        "Accept once, then own",
        "Never in CI",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


def test_adr_names_the_command(text: str) -> None:
    command = _section(text, "### 1. The command")
    assert "seams draft-generator NAME --reference FILE [--provider CMD] [--out DIR] [--force]" in command


@pytest.mark.parametrize(
    "term",
    [
        "[propose] provider",
        "propose.call_provider",
        "propose.quote",
        "draft-generator-v1.txt",
        "new_generator.scaffold",
        "new_generator.write",
        "DraftGeneratorError",
        "-p no:cacheprovider",
        "SEAMS_MODEL",
        "seams draft-generator: <error>",
        "ADR-0020",
        "ADR-0028",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


def test_answer_has_exactly_three_keys(text: str) -> None:
    section = _section(text, "### 4. The answer is one JSON object")
    rows = [r for r in section.splitlines() if r.startswith("| `")]
    assert [r.split("`")[1] for r in rows] == ["extract", "template", "golden"]


def test_acceptance_has_three_checks(text: str) -> None:
    section = _section(text, "### 5. Acceptance")
    checks = re.findall(r"^\d+\. \*\*(.+?)\*\*", section, re.MULTILINE)
    assert checks == [
        "The golden test passes.",
        "The template restates no model fact.",
        "The template holds no logic.",
    ]
    assert "four tests" in section


def test_cache_dir_and_key(text: str) -> None:
    section = _section(text, "### 6. The cache")
    assert ".seams/generator-drafts/<key>.json" in section
    for part in ("reference's sha256", "model hash", "template name", "provider command"):
        assert part in section
    assert "not cached" in section


def test_never_in_ci(text: str) -> None:
    section = _section(text, "### 9. Never in CI")
    assert "CI calls no provider" in section
    assert "fake provider scripts" in section


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0029", "LLM-drafted generators", "0029-llm-drafted-generators"]' in config
    assert config.index("0028-copilot-suggestions") < config.index("0029-llm-drafted-generators")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "[ADR-0029](./0029-llm-drafted-generators)" in index
    assert index.index("0028-copilot-suggestions") < index.index("0029-llm-drafted-generators")
