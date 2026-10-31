"""The as-designed sequence deriver (backlog U1, R008, D047).

``derive(model, event)`` turns an IFML event into Mermaid sequence diagrams
built only from graph facts, read through the ``seams`` views, with the step
order taken from the BPMN sequence flows of the process the event triggers
(research note docs/research/2026-10-29-uml-coverage-and-gaps.md, section 2):

- the actor is the assignee of each permission of the policies governing the
  event or the operation it submits to;
- the UI is the container that seam:presents the interaction model holding
  the event's component or page;
- the executing container ("API") exposes the operation the event
  seam:submitsTo and seam:executes the process it seam:triggers;
- each node of the walk adds its arrows: seam:writes to the containers the
  shape is seam:storedIn, seam:fires as a note, seam:decidedBy as a self call,
  seam:invokes to the container that exposes the operation, and
  seam:publishesTo to the containers that seam:consume the channel. The
  operation's seam:rendersComponent fragment goes back to the UI after the
  node that invokes the submitted operation. seam:reads draws nothing;
- a user task (ADR-0009) is its policy's assignee submitting the task's
  seam:completedOn form on the container presenting it, then the UI
  completing the task on the API with the form's output shape;
- a channel a message start event seam:subscribesTo is drawn as the API
  starting that process on its executing container (the walk stops there).

There is one diagram per path: the walk forks at each exclusive gateway with
more than one outgoing flow, in BPMN document order, notes the chosen flow,
and names the diagram ``<event>--<flow>--...`` (no alt fragments). A flow met
twice on one path ends it with a ``loop at <flow>`` gap; a parallel or
inclusive gateway is a gap and follows its first flow. Every arrow the
deriver cannot place (a missing fact) is recorded as a gap and rendered as a
``%% gap: <detail>`` line, never dropped.

As executed (backlog U4): ``executed(model, event, rows, run=None)`` draws
one recorded run from the worker's trace rows (``read_trace`` reads them from
a JSON file, an instance result or a bare list, or from an instance id in the
runtime's SQLite store, without importing seams_runtime, D049) on the same
actor, UI and API lifelines as ``derive``. Each row adds, in the worker's
order: the ``by`` identity as an actor completing the user task on its form,
the decision as a self call with its outputs, the invoke (a self call when in
process, else the call to the row's container and its delta count), the
streamed deltas and published event to the channel's consumers, the writes to
each seam:storedIn container, the fired transition and status as a note, and
the processes it started. An error row is a note. A row whose IRI is not an
element of the triggered process, an unknown container, channel or process,
or a row with no IRI is a gap. The diagram is ``<event>.executed`` with path
= the rows' task ids and a ``%% run: <id>`` header line when the run is known.

Command line: ``python -m seams_gen.sequence <trig> <event> --out DIR``
writes each diagram as ``DIR/<name>.mmd`` (``write_diagrams``, shared with
``seams sequence``), prints each path, and prints ``gap <name>: <detail>`` to
stderr per gap. ``--trace RUN`` (a trace JSON file or an instance id) with an
optional ``--db PATH`` (the SQLite store, default ``default_db()``) writes the
one as-executed ``DIR/<event>.executed.mmd`` instead; ``--db`` without
``--trace`` is a usage error (exit 2). An unreadable trace exits 2. Gaps are an audit, not a failure: it exits 0 with them. A
GeneratorError (an unknown event included) or a model that cannot be read or
parsed exits 2 with ``python -m seams_gen.sequence: <message>`` on stderr; a
file that cannot be written exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import URIRef
from seams import Component, Container, Event, FlowNode, Model, Operation, Page, local_name
from seams.bpmn import SequenceFlow

from . import GeneratorError
from ._views import view_errors

#: The BPMN tags a publishesTo is drawn as a channel event from.
_EVENT_TAGS = ("intermediateThrowEvent", "endEvent")


@dataclass(frozen=True)
class Participant:
    """A lifeline: the graph element, its Mermaid id (local name) and label."""

    iri: URIRef
    id: str
    label: str
    actor: bool = False


@dataclass(frozen=True)
class Message:
    """One Mermaid statement (arrow or note) and the graph terms it was built from."""

    line: str
    terms: tuple[URIRef, ...]


@dataclass(frozen=True)
class SequenceDiagram:
    """One derived diagram: a path of ``event``'s process, its lifelines,
    messages in order and the facts it could not place."""

    name: str
    event: URIRef
    path: tuple[str, ...]
    participants: tuple[Participant, ...]
    messages: tuple[Message, ...]
    gaps: tuple[str, ...]
    #: True for an as-executed diagram (``executed``); its path is the row task ids.
    executed: bool = False
    #: The run (instance id) an as-executed diagram was drawn from, when known.
    run: str | None = None


@dataclass
class _Builder:
    model: Model
    participants: dict[URIRef, Participant] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def lifeline(self, iri: URIRef, *, actor: bool = False) -> str:
        found = self.participants.get(iri)
        if found is None:
            found = Participant(iri, local_name(iri), _text(self.model.label(iri)), actor)
            self.participants[iri] = found
        return found.id

    def arrow(self, sender: URIRef, receiver: URIRef, text: str, *terms: URIRef, reply: bool = False) -> None:
        a, b = self.lifeline(sender), self.lifeline(receiver)
        self.messages.append(Message(f"{a}{'-->>' if reply else '->>'}{b}: {text}", (sender, receiver, *terms)))

    def note(self, over: URIRef, text: str, *terms: URIRef) -> None:
        self.messages.append(Message(f"Note over {self.lifeline(over)}: {text}", (over, *terms)))

    def gap(self, detail: str) -> None:
        if detail not in self.gaps:
            self.gaps.append(detail)

    def diagram(self, name: str, event: URIRef, path: tuple[str, ...], **kw) -> SequenceDiagram:
        # Actors first, then the other lifelines in first-use order.
        ordered = [p for p in self.participants.values() if p.actor]
        ordered += [p for p in self.participants.values() if not p.actor]
        return SequenceDiagram(name, event, path, tuple(ordered), tuple(self.messages), tuple(self.gaps), **kw)


def _text(label: str) -> str:
    """A label safe to end a Mermaid statement (``;`` separates statements)."""
    return label.replace(";", ",").replace("\n", " ")


def _shape(shape) -> str:
    return "" if shape is None else f" [{local_name(shape.iri)}]"


def find_event(model: Model, event: object) -> Event:
    """The ifml:Event named by a CURIE (``:send_message``), a local name or a
    full IRI; ``GeneratorError`` naming it when the model has no such event."""
    text = str(event)
    events = model.interfaces.events()
    if "://" in text or text.startswith("urn:") or ":" in text:
        try:
            iri = model.curie(text)
        except Exception:  # an unbound prefix is an unknown event too
            iri = None
        found = [e for e in events if e.iri == iri]
    else:
        found = [e for e in events if local_name(e.iri) == text]
    if len(found) != 1:
        detail = "no such ifml:Event" if not found else f"ambiguous: {[str(e.iri) for e in found]}"
        raise GeneratorError(text, "ifml:Event", detail)
    return found[0]


def _ui(b: _Builder, event: Event) -> URIRef | None:
    """The container presenting the interaction model that holds the event's owner."""
    found = _presenter(event.owners)
    if found is None:
        b.gap(f"{local_name(event.iri)} has no interaction model seam:presents by one container")
    return found


