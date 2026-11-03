"""Context assembly (backlog C3): the model facts a task's code depends on.

``context_for(model, task)`` gathers, by per-kind rules, the elements and
native file fragments that code written for a service task depends on, and
hashes each one, so a change to any of them shows up as a changed item hash
and a changed ``context_hash``. The rules for a ``proc:ServiceTask``:

- **task**: the task's own triples (what it reads, writes, fires, invokes).
- **shape**: each shape it reads or writes: its type, label, comment and
  ``sh:`` triples, down to its property shapes. Its ``seam:`` joins are left
  out; the items below cover the ones the task uses.
- **transition** and **state**: the transition it fires, with its from and
  to states.
- **process**: its process's type, label, comment, ``seam:detailedBy`` and
  ``proc:correlationKey``, plus the correlation parameter's type and label.
- **decision**: each decision an upstream business-rule task is
  ``seam:decidedBy`` whose ``dec:processVariable`` an incoming gateway
  condition reads, with its inputs and outputs.
- **container**: the container that ``seam:executes`` the process, narrowed
  to its type, label, ``arch:technology`` and the ``deploy:key`` of each
  configuration binding (shared and per override). Binding values, secret
  references and file paths are never read.
- **bpmn**: the task's element, its incoming sequence flows (which carry the
  gateway conditions) and the gateways they come from, in the BPMN file.
- **dmn**: the ``decision`` element of each decision above, in the DMN file.

A graph item hashes its chosen triples: blank nodes canonicalised
(``rdflib.compare``), serialised as N-Triples, lines sorted. An XML item
hashes the element's exclusive C14N, without its tail. Every hash is
``sha256:<hex>``. A graph item's ref is its IRI, an XML item's the payload's
model-relative path, ``#`` and the element id. ``context_hash`` is sha256
over the items sorted by (kind, ref), each framed as kind, NUL, ref, NUL,
hash, newline.

A missing hop raises ``ResolutionError(subject, predicate, detail)``: an
unknown task, one that is not a ``proc:ServiceTask``, no process, no element
in the BPMN file, not exactly one executing container, no correlation key,
a transition without a from or to state, a decision id the DMN file lacks,
or a gateway condition that does not parse.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from rdflib import RDF, RDFS, BNode, Graph, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import SH
from rdflib.term import Node

from .bpmn import BpmnNode
from .decisions_check import condition_names
from .errors import ResolutionError
from .graph import ModelGraph
from .loader import Model
from .namespaces import ARCH, DEPLOY, PROC, SEAM
from .views import Decision, FlowNode, Process, ProcessElement

Triple = tuple[Node, Node, Node]


@dataclass(frozen=True)
class ContextItem:
    """One model fact a task's code depends on: ``kind`` (``task``, ``shape``,
    ``transition``, ``state``, ``process``, ``decision``, ``container``,
    ``bpmn`` or ``dmn``), ``ref`` (an IRI, or ``path#id`` for an XML
    fragment) and ``hash`` (``sha256:<hex>`` of ``content``). ``content`` is
    the hashed text: sorted canonical N-Triples, or the fragment's C14N."""

    kind: str
    ref: str
    hash: str
    content: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class Manifest:
    """The context of ``task``: its items sorted by (kind, ref) and the hash over them."""

    task: URIRef
    items: tuple[ContextItem, ...]
    context_hash: str


#: Predicates a shape item keeps besides the ``sh:`` ones.
_SHAPE_PREDICATES = frozenset({RDF.type, RDFS.label, RDFS.comment})
#: Predicates a process item keeps.
_PROCESS_PREDICATES = frozenset({RDF.type, RDFS.label, RDFS.comment, SEAM.detailedBy, PROC.correlationKey})
#: Predicates a container item keeps on the container itself.
_CONTAINER_PREDICATES = frozenset({RDF.type, RDFS.label, ARCH.technology})


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _graph_item(kind: str, ref: URIRef, triples: Iterable[Triple]) -> ContextItem:
    g = Graph()
    for t in triples:
        g.add(t)
    canonical = Graph()
    canonical += to_canonical_graph(g)
    lines = sorted(line for line in canonical.serialize(format="nt").splitlines() if line.strip())
    content = "".join(f"{line}\n" for line in lines)
    return ContextItem(kind, str(ref), _sha256(content.encode("utf-8")), content)


