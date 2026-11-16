"""Event-storm import (backlog X12, ADR-0046): a big-picture storm becomes a skeleton model.

The inverse of ``seams_gen.storm``. ``parse(text)`` reads the Markdown subset of the
``seams storm`` timeline that ADR-0046 section 1 fixes: the heading
``# Event storm: <label> (`<name>`)``, ``<!-- base: <IRI> -->``, ``## Timeline``, then
numbered steps ``<n>. **<label>** (`<name>`)`` with ``- <kind>: <label> (`<name>`)``
entries (actor, command, aggregate, domain event, policy; a command may end
``on `<form>```). A trailing ``## Read models`` or ``## Gaps`` section is skipped to the
end of the file. Every other line, and every storm the derivation could not give back
(section 2), is a ``GeneratorError`` naming the line number and quoting the line, so a
storm that parses always imports.

``to_patch(draft, out)`` is the skeleton as one ``seams_edit.Patch`` (section 3): the
facts ``seams_gen.storm.derive`` reads, under IRIs minted from the storm's base
(ADR-0002), each element ``seam:inModel`` its model in that model's graph and every
seam edge in the seams graph (ADR-0001). ``bpmn_payload(draft)`` is the BPMN file the
process is ``seam:detailedBy``: the BPMN steps as nodes in step order, with no sequence
flows. Nothing a storm does not say is written, so the seam shapes flag the skeleton
and ``seams generate`` refuses it.

``write(draft, out)`` writes the TriG file and the payload beside it through
``seams_edit.create``, which refuses a path that exists and writes both or neither, and
returns the gaps (section 4): those of ``derive`` on the written skeleton, then the
sequence flows and start and end events the process lacks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from xml.sax.saxutils import escape

from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
from rdflib.namespace import SH
from rdflib.term import Node
from seams import (
    DEC,
    DEFAULT_ONTOLOGY_DIR,
    IFML,
    MANIFEST_GRAPH,
    ODRL,
    PREFIXES,
    PROC,
    SEAM,
    STATE,
    load,
    shipped_versions,
    version_iri,
)

from seams_edit import Patch, Quad, create

from . import GeneratorError
from .storm import derive

#: The entry kinds a storm may state, as its lines write them (ADR-0046 section 1).
KINDS = ("actor", "command", "aggregate", "domain event", "policy")

#: The seams graph (ADR-0001), which holds every seam edge.
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_NAME = r"[A-Za-z_][A-Za-z0-9_.-]*"
_NAME_RE = re.compile(_NAME)
_HEADING = re.compile(r"# Event storm: (?P<label>.+) \(`(?P<name>[^`]*)`\)")
_BASE = re.compile(r"<!-- base: (?P<iri>\S*) -->")
_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+[/#]")
_TIMELINE = "## Timeline"
_TAILS = ("## Read models", "## Gaps")
_STEP = re.compile(r"(?P<number>\d+)\. \*\*(?P<label>.+)\*\* \(`(?P<name>[^`]*)`\)")
_ENTRY = re.compile(r"\s*- (?P<kind>[^:]+): (?P<body>.*)")
_STICKY = re.compile(r"(?P<label>.+) \(`(?P<name>[^`]*)`\)(?: on `(?P<form>[^`]*)`)?")

# Each BPMN step's tag in the payload and its lifted type (section 2).
_USER, _RULE, _SERVICE = "userTask", "businessRuleTask", "serviceTask"
_LIFTED = {_USER: PROC.UserTask, _RULE: PROC.BusinessRuleTask, _SERVICE: PROC.ServiceTask}

# The models, by suffix of the process name: notation, and the label word after the
# process label (the notation's local name).
_MODELS = {
    "bpmn": SEAM.BPMN,
    "ifml": SEAM.IFML,
    "data": SEAM.ShapeGraph,
    "lifecycle": SEAM.Statechart,
    "dmn": SEAM.DMN,
}


@dataclass(frozen=True)
class Sticky:
    """One entry of a step: its kind, label and name, the form of a command
    (``on `form```, else None) and the line it is on."""

    kind: str
    label: str
    name: str
    form: str | None
    line: int


@dataclass(frozen=True)
class DraftStep:
    """One numbered step and its entries, in the order the storm writes them."""

    index: int
    label: str
    name: str
    line: int
    entries: tuple[Sticky, ...]

    def of(self, kind: str) -> tuple[Sticky, ...]:
        return tuple(e for e in self.entries if e.kind == kind)

    @property
    def command(self) -> Sticky | None:
        found = self.of("command")
        return found[0] if found else None

    @property
    def policy(self) -> Sticky | None:
        found = self.of("policy")
        return found[0] if found else None

    @property
    def is_trigger(self) -> bool:
        """A command with no ``on`` form: an ifml:Event that seam:triggers the process."""
        command = self.command
        return command is not None and command.form is None

    @property
    def tag(self) -> str:
        """The BPMN element of a BPMN step: a user task, business-rule task or service task."""
        command = self.command
        if command is not None and command.form is not None:
            return _USER
        return _RULE if self.policy is not None else _SERVICE


@dataclass(frozen=True)
class StormDraft:
    """A parsed storm: the process label and name, the base IRI, the steps in order."""

    label: str
    name: str
    base: str
    steps: tuple[DraftStep, ...]

    def iri(self, name: str) -> URIRef:
        return URIRef(self.base + name)

    def model(self, suffix: str) -> URIRef:
        return self.iri(f"{self.name}_{suffix}")

    def element(self, step: DraftStep) -> URIRef:
        """The step's graph element: the trigger event, or the lifted BPMN node (ADR-0002)."""
        if step.is_trigger:
            return self.iri(step.name)
        return URIRef(f"{self.model('bpmn')}#{step.name}")

    @property
    def payload_name(self) -> str:
        """The BPMN payload's file name, beside the TriG file."""
        return f"{self.name}.bpmn"