def _presenter(owners) -> URIRef | None:
    """The one container presenting the interaction model of the pages or
    components ``owners``, or None when there is none or several."""
    containers: list[Container] = []
    for owner in owners:
        pages = [owner] if isinstance(owner, Page) else [owner.page] if isinstance(owner, Component) else []
        im = None
        while pages and im is None:  # a nested page sits in its parent's interaction model
            page = pages.pop(0)
            if page is not None:
                im = page.interaction_model
                pages += list(page.parents)
        presenter = None if im is None else im.presented_by
        if presenter is not None and presenter not in containers:
            containers.append(presenter)
    return containers[0].iri if len(containers) == 1 else None


def _actors(b: _Builder, event: Event, op: Operation | None) -> list[tuple[URIRef, URIRef]]:
    """(assignee, policy) for each permission of each policy governing the
    event, then of each governing the operation it submits to."""
    ev = local_name(event.iri)
    found: list[tuple[URIRef, URIRef]] = []
    policies = list(event.governed_by)
    for policy in [] if op is None else op.governed_by:
        if policy.iri not in [p.iri for p in policies]:
            policies.append(policy)
    if not policies:
        where = "" if op is None else f" or on {local_name(op.iri)}"
        b.gap(f"{ev} has no seam:governedBy policy{where}, so no actor")
    for policy in policies:
        assignees = [p.assignee for p in policy.permissions if p.assignee is not None]
        if not assignees:
            b.gap(f"{local_name(policy.iri)} governing {ev} has no odrl:assignee, so no actor")
        for a in assignees:
            if (a, policy.iri) not in found:
                found.append((a, policy.iri))
    return found


