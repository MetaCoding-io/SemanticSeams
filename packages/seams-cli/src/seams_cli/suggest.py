"""``seams suggest``: a model change an LLM proposes and deterministic code builds (M025/S01, ADR-0028).

The LLM only proposes. Its answer is one JSON object of a named kind, which
``parse_suggestion`` reads against the model; the first kind is
``condition-to-dmn``: a gateway whose outgoing conditions compute over form
fields becomes a DMN decision, a business-rule task before the gateway and
conditions over the decision's output variable. A malformed answer, or one
that names a gateway, flow, field or id the model does not allow, raises
``SuggestionError`` (a ``ResolutionError``) naming the subject and predicate.

``build_change`` turns a parsed suggestion into a ``Change``: the
``seams_edit.Patch`` of the TriG facts and the new text of the BPMN and DMN
payloads. Every graph a fact goes in, every predicate it carries and every
name it holds comes from the model (the process's existing business-rule
task and decision) or the suggestion; none is fixed here. The payloads are
edited as text, element by element, so the modeler's layout and every other
byte stay as they were (as ``seams_edit.xml`` does); the result is parsed
before it is returned. The same model and suggestion give the same bytes.

``check_change`` copies the project to a temporary directory, writes the
change there through ``seams_edit`` (``apply``, ``save_payload``), and runs the
seam shapes, ``seams.decision_findings`` and every generator of the project on
the copy. It returns the verdicts and the findings, each naming its subject
and predicate. The project itself is only read.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from string import Template
from typing import cast
from xml.sax.saxutils import escape, quoteattr

import seams
from lxml import etree
from rdflib import RDF, RDFS, BNode, Literal, URIRef
from rdflib.term import Node
from seams import DEC, PROC, SEAM, FlowNode, Process, ResolutionError, Shape
from seams.decisions_check import TYPE_REF_DATATYPES, condition_names

import seams_edit
from seams_gen import GeneratorError

from .check import ONTOLOGY_DIR, check_shapes, load_model, model_graph
from .generate import generate_project
from .project import Project, ProjectError, load_project, resolve_model
from .propose import cache_key, call_provider, extract_draft, quote

#: The suggestion kinds this module builds (ADR-0028 section 3).
KINDS = ("condition-to-dmn",)

_SCRATCH_IGNORE = shutil.ignore_patterns(".seams", "__pycache__", ".pytest_cache")
# An XML id is an NCName; a DMN input expression and a process variable are Python names.
_NCNAME = re.compile(r"[^\W\d][\w.\-]*")
_KEYS = frozenset({"kind", "gateway", "decision_id", "decision_name", "inputs", "output", "rules", "conditions"})


class SuggestionError(ResolutionError):
    """A suggestion the model does not allow: the subject and predicate name the fact."""


# ── the suggestion ──


@dataclass(frozen=True)
class DmnRule:
    """One rule: the input test per input variable (``-`` when the answer gives
    none), in the order of the suggestion's inputs, and the output value."""

    tests: tuple[str, ...]
    output: str


@dataclass(frozen=True)
class ConditionToDmn:
    """A ``condition-to-dmn`` suggestion (ADR-0028 section 3).

    ``gateway`` is the BPMN id of the gateway, ``process`` the IRI of the
    process whose BPMN holds it. ``inputs`` are form field names (each a
    ``sh:name``), ``output`` the variable the decision sets and the flows
    read, ``conditions`` the new condition of each outgoing flow, by flow id."""

    process: URIRef
    gateway: str
    decision_id: str
    decision_name: str
    inputs: tuple[str, ...]
    output: str
    rules: tuple[DmnRule, ...]
    conditions: tuple[tuple[str, str], ...]


def _string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SuggestionError("suggestion", key, f"must be a non-empty string, got {value!r}")
    return value.strip()


def _name(data: Mapping[str, object], key: str) -> str:
    value = _string(data, key)
    if not value.isidentifier():
        raise SuggestionError("suggestion", key, f"{value!r} is not a name")
    return value


def _gateway(model: seams.Model, gateway: str) -> tuple[Process, FlowNode]:
    found = [(p, n) for p in model.processes for n in p.gateways() if n.bpmn_id == gateway]
    if not found:
        raise SuggestionError(gateway, "gateway", "no gateway of the model's processes has this BPMN id")
    if len(found) > 1:
        iris = ", ".join(sorted(str(n.iri) for _, n in found))
        raise SuggestionError(gateway, "gateway", f"the BPMN id names more than one gateway ({iris})")
    return found[0]


def _rules(data: Mapping[str, object], inputs: tuple[str, ...]) -> tuple[DmnRule, ...]:
    raw = data.get("rules")
    if not isinstance(raw, list) or not raw:
        raise SuggestionError("suggestion", "rules", "must be a non-empty list")
    rules: list[DmnRule] = []
    for index, item in enumerate(cast(list[object], raw)):
        where = f"rules[{index}]"
        if not isinstance(item, dict):
            raise SuggestionError("suggestion", where, "must be an object with `when` and `then`")
        rule = cast(dict[str, object], item)
        when = rule.get("when", {})
        if not isinstance(when, dict):
            raise SuggestionError("suggestion", f"{where}.when", "must be an object of input tests")
        tests = cast(dict[str, object], when)
        unknown = sorted(set(tests) - set(inputs))
        if unknown:
            raise SuggestionError("suggestion", f"{where}.when", f"tests {unknown} name no input of {list(inputs)}")
        for key, test in tests.items():
            if not isinstance(test, str) or not test.strip():
                raise SuggestionError("suggestion", f"{where}.when.{key}", "must be a non-empty FEEL test")
        rules.append(DmnRule(tuple(cast(str, tests.get(i, "-")).strip() for i in inputs), _string(rule, "then")))
    return tuple(rules)


