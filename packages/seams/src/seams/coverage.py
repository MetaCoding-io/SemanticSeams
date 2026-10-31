"""Coverage: what the model declares that no scenario or test exercises (D054).

Three questions, one module:

- ``unexercised_paths(model)`` lists the start-to-end BPMN paths no
  verify:Scenario runs. Sequence flows live only in the BPMN XML
  (ADR-0007), so this is a Python join of ``Process.nodes()`` with
  ``model.scenarios``, not SPARQL.
- ``unfired_transitions(model)`` runs ``coverage/unfired-transitions.rq``:
  the state:Transitions nothing seam:fires.
- ``policies_without_deny(model)`` runs ``coverage/policies-without-deny.rq``:
  the odrl:permissions the ``tests`` generator writes no party deny test for.

A path is a simple walk over a process's flow nodes: it starts at a
bpmn:startEvent, follows outgoing sequence flows without revisiting a node,
and ends at a node with no way out. A boundary event is one more way out of
the task it is attached to, so its path runs through that task. A walk whose
every way out is already on it (a loop back) is not a start-to-end path and
is dropped.

A scenario exercises a path when it runs that path's process, every
expectation it states is on the path (its verify:expectEndEvent, and a node
that seam:fires a transition whose state:to is its verify:expectState), and
its verify:step tasks are exactly the user tasks on the path up to the last
of those expectations, in order: a run cannot pass a user task without a step
completing it. A path through a boundary event is never exercised, since the
verify vocabulary has no way to make a task's operation fail.

Every list comes in a fixed order (principle 6): processes by IRI, then
paths in BPMN flow order (start events in flow order, outgoing flows in
document order, boundary events after them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import URIRef

from .namespaces import SEAM
from .views import FlowNode, Many, Policy, Process, Scenario, Transition

if TYPE_CHECKING:
    from .loader import Model


@dataclass(frozen=True)
class ProcessPath:
    """One start-to-end path through a process's BPMN flow nodes.

    ``nodes`` are in walk order, from the start event to ``end``;
    ``scenarios`` are the verify:Scenarios that exercise it, by IRI (empty
    when it is unexercised).
    """

    process: Process
    nodes: tuple[FlowNode, ...]
    scenarios: tuple[Scenario, ...]

    @property
    def iris(self) -> tuple[URIRef, ...]:
        """The node IRIs (``<bpmn model>#<bpmn id>``), in walk order."""
        return tuple(n.iri for n in self.nodes)

    @property
    def bpmn_ids(self) -> tuple[str, ...]:
        """The node BPMN ids, in walk order."""
        return tuple(n.bpmn_id for n in self.nodes)

    @property
    def start(self) -> FlowNode:
        return self.nodes[0]

    @property
    def end(self) -> FlowNode:
        """The node the path finishes on (normally a bpmn:endEvent)."""
        return self.nodes[-1]

    @property
    def exercised(self) -> bool:
        return bool(self.scenarios)


@dataclass(frozen=True)
class UndeniedPermission:
    """An odrl:permission of ``policy`` with no party deny test; ``assignee`` is None when it has none."""

    policy: Policy
    target: URIRef | None
    assignee: URIRef | None


def _paths(process: Process) -> list[tuple[FlowNode, ...]]:
    """Every simple start-to-end walk of ``process``'s flow nodes, in flow order."""
    nodes = process.nodes()
    by_id = {(n.node.process_id, n.bpmn_id): n for n in nodes}
    attached: dict[tuple[str, str], list[FlowNode]] = {}
    for n in nodes:
        if n.node.attached_to is not None:
            attached.setdefault((n.node.process_id, n.node.attached_to), []).append(n)

    def ways_out(n: FlowNode) -> list[FlowNode]:
        key = (n.node.process_id, n.bpmn_id)
        return [by_id[(key[0], f.target)] for f in n.outgoing] + attached.get(key, [])

    found: list[tuple[FlowNode, ...]] = []

    def walk(path: list[FlowNode]) -> None:
        out = ways_out(path[-1])
        if not out:
            found.append(tuple(path))
            return
        on_path = {id(n) for n in path}
        for nxt in out:
            if id(nxt) not in on_path:
                walk([*path, nxt])

    for start in nodes:
        if start.tag == "startEvent":
            walk([start])
    return found


def _expectation_index(scenario: Scenario, path: tuple[FlowNode, ...]) -> int | None:
    """The index of the last node the scenario's expectations name, or None when one is not on the path."""
    last = len(path) - 1
    if scenario.expect_end_event is None and scenario.expect_state is None:
        return last
    cut = 0
    end = scenario.expect_end_event
    if end is not None:
        found = [i for i, n in enumerate(path) if n.iri == end]
        if not found:
            return None
        cut = max(cut, found[0])
    state = scenario.expect_state
    if state is not None:
        found = [i for i, n in enumerate(path) if n.fires is not None and n.fires.to_state.iri == state.iri]
        if not found:
            return None
        cut = max(cut, found[0])
    return cut


def exercises(scenario: Scenario, process: Process, path: tuple[FlowNode, ...]) -> bool:
    """True when ``scenario`` runs ``process`` along ``path`` (the rule in the module docstring)."""
    if scenario.process.iri != process.iri:
        return False
    if any(n.tag == "boundaryEvent" for n in path):
        return False
    cut = _expectation_index(scenario, path)
    if cut is None:
        return False
    user_tasks = tuple(n.iri for n in path[: cut + 1] if n.tag == "userTask")
    return user_tasks == tuple(step.task.iri for step in scenario.steps)


def process_paths(model: Model, process: object = None) -> tuple[ProcessPath, ...]:
    """Every start-to-end path of every process (or of ``process``, an IRI
    or CURIE, ``ResolutionError`` when it is not a proc:Process), with the
    scenarios that exercise each."""
    processes = model.processes
    chosen = list(processes) if process is None else [processes.by_iri(process)]
    scenarios = model.scenarios
    out: list[ProcessPath] = []
    for proc in chosen:
        runs = [s for s in scenarios if s.process.iri == proc.iri]
        for path in _paths(proc):
            out.append(ProcessPath(proc, path, tuple(s for s in runs if exercises(s, proc, path))))
    return tuple(out)


def unexercised_paths(model: Model, process: object = None) -> tuple[ProcessPath, ...]:
    """The ``process_paths`` no scenario exercises."""
    return tuple(p for p in process_paths(model, process) if not p.exercised)


def unfired_transitions(model: Model, lifecycle: object = None) -> Many[Transition]:
    """The state:Transitions nothing seam:fires (``coverage/unfired-transitions.rq``),
    by (lifecycle, transition); ``lifecycle`` narrows it to one state machine."""
    bindings = {} if lifecycle is None else {"lifecycle": lifecycle}
    rows = model.question("coverage/unfired-transitions", **bindings)
    iris = [r["transition"] for r in rows if isinstance(r["transition"], URIRef)]
    return Many([model.views.intern(Transition, i) for i in iris], model.subject, SEAM.fires, model.curie)


def policies_without_deny(model: Model, policy: object = None) -> tuple[UndeniedPermission, ...]:
    """The permissions the ``tests`` generator writes no party deny test for
    (``coverage/policies-without-deny.rq``), by (policy, target, assignee)."""
    bindings = {} if policy is None else {"policy": policy}
    out: list[UndeniedPermission] = []
    for row in model.question("coverage/policies-without-deny", **bindings):
        pol, target, assignee = row["policy"], row.get("target"), row.get("assignee")
        if not isinstance(pol, URIRef):
            continue
        out.append(
            UndeniedPermission(
                model.views.intern(Policy, pol),
                target if isinstance(target, URIRef) else None,
                assignee if isinstance(assignee, URIRef) else None,
            )
        )
    return tuple(out)


__all__ = [
    "ProcessPath",
    "UndeniedPermission",
    "exercises",
    "policies_without_deny",
    "process_paths",
    "unexercised_paths",
    "unfired_transitions",
]