def _closure(ds: Graph, node: Node, seen: set[Node]) -> list[Triple]:
    """Every triple of ``node`` and, recursively, of the blank nodes it reaches."""
    if node in seen:
        return []
    seen.add(node)
    out: list[Triple] = []
    for p, o in ds.predicate_objects(node):
        out.append((node, p, o))
        if isinstance(o, BNode):
            out.extend(_closure(ds, o, seen))
    return out


def _described(ds: Graph, subject: URIRef, keep: frozenset[URIRef] | None = None) -> list[Triple]:
    """``subject``'s triples whose predicate ``keep`` admits (all when None),
    with the blank nodes they reach."""
    seen: set[Node] = {subject}
    out: list[Triple] = []
    for p, o in ds.predicate_objects(subject):
        if keep is not None and p not in keep:
            continue
        out.append((subject, p, o))
        if isinstance(o, BNode):
            out.extend(_closure(ds, o, seen))
    return out


def _shape_triples(ds: Graph, shape: URIRef) -> list[Triple]:
    seen: set[Node] = {shape}
    out: list[Triple] = []
    for p, o in ds.predicate_objects(shape):
        if p in _SHAPE_PREDICATES or str(p).startswith(str(SH)):
            out.append((shape, p, o))
            if isinstance(o, BNode):
                out.extend(_closure(ds, o, seen))
    return out


def _binding_keys(ds: Graph, holder: Node) -> list[Triple]:
    """holder -deploy:configuration-> cfg -deploy:binding-> b -deploy:key-> key, and nothing else of b."""
    out: list[Triple] = []
    for cfg in ds.objects(holder, DEPLOY.configuration):
        out.append((holder, DEPLOY.configuration, cfg))
        for b in ds.objects(cfg, DEPLOY.binding):
            out.append((cfg, DEPLOY.binding, b))
            out.extend((b, DEPLOY.key, key) for key in ds.objects(b, DEPLOY.key))
    return out


def _container_triples(ds: Graph, container: URIRef) -> list[Triple]:
    out: list[Triple] = [(container, p, o) for p, o in ds.predicate_objects(container) if p in _CONTAINER_PREDICATES]
    out.extend(_binding_keys(ds, container))
    for override in ds.objects(container, DEPLOY.override):
        if ds.value(override, DEPLOY.configuration) is not None:
            out.append((container, DEPLOY.override, override))
            out.extend(_binding_keys(ds, override))
    return out


def _process_triples(ds: Graph, process: Process) -> list[Triple]:
    params = process.correlation_parameters
    if not params:
        raise ResolutionError(process.iri, PROC.correlationKey, "process names no correlation key")
    out = _described(ds, process.iri, _PROCESS_PREDICATES)
    for param in params:
        out.extend((param, p, o) for p, o in ds.predicate_objects(param) if p in (RDF.type, RDFS.label))
    return out


def _relpath(path: Path, base_dir: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base_dir.resolve())).as_posix()


def _xml_item(
    kind: str, model: ModelGraph, path: Path, element_id: str, subject: object, predicate: object
) -> ContextItem:
    """The element with id ``element_id`` in ``path``, as exclusive C14N without its tail."""
    tree = model.views.view(f"xml:{path}", lambda: etree.parse(str(path)))
    found = [el for el in tree.getroot().iter() if isinstance(el.tag, str) and el.get("id") == element_id]
    ref = f"{_relpath(path, model.base_dir)}#{element_id}"
    if len(found) != 1:
        raise ResolutionError(subject, predicate, f"expected one element with id {element_id!r}, found {len(found)}")
    # C14N serialises the element's subtree only: never its tail.
    c14n = etree.tostring(found[0], method="c14n", exclusive=True, with_comments=False)
    return ContextItem(kind, ref, _sha256(c14n), c14n.decode("utf-8"))


