"""Static checks for decisions (backlog K2): faults the runtime would hit.

``decision_findings(model)`` asks three questions and returns one
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

- **UNIQUE tables are complete and disjoint** (backlog X13). Spiff stops at
  the first rule of a UNIQUE table that matches and gives no output when none
  does, so overlapping rules and uncovered inputs only show at run time. For
  each decision table whose hitPolicy is UNIQUE (the DMN default), every
  inputEntry is read as a set of values: ``-`` (any), a number comparison
  (``< 5``, ``<= 5``, ``> 5``, ``>= 5``, ``= 5`` or ``5``), a range
  (``[a..b]``, ``(a..b)``, ``]a..b[`` and mixed brackets), a quoted string,
  or a comma list of these, all numbers or all strings. A table with any
  other entry (FEEL beyond this subset, an empty entry, numbers and strings
  in one input) is skipped rather than guessed at. Each input's values are
  cut into cells at the boundary numbers its entries name (each boundary, the
  span between two, below the lowest and above the highest), or into its
  listed strings plus any other string; every entry holds or misses a whole
  cell. Two rules overlap when, on every input, some cell matches both: one
  finding per pair, naming both rule ids and an input they both match. A gap
  is a combination of cells no rule matches: one finding per table, naming
  the first such input in cell order. The subject is the decision, the fact
  ``dmn:rule``. A decision that cannot be read gives no finding here; the
  typeRef check reports it.

None of the questions needs vocabulary beyond what the engine already reads
(principle 4), and all read the BPMN and DMN in their native XML
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
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING

from rdflib import XSD, URIRef

from .bpmn import BpmnNode
from .dmn import DecisionTable, Rule
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


# ── UNIQUE tables: overlap and gaps ──

_NUMBER = r"-?\d+(?:\.\d+)?"
_COMPARISON = re.compile(rf"(<=|>=|<|>|=)?\s*({_NUMBER})")
_RANGE = re.compile(rf"([\[(\]])\s*({_NUMBER})\s*\.\.\s*({_NUMBER})\s*([\])\[])")
_STRING = re.compile(r'"([^"\\]*)"')


@dataclass(frozen=True)
class _Range:
    """Numbers between ``lo`` and ``hi`` (None: unbounded), each end closed or open."""

    lo: Fraction | None
    lo_closed: bool
    hi: Fraction | None
    hi_closed: bool

    def holds(self, value: Fraction) -> bool:
        if self.lo is not None and (value < self.lo or (value == self.lo and not self.lo_closed)):
            return False
        return not (self.hi is not None and (value > self.hi or (value == self.hi and not self.hi_closed)))


#: An inputEntry read as a set: None is ``-`` (any value), a tuple of ranges a
#: set of numbers, a frozenset the strings it lists.
_Entry = tuple[_Range, ...] | frozenset[str] | None

#: One cell of an input's values: a representative (a number, a listed string,
#: or None for any other value) and how a finding writes it.
_Cell = tuple[Fraction | str | None, str]


def _split(text: str) -> list[str]:
    """``text`` split at the commas outside quotes, each part stripped."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        if char == "," and not quoted:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return parts


def _number_atom(atom: str) -> _Range | None:
    if match := _COMPARISON.fullmatch(atom):
        op, value = match.group(1) or "=", Fraction(Decimal(match.group(2)))
        if op == "=":
            return _Range(value, True, value, True)
        if op.startswith("<"):
            return _Range(None, False, value, op == "<=")
        return _Range(value, op == ">=", None, False)
    if match := _RANGE.fullmatch(atom):
        lo, hi = Fraction(Decimal(match.group(2))), Fraction(Decimal(match.group(3)))
        return _Range(lo, match.group(1) == "[", hi, match.group(4) == "]")
    return None


def _entry(text: str) -> _Entry:
    """The entry's set; ValueError when it is outside the subset the check reads."""
    if text == "-":
        return None
    atoms = _split(text)
    strings = [m.group(1) for a in atoms if (m := _STRING.fullmatch(a))]
    if len(strings) == len(atoms):
        return frozenset(strings)
    ranges = [r for a in atoms if (r := _number_atom(a)) is not None]
    if len(ranges) == len(atoms):
        return tuple(ranges)
    raise ValueError(f"inputEntry {text!r} is outside the subset the check reads")


def _matches(entry: _Entry, value: Fraction | str | None) -> bool:
    if entry is None:
        return True
    if isinstance(entry, frozenset):
        return isinstance(value, str) and value in entry
    return isinstance(value, Fraction) and any(r.holds(value) for r in entry)


