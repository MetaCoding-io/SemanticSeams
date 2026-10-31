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
from rdflib import RDF, Literal, Namespace, URIRef

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
# seam:completedOn (ADR-0009) needs a user task and a form, which checkout does not
# model; the human-task fixture exercises it instead.
HUMAN_TASK_TRIG = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
EXPENSES_CHAPTER_7_TRIG = ROOT / "examples" / "expenses" / "chapter-07" / "expenses.trig"

RESERVED_PREDICATES = {SEAM.conformsTo, SEAM.realizes}
# Declared ahead of their first example: seam:catches (ADR-0013) is added in M014/S04/T01,
# and the expense chapter 9 checkpoint gains the first lifted error boundary in
# M014/S04/T04. test_pending_predicates_are_not_yet_exercised fails once a fixture
# uses one, as the reminder to drop it from this set.
PENDING_PREDICATES = {SEAM.catches}
EXPENSES_CHAPTER_9_TRIG = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"


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


@pytest.mark.parametrize("path", [*ONTOLOGY_FILES, SHAPES_FILE, EXAMPLE_TTL], ids=lambda p: p.name)
def test_turtle_parses(path):
    load(path)


def test_trig_parses():
    """TriG file parses into a Dataset with named graphs."""
    ds = rdflib.Dataset()
    ds.parse(EXAMPLE_TRIG, format="trig")
    graphs = [g.identifier for g in ds.contexts()]
    assert len(graphs) >= 8, f"Expected 8+ graphs, got {len(graphs)}"


def test_model_conforms_to_seam_shapes(model):
    conforms, _, report = pyshacl.validate(model, shacl_graph=str(SHAPES_FILE), inference="none")
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
    conforms, _, _ = pyshacl.validate(bad, shacl_graph=str(SHAPES_FILE), inference="none")
    assert not conforms, "shapes accepted a Model without notation and a ServiceTask with seam:decidedBy"


def test_every_nonreserved_seam_predicate_is_exercised(dataset):
    """Verify all declared seam predicates appear in a fixture model. The chat app
    counts too: its LLM call is the cross-container operation that exercises
    seam:implementedBy (ADR-0012); checkout and the human-task fixture serve every
    operation in-process."""
    declared = {
        p for p in load(ROOT / "ontology" / "seam.ttl").subjects(RDF.type, RDF.Property) if str(p).startswith(str(SEAM))
    }
    missing = declared - RESERVED_PREDICATES - PENDING_PREDICATES - exercised_seam_predicates(dataset)
    assert not missing, (
        "seam predicates never exercised by checkout.trig, the human-task fixture, the chat app "
        f"or expense chapter 9: {sorted(missing)}"
    )


def test_pending_predicates_are_not_yet_exercised(dataset):
    """A pending predicate that a fixture now uses must leave PENDING_PREDICATES, so the
    check above covers it."""
    assert not PENDING_PREDICATES & exercised_seam_predicates(dataset)


def exercised_seam_predicates(dataset) -> set:
    used = set()
    for _s, p, _o, _g in dataset.quads((None, None, None, None)):
        if str(p).startswith(str(SEAM)):
            used.add(p)
    for trig in (HUMAN_TASK_TRIG, CHAT_APP_TRIG, EXPENSES_CHAPTER_9_TRIG):
        fixture = rdflib.Dataset()
        fixture.parse(trig, format="trig")
        for _s, p, _o, _g in fixture.quads((None, None, None, None)):
            if str(p).startswith(str(SEAM)):
                used.add(p)
    return used


def test_what_writes_shape(model):
    """The flagship traversal: UI event -> process -> tasks -> shape, including
    the async hop through the order.events channel into fulfillment."""
    rows = model.query(canned("what-writes-shape.rq"), initBindings={"shape": SHOP.OrderShape})
    assert {(r.event, r.writer) for r in rows} == {
        (SHOP.submit_order, PERSIST_TASK),
        (SHOP.submit_order, FULFILL_TASK),
    }


def test_impact_of_node(model):
    """'What breaks if db01 goes away' — must reach containers, processes AND
    the data stored on it, and must NOT depend on deploy:dependsOn (startup ordering)."""
    rows = model.query(canned("impact-of-node.rq"), initBindings={"node": SHOP.db01})
    assert {r.impacted for r in rows} == {
        SHOP.order_db,
        SHOP.order_api,
        SHOP.web_ui,
        SHOP.order_process,
        SHOP.fulfillment_process,
        SHOP.OrderShape,
    }