def _conditions(
    data: Mapping[str, object], process: Process, node: FlowNode, output: str
) -> tuple[tuple[str, str], ...]:
    raw = data.get("conditions")
    if not isinstance(raw, dict) or not raw:
        raise SuggestionError("suggestion", "conditions", "must be an object of conditions by flow id")
    given = cast(dict[str, object], raw)
    flows = {f.id: f for f in node.outgoing}
    for flow_id in sorted(given):
        if flow_id not in flows:
            raise SuggestionError(
                process.element_iri(flow_id), "conditions", f"{flow_id!r} is not an outgoing flow of {node.bpmn_id!r}"
            )
    out: list[tuple[str, str]] = []
    for flow_id, flow in sorted(flows.items()):
        if not flow.condition:
            continue
        iri = process.element_iri(flow_id)
        condition = given.get(flow_id)
        if not isinstance(condition, str) or not condition.strip():
            raise SuggestionError(iri, "conditionExpression", f"the suggestion gives flow {flow_id!r} no condition")
        try:
            names = condition_names(condition)
        except SyntaxError as err:
            raise SuggestionError(iri, "conditionExpression", f"{condition!r} is not Python ({err.msg})") from None
        if names != (output,):
            raise SuggestionError(
                iri, "conditionExpression", f"{condition!r} reads {list(names)}, not only the output {output!r}"
            )
        out.append((flow_id, condition.strip()))
    unconditioned = sorted(set(given) - {f for f, _ in out})
    if unconditioned:
        raise SuggestionError(
            process.element_iri(unconditioned[0]), "conditionExpression", "the flow has no condition to replace"
        )
    return tuple(out)


def parse_suggestion(model: seams.Model, text: str) -> ConditionToDmn:
    """The suggestion in the JSON ``text``, checked against ``model``.

    ``SuggestionError`` names the key of a malformed answer, the gateway id
    no process has, or the flow that is not the gateway's or whose condition
    does not read the output variable alone."""
    try:
        data: object = json.loads(text)
    except json.JSONDecodeError as err:
        raise SuggestionError("suggestion", "json", f"not JSON: {err.msg} at line {err.lineno}") from None
    if not isinstance(data, dict):
        raise SuggestionError("suggestion", "json", "must be one JSON object")
    answer = cast(dict[str, object], data)
    unknown = sorted(set(answer) - _KEYS)
    if unknown:
        raise SuggestionError("suggestion", unknown[0], f"unknown key; the keys are {sorted(_KEYS)}")
    kind = answer.get("kind")
    if kind not in KINDS:
        raise SuggestionError("suggestion", "kind", f"{kind!r} is not one of {list(KINDS)}")
    gateway = _string(answer, "gateway")
    process, node = _gateway(model, gateway)
    decision_id = _string(answer, "decision_id")
    if not _NCNAME.fullmatch(decision_id):
        raise SuggestionError("suggestion", "decision_id", f"{decision_id!r} is not an XML id")
    raw_inputs = answer.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise SuggestionError("suggestion", "inputs", "must be a non-empty list of field names")
    inputs = tuple(_name({"inputs": i}, "inputs") for i in cast(list[object], raw_inputs))
    if len(set(inputs)) != len(inputs):
        raise SuggestionError("suggestion", "inputs", f"{list(inputs)} names a field twice")
    output = _name(answer, "output")
    return ConditionToDmn(
        process=process.iri,
        gateway=gateway,
        decision_id=decision_id,
        decision_name=_string(answer, "decision_name"),
        inputs=inputs,
        output=output,
        rules=_rules(answer, inputs),
        conditions=_conditions(answer, process, node, output),
    )


# ── the payload text ──


@dataclass
class _El:
    """An element as written: its qualified tag, attributes, and the offsets of
    its start tag (``start``..``open_end``) and end tag (``close_start``..``end``)."""

    tag: str
    attrs: dict[str, str]
    start: int
    open_end: int
    close_start: int = -1
    end: int = -1
    parent: _El | None = None
    children: list[_El] | None = None

    @property
    def local(self) -> str:
        return self.tag.rpartition(":")[2]

    @property
    def prefix(self) -> str:
        """``bpmn:`` for ``bpmn:task``; empty for a default-namespace tag."""
        head, colon, _ = self.tag.rpartition(":")
        return head + colon

    def kids(self, local: str | None = None) -> list[_El]:
        return [c for c in self.children or [] if local is None or c.local == local]

    def iter(self) -> Iterable[_El]:
        yield self
        for child in self.children or []:
            yield from child.iter()


_TOKEN = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE(?:[^\[>]|\[.*?\])*>"
    r"|</(?P<end>[^\s>]+)\s*>"
    r"|<(?P<tag>[^\s/>!?]+)(?P<attrs>(?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*/?>",
    re.DOTALL,
)
_ATTRIBUTE = re.compile(r"\s+(?P<name>[^\s=/>]+)\s*=\s*(?P<q>[\"'])(?P<value>.*?)(?P=q)", re.DOTALL)


def _scan(path: Path, text: str) -> _El:
    """The element tree of ``text`` with the offsets of every tag."""
    root: _El | None = None
    stack: list[_El] = []
    for match in _TOKEN.finditer(text):
        if match["tag"]:
            attrs = {m["name"]: m["value"] for m in _ATTRIBUTE.finditer(match["attrs"])}
            el = _El(match["tag"], attrs, match.start(), match.end(), children=[])
            if stack:
                el.parent = stack[-1]
                cast(list[_El], stack[-1].children).append(el)
            elif root is None:
                root = el
            if match.group().endswith("/>"):
                el.close_start = el.end = match.end()
            else:
                stack.append(el)
        elif match["end"]:
            if not stack or stack[-1].tag != match["end"]:
                raise SuggestionError(path.name, "end tag", f"the payload's tags do not nest at {match['end']!r}")
            el = stack.pop()
            el.close_start, el.end = match.start(), match.end()
    if root is None or stack:
        raise SuggestionError(path.name, "root", "the payload has no closed root element")
    return root


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _line_end(text: str, pos: int) -> int:
    end = text.find("\n", pos)
    return len(text) if end < 0 else end


def _indent(text: str, el: _El) -> str:
    lead = text[_line_start(text, el.start) : el.start]
    return lead if not lead.strip() else ""


def _step(text: str, el: _El) -> str:
    """The indentation one level adds, read from ``el``'s first child (two spaces without one)."""
    own, kids = _indent(text, el), el.kids()
    if kids:
        inner = _indent(text, kids[0])
        if inner.startswith(own) and len(inner) > len(own):
            return inner[len(own) :]
    return "  "


def _after_line(text: str, el: _El) -> int:
    """The offset after ``el``'s end, at the end of its line when only spaces follow it."""
    end = _line_end(text, el.end)
    return end if not text[el.end : end].strip() else el.end


def _splice(text: str, edits: Iterable[tuple[int, int, str]]) -> str:
    out, pos = [], 0
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1])):
        if start < pos:
            raise ValueError("overlapping payload edits")
        out += [text[pos:start], new]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _attr_span(text: str, el: _El, name: str) -> tuple[int, int]:
    for match in _ATTRIBUTE.finditer(text, el.start, el.open_end):
        if match["name"] == name:
            return match.start("value"), match.end("value")
    raise KeyError(name)


