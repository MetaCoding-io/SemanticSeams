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
from rdflib import RDF, Dataset, Graph, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import ModelGraph  # noqa: E402

from seams_gen import GeneratorError, ifmledit  # noqa: E402
from seams_gen.htmx import generate_pages  # noqa: E402

SEAMS_GEN = ROOT / "seams_gen"
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
CHAT_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
EXPENSES_TRIG = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"

SH = Namespace("http://www.w3.org/ns/shacl#")
IFML = Namespace("https://w3id.org/seams/ifml#")
SEAM = Namespace("https://w3id.org/seams/seam#")
STATE = Namespace("https://w3id.org/seams/state#")
CHAT = Namespace("https://example.org/chat/")
EXP = Namespace("https://example.org/expenses/")
APPROVAL = Namespace("https://example.org/expenses/approval_bpmn#")

# Modules whose raise sites a later task of M017/S01 covers. Their strict inventory
# waits for that task; test_pending_modules_are_not_yet_covered fails once one is
# covered, as the reminder to drop it from this map.
PENDING = {
    "fastapi": "T02",
    "tests": "T02",
    "smoke": "T02",
    "sequence": "T02",
    "compose": "T03",
    "dockerfile": "T03",
}


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


GENERATORS = {"htmx": _htmx, "ifmledit": _ifmledit}


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
]


# ── conditions the shapes do not state ──────────────────────────────────────

_TEMPLATE = "it needs the variables of a comm:path hydra:template, which means parsing the template string"
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
    Site("htmx", "generate_pages", "IFML.contains"): (
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
    assert set(_modules()) == {"htmx", "fragments", "_views", "ifmledit", *PENDING}


@pytest.mark.parametrize("module", [m for m in _modules() if m not in PENDING])
def test_inventory_matches_the_raise_sites(module):
    """One parity case or generator-only entry per raise site, no more and no fewer."""
    count = len(re.findall(r"\braise GeneratorError\b", _source(module)))
    covered = _covered(module)
    assert len(covered) == count, f"{module}: {count} raise sites, {len(covered)} cases and entries"
    assert Counter((s.function, s.predicate) for s in covered) == _raise_sites(module)


@pytest.mark.parametrize("module", sorted(PENDING))
def test_pending_modules_are_not_yet_covered(module):
    count = len(re.findall(r"\braise GeneratorError\b", _source(module)))
    assert len(_covered(module)) != count, f"{module} is covered: drop it from PENDING ({PENDING[module]})"