def _api(b: _Builder, event: Event, op: Operation | None) -> URIRef | None:
    """The executing container: exposes the submitted operation and executes the triggered process."""
    ev = local_name(event.iri)
    process = event.triggers
    exposers = [] if op is None else [c.iri for c in op.exposed_by]
    executors = [] if process is None else [c.iri for c in process.executed_by]
    if op is not None and not exposers:
        b.gap(f"{local_name(op.iri)} submitted by {ev} has no seam:exposes container")
    if process is not None and not executors:
        b.gap(f"{local_name(process.iri)} triggered by {ev} has no seam:executes container")
    if op is not None and process is not None and exposers and executors and exposers[0] != executors[0]:
        b.gap(
            f"{local_name(op.iri)} is exposed by {local_name(exposers[0])} but "
            f"{local_name(process.iri)} is executed by {local_name(executors[0])}"
        )
    found = exposers or executors
    return found[0] if found else None


#: Gateway tags that fork without choosing one flow: drawn as their first flow and a gap.
_FORK_TAGS = {"parallelGateway": "parallel", "inclusiveGateway": "inclusive", "complexGateway": "complex"}

#: More paths than this is a model the deriver will not enumerate.
MAX_PATHS = 256


@dataclass(frozen=True)
class _Path:
    """One walk through a process: each node with the flow chosen out of it
    when it is a forking exclusive gateway, the labels of those flows, and the
    gaps the walk met (loops, parallel forks)."""

    steps: tuple[tuple[FlowNode, SequenceFlow | None], ...]
    labels: tuple[str, ...]
    gaps: tuple[str, ...]


def derive(model: Model, event: object) -> list[SequenceDiagram]:
    """One ``SequenceDiagram`` per path of the process ``event`` triggers,
    from each start event through one outgoing flow of each exclusive gateway,
    in BPMN document order. ``event`` is a CURIE, local name or full IRI; an
    unknown one raises ``GeneratorError`` naming it."""
    ev = find_event(model, event)
    with view_errors():
        process = ev.triggers
        if process is None:
            return [_derive_path(model, ev, None)]
        return [_derive_path(model, ev, path) for path in _paths(process)]


def _derive_path(model: Model, event: Event, path: _Path | None) -> SequenceDiagram:
    b = _Builder(model)
    ev = local_name(event.iri)
    labels = () if path is None else path.labels
    name = "--".join([ev, *labels])
    op = event.submits_to
    actors = _actors(b, event, op)
    ui = _ui(b, event)
    process = event.triggers
    if op is None:
        b.gap(f"{ev} has no seam:submitsTo operation")
    if process is None:
        b.gap(f"{ev} has no seam:triggers process")
    api = _api(b, event, op)

    # Lifelines in first-use order: actors, then UI, then API.
    for actor, _ in actors:
        b.lifeline(actor, actor=True)
    first = ui if ui is not None else api
    for actor, policy in actors:
        if first is not None:
            b.arrow(actor, first, f"{ev} (policy: {local_name(policy)})", event.iri, policy)
    if not actors and first is not None:
        b.arrow(first, first, ev, event.iri)
    if ui is not None and api is not None and op is not None:
        method = f"{op.method} " if op.method else ""
        b.arrow(ui, api, f"{method}{local_name(op.iri)}{_shape(op.accepts)}", op.iri, *_iris(op.accepts))

    if api is None or process is None or path is None:
        return b.diagram(name, event.iri, labels)
    b.note(api, f"start {local_name(process.iri)}", process.iri)
    for gap in path.gaps:
        b.gap(gap)

    nodes = process.nodes()
    invokers = [n for n in nodes if op is not None and n.invokes is not None and n.invokes.iri == op.iri]
    if not invokers:
        _fragment(b, api, ui, op)

    for node, flow in path.steps:
        _node(b, api, ui, op, node)
        if node in invokers:
            _fragment(b, api, ui, op)
        if flow is not None:
            b.note(api, f"{node.name or node.bpmn_id}: {flow.name or flow.id}", process.iri)
    return b.diagram(name, event.iri, labels)