def test_what_moves_state(model):
    """Which tasks may move an Order out of 'submitted'? t_cancel has no firing
    task on purpose — that absence is an M2 model-health warning, not an error."""
    rows = model.query(canned("what-moves-state.rq"), initBindings={"state": SHOP.s_submitted})
    assert {(r.task, r.transition, r.toState) for r in rows} == {
        (FULFILL_TASK, SHOP.t_fulfill, SHOP.s_fulfilled),
    }


# --- Named-graph verification (ADR-0001) ---

SEAMS_GRAPH = URIRef("urn:seams:graph:seams")


def _leaked_seam_quads(ds: rdflib.Dataset) -> list[tuple]:
    """Quads using a seam: predicate outside the seams graph.

    seam:inModel is allowed in model graphs. seam:reveal annotates the seam
    predicates themselves (ADR-0005 as amended), so it is allowed in the default
    graph, where the ontology files load.
    """
    allowed_in_model_graphs = {SEAM.inModel}
    leaked = []
    for s, p, o, ctx in ds.quads((None, None, None, None)):
        graph_id = ctx.identifier if hasattr(ctx, "identifier") else ctx
        if p == SEAM.reveal and str(graph_id) == "urn:x-rdflib:default":
            continue
        if str(p).startswith(str(SEAM)) and p not in allowed_in_model_graphs:
            if graph_id != SEAMS_GRAPH:
                leaked.append((graph_id, s, p, o))
    return leaked