def _upstream(start: str, nodes: dict[str, BpmnNode]) -> set[str]:
    """``start`` and every node it is reachable from over sequence flows."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        node_id = todo.pop()
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        todo.extend(f.source for f in nodes[node_id].incoming)
    return seen


def _gateway_decisions(process: Process, node: FlowNode) -> tuple[list[FlowNode], list[Decision]]:
    """The gateways flowing into ``node`` and the decisions whose output
    variable their conditions on those flows read."""
    flows = process.nodes()
    by_id = {fn.bpmn_id: fn for fn in flows if fn.node.process_id == node.node.process_id}
    bpmn_nodes = {k: v.node for k, v in by_id.items()}
    gateways: dict[str, FlowNode] = {}
    decisions: dict[URIRef, Decision] = {}
    for flow in node.incoming:
        source = by_id.get(flow.source)
        if source is None or not source.node.is_gateway:
            continue
        gateways[source.bpmn_id] = source
        if not flow.condition:
            continue
        try:
            names = set(condition_names(flow.condition))
        except SyntaxError as err:
            raise ResolutionError(
                process.element_iri(flow.id), "bpmn:conditionExpression", f"{flow.condition!r} does not parse: {err}"
            ) from None
        for upstream_id in sorted(_upstream(source.bpmn_id, bpmn_nodes)):
            decision = by_id[upstream_id].decided_by
            if decision is not None and any(o.process_variable in names for o in decision.outputs):
                decisions[decision.iri] = decision
    return [gateways[k] for k in sorted(gateways)], [decisions[k] for k in sorted(decisions, key=str)]


def _service_task(model: ModelGraph, task: object) -> ProcessElement:
    text = str(task)
    iri = model.curie(task) if isinstance(task, URIRef) or ":" in text else model.task_iri(text)
    if (iri, RDF.type, PROC.ServiceTask) not in model.ds:
        raise ResolutionError(iri, RDF.type, "not a proc:ServiceTask")
    return model.task_element(iri)


def context_for(model: Model | ModelGraph, task: object) -> Manifest:
    """The context manifest of service task ``task`` (a BPMN id, CURIE or IRI)."""
    graph = model if isinstance(model, ModelGraph) else ModelGraph(model.path, model.ds)
    ds = graph.ds
    element = _service_task(graph, task)
    process = element.process
    if process is None:
        raise ResolutionError(element.iri, SEAM.detailedBy, "no proc:Process is detailed by its BPMN model")
    node = next((fn for fn in process.nodes() if fn.iri == element.iri), None)
    if node is None:
        raise ResolutionError(
            element.iri, SEAM.detailedBy, f"no element with id {element.bpmn_id!r} in {process.bpmn_path.name}"
        )
    container = process.executed_by.only()

    items: list[ContextItem] = [
        _graph_item("task", element.iri, _described(ds, element.iri)),
        _graph_item("process", process.iri, _process_triples(ds, process)),
        _graph_item("container", container.iri, _container_triples(ds, container.iri)),
    ]
    shapes = sorted({*element.reads.iris(), *element.writes.iris()}, key=str)
    items.extend(_graph_item("shape", s, _shape_triples(ds, s)) for s in shapes)

    transition = element.fires
    if transition is not None:
        items.append(_graph_item("transition", transition.iri, _described(ds, transition.iri)))
        states = sorted({transition.from_state.iri, transition.to_state.iri}, key=str)
        items.extend(_graph_item("state", s, _described(ds, s)) for s in states)

    bpmn = process.bpmn_path
    items.append(_xml_item("bpmn", graph, bpmn, element.bpmn_id, element.iri, SEAM.detailedBy))
    for flow in node.incoming:
        flow_iri = process.element_iri(flow.id)
        items.append(_xml_item("bpmn", graph, bpmn, flow.id, flow_iri, SEAM.detailedBy))
    gateways, decisions = _gateway_decisions(process, node)
    for gateway in gateways:
        items.append(_xml_item("bpmn", graph, bpmn, gateway.bpmn_id, gateway.iri, SEAM.detailedBy))
    for decision in decisions:
        items.append(_graph_item("decision", decision.iri, _described(ds, decision.iri)))
        items.append(_xml_item("dmn", graph, decision.dmn_path, decision.decision_id, decision.iri, "dmn:decision"))

    ordered = tuple(sorted({(i.kind, i.ref): i for i in items}.values(), key=lambda i: (i.kind, i.ref)))
    h = hashlib.sha256()
    for item in ordered:
        h.update(f"{item.kind}\0{item.ref}\0{item.hash}\n".encode())
    return Manifest(element.iri, ordered, "sha256:" + h.hexdigest())