def _fail(number: int, line: str, detail: str) -> NoReturn:
    """The one parse error: the line number, the line quoted, and what is wrong."""
    raise GeneratorError(f"line {number}", f'"{line.strip()}"', detail)


def _check_name(number: int, line: str, name: str, what: str) -> None:
    if not _NAME_RE.fullmatch(name):
        _fail(number, line, f"{what} name `{name}` is not a BPMN id and local name ({_NAME})")


# ── parsing ──


@dataclass
class _Step:
    index: int
    label: str
    name: str
    line: int
    entries: list[Sticky]


def parse(text: str) -> StormDraft:
    """The storm in ``text``; ``GeneratorError`` naming the line on anything else."""
    lines = text.splitlines()
    label = name = base = None
    timeline: int | None = None
    steps: list[_Step] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        stripped = line.strip()
        if label is None:
            match = _HEADING.fullmatch(stripped)
            if match is None:
                _fail(number, line, "expected the heading # Event storm: <label> (`<name>`)")
            label, name = match["label"].strip(), match["name"]
            _check_name(number, line, name, "the process")
            continue
        if base is None:
            match = _BASE.fullmatch(stripped)
            if match is None:
                _fail(number, line, "expected <!-- base: <IRI> --> after the heading")
            if not _IRI.fullmatch(match["iri"]):
                _fail(number, line, f"base <{match['iri']}> is not an absolute IRI ending in / or #")
            base = match["iri"]
            continue
        if timeline is None:
            if stripped != _TIMELINE:
                _fail(number, line, f"expected {_TIMELINE} after the base")
            timeline = number
            continue
        if stripped in _TAILS:
            break
        step = _STEP.fullmatch(stripped)
        if step is not None:
            expected = len(steps) + 1
            if int(step["number"]) != expected:
                _fail(number, line, f"step number {step['number']} is out of sequence: expected {expected}")
            _check_name(number, line, step["name"], "the step")
            steps.append(_Step(expected, step["label"].strip(), step["name"], number, []))
            continue
        entry = _ENTRY.fullmatch(line)
        if entry is None:
            _fail(number, line, "expected a numbered step <n>. **<label>** (`<name>`) or an entry - <kind>: ...")
        if not steps:
            _fail(number, line, "an entry before the first step")
        steps[-1].entries.append(_sticky(number, line, entry["kind"], entry["body"]))
    end = len(lines) + 1
    if label is None or name is None:
        _fail(end, "", "end of file: expected the heading # Event storm: <label> (`<name>`)")
    if base is None:
        _fail(end, "", "end of file: expected <!-- base: <IRI> --> after the heading")
    if timeline is None:
        _fail(end, "", f"end of file: expected {_TIMELINE} after the base")
    if not steps:
        _fail(timeline, _TIMELINE, "the timeline has no step")
    draft = StormDraft(label, name, base, tuple(_draft_step(s) for s in steps))
    _check(draft, lines)
    return draft