def _number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _bounds(el: _El | None) -> tuple[float, float, float, float] | None:
    bounds = next((c for c in el.kids("Bounds")), None) if el is not None else None
    if bounds is None:
        return None
    try:
        x, y, w, h = (float(bounds.attrs[k]) for k in ("x", "y", "width", "height"))
    except (KeyError, ValueError):
        return None
    return x, y, w, h


def _di_suffix(shape: _El, element_id: str) -> str:
    """The suffix the payload's diagram ids add to their element's id (``_di`` for ``task_di``)."""
    shape_id = shape.attrs.get("id", "")
    return shape_id[len(element_id) :] if shape_id.startswith(element_id) and shape_id != element_id else "_di"


def _below(root: _El, bounds: tuple[float, float, float, float], size: tuple[float, float]) -> tuple[float, float]:
    """A free spot for a ``size`` box: centred under ``bounds`` and below every drawn box."""
    boxes = [b for el in root.iter() if el.local == "Bounds" for b in [_bounds(el.parent)] if b is not None]
    bottom = max(y + h for _, y, _, h in boxes)
    x, _, w, _ = bounds
    return x + w / 2 - size[0] / 2, bottom + size[1] / 2


def _check_ids(path: Path, root: _El, subject: object, ids: Iterable[str]) -> None:
    taken = {el.attrs["id"] for el in root.iter() if "id" in el.attrs}
    for new in sorted(ids):
        if new in taken:
            raise SuggestionError(subject, "id", f"{path.name} already has an element with id {new!r}")


