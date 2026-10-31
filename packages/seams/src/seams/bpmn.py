"""BPMN processes read from the payload XML in flow order (lxml only).

Elements are matched on their local names, so any BPMN namespace prefix
reads the same. ``parse_bpmn`` returns one ``BpmnProcess`` per
``bpmn:process`` in document order. Its nodes are the flow nodes (tasks,
events, gateways, call activities and sub-processes, including the nodes
inside sub-processes) in flow order: a topological sort over the sequence
flows that breaks ties by document order and, on a cycle, releases the
remaining node that comes first in the document. Nodes nothing flows into
are ready at the start, so unreachable nodes still appear.

A sequence flow or lane that names a node the process does not have raises
``ResolutionError`` naming the flow or lane and the BPMN attribute that failed.
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from ._xml import localname
from .errors import ResolutionError


@dataclass(frozen=True)
class SequenceFlow:
    """A sequence flow between two flow nodes (bpmn ids)."""

    id: str
    name: str | None
    source: str
    target: str
    condition: str | None


@dataclass(frozen=True)
class Lane:
    """A lane and the ids of the flow nodes it holds."""

    id: str
    name: str | None
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class BpmnNode:
    """A flow node with its sequence flows in and out (in document order)."""

    id: str
    tag: str
    name: str | None
    process_id: str
    lane_id: str | None
    event_definitions: tuple[str, ...]
    incoming: tuple[SequenceFlow, ...]
    outgoing: tuple[SequenceFlow, ...]

    @property
    def is_task(self) -> bool:
        return self.tag.endswith("Task") or self.tag in ("task", "callActivity")

    @property
    def is_gateway(self) -> bool:
        return self.tag.endswith("Gateway")

    @property
    def is_event(self) -> bool:
        return self.tag.endswith("Event")

    @property
    def paths(self) -> tuple[SequenceFlow, ...]:
        """The outgoing flows (the paths out of a gateway)."""
        return self.outgoing


@dataclass(frozen=True)
class BpmnProcess:
    """A bpmn:process: nodes in flow order, flows in document order, lanes."""

    id: str
    name: str | None
    nodes: tuple[BpmnNode, ...]
    flows: tuple[SequenceFlow, ...]
    lanes: tuple[Lane, ...]

    def node(self, bpmn_id: str) -> BpmnNode:
        """The node with id ``bpmn_id`` (KeyError when there is none)."""
        for n in self.nodes:
            if n.id == bpmn_id:
                return n
        raise KeyError(bpmn_id)


def _is_flow_node(name: str) -> bool:
    return name.endswith(("Task", "Event", "Gateway")) or name in ("task", "callActivity", "subProcess")


def _walk(container: Any, nodes: list[Any], flows: list[Any], lanes: list[Any]) -> None:
    """Collect the flow nodes, sequence flows and lanes of a process or sub-process, in document order."""
    for child in container:
        name = localname(child.tag)
        if name is None:
            continue
        if name == "sequenceFlow":
            flows.append(child)
        elif name == "laneSet":
            _lanes(child, lanes)
        elif _is_flow_node(name):
            nodes.append(child)
            if name == "subProcess":
                _walk(child, nodes, flows, lanes)


def _lanes(lane_set: Any, out: list[Any]) -> None:
    """Every lane of a laneSet, parents before their childLaneSet lanes."""
    for lane in lane_set:
        if localname(lane.tag) != "lane":
            continue
        out.append(lane)
        for child in lane:
            if localname(child.tag) == "childLaneSet":
                _lanes(child, out)


def _text(el: Any) -> str | None:
    return (el.text or "").strip() if el is not None else None


def _flow(el: Any, path: Path, node_ids: set[str]) -> SequenceFlow:
    flow_id = str(el.get("id") or "")
    refs: dict[str, str] = {}
    for attr in ("sourceRef", "targetRef"):
        ref = el.get(attr)
        if ref not in node_ids:
            raise ResolutionError(
                f"{path.name}#{flow_id}", f"bpmn:{attr}", f"{ref!r} is not a flow node of the process"
            )
        refs[attr] = str(ref)
    condition = next((c for c in el if localname(c.tag) == "conditionExpression"), None)
    return SequenceFlow(
        id=flow_id,
        name=el.get("name"),
        source=refs["sourceRef"],
        target=refs["targetRef"],
        condition=_text(condition),
    )


def _lane(el: Any, path: Path, node_ids: set[str]) -> Lane:
    lane_id = str(el.get("id") or "")
    refs: list[str] = []
    for ref in el:
        if localname(ref.tag) != "flowNodeRef":
            continue
        node_id = (ref.text or "").strip()
        if node_id not in node_ids:
            raise ResolutionError(
                f"{path.name}#{lane_id}", "bpmn:flowNodeRef", f"{node_id!r} is not a flow node of the process"
            )
        refs.append(node_id)
    return Lane(id=lane_id, name=el.get("name"), node_ids=tuple(refs))


def _flow_order(ids: list[str], flows: list[SequenceFlow]) -> list[int]:
    """Document indexes of ``ids`` in flow order (Kahn; ties and cycles go to document order)."""
    index = {node_id: i for i, node_id in enumerate(ids)}
    indegree = [0] * len(ids)
    successors: list[list[int]] = [[] for _ in ids]
    for f in flows:
        successors[index[f.source]].append(index[f.target])
        indegree[index[f.target]] += 1
    ready = [i for i, d in enumerate(indegree) if d == 0]
    heapq.heapify(ready)
    done = [False] * len(ids)
    order: list[int] = []
    while len(order) < len(ids):
        if not ready:  # a cycle: release the remaining node first in the document
            heapq.heappush(ready, next(i for i, d in enumerate(done) if not d))
        i = heapq.heappop(ready)
        if done[i]:
            continue
        done[i] = True
        order.append(i)
        for j in successors[i]:
            indegree[j] -= 1
            if indegree[j] == 0 and not done[j]:
                heapq.heappush(ready, j)
    return order


def _process(el: Any, path: Path) -> BpmnProcess:
    process_id = str(el.get("id") or "")
    node_els: list[Any] = []
    flow_els: list[Any] = []
    lane_els: list[Any] = []
    _walk(el, node_els, flow_els, lane_els)
    ids = [str(n.get("id") or "") for n in node_els]
    known = set(ids)
    flows = [_flow(f, path, known) for f in flow_els]
    lanes = [_lane(lane, path, known) for lane in lane_els]
    lane_of: dict[str, str] = {}
    for lane in lanes:  # parents come before children, so a node gets its innermost lane
        for node_id in lane.node_ids:
            lane_of[node_id] = lane.id
    nodes = [
        BpmnNode(
            id=node_id,
            tag=str(localname(n.tag)),
            name=n.get("name"),
            process_id=process_id,
            lane_id=lane_of.get(node_id),
            event_definitions=tuple(
                str(localname(c.tag)) for c in n if (localname(c.tag) or "").endswith("EventDefinition")
            ),
            incoming=tuple(f for f in flows if f.target == node_id),
            outgoing=tuple(f for f in flows if f.source == node_id),
        )
        for node_id, n in zip(ids, node_els, strict=True)
    ]
    return BpmnProcess(
        id=process_id,
        name=el.get("name"),
        nodes=tuple(nodes[i] for i in _flow_order(ids, flows)),
        flows=tuple(flows),
        lanes=tuple(lanes),
    )


def parse_bpmn(path: str | os.PathLike[str]) -> tuple[BpmnProcess, ...]:
    """Every bpmn:process of the BPMN file, in document order."""
    p = Path(path)
    root = etree.parse(str(p)).getroot()
    return tuple(_process(el, p) for el in root.iter() if localname(el.tag) == "process")
