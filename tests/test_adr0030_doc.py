"""ADR-0030 (M028/S02): domains and bounded contexts are decided before the vocabulary.
The ADR makes the domain and the bounded context arch: elements, has a context own one
ontology and its models by seam:owns, keeps one context per file a convention, gives a
shared ontology one owner (amending ADR-0022), and leaves context maps to B2."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0030-domains-and-bounded-contexts.md"


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
    assert len(numbers) == 7


@pytest.mark.parametrize(
    "heading",
    [
        "A domain is an `arch:` element with one classification",
        "A bounded context is an `arch:` element that owns its models",
        "One context per TriG file is a convention, not a rule",
        "A shared ontology has exactly one owning context",
        "The C4 L1 projection draws domains and contexts",
        "Shapes and the first query",
        "Context maps are out of scope",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


def test_domain_has_three_classifications(text: str) -> None:
    section = _section(text, "### 1. A domain")
    for term in ("arch:Domain", "arch:classification", "arch:Core", "arch:Supporting", "arch:Generic"):
        assert term in section, term


def test_context_is_not_a_model(text: str) -> None:
    section = _flat(_section(text, "### 2. A bounded context"))
    assert "arch:BoundedContext" in section
    assert "not a `seam:Model` subclass" in section
    assert "seam:owns" in section
    assert "Exactly one ontology." in section
    assert "seams graph" in section


def test_shared_ontology_amends_adr0022(text: str) -> None:
    section = _flat(_section(text, "### 4. A shared ontology"))
    assert "amends [ADR-0022](./0022-ontology-notation.md)" in section
    assert "owl:imports" in section
    assert "No ontology is owned by two contexts." in section


def test_shapes_and_query_are_named(text: str) -> None:
    section = _section(text, "### 6. Shapes and the first query")
    shapes = re.findall(r"^\| `(\w+Shape)` \|", section, re.MULTILINE)
    assert shapes == ["DomainShape", "BoundedContextShape", "ModelOwnerShape", "OwnsTargetShape"]
    assert "core operations with no handler and no scenario" in _flat(section)
    assert "docs/queries/coverage/core-operations-untested.rq" in section


def test_context_maps_go_to_b2(text: str) -> None:
    section = _section(text, "### 7. Context maps are out of scope")
    assert "is B2" in section


@pytest.mark.parametrize(
    "term",
    [
        "seams storm",
        "payouts",
        "PaymentShape",
        "finance_ontology",
        "expense_ontology",
        "chapter 11",
        "ADR-0001",
        "ADR-0021",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


@pytest.mark.parametrize(
    "link",
    [
        "(./0022-ontology-notation.md)",
        "(../research/2026-11-02-domain-driven-design.md)",
    ],
)
def test_adr_links(text: str, link: str) -> None:
    assert link in text


def test_adr0022_links_the_amendment() -> None:
    adr0022 = (ROOT / "docs" / "adr" / "0022-ontology-notation.md").read_text(encoding="utf-8")
    assert "(./0030-domains-and-bounded-contexts.md)" in adr0022


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0030", "Domains and bounded contexts", "0030-domains-and-bounded-contexts"]' in config
    assert config.index("0029-llm-drafted-generators") < config.index("0030-domains-and-bounded-contexts")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "[ADR-0030](./0030-domains-and-bounded-contexts)" in index
    assert index.index("0029-llm-drafted-generators") < index.index("0030-domains-and-bounded-contexts")
