"""ADR-0012 (M014/S01): operation implementation is recorded before the runtime
changes. The ADR names the seam predicate (seam:implementedBy), the three
implementation kinds, the handlers package, the error contract and the step
row field, and its turtle example parses with one implementation of each kind."""

import re
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Namespace

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0012-operation-implementation.md"
SEAM = Namespace("https://w3id.org/seams/seam#")
COMM = Namespace("https://w3id.org/seams/comm#")
KINDS = {COMM.LLMCompletion, COMM.PythonHandler, COMM.HTTPEndpoint}


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def example(text: str) -> Graph:
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    return Graph().parse(data=blocks[0], format="turtle")


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize(
    "term",
    [
        "seam:implementedBy",
        "comm:LLMCompletion",
        "comm:PythonHandler",
        "comm:HTTPEndpoint",
        "comm:handler",
        "ResolutionError",
        "SEAMS_HANDLERS",
        "Runtime.load",
        'row["implementation"]',
        "deploy:serviceOf",
        "ADR-0007",
        "Principle 8",
        "C1",
        "C4",
        "never overwrites",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_turtle_example_has_one_implementation_of_each_kind(example: Graph) -> None:
    impls = sorted(example.objects(None, SEAM.implementedBy))
    assert len(impls) == 3
    kinds = [set(example.objects(impl, RDF.type)) & KINDS for impl in impls]
    assert all(len(k) == 1 for k in kinds), kinds
    assert set().union(*kinds) == KINDS


def test_only_the_python_handler_names_a_handler_path(example: Graph) -> None:
    for impl in example.objects(None, SEAM.implementedBy):
        paths = list(example.objects(impl, COMM.handler))
        if (impl, RDF.type, COMM.PythonHandler) in example:
            assert len(paths) == 1
            assert all(part.isidentifier() for part in str(paths[0]).split("."))
        else:
            assert paths == []


def test_example_holds_no_endpoint_url(text: str) -> None:
    # HTTP bases come from deploy:serviceOf bindings, never from the model text.
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)
    assert "http://localhost" not in blocks[0]
    assert '"https://' not in blocks[0]


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0012", "Operation implementation", "0012-operation-implementation"]' in config


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "0012-operation-implementation" in index


def test_backlog_u6_cites_adr() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| U6 |"))
    assert "ADR-0012" in row
    assert "M014/S02" in row and "M014/S03" in row
