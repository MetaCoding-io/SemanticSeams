"""ADR-0025 (M024/S01): SemPKM as a store is recorded before the runtime changes.
The ADR places deploy:SemPKM beside SQLite and PostgreSQL, resolves the research
note's open points (nested values, IRIs, identity, gist version), keeps embedded
SQLite the default, and its turtle example parses and states a SemPKM store."""

import re
from pathlib import Path

import pytest
from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0025-sempkm-store.md"
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
SEAM = Namespace("https://w3id.org/seams/seam#")
EX = Namespace("https://example.org/expenses/")


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize(
    "term",
    [
        "deploy:SemPKM",
        "deploy:SQLite",
        "deploy:PostgreSQL",
        "deploy:connectsTo",
        "deploy:authenticatesTo",
        "POST /api/commands",
        "SPARQL",
        "ResolutionError",
        "ADR-0011",
        "ADR-0009",
        "/healthz",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


@pytest.mark.parametrize(
    "heading",
    [
        "Nested values are objects joined by an edge",
        "Identity: one service token per application",
        "IRIs: the runtime gives way",
        "gist version",
        "SemPKM is not the default",
        "The error contract",
    ],
)
def test_adr_resolves_open_point(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}", text, re.MULTILINE), heading


def test_adr_keeps_embedded_sqlite_the_default(text: str) -> None:
    assert "**Embedded SQLite stays the default**" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_turtle_example_parses_and_states_the_store(text: str) -> None:
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    g = Graph().parse(data=blocks[0], format="turtle")
    assert (EX.expense_store, DEPLOY.storeKind, DEPLOY.SemPKM) in g
    assert (EX.ExpenseShape, SEAM.storedIn, EX.expense_store) in g
    assert set(g.objects(None, DEPLOY.connectsTo)) == {EX.expense_store}
    token = next(g.subjects(DEPLOY.authenticatesTo, EX.expense_store))
    assert (token, DEPLOY.secretRef, None) in g
    assert (token, DEPLOY.value, None) not in g


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0025", "SemPKM as a store", "0025-sempkm-store"]' in config
    assert config.index("0024-json-ld-context") < config.index("0025-sempkm-store")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "0025-sempkm-store" in index


def test_adr_0011_points_forward() -> None:
    adr0011 = (ROOT / "docs" / "adr" / "0011-storage-resolution.md").read_text(encoding="utf-8")
    kinds = adr0011.split("### Supported kinds and the default", 1)[1].split("\n### ", 1)[0]
    assert "[ADR-0025](./0025-sempkm-store.md)" in kinds


def test_backlog_cites_adr_for_o4() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| O4 |"))
    assert "ADR-0025" in row
    assert "*ADR done, M024/S01: [ADR-0025]" in backlog