def _iris(*elements) -> tuple[URIRef, ...]:
    return tuple(e.iri for e in elements if e is not None)


def _paths(process) -> list[_Path]:
    """Every path from each start event of ``process`` (not a channel start)
    to an end, depth first, forking at each exclusive gateway with more than
    one outgoing flow in BPMN document order. A flow already on the path ends
    it with a ``loop at`` gap; a parallel or inclusive fork is a gap and
    follows only its first flow."""
    nodes = process.nodes()
    by_id = {n.bpmn_id: n for n in nodes}
    channel_starts = {s.iri for s in process.channel_starts}
    starts = [n for n in nodes if n.tag == "startEvent" and n.iri not in channel_starts]
    if not starts:
        return [_Path((), (), (f"{local_name(process.iri)} has no start event",))]
    found: list[_Path] = []

    def add(path: _Path) -> None:
        if len(found) >= MAX_PATHS:
            raise GeneratorError(str(process.iri), "proc:Process", f"more than {MAX_PATHS} paths")
        found.append(path)

    def walk(node, steps, labels, flows, gaps) -> None:
        out = node.outgoing
        if len(out) > 1 and node.tag == "exclusiveGateway":
            for flow in out:
                follow(flow, (*steps, (node, flow)), (*labels, flow.name or flow.id), flows, gaps)
            return
        if len(out) > 1:
            kind = _FORK_TAGS.get(node.tag, node.tag)
            gaps = (
                *gaps,
                f"{kind} gateway {node.bpmn_id} forks; only flow {out[0].name or out[0].id} is drawn, "
                f"not {', '.join(f.name or f.id for f in out[1:])}",
            )
        steps = (*steps, (node, None))
        if out:
            follow(out[0], steps, labels, flows, gaps)
        else:
            add(_Path(steps, labels, gaps))

    def follow(flow, steps, labels, flows, gaps) -> None:
        if flow.id in flows:
            add(_Path(steps, labels, (*gaps, f"loop at {flow.id}")))
            return
        target = by_id.get(flow.target)
        if target is None:
            add(_Path(steps, labels, (*gaps, f"flow {flow.id} targets no flow node {flow.target}")))
            return
        walk(target, steps, labels, flows | {flow.id}, gaps)

    for start in starts:
        prefix = (start.name or start.bpmn_id,) if len(starts) > 1 else ()
        walk(start, (), prefix, frozenset(), ())
    return found


def _fragment(b: _Builder, api: URIRef, ui: URIRef | None, op: Operation | None) -> None:
    if ui is None or op is None:
        return
    for component in op.renders:
        b.arrow(api, ui, f"{local_name(component.iri)} fragment", component.iri, op.iri, reply=True)


