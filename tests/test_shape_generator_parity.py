"""Shapes catch every generator fault (backlog K1, principle 5).

If a model passes ontology/shapes/seam-shapes.ttl, generation must succeed. So every
``raise GeneratorError`` in seams_gen is either

- a parity case in ``CASES``: a mutation of a conforming example that makes the
  generator raise with the expected subject and predicate, and that the shapes
  report as a violation on the expected focus node; or
- an entry in ``GENERATOR_ONLY``, with the reason the shapes do not state it.

The inventory tests count the raise sites per seams_gen module and fail when a site
has neither. A new raise needs a parity case or a generator-only entry.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest
from rdflib import OWL, RDF, RDFS, BNode, Dataset, Graph, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import ModelGraph  # noqa: E402

from seams_gen import ifmledit  # noqa: E402
from seams_gen.acceptance import extract_acceptance  # noqa: E402
from seams_gen.compose import compose_file_name, environments, extract_compose  # noqa: E402
from seams_gen.dockerfile import extract_dockerfile  # noqa: E402
from seams_gen.fastapi import extract_routes  # noqa: E402
from seams_gen.htmx import generate_pages  # noqa: E402
from seams_gen.jsonld import extract_jsonld  # noqa: E402
from seams_gen.mentalmodel import extract_mentalmodel  # noqa: E402
from seams_gen.smoke import extract_smoke  # noqa: E402
from seams_gen.stubs import extract_stubs  # noqa: E402
from seams_gen.testing import SHAPES_FILE, assert_shapes_catch, shape_violations  # noqa: E402
from seams_gen.tests import extract_tests  # noqa: E402

SEAMS_GEN = ROOT / "seams_gen"
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
CHAT_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
EXPENSES_TRIG = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"

SH = Namespace("http://www.w3.org/ns/shacl#")
ARCH = Namespace("https://w3id.org/seams/arch#")
COMM = Namespace("https://w3id.org/seams/comm#")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
PROC = Namespace("https://w3id.org/seams/proc#")
VERIFY = Namespace("https://w3id.org/seams/verify#")
IFML = Namespace("https://w3id.org/seams/ifml#")
SEAM = Namespace("https://w3id.org/seams/seam#")
STATE = Namespace("https://w3id.org/seams/state#")
CHAT = Namespace("https://example.org/chat/")
EXP = Namespace("https://example.org/expenses/")
APPROVAL = Namespace("https://example.org/expenses/approval_bpmn#")
PAYOUT = Namespace("https://example.org/expenses/payout_bpmn#")
OTHER = Namespace("https://example.org/other/")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")


class Site(NamedTuple):
    """One ``raise GeneratorError`` in seams_gen: its module, the innermost function
    around it, and its predicate argument as written. ``note`` tells apart two raises
    in one function with the same predicate."""

    module: str
    function: str
    predicate: str
    note: str = ""


# ── the model and the checks ────────────────────────────────────────────────


def _dataset(trig: Path) -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(trig), format="trig")
    return ds


def _graph(ds: Dataset, name: str) -> Graph:
    """The named graph ``urn:seams:graph:<name>`` (ADR-0001), which must exist."""
    iri = URIRef(f"urn:seams:graph:{name}")
    assert iri in {g.identifier for g in ds.graphs()}, iri
    return ds.graph(iri)


def _remove(graph: Graph, s, p, o=None) -> None:
    assert (s, p, o) in graph, (s, p, o)
    graph.remove((s, p, o))


def _replace(graph: Graph, s, p, o) -> None:
    _remove(graph, s, p)
    graph.add((s, p, o))


def _htmx(model) -> object:
    return generate_pages(model)


def _ifmledit(model) -> object:
    return ifmledit.generate(model)


def _compose(model) -> object:
    """The compose model of every environment, as generate_compose_environments
    builds them, with paths relative to the model's directory."""
    files = []
    for env in environments(model):
        compose_file_name(env)
        files.append(extract_compose(model, model.path.parent, env))
    return files


GENERATORS = {
    "htmx": _htmx,
    "ifmledit": _ifmledit,
    "fastapi": extract_routes,
    "tests": extract_tests,
    "smoke": extract_smoke,
    "compose": _compose,
    "dockerfile": extract_dockerfile,
    "stubs": extract_stubs,
    "acceptance": extract_acceptance,
    "jsonld": extract_jsonld,
}

# The generators only a case runs: neither example generates them as written (the
# chat app has no ontology model and chapter 9 states no owl:versionInfo), so a
# case's mutation states what they need besides its fault.
CASE_GENERATORS = GENERATORS | {"mentalmodel": extract_mentalmodel}


# ── parity cases ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Case:
    id: str
    site: Site
    trig: Path
    mutate: Callable[[Dataset], None]
    generator: str
    subject: URIRef
    predicate: URIRef
    focus: URIRef  # the shape result's focus node
    path: URIRef | None = None  # the shape result's path, when it has a plain one
    match: str = ""  # a part of the GeneratorError detail, to tell apart raises on one fact


def _chat_ifml(ds):
    return _graph(ds, "model:chat_ifml")


def _seams(ds):
    return _graph(ds, "seams")


def _exp_ifml(ds):
    return _graph(ds, "model:expense_ifml")


def _remove_subject(ds: Dataset, s) -> None:
    assert (s, None, None) in ds, s
    for g in ds.graphs():
        g.remove((s, None, None))


def _guard_state_outside_lifecycle(ds):
    _graph(ds, "model:message_lifecycle").add((CHAT.s_bogus, RDF.type, STATE.State))
    _seams(ds).add((CHAT.message_thread, SEAM.visibleWhen, CHAT.s_bogus))


def _details_without_reads(ds):
    _remove(_seams(ds), CHAT.message_thread, SEAM.reads)
    _remove(_seams(ds), CHAT.message_thread, SEAM.visibleWhen)


def _form_completes_two_tasks(ds):
    _replace(_seams(ds), APPROVAL.finance_approve_expense, SEAM.completedOn, EXP.approve_form)


def _item_swap_onto_a_form(ds):
    _replace(_chat_ifml(ds), CHAT.send_to_thread, IFML.target, CHAT.compose_form)
    _replace(_seams(ds), CHAT.send_message_op, SEAM.rendersComponent, CHAT.compose_form)


def _also_started_by(ds, container, event, process) -> None:
    """A second executed process ``process`` that ``event`` also seam:triggers."""
    g = _seams(ds)
    g.add((process, RDF.type, PROC.Process))
    g.add((container, SEAM.executes, process))
    g.add((event, SEAM.triggers, process))


