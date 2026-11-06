"""The C4 L1 projection of domains and bounded contexts (ADR-0030 section 5, M028/S03/T04).

Each test copies expense chapter 9 into tmp_path, appends two domains and two contexts
to its architecture graph and their seam:owns facts to its seams graph, and points the
viewer at the copy. The chat app, which declares no domain, must draw L1 as before.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import rdflib
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import levels, validation  # noqa: E402

CHAPTER_09 = ROOT / "examples" / "expenses" / "chapter-09"
EX = "https://example.org/expenses/"
ARCHITECTURE = f"{EX}expense_architecture"
SYSTEM = f"{EX}expense_system"
EXPENSE_DOMAIN = f"{EX}expense_domain"
FINANCE_DOMAIN = f"{EX}finance_domain"
EXPENSE_CONTEXT = f"{EX}expense_context"
FINANCE_CONTEXT = f"{EX}finance_context"
CHAT = "https://example.org/chat/"

# The payout process is executed by expense_api (a process in an owned model), the
# expense IFML is presented by employee_portal (an owned model itself): both routes
# of ADR-0030 section 2 reach the one system.
DOMAINS = """
<urn:seams:graph:model:expense_architecture> {
    :expense_domain a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_system , :expense_context ;
        seam:inModel :expense_architecture .
    :finance_domain a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context ;
        seam:inModel :expense_architecture .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" ;
        seam:inModel :expense_architecture .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" ;
        seam:inModel :expense_architecture .
}
<urn:seams:graph:seams> {
    :expense_context seam:owns :expense_ontology , :expense_ifml .
    :finance_context seam:owns :payout_bpmn .
}
"""


@pytest.fixture(autouse=True)
def restore_viewer():
    """Point the viewer back at its model afterwards; the conformance cache is
    keyed by id(ds), so clear it on both sides (MEM010)."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    viewer_app.configure(original)


def open_viewer(tmp_path: Path, extra: str = DOMAINS) -> TestClient:
    app_dir = Path(shutil.copytree(CHAPTER_09, tmp_path / "chapter-09"))
    trig = app_dir / "expenses.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + extra, encoding="utf-8")
    viewer_app.configure(trig)
    return TestClient(viewer_app.app)


def l1(model_iri: str = ARCHITECTURE):
    nodes, edges = viewer_app.c4_graph_data(model_iri, "L1")
    return {n["id"]: n for n in nodes}, [(e["from"], e["to"], e["label"]) for e in edges]


def test_domain_and_context_classes_are_l1():
    assert {levels.ARCH.Domain, levels.ARCH.BoundedContext} <= levels.C4_LEVELS["L1"].classes


def test_domain_is_a_compound_node_holding_its_systems_and_contexts(tmp_path):
    open_viewer(tmp_path)
    nodes, _ = l1()
    assert {i: n["parent"] for i, n in nodes.items() if n["parent"]} == {
        SYSTEM: EXPENSE_DOMAIN,
        EXPENSE_CONTEXT: EXPENSE_DOMAIN,
        FINANCE_CONTEXT: FINANCE_DOMAIN,
    }
    assert nodes[EXPENSE_DOMAIN]["parent"] is None
    assert nodes[FINANCE_DOMAIN]["parent"] is None


def test_domain_is_labelled_with_its_classification(tmp_path):
    open_viewer(tmp_path)
    nodes, _ = l1()
    assert nodes[FINANCE_DOMAIN]["classification"] == "core"
    assert nodes[EXPENSE_DOMAIN]["classification"] == "supporting"
    assert nodes[FINANCE_DOMAIN]["typeLabel"].endswith("· core")
    assert nodes[FINANCE_DOMAIN]["label"] == "Finance"
    assert "classification" not in nodes[EXPENSE_CONTEXT]
    assert "classification" not in nodes[SYSTEM]