def _node(b: _Builder, api: URIRef, ui: URIRef | None, submitted: Operation | None, node: FlowNode) -> None:
    nid = node.bpmn_id
    if node.element is None:
        if node.node.is_task:
            b.gap(f"BPMN node {nid} has no graph element")
        return
    el = node.iri
    if node.tag == "userTask":
        _user_task(b, api, node)

    for shape in node.writes:
        stores = shape.stored_in
        if not stores:
            b.gap(f"{local_name(shape.iri)} written by {nid} has no seam:storedIn")
        for store in stores:
            b.arrow(api, store.iri, f"{nid} writes {local_name(shape.iri)}", el, shape.iri)

    transition = node.fires
    if transition is not None:
        b.note(api, local_name(transition.iri), el, transition.iri)

    decision = node.decided_by
    if decision is not None:
        b.arrow(api, api, f"{nid} (DMN {local_name(decision.iri)})", el, decision.iri)

    op = node.invokes
    if op is not None and (submitted is None or op.iri != submitted.iri):
        name = local_name(op.iri)
        exposers = [c.iri for c in op.exposed_by]
        if not exposers:
            b.gap(f"{name} invoked by {nid} has no seam:exposes container")
        for c in exposers:
            b.arrow(api, c, f"{nid}, {name}{_shape(op.accepts)}", el, op.iri, *_iris(op.accepts))
            if c != api:
                b.arrow(c, api, f"{name} returns{_shape(op.returns)}", op.iri, *_iris(op.returns), reply=True)

    for channel in node.publishes_to:
        consumers = [c.iri for c in channel.consumed_by]
        subscribers = _channel_processes(b.model, channel)
        if not consumers and not subscribers:
            b.gap(f"{local_name(channel.iri)} published by {nid} has no seam:consumes container or subscriber")
        if op is not None:
            text = f"{local_name(channel.iri)} ({channel.event_name} deltas)"
        else:
            text = f"{local_name(channel.iri)} ({_text(channel.label)} event)"
        for c in consumers:
            b.arrow(api, c, text, el, channel.iri, reply=True)
        for started in subscribers:
            executors = [c.iri for c in started.executed_by]
            if not executors:
                b.gap(f"{local_name(started.iri)} started by {local_name(channel.iri)} has no seam:executes container")
            for c in executors:
                b.arrow(
                    api,
                    c,
                    f"{local_name(channel.iri)} starts {local_name(started.iri)}",
                    el,
                    channel.iri,
                    started.iri,
                    reply=True,
                )


def _channel_processes(model: Model, channel) -> list:
    """The processes a message start event of which seam:subscribesTo ``channel``."""
    return [p for p in model.processes if any(s.channel.iri == channel.iri for s in p.channel_starts)]


def _user_task(b: _Builder, api: URIRef, node: FlowNode) -> None:
    """``<actor>->>UI: <task> on <form>`` and ``UI->>API: complete <task> [<output>]``
    (ADR-0009): the actor is the assignee of the policies governing the task,
    the UI the container presenting the page that holds its seam:completedOn form."""
    nid, el = node.bpmn_id, node.iri
    actors: list[tuple[URIRef, URIRef]] = []
    for policy in b.model.policies:
        if el in policy.governs.iris():
            actors += [(p.assignee, policy.iri) for p in policy.permissions if p.assignee is not None]
    if not actors:
        b.gap(f"user task {nid} has no seam:governedBy policy with an odrl:assignee, so no actor")
    form = node.completed_on
    if form is None:
        b.gap(f"user task {nid} has no seam:completedOn form")
        return
    ui = _presenter([form])
    if ui is None:
        b.gap(f"form {local_name(form.iri)} of {nid} has no interaction model seam:presents by one container")
        return
    for actor, _ in actors:
        b.lifeline(actor, actor=True)
    for actor, policy in actors or [(ui, None)]:
        b.arrow(actor, ui, f"{nid} on {local_name(form.iri)}", el, form.iri, *([policy] if policy else []))
    shapes = list(form.writes) or list(node.writes)
    output = shapes[0] if len(shapes) == 1 else None
    b.arrow(ui, api, f"complete {nid}{_shape(output)}", el, *_iris(output))


def render(diagram: SequenceDiagram) -> str:
    """The diagram as Mermaid text, ``\\n`` newlines and a trailing newline."""
    source = "executed from" if diagram.executed else "derived from"
    lines = ["sequenceDiagram", f"%% {source} {diagram.event}"]
    lines.append(f"%% path: {', '.join(diagram.path) if diagram.path else 'single'}")
    if diagram.run is not None:
        lines.append(f"%% run: {diagram.run}")
    lines += [f"%% gap: {g}" for g in diagram.gaps]
    for p in diagram.participants:
        lines.append(f"{'actor' if p.actor else 'participant'} {p.id} as {p.label}")
    lines += [m.line for m in diagram.messages]
    return "\n".join([lines[0], *(f"    {line}" for line in lines[1:])]) + "\n"