def _completion_without_body(ds):
    _remove(_seams(ds), EXP.approve_expense_op, SEAM.acceptsShape)
    _remove(_seams(ds), EXP.approve_expense_op, COMM.requestMediaType)


def _permission(ds, policy):
    node = _seams(ds).value(policy, ODRL.permission)
    assert node is not None, policy
    return node


def _permission_without_target(ds):
    _remove(_seams(ds), _permission(ds, CHAT.user_send_policy), ODRL.target)


def _chat_arch(ds):
    return _graph(ds, "model:chat_architecture")


def _outsider(ds):
    """An arch:Container no arch:System contains."""
    _chat_arch(ds).add((CHAT.outsider, RDF.type, ARCH.Container))
    return CHAT.outsider


def _binding_with_key(ds, key: str):
    (node,) = _chat_arch(ds).subjects(DEPLOY.key, Literal(key))
    return node


def _add_binding(ds, container, node, key: str, *facts) -> None:
    """A shared binding ``node`` of ``container`` with deploy:key ``key`` and ``facts``."""
    g = _chat_arch(ds)
    config = g.value(container, DEPLOY.configuration)
    assert config is not None, container
    g.add((config, DEPLOY.binding, node))
    g.add((node, DEPLOY.key, Literal(key)))
    for p, o in facts:
        g.add((node, p, o))


def _system_without_containers(ds):
    _chat_arch(ds).remove((CHAT.chat_system, ARCH.contains, None))


def _service_of_outsider(ds):
    _replace(_chat_arch(ds), _binding_with_key(ds, "LLM_GATEWAY_URL"), DEPLOY.serviceOf, _outsider(ds))


def _second_port(ds, container):
    port = BNode()
    g = _chat_arch(ds)
    g.add((container, DEPLOY.port, port))
    g.add((port, RDF.type, DEPLOY.Port))
    g.add((port, DEPLOY.containerPort, Literal(9000)))


def _exp_data(ds):
    return _graph(ds, "model:expense_data")


def _notification_property(ds, path):
    """The sh:property node of :NotificationShape whose sh:path is ``path``."""
    g = _exp_data(ds)
    (node,) = [p for p in g.objects(EXP.NotificationShape, SH.property) if (p, SH.path, path) in g]
    return node


def _second_handler(ds, handler, shape):
    """A second operation returning ``shape``, seam:implementedBy a comm:PythonHandler ``handler``."""
    g = _seams(ds)
    g.add((EXP.second_op, RDF.type, HYDRA.Operation))
    g.add((EXP.second_op, RDFS.label, Literal("Second")))
    g.add((EXP.second_op, SEAM.returnsShape, shape))
    g.add((EXP.second_op, SEAM.implementedBy, EXP.second_impl))
    g.add((EXP.second_impl, RDF.type, COMM.PythonHandler))
    g.add((EXP.second_impl, COMM.handler, Literal(handler)))


def _expense_property(ds, path):
    """The sh:property node of :ExpenseShape whose sh:path is ``path``."""
    g = _exp_data(ds)
    (node,) = [p for p in g.objects(EXP.ExpenseShape, SH.property) if (p, SH.path, path) in g]
    return node


def _view_reads_two_shapes(ds):
    """Chapter 9's ontology gets the version a Mental Model needs, and :expense_list a second shape."""
    _graph(ds, "model:expense_ontology").add((EXP.expense_ontology, OWL.versionInfo, Literal("1.0.0")))
    _seams(ds).add((EXP.expense_list, SEAM.reads, EXP.PaymentShape))


def _same_named_shape(ds):
    """:NotificationShape's namesake in another namespace, returned by a second handler of the notify module."""
    other = OTHER.NotificationShape
    g = _exp_data(ds)
    field = BNode()
    g.add((other, RDF.type, SH.NodeShape))
    g.add((other, SEAM.inModel, EXP.expense_data))
    g.add((other, SH.property, field))
    g.add((field, SH.path, EXP.recipient))
    g.add((field, SH.datatype, XSD.string))
    _second_handler(ds, "notify.second", other)


BAD_KEY = BNode("bad_key_binding")
TWO_KINDS = BNode("two_kinds_binding")


