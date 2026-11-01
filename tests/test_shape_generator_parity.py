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
from functools import cache
from pathlib import Path
from typing import NamedTuple

import pyshacl
import pytest
from rdflib import RDF, RDFS, BNode, Dataset, Graph, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import ModelGraph  # noqa: E402

from seams_gen import GeneratorError, ifmledit  # noqa: E402
from seams_gen.compose import compose_file_name, environments, extract_compose  # noqa: E402
from seams_gen.dockerfile import extract_dockerfile  # noqa: E402
from seams_gen.fastapi import extract_routes  # noqa: E402
from seams_gen.htmx import generate_pages  # noqa: E402
from seams_gen.smoke import extract_smoke  # noqa: E402
from seams_gen.tests import extract_tests  # noqa: E402

SEAMS_GEN = ROOT / "seams_gen"
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
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


@cache
def _ontology() -> Graph:
    g = Graph()
    for path in ONTOLOGY_FILES:
        g.parse(path, format="turtle")
    return g


@cache
def _shapes() -> Graph:
    return Graph().parse(SHAPES_FILE, format="turtle")


def _violations(ds: Dataset) -> list[tuple[str, str | None, str]]:
    """(focus node, result path, message) of each shape result, validated the way
    `seams check` and the viewer do: the model unioned with ontology/*.ttl."""
    union = Graph()
    union += _ontology()
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    _conforms, results, _text = pyshacl.validate(union, shacl_graph=_shapes(), inference="none")
    out = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        path = results.value(r, SH.resultPath)
        out.append(
            (
                str(results.value(r, SH.focusNode)),
                str(path) if isinstance(path, URIRef) else None,
                str(results.value(r, SH.resultMessage) or ""),
            )
        )
    return out


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
}


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
    Site("sequence", "find_event", "'ifml:Event'"): (
        "The event is the command-line argument naming the diagram to derive; no or several matching events "
        "is a fault of the argument, not of the model."
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
}


# ── tests ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("trig", [CHAT_TRIG, EXPENSES_TRIG], ids=lambda p: p.parent.name)
def test_unmutated_example_conforms_and_generates(trig):
    """The baseline: each case's violation and GeneratorError come from its mutation."""
    ds = _dataset(trig)
    assert _violations(ds) == []
    for generate in GENERATORS.values():
        assert generate(ModelGraph(trig, dataset=ds))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_generator_fault_is_a_shape_violation(case: Case):
    ds = _dataset(case.trig)
    case.mutate(ds)

    with pytest.raises(GeneratorError) as err:
        GENERATORS[case.generator](ModelGraph(case.trig, dataset=ds))
    assert (err.value.subject, err.value.predicate) == (str(case.subject), str(case.predicate)), err.value
    assert case.match in err.value.detail

    violations = _violations(ds)
    found = [v for v in violations if v[0] == str(case.focus) and (case.path is None or v[1] == str(case.path))]
    assert found, f"no shape result on {case.focus} {case.path or ''}; results: {violations}"
    assert all(message for _f, _p, message in found), found


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
