"""The as-designed sequence deriver (backlog U1, R008, D047).

``derive(model, event)`` turns an IFML event into Mermaid sequence diagrams
built only from graph facts, read through the ``seams`` views, with the step
order taken from the BPMN sequence flows of the process the event triggers
(research note docs/research/2026-10-29-uml-coverage-and-gaps.md, section 2):

- the actor is the assignee of each permission of the event's policies;
- the UI is the container that seam:presents the interaction model holding
  the event's component or page;
- the executing container ("API") exposes the operation the event
  seam:submitsTo and seam:executes the process it seam:triggers;
- each node of the walk adds its arrows: seam:writes to the containers the
  shape is seam:storedIn, seam:fires as a note, seam:decidedBy as a self call,
  seam:invokes to the container that exposes the operation, and
  seam:publishesTo to the containers that seam:consume the channel. The
  operation's seam:rendersComponent fragment goes back to the UI after the
  node that invokes the submitted operation. seam:reads draws nothing.

Every arrow the deriver cannot place (a missing fact) is recorded as a gap and
rendered as a ``%% gap: <detail>`` line, never dropped. This version walks one
linear path from the start event to the end event; a node with more than one
outgoing flow raises ``NotImplementedError``, except a parallel gateway, which
is a gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import URIRef
from seams import Component, Container, Event, FlowNode, Model, Operation, Page, local_name

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

    def diagram(self, name: str, event: URIRef, path: tuple[str, ...]) -> SequenceDiagram:
        # Actors first, then the other lifelines in first-use order.
        ordered = [p for p in self.participants.values() if p.actor]
        ordered += [p for p in self.participants.values() if not p.actor]
        return SequenceDiagram(name, event, path, tuple(ordered), tuple(self.messages), tuple(self.gaps))


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
    containers: list[Container] = []
    for owner in event.owners:
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
    if len(containers) != 1:
        b.gap(f"{local_name(event.iri)} has no interaction model seam:presents by one container")
        return None
    return containers[0].iri


def _actors(b: _Builder, event: Event) -> list[tuple[URIRef, URIRef]]:
    """(assignee, policy) for each permission of each governing policy."""
    ev = local_name(event.iri)
    found: list[tuple[URIRef, URIRef]] = []
    policies = event.governed_by
    if not policies:
        b.gap(f"{ev} has no seam:governedBy policy, so no actor")
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


def derive(model: Model, event: object) -> list[SequenceDiagram]:
    """One ``SequenceDiagram`` per path of the process ``event`` triggers.
    ``event`` is a CURIE, local name or full IRI; an unknown one raises
    ``GeneratorError`` naming it."""
    ev = find_event(model, event)
    with view_errors():
        return [_derive_path(model, ev)]


def _derive_path(model: Model, event: Event) -> SequenceDiagram:
    b = _Builder(model)
    ev = local_name(event.iri)
    actors = _actors(b, event)
    ui = _ui(b, event)
    op = event.submits_to
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

    if api is None or process is None:
        return b.diagram(ev, event.iri, ())
    b.note(api, f"start {local_name(process.iri)}", process.iri)

    nodes = process.nodes()
    invokers = [n for n in nodes if op is not None and n.invokes is not None and n.invokes.iri == op.iri]
    if not invokers:
        _fragment(b, api, ui, op)

    for node in _walk(b, process):
        _node(b, api, ui, op, node)
        if node in invokers:
            _fragment(b, api, ui, op)
    return b.diagram(ev, event.iri, ())


def _iris(*elements) -> tuple[URIRef, ...]:
    return tuple(e.iri for e in elements if e is not None)


def _walk(b: _Builder, process) -> list[FlowNode]:
    """The linear path from the process's start event (not a channel start)
    to its end, following each node's single outgoing flow."""
    nodes = process.nodes()
    by_id = {n.bpmn_id: n for n in nodes}
    channel_starts = {s.iri for s in process.channel_starts}
    starts = [n for n in nodes if n.tag == "startEvent" and n.iri not in channel_starts]
    if not starts:
        b.gap(f"{local_name(process.iri)} has no start event")
        return []
    path: list[FlowNode] = []
    node: FlowNode | None = starts[0]
    while node is not None:
        if node in path:
            b.gap(f"BPMN flow loops back to {node.bpmn_id}; the loop is drawn once")
            break
        path.append(node)
        out = node.outgoing
        if len(out) > 1:
            if node.tag != "parallelGateway":
                raise NotImplementedError(f"{node.bpmn_id} has {len(out)} outgoing flows")
            b.gap(
                f"parallel gateway {node.bpmn_id} forks; only flow {out[0].name or out[0].id} is drawn, "
                f"not {', '.join(f.name or f.id for f in out[1:])}"
            )
        node = by_id.get(out[0].target) if out else None
    return path


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
        if not consumers and not channel.subscribed_by:
            b.gap(f"{local_name(channel.iri)} published by {nid} has no seam:consumes container or subscriber")
        if op is not None:
            text = f"{local_name(channel.iri)} ({channel.event_name} deltas)"
        else:
            text = f"{local_name(channel.iri)} ({_text(channel.label)} event)"
        for c in consumers:
            b.arrow(api, c, text, el, channel.iri, reply=True)


def render(diagram: SequenceDiagram) -> str:
    """The diagram as Mermaid text, ``\\n`` newlines and a trailing newline."""
    lines = ["sequenceDiagram", f"%% derived from {diagram.event}"]
    lines.append(f"%% path: {' -> '.join(diagram.path) if diagram.path else 'single'}")
    lines += [f"%% gap: {g}" for g in diagram.gaps]
    for p in diagram.participants:
        lines.append(f"{'actor' if p.actor else 'participant'} {p.id} as {p.label}")
    lines += [m.line for m in diagram.messages]
    return "\n".join([lines[0], *(f"    {line}" for line in lines[1:])]) + "\n"


def file_name(diagram: SequenceDiagram) -> str:
    """``<event local>.mmd`` for a single path, ``<event local>--<flow>[--<flow>].mmd`` otherwise."""
    return "--".join([diagram.name, *diagram.path]) + ".mmd"