CASES = [
    Case(
        "page-component-without-order",
        Site("htmx", "_extract_page", "IFML.order"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_ifml(ds), CHAT.message_thread, IFML.order),
        "htmx",
        CHAT.message_thread,
        IFML.order,
        CHAT.message_thread,
    ),
    Case(
        "no-landmark",
        Site("htmx", "_landmark", "IFML.isLandmark"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_ifml(ds), CHAT.chat_page, IFML.isLandmark),
        "htmx",
        CHAT.chat_ifml,
        IFML.isLandmark,
        CHAT.chat_ifml,
    ),
    Case(
        "page-outside-interaction-model",
        Site("htmx", "_interaction_model", "IFML.contains"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_ifml(ds), CHAT.chat_ifml, IFML.contains, CHAT.chat_page),
        "htmx",
        CHAT.chat_page,
        IFML.contains,
        CHAT.chat_page,
    ),
    Case(
        "model-without-presenter",
        Site("htmx", "_presenter", "SEAM.presents"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.chat_ui, SEAM.presents),
        "htmx",
        CHAT.chat_ifml,
        SEAM.presents,
        CHAT.chat_ifml,
    ),
    Case(
        "component-of-two-kinds",
        Site("htmx", "_component", "RDF.type"),
        CHAT_TRIG,
        lambda ds: _chat_ifml(ds).add((CHAT.message_thread, RDF.type, IFML.List)),
        "htmx",
        CHAT.message_thread,
        RDF.type,
        CHAT.message_thread,
    ),
    Case(
        "guard-without-reads",
        Site("htmx", "_component", "SEAM.reads", "visibleWhen"),
        CHAT_TRIG,
        lambda ds: _seams(ds).add((CHAT.compose_form, SEAM.visibleWhen, CHAT.s_complete)),
        "htmx",
        CHAT.compose_form,
        SEAM.reads,
        CHAT.compose_form,
        SEAM.reads,
        "seam:visibleWhen",
    ),
    Case(
        "guard-state-outside-lifecycle",
        Site("htmx", "_component", "STATE.hasState"),
        CHAT_TRIG,
        _guard_state_outside_lifecycle,
        "htmx",
        CHAT.message_lifecycle,
        STATE.hasState,
        CHAT.message_thread,
    ),
    Case(
        "list-without-reads",
        Site("htmx", "_component", "SEAM.reads", "List"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.conversation_list, SEAM.reads),
        "htmx",
        CHAT.conversation_list,
        SEAM.reads,
        CHAT.conversation_list,
        SEAM.reads,
        "ifml:List must read",
    ),
    Case(
        "list-without-event",
        Site("htmx", "_list_link", "IFML.hasEvent"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_ifml(ds), CHAT.conversation_list, IFML.hasEvent),
        "htmx",
        CHAT.conversation_list,
        IFML.hasEvent,
        CHAT.conversation_list,
        IFML.hasEvent,
        "an ifml:List has exactly one event",
    ),
    Case(
        "details-without-reads",
        Site("htmx", "_component", "SEAM.reads", "Details"),
        CHAT_TRIG,
        _details_without_reads,
        "htmx",
        CHAT.message_thread,
        SEAM.reads,
        CHAT.message_thread,
        SEAM.reads,
        "ifml:Details must read",
    ),
    Case(
        "form-without-writes",
        Site("htmx", "_component", "SEAM.writes"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.compose_form, SEAM.writes),
        "htmx",
        CHAT.compose_form,
        SEAM.writes,
        CHAT.compose_form,
        SEAM.writes,
    ),
    Case(
        "form-input-bound-off-shape",
        Site("htmx", "_component", "IFML.boundTo"),
        CHAT_TRIG,
        lambda ds: _replace(_chat_ifml(ds), CHAT.message_input, IFML.boundTo, CHAT.not_a_field),
        "htmx",
        CHAT.message_input,
        IFML.boundTo,
        CHAT.message_input,
    ),
    Case(
        "unknown-swap",
        Site("htmx", "_flow", "IFML.swap"),
        CHAT_TRIG,
        lambda ds: _replace(_chat_ifml(ds), CHAT.select_to_thread, IFML.swap, IFML.Merge),
        "htmx",
        CHAT.select_to_thread,
        IFML.swap,
        CHAT.select_to_thread,
        IFML.swap,
    ),
    Case(
        "list-event-without-navigation",
        Site("htmx", "_navigation", "IFML.source"),
        CHAT_TRIG,
        lambda ds: _remove_subject(ds, CHAT.select_to_thread),
        "htmx",
        CHAT.select_conversation,
        IFML.source,
        CHAT.select_conversation,
    ),
    Case(
        "list-target-without-get",
        Site("htmx", "_list_link", "SEAM.rendersComponent"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.message_thread_op, SEAM.rendersComponent),
        "htmx",
        CHAT.message_thread,
        SEAM.rendersComponent,
        CHAT.message_thread,
    ),
    Case(
        "form-without-submit",
        Site("htmx", "_submit", "SEAM.submitsTo"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.send_message, SEAM.submitsTo),
        "htmx",
        CHAT.send_message,
        SEAM.submitsTo,
        CHAT.compose_form,
    ),
    Case(
        "presenter-does-not-consume",
        Site("htmx", "_submit", "SEAM.consumes"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.chat_ui, SEAM.consumes, CHAT.send_message_op),
        "htmx",
        CHAT.chat_ui,
        SEAM.consumes,
        CHAT.send_message,
    ),
    Case(
        "form-completes-two-tasks",
        Site("htmx", "_task_forms", "SEAM.completedOn"),
        EXPENSES_TRIG,
        _form_completes_two_tasks,
        "htmx",
        EXP.approve_form,
        SEAM.completedOn,
        EXP.approve_form,
    ),
    Case(
        "task-completed-on-a-details",
        Site("htmx", "_task_form", "SEAM.completedOn"),
        EXPENSES_TRIG,
        lambda ds: _replace(_seams(ds), APPROVAL.pay_expense, SEAM.completedOn, EXP.expense_details),
        "htmx",
        APPROVAL.pay_expense,
        SEAM.completedOn,
        APPROVAL.pay_expense,
        SEAM.completedOn,
    ),
    Case(
        "task-form-input-bound-off-shape",
        Site("htmx", "_task_form", "IFML.boundTo"),
        EXPENSES_TRIG,
        lambda ds: _replace(_exp_ifml(ds), EXP.decision_input, IFML.boundTo, EXP.not_a_field),
        "htmx",
        EXP.decision_input,
        IFML.boundTo,
        EXP.decision_input,
    ),
    Case(
        "item-swap-onto-a-form",
        Site("fragments", "fragment_for", "RDF.type"),
        CHAT_TRIG,
        _item_swap_onto_a_form,
        "htmx",
        CHAT.compose_form,
        RDF.type,
        CHAT.send_to_thread,
    ),
    Case(
        "ifmledit-component-of-two-kinds",
        Site("ifmledit", "extract_ifmledit", "RDF.type", "component kind"),
        CHAT_TRIG,
        lambda ds: _chat_ifml(ds).add((CHAT.message_thread, RDF.type, IFML.List)),
        "ifmledit",
        CHAT.message_thread,
        RDF.type,
        CHAT.message_thread,
    ),
    Case(
        "ifmledit-event-without-owner",
        Site("ifmledit", "extract_ifmledit", "IFML.hasEvent"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_ifml(ds), CHAT.compose_form, IFML.hasEvent, CHAT.send_message),
        "ifmledit",
        CHAT.send_message,
        IFML.hasEvent,
        CHAT.send_message,
    ),
    Case(
        "ifmledit-flow-to-a-non-ifml-element",
        Site("ifmledit", "extract_ifmledit", "predicate"),
        CHAT_TRIG,
        lambda ds: _replace(_chat_ifml(ds), CHAT.select_to_thread, IFML.target, CHAT.message_thread_op),
        "ifmledit",
        CHAT.select_to_thread,
        IFML.target,
        CHAT.select_to_thread,
        IFML.target,
    ),
    Case(
        "serving-container-in-no-system",
        Site("fastapi", "_module", "ARCH.contains"),
        CHAT_TRIG,
        lambda ds: _remove(_graph(ds, "model:chat_architecture"), CHAT.chat_system, ARCH.contains, CHAT.chat_api),
        "fastapi",
        CHAT.chat_api,
        ARCH.contains,
        CHAT.chat_api,
    ),
    Case(
        "executes-a-non-process",
        Site("fastapi", "_triggered", "RDF.type"),
        CHAT_TRIG,
        lambda ds: _replace(_seams(ds), CHAT.chat_api, SEAM.executes, CHAT.chat_bpmn),
        "fastapi",
        CHAT.chat_bpmn,
        RDF.type,
        CHAT.chat_api,
        SEAM.executes,
    ),
    Case(
        "executed-process-without-a-model",
        Site("fastapi", "_triggered", "SEAM.subscribesTo", "no model"),
        EXPENSES_TRIG,
        lambda ds: _remove(_seams(ds), EXP.payout_process, SEAM.detailedBy),
        "fastapi",
        EXP.payout_process,
        SEAM.subscribesTo,
        EXP.payout_process,
        SEAM.detailedBy,
        "BPMN model",
    ),
    Case(
        "executed-process-never-started",
        Site("fastapi", "_triggered", "SEAM.triggers"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.send_message, SEAM.triggers),
        "fastapi",
        CHAT.send_message_process,
        SEAM.triggers,
        CHAT.send_message_process,
    ),
    Case(
        "route-starts-two-processes",
        Site("fastapi", "_triggered", "SEAM.submitsTo"),
        CHAT_TRIG,
        lambda ds: _also_started_by(ds, CHAT.chat_api, CHAT.send_message, CHAT.audit_process),
        "fastapi",
        CHAT.send_message_op,
        SEAM.submitsTo,
        CHAT.send_message_op,
    ),
    Case(
        "exposes-a-non-endpoint",
        Site("fastapi", "_endpoint", "RDF.type"),
        CHAT_TRIG,
        lambda ds: _seams(ds).add((CHAT.chat_api, SEAM.exposes, CHAT.chat_page)),
        "fastapi",
        CHAT.chat_page,
        RDF.type,
        CHAT.chat_api,
        SEAM.exposes,
    ),
    Case(
        "unknown-method",
        Site("fastapi", "_operation", "HYDRA.method"),
        CHAT_TRIG,
        lambda ds: _replace(_seams(ds), CHAT.list_conversations_op, HYDRA.method, Literal("FETCH")),
        "fastapi",
        CHAT.list_conversations_op,
        HYDRA.method,
        CHAT.list_conversations_op,
        HYDRA.method,
    ),
    Case(
        "accepted-shape-without-request-body",
        Site("fastapi", "_operation", "COMM.requestMediaType", "acceptsShape"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.send_message_op, COMM.requestMediaType),
        "fastapi",
        CHAT.send_message_op,
        COMM.requestMediaType,
        CHAT.send_message_op,
        match="seam:acceptsShape needs a request body",
    ),
    Case(
        "completion-without-request-body",
        Site("fastapi", "_operation", "COMM.requestMediaType", "completion"),
        EXPENSES_TRIG,
        _completion_without_body,
        "fastapi",
        EXP.approve_expense_op,
        COMM.requestMediaType,
        EXP.approve_expense_op,
        match="completing",
    ),
    Case(
        "route-completes-and-starts",
        Site("fastapi", "_operation", "SEAM.submitsTo"),
        EXPENSES_TRIG,
        lambda ds: _also_started_by(ds, EXP.expense_api, EXP.submit_approval, EXP.review_process),
        "fastapi",
        EXP.approve_expense_op,
        SEAM.submitsTo,
        EXP.approve_expense_op,
    ),
    Case(
        "start-without-accepted-shape",
        Site("fastapi", "_operation", "SEAM.acceptsShape"),
        CHAT_TRIG,
        lambda ds: _remove(_seams(ds), CHAT.send_message_op, SEAM.acceptsShape),
        "fastapi",
        CHAT.send_message_op,
        SEAM.acceptsShape,
        CHAT.send_message_op,
    ),
    Case(
        "item-route-returns-another-shape",
        Site("fastapi", "_operation", "SEAM.returnsShape", "item"),
        CHAT_TRIG,
        lambda ds: _replace(_seams(ds), CHAT.send_message_op, SEAM.returnsShape, CHAT.ConversationShape),
        "fastapi",
        CHAT.send_message_op,
        SEAM.returnsShape,
        CHAT.send_message_op,
        match="item partial",
    ),
    Case(
        "component-route-without-a-query",
        Site("fastapi", "_operation", "SEAM.returnsShape", "component"),
        CHAT_TRIG,
        lambda ds: _replace(_chat_ifml(ds), CHAT.send_to_thread, IFML.swap, IFML.Replace),
        "fastapi",
        CHAT.send_message_op,
        SEAM.returnsShape,
        CHAT.send_message_op,
        match="component partial",
    ),
    Case(
        "route-completes-two-tasks",
        Site("fastapi", "_completed_task", "SEAM.submitsTo"),
        EXPENSES_TRIG,
        lambda ds: _replace(_seams(ds), EXP.submit_finance_approval, SEAM.submitsTo, EXP.approve_expense_op),
        "fastapi",
        EXP.approve_expense_op,
        SEAM.submitsTo,
        EXP.approve_expense_op,
    ),
    # _submits also checks that a step's or a permission's form submits to one
    # operation; seamsh:FormWritesShape states that for every form.
    Case(
        "scenario-process-not-started-by-a-route",
        Site("tests", "_submits", "predicate"),
        EXPENSES_TRIG,
        lambda ds: _remove(_seams(ds), EXP.submit_expense, SEAM.triggers),
        "tests",
        EXP.approval_process,
        SEAM.triggers,
        EXP.auto_approved,
        match="starting",
    ),
    Case(
        "scenario-without-an-expectation",
        Site("tests", "_scenario", "VERIFY.expectState"),
        EXPENSES_TRIG,
        lambda ds: _remove(_seams(ds), EXP.auto_approved, VERIFY.expectState),
        "tests",
        EXP.auto_approved,
        VERIFY.expectState,
        EXP.auto_approved,
    ),
    Case(
        "decision-example-without-an-output",
        Site("tests", "_decision_example", "VERIFY.expectOutput"),
        EXPENSES_TRIG,
        lambda ds: _remove(_seams(ds), EXP.routes_up_to_100_automatically, VERIFY.expectOutput),
        "tests",
        EXP.routes_up_to_100_automatically,
        VERIFY.expectOutput,
        EXP.routes_up_to_100_automatically,
        VERIFY.expectOutput,
    ),
    Case(
        "permission-target-not-a-request",
        Site("tests", "target_operation", "ODRL.target"),
        CHAT_TRIG,
        lambda ds: _replace(_seams(ds), _permission(ds, CHAT.user_send_policy), ODRL.target, CHAT.chat_page),
        "tests",
        CHAT.user_send_policy,
        ODRL.target,
        CHAT.user_send_policy,
    ),
    Case(
        "permission-without-a-target",
        Site("tests", "_permission_target", "ODRL.target"),
        CHAT_TRIG,
        _permission_without_target,
        "tests",
        CHAT.user_send_policy,
        ODRL.target,
        CHAT.user_send_policy,
        ODRL.permission,
    ),
    Case(
        "smoke-permission-without-a-target",
        Site("smoke", "_grants", "ODRL.target"),
        CHAT_TRIG,
        _permission_without_target,
        "smoke",
        CHAT.user_send_policy,
        ODRL.target,
        CHAT.user_send_policy,
        ODRL.permission,
    ),
    Case(
        "system-without-containers",
        Site("compose", "extract_compose", "ARCH.contains", "no container"),
        CHAT_TRIG,
        _system_without_containers,
        "compose",
        CHAT.chat_system,
        ARCH.contains,
        CHAT.chat_system,
        ARCH.contains,
    ),
    Case(
        "serving-container-without-a-port",
        Site("compose", "_single_port", "DEPLOY.port"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_arch(ds), CHAT.chat_api, DEPLOY.port),
        "compose",
        CHAT.chat_api,
        DEPLOY.port,
        CHAT.chat_api,
        match="/healthz",
    ),
    Case(
        "depends-on-outside-the-system",
        Site("compose", "_service", "DEPLOY.dependsOn"),
        CHAT_TRIG,
        lambda ds: _chat_arch(ds).add((CHAT.chat_ui, DEPLOY.dependsOn, _outsider(ds))),
        "compose",
        CHAT.chat_ui,
        DEPLOY.dependsOn,
        CHAT.chat_ui,
    ),
    Case(
        "proxies-outside-the-system",
        Site("compose", "_service", "DEPLOY.proxies"),
        CHAT_TRIG,
        lambda ds: _replace(_chat_arch(ds), CHAT.chat_ui, DEPLOY.proxies, _outsider(ds)),
        "compose",
        CHAT.chat_ui,
        DEPLOY.proxies,
        CHAT.chat_ui,
    ),
    Case(
        "placed-on-an-unlabelled-node",
        Site("compose", "_service", "RDFS.label"),
        CHAT_TRIG,
        lambda ds: _remove(_chat_arch(ds), CHAT.app01, RDFS.label),
        "compose",
        CHAT.app01,
        RDFS.label,
        CHAT.app01,
        RDFS.label,
    ),
    Case(
        "binding-key-not-an-env-name",
        Site("compose", "_bindings", "DEPLOY.key"),
        CHAT_TRIG,
        lambda ds: _add_binding(ds, CHAT.llm_gateway, BAD_KEY, "BAD-KEY", (DEPLOY.value, Literal("x"))),
        "compose",
        CHAT.llm_gateway,
        DEPLOY.key,
        BAD_KEY,
        DEPLOY.key,
    ),
    Case(
        "binding-key-bound-twice",
        Site("compose", "_bindings", "DEPLOY.binding", "twice"),
        CHAT_TRIG,
        lambda ds: _add_binding(ds, CHAT.llm_gateway, BNode(), "UPSTREAM_BASE_URL", (DEPLOY.value, Literal("x"))),
        "compose",
        CHAT.llm_gateway,
        DEPLOY.binding,
        CHAT.llm_gateway,
        match="bound twice",
    ),
    Case(
        "binding-with-two-kinds",
        Site("compose", "_bindings", "DEPLOY.binding", "kinds"),
        CHAT_TRIG,
        lambda ds: _add_binding(
            ds,
            CHAT.llm_gateway,
            TWO_KINDS,
            "TWO_KINDS",
            (DEPLOY.value, Literal("x")),
            (DEPLOY.secretFile, Literal("../../.secrets/x")),
        ),
        "compose",
        CHAT.llm_gateway,
        DEPLOY.binding,
        TWO_KINDS,
        match="exactly one of",
    ),
    Case(
        "service-of-outside-the-system",
        Site("compose", "_bindings", "DEPLOY.serviceOf"),
        CHAT_TRIG,
        _service_of_outsider,
        "compose",
        CHAT.chat_api,
        DEPLOY.serviceOf,
        CHAT.chat_api,
    ),
    Case(
        "service-of-a-container-with-two-ports",
        Site("compose", "_bindings", "DEPLOY.port"),
        CHAT_TRIG,
        lambda ds: _second_port(ds, CHAT.llm_gateway),
        "compose",
        CHAT.llm_gateway,
        DEPLOY.port,
        CHAT.llm_gateway,
        DEPLOY.port,
    ),
    Case(
        "handler-shape-field-without-a-python-type",
        Site("stubs", "_stub_class", "SH.datatype"),
        EXPENSES_TRIG,
        lambda ds: _replace(_exp_data(ds), _notification_property(ds, EXP.message), SH.datatype, XSD.anyURI),
        "stubs",
        EXP.NotificationShape,
        SH.datatype,
        EXP.NotificationShape,
    ),
    Case(
        "handler-shape-key-is-a-keyword",
        Site("stubs", "_identifier", "predicate"),
        EXPENSES_TRIG,
        lambda ds: _replace(_exp_data(ds), _notification_property(ds, EXP.message), SH.path, EXP["class"]),
        "stubs",
        EXP.NotificationShape,
        SH.path,
        EXP.NotificationShape,
        match="not a Python identifier",
    ),
    Case(
        "handler-shape-keys-collide",
        Site("stubs", "_stub_class", "SH.path"),
        EXPENSES_TRIG,
        lambda ds: _replace(_exp_data(ds), _notification_property(ds, EXP.message), SH.path, COMM.recipient),
        "stubs",
        EXP.NotificationShape,
        SH.path,
        EXP.NotificationShape,
    ),
    Case(
        "handler-module-shapes-share-a-local-name",
        Site("stubs", "_module", "RDF.type", "share"),
        EXPENSES_TRIG,
        _same_named_shape,
        "stubs",
        EXP.NotificationShape,
        RDF.type,
        EXP.NotificationShape,
        match="share a local name",
    ),
    Case(
        "handler-shape-named-like-a-function",
        Site("stubs", "_module", "RDF.type", "function"),
        EXPENSES_TRIG,
        lambda ds: _replace(_seams(ds), EXP.notify_manager_impl, COMM.handler, Literal("notify.ExpenseShape")),
        "stubs",
        EXP.ExpenseShape,
        RDF.type,
        EXP.ExpenseShape,
        match="also a function",
    ),
    Case(
        "context-fields-share-a-name",
        Site("jsonld", "_unique_names", "SH.name"),
        EXPENSES_TRIG,
        lambda ds: _replace(_exp_data(ds), _expense_property(ds, EXP.description), SH.name, Literal("amount")),
        "jsonld",
        EXP.ExpenseShape,
        SH.name,
        EXP.ExpenseShape,
        match='both have the name "amount"',
    ),
    Case(
        "mental-model-view-reads-two-shapes",
        Site("mentalmodel", "_views", "SEAM.reads"),
        EXPENSES_TRIG,
        _view_reads_two_shapes,
        "mentalmodel",
        EXP.expense_list,
        SEAM.reads,
        EXP.expense_list,
        SEAM.reads,
        "a SemPKM view is a table of one shape's entities",
    ),
]


