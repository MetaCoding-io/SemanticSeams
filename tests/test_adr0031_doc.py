"""ADR-0031 (M028/S04): lifecycle on the class is decided before the vocabulary.
The ADR lets seam:lifecycle name an owl:Class (a shape kept for compatibility), derives
a shape's lifecycle through sh:targetClass and refuses more than one, makes a transition
a domain event that may seam:publishesTo a channel, leaves runtime emission to a
follow-up, and moves seam to 1.4 with no migration."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0031-lifecycle-on-the-class.md"


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text
    assert "**Date:** 2026-11-06" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences", "Open questions"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))
    assert len(numbers) == 5


@pytest.mark.parametrize(
    "heading",
    [
        "`seam:lifecycle` names a class, and a shape is kept for compatibility",
        "A shape's effective lifecycle is its own, else its class's",
        "A transition is a domain event and may publish on a channel",
        "Runtime emission is a follow-up",
        "`seam` goes to 1.4 as a compatible widening",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


def test_subject_is_class_or_shape(text: str) -> None:
    section = _flat(_section(text, "### 1. `seam:lifecycle` names a class"))
    assert "`owl:Class` (preferred) or a `sh:NodeShape`" in section
    assert "seams graph" in section
    assert "owl:Class | sh:NodeShape -> state:StateMachine" in section


def test_effective_lifecycle_is_derived(text: str) -> None:
    section = _flat(_section(text, "### 2. A shape's effective lifecycle"))
    assert "sh:targetClass" in section
    assert "More than one is a violation." in section
    assert "ResolutionError(<shape>, seam:lifecycle, <sorted machine IRIs>)" in section
    assert "?shape seam:lifecycle|sh:targetClass/seam:lifecycle ?machine" in section


def test_transition_is_an_event(text: str) -> None:
    section = _flat(_section(text, "### 3. A transition is a domain event"))
    assert "state:Transition" in section
    assert "seam:publishesTo" in section
    assert "comm:Channel" in section
    assert "state:trigger" in section
    assert "never a copied label" in section


def test_runtime_emission_is_deferred(text: str) -> None:
    section = _flat(_section(text, "### 4. Runtime emission is a follow-up"))
    assert "seams_runtime" in section
    assert "not sent" in section


def test_seam_version_and_shapes(text: str) -> None:
    section = _section(text, "### 5. `seam` goes to 1.4")
    assert "`1.3` to `1.4`" in section
    assert "no migration files" in _flat(section)
    shapes = re.findall(r"^\| `(\w+Shape)` \|", section, re.MULTILINE)
    assert shapes == ["LifecycleShape", "EffectiveLifecycleShape", "PublishesToShape"]


@pytest.mark.parametrize(
    "term",
    [":Expense seam:lifecycle", ":Payment seam:lifecycle", "chapter 9", "seams storm", "D046", "ADR-0001"],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term.lower() in text.lower(), term


@pytest.mark.parametrize(
    "link",
    [
        "(./0022-ontology-notation.md)",
        "(./0021-vocabulary-versions.md)",
        "(./0030-domains-and-bounded-contexts.md)",
        "(../research/2026-11-02-domain-driven-design.md)",
    ],
)
def test_adr_links(text: str, link: str) -> None:
    assert link in text


def test_adr0022_links_the_amendment() -> None:
    adr0022 = (ROOT / "docs" / "adr" / "0022-ontology-notation.md").read_text(encoding="utf-8")
    assert "(./0031-lifecycle-on-the-class.md)" in adr0022


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0031", "Lifecycle on the class", "0031-lifecycle-on-the-class"]' in config
    assert config.index("0030-domains-and-bounded-contexts") < config.index("0031-lifecycle-on-the-class")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "[ADR-0031](./0031-lifecycle-on-the-class)" in index
    assert index.index("0030-domains-and-bounded-contexts") < index.index("0031-lifecycle-on-the-class")
