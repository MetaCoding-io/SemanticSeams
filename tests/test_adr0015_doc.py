"""ADR-0015 (M016/S01): environments are decided before the compose generator
changes. The ADR inventories every compose.override.yaml line group, picks
qualified relations (deploy:override) over a named graph per environment, states
the override rule, the storage binding per environment and the replica caveat,
and names the per-environment output files. Its turtle example parses with a
development and a production arch:Environment and an environment-scoped fact."""

import re
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Namespace

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0015-environments.md"
ARCH = Namespace("https://w3id.org/seams/arch#")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
CHAT = Namespace("https://example.org/chat/")


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
        "arch:Environment",
        "compose.development.yaml",
        "compose.production.yaml",
        "SEAMS_DEV_USER",
        "SEAMS_SEED",
        "replicas",
        "override",
        "deploy:override",
        "deploy:environment",
        "deploy:secretFile",
        "pull_policy",
        "service_healthy",
        "POSTGRES_PASSWORD",
        "SEAMS_APP_DIR",
        "SEAMS_ROUTES_FILE",
        "caddy",
        "deploy:connectsTo",
        "A10",
        "ADR-0001",
        "ADR-0011",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_adr_records_the_rejected_named_graph_option(text: str) -> None:
    alternatives = text.split("## Alternatives Considered", 1)[1].split("## Consequences", 1)[0]
    assert "named graph per environment" in alternatives
    assert "Rejected" in alternatives


def test_example_declares_development_and_production(example: Graph) -> None:
    envs = set(example.subjects(RDF.type, ARCH.Environment))
    assert envs == {CHAT.development, CHAT.production}


def test_example_has_an_environment_scoped_deploy_fact(example: Graph) -> None:
    overrides = list(example.objects(None, DEPLOY.override))
    assert overrides
    envs = set(example.subjects(RDF.type, ARCH.Environment))
    for node in overrides:
        assert (node, RDF.type, DEPLOY.Override) in example
        assert set(example.objects(node, DEPLOY.environment)) <= envs
        assert len(list(example.objects(node, DEPLOY.environment))) == 1
        facts = {p for p, _ in example.predicate_objects(node)} - {RDF.type, DEPLOY.environment}
        assert facts, "an override must carry at least one deploy: fact"
        assert all(str(p).startswith(str(DEPLOY)) for p in facts)


def test_override_binding_keeps_the_shared_store(example: Graph) -> None:
    # Storage binding per environment: the development DB_URL binding reaches the
    # same store as the shared one; only where its value comes from changes.
    stores = set(example.objects(None, DEPLOY.connectsTo))
    assert len(stores) == 1
    dev_bindings = [
        b
        for node in example.objects(None, DEPLOY.override)
        for cfg in example.objects(node, DEPLOY.configuration)
        for b in example.objects(cfg, DEPLOY.binding)
        if (b, DEPLOY.connectsTo, None) in example
    ]
    assert dev_bindings
    for b in dev_bindings:
        assert list(example.objects(b, DEPLOY.secretFile))
        assert not list(example.objects(b, DEPLOY.secretRef))


def test_example_holds_no_secret_value(text: str) -> None:
    block = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)[0]
    assert "postgresql://" not in block
    assert "seams-dev" not in block


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0015", "Environments", "0015-environments"]' in config


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "0015-environments" in index


def test_backlog_a4_cites_adr_and_stays_planned() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| A4 |"))
    assert "ADR-0015" in row
    assert "planned (M016/S02)" in row