def file_name(diagram: SequenceDiagram) -> str:
    """``<name>.mmd``: ``<event local>.mmd`` for a single path,
    ``<event local>--<flow>[--<flow>].mmd`` otherwise, and
    ``<event local>.executed.mmd`` for an as-executed diagram."""
    return f"{diagram.name}.mmd"


def write_diagrams(diagrams: list[SequenceDiagram], out: Path) -> list[Path]:
    """Write each diagram to ``out/<file_name>`` (UTF-8, ``\\n`` newlines),
    creating ``out``; the paths written, in order."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in diagrams:
        path = out / file_name(d)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(d))
        paths.append(path)
    return paths


# ── as executed (backlog U4) ─────────────────────────────────────────────────


def executed(model: Model, event: object, rows: list[dict], *, run: str | None = None) -> SequenceDiagram:
    """The as-executed ``SequenceDiagram`` of one recorded run of the process
    ``event`` triggers, drawn from the worker's trace ``rows`` (one per BPMN
    element, in order) on the same lifelines as ``derive``. It is named
    ``<event>.executed`` and its path is the rows' task ids. A row the graph
    cannot place (an IRI that is not an element of the process, an unknown
    container, channel or process, a row with no IRI) is a gap, never dropped."""
    ev = find_event(model, event)
    with view_errors():
        return _executed(model, ev, rows, run)


def _executed(model: Model, event: Event, rows: list[dict], run: str | None) -> SequenceDiagram:
    b = _Builder(model)
    ev = local_name(event.iri)
    name = f"{ev}.executed"
    path = tuple(str(r.get("task") or "error") for r in rows)
    op = event.submits_to
    actors = _actors(b, event, op)
    ui = _ui(b, event)
    process = event.triggers
    if op is None:
        b.gap(f"{ev} has no seam:submitsTo operation")
    if process is None:
        b.gap(f"{ev} has no seam:triggers process")
    api = _api(b, event, op)

    for actor, _ in actors:
        b.lifeline(actor, actor=True)
    first = ui if ui is not None else api
    for actor, policy in actors:
        if first is not None:
            b.arrow(actor, first, f"{ev} (policy: {local_name(policy)})", event.iri, policy)
    if not actors and first is not None:
        b.arrow(first, first, ev, event.iri)
    if ui is not None and api is not None and op is not None:
        method = f"{op.method} " if op.method else ""
        b.arrow(ui, api, f"{method}{local_name(op.iri)}{_shape(op.accepts)}", op.iri, *_iris(op.accepts))
    if api is None or process is None:
        return b.diagram(name, event.iri, path, executed=True, run=run)
    b.note(api, f"start {local_name(process.iri)}", process.iri)

    nodes = {n.iri: n for n in process.nodes()}
    containers = {c.iri: c for c in model.architecture.containers()}
    channels = {c.iri: c for c in model.channels}
    processes = {p.iri: p for p in model.processes}
    for i, row in enumerate(rows, 1):
        _row(b, api, process, nodes, containers, channels, processes, i, row)
    return b.diagram(name, event.iri, path, executed=True, run=run)


def _row(b: _Builder, api: URIRef, process, nodes, containers, channels, processes, i: int, row: dict) -> None:
    """The statements of trace row ``i``, in the worker's order: the person
    completing a user task, the decision, the invoke and its deltas, the
    writes, the transition, the published event and the processes it started."""
    task = row.get("task")
    where = f"row {i} {task or 'error'}"
    error = row.get("error")
    if task is None and error is not None:
        transition = row.get("fires")
        moved = f"{local_name(transition)} → {row.get('status')}" if transition else row.get("status")
        b.note(api, f"error {error}, {moved}", *([URIRef(transition)] if transition else []))
        return
    iri = row.get("iri")
    node = None
    if not iri:
        b.gap(f"{where} has no iri")
    else:
        node = nodes.get(URIRef(iri))
        if node is None:
            b.gap(f"{where}: {iri} is not an element of {local_name(process.iri)}")
    el = () if not iri else (URIRef(iri),)

    by = row.get("by")
    if by is not None:
        actor = _by(b, str(by))
        form = None if node is None else node.completed_on
        ui = None if form is None else _presenter([form])
        if ui is None:
            b.gap(f"{where}: completed by {by} on no seam:completedOn form presented by one container")
            b.arrow(actor, api, f"complete {task}", *el)
        else:
            b.arrow(actor, ui, f"{task} on {local_name(form.iri)}", *el, form.iri)
            b.arrow(ui, api, f"complete {task}", *el)

    decision = row.get("decision")
    if decision is not None:
        outputs = ", ".join(_text(str(v)) for v in (row.get("outputs") or {}).values())
        b.arrow(api, api, f"{task} (DMN {local_name(decision)}) = {outputs}", *el, URIRef(decision))

    op = row.get("invokes")
    if op is not None:
        opname = local_name(op)
        if row.get("in_process"):
            b.arrow(api, api, f"{task}, {opname} (in process)", *el, URIRef(op))
        else:
            container = row.get("container")
            if container is None or URIRef(container) not in containers:
                b.gap(f"{where}: container {container} is not an arch:Container")
            else:
                c = URIRef(container)
                path = f" {row['path']}" if row.get("path") else ""
                b.arrow(api, c, f"{task}, {opname}{path}", *el, URIRef(op))
                b.arrow(c, api, f"{row.get('tokens', 0)} deltas", URIRef(op), reply=True)

    streamed = row.get("streamed")
    if streamed is not None:
        for c in _consumers(b, channels, streamed.get("channel"), where):
            text = f"{local_name(streamed['channel'])} ({row.get('tokens', 0)} {streamed.get('event')} deltas)"
            b.arrow(api, c, text, *el, URIRef(streamed["channel"]), reply=True)

    written = row.get("writes") or []
    if written:
        shapes = [] if node is None else list(node.writes)
        if len(shapes) != len(written):
            b.gap(f"{where} writes {len(written)} entities but its element seam:writes {len(shapes)} shapes")
        for shape in shapes[: len(written)]:
            stores = shape.stored_in
            if not stores:
                b.gap(f"{local_name(shape.iri)} written by {task} has no seam:storedIn")
            for store in stores:
                b.arrow(api, store.iri, f"{task} writes {local_name(shape.iri)}", *el, shape.iri)

    transition = row.get("fires")
    if transition is not None:
        status = row.get("status")
        text = local_name(transition) if status is None else f"{local_name(transition)} → {_text(str(status))}"
        b.note(api, text, *el, URIRef(transition))

    published = row.get("published")
    if published is not None:
        for c in _consumers(b, channels, published.get("channel"), where):
            text = f"{local_name(published['channel'])} ({_text(str(published.get('event')))} event)"
            b.arrow(api, c, text, *el, URIRef(published["channel"]), reply=True)

    for started in row.get("started") or []:
        started_iri = URIRef(str(started.get("process")))
        found = processes.get(started_iri)
        executors = [] if found is None else [c.iri for c in found.executed_by]
        if not executors:
            b.gap(f"{where}: started process {started_iri} has no seam:executes container")
        for c in executors:
            b.arrow(api, c, f"start {local_name(started_iri)}", *el, started_iri)


def _consumers(b: _Builder, channels, channel, where: str) -> list[URIRef]:
    """The containers that seam:consume the channel IRI ``channel``; a gap when it is unknown or has none."""
    found = None if channel is None else channels.get(URIRef(channel))
    if found is None:
        b.gap(f"{where}: channel {channel} is not a comm:Channel")
        return []
    consumers = [c.iri for c in found.consumed_by]
    if not consumers:
        b.gap(f"{where}: {local_name(found.iri)} has no seam:consumes container")
    return consumers


def _by(b: _Builder, identity: str) -> URIRef:
    """The actor lifeline of the identity that completed a user task, labelled with its id."""
    iri = URIRef(f"urn:seams:identity:{identity}")
    if iri not in b.participants:
        b.participants[iri] = Participant(iri, "by_" + re.sub(r"\W", "_", identity), _text(identity), True)
    return iri


def default_db() -> Path:
    """The runtime's embedded store: ``SEAMS_DB``, else ``./seams.sqlite``."""
    return Path(os.environ.get("SEAMS_DB") or "seams.sqlite")