def _parsed(path: Path, text: str) -> str:
    try:
        etree.fromstring(text.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as err:
        raise SuggestionError(path.name, f"line {err.lineno}", f"the edited payload is not XML: {err.msg}") from None
    return text


def _bpmn_text(path: Path, text: str, s: ConditionToDmn, task: str, flow: str, subject: object) -> str:
    """The BPMN with the business-rule task ``task`` before the gateway, joined to it
    by the new flow ``flow``, and each outgoing flow's condition replaced."""
    root = _scan(path, text)
    by_id = {el.attrs["id"]: el for el in root.iter() if "id" in el.attrs}
    gateway = by_id[s.gateway]
    process = cast(_El, gateway.parent)
    flows = process.kids("sequenceFlow")
    incoming = [f for f in flows if f.attrs.get("targetRef") == s.gateway]
    if not incoming:
        raise SuggestionError(subject, "incoming", f"gateway {s.gateway!r} has no incoming sequence flow")
    shape = next((el for el in root.iter() if el.attrs.get("bpmnElement") == s.gateway), None)
    suffix = _di_suffix(shape, s.gateway) if shape is not None else ""
    _check_ids(path, root, subject, {task, flow} | ({task + suffix, flow + suffix} if shape is not None else set()))
    p, ind, step = gateway.prefix, _indent(text, gateway), _step(text, gateway)
    edits: list[tuple[int, int, str]] = []
    for f in incoming:
        start, end = _attr_span(text, f, "targetRef")
        edits.append((start, end, escape(task)))
    gateway_in = gateway.kids("incoming")
    if gateway_in:
        edits.append((gateway_in[0].open_end, gateway_in[0].close_start, escape(flow)))
        for extra in gateway_in[1:]:
            edits.append((_line_start(text, extra.start), _after_line(text, extra) + 1, ""))
    lines = [f"{ind}<{p}businessRuleTask id={quoteattr(task)} name={quoteattr(s.decision_name)}>"]
    lines += [f"{ind}{step}<{p}incoming>{escape(f.attrs['id'])}</{p}incoming>" for f in incoming]
    lines += [f"{ind}{step}<{p}outgoing>{escape(flow)}</{p}outgoing>", f"{ind}</{p}businessRuleTask>"]
    head = _line_start(text, gateway.start)
    blank = "\n" if head >= 2 and not text[_line_start(text, head - 1) : head - 1].strip() else ""
    edits.append((head, head, "\n".join(lines) + "\n" + blank))
    last = incoming[-1]
    new_flow = f"<{last.prefix}sequenceFlow id={quoteattr(flow)} sourceRef={quoteattr(task)} targetRef={quoteattr(s.gateway)} />"
    at = _after_line(text, last)
    edits.append((at, at, f"\n{_indent(text, last)}{new_flow}"))
    outgoing = {f.attrs.get("id"): f for f in flows if f.attrs.get("sourceRef") == s.gateway}
    for flow_id, condition in s.conditions:
        expression = next(iter(outgoing[flow_id].kids("conditionExpression")), None)
        if expression is None or expression.open_end == expression.end:
            raise SuggestionError(subject, "conditionExpression", f"flow {flow_id!r} has no condition text to replace")
        edits.append((expression.open_end, expression.close_start, escape(condition)))
    if shape is not None:
        edits += _bpmn_diagram(text, root, shape, task, flow, suffix)
    return _parsed(path, _splice(text, edits))


def _bpmn_diagram(text: str, root: _El, shape: _El, task: str, flow: str, suffix: str) -> list[tuple[int, int, str]]:
    """The task's shape below the diagram and an edge from it up into the gateway."""
    gateway_box = _bounds(shape)
    if gateway_box is None:
        return []
    task_shapes = [el for el in root.iter() if el.local == shape.local and el is not shape]
    by_id = {el.attrs["id"]: el for el in root.iter() if "id" in el.attrs}
    sized = [
        b
        for el in task_shapes
        for b in [_bounds(el)]
        if b is not None and by_id.get(el.attrs.get("bpmnElement", ""), shape).local.endswith("Task")
    ]
    width, height = (sized[0][2], sized[0][3]) if sized else (gateway_box[2], gateway_box[3])
    x, y = _below(root, gateway_box, (width, height))
    bounds = next(c for c in shape.kids("Bounds"))
    waypoint = next((el for el in root.iter() if el.local == "waypoint"), None)
    ind, step, sp = _indent(text, shape), _step(text, shape), shape.prefix
    lines = [
        f"{ind}<{shape.tag} id={quoteattr(task + suffix)} bpmnElement={quoteattr(task)}>",
        f'{ind}{step}<{bounds.tag} x="{_number(x)}" y="{_number(y)}" width="{_number(width)}" height="{_number(height)}" />',
        f"{ind}</{shape.tag}>",
    ]
    if waypoint is not None:
        gx, gy, gw, gh = gateway_box
        edge = f"{sp}BPMNEdge"
        lines += [
            f"{ind}<{edge} id={quoteattr(flow + suffix)} bpmnElement={quoteattr(flow)}>",
            f'{ind}{step}<{waypoint.tag} x="{_number(x + width / 2)}" y="{_number(y)}" />',
            f'{ind}{step}<{waypoint.tag} x="{_number(gx + gw / 2)}" y="{_number(gy + gh)}" />',
            f"{ind}</{edge}>",
        ]
    at = _after_line(text, shape)
    return [(at, at, "\n" + "\n".join(lines))]


def _dmn_text(
    path: Path, text: str, s: ConditionToDmn, types: Mapping[str, str], labels: Mapping[str, str], output_type: str
) -> str:
    """The DMN with the suggested decision after its last decision."""
    root = _scan(path, text)
    decisions = root.kids("decision")
    if not decisions:
        raise SuggestionError(path.name, "decision", "the DMN payload has no decision to add the new one beside")
    last = decisions[-1]
    d = s.decision_id
    ids = {d, f"{d}_var", f"{d}_table", f"{d}_output"}
    ids |= {f"{d}_input_{i}" for i in s.inputs} | {f"{d}_input_{i}_expr" for i in s.inputs}
    for n in range(1, len(s.rules) + 1):
        ids |= {f"{d}_rule_{n}", f"{d}_rule_{n}_out"} | {f"{d}_rule_{n}_{i}" for i in s.inputs}
    shape = next((el for el in root.iter() if el.attrs.get("dmnElementRef") == last.attrs.get("id")), None)
    suffix = _di_suffix(shape, last.attrs.get("id", "")) if shape is not None else ""
    _check_ids(path, root, d, ids | ({d + suffix} if shape is not None else set()))
    p, ind, s1 = last.prefix, _indent(text, last), _step(text, last)
    s2, s3, s4 = s1 * 2, s1 * 3, s1 * 4
    out = quoteattr(s.output)
    lines = [
        f"{ind}<{p}decision id={quoteattr(d)} name={quoteattr(s.decision_name)}>",
        f'{ind}{s1}<{p}variable id={quoteattr(d + "_var")} name={out} typeRef="{output_type}" />',
        f'{ind}{s1}<{p}decisionTable id={quoteattr(d + "_table")} hitPolicy="FIRST">',
    ]
    for i in s.inputs:
        lines += [
            f"{ind}{s2}<{p}input id={quoteattr(f'{d}_input_{i}')} label={quoteattr(labels[i])}>",
            f'{ind}{s3}<{p}inputExpression id={quoteattr(f"{d}_input_{i}_expr")} typeRef="{types[i]}">',
            f"{ind}{s4}<{p}text>{escape(i)}</{p}text>",
            f"{ind}{s3}</{p}inputExpression>",
            f"{ind}{s2}</{p}input>",
        ]
    lines.append(f'{ind}{s2}<{p}output id={quoteattr(d + "_output")} label={out} name={out} typeRef="{output_type}" />')
    for n, rule in enumerate(s.rules, start=1):
        lines.append(f"{ind}{s2}<{p}rule id={quoteattr(f'{d}_rule_{n}')}>")
        for i, test in zip(s.inputs, rule.tests, strict=True):
            entry = quoteattr(f"{d}_rule_{n}_{i}")
            lines.append(f"{ind}{s3}<{p}inputEntry id={entry}><{p}text>{escape(test)}</{p}text></{p}inputEntry>")
        entry = quoteattr(f"{d}_rule_{n}_out")
        lines.append(f"{ind}{s3}<{p}outputEntry id={entry}><{p}text>{escape(rule.output)}</{p}text></{p}outputEntry>")
        lines.append(f"{ind}{s2}</{p}rule>")
    lines += [f"{ind}{s1}</{p}decisionTable>", f"{ind}</{p}decision>"]
    edits = [(last.end, last.end, "\n\n" + "\n".join(lines))]
    box = _bounds(shape)
    if shape is not None and box is not None:
        x, y = _below(root, box, (box[2], box[3]))
        bounds = next(c for c in shape.kids("Bounds"))
        sind, sstep = _indent(text, shape), _step(text, shape)
        shape_lines = [
            f"{sind}<{shape.tag} id={quoteattr(d + suffix)} dmnElementRef={quoteattr(d)}>",
            f'{sind}{sstep}<{bounds.tag} x="{_number(x)}" y="{_number(y)}" '
            f'width="{_number(box[2])}" height="{_number(box[3])}" />',
            f"{sind}</{shape.tag}>",
        ]
        at = _after_line(text, shape)
        edits.append((at, at, "\n" + "\n".join(shape_lines)))
    return _parsed(path, _splice(text, edits))


# ── the change ──


@dataclass(frozen=True)
class Change:
    """A suggestion as model edits: the TriG patch and each payload's new text,
    by absolute payload path, sorted."""

    patch: seams_edit.Patch
    payloads: tuple[tuple[Path, str], ...]


def _graph(model: seams.Model, subject: Node, predicate: URIRef, obj: Node | None = None) -> URIRef:
    """The one named graph that states ``subject predicate obj``."""
    graphs = sorted({g for _, _, _, g in model.ds.quads((subject, predicate, obj, None)) if isinstance(g, URIRef)})
    if len(graphs) != 1:
        raise ResolutionError(subject, predicate, f"expected the fact in one graph, found {[str(g) for g in graphs]}")
    return graphs[0]


def _upstream(process: Process, node: FlowNode) -> list[FlowNode]:
    """``node``'s process nodes that reach it over sequence flows, in flow order."""
    by_id = {n.bpmn_id: n for n in process.nodes() if n.node.process_id == node.node.process_id}
    seen: set[str] = set()
    todo = [f.source for f in node.incoming]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        todo.extend(f.source for f in by_id[current].incoming)
        attached = by_id[current].node.attached_to
        if attached is not None:
            todo.extend(f.source for f in by_id[attached].incoming)
    return [n for n in by_id.values() if n.bpmn_id in seen]


def _upstream_shapes(process: Process, node: FlowNode) -> dict[URIRef, Shape]:
    """The shapes a task upstream of ``node`` reads or writes, or its form writes, by IRI."""
    shapes: dict[URIRef, Shape] = {}
    for n in _upstream(process, node):
        form = n.completed_on
        for shape in [*n.reads, *n.writes, *(form.writes if form is not None else [])]:
            shapes[shape.iri] = shape
    return dict(sorted(shapes.items()))


def _input_shapes(process: Process, node: FlowNode, s: ConditionToDmn) -> tuple[list[Shape], dict[str, seams.Field]]:
    """The shapes upstream of the gateway that give every input, and each input's field."""
    shapes = _upstream_shapes(process, node)
    givers: dict[str, dict[URIRef, seams.Field]] = {}
    for iri, shape in sorted(shapes.items()):
        for field in shape.fields():
            if field.name in s.inputs:
                givers.setdefault(field.name, {})[iri] = field
    for name in s.inputs:
        if name not in givers:
            raise SuggestionError(
                node.iri, SEAM.reads, f"no shape a task upstream of {s.gateway!r} reads or writes has field {name!r}"
            )
    common = set.intersection(*(set(givers[name]) for name in s.inputs))
    if not common:
        raise SuggestionError(node.iri, SEAM.reads, f"no one upstream shape gives all of {list(s.inputs)}")
    chosen = sorted(common)
    fields = {name: givers[name][chosen[0]] for name in s.inputs}
    for name in s.inputs:
        paths = {givers[name][iri].iri for iri in chosen}
        if len(paths) > 1:
            raise SuggestionError(node.iri, SEAM.reads, f"field {name!r} has more than one sh:path upstream")
    return [shapes[iri] for iri in chosen], fields


def _type_ref(field: seams.Field) -> str:
    for type_ref, datatypes in sorted(TYPE_REF_DATATYPES.items()):
        if field.datatype in datatypes:
            return type_ref
    raise SuggestionError(field.iri, "sh:datatype", f"no DMN typeRef takes {field.datatype} of field {field.name!r}")


def _output_type(s: ConditionToDmn) -> str:
    """The typeRef every rule's output value is written in: FEEL strings, numbers or booleans."""

    def kind(value: str) -> str | None:
        if len(value) >= 2 and value[0] == value[-1] == '"':
            return "string"
        if value in ("true", "false"):
            return "boolean"
        try:
            float(value)
        except ValueError:
            return None
        return "number"

    kinds = {kind(rule.output) for rule in s.rules}
    if len(kinds) != 1 or None in kinds:
        values = [rule.output for rule in s.rules]
        raise SuggestionError(s.decision_id, "rules", f"outputs {values} are not all FEEL strings, numbers or booleans")
    return cast(str, kinds.pop())


def _labelled(text: str, like: Node | None) -> Literal:
    return Literal(text, lang=like.language) if isinstance(like, Literal) and like.language else Literal(text)


def build_change(model: seams.Model, suggestion: ConditionToDmn) -> Change:
    """The ``Change`` that applies ``suggestion`` to ``model`` (ADR-0028 section 4).

    The decision joins the DMN payload of the process's existing business-rule
    task, and its facts mirror that task's decision: the same graphs, types,
    ``seam:inModel`` and ``seam:detailedBy``. The new task, whose BPMN id is the
    decision id, mirrors the existing task. ``SuggestionError`` names an input no
    upstream shape gives, a field with no DMN type, an id the payloads already
    use, or a process with no single DMN payload."""
    s = suggestion
    process = next(p for p in model.processes if p.iri == s.process)
    node = next(n for n in process.gateways() if n.bpmn_id == s.gateway)
    tasks = [n for n in process.tasks() if n.tag == "businessRuleTask" and n.decided_by is not None]
    references = sorted(((n, cast(seams.Decision, n.decided_by)) for n in tasks), key=lambda t: str(t[0].iri))
    dmn_models = sorted({d.dmn_model for _, d in references})
    if len(dmn_models) != 1:
        found = [str(m) for m in dmn_models]
        raise SuggestionError(
            process.iri, SEAM.decidedBy, f"expected the process's decisions in one DMN model, found {found}"
        )
    ref_task, ref = references[0]
    shapes, fields = _input_shapes(process, node, s)
    types = {name: _type_ref(field) for name, field in fields.items()}
    labels = {name: field.label for name, field in fields.items()}
    output_type = _output_type(s)

    ds = model.ds
    namespace = str(ref.iri)[: -len(seams.local_name(ref.iri))]
    decision = URIRef(namespace + s.decision_id)
    task = process.element_iri(s.decision_id)
    flow = f"{s.decision_id}_to_{s.gateway}"
    if (decision, None, None) in ds or (task, None, None) in ds:
        raise SuggestionError(decision, "id", f"the model already states {decision} or {task}")
    dmn_model = dmn_models[0]
    g_decision = _graph(model, ref.iri, RDF.type, DEC.Decision)
    g_detail = _graph(model, ref.iri, SEAM.detailedBy, dmn_model)
    g_reads = _graph(model, ref.iri, SEAM.reads) if ds.value(ref.iri, SEAM.reads) is not None else g_detail
    g_task = _graph(model, ref_task.iri, RDF.type, PROC.BusinessRuleTask)
    g_link = _graph(model, ref_task.iri, SEAM.decidedBy, ref.iri)
    g_task_reads = _graph(model, ref_task.iri, SEAM.reads) if ref_task.reads else g_link

    adds: list[seams_edit.Quad] = [
        (decision, RDF.type, DEC.Decision, g_decision),
        (decision, RDFS.label, _labelled(s.decision_name, ds.value(ref.iri, RDFS.label)), g_decision),
        (decision, DEC.payloadElement, Literal(s.decision_id), g_decision),
        (decision, SEAM.inModel, dmn_model, g_decision),
        (decision, SEAM.detailedBy, dmn_model, g_detail),
        (task, RDF.type, PROC.BusinessRuleTask, g_task),
        (task, RDFS.label, _labelled(s.decision_name, ds.value(ref_task.iri, RDFS.label)), g_task),
        (task, SEAM.decidedBy, decision, g_link),
    ]
    if (ref_task.iri, SEAM.inModel, None) in ds:
        adds += [(task, SEAM.inModel, o, g_task) for o in sorted(ds.objects(ref_task.iri, SEAM.inModel), key=str)]
    adds += [(decision, SEAM.reads, shape.iri, g_reads) for shape in shapes]
    adds += [(task, SEAM.reads, shape.iri, g_task_reads) for shape in shapes]
    ref_input = ds.value(ref.iri, DEC.input)
    ref_output = ds.value(ref.iri, DEC.output)
    for name in s.inputs:
        binding = BNode(f"{s.decision_id}_input_{name}")
        adds += [(decision, DEC.input, binding, g_decision)]
        adds += [(binding, RDF.type, t, g_decision) for t in sorted(ds.objects(ref_input, RDF.type), key=str)]
        adds += [
            (binding, DEC.variable, Literal(name), g_decision),
            (binding, DEC.fromPath, fields[name].iri, g_decision),
        ]
    binding = BNode(f"{s.decision_id}_output")
    adds += [(decision, DEC.output, binding, g_decision)]
    adds += [(binding, RDF.type, t, g_decision) for t in sorted(ds.objects(ref_output, RDF.type), key=str)]
    adds += [
        (binding, DEC.variable, Literal(s.output), g_decision),
        (binding, DEC.processVariable, Literal(s.output), g_decision),
    ]

    bpmn_path, dmn_path = process.bpmn_path, ref.dmn_path
    bpmn = _bpmn_text(bpmn_path, bpmn_path.read_text(encoding="utf-8"), s, s.decision_id, flow, node.iri)
    dmn = _dmn_text(dmn_path, dmn_path.read_text(encoding="utf-8"), s, types, labels, output_type)
    return Change(seams_edit.Patch(adds=adds), tuple(sorted({bpmn_path: bpmn, dmn_path: dmn}.items())))


# ── the scratch check ──


@dataclass(frozen=True, order=True)
class ChangeFinding:
    """One reason a change fails: the check (``patch``, ``shacl``, ``decision`` or
    ``generate``), the subject and the predicate or fact, and why."""

    kind: str
    subject: str
    predicate: str
    detail: str


@dataclass(frozen=True)
class Verdicts:
    """What ``check_change`` found. ``validated``: the change applied and the copy
    passes the shapes and the decision checks; ``generated``: every generator ran;
    ``outputs``: how many files they produced."""

    validated: bool
    generated: bool
    outputs: int
    findings: tuple[ChangeFinding, ...]

    @property
    def passed(self) -> bool:
        return self.validated and self.generated


def _inside(project: Project, path: Path, what: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(project.root):
        raise ProjectError(f"{resolved}: the {what} is outside the project directory {project.root}")
    return resolved.relative_to(project.root)


def check_change(project: Project, change: Change, model: Path | None = None) -> Verdicts:
    """Write ``change`` into a scratch copy of ``project`` and check the copy.

    The model (``model``, else the project's) and the payloads must be inside the
    project directory. Nothing in the project is written."""
    return _check(project, change, model)[0]


#: A changed file: its POSIX path relative to the project root, its text before and after.
FileText = tuple[str, str, str]


def _check(project: Project, change: Change, model: Path | None) -> tuple[Verdicts, tuple[FileText, ...]]:
    """``check_change``'s verdicts and the text of every file the change wrote in the copy."""
    model_rel = _inside(project, resolve_model(project, model), "model")
    payloads = [(_inside(project, path, "payload"), text) for path, text in change.payloads]
    project_rel = project.path.relative_to(project.root)
    with tempfile.TemporaryDirectory(prefix="seams-suggest-") as tmp:
        root = Path(tmp).resolve() / "project"
        shutil.copytree(project.root, root, ignore=_SCRATCH_IGNORE, symlinks=True)
        scratch, scratch_model = load_project(root / project_rel), root / model_rel
        files = load_model(scratch_model, ONTOLOGY_DIR).files
        try:
            records = [seams_edit.apply(files, change.patch)]
            for rel, text in payloads:
                records.append(seams_edit.save_payload(files, root / rel, text))
        except seams_edit.PatchError as err:
            finding = ChangeFinding("patch", _scrub(err.subject, root), err.predicate, _scrub(err.detail, root))
            return Verdicts(False, False, 0, (finding,)), ()
        texts: list[FileText] = []
        for path in sorted({edit.path.resolve() for record in records for edit in record.files}):
            rel = path.relative_to(root)
            before = (project.root / rel).read_text(encoding="utf-8")
            texts.append((rel.as_posix(), before, path.read_text(encoding="utf-8")))
        return _verdicts(scratch, scratch_model, root), tuple(texts)


def _scrub(text: str, root: Path) -> str:
    """``text`` with the scratch directory taken out of its paths."""
    return text.replace(f"{root.as_uri()}/", "").replace(f"{root}/", "")


def _verdicts(project: Project, model: Path, root: Path) -> Verdicts:
    findings: list[ChangeFinding] = []
    try:
        for f in check_shapes(model_graph(model, ONTOLOGY_DIR), ONTOLOGY_DIR / "shapes" / "seam-shapes.ttl"):
            if f.kind == "shacl":
                subject, predicate, detail = (f.detail.split(" ", 2) + ["", ""])[:3]
                findings.append(ChangeFinding("shacl", subject, predicate, detail))
        for d in seams.decision_findings(load_model(model, ONTOLOGY_DIR)):
            findings.append(ChangeFinding("decision", d.subject, d.fact, d.message))
    except ProjectError as err:
        findings.append(ChangeFinding("shacl", "model", "load", _scrub(str(err), root)))
    validated = not findings
    try:
        outputs = len(generate_project(project, model).files)
    except GeneratorError as err:
        findings.append(ChangeFinding("generate", str(err.subject), str(err.predicate), _scrub(err.detail, root)))
        return Verdicts(validated, False, 0, tuple(sorted(findings)))
    except ResolutionError as err:
        findings.append(ChangeFinding("generate", err.subject, err.predicate, _scrub(err.detail, root)))
        return Verdicts(validated, False, 0, tuple(sorted(findings)))
    return Verdicts(validated, True, outputs, tuple(sorted(findings)))


# ── the prompt ──

TEMPLATE_NAME = "suggest"
TEMPLATE_VERSION = 1
TEMPLATE_FILE = f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}.txt"


class NothingToSuggest(Exception):
    """No gateway of the model has a condition that reads a name no upstream decision outputs."""


@dataclass(frozen=True)
class SuggestPrompt:
    """An assembled prompt: its text, ``<name>-v<version>``, the model hash and
    the IRIs of the gateways it offers, sorted."""

    text: str
    template: str
    model_hash: str
    gateways: tuple[str, ...]


def _decided(model: seams.Model, process: Process, node: FlowNode) -> set[str]:
    """The process variables a decision upstream of ``node`` outputs. Its input
    variables do not count: a condition over them still computes inline."""
    ds = model.ds
    names: set[str] = set()
    for n in _upstream(process, node):
        decision = n.decided_by if n.tag == "businessRuleTask" else None
        if decision is None:
            continue
        for binding in ds.objects(decision.iri, DEC.output):
            value = ds.value(binding, DEC.processVariable)
            if value is not None:
                names.add(str(value))
    return names


def inline_gateways(model: seams.Model) -> list[tuple[Process, FlowNode]]:
    """The gateways whose outgoing conditions read a name no upstream decision
    outputs (a form field, for example), sorted by IRI. A condition that is not
    Python is left to ``decision_findings``."""
    found: list[tuple[Process, FlowNode]] = []
    for process in model.processes:
        for node in process.gateways():
            names: set[str] = set()
            for flow in node.outgoing:
                if not flow.condition:
                    continue
                try:
                    names.update(condition_names(flow.condition))
                except SyntaxError:
                    continue
            if names - _decided(model, process, node):
                found.append((process, node))
    return sorted(found, key=lambda pn: str(pn[1].iri))


def _gateway_block(process: Process, node: FlowNode) -> str:
    lines = [f"gateway: {node.bpmn_id}", f"iri: {node.iri}", f"name: {node.name or '-'}", "outgoing flows:"]
    for flow in sorted(node.outgoing, key=lambda f: f.id):
        lines.append(f"  {flow.id} -> {flow.target}: {flow.condition or '(no condition)'}")
    lines.append("fields upstream (shape, field name, DMN typeRef, label):")
    for iri, shape in _upstream_shapes(process, node).items():
        for field in sorted(shape.fields(), key=lambda f: f.name):
            type_ref = next((t for t, d in sorted(TYPE_REF_DATATYPES.items()) if field.datatype in d), "-")
            lines.append(f"  {iri} {field.name} {type_ref} {json.dumps(field.label, ensure_ascii=False)}")
    return "\n".join(lines)


def _decision_blocks(model: seams.Model, root: Path) -> list[str]:
    texts: dict[Path, tuple[str, _El]] = {}
    blocks: list[str] = []
    for decision in sorted(model.decisions, key=lambda d: str(d.iri)):
        path = decision.dmn_path
        if path not in texts:
            text = path.read_text(encoding="utf-8")
            texts[path] = (text, _scan(path, text))
        text, scanned = texts[path]
        element = next(
            el for el in scanned.iter() if el.local == "decision" and el.attrs.get("id") == decision.decision_id
        )
        rel = Path(os.path.relpath(path.resolve(), root)).as_posix()
        head = f"decision: {decision.iri}\npayload: {rel}#{decision.decision_id}\n"
        blocks.append(quote("decision", head + _indent(text, element) + text[element.start : element.end]))
    return blocks


def build_prompt(project: Project, model: Path | None = None) -> SuggestPrompt:
    """The ``condition-to-dmn`` prompt for the project's model: every gateway
    ``inline_gateways`` finds, its flows and the fields upstream of it, and the
    model's decisions as DMN, each in a DATA block. ``NothingToSuggest`` when
    there is no such gateway."""
    trig = resolve_model(project, model)
    loaded = load_model(trig, ONTOLOGY_DIR)
    gateways = inline_gateways(loaded)
    if not gateways:
        raise NothingToSuggest("no gateway condition reads a name that no upstream decision outputs")
    source = resources.files(__package__).joinpath("prompts", TEMPLATE_FILE).read_text(encoding="utf-8")
    decisions = _decision_blocks(loaded, project.root)
    text = Template(source).substitute(
        model_hash=loaded.hash,
        gateways="\n\n".join(quote("gateway", _gateway_block(p, n)) for p, n in gateways),
        decisions="\n\n".join(decisions) if decisions else "(none)",
    )
    return SuggestPrompt(
        text=text,
        template=f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}",
        model_hash=loaded.hash,
        gateways=tuple(str(n.iri) for _, n in gateways),
    )


