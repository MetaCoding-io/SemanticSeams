"""C4 zoom levels for the node-link viewer (M006/S02, ADR-0008).

Levels are viewer configuration, not seam predicates (design rule 2): they
decide which model members are drawn and which edges connect them. Each level
is cumulative — L2 shows everything L1 shows plus its own classes and edges.

L1 edges are not derived in Python: they come from the canned projection
query docs/queries/c4-l1-rollup.rq, which has its own acceptance tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Namespace, URIRef

BASE_DIR = Path(__file__).resolve().parent
QUERIES_DIR = BASE_DIR.parent / "docs" / "queries"
# Fixed path — the rollup is never selected by a user-supplied name.
ROLLUP_QUERY_PATH = QUERIES_DIR / "c4-l1-rollup.rq"

SEAM = Namespace("https://w3id.org/seams/seam#")
ARCH = Namespace("https://w3id.org/seams/arch#")


@dataclass(frozen=True)
class C4Level:
    id: str
    title: str
    # Node classes visible at this level (cumulative).
    classes: frozenset[URIRef]
    # (predicate, edge label) pairs drawn between visible nodes (cumulative).
    edge_rules: tuple[tuple[URIRef, str], ...] = ()
    # L1 only: edges come from the rollup query instead of edge_rules.
    rollup: bool = False
    # L3 only: comm elements a visible container seam:exposes become nodes
    # nested inside that container.
    exposed_elements: bool = False
    # The question this level answers, shown on its level card (M006/S03).
    question: str = ""


_L1_CLASSES = frozenset({ARCH.System, ARCH.Person, ARCH.Environment})
_L2_CLASSES = _L1_CLASSES | {ARCH.Container, ARCH.Component, ARCH.DeploymentNode}
_L2_EDGES = ((ARCH.dependsOn, "depends on"), (SEAM.deployedTo, "deployed to"))

C4_LEVELS: dict[str, C4Level] = {
    "L1": C4Level(
        id="L1",
        title="System context",
        classes=_L1_CLASSES,
        rollup=True,
        question="Which systems talk to each other, and where do they run?",
    ),
    "L2": C4Level(
        id="L2",
        title="Containers",
        classes=_L2_CLASSES,
        edge_rules=_L2_EDGES,
        question="Which containers make up the system, and where are they deployed?",
    ),
    "L3": C4Level(
        id="L3",
        title="Components and operations",
        classes=_L2_CLASSES,
        edge_rules=_L2_EDGES + ((SEAM.consumes, "consumes"),),
        exposed_elements=True,
        question="Which operations does each container expose and consume?",
    ),
}

DEFAULT_LEVEL = "L2"


def load_rollup(graph) -> list[tuple[str, str, str]]:
    """Run the C4 L1 rollup query on graph; returns sorted (from, to, kind) rows."""
    sparql = ROLLUP_QUERY_PATH.read_text(encoding="utf-8")
    rows = {(str(r[0]), str(r[1]), str(r[2])) for r in graph.query(sparql)}
    return sorted(rows)