# ── conditions the shapes do not state ──────────────────────────────────────

_TEMPLATE = "it needs the variables of a comm:path hydra:template, which means parsing the template string"
_LIMIT = "a limit of this generator, not a fault of the model"
_NAMES = (
    "generated test names come from IRI local names, and two IRIs in different namespaces may share "
    "one in a valid model; a constraint of the generated module, not of the model"
)
_TRACE = (
    "the trace an executed diagram is drawn from is a runtime input (a JSON file or the SQLite store), not the model"
)
_GEN_TRACE = (
    "it checks the traced template render against the normal one (ADR-0019), a property of the "
    "templates and the rendered text, not of the model"
)
_HELPER = (
    "a generic helper: it raises for whatever fact its caller asks for, so the condition "
    "belongs to the calling site, not to this one"
)

GENERATOR_ONLY: dict[Site, str] = {
    Site("htmx", "_path_template", "HYDRA.mapping"): f"Every template variable has a hydra:mapping: {_TEMPLATE}.",
    Site("htmx", "fill_param", "IFML.hasParameter"): (
        f"A form's submit path variable names a page ifml:Parameter by its label: {_TEMPLATE}."
    ),
    Site("htmx", "_component", "SH.property"): (
        "Which datatype property a List shows depends on the identifiers its link uses, taken from the "
        f"GET operation's path and the hx-vals bindings: {_TEMPLATE}."
    ),
    Site("htmx", "_component", "SEAM.reads", "SSE"): (
        "Two SSE channels the presenting container consumes, both accepting the shape a Details reads, "
        "make the stream ambiguous. Stating it joins container, channel transport and component read shape "
        "across three layers for one rendering choice; left to the generator."
    ),
    Site("htmx", "_component", "SEAM.publishesTo"): (
        "The delta publisher of an SSE channel is picked by a rendering rule (the publisher that seam:invokes "
        "an operation, else the sole one); the shapes do not encode that tie-break."
    ),
    Site("htmx", "_list_link", "IFML.targetParameter"): (
        f"A binding's target parameter is a path variable of the GET operation: {_TEMPLATE}."
    ),
    Site("htmx", "fill_key", "PROC.correlationKey"): (
        f"Every path variable of a task completion is the process correlation key: {_TEMPLATE}."
    ),
    Site("htmx", "_task_form", "PROC.correlationKey"): (
        f"The correlation key is a path variable of the task completion: {_TEMPLATE}."
    ),
    Site("htmx", "_task_process", "SEAM.detailedBy"): (
        "Finding a task's process uses the IRI rule of ADR-0002 (<model>#<id>) as well as seam:inModel, "
        "then counts the processes seam:detailedBy that model; left to the generator."
    ),
    Site("htmx", "render_pages", "IFML.contains"): (
        "Two served pages rendering one partial differently is a comparison of rendered text across pages, "
        "not a graph condition."
    ),
    Site("_views", "only", "many.predicate"): f"only() is {_HELPER}.",
    Site("_views", "optional", "many.predicate"): f"optional() is {_HELPER}.",
    Site("_views", "required", "predicate"): f"required() is {_HELPER}.",
    Site("_views", "view_errors", "err.predicate"): (
        "view_errors() re-raises a seams view ResolutionError for the fact the view resolved; "
        "the condition belongs to the calling site."
    ),
    Site("ifmledit", "_ids", "RDF.type"): (
        "IFMLEdit ids are IRI local names. Two IRIs in different namespaces may share a local name in a "
        "valid model; this is a constraint of the export, not of the model."
    ),
    Site("ifmledit", "_parent", "IFML.contains"): (
        "IFMLEdit nests each element in one container, while a model may let two pages contain one "
        "component (the htmx generator renders it on both); a constraint of the export."
    ),
    Site("ifmledit", "extract_ifmledit", "RDF.type", "no interaction model"): (
        "A model without an IFML layer is valid (a process-only model); only this export needs one."
    ),
    Site("fastapi", "extract_routes", "SEAM.executes"): (
        "A model with no container serving routes is valid (a data, process-only or UI sketch model); "
        "only route generation needs one."
    ),
    Site("fastapi", "extract_route_module", "SEAM.executes"): (
        "Several serving containers are a valid architecture, and extract_routes renders a module for each. "
        "extract_route_module, behind route_module, which the CLI, the tests generator and seams_gen.sources use, takes one: "
        f"{_LIMIT}."
    ),
    Site("fastapi", "_triggered", "SEAM.subscribesTo", "several"): (
        "Whether a proc:MessageCatchEvent that seam:subscribesTo a channel is a start event is in the BPMN XML "
        "(bpmn:startEvent), not in the graph; an intermediate catch event subscribes the same way."
    ),
    Site("fastapi", "_channel", "COMM.transport"): (
        f"comm:WebSocket is a comm:Transport of the vocabulary, and the generator routes only comm:SSE: {_LIMIT}."
    ),
    Site(
        "fastapi", "_channel", "COMM.path"
    ): f"An SSE channel's path has exactly one variable, its scope: {_TEMPLATE}.",
    Site("fastapi", "_operation", "SEAM.mediaKind"): (
        f"seam:Data is a seam:MediaKind of the vocabulary, and the generator routes only seam:UIFragment: {_LIMIT}."
    ),
    Site("fastapi", "_operation", "COMM.requestMediaType", "unknown"): (
        "comm:requestMediaType takes any media type, and the generator decodes only "
        f"application/x-www-form-urlencoded and application/json bodies: {_LIMIT}."
    ),
    Site("fastapi", "_operation", "PROC.correlationKey", "completion"): (
        f"The correlation key is a path variable of the operation completing the task: {_TEMPLATE}."
    ),
    Site("fastapi", "_operation", "PROC.correlationKey", "start"): (
        f"The correlation key is a path variable of the operation starting the process: {_TEMPLATE}."
    ),
    Site("tests", "_unique", "predicate"): f"Two tests named alike: {_NAMES}.",
    Site("smoke", "extract_smoke", "HYDRA.Operation"): f"Two probes named alike: {_NAMES}.",
    Site("acceptance", "_unique", "COMM.handler"): f"Two acceptance files or tests named alike: {_NAMES}.",
    Site("sequence", "find_event", "'ifml:Event'"): (
        "The event is the command-line argument naming the diagram to derive; no or several matching events "
        "is a fault of the argument, not of the model."
    ),
    Site("storm", "find_process", "'proc:Process'", "unknown"): (
        "The process is the command-line argument naming the storm to derive; a name that matches no "
        "process or triggering event is a fault of the argument, not of the model."
    ),
    Site("storm", "find_process", "'proc:Process'", "ambiguous"): (
        "The argument is a local name that matches both a process and an event, or several of them; "
        "a full IRI names one, so this is a fault of the argument, not of the model."
    ),
    Site("storm", "find_process", "'seam:triggers'"): (
        "The argument names an ifml:Event that triggers no process; a valid model has events that start "
        "nothing, so naming one is a fault of the argument."
    ),
    Site("sequence", "add", "'proc:Process'"): (
        "The number of paths through a process is a property of its BPMN flow graph; MAX_PATHS bounds the "
        "diagrams derived, and a valid process may exceed it."
    ),
    Site("sequence", "read_trace", "'trace file'", "not JSON"): f"The trace file is not JSON: {_TRACE}.",
    Site("sequence", "read_trace", "'trace file'", "not a trace"): f"The trace file holds no trace: {_TRACE}.",
    Site("sequence", "read_trace", "'trace'", "no store"): f"No trace file and no SQLite store: {_TRACE}.",
    Site("sequence", "read_trace", "'trace'", "unreadable store"): f"The store cannot be read: {_TRACE}.",
    Site("sequence", "read_trace", "'trace'", "no row"): f"The store has no row for the instance: {_TRACE}.",
    Site("sequence", "read_trace", "'trace'", "no trace"): f"The checkpoint holds no trace: {_TRACE}.",
    Site("sequence", "_rows", "'trace'"): f"The trace is not a list of rows: {_TRACE}.",
    Site("trace", "_parse", "'trace'"): f"A trace span ends that never began: {_GEN_TRACE}.",
    Site("trace", "trace_template", "'trace'", "sentinel"): (
        f"A rendered line already holds a trace sentinel character: {_GEN_TRACE}."
    ),
    Site("trace", "trace_template", "'trace'", "differs"): (
        f"The traced render differs from the normal render: {_GEN_TRACE}."
    ),
    Site("trace", "trace_template", "'trace'", "no origin"): f"A rendered line has no template origin: {_GEN_TRACE}.",
    Site("compose", "environments", "RDF.type"): (
        "A model without an arch:Environment is valid (a model with no deployment layer); "
        "only compose generation needs one."
    ),
    Site("compose", "compose_file_name", "RDF.type"): (
        "A compose file is named after the environment's IRI local name, and a valid IRI may have a local "
        "name that is not a file stem; a constraint of the generated file name, not of the model."
    ),
    Site("compose", "_resolve_environment", "RDF.type"): (
        "The environment is the caller's argument (the CLI's --environment); naming one the model does not "
        "declare is a fault of the argument, not of the model."
    ),
    Site("compose", "extract_compose", "ARCH.contains", "one system"): (
        "A model without an arch:System is valid (no architecture layer), and several systems are valid "
        f"architecture; a compose file is the project of one system: {_LIMIT}."
    ),
    Site("compose", "_executing", "SEAM.executes"): (
        "Several serving containers are a valid architecture; the compose file mounts the model into one "
        f"(D026): {_LIMIT}."
    ),
    Site("compose", "_bindings", "kind"): (
        "Two bindings with one secret key (the deploy:key lower-cased) and different sources, in any "
        "containers of one environment. Stating it needs each container's bindings in that environment "
        "after ADR-0015's override merge, compared case-insensitively across containers; left to the generator."
    ),
    Site("compose", "extract_compose_environments", "RDF.type"): f"Two compose files named alike: {_NAMES}.",
    Site("dockerfile", "extract_dockerfile", "SEAM.executes"): (
        "A model with no container serving routes is valid; only the runtime image's Dockerfile needs one."
    ),
    Site("dockerfile", "extract_dockerfile", "DEPLOY.build"): (
        "A serving container whose development deploy:artifact pulls a published image is valid (compose "
        "pulls it); only the Dockerfile generator, run on its own, needs a deploy:build."
    ),
    Site("dockerfile", "extract_dockerfile", "DEPLOY.context"): (
        "Whether the build context holds the model's directory depends on resolving the deploy:context path "
        "against the model file's location on disk, not on the graph; backlog A11 covers the build paths."
    ),
    Site("dockerfile", "_read_pyproject", "DEPLOY.context"): (
        "The build context's root pyproject.toml and its workspace members' pyproject.toml files are files on "
        "disk beside the model, not facts in the graph; only the Dockerfile generator reads them (backlog A12)."
    ),
    Site("dockerfile", "_workspace_members", "DEPLOY.context", "no members"): (
        "The [tool.uv.workspace] members are read from the build context's root pyproject.toml on disk, not "
        "from the graph; only the Dockerfile generator needs them (backlog A12)."
    ),
    Site("dockerfile", "_workspace_members", "DEPLOY.context", "glob"): (
        "A uv workspace member written as a glob pattern is valid uv; the Dockerfile copies each member's "
        "files by literal path, so the generator cannot expand it, and the pattern is on disk, not in the "
        "graph (backlog A12)."
    ),
    Site("dockerfile", "extract_dockerfile", "DEPLOY.dockerfile"): (
        "The file the generator writes, <app dir>/generated/<route module>.Dockerfile, is relative to the "
        "deploy:context resolved against the model file's location on disk, not to anything in the graph; a "
        "deploy:build without a deploy:dockerfile is valid for a container whose image is built by hand "
        "(backlog A11)."
    ),
    Site("fastapi", "_contexts", "SH.targetClass"): (
        "A route path or handler name equal to /contexts/<shape>.jsonld or <shape name>_context is valid for "
        "every other generator; only the fastapi generator also routes a target-classed shape's JSON-LD "
        "context there (ADR-0024 sections 5 and 7)."
    ),
    Site("jsonld", "_class_term", "SH.targetClass"): (
        "A target class and a field with one local name are distinct IRIs in any valid model; only a JSON-LD "
        "context puts class and field names in one namespace of terms (ADR-0024 section 7)."
    ),
    Site("jsonld", "_unique_files", "SH.targetClass"): (
        "Two target-classed shapes in different namespaces may share a local name in a valid model; a context "
        f"file is named after it: {_NAMES}."
    ),
    Site("jsonld", "_check_label", "RDFS.label"): (
        "A category member's rdfs:label is free text for every other generator; only a JSON-LD term must be "
        "non-empty, not start with @ and contain no colon (ADR-0024 section 3)."
    ),
    Site("mentalmodel", "_ontology", "SEAM.notation", "none"): (
        "A model with no seam:Ontology model is valid (the chat app has none); only a Mental Model is "
        "written for one (ADR-0026 section 2)."
    ),
    Site("mentalmodel", "_ontology", "SEAM.notation", "several"): (
        "Several seam:Ontology models are valid; a Mental Model describes one ontology, and the generator does "
        f"not choose (ADR-0026 section 2): {_LIMIT}."
    ),
    Site("mentalmodel", "_model_id", "RDF.type"): (
        "Any IRI may name an ontology model; only SemPKM's modelId alphabet and length (^[a-z][a-z0-9-]*$, 2 to "
        "64 characters) constrain the local name it is encoded from (ADR-0026 section 4)."
    ),
    Site("mentalmodel", "_version", "OWL.versionInfo"): (
        "owl:versionInfo is optional OWL (the ontology's version is its owl:versionIRI); only a Mental Model "
        "needs one, and SemPKM needs it as MAJOR.MINOR.PATCH (ADR-0026 section 4)."
    ),
    Site("mentalmodel", "_name", "RDFS.label"): (
        "An ontology model's rdfs:label is optional and free text for every other generator; only a Mental "
        "Model's name needs exactly one of at most 200 characters (ADR-0026 section 4)."
    ),
    Site("mentalmodel", "_description", "RDFS.comment"): (
        "rdfs:comment is free documentation; only a Mental Model's description is at most one of at most 2000 "
        "characters (ADR-0026 section 4)."
    ),
    Site("mentalmodel", "_imports", "OWL.imports"): (
        "Any vendored gistCore version is a valid import (ADR-0022); only a SemPKM package, like a SemPKM "
        "store at runtime load, must state the 14.0.0 SemPKM bundles (ADR-0026 section 7)."
    ),
    Site("mentalmodel", "_archive", "RDF.type"): (
        "An ontology, shapes and IFML components in different namespaces may share a local name in a valid "
        f"model; a package node is named after it: {_NAMES}."
    ),
    Site("mentalmodel", "_views", "SH.targetClass"): (
        "An ifml:List or ifml:Details may read a shape without a sh:targetClass (a message shape) in a valid "
        "model; only a SemPKM view selects its entities by class (ADR-0026 section 8)."
    ),
    Site("mentalmodel", "_columns", "SH.name"): (
        "A field without sh:name takes its path's local name, which any IRI may make (a hyphen, a leading "
        "digit); the shapes check only a stated sh:name. Only a view's columns must be SPARQL variables "
        "(ADR-0026 section 8)."
    ),
    Site("protocol", "check_preconditions", "shape"): (
        "A generator's precondition check is the shapes themselves: it raises exactly when ontology/shapes "
        "reports a result of one of the generator's precondition shapes, so there is no condition left to state."
    ),
}