def _sticky(number: int, line: str, kind: str, body: str) -> Sticky:
    if kind not in KINDS:
        _fail(number, line, f"unknown entry kind {kind!r}: expected one of {', '.join(KINDS)}")
    if "→" in body:
        _fail(number, line, "a command's operation (→ ...) is not imported: the skeleton has no operations")
    match = _STICKY.fullmatch(body.strip())
    if match is None:
        _fail(number, line, f"expected - {kind}: <label> (`<name>`)")
    form = match["form"]
    if form is not None and kind != "command":
        _fail(number, line, f"only a command names a form (on `<form>`), not a {kind}")
    _check_name(number, line, match["name"], f"the {kind}")
    if form is not None:
        _check_name(number, line, form, "the form")
    return Sticky(kind, match["label"].strip(), match["name"], form, number)


def _draft_step(step: _Step) -> DraftStep:
    return DraftStep(step.index, step.label, step.name, step.line, tuple(step.entries))


def _check(draft: StormDraft, lines: list[str]) -> None:
    """The storm rules of ADR-0046 section 2, so the derivation gives the storm back."""

    def at(number: int) -> str:
        return lines[number - 1]

    names = _Names(draft)
    seen_bpmn: DraftStep | None = None
    last_trigger: DraftStep | None = None
    for step in draft.steps:
        line = at(step.line)
        if not step.entries:
            _fail(step.line, line, "a step with no entry: the derivation would not show it")
        for kind in ("command", "policy"):
            if len({(e.name, e.form) for e in step.of(kind)}) > 1:
                extra = step.of(kind)[1]
                _fail(extra.line, at(extra.line), f"a step has at most one {kind}")
        command, policy = step.command, step.policy
        if command is not None and policy is not None:
            _fail(policy.line, at(policy.line), "a step has a command or a policy, not both")
        if step.is_trigger:
            if seen_bpmn is not None:
                _fail(step.line, line, f"a trigger step comes before every BPMN step (step {seen_bpmn.index} is one)")
            if last_trigger is not None and str(draft.element(last_trigger)) > str(draft.element(step)):
                _fail(
                    step.line, line, f"trigger steps are in IRI order: `{step.name}` sorts before `{last_trigger.name}`"
                )
            last_trigger = step
            for e in step.entries:
                if e.kind not in ("actor", "command"):
                    _fail(e.line, at(e.line), f"a trigger step (a command with no form) has no {e.kind}")
        else:
            seen_bpmn = step
            if step.of("actor") and (command is None or command.form is None):
                actor = step.of("actor")[0]
                _fail(actor.line, at(actor.line), "an actor needs the step's command on a form (a user task)")
        if command is not None and command.name != step.name:
            _fail(command.line, at(command.line), f"the command's name must be the step's, `{step.name}`")
        names.step(step, line)
        for e in step.entries:
            names.entry(step, e, at(e.line))


