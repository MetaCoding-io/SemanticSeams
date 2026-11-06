"""Chapter 11 of the expense tutorial: two bounded contexts (ADR-0030, E6).

examples/expenses/chapter-11 is chapter 10 split into an expense context
(expenses.trig) and a finance context (finance.trig), loaded together as one
dataset. These tests check the facts the chapter is about: two classified
domains and two contexts, every model graph owned by exactly one context (and
written in that context's file), the expense ontology importing the finance
ontology by version IRI from the dataset, and the Pay Expense task moved to
the payout process, so the approval storm writes no payment and the app pays
an expense in its payout instance.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import rdflib
import seams
from rdflib import OWL, RDF, Namespace, URIRef
from seams import ResolutionError, local_name

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from expense_app import PAYOUT_PROCESS, serve, status, until  # noqa: E402

from seams_gen.storm import derive  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"
EX = Namespace("https://example.org/expenses/")
SEAM = Namespace("https://w3id.org/seams/seam#")
ARCH = Namespace("https://w3id.org/seams/arch#")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
ARCHITECTURE_GRAPH = URIRef("urn:seams:graph:model:expense_architecture")
FINANCE_VERSION = URIRef("https://example.org/expenses/finance_ontology/1.0")
APPROVAL_PAY = URIRef(EX + "approval_bpmn#pay_expense")
PAYOUT_PAY = URIRef(EX + "payout_bpmn#pay_expense")
EXPENSE = {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"}
PAYMENT = {"reference": "PAY-1", "paid_on": "2026-10-05"}


@pytest.fixture(scope="module")
def model():
    return seams.load(CHAPTER)


@pytest.fixture(scope="module")
def seams_graph(model):
    return model.ds.graph(SEAMS_GRAPH)


def _models(model) -> dict[URIRef, URIRef]:
    """{model IRI: its seam:notation} for every model the seams graph names."""
    graph = model.ds.graph(SEAMS_GRAPH)
    return {s: o for s, o in graph.subject_objects(SEAM.notation) if isinstance(s, URIRef) and isinstance(o, URIRef)}


def _owned(seams_graph, context: URIRef) -> set[URIRef]:
    return {o for o in seams_graph.objects(context, SEAM.owns) if isinstance(o, URIRef)}


def test_the_model_is_the_directory():
    assert sorted(p.name for p in CHAPTER.glob("*.trig")) == ["expenses.trig", "finance.trig"]
    assert 'model = "."' in (CHAPTER / "seams.toml").read_text(encoding="utf-8")


def test_two_domains_each_with_one_classification(model):
    arch = model.ds.graph(ARCHITECTURE_GRAPH)
    domains = {d: set(arch.objects(d, ARCH.classification)) for d in arch.subjects(RDF.type, ARCH.Domain)}
    assert domains == {EX.expense_management: {ARCH.Supporting}, EX.finance: {ARCH.Core}}
    assert set(arch.objects(EX.expense_management, ARCH.contains)) == {EX.expense_system, EX.expense_context}
    assert set(arch.objects(EX.finance, ARCH.contains)) == {EX.finance_context}


def test_two_contexts_each_owning_one_ontology(model, seams_graph):
    arch = model.ds.graph(ARCHITECTURE_GRAPH)
    contexts = sorted(arch.subjects(RDF.type, ARCH.BoundedContext))
    assert contexts == [EX.expense_context, EX.finance_context]
    notations = _models(model)
    ontologies = {c: {m for m in _owned(seams_graph, c) if notations.get(m) == SEAM.Ontology} for c in contexts}
    assert ontologies == {EX.expense_context: {EX.expense_ontology}, EX.finance_context: {EX.finance_ontology}}


def test_every_model_but_the_architecture_has_exactly_one_owner(model, seams_graph):
    owners: dict[URIRef, list[URIRef]] = {}
    for context, owned in seams_graph.subject_objects(SEAM.owns):
        owners.setdefault(owned, []).append(context)
    for iri, notation in sorted(_models(model).items()):
        if notation == SEAM.C4:
            assert iri not in owners, f"{local_name(iri)} is the architecture model; no context owns it"
        else:
            assert len(owners.get(iri, [])) == 1, f"{local_name(iri)} has owners {owners.get(iri)}"


def test_expense_is_the_conformist_upstream_of_finance(model):
    arch = model.ds.graph(ARCHITECTURE_GRAPH)
    relationships = sorted(arch.subjects(RDF.type, ARCH.ContextRelationship))
    assert relationships == [EX.expense_to_finance]
    facts = {p: set(arch.objects(EX.expense_to_finance, p)) for p in (ARCH.upstream, ARCH.downstream)}
    assert facts == {ARCH.upstream: {EX.expense_context}, ARCH.downstream: {EX.finance_context}}
    assert set(arch.objects(EX.expense_to_finance, ARCH.relationshipType)) == {ARCH.Conformist}


def test_every_cross_context_access_runs_from_finance_to_expense(model, seams_graph):
    """The declared direction (ADR-0032 section 2) is the one the accesses run in."""
    owner = {owned: context for context, owned in seams_graph.subject_objects(SEAM.owns)}

    def context_of(element: URIRef) -> URIRef | None:
        models = set(model.ds.objects(element, SEAM.inModel))
        return next((owner[m] for m in models if m in owner), None)

    crossings: set[tuple[URIRef | None, URIRef | None]] = set()
    for predicate in (SEAM.reads, SEAM.writes):
        for element, shape in seams_graph.subject_objects(predicate):
            pair = (context_of(element), context_of(shape))
            if pair[0] != pair[1]:
                crossings.add(pair)
    assert crossings == {(EX.finance_context, EX.expense_context)}


@pytest.mark.parametrize(
    "file, context", [("expenses.trig", EX.expense_context), ("finance.trig", EX.finance_context)], ids=str
)
def test_each_file_holds_the_model_graphs_its_context_owns(file, context, seams_graph):
    ds = rdflib.Dataset()
    ds.parse(CHAPTER / file, format="trig")
    prefix = "urn:seams:graph:model:"
    graphs = {
        URIRef(EX + str(g.identifier).removeprefix(prefix))
        for g in ds.graphs()
        if str(g.identifier).startswith(prefix) and len(g) > 0
    }
    graphs.discard(EX.expense_architecture)
    assert graphs == _owned(seams_graph, context)


def test_the_expense_ontology_imports_the_finance_ontology_from_the_dataset(model):
    ontology = model.ds.graph(URIRef("urn:seams:graph:model:expense_ontology"))
    assert FINANCE_VERSION in set(ontology.objects(EX.expense_ontology, OWL.imports))
    assert [(d.ontology, d.version) for d in model.dataset_imports] == [(EX.finance_ontology, FINANCE_VERSION)]
    finance = model.ds.graph(URIRef("urn:seams:graph:model:finance_ontology"))
    assert set(finance.objects(EX.finance_ontology, OWL.versionIRI)) == {FINANCE_VERSION}


@pytest.mark.parametrize("cls", [EX.Payment, EX.Vendor], ids=local_name)
def test_payment_and_vendor_keep_their_iris_in_the_finance_ontology(model, cls):
    """ADR-0002: moving a class changes its seam:inModel, not its IRI."""
    finance = model.ds.graph(URIRef("urn:seams:graph:model:finance_ontology"))
    assert (cls, RDF.type, OWL.Class) in finance
    assert set(finance.objects(cls, SEAM.inModel)) == {EX.finance_ontology}
    expense = model.ds.graph(URIRef("urn:seams:graph:model:expense_ontology"))
    assert not set(expense.predicate_objects(cls))


def test_expenses_trig_alone_cannot_resolve_the_finance_import():
    """Without finance.trig the import names no ontology of the dataset."""
    with pytest.raises(ResolutionError) as raised:
        seams.load(CHAPTER / "expenses.trig")
    assert raised.value.subject == str(EX.expense_ontology)
    assert raised.value.predicate == str(OWL.imports)
    assert str(FINANCE_VERSION) in raised.value.detail


def test_a_finance_version_the_import_does_not_name_fails(tmp_path):
    copy = tmp_path / "chapter-11"
    shutil.copytree(CHAPTER, copy, ignore=shutil.ignore_patterns("generated", "__pycache__"))
    finance = copy / "finance.trig"
    text = finance.read_text(encoding="utf-8")
    assert text.count("finance_ontology/1.0>") == 1
    finance.write_text(text.replace("finance_ontology/1.0>", "finance_ontology/1.1>"), encoding="utf-8")
    with pytest.raises(ResolutionError) as raised:
        seams.load(copy)
    assert raised.value.subject == str(EX.expense_ontology)
    assert raised.value.predicate == str(OWL.imports)
    assert str(FINANCE_VERSION) in raised.value.detail
    assert "https://example.org/expenses/finance_ontology/1.1" in raised.value.detail


def test_pay_expense_is_a_task_of_the_payout_process(model, seams_graph):
    payout = model.ds.graph(URIRef("urn:seams:graph:model:payout_bpmn"))
    assert (PAYOUT_PAY, SEAM.inModel, EX.payout_bpmn) in payout
    assert set(seams_graph.objects(PAYOUT_PAY, SEAM.completedOn)) == {EX.payment_form}
    console = model.ds.graph(URIRef("urn:seams:graph:model:finance_console"))
    assert (EX.payment_form, SEAM.inModel, EX.finance_console) in console
    assert not list(model.ds.quads((APPROVAL_PAY, None, None, None)))
    assert not list(model.ds.quads((None, None, APPROVAL_PAY, None)))
    assert (CHAPTER / "approval.bpmn").read_text(encoding="utf-8").count("pay_expense") == 0


def test_the_approval_storm_writes_no_payment(model):
    storm = derive(model, "approval_process")
    assert EX.PaymentShape not in {e.iri for e in storm.aggregates}
    assert "pay_expense" not in {local_name(s.iri) for s in storm.steps}
    # the payouts channel is the one line out of the approval storm
    assert [e.iri for e in storm.channels] == [EX.payouts]
    assert [e.iri for e in storm.processes] == [URIRef(PAYOUT_PROCESS)]


def test_the_payout_storm_writes_the_payment_from_pay_expense(model):
    storm = derive(model, "payout_process")
    names = [local_name(s.iri) for s in storm.steps]
    assert names[:3] == ["payout_requested", "pay_expense", "schedule_payout"]
    pay_step = names.index("pay_expense") + 1
    assert (pay_step, EX.PaymentShape) in {(e.step, e.iri) for e in storm.aggregates}


def test_finance_pays_the_approved_expense_in_its_payout_instance(tmp_path, monkeypatch):
    with serve("chapter-11", tmp_path, monkeypatch) as (c, runtime):
        r = c.post("/expenses/e1", data=EXPENSE, headers={"X-Forwarded-User": "employee"})
        assert r.status_code == 200, r.text
        # up to 100 the table approves at once: the approval ends and hands over
        until(lambda: status(runtime, "e1") == "complete")
        until(lambda: status(runtime, "e1", PAYOUT_PROCESS) == "waiting")
        [task] = runtime.store.list_user_tasks()
        assert task["bpmn_id"] == "pay_expense" and task["correlation_key"] == "e1"
        assert runtime.query(":PaymentShape", expense="e1") == []

        # only finance pays (finance_payment_policy targets the payout task)
        r = c.post("/expenses/e1/payment", data=PAYMENT, headers={"X-Forwarded-User": "employee"})
        assert r.status_code == 403, r.text
        assert status(runtime, "e1", PAYOUT_PROCESS) == "waiting"

        r = c.post("/expenses/e1/payment", data=PAYMENT, headers={"X-Forwarded-User": "finance"})
        assert r.status_code == 200, r.text
        assert '<section id="payment_details"' in r.text and 'data-expense="e1"' in r.text
        until(lambda: status(runtime, "e1", PAYOUT_PROCESS) == "complete")
        [payment] = runtime.query(":PaymentShape", expense="e1")
        # 42.50 is at most 500, so the payout table batches it
        assert payment["data"]["reference"] == "PAY-1" and payment["status"] == "batched"
        [expense] = runtime.query(":ExpenseShape", expense="e1")
        assert expense["status"] == "approved"
        assert runtime.store.list_user_tasks() == []