# ── tests ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("trig", [CHAT_TRIG, EXPENSES_TRIG], ids=lambda p: p.parent.name)
def test_unmutated_example_conforms_and_generates(trig):
    """The baseline: each case's violation and GeneratorError come from its mutation."""
    ds = _dataset(trig)
    assert shape_violations(ds, SHAPES_FILE, ONTOLOGY_FILES) == []
    for generate in GENERATORS.values():
        assert generate(ModelGraph(trig, dataset=ds))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_generator_fault_is_a_shape_violation(case: Case):
    ds = _dataset(case.trig)
    case.mutate(ds)

    assert_shapes_catch(
        CASE_GENERATORS[case.generator],
        ds,
        subject=case.subject,
        predicate=case.predicate,
        focus=case.focus,
        path=case.path,
        match=case.match,
        model_path=case.trig,
    )


def test_each_site_has_one_case_or_entry():
    sites = [c.site for c in CASES]
    assert len(sites) == len(set(sites)), Counter(sites).most_common(3)
    assert not set(sites) & set(GENERATOR_ONLY)
    assert all(reason.strip() for reason in GENERATOR_ONLY.values())


def _source(module: str) -> str:
    return (SEAMS_GEN / f"{module}.py").read_text()


def _raise_sites(module: str) -> Counter[tuple[str, str]]:
    """(innermost function, predicate argument as written) of each raise GeneratorError."""
    found: Counter[tuple[str, str]] = Counter()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            exc = child.exc if isinstance(child, ast.Raise) else None
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "GeneratorError":
                found[(function, ast.unparse(exc.args[1]))] += 1
            visit(child, name)

    visit(ast.parse(_source(module)), "<module>")
    return found


def _modules() -> list[str]:
    return sorted(p.stem for p in SEAMS_GEN.glob("*.py") if "raise GeneratorError" in p.read_text())


def _covered(module: str) -> list[Site]:
    return [s for s in [*(c.site for c in CASES), *GENERATOR_ONLY] if s.module == module]


def test_every_module_with_raises_is_inventoried():
    """A module with raise sites and no case or entry fails here, not silently."""
    assert set(_modules()) == {s.module for s in [*(c.site for c in CASES), *GENERATOR_ONLY]}


@pytest.mark.parametrize("module", _modules())
def test_inventory_matches_the_raise_sites(module):
    """One parity case or generator-only entry per raise site, no more and no fewer."""
    count = len(re.findall(r"\braise GeneratorError\b", _source(module)))
    covered = _covered(module)
    assert len(covered) == count, f"{module}: {count} raise sites, {len(covered)} cases and entries"
    assert Counter((s.function, s.predicate) for s in covered) == _raise_sites(module)