def _number_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return str(Decimal(value.numerator) / Decimal(value.denominator))


def _cells(entries: Sequence[_Entry]) -> list[_Cell] | None:
    """An input's cells in value order, or None when its entries mix numbers and strings."""
    numbers = [e for e in entries if isinstance(e, tuple)]
    strings = [e for e in entries if isinstance(e, frozenset)]
    if numbers and strings:
        return None
    if strings:
        listed = sorted({s for e in strings for s in e})
        others = ", ".join(f'"{s}"' for s in listed)
        cells: list[_Cell] = [(s, f'= "{s}"') for s in listed]
        return [*cells, (None, f"not {others}")]
    if not numbers:
        return [(None, "= anything")]
    points = sorted({p for e in numbers for r in e for p in (r.lo, r.hi) if p is not None})
    values = [points[0] - 1]
    for low, high in zip(points, points[1:], strict=False):
        values += [low, (low + high) / 2]
    values += [points[-1], points[-1] + 1]
    return [(v, f"= {_number_text(v)}") for v in values]


def _witness(names: Sequence[str], cells: Sequence[_Cell]) -> str:
    return ", ".join(f"{name} {text}" for name, (_value, text) in zip(names, cells, strict=True))


def _gap(rules: Sequence[tuple[Rule, tuple[_Entry, ...]]], cells: Sequence[list[_Cell]]) -> list[_Cell] | None:
    """The first combination of cells, in cell order, that no rule matches."""
    chosen: list[_Cell] = []

    def search(depth: int, alive: list[int]) -> bool:
        if not alive:
            chosen.extend(cells[i][0] for i in range(depth, len(cells)))
            return True
        if depth == len(cells):
            return False
        for cell in cells[depth]:
            chosen.append(cell)
            if search(depth + 1, [r for r in alive if _matches(rules[r][1][depth], cell[0])]):
                return True
            chosen.pop()
        return False

    return chosen if search(0, list(range(len(rules)))) else None


def _unique_table_findings(subject: str, table: DecisionTable, dmn: str) -> list[DecisionFinding]:
    try:
        parsed = [(rule, tuple(_entry(text) for text in rule.inputs)) for rule in table.rules]
    except ValueError:
        return []
    cells: list[list[_Cell]] = []
    for i in range(len(table.inputs)):
        input_cells = _cells([entries[i] for _rule, entries in parsed])
        if input_cells is None:
            return []
        cells.append(input_cells)
    names = [i.expression or i.label or i.id for i in table.inputs]
    where = f"UNIQUE table {table.decision_id!r} in {dmn}"
    found: list[DecisionFinding] = []
    for a, (rule_a, entries_a) in enumerate(parsed):
        for rule_b, entries_b in parsed[a + 1 :]:
            shared: list[_Cell] = []
            for i, input_cells in enumerate(cells):
                both = [c for c in input_cells if _matches(entries_a[i], c[0]) and _matches(entries_b[i], c[0])]
                if not both:
                    break
                shared.append(both[0])
            else:
                found.append(
                    DecisionFinding(
                        subject,
                        "dmn:rule",
                        f"rules {rule_a.id!r} and {rule_b.id!r} of {where} both match {_witness(names, shared)}",
                    )
                )
    gap = _gap(parsed, cells)
    if gap is not None:
        found.append(DecisionFinding(subject, "dmn:rule", f"no rule of {where} matches {_witness(names, gap)}"))
    return found


def table_findings(model: Model) -> list[DecisionFinding]:
    """Every overlapping rule pair and one uncovered input of each UNIQUE decision table."""
    found: list[DecisionFinding] = []
    for decision in model.decisions:
        if model.ds.value(decision.iri, DEC.payloadElement) is None:
            continue
        try:
            table = decision.table
            dmn = decision.dmn_path.name
        except ResolutionError:
            continue
        if table.hit_policy == "UNIQUE":
            found.extend(_unique_table_findings(str(decision.iri), table, dmn))
    return sorted(found)


def decision_findings(model: Model) -> list[DecisionFinding]:
    """The three checks' findings, sorted by subject, fact and message."""
    return sorted(type_ref_findings(model) + condition_findings(model) + table_findings(model))


__all__ = [
    "TYPE_REF_DATATYPES",
    "DecisionFinding",
    "condition_findings",
    "condition_names",
    "decision_findings",
    "table_findings",
    "type_ref_findings",
]
