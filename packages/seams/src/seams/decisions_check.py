"""Static checks for decisions (backlog K2): faults the runtime would hit.

``decision_findings(model)`` asks two questions and returns one
``DecisionFinding`` (subject IRI, fact, message) per fault, sorted:

- **typeRef against sh:datatype.** For each dec:Decision with a
  dec:payloadElement, every dec:input is matched to the decision table input
  whose inputExpression text is its dec:variable, as the engine matches them
  (``seams.dmn``). The sh:datatype of each sh:property whose sh:path is the
  input's dec:fromPath (on the shapes the decision seam:reads, else on every
  shape) must be one the typeRef accepts: ``number`` takes xsd:decimal,
  xsd:integer and its subtypes, xsd:double and xsd:float; ``string``
  xsd:string; ``boolean`` xsd:boolean; ``date`` xsd:date. An input with
  dec:measure dec:Length is a number whatever the datatype, so its typeRef
  must be ``number``. A missing typeRef, a typeRef outside that list, or a
  property without a datatype gives no finding. The subject is the
  decision, the fact the dec:fromPath property.
- **Gateway conditions read declared variables.** Spiff evaluates a
  conditionExpression as a Python expression over the task data, so each
  one is parsed with ``ast`` and every free name it reads (Python builtins
  aside) must be in the task data upstream of the flow. The engine and worker
  put three things there: each dec:output's dec:processVariable and each
  dec:input's dec:variable of the decision an upstream business-rule task is
  seam:decidedBy, and the field names of the shape an upstream user task
  writes (its seam:completedOn form's seam:writes, else its own), which
  ``complete_user_task`` merges in. Upstream means a node the flow's source
  is reachable from over sequence flows, the source included; a boundary
  event follows from what precedes the task it is attached to. The subject
  is the sequence flow's IRI (``<bpmn model>#<flow id>``), the fact the
  variable name, or the expression itself when it does not parse.

Neither question needs vocabulary beyond what the engine already reads
(principle 4), and both read the BPMN and DMN in their native XML
(principle 3). A decision or process whose payload file is missing is
skipped: there is no XML to check, and the missing payload is a fault of its
own that loading the payload reports. Any other ``ResolutionError`` met
while reading a decision or process becomes a finding naming its subject and predicate.

Sub-processes: sequence flows do not cross a bpmn:subProcess boundary, so a
condition inside one does not see variables set before the sub-process. No
example uses one.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import XSD, URIRef

from .bpmn import BpmnNode
from .errors import ResolutionError
from .namespaces import DEC, SEAM, local_name
from .views import Decision, FlowNode, Process, Shape

if TYPE_CHECKING:
    from .loader import Model

#: The sh:datatypes each DMN typeRef accepts.
TYPE_REF_DATATYPES: dict[str, frozenset[URIRef]] = {
    "number": frozenset(
        {
            XSD.decimal,
            XSD.integer,
            XSD.double,
            XSD.float,
            XSD.int,
            XSD.long,
            XSD.short,
            XSD.byte,
            XSD.nonNegativeInteger,
            XSD.positiveInteger,
            XSD.nonPositiveInteger,
            XSD.negativeInteger,
            XSD.unsignedLong,
            XSD.unsignedInt,
            XSD.unsignedShort,
            XSD.unsignedByte,
        }
    ),
    "string": frozenset({XSD.string}),
    "boolean": frozenset({XSD.boolean}),
    "date": frozenset({XSD.date}),
}

_BUILTINS = frozenset(dir(builtins))


@dataclass(frozen=True, order=True)
class DecisionFinding:
    """One decision fault: the decision or sequence flow IRI, the fact it is
    about (a dec:fromPath IRI, a variable name or an expression) and why."""

    subject: str
    fact: str
    message: str


def _missing_payload(err: ResolutionError) -> bool:
    return err.predicate == str(SEAM.renderPayload)


# ── typeRef against sh:datatype ──


def _candidate_shapes(model: Model, decision: Decision) -> Iterable[Shape]:
    reads = list(decision.reads)
    return reads if reads else list(model.shapes)


def _input_findings(model: Model, decision: Decision) -> list[DecisionFinding]:
    table = decision.table
    type_refs = {i.expression: i.type_ref for i in table.inputs}
    dmn = decision.dmn_path.name
    found: list[DecisionFinding] = []
    for binding in decision.inputs:
        type_ref = type_refs.get(binding.variable)
        if type_ref is None:
            continue
        subject, fact = str(decision.iri), str(binding.from_path_iri)
        where = f"input {binding.variable!r} of {table.decision_id!r} in {dmn} is typeRef {type_ref}"
        if binding.measure == DEC.Length:
            if type_ref != "number":
                found.append(DecisionFinding(subject, fact, f"{where}, but dec:Length measures a number"))
            continue
        accepted = TYPE_REF_DATATYPES.get(type_ref)
        if accepted is None:
            continue
        for shape in _candidate_shapes(model, decision):
            for field in shape.fields():
                if field.iri != binding.from_path_iri or field.datatype is None or field.datatype in accepted:
                    continue
                found.append(
                    DecisionFinding(
                        subject,
                        fact,
                        f"{where}, but {local_name(shape.iri)} gives {binding.from_path!r} "
                        f"sh:datatype xsd:{local_name(field.datatype)}",
                    )
                )
    return found


def type_ref_findings(model: Model) -> list[DecisionFinding]:
    """Every dec:input whose DMN typeRef disagrees with its dec:fromPath's sh:datatype."""
    found: list[DecisionFinding] = []
    for decision in model.decisions:
        if model.ds.value(decision.iri, DEC.payloadElement) is None:
            continue
        try:
            found.extend(_input_findings(model, decision))
        except ResolutionError as err:
            if _missing_payload(err):
                continue
            found.append(DecisionFinding(err.subject, err.predicate, err.detail or str(err)))
    return sorted(found)