def test_seam_predicates_isolated_to_seams_graph(dataset):
    """Cross-layer seam predicates must only appear in the seams graph.

    seam:inModel is the sole seam predicate allowed in model graphs (it anchors
    resources to their owning model). Every other seam: predicate must live in
    the dedicated seams graph per ADR-0001.
    """
    leaked = _leaked_seam_quads(dataset)
    assert not leaked, "seam predicates leaked into model graphs:\n" + "\n".join(
        f"  {g}: {s} {p} {o}" for g, s, p, o in leaked
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
    trig_ground, trig_bnode_count = _ground_triples(ds.quads((None, None, None, None)))

    missing = flat_ground - trig_ground
    assert not missing, f"{len(missing)} ground triples in checkout.ttl missing from checkout.trig:\n" + "\n".join(
        f"  {s} {p} {o}" for s, p, o in sorted(missing, key=str)
    )
    assert len(trig_ground) >= len(flat_ground), (
        f"TriG ground triples ({len(trig_ground)}) fewer than flat Turtle ({len(flat_ground)})"
    )
    assert trig_bnode_count >= flat_bnode_count, (
        f"TriG bnode triples ({trig_bnode_count}) fewer than flat Turtle ({flat_bnode_count})"
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
    graph_ids = {g.identifier for g in ds.graphs() if str(g.identifier) != "urn:x-rdflib:default"}
    assert len(graph_ids) == 6, f"Expected 6 named graphs, got {len(graph_ids)}: {graph_ids}"


def test_chat_app_conforms_to_seam_shapes(chat_model):
    conforms, _, report = pyshacl.validate(chat_model, shacl_graph=str(SHAPES_FILE), inference="none")
    assert conforms, report


def test_chat_app_seam_predicates_isolated(chat_dataset):
    """Cross-layer seam predicates in chat-app must only appear in the seams graph."""
    leaked = _leaked_seam_quads(chat_dataset)
    assert not leaked, "seam predicates leaked into model graphs:\n" + "\n".join(
        f"  {g}: {s} {p} {o}" for g, s, p, o in leaked
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


def test_chat_app_screens_by_role_writing_shape(chat_model):
    """Authenticated users reach MessageShape from the chat page's send_message,
    governed through the operation it submits to."""
    rows = chat_model.query(
        canned("screens-by-role-writing-shape.rq"),
        initBindings={"shape": CHAT.MessageShape},
    )
    assert {(r.role, r.screen, r.event, r.writer) for r in rows} == {
        (CHAT.authenticated_user, CHAT.chat_page, CHAT.send_message, CHAT_PERSIST_USER_MSG),
        (CHAT.authenticated_user, CHAT.chat_page, CHAT.send_message, CHAT_PERSIST_RESPONSE),
    }


def test_chat_app_impact_of_node(chat_model):
    """'What breaks if db01 goes away' — must reach message_db, chat_api, chat_ui,
    the send_message_process, and the shapes stored in message_db (ADR-0011)."""
    rows = chat_model.query(canned("impact-of-node.rq"), initBindings={"node": CHAT.db01})
    assert {r.impacted for r in rows} == {
        CHAT.message_db,
        CHAT.chat_api,
        CHAT.chat_ui,
        CHAT.send_message_process,
        CHAT.MessageShape,
        CHAT.ConversationShape,
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


# --- C4 L1 rollup projection query (ADR-0008) ---

ARCH = Namespace("https://w3id.org/seams/arch#")


def _rollup_rows(graph: rdflib.Graph) -> set[tuple]:
    return {(r["from"], r.to, r.kind) for r in graph.query(canned("c4-l1-rollup.rq"))}


def test_chat_app_c4_l1_rollup(chat_model):
    """Chat app has one system and one environment: the only rolled-up edge is
    'deployed to'. Container dependsOn edges stay inside chat_system, so they
    produce no 'depends on' self-edge."""
    assert _rollup_rows(chat_model) == {
        (CHAT.chat_system, CHAT.prod, Literal("deployed to")),
    }


def test_checkout_c4_l1_rollup(model):
    """Checkout: shop's containers deploy to web01/app01/db01, all in :prod."""
    assert _rollup_rows(model) == {
        (SHOP.shop, SHOP.prod, Literal("deployed to")),
    }


def test_c4_l1_rollup_depends_on_branch():
    """A dependsOn between containers of different systems rolls up to a
    system edge; one between containers of the same system does not."""
    ex = Namespace("https://example.org/rollup/")
    g = rdflib.Graph()
    for system, parts in ((ex.sysA, (ex.a1, ex.a2)), (ex.sysB, (ex.b1,))):
        g.add((system, RDF.type, ARCH.System))
        for part in parts:
            g.add((part, RDF.type, ARCH.Container))
            g.add((system, ARCH.contains, part))
    g.add((ex.a1, ARCH.dependsOn, ex.b1))
    g.add((ex.a1, ARCH.dependsOn, ex.a2))  # intra-system: must not roll up

    rows = _rollup_rows(g)
    assert rows == {(ex.sysA, ex.sysB, Literal("depends on"))}
    assert not any(frm == to for frm, to, _ in rows)


# --- Human tasks (ADR-0009) ---

EXPENSES = Namespace("https://example.org/expenses/")


def test_human_task_screens_to_finish_process():
    """The approval process waits on one screen: the approvals page holding the
    form its user task seam:completedOn, governed by the manager policy."""
    g = load(*ONTOLOGY_FILES)
    ds = rdflib.Dataset()
    ds.parse(HUMAN_TASK_TRIG, format="trig")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    rows = g.query(
        canned("screens-to-finish-process.rq"),
        initBindings={"process": EXPENSES.approval_process},
    )
    assert {(r.task, r.form, r.screen, r.policy) for r in rows} == {
        (
            URIRef("https://example.org/expenses/approval_bpmn#approve_expense"),
            EXPENSES.approve_form,
            EXPENSES.approvals_page,
            EXPENSES.manager_approval_policy,
        ),
    }


def test_chat_app_has_no_screens_to_finish(chat_model):
    """The chat app's process has no user task, so no screen waits for a person."""
    assert list(chat_model.query(canned("screens-to-finish-process.rq"))) == []


APPROVAL_PERSIST_EXPENSE = URIRef("https://example.org/expenses/approval_bpmn#persist_expense")
APPROVAL_APPROVE_EXPENSE = URIRef("https://example.org/expenses/approval_bpmn#approve_expense")
SCREENS_BY_ROLE_SUBMIT_POLICY = (EXPENSES.submit_expense, SEAM.governedBy, EXPENSES.employee_submit_policy)


def _human_task_model() -> rdflib.Graph:
    g = load(*ONTOLOGY_FILES)
    ds = rdflib.Dataset()
    ds.parse(HUMAN_TASK_TRIG, format="trig")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def _screens_by_role(g: rdflib.Graph, shape: URIRef) -> set:
    rows = g.query(canned("screens-by-role-writing-shape.rq"), initBindings={"shape": shape})
    return {(r.role, r.screen, r.event, r.writer) for r in rows}


def test_human_task_screens_by_role_writing_shape():
    """Only the employee's Submit Expense, on the Expenses page, eventually writes
    either shape: submitting starts the process whose tasks write both. The
    manager's Submit Approval triggers nothing, so it reaches no writer."""
    g = _human_task_model()
    assert _screens_by_role(g, EXPENSES.ExpenseShape) == {
        (EXPENSES.employee, EXPENSES.submit_page, EXPENSES.submit_expense, APPROVAL_PERSIST_EXPENSE),
    }
    assert _screens_by_role(g, EXPENSES.ApprovalShape) == {
        (EXPENSES.employee, EXPENSES.submit_page, EXPENSES.submit_expense, APPROVAL_APPROVE_EXPENSE),
    }


def test_expenses_chapter_7_screens_by_role_writing_payment():
    """The tutorial's chapter 7 answer: the only screen an employee can use
    that eventually writes a Payment is the Expenses page's Submit Expense,
    whose process reaches finance's pay_expense task. Finance's own Submit
    Payment completes the task but triggers nothing, so it is no row."""
    g = load(*ONTOLOGY_FILES)
    ds = rdflib.Dataset()
    ds.parse(EXPENSES_CHAPTER_7_TRIG, format="trig")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    assert _screens_by_role(g, EXPENSES.PaymentShape) == {
        (
            EXPENSES.employee,
            EXPENSES.expenses_page,
            EXPENSES.submit_expense,
            URIRef("https://example.org/expenses/approval_bpmn#pay_expense"),
        ),
    }


def test_screens_by_role_via_operation_policy_only():
    """With the event's own seam:governedBy removed, the role still comes from
    the operation it seam:submitsTo."""
    g = _human_task_model()
    g.remove(SCREENS_BY_ROLE_SUBMIT_POLICY)
    assert _screens_by_role(g, EXPENSES.ExpenseShape) == {
        (EXPENSES.employee, EXPENSES.submit_page, EXPENSES.submit_expense, APPROVAL_PERSIST_EXPENSE),
    }


def test_screens_by_role_ungoverned_writer_has_no_role():
    """No model ships an ungoverned writing event, so drop both policy links in
    memory: the row survives with ?role unbound (open to any identity)."""
    g = _human_task_model()
    g.remove(SCREENS_BY_ROLE_SUBMIT_POLICY)
    g.remove((EXPENSES.submit_expense_op, SEAM.governedBy, EXPENSES.employee_submit_policy))
    assert _screens_by_role(g, EXPENSES.ExpenseShape) == {
        (None, EXPENSES.submit_page, EXPENSES.submit_expense, APPROVAL_PERSIST_EXPENSE),
    }


def test_screens_by_role_unrelated_shape_has_no_rows(chat_model):
    """A focus no event writes returns nothing, governed or not."""
    assert _screens_by_role(chat_model, CHAT.ConversationShape) == set()


# --- Expense tutorial chapter 8: storage (ADR-0011) ---

EXPENSES_CHAPTER_8_TRIG = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"


@pytest.fixture(scope="session")
def expenses_8_model() -> rdflib.Graph:
    """Union graph of the ontologies plus the chapter-08 expense checkpoint."""
    ds = load_dataset(*ONTOLOGY_FILES, trig_path=EXPENSES_CHAPTER_8_TRIG)
    g = rdflib.Graph()
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def test_expenses_chapter_8_conforms_to_seam_shapes(expenses_8_model):
    conforms, _, report = pyshacl.validate(expenses_8_model, shacl_graph=str(SHAPES_FILE), inference="none")
    assert conforms, report


def test_expenses_chapter_8_impact_of_node(expenses_8_model):
    """A second model declares its store under a different key (DATABASE_URL),
    and db01's impact still reaches the store, the API and portal above it,
    both processes the API runs and the three shapes stored in expense_db."""
    rows = expenses_8_model.query(canned("impact-of-node.rq"), initBindings={"node": EXPENSES.db01})
    assert {r.impacted for r in rows} == {
        EXPENSES.expense_db,
        EXPENSES.expense_api,
        EXPENSES.employee_portal,
        EXPENSES.approval_process,
        EXPENSES.payout_process,
        EXPENSES.ExpenseShape,
        EXPENSES.ApprovalShape,
        EXPENSES.PaymentShape,
    }


def test_expenses_chapter_8_impact_of_app_node_skips_the_shapes(expenses_8_model):
    """The shapes depend on the store, not on the API: losing app01 does not
    reach them, because nothing stored on app01 holds their rows."""
    rows = expenses_8_model.query(canned("impact-of-node.rq"), initBindings={"node": EXPENSES.app01})
    impacted = {r.impacted for r in rows}
    assert EXPENSES.expense_api in impacted
    assert not impacted & {EXPENSES.expense_db, EXPENSES.ExpenseShape, EXPENSES.ApprovalShape, EXPENSES.PaymentShape}