def test_runs_edges_join_each_context_to_the_system_running_it(tmp_path):
    open_viewer(tmp_path)
    _, edges = l1()
    assert [e for e in edges if e[2] == "runs"] == [
        (EXPENSE_CONTEXT, SYSTEM, "runs"),
        (FINANCE_CONTEXT, SYSTEM, "runs"),
    ]


def test_l1_nodes_and_edges_are_sorted(tmp_path):
    open_viewer(tmp_path)
    nodes, edges = viewer_app.c4_graph_data(ARCHITECTURE, "L1")
    assert nodes == sorted(nodes, key=lambda n: (n["parent"] or "", n["id"]))
    keys = [(e["from"], e["to"], e["label"]) for e in edges]
    assert keys == sorted(keys)


def test_context_owning_no_running_model_has_no_runs_edge(tmp_path):
    """A context whose owned models no container presents or executes draws no edge."""
    open_viewer(tmp_path, DOMAINS.replace(":finance_context seam:owns :payout_bpmn .", ""))
    _, edges = l1()
    assert (FINANCE_CONTEXT, SYSTEM, "runs") not in edges
    assert (EXPENSE_CONTEXT, SYSTEM, "runs") in edges


def test_domain_with_no_classification_still_draws(tmp_path):
    """DomainShape reports the missing classification; the viewer still draws the frame."""
    open_viewer(tmp_path, DOMAINS.replace("arch:classification arch:Core ;", ""))
    nodes, _ = l1()
    assert "classification" not in nodes[FINANCE_DOMAIN]
    assert nodes[FINANCE_CONTEXT]["parent"] == FINANCE_DOMAIN


def test_l1_page_embeds_the_domain_frame(tmp_path):
    """The L1 page hands the renderer the domain's classification and the runs edge."""
    client = open_viewer(tmp_path)
    resp = client.get(f"/view/{quote(ARCHITECTURE, safe='')}?level=L1", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert '"classification": "core"' in resp.text
    assert '"label": "runs"' in resp.text
    assert FINANCE_DOMAIN in resp.text


def test_chapter_without_domains_draws_l1_as_before(tmp_path):
    open_viewer(tmp_path, "")
    nodes, edges = l1()
    assert not any("classification" in n for n in nodes.values())
    assert not any(label == "runs" for _, _, label in edges)


def test_chat_app_l1_unchanged():
    nodes, edges = l1(f"{CHAT}chat_architecture")
    assert {i: n["parent"] for i, n in nodes.items()} == {
        f"{CHAT}chat_system": None,
        f"{CHAT}development": None,
        f"{CHAT}production": None,
    }
    assert edges == [(f"{CHAT}chat_system", f"{CHAT}production", "deployed to")]
    assert not any("classification" in n for n in nodes.values())


def test_runs_branch_needs_a_container_of_the_system():
    """The rollup's runs branch on a bare graph: a model presented by something that is
    not an arch:Container, or a container in no system, draws no edge."""
    ex = rdflib.Namespace("https://example.org/rollup/")
    seam = rdflib.Namespace("https://w3id.org/seams/seam#")
    g = rdflib.Graph()
    g.add((ex.ctx, rdflib.RDF.type, levels.ARCH.BoundedContext))
    g.add((ex.ctx, seam.owns, ex.ui_model))
    g.add((ex.sys, rdflib.RDF.type, levels.ARCH.System))
    g.add((ex.sys, levels.ARCH.contains, ex.ui))
    g.add((ex.ui, seam.presents, ex.ui_model))  # ex.ui is not typed arch:Container
    g.add((ex.loose, rdflib.RDF.type, levels.ARCH.Container))
    g.add((ex.loose, seam.presents, ex.ui_model))  # in no system
    assert levels.load_rollup(g) == []
    g.add((ex.ui, rdflib.RDF.type, levels.ARCH.Container))
    assert levels.load_rollup(g) == [(str(ex.ctx), str(ex.sys), "runs")]
