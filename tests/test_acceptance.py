"""Executable acceptance test for the SemanticSeams ontologies + checkout example.

The CI form of the prose claims in README.md and examples/checkout.trig:

1. every Turtle/TriG file parses;
2. the checkout model conforms to ontology/shapes/seam-shapes.ttl;
3. the shapes actually reject bad seams (a vacuously-green shapes file is
   exactly the silent regression this suite exists to prevent);
4. every non-reserved seam predicate is exercised by the example;
5. the canned queries in docs/queries/ return exactly the expected rows —
   the flagship cross-layer traversals can never silently return zero rows again.
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
EXAMPLE_TTL = ROOT / "examples" / "checkout.ttl"
EXAMPLE_TRIG = ROOT / "examples" / "checkout.trig"
QUERIES_DIR = ROOT / "docs" / "queries"

SEAM = Namespace("https://w3id.org/seams/seam#")
SHOP = Namespace("https://example.org/shop/")
CHAT = Namespace("https://example.org/chat/")

PERSIST_TASK = URIRef("https://example.org/shop/order_bpmn#persist_task")
FULFILL_TASK = URIRef("https://example.org/shop/fulfillment_bpmn#fulfill_task")

CHAT_PERSIST_USER_MSG = URIRef("https://example.org/chat/chat_bpmn#persist_user_msg")
CHAT_PERSIST_RESPONSE = URIRef("https://example.org/chat/chat_bpmn#persist_response")

CHAT_APP_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"

RESERVED_PREDICATES = {SEAM.conformsTo, SEAM.realizes}


def load(*paths: Path) -> rdflib.Graph:
    """Load one or more Turtle files into a single Graph."""
    g = rdflib.Graph()
    for p in paths:
        g.parse(p, format="turtle")
    return g


def load_dataset(*ttl_paths: Path, trig_path: Path | None = None) -> rdflib.Dataset:
    """Load ontology Turtle files and a TriG example into a Dataset.

    Turtle files are parsed into the default graph. The TriG file populates
    named graphs. Queries against the Dataset's union graph see all triples.
    """
    ds = rdflib.Dataset()
    for p in ttl_paths:
        ds.default_graph.parse(p, format="turtle")
    if trig_path:
        ds.parse(trig_path, format="trig")
    return ds


@pytest.fixture(scope="session")
def dataset() -> rdflib.Dataset:
    """Ontologies + TriG example loaded into a Dataset for named-graph-aware tests."""
    return load_dataset(*ONTOLOGY_FILES, trig_path=EXAMPLE_TRIG)


@pytest.fixture(scope="session")
def model(dataset: rdflib.Dataset) -> rdflib.Graph:
    """Union graph view for backward-compatible SPARQL queries.

    rdflib.Dataset exposes a union of all graphs when queried directly,
    maintaining compatibility with existing tests that expect a flat Graph interface.
    """
    g = rdflib.Graph()
    for s, p, o, _ctx in dataset.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def canned(name: str) -> str:
    return (QUERIES_DIR / name).read_text()


@pytest.mark.parametrize(
    "path", [*ONTOLOGY_FILES, SHAPES_FILE, EXAMPLE_TTL], ids=lambda p: p.name
)
def test_turtle_parses(path):
    load(path)


def test_trig_parses():
    """TriG file parses into a Dataset with named graphs."""
    ds = rdflib.Dataset()
    ds.parse(EXAMPLE_TRIG, format="trig")
    graphs = [g.identifier for g in ds.contexts()]
    assert len(graphs) >= 8, f"Expected 8+ graphs, got {len(graphs)}"


def test_model_conforms_to_seam_shapes(model):
    conforms, _, report = pyshacl.validate(
        model, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    assert conforms, report


def test_seam_shapes_have_teeth():
    bad = load(*ONTOLOGY_FILES)
    bad.parse(
        data="""
        @prefix seam: <https://w3id.org/seams/seam#> .
        @prefix proc: <https://w3id.org/seams/proc#> .
        @prefix ex:   <https://example.org/bad/> .

        ex:model a seam:Model .                    # missing seam:notation
        ex:task a proc:ServiceTask ;
            seam:decidedBy ex:not_a_decision .     # only BusinessRuleTasks are decidedBy
        """,
        format="turtle",
    )
    conforms, _, _ = pyshacl.validate(
        bad, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    assert not conforms, "shapes accepted a Model without notation and a ServiceTask with seam:decidedBy"


def test_every_nonreserved_seam_predicate_is_exercised(dataset):
    """Verify all declared seam predicates appear in the TriG dataset."""
    declared = {
        p
        for p in load(ROOT / "ontology" / "seam.ttl").subjects(RDF.type, RDF.Property)
        if str(p).startswith(str(SEAM))
    }
    used = set()
    for _s, p, _o, _g in dataset.quads((None, None, None, None)):
        if str(p).startswith(str(SEAM)):
            used.add(p)
    missing = declared - RESERVED_PREDICATES - used
    assert not missing, (
        f"seam predicates never exercised by checkout.trig: {sorted(missing)}"
    )


def test_what_writes_shape(model):
    """The flagship traversal: UI event -> process -> tasks -> shape, including
    the async hop through the order.events channel into fulfillment."""
    rows = model.query(
        canned("what-writes-shape.rq"), initBindings={"shape": SHOP.OrderShape}
    )
    assert {(r.event, r.writer) for r in rows} == {
        (SHOP.submit_order, PERSIST_TASK),
        (SHOP.submit_order, FULFILL_TASK),
    }


def test_impact_of_node(model):
    """'What breaks if db01 goes away' — must reach containers AND processes,
    and must NOT depend on deploy:dependsOn (startup ordering)."""
    rows = model.query(
        canned("impact-of-node.rq"), initBindings={"node": SHOP.db01}
    )
    assert {r.impacted for r in rows} == {
        SHOP.order_db,
        SHOP.order_api,
        SHOP.web_ui,
        SHOP.order_process,
        SHOP.fulfillment_process,
    }


def test_what_moves_state(model):
    """Which tasks may move an Order out of 'submitted'? t_cancel has no firing
    task on purpose — that absence is an M2 model-health warning, not an error."""
    rows = model.query(
        canned("what-moves-state.rq"), initBindings={"state": SHOP.s_submitted}
    )
    assert {(r.task, r.transition, r.toState) for r in rows} == {
        (FULFILL_TASK, SHOP.t_fulfill, SHOP.s_fulfilled),
    }


# --- Named-graph verification (ADR-0001) ---

SEAMS_GRAPH = URIRef("urn:seams:graph:seams")


def test_seam_predicates_isolated_to_seams_graph(dataset):
    """Cross-layer seam predicates must only appear in the seams graph.

    seam:inModel is the sole seam predicate allowed in model graphs (it anchors
    resources to their owning model). Every other seam: predicate must live in
    the dedicated seams graph per ADR-0001.
    """
    ALLOWED_IN_MODEL_GRAPHS = {SEAM.inModel}
    leaked = []
    for s, p, o, ctx in dataset.quads((None, None, None, None)):
        graph_id = ctx.identifier if hasattr(ctx, "identifier") else ctx
        if str(p).startswith(str(SEAM)) and p not in ALLOWED_IN_MODEL_GRAPHS:
            if graph_id != SEAMS_GRAPH:
                leaked.append((graph_id, s, p, o))
    assert not leaked, (
        f"seam predicates leaked into model graphs:\n"
        + "\n".join(f"  {g}: {s} {p} {o}" for g, s, p, o in leaked)
    )


def _ground_triples(graph_or_quads, is_quads=False):
    """Return the set of triples that contain no blank nodes (ground triples)
    and a count of triples involving at least one blank node."""
    ground = set()
    bnode_count = 0
    items = graph_or_quads if is_quads else graph_or_quads
    for item in items:
        s, p, o = item[:3]
        if isinstance(s, rdflib.BNode) or isinstance(o, rdflib.BNode):
            bnode_count += 1
        else:
            ground.add((s, p, o))
    return ground, bnode_count


def test_no_triple_loss_trig_vs_turtle():
    """Union of TriG quads must contain at least as many unique triples as the
    flat Turtle file, proving the named-graph conversion lost nothing.

    Blank nodes get fresh identifiers per parse, so we compare ground triples
    (no blank nodes) exactly and verify bnode-bearing triple counts match.
    """
    flat = rdflib.Graph()
    flat.parse(EXAMPLE_TTL, format="turtle")
    flat_ground, flat_bnode_count = _ground_triples(flat)

    ds = rdflib.Dataset()
    ds.parse(EXAMPLE_TRIG, format="trig")
    trig_ground, trig_bnode_count = _ground_triples(
        ds.quads((None, None, None, None))
    )

    missing = flat_ground - trig_ground
    assert not missing, (
        f"{len(missing)} ground triples in checkout.ttl missing from checkout.trig:\n"
        + "\n".join(f"  {s} {p} {o}" for s, p, o in sorted(missing, key=str))
    )
    assert len(trig_ground) >= len(flat_ground), (
        f"TriG ground triples ({len(trig_ground)}) fewer than "
        f"flat Turtle ({len(flat_ground)})"
    )
    assert trig_bnode_count >= flat_bnode_count, (
        f"TriG bnode triples ({trig_bnode_count}) fewer than "
        f"flat Turtle ({flat_bnode_count})"
    )


# --- Chat-app model tests ---


@pytest.fixture(scope="session")
def chat_dataset() -> rdflib.Dataset:
    """Ontologies + chat-app TriG loaded into a Dataset."""
    return load_dataset(*ONTOLOGY_FILES, trig_path=CHAT_APP_TRIG)


@pytest.fixture(scope="session")
def chat_model(chat_dataset: rdflib.Dataset) -> rdflib.Graph:
    """Union graph for chat-app SPARQL queries."""
    g = rdflib.Graph()
    for s, p, o, _ctx in chat_dataset.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def test_chat_app_trig_parses():
    """Chat-app TriG parses into a Dataset with exactly 6 named graphs."""
    ds = rdflib.Dataset()
    ds.parse(CHAT_APP_TRIG, format="trig")
    graph_ids = {
        g.identifier
        for g in ds.graphs()
        if str(g.identifier) != "urn:x-rdflib:default"
    }
    assert len(graph_ids) == 6, f"Expected 6 named graphs, got {len(graph_ids)}: {graph_ids}"


def test_chat_app_conforms_to_seam_shapes(chat_model):
    conforms, _, report = pyshacl.validate(
        chat_model, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    assert conforms, report


def test_chat_app_seam_predicates_isolated(chat_dataset):
    """Cross-layer seam predicates in chat-app must only appear in the seams graph."""
    ALLOWED_IN_MODEL_GRAPHS = {SEAM.inModel}
    leaked = []
    for s, p, o, ctx in chat_dataset.quads((None, None, None, None)):
        graph_id = ctx.identifier if hasattr(ctx, "identifier") else ctx
        if str(p).startswith(str(SEAM)) and p not in ALLOWED_IN_MODEL_GRAPHS:
            if graph_id != SEAMS_GRAPH:
                leaked.append((graph_id, s, p, o))
    assert not leaked, (
        f"seam predicates leaked into model graphs:\n"
        + "\n".join(f"  {g}: {s} {p} {o}" for g, s, p, o in leaked)
    )


def test_chat_app_what_writes_shape(chat_model):
    """send_message event reaches MessageShape through persist_user_msg and persist_response."""
    rows = chat_model.query(
        canned("what-writes-shape.rq"),
        initBindings={"shape": CHAT.MessageShape},
    )
    assert {(r.event, r.writer) for r in rows} == {
        (CHAT.send_message, CHAT_PERSIST_USER_MSG),
        (CHAT.send_message, CHAT_PERSIST_RESPONSE),
    }


def test_chat_app_impact_of_node(chat_model):
    """'What breaks if db01 goes away' — must reach message_db, chat_api, chat_ui,
    and the send_message_process."""
    rows = chat_model.query(
        canned("impact-of-node.rq"), initBindings={"node": CHAT.db01}
    )
    assert {r.impacted for r in rows} == {
        CHAT.message_db,
        CHAT.chat_api,
        CHAT.chat_ui,
        CHAT.send_message_process,
    }


def test_chat_app_what_moves_state(chat_model):
    """persist_user_msg fires t_send, moving message from composing to sending."""
    rows = chat_model.query(
        canned("what-moves-state.rq"),
        initBindings={"state": CHAT.s_composing},
    )
    assert {(r.task, r.transition, r.toState) for r in rows} == {
        (CHAT_PERSIST_USER_MSG, CHAT.t_send, CHAT.s_sending),
    }