def read_trace(source: object, db: object = None) -> tuple[str | None, list[dict]]:
    """(run id, trace rows) from ``source``: an existing JSON file holding an
    instance result (a dict with ``trace``, its ``instance`` the run id) or a
    bare list of rows; otherwise an instance id in the runtime's SQLite store
    at ``db`` (``default_db()`` when None), read with sqlite3 from its
    ``workflow_state`` checkpoint (the Spiff JSON's ``data.seams.trace``).
    ``GeneratorError`` naming the file, or the store and instance."""
    path = Path(str(source))
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise GeneratorError(str(path), "trace file", f"is not JSON: {exc}") from exc
        if isinstance(data, dict) and isinstance(data.get("trace"), list):
            run = data.get("instance")
            return (None if run is None else str(run)), _rows(data["trace"], str(path))
        if isinstance(data, list):
            return None, _rows(data, str(path))
        raise GeneratorError(str(path), "trace file", "holds neither an instance result with a trace nor a list")
    store = Path(str(db)) if db is not None else default_db()
    instance = str(source)
    if not store.is_file():
        raise GeneratorError(instance, "trace", f"no such file and no SQLite store {store}")
    try:
        with closing(sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            found = con.execute("SELECT state FROM workflow_state WHERE instance_id = ?", (instance,)).fetchone()
    except sqlite3.Error as exc:
        raise GeneratorError(instance, "trace", f"cannot read workflow_state in {store}: {exc}") from exc
    if found is None:
        raise GeneratorError(instance, "trace", f"no workflow_state row for instance {instance} in {store}")
    try:
        trace = json.loads(found[0])["data"]["seams"]["trace"]
    except (TypeError, ValueError, KeyError) as exc:
        raise GeneratorError(instance, "trace", f"the checkpoint in {store} has no data.seams.trace") from exc
    return instance, _rows(trace, f"instance {instance} in {store}")


def _rows(rows: object, where: str) -> list[dict]:
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise GeneratorError(where, "trace", "is not a list of trace rows")
    return rows


EXIT_OK = 0
EXIT_IO_ERROR = 1
EXIT_ERROR = 2
_PROG = "python -m seams_gen.sequence"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Derive Mermaid sequence diagrams for an IFML event, one per gateway path."
    )
    parser.add_argument("trig", type=Path, help="the model's TriG file")
    parser.add_argument("event", help="the IFML event: a CURIE (:send_message), local name or full IRI")
    parser.add_argument("--out", type=Path, required=True, help="the directory the .mmd files are written to")
    parser.add_argument(
        "--trace",
        metavar="RUN",
        help="draw one recorded run as <event>.executed.mmd: a trace JSON file or an instance id in the --db store",
    )
    parser.add_argument(
        "--db", type=Path, help="the runtime's SQLite store for an instance id (default: SEAMS_DB, else ./seams.sqlite)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.db is not None and args.trace is None:
        parser.error("--db needs --trace")
    try:
        if not args.trig.is_file():
            raise FileNotFoundError(f"no such model file: {args.trig}")
        model = _load(args.trig)
        if args.trace is None:
            diagrams = derive(model, args.event)
        else:
            run, rows = read_trace(args.trace, args.db)
            diagrams = [executed(model, args.event, rows, run=run)]
    except Exception as exc:  # GeneratorError, OSError, or any rdflib parse error
        print(f"{_PROG}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        paths = write_diagrams(diagrams, args.out)
    except OSError as exc:
        print(f"{_PROG}: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR
    for path in paths:
        print(path)
    for d in diagrams:
        for gap in d.gaps:
            print(f"gap {d.name}: {gap}", file=sys.stderr)
    return EXIT_OK


def _load(trig: Path) -> Model:
    import seams

    return seams.load(trig)


if __name__ == "__main__":
    sys.exit(main())
