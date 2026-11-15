"""ADR-0040 (M031/S02): external systems and inbound webhooks are decided before the
vocabulary. `arch:external true` marks an arch:System the model neither builds nor runs;
its containers and operations are external by derivation; generators write nothing for
it; impact queries stop at its boundary; an inbound webhook is a channel whose sender is
an external container, and ADR-0027's SemPKM webhook is restated as one case."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0040-external-systems-and-webhooks.md"


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text
    assert "**Date:** 2026-11-15" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences", "Open questions"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, 7))


@pytest.mark.parametrize(
    "heading",
    [
        "`arch:external true` marks a system the model neither builds nor runs",
        "Its containers and operations are external by derivation, never by a second marker",
        "Generators emit no code, no image and no service for an external system",
        "Impact queries stop at the boundary and report the system",
        "An inbound webhook is a channel the model exposes and an external container sends",
        "Shape rules and errors",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


def test_marker_term(text: str) -> None:
    section = _flat(_section(text, "### 1. `arch:external true`"))
    assert "**Domain `arch:System`, range `xsd:boolean`.**" in section
    assert "only as `true`" in section
    assert "**`arch` moves from 1.2 to 1.3**, a compatible widening" in section
    assert "No migration file." in section
    assert "arch:external true ;" in section


def test_operations_are_external_by_derivation(text: str) -> None:
    section = _flat(_section(text, "### 2. Its containers and operations"))
    assert "an `arch:Container` that an external system `arch:contains`" in section
    assert "that an external container `seam:exposes`" in section
    assert "**No marker on the operation.**" in section


def test_generators_emit_nothing(text: str) -> None:
    section = _flat(_section(text, "### 3. Generators emit no code"))
    assert "writes no service, volume, secret or healthcheck for an external container" in section
    assert "one system that is not external" in section
    assert "A `deploy:serviceOf` binding cannot name one" in section
    assert "No `depends_on` on an external container." in section
    assert "it raises `GeneratorError` naming the same subject and predicate" in section
    assert "with a parity case" in section


def test_impact_stops_at_the_boundary(text: str) -> None:
    section = _flat(_section(text, "### 4. Impact queries"))
    assert "`impact-of-node.rq`" in section
    assert "**It never starts a walk.**" in section
    assert "lists the external **system** once, not its containers" in section
    assert "the walk does not continue through it" in section


def test_inbound_webhook_convention_restates_o6(text: str) -> None:
    section = _flat(_section(text, "### 5. An inbound webhook"))
    assert "**The sender is an external container.**" in section
    assert "There is no generic `comm:Webhook` transport." in section
    assert "ADR-0027 restated under this convention" in section
    assert "`comm:SemPKMWebhook` is an inbound transport" in section
    assert "into an external `:sempkm`" in section


def test_shape_rules(text: str) -> None:
    section = _section(text, "### 6. Shape rules and errors")
    shapes = re.findall(r"^\| `(seamsh:\w+)` \|", section, re.MULTILINE)
    assert shapes == [
        "seamsh:ExternalMarkerShape",
        "seamsh:ExternalContainmentShape",
        "seamsh:ExternalContainerShape",
        "seamsh:ExternalReachShape",
    ]
    assert "ResolutionError(subject, predicate, detail)" in section


@pytest.mark.parametrize("term", ["arch:external", "comm:SemPKMWebhook", "O6", "X4", "M031/S02", ":expense_pkm"])
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text, term


@pytest.mark.parametrize(
    "link",
    [
        "(./0001-named-graph-partitioning.md)",
        "(./0002-iri-identity-and-migration.md)",
        "(./0012-operation-implementation.md)",
        "(./0021-vocabulary-versions.md)",
        "(./0025-sempkm-store.md)",
        "(./0027-sempkm-webhook-channel.md)",
        "(./0032-context-map-relationships.md)",
        "(../research/2026-10-29-uml-coverage-and-gaps.md)",
    ],
)
def test_adr_links(text: str, link: str) -> None:
    assert link in text
    assert (ADR.parent / link[1:-1]).resolve().is_file(), link


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0040", "External systems and webhooks", "0040-external-systems-and-webhooks"]' in config
    assert config.index("0039-data-classification") < config.index("0040-external-systems-and-webhooks")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "[ADR-0040](./0040-external-systems-and-webhooks)" in index
    assert index.index("0039-data-classification") < index.index("0040-external-systems-and-webhooks")


def test_backlog_notes_the_adr() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| X4 |"))
    assert "[ADR-0040](adr/0040-external-systems-and-webhooks.md) accepted (M031/S02)" in row
    assert "in progress (M031/S02)" in row
