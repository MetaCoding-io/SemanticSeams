"""The derived event-storm view (backlog B4).

``derive(model, process)`` reads one process's event-storm timeline from
graph facts alone, through the ``seams`` views, with no vocabulary of its own.
The process is named by its IRI, CURIE or local name, or by an ifml:Event
that seam:triggers it (``find_process``). Each step of the timeline is one of:

- a trigger: each ifml:Event that seam:triggers the process (by IRI) is a
  command, with the operation it seam:submitsTo. Its actors are the
  odrl:assignees of the policies seam:governedBy the event or that operation.
  A message start event that seam:subscribesTo a channel is the command of a
  process started by what seam:publishesTo the channel: it has no actor;
- a BPMN flow node, in BPMN step order (``Process.nodes()``). A user task is a
  command on its seam:completedOn form, submitting to what the form's events
  seam:submitsTo. Its actors are its lane and the assignees of the policies
  governing it. The node's seam:writes shapes are aggregates (with their
  sh:targetClass, seam:storedIn and seam:lifecycle). Its seam:fires
  transition is the domain event (the state:from states, the state:to
  state). Its seam:decidedBy decision is a DMN decision. Its seam:publishesTo
  channels are published, and each process whose message start event
  seam:subscribesTo one is started.

A node with none of these facts is not a step. The read models are the IFML
pages and components that seam:reads an aggregate, with the GET operations
that seam:rendersComponent them, sorted by IRI. Entries within a step are
sorted by IRI.

A fact the view expects and cannot find is a gap, never dropped:
- a trigger with no actor;
- a user task with no actor or no form;
- an unlifted task;
- an aggregate no page or component reads;
- a channel nothing consumes or subscribes to;
- a process nothing starts.

``render(storm)`` is the timeline as Markdown. An unknown name raises
``GeneratorError`` naming it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import URIRef
from seams import (
    Channel,
    Component,
    Event,
    FlowNode,
    Model,
    Operation,
    Page,
    Process,
    ProcessElement,
    Shape,
    local_name,
)

from . import GeneratorError
from ._views import view_errors

#: The entry kinds of a step, in the order a step renders them.
KINDS = ("actor", "command", "aggregate", "domain event", "decision", "channel", "process started")


@dataclass(frozen=True)
class Entry:
    """One sticky note: its kind, the step it belongs to (None for a read
    model), the graph element it names and its one-line text."""

    kind: str
    step: int | None
    iri: URIRef
    text: str


@dataclass(frozen=True)
class Step:
    """One point on the timeline: a trigger event or a BPMN flow node."""

    index: int
    iri: URIRef
    name: str


@dataclass(frozen=True)
class Storm:
    """The event storm of ``process``. Each tuple is sorted by (step, IRI)."""

    process: URIRef
    label: str
    steps: tuple[Step, ...]
    actors: tuple[Entry, ...]
    commands: tuple[Entry, ...]
    aggregates: tuple[Entry, ...]
    events: tuple[Entry, ...]
    decisions: tuple[Entry, ...]
    channels: tuple[Entry, ...]
    processes: tuple[Entry, ...]
    read_models: tuple[Entry, ...]
    gaps: tuple[str, ...]

    def entries(self) -> tuple[Entry, ...]:
        """Every step entry, by (step, kind order, IRI)."""
        found = [*self.actors, *self.commands, *self.aggregates, *self.events]
        found += [*self.decisions, *self.channels, *self.processes]
        return tuple(sorted(found, key=_order))


def _order(e: Entry) -> tuple[int, int, str, str]:
    return (
        -1 if e.step is None else e.step,
        KINDS.index(e.kind) if e.kind in KINDS else len(KINDS),
        str(e.iri),
        e.text,
    )


@dataclass
class _Builder:
    model: Model
    steps: list[Step] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    aggregates: dict[URIRef, Shape] = field(default_factory=dict)

    def step(self, iri: URIRef, name: str) -> int:
        self.steps.append(Step(len(self.steps) + 1, iri, name))
        return len(self.steps)

    def add(self, kind: str, step: int, iri: URIRef, text: str) -> None:
        entry = Entry(kind, step, iri, text)
        if entry not in self.entries:
            self.entries.append(entry)

    def gap(self, detail: str) -> None:
        if detail not in self.gaps:
            self.gaps.append(detail)

    def of(self, kind: str) -> tuple[Entry, ...]:
        return tuple(sorted((e for e in self.entries if e.kind == kind), key=_order))


def _is_iri(text: str) -> bool:
    return "://" in text or text.startswith("urn:") or ":" in text


def find_process(model: Model, name: object) -> Process:
    """The proc:Process named by an IRI, CURIE (``:approval_process``) or local
    name, or the one an ifml:Event so named seam:triggers. ``GeneratorError``
    naming ``name`` when it is neither, or triggers no process or several."""
    text = str(name)
    with view_errors():
        processes = list(model.processes)
        events = list(model.interfaces.events())
        if _is_iri(text):
            try:
                iri = model.curie(text)
            except Exception:  # an unbound prefix names nothing, like an unknown name
                iri = None
            found_p = [p for p in processes if p.iri == iri]
            found_e = [e for e in events if e.iri == iri]
        else:
            found_p = [p for p in processes if local_name(p.iri) == text]
            found_e = [e for e in events if local_name(e.iri) == text]
        if len(found_p) == 1 and not found_e:
            return found_p[0]
        if len(found_e) == 1 and not found_p:
            triggered = list(found_e[0].triggers_all)
            if len(triggered) == 1:
                return triggered[0]
            detail = (
                "triggers no proc:Process" if not triggered else f"triggers several: {[str(p.iri) for p in triggered]}"
            )
            raise GeneratorError(text, "seam:triggers", f"ifml:Event {detail}")
    if not found_p and not found_e:
        raise GeneratorError(text, "proc:Process", "no such proc:Process, or ifml:Event that seam:triggers one")
    names = sorted(str(x.iri) for x in [*found_p, *found_e])
    raise GeneratorError(text, "proc:Process", f"ambiguous: {names}")


def derive(model: Model, process: object) -> Storm:
    """The ``Storm`` of ``process`` (a ``Process`` or anything ``find_process`` takes)."""
    proc = process if isinstance(process, Process) else find_process(model, process)
    b = _Builder(model)
    with view_errors():
        triggers = sorted(proc.triggered_by, key=lambda e: str(e.iri))
        starts = list(proc.channel_starts)
        if not triggers and not starts:
            b.gap(
                f"{local_name(proc.iri)} has no seam:triggers event and no message start event "
                "seam:subscribesTo a channel, so nothing starts it"
            )
        for event in triggers:
            _trigger(b, event)
        for node in proc.nodes():
            _node(b, node)
        read_models = _read_models(b)
    return Storm(
        proc.iri,
        proc.label,
        tuple(b.steps),
        b.of("actor"),
        b.of("command"),
        b.of("aggregate"),
        b.of("domain event"),
        b.of("decision"),
        b.of("channel"),
        b.of("process started"),
        read_models,
        tuple(b.gaps),
    )


def _name(iri: URIRef) -> str:
    return f"`{local_name(iri)}`"


def _operation(op: Operation | None) -> str:
    if op is None:
        return ""
    method = f"{op.method} " if op.method else ""
    accepts = "" if op.accepts is None else f" [{local_name(op.accepts.iri)}]"
    return f" → {method}{_name(op.iri)}{accepts}"


def _trigger(b: _Builder, event: Event) -> None:
    ev = local_name(event.iri)
    step = b.step(event.iri, event.label)
    op = event.submits_to
    if op is None:
        b.gap(f"{ev} has no seam:submitsTo operation")
    b.add("command", step, event.iri, f"{event.label} ({_name(event.iri)}){_operation(op)}")
    policies = {p.iri: p for p in event.governed_by}
    for policy in [] if op is None else op.governed_by:
        policies.setdefault(policy.iri, policy)
    actors = 0
    for policy in policies.values():
        for perm in policy.permissions:
            if perm.assignee is not None:
                actors += 1
                b.add("actor", step, perm.assignee, f"{b.model.label(perm.assignee)} (policy {_name(policy.iri)})")
    if not actors:
        where = "" if op is None else f" or on {local_name(op.iri)}"
        b.gap(f"{ev} has no seam:governedBy policy with an odrl:assignee{where}, so no actor")


def _node(b: _Builder, node: FlowNode) -> None:
    nid = node.bpmn_id
    if node.element is None:
        if node.node.is_task:
            b.gap(f"BPMN node {nid} has no graph element")
        return
    pending: list[tuple[str, URIRef, str]] = []

    channel = node.starts_from
    if channel is not None:
        pending.append(
            ("command", node.iri, f"{node.name or nid} ({_name(node.iri)}) on channel {_publishers(channel)}")
        )
    if node.tag == "userTask":
        pending += _user_task(b, node)

    for shape in node.writes:
        b.aggregates.setdefault(shape.iri, shape)
        pending.append(("aggregate", shape.iri, _aggregate(shape)))

    transition = node.fires
    if transition is not None:
        sources = ", ".join(s.label for s in transition.from_states)
        lifecycle = transition.lifecycle
        within = "" if lifecycle is None else f", {lifecycle.label}"
        text = f"{transition.to_state.label} ({_name(transition.iri)}: {sources} → {transition.to_state.label}{within})"
        pending.append(("domain event", transition.iri, text))

    decision = node.decided_by
    if decision is not None:
        pending.append(("decision", decision.iri, f"{decision.label} ({_name(decision.iri)})"))

    for published in node.publishes_to:
        pending += _published(b, nid, published)

    if not pending:
        return
    step = b.step(node.iri, node.name or nid)
    for kind, iri, text in pending:
        b.add(kind, step, iri, text)


def _publishers(channel: Channel) -> str:
    """``channel`` and what seam:publishesTo it: an element of a process names that process."""
    found = []
    for el in sorted(channel.published_by, key=lambda e: str(e.iri)):
        process = el.process if isinstance(el, ProcessElement) else None
        found.append(_name(el.iri) + ("" if process is None else f" ({process.label})"))
    return _name(channel.iri) + (f", published by {', '.join(found)}" if found else "")


def _user_task(b: _Builder, node: FlowNode) -> list[tuple[str, URIRef, str]]:
    """The actors and the command of a user task (ADR-0009)."""
    nid = node.bpmn_id
    found: list[tuple[str, URIRef, str]] = []
    lane = node.lane
    if lane is not None:
        found.append(("actor", node.process.element_iri(lane.id), f"{lane.name or lane.id} (lane)"))
    for policy in b.model.policies:
        if node.iri in policy.governs.iris():
            for perm in policy.permissions:
                if perm.assignee is not None:
                    found.append(
                        ("actor", perm.assignee, f"{b.model.label(perm.assignee)} (policy {_name(policy.iri)})")
                    )
    if not found:
        b.gap(f"user task {nid} has no lane and no seam:governedBy policy with an odrl:assignee, so no actor")
    form = node.completed_on
    if form is None:
        b.gap(f"user task {nid} has no seam:completedOn form")
        return found
    ops = sorted({e.submits_to.iri: e.submits_to for e in form.events() if e.submits_to is not None}.items())
    via = "".join(_operation(op) for _, op in ops)
    found.append(("command", node.iri, f"{node.name or nid} ({_name(node.iri)}) on {_name(form.iri)}{via}"))
    return found


def _aggregate(shape: Shape) -> str:
    parts = [f"{shape.label} ({_name(shape.iri)})"]
    cls = shape.target_class
    if cls is not None:
        parts.append(f"class {_name(cls.iri)}")
    stores = sorted(_name(c.iri) for c in shape.stored_in)
    if stores:
        parts.append(f"stored in {', '.join(stores)}")
    lifecycle = shape.lifecycle
    if lifecycle is not None:
        parts.append(f"lifecycle {_name(lifecycle.iri)}")
    return ", ".join(parts)


def _published(b: _Builder, nid: str, channel: Channel) -> list[tuple[str, URIRef, str]]:
    found: list[tuple[str, URIRef, str]] = [("channel", channel.iri, f"{channel.label} ({_name(channel.iri)})")]
    started = sorted(
        (p for p in b.model.processes if any(s.channel.iri == channel.iri for s in p.channel_starts)),
        key=lambda p: str(p.iri),
    )
    if not started and not channel.consumed_by:
        b.gap(f"{local_name(channel.iri)} published by {nid} has no seam:consumes container or subscriber")
    for p in started:
        found.append(("process started", p.iri, f"{p.label} ({_name(p.iri)}) via {_name(channel.iri)}"))
    return found


def _read_models(b: _Builder) -> tuple[Entry, ...]:
    """The pages and components that seam:read an aggregate, by IRI."""
    readers: dict[URIRef, tuple[Page | Component, list[URIRef]]] = {}
    for iri in sorted(b.aggregates, key=str):
        shape = b.aggregates[iri]
        views = [r for r in shape.read_by if isinstance(r, Page | Component)]
        if not views:
            b.gap(f"{local_name(iri)} has no read model: no ifml page or component seam:reads it")
        for r in views:
            readers.setdefault(r.iri, (r, []))[1].append(iri)
    found: list[Entry] = []
    for iri in sorted(readers, key=str):
        view, shapes = readers[iri]
        text = f"{view.label} ({_name(iri)}) reads {', '.join(_name(s) for s in shapes)}"
        if isinstance(view, Component):
            queries = sorted(_name(op.iri) for op in view.rendered_by if op.method == "GET")
            if queries:
                text += f", served by GET {', '.join(queries)}"
        found.append(Entry("read model", None, iri, text))
    return tuple(found)


def render(storm: Storm) -> str:
    """The storm as a Markdown timeline, ``\\n`` newlines and a trailing newline."""
    lines = [f"# Event storm: {storm.label}", "", f"<!-- derived from {storm.process} -->", "", "## Timeline", ""]
    entries = storm.entries()
    if not storm.steps:
        lines.append("No step of the process has a fact to show.")
    for step in storm.steps:
        marker = f"{step.index}. "
        lines.append(f"{marker}**{step.name}** ({_name(step.iri)})")
        lines += [f"{' ' * len(marker)}- {e.kind}: {e.text}" for e in entries if e.step == step.index]
    lines += ["", "## Read models", ""]
    lines += [f"- {e.text}" for e in storm.read_models] or ["None."]
    lines += ["", "## Gaps", ""]
    lines += [f"- {g}" for g in storm.gaps] or ["None."]
    return "\n".join(lines) + "\n"