# ── gateway conditions ──


def condition_names(expression: str) -> tuple[str, ...]:
    """The free names a Python condition reads, Python builtins and names it
    binds itself (comprehension targets, lambda arguments) aside, sorted.
    SyntaxError when it is not a Python expression."""
    tree = ast.parse(expression, mode="eval")
    read: set[str] = set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (read if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return tuple(sorted(read - bound - _BUILTINS))


def _decision_variables(model: Model, decision: Decision) -> set[str]:
    ds = model.ds
    out: set[str] = set()
    for node in ds.objects(decision.iri, DEC.output):
        value = ds.value(node, DEC.processVariable)
        if value is not None:
            out.add(str(value))
    for node in ds.objects(decision.iri, DEC.input):
        value = ds.value(node, DEC.variable)
        if value is not None:
            out.add(str(value))
    return out


def _user_task_fields(node: FlowNode) -> set[str]:
    form = node.completed_on
    shapes = list(form.writes) if form is not None else []
    if not shapes:
        shapes = list(node.writes)
    return {field.name for shape in shapes for field in shape.fields()}


def _provides(model: Model, node: FlowNode) -> set[str]:
    """The task data names the engine or worker sets at ``node``."""
    if node.tag == "businessRuleTask":
        decision = node.decided_by
        return set() if decision is None else _decision_variables(model, decision)
    if node.tag == "userTask" or node.kind == "UserTask":
        return _user_task_fields(node)
    return set()


def _upstream(start: str, nodes: dict[str, BpmnNode]) -> set[str]:
    """``start`` and every node it is reachable from (boundary events follow
    from what precedes the task they are attached to)."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        node_id = todo.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes[node_id]
        todo.extend(f.source for f in node.incoming)
        if node.attached_to is not None:
            todo.extend(f.source for f in nodes[node.attached_to].incoming)
    return seen


def _process_findings(model: Model, process: Process) -> list[DecisionFinding]:
    found: list[DecisionFinding] = []
    by_bpmn_process: dict[str, dict[str, FlowNode]] = {}
    for flow_node in process.nodes():
        by_bpmn_process.setdefault(flow_node.node.process_id, {})[flow_node.bpmn_id] = flow_node
    for flow_nodes in by_bpmn_process.values():
        nodes = {node_id: fn.node for node_id, fn in flow_nodes.items()}
        flows = {f.id: f for n in nodes.values() for f in n.outgoing}
        for flow in sorted(flows.values(), key=lambda f: f.id):
            if not flow.condition:
                continue
            subject = str(process.element_iri(flow.id))
            try:
                names = condition_names(flow.condition)
            except SyntaxError as err:
                found.append(
                    DecisionFinding(
                        subject, flow.condition, f"is not a Python expression the engine can evaluate ({err.msg})"
                    )
                )
                continue
            declared: set[str] = set()
            for node_id in _upstream(flow.source, nodes):
                declared |= _provides(model, flow_nodes[node_id])
            for name in names:
                if name not in declared:
                    found.append(
                        DecisionFinding(
                            subject,
                            name,
                            f"condition {flow.condition!r} reads {name!r}, but no decision or user task "
                            f"upstream of {flow.source!r} sets it",
                        )
                    )
    return found


def condition_findings(model: Model) -> list[DecisionFinding]:
    """Every variable a sequence flow condition reads that nothing upstream sets."""
    found: list[DecisionFinding] = []
    for process in model.processes:
        try:
            found.extend(_process_findings(model, process))
        except ResolutionError as err:
            if _missing_payload(err):
                continue
            found.append(DecisionFinding(err.subject, err.predicate, err.detail or str(err)))
    return sorted(found)


def decision_findings(model: Model) -> list[DecisionFinding]:
    """Both checks' findings, sorted by subject, fact and message."""
    return sorted(type_ref_findings(model) + condition_findings(model))


__all__ = [
    "TYPE_REF_DATATYPES",
    "DecisionFinding",
    "condition_findings",
    "condition_names",
    "decision_findings",
    "type_ref_findings",
]