class _Names:
    """Every local name the import mints, with its kind and label: a name met twice is
    one element, so its kind and label must agree."""

    def __init__(self, draft: StormDraft) -> None:
        self.found: dict[str, tuple[str, str | None]] = {}
        for suffix in _MODELS:
            self.found[f"{draft.name}_{suffix}"] = (f"the {suffix} model", None)
        self.found[draft.name] = ("the process", draft.label)

    def add(self, number: int, line: str, name: str, kind: str, label: str | None) -> None:
        known = self.found.get(name)
        if known is None:
            self.found[name] = (kind, label)
            return
        if known[0] != kind:
            _fail(number, line, f"`{name}` is {known[0]} already, so it cannot be {kind}")
        if label is not None and known[1] is not None and known[1] != label:
            _fail(number, line, f"`{name}` is labelled {known[1]!r} already, not {label!r}")
        if known[1] is None and label is not None:
            self.found[name] = (kind, label)

    def step(self, step: DraftStep, line: str) -> None:
        kind = "a trigger event" if step.is_trigger else "a BPMN step"
        self.add(step.line, line, step.name, kind, step.label)
        if step.of("actor"):
            self.add(step.line, line, f"{step.name}_policy", f"the policy of step {step.index}", None)

    def entry(self, step: DraftStep, e: Sticky, line: str) -> None:
        if e.kind == "command":
            kind = "a trigger event" if step.is_trigger else "a BPMN step"
            self.add(e.line, line, e.name, kind, e.label)
            if e.form is not None:
                self.add(e.line, line, e.form, "a form", None)
        elif e.kind == "domain event":
            self.add(e.line, line, e.name, "a domain event", e.label)
            self.add(e.line, line, f"{e.name}_state", f"the state of {e.name}", e.label)
        else:
            self.add(e.line, line, e.name, f"an {e.kind}" if e.kind[0] in "aeiou" else f"a {e.kind}", e.label)


# ── the skeleton ──


def _graph(model: URIRef) -> URIRef:
    return URIRef(f"urn:seams:graph:model:{str(model).rsplit('/', 1)[-1].rsplit('#', 1)[-1]}")


def to_patch(draft: StormDraft, out: str | os.PathLike[str]) -> Patch:
    """The skeleton of ``draft`` as quads to add; ``out`` is the TriG file the payload
    sits beside, so its ``seam:renderPayload`` resolves (and is written relative)."""
    payload = URIRef((Path(out).resolve().parent / draft.payload_name).as_uri())
    quads: list[Quad] = []
    used: set[str] = set()

    def model_fact(suffix: str, s: Node, p: Node, o: Node) -> None:
        used.add(suffix)
        quads.append((s, p, o, _graph(draft.model(suffix))))

    def element(suffix: str, iri: URIRef, kind: URIRef, label: str | None) -> None:
        model_fact(suffix, iri, RDF.type, kind)
        if label is not None:
            model_fact(suffix, iri, RDFS.label, Literal(label))
        model_fact(suffix, iri, SEAM.inModel, draft.model(suffix))

    def seam(s: Node, p: Node, o: Node) -> None:
        quads.append((s, p, o, SEAMS_GRAPH))

    process = draft.iri(draft.name)
    element("bpmn", process, PROC.Process, draft.label)
    seam(process, SEAM.detailedBy, draft.model("bpmn"))
    seam(draft.model("bpmn"), SEAM.renderPayload, payload)
    for step in draft.steps:
        node = draft.element(step)
        if step.is_trigger:
            element("ifml", node, IFML.Event, step.label)
            seam(node, SEAM.triggers, process)
        else:
            element("bpmn", node, _LIFTED[step.tag], step.label)
        command = step.command
        if command is not None and command.form is not None:
            form = draft.iri(command.form)
            element("ifml", form, IFML.Form, None)
            seam(node, SEAM.completedOn, form)
        actors = step.of("actor")
        policy = draft.iri(f"{step.name}_policy")
        if actors:
            seam(policy, RDF.type, ODRL.Policy)
            seam(node, SEAM.governedBy, policy)
        for actor in actors:
            party = draft.iri(actor.name)
            permission = BNode(f"{step.name}_policy_{actor.name}")
            seam(party, RDF.type, ODRL.Party)
            seam(party, RDFS.label, Literal(actor.label))
            seam(policy, ODRL.permission, permission)
            seam(permission, RDF.type, ODRL.Permission)
            seam(permission, ODRL.assignee, party)
            seam(permission, ODRL.action, ODRL.use)
            seam(permission, ODRL.target, node)
        for shape in step.of("aggregate"):
            element("data", draft.iri(shape.name), SH.NodeShape, shape.label)
            seam(node, SEAM.writes, draft.iri(shape.name))
        for event in step.of("domain event"):
            transition, state = draft.iri(event.name), draft.iri(f"{event.name}_state")
            element("lifecycle", transition, STATE.Transition, event.label)
            model_fact("lifecycle", transition, STATE.to, state)
            element("lifecycle", state, STATE.State, event.label)
            seam(node, SEAM.fires, transition)
        policy_sticky = step.policy
        if policy_sticky is not None:
            decision = draft.iri(policy_sticky.name)
            element("dmn", decision, DEC.Decision, policy_sticky.label)
            seam(node, SEAM.decidedBy, decision)
    for suffix, notation in _MODELS.items():
        if suffix not in used:
            continue
        model = draft.model(suffix)
        model_fact(suffix, model, RDF.type, SEAM.Model)
        model_fact(suffix, model, RDFS.label, Literal(f"{draft.label} ({str(notation).rsplit('#', 1)[-1]})"))
        seam(model, SEAM.notation, notation)
    shipped = shipped_versions(DEFAULT_ONTOLOGY_DIR)
    for vocabulary in sorted(_vocabularies(quads) & set(shipped)):
        quads.append((MANIFEST_GRAPH, OWL.imports, version_iri(vocabulary, shipped[vocabulary]), MANIFEST_GRAPH))
    quads.append((MANIFEST_GRAPH, RDF.type, OWL.Ontology, MANIFEST_GRAPH))
    return Patch(adds=quads)


