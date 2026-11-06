"""Coverage: what the model declares that no scenario or test exercises (D054).

Four questions, one module:

- ``unexercised_paths(model)`` lists the start-to-end BPMN paths no
  verify:Scenario runs. Sequence flows live only in the BPMN XML
  (ADR-0007), so this is a Python join of ``Process.nodes()`` with
  ``model.scenarios``, not SPARQL.
- ``unfired_transitions(model)`` runs ``coverage/unfired-transitions.rq``:
  the state:Transitions nothing seam:fires.
- ``policies_without_deny(model)`` runs ``coverage/policies-without-deny.rq``:
  the odrl:permissions the ``tests`` generator writes no party deny test for.
- ``core_operations_untested(model)`` runs ``coverage/core-operations-untested.rq``
  (ADR-0030 section 6): the hydra:Operations of a context in an arch:Core domain
  with no comm:PythonHandler and no verify:Scenario reaching them.

A path is a simple walk over a process's flow nodes: it starts at a
bpmn:startEvent, follows outgoing sequence flows without revisiting a node,
and ends at a node with no way out. A boundary event is one more way out of
the task it is attached to, so its path runs through that task. A walk whose
every way out is already on it (a loop back) is not a start-to-end path and
is dropped.

A scenario's run is a walk: a path of its process, then, when a node on it
seam:publishesTo a channel, a path of a process whose start event
seam:subscribesTo that channel (ADR-0010; one hop). A scenario exercises a
walk when every expectation it states is on the walk (its
verify:expectEndEvent, and a node that seam:fires a transition whose state:to
is its verify:expectState), its verify:step tasks are exactly the user tasks
on the walk up to the last of those expectations, in order (a run cannot pass
a user task without a step completing it), and the walk agrees with its
verify:failures: it invokes every operation the scenario fails (a failure
the walk never meets says it is not this run), a task whose operation the scenario fails leaves through
the error boundary that catches the failure's status, and a walk passes a
boundary event only from a task whose operation the scenario fails with the
status the boundary catches. The scenario then exercises the walk's own-process
path, and the started process's path too when an expectation lies on it:
a started path no expectation reaches is not credited, since nothing the run
checks tells its branches apart.

Every list comes in a fixed order (principle 6): processes by IRI, then
paths in BPMN flow order (start events in flow order, outgoing flows in
document order, boundary events after them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import URIRef

from .namespaces import SEAM
from .views import FlowNode, Many, Operation, Policy, Process, Scenario, Transition

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


def _failures_agree(scenario: Scenario, walk: tuple[FlowNode, ...]) -> bool:
    """True when ``walk`` invokes every failed operation, leaves its task through the boundary catching its
    status, and passes a boundary only that way (the failure rule in the module docstring)."""
    failing = {f.operation.iri: f.status.iri for f in scenario.failures}
    invoked = {op.iri for op in (n.invokes for n in walk) if op is not None}
    if not set(failing) <= invoked:
        return False
    for i, n in enumerate(walk):
        if n.tag == "boundaryEvent":
            task = walk[i - 1] if i > 0 else None
            caught = n.catches
            if task is None or task.bpmn_id != n.node.attached_to or caught is None:
                return False
            op = task.invokes
            if op is None or failing.get(op.iri) != caught.iri:
                return False
            continue
        op = n.invokes
        if op is None or op.iri not in failing:
            continue
        after = walk[i + 1] if i + 1 < len(walk) else None
        if after is None or after.tag != "boundaryEvent" or after.node.attached_to != n.bpmn_id:
            return False
    return True


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


def _walk_cut(scenario: Scenario, walk: tuple[FlowNode, ...]) -> int | None:
    """The index of the walk's last expected node when ``scenario`` exercises ``walk``, else None."""
    if not _failures_agree(scenario, walk):
        return None
    cut = _expectation_index(scenario, walk)
    if cut is None:
        return None
    user_tasks = tuple(n.iri for n in walk[: cut + 1] if n.tag == "userTask")
    return cut if user_tasks == tuple(step.task.iri for step in scenario.steps) else None


def exercises(scenario: Scenario, process: Process, path: tuple[FlowNode, ...]) -> bool:
    """True when ``scenario`` runs ``process`` along ``path`` and stops there:
    the walk is ``path`` alone (the rule in the module docstring). A path
    a scenario reaches through a channel is credited by ``process_paths``."""
    if scenario.process.iri != process.iri:
        return False
    return _walk_cut(scenario, path) is not None


def process_paths(model: Model, process: object = None) -> tuple[ProcessPath, ...]:
    """Every start-to-end path of every process (or of ``process``, an IRI
    or CURIE, ``ResolutionError`` when it is not a proc:Process), with the
    scenarios that exercise each."""
    processes = model.processes
    chosen = list(processes) if process is None else [processes.by_iri(process)]
    every = {proc.iri: _paths(proc) for proc in processes}
    # The paths each channel starts: those whose start event seam:subscribesTo it.
    started: dict[URIRef, list[tuple[FlowNode, ...]]] = {}
    for paths in every.values():
        for path in paths:
            channel = path[0].starts_from
            if channel is not None:
                started.setdefault(channel.iri, []).append(path)
    credit: dict[int, list[Scenario]] = {}
    for scenario in model.scenarios:
        for own in every.get(scenario.process.iri, []):
            if _walk_cut(scenario, own) is not None:
                credit.setdefault(id(own), []).append(scenario)
            channels = sorted({ch.iri for n in own for ch in n.publishes_to}, key=str)
            for then in (p for ch in channels for p in started.get(ch, [])):
                cut = _walk_cut(scenario, own + then)
                if cut is None:
                    continue
                for path in (own, then) if cut >= len(own) else (own,):
                    if scenario not in credit.setdefault(id(path), []):
                        credit[id(path)].append(scenario)
    out: list[ProcessPath] = []
    for proc in chosen:
        for path in every[proc.iri]:
            runs = credit.get(id(path), [])
            out.append(ProcessPath(proc, path, tuple(s for s in model.scenarios if s in runs)))
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


def core_operations_untested(model: Model, context: object = None) -> Many[Operation]:
    """The core operations with no handler and no scenario (``coverage/core-operations-untested.rq``),
    by (domain, context, operation); ``context`` narrows it to one arch:BoundedContext."""
    bindings = {} if context is None else {"context": context}
    rows = model.question("coverage/core-operations-untested", **bindings)
    iris = list(dict.fromkeys(r["operation"] for r in rows if isinstance(r["operation"], URIRef)))
    return Many([model.views.intern(Operation, i) for i in iris], model.subject, SEAM.implementedBy, model.curie)


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
    "core_operations_untested",
    "exercises",
    "policies_without_deny",
    "process_paths",
    "unexercised_paths",
    "unfired_transitions",
]