# ── suggest, list, accept ──

SUGGESTIONS_DIR = Path(".seams") / "suggestions"
CACHE_DIR = Path(".seams") / "suggest-cache"
SUGGESTION_FILE = "suggestion.json"


class StaleSuggestion(Exception):
    """The model changed since the suggestion was made; the message says how."""


@dataclass(frozen=True)
class Suggested:
    """What ``suggest`` did. ``findings`` say why the answer was rejected (the
    ``suggestion`` kind for an answer the model does not allow); ``files`` are
    the changed files, relative to the project root; ``stored`` the pending
    suggestion's directory, or None when it was rejected."""

    id: str
    template: str
    provider: str
    model_hash: str
    cache_hit: bool
    gateway: str | None
    files: tuple[str, ...]
    verdicts: Verdicts | None
    findings: tuple[ChangeFinding, ...]
    stored: str | None

    @property
    def passed(self) -> bool:
        return self.stored is not None


def suggestion_id(model_hash: str, template: str, provider: str, response: str) -> str:
    return hashlib.sha256("\n".join((model_hash, template, provider, response)).encode("utf-8")).hexdigest()


def _rejected(err: ResolutionError) -> ChangeFinding:
    return ChangeFinding("suggestion", str(err.subject), str(err.predicate), err.detail or str(err))