def _vocabularies(quads: list[Quad]) -> set[str]:
    """The SemanticSeams vocabularies the quads use a term of, by name."""
    found: set[str] = set()
    for quad in quads:
        for term in quad[:3]:
            text = str(term)
            if isinstance(term, URIRef) and text.startswith("https://w3id.org/seams/") and "#" in text:
                found.add(text[len("https://w3id.org/seams/") :].split("#", 1)[0])
    return found


def prefixes(patch: Patch, base: str) -> dict[str, str]:
    """The prefixes of the header: each known vocabulary the patch uses, by name, then
    ``:`` for the storm's base."""
    known = {name: str(ns) for name, ns in PREFIXES.items()} | {"owl": str(OWL)}
    terms = {str(t) for quad in patch.adds for t in quad if isinstance(t, URIRef)}
    found = {name: ns for name, ns in sorted(known.items()) if name != "rdf" and any(t.startswith(ns) for t in terms)}
    found[""] = base
    return found


def bpmn_payload(draft: StormDraft) -> str:
    """The BPMN payload: one bpmn:process with the BPMN steps in step order, no flows."""
    model = str(draft.model("bpmn"))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<bpmn:definitions xmlns:bpmn="{_BPMN_NS}" id={_attr(draft.name + "_defs")} targetNamespace={_attr(model)}>',
        f'  <bpmn:process id={_attr(draft.name)} name={_attr(draft.label)} isExecutable="true">',
    ]
    for step in draft.steps:
        if not step.is_trigger:
            lines.append(f"    <bpmn:{step.tag} id={_attr(step.name)} name={_attr(step.label)} />")
    lines += ["  </bpmn:process>", "</bpmn:definitions>"]
    return "\n".join(lines) + "\n"


def _attr(value: str) -> str:
    return '"' + escape(value, {'"': "&quot;"}) + '"'


def write(draft: StormDraft, out: str | os.PathLike[str]) -> tuple[str, ...]:
    """Write the skeleton to ``out`` and its payload beside it, both or neither; return
    the gaps. ``seams_edit.PatchError`` when either file exists."""
    target = Path(out)
    patch = to_patch(draft, target)
    create(
        target,
        patch,
        prefixes=prefixes(patch, draft.base),
        payloads={target.resolve().parent / draft.payload_name: bpmn_payload(draft)},
    )
    return gaps(draft, target)


def gaps(draft: StormDraft, out: str | os.PathLike[str]) -> tuple[str, ...]:
    """What the written skeleton lacks: the gaps of ``derive`` on it, in its order, then
    the sequence flows and the start and end events of the process (ADR-0046 section 4)."""
    found = list(derive(load(out), draft.iri(draft.name)).gaps)
    payload = draft.payload_name
    found += [
        f"{draft.name} has no sequence flows: {payload} lists its BPMN steps in step order, unjoined",
        f"{draft.name} has no start event in {payload}",
        f"{draft.name} has no end event in {payload}",
    ]
    return tuple(dict.fromkeys(found))
