"""ADR-0011 (M011/S01): storage resolution is recorded before the runtime
changes. The ADR names the three graph facts (seam:storedIn, deploy:storeKind,
deploy:connectsTo), the supported kinds, the default and the error contract,
and its turtle example parses and states the chat app's store."""

import re
from pathlib import Path

import pytest
from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0011-storage-resolution.md"
SEAM = Namespace("https://w3id.org/seams/seam#")
CHAT = Namespace("https://example.org/chat/")


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize(
    "term",
    [
        "seam:storedIn",
        "deploy:storeKind",
        "deploy:StoreKind",
        "deploy:PostgreSQL",
        "deploy:SQLite",
        "deploy:connectsTo",
        "ResolutionError",
        "seam:executes",
        "SEAMS_DB",
        "/healthz",
        "U8",
        "A10",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_turtle_example_parses_and_states_the_store(text: str) -> None:
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    g = Graph().parse(data=blocks[0], format="turtle")
    assert (CHAT.MessageShape, SEAM.storedIn, CHAT.message_db) in g


@pytest.mark.parametrize("secret", ["postgres://", "postgresql://user:"])
def test_adr_shows_no_connection_string(text: str, secret: str) -> None:
    assert secret not in text