def _diff(rel: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{rel}", f"b/{rel}"
    )
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def _store(project: Project, ident: str, record: Mapping[str, object], texts: Iterable[FileText]) -> Path:
    """Write the pending suggestion's directory whole: into a sibling first, then renamed."""
    target = project.root / SUGGESTIONS_DIR / ident
    partial = target.with_name(f"{ident}.partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    (partial / SUGGESTION_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for rel, before, after in texts:
        diff = partial / f"{rel}.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text(_diff(rel, before, after), encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    return target


def suggest(project: Project, model: Path | None = None, provider: str | None = None) -> Suggested:
    """Ask the provider for a suggestion, build and check its change, and store
    it pending when it passes (ADR-0028 sections 1, 5 and 6).

    The provider's answer is cached by (model hash, template, provider) once it
    passes; a rejected answer is reported, and neither it nor anything else is
    written. ``ProposeError`` when the provider fails; ``NothingToSuggest`` when
    no gateway qualifies; ``ProjectError`` when no provider is set."""
    provider = provider if provider is not None else project.provider
    if provider is None or not provider.strip():
        raise ProjectError(f"no provider: set `[propose] provider` in {project.path} or pass --provider")
    trig = resolve_model(project, model)
    prompt = build_prompt(project, model)
    cached = project.root / CACHE_DIR / f"{cache_key(prompt.model_hash, prompt.template, provider)}.txt"
    cache_hit = cached.is_file()
    response = cached.read_text(encoding="utf-8") if cache_hit else call_provider(provider, prompt.text, "suggestion")
    ident = suggestion_id(prompt.model_hash, prompt.template, provider, response)

    base = Suggested(ident, prompt.template, provider, prompt.model_hash, cache_hit, None, (), None, (), None)
    loaded = load_model(trig, ONTOLOGY_DIR)
    try:
        suggestion = parse_suggestion(loaded, extract_draft(response))
        process = next(p for p in loaded.processes if p.iri == suggestion.process)
        gateway = str(process.element_iri(suggestion.gateway))
        change = build_change(loaded, suggestion)
    except ResolutionError as err:
        return replace(base, findings=(_rejected(err),))
    verdicts, texts = _check(project, change, model)
    files = tuple(rel for rel, _, _ in texts)
    if not verdicts.passed:
        return replace(base, gateway=gateway, files=files, verdicts=verdicts, findings=verdicts.findings)
    record: dict[str, object] = {
        "id": ident,
        "kind": KINDS[0],
        "gateway": gateway,
        "model": _inside(project, trig, "model").as_posix(),
        "model_hash": prompt.model_hash,
        "template": prompt.template,
        "provider": provider,
        "response": response,
        "files": list(files),
        "validated": verdicts.validated,
        "generated": verdicts.generated,
        "outputs": verdicts.outputs,
    }
    stored = _store(project, ident, record, texts)
    if not cache_hit:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(response, encoding="utf-8")
    return replace(
        base,
        gateway=gateway,
        files=files,
        verdicts=verdicts,
        stored=stored.relative_to(project.root).as_posix(),
    )


@dataclass(frozen=True)
class Pending:
    """A stored suggestion: its id, kind, gateway IRI, the model hash it was
    made for, its changed files, and whether that hash is still the model's."""

    id: str
    kind: str
    gateway: str
    model_hash: str
    files: tuple[str, ...]
    current: bool


def _read_pending(path: Path, model_hash: str) -> Pending:
    try:
        data = json.loads((path / SUGGESTION_FILE).read_text(encoding="utf-8"))
        files = cast(list[str], data["files"])
        return Pending(
            str(data["id"]),
            str(data["kind"]),
            str(data["gateway"]),
            str(data["model_hash"]),
            tuple(str(f) for f in files),
            data["model_hash"] == model_hash,
        )
    except (ValueError, KeyError, TypeError) as err:
        raise ProjectError(f"{path / SUGGESTION_FILE}: not a stored suggestion: {err}") from err


def pending(project: Project, model: Path | None = None) -> list[Pending]:
    """The stored suggestions, by id, each marked current or stale against the model."""
    folder = project.root / SUGGESTIONS_DIR
    if not folder.is_dir():
        return []
    model_hash = seams.model_hash(resolve_model(project, model))
    return [
        _read_pending(path, model_hash)
        for path in sorted(folder.iterdir())
        if path.is_dir() and (path / SUGGESTION_FILE).is_file()
    ]


@dataclass(frozen=True)
class Accepted:
    """What ``accept`` did: the suggestion id, the re-check's verdicts and the
    files written (relative to the project root; none when the re-check failed)."""

    id: str
    verdicts: Verdicts
    files: tuple[str, ...]


def _find(project: Project, ident: str) -> Path:
    folder = project.root / SUGGESTIONS_DIR
    found = (
        [p for p in sorted(folder.iterdir()) if p.name.startswith(ident) and (p / SUGGESTION_FILE).is_file()]
        if ident and folder.is_dir()
        else []
    )
    if len(found) != 1:
        problem = "no" if not found else "more than one"
        raise ProjectError(f"{problem} pending suggestion matches {ident!r} in {SUGGESTIONS_DIR.as_posix()}")
    return found[0]


def accept(project: Project, model: Path | None, ident: str) -> Accepted:
    """Apply the pending suggestion ``ident`` (an id or a unique prefix) through
    ``seams_edit`` (ADR-0028 section 7).

    ``StaleSuggestion`` when the model's hash is not the one the suggestion was
    made for. The change is rebuilt from the stored answer and checked again in
    a scratch copy; only when it passes are the TriG files and payloads written
    (all or none) and the pending directory removed."""
    trig = resolve_model(project, model)
    folder = _find(project, ident)
    loaded = load_model(trig, ONTOLOGY_DIR)
    stored = _read_pending(folder, loaded.hash)
    if not stored.current:
        raise StaleSuggestion(
            f"suggestion {stored.id} was made for model {stored.model_hash}, but the model is now {loaded.hash};"
            " run seams suggest again"
        )
    data = json.loads((folder / SUGGESTION_FILE).read_text(encoding="utf-8"))
    try:
        change = build_change(loaded, parse_suggestion(loaded, extract_draft(str(data["response"]))))
    except ResolutionError as err:
        return Accepted(stored.id, Verdicts(False, False, 0, (_rejected(err),)), ())
    verdicts = check_change(project, change, model)
    if not verdicts.passed:
        return Accepted(stored.id, verdicts, ())
    records: list[seams_edit.EditRecord] = []
    try:
        records.append(seams_edit.apply(loaded.files, change.patch))
        for path, text in change.payloads:
            records.append(seams_edit.save_payload(loaded.files, path, text))
    except seams_edit.PatchError:
        for record in reversed(records):
            seams_edit.undo(record)
        raise
    written = sorted({_inside(project, e.path, "file").as_posix() for r in records for e in r.files})
    shutil.rmtree(folder)
    return Accepted(stored.id, verdicts, tuple(written))


__all__ = [
    "CACHE_DIR",
    "KINDS",
    "SUGGESTIONS_DIR",
    "SUGGESTION_FILE",
    "Accepted",
    "Change",
    "ChangeFinding",
    "ConditionToDmn",
    "DmnRule",
    "NothingToSuggest",
    "Pending",
    "StaleSuggestion",
    "SuggestPrompt",
    "Suggested",
    "SuggestionError",
    "Verdicts",
    "accept",
    "build_change",
    "build_prompt",
    "check_change",
    "inline_gateways",
    "parse_suggestion",
    "pending",
    "suggest",
    "suggestion_id",
]
