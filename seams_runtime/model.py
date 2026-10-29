"""The TriG model as the runtime's service registry (ADR-0007 rule 2).

``ModelGraph`` loads a seams TriG file and answers the questions the worker
asks while it runs a process, such as which operation a BPMN task invokes,
which container implements that operation, which DMN decision a business-rule
task is bound to, and which lifecycle transition it fires. Each answer comes
from graph facts. When a hop is missing, the resolver raises
``ResolutionError`` naming the subject IRI and the predicate it could not
follow.

``model_hash`` fingerprints the model the runtime executes, covering the TriG
file and every ``seam:renderPayload`` file (BPMN, DMN) it names.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

from lxml import etree
from rdflib import RDF, RDFS, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH

from .errors import ResolutionError

SEAM = Namespace("https://w3id.org/seams/seam#")
COMM = Namespace("https://w3id.org/seams/comm#")
DEC = Namespace("https://w3id.org/seams/dec#")
PROC = Namespace("https://w3id.org/seams/proc#")
STATE = Namespace("https://w3id.org/seams/state#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
IFML = Namespace("https://w3id.org/seams/ifml#")


def local_name(iri) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# ── resolver results ────────────────────────────────────────────────────────


class Transition(NamedTuple):
    iri: URIRef
    from_state: str
    to_state: str
    trigger: str | None


@dataclass(frozen=True)
class InputBinding:
    variable: str
    from_path: str  # local name of the dec:fromPath property, e.g. "content"
    from_path_iri: URIRef
    measure: URIRef | None  # e.g. dec:Length, or None for the raw value
    # typeRef of the DMN inputExpression whose text is this variable (e.g.
    # "number"), or None when the table has no such input expression.
    type_ref: str | None = None


@dataclass(frozen=True)
class OutputBinding:
    variable: str
    process_variable: str


@dataclass(frozen=True)
class DecisionBinding:
    task: URIRef
    decision: URIRef
    model: URIRef
    dmn_path: Path
    decision_id: str
    inputs: tuple[InputBinding, ...]
    outputs: tuple[OutputBinding, ...]


@dataclass(frozen=True)
class Container:
    iri: URIRef
    label: str
    in_process: bool


@dataclass(frozen=True)
class PathMapping:
    variable: str
    property: str  # local name of hydra:property, e.g. "id"
    property_iri: URIRef


@dataclass(frozen=True)
class OperationPath:
    operation: URIRef
    template: str
    mappings: tuple[PathMapping, ...]

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(m.variable for m in self.mappings)


@dataclass(frozen=True)
class ChannelBinding:
    iri: URIRef
    label: str
    event_name: str


@dataclass(frozen=True)
class ChannelStart:
    process: URIRef
    event: URIRef    # the proc:MessageCatchEvent start event
    channel: URIRef  # the comm:Channel it seam:subscribesTo


@dataclass(frozen=True)
class ProcessFacts:
    iri: URIRef
    label: str
    model: URIRef
    bpmn_path: Path


@dataclass(frozen=True)
class Lifecycle:
    iri: URIRef
    initial: str
    states: dict  # state IRI -> label


@dataclass(frozen=True)
class Permission:
    target: URIRef | None
    action: URIRef | None
    assignee: URIRef | None
    assignee_types: tuple[URIRef, ...]


@dataclass(frozen=True)
class PolicyFacts:
    iri: URIRef
    label: str
    permissions: tuple[Permission, ...]


# ── payload paths and the model hash ────────────────────────────────────────


def _load(trig_path: Path) -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(trig_path), format="trig")
    return ds


def payload_path(payload_iri, base_dir: Path) -> Path:
    """file: IRIs map to their path; anything else resolves its last path
    segment against the TriG file's directory."""
    parts = urlsplit(str(payload_iri))
    if parts.scheme == "file":
        return Path(unquote(parts.path))
    return Path(base_dir) / unquote(parts.path).rsplit("/", 1)[-1]


def _payload_files(ds: Dataset, base_dir: Path) -> list[tuple[str, Path]]:
    """(path relative to base_dir, absolute path) for every seam:renderPayload,
    sorted by relative path. A payload that does not exist is a ResolutionError."""
    seen = {}
    for model, payload in ds.subject_objects(SEAM.renderPayload):
        path = payload_path(payload, base_dir)
        if not path.is_file():
            raise ResolutionError(model, SEAM.renderPayload, f"payload {path} not found")
        rel = Path(_relpath(path, base_dir)).as_posix()
        seen[rel] = path
    return sorted(seen.items())


def _relpath(path: Path, base_dir: Path) -> str:
    return os.path.relpath(Path(path).resolve(), Path(base_dir).resolve())


def _hash(trig_path: Path, ds: Dataset) -> str:
    h = hashlib.sha256()
    h.update(Path(trig_path).read_bytes())
    for rel, path in _payload_files(ds, Path(trig_path).parent):
        data = path.read_bytes()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(data)
    return "sha256:" + h.hexdigest()


def model_hash(trig_path) -> str:
    """sha256 over the TriG bytes, then each seam:renderPayload file framed as
    relative path, NUL, length, bytes (sorted by relative path), so editing
    or renaming any payload changes the hash. Returns "sha256:<hex>"."""
    trig_path = Path(trig_path)
    return _hash(trig_path, _load(trig_path))


# ── the graph ───────────────────────────────────────────────────────────────


class ModelGraph:
    """A loaded seams model plus the resolvers the worker dispatches on."""

    def __init__(self, trig_path, dataset: Dataset | None = None):
        self.path = Path(trig_path).resolve()
        self.base_dir = self.path.parent
        self.ds = dataset if dataset is not None else _load(self.path)
        self._hash: str | None = None
        # Per-instance caches (never module-level id()-keyed dicts; see MEM010).
        self._contract_cache: dict = {}

    @classmethod
    def load(cls, trig_path) -> "ModelGraph":
        return cls(trig_path)

    @property
    def hash(self) -> str:
        if self._hash is None:
            self._hash = _hash(self.path, self.ds)
        return self._hash

    @property
    def subject(self) -> URIRef:
        """IRI used as the subject of model-level resolution errors."""
        return URIRef(self.path.as_uri())

    # ── term helpers ──

    def curie(self, term) -> URIRef:
        """Expand ":x" (or any prefix bound in the TriG) to an IRI; full IRIs
        pass through unchanged."""
        if isinstance(term, URIRef):
            return term
        term = str(term)
        if "://" in term or term.startswith("urn:"):
            return URIRef(term)
        prefix, sep, local = term.partition(":")
        if not sep:
            raise ValueError(f"not a CURIE or IRI: {term!r}")
        ns = dict(self.ds.namespaces()).get(prefix)
        if ns is None:
            raise ResolutionError(self.subject, f"@prefix {prefix}:", f"cannot expand {term!r}")
        return URIRef(str(ns) + local)

    def label(self, iri) -> str:
        value = self.ds.value(URIRef(str(iri)), RDFS.label)
        return str(value) if value is not None else local_name(iri)

    def _one(self, subject, predicate, detail: str = ""):
        value = self.ds.value(subject, predicate)
        if value is None:
            raise ResolutionError(subject, predicate, detail)
        return value

    def payload_path(self, model) -> Path:
        model = self.curie(model)
        payload = self._one(model, SEAM.renderPayload)
        path = payload_path(payload, self.base_dir)
        if not path.is_file():
            raise ResolutionError(model, SEAM.renderPayload, f"payload {path} not found")
        return path

    # ── BPMN element IRIs ──

    def _bpmn_model(self) -> URIRef:
        models = [m for m in self.ds.subjects(SEAM.notation, SEAM.BPMN)
                  if (m, SEAM.renderPayload, None) in self.ds]
        if not models:
            models = [m for m, p in self.ds.subject_objects(SEAM.renderPayload)
                      if str(p).lower().endswith(".bpmn")]
        models = sorted(set(models))
        if len(models) != 1:
            raise ResolutionError(
                self.subject, SEAM.renderPayload,
                f"expected one model rendering a BPMN payload, found {[str(m) for m in models]}",
            )
        return models[0]

    def task_iri(self, bpmn_id: str) -> URIRef:
        """Fragment IRI of a BPMN element: <BPMN model IRI>#<bpmn id>."""
        return URIRef(f"{self._bpmn_model()}#{bpmn_id}")

    def _task(self, task) -> URIRef:
        if isinstance(task, URIRef) or "://" in str(task) or ":" in str(task):
            return self.curie(task)
        return self.task_iri(str(task))

    # ── task facts ──

    def invoked_operation(self, task) -> URIRef:
        return self._one(self._task(task), SEAM.invokes, "task invokes no operation")

    def fired_transition(self, task) -> Transition:
        t = self._one(self._task(task), SEAM.fires, "task fires no transition")
        return self._transition(t)

    def _transition(self, t) -> Transition:
        src = self._one(t, STATE["from"])
        dst = self._one(t, STATE.to)
        trigger = self.ds.value(t, STATE.trigger)
        return Transition(t, self.label(src), self.label(dst),
                          None if trigger is None else str(trigger))

    def transitions_from(self, state_label: str, trigger: str | None = None) -> list[Transition]:
        """Transitions leaving the state labelled ``state_label`` (and with the
        given state:trigger, if any), sorted by IRI."""
        out = []
        for t in sorted(set(self.ds.subjects(RDF.type, STATE.Transition))):
            src = self.ds.value(t, STATE["from"])
            if src is None or self.label(src) != state_label:
                continue
            tr = self._transition(t)
            if trigger is None or tr.trigger == trigger:
                out.append(tr)
        return out

    def read_shapes(self, task) -> list[URIRef]:
        return sorted(set(self.ds.objects(self._task(task), SEAM.reads)))

    def written_shapes(self, task) -> list[URIRef]:
        return sorted(set(self.ds.objects(self._task(task), SEAM.writes)))

    # ── user tasks (ADR-0009) ──

    def user_task_form(self, task) -> URIRef:
        """The ifml:Form a user task is seam:completedOn."""
        return self._one(self._task(task), SEAM.completedOn, "user task names no form it is completed on")

    def task_output_shape(self, task) -> URIRef:
        """The shape completing a user task writes: its form's seam:writes,
        else the task's own seam:writes (there must be exactly one)."""
        iri = self._task(task)
        shapes = sorted(set(self.ds.objects(self.user_task_form(iri), SEAM.writes)))
        if not shapes:
            shapes = self.written_shapes(iri)
        if len(shapes) != 1:
            raise ResolutionError(iri, SEAM.writes,
                                  f"expected one output shape for the user task, found {[str(s) for s in shapes]}")
        return shapes[0]

    def form_screen(self, form) -> URIRef | None:
        """The ifml:ViewContainer that ifml:contains ``form``, or None."""
        pages = sorted(p for p in self.ds.subjects(IFML.contains, self.curie(form))
                       if (p, RDF.type, IFML.ViewContainer) in self.ds)
        return pages[0] if pages else None

    # ── decisions ──

    def decision_binding(self, task) -> DecisionBinding:
        """task -seam:decidedBy-> decision -dec:payloadElement-> DMN decision id;
        decision -seam:inModel-> model -seam:renderPayload-> DMN file."""
        iri = self._task(task)
        decision = self._one(iri, SEAM.decidedBy, "business-rule task has no decision")
        element = self._one(decision, DEC.payloadElement, f"via {iri}")
        model = self._one(decision, SEAM.inModel, f"via {iri}")
        payload = self._one(model, SEAM.renderPayload, f"via {iri}")
        dmn_path = payload_path(payload, self.base_dir)
        if not dmn_path.is_file():
            raise ResolutionError(model, SEAM.renderPayload, f"payload {dmn_path} not found, via {iri}")
        decision_id = str(element)
        ids = dmn_decision_ids(dmn_path)
        if decision_id not in ids:
            raise ResolutionError(
                decision, DEC.payloadElement,
                f"{decision_id!r} not among DMN decision ids {ids} in {dmn_path.name}, via {iri}",
            )
        inputs = []
        types = dmn_input_types(dmn_path, decision_id)
        for node in self.ds.objects(decision, DEC.input):
            path = self._one(node, DEC.fromPath, f"input of {decision}")
            variable = str(self._one(node, DEC.variable, f"input of {decision}"))
            inputs.append(InputBinding(
                variable=variable,
                from_path=local_name(path), from_path_iri=path,
                measure=self.ds.value(node, DEC.measure),
                type_ref=types.get(variable),
            ))
        outputs = []
        for node in self.ds.objects(decision, DEC.output):
            outputs.append(OutputBinding(
                variable=str(self._one(node, DEC.variable, f"output of {decision}")),
                process_variable=str(self._one(node, DEC.processVariable, f"output of {decision}")),
            ))
        return DecisionBinding(
            iri, decision, model, dmn_path, decision_id,
            tuple(sorted(inputs, key=lambda b: b.variable)),
            tuple(sorted(outputs, key=lambda b: b.variable)),
        )

    # ── operations, containers, channels ──

    def implementing_container(self, operation, process=None) -> Container:
        """The container that seam:exposes the operation. ``in_process`` is
        True when it also seam:executes ``process`` (or any process, when no
        process is given)."""
        op = self.curie(operation)
        containers = sorted(set(self.ds.subjects(SEAM.exposes, op)))
        if not containers:
            raise ResolutionError(op, SEAM.exposes, "no container exposes this operation")
        if len(containers) > 1:
            raise ResolutionError(
                op, SEAM.exposes,
                f"ambiguous: exposed by {[str(c) for c in containers]}",
            )
        c = containers[0]
        if process is None:
            in_process = (c, SEAM.executes, None) in self.ds
        else:
            in_process = (c, SEAM.executes, self.curie(process)) in self.ds
        return Container(c, self.label(c), in_process)

    def operation_path(self, operation) -> OperationPath:
        op = self.curie(operation)
        tpl_node = self._one(op, COMM.path, "operation has no comm:path")
        template = self._one(tpl_node, HYDRA.template, f"comm:path of {op}")
        mappings = []
        for m in self.ds.objects(tpl_node, HYDRA.mapping):
            prop = self._one(m, HYDRA.property, f"mapping of {op}")
            mappings.append(PathMapping(
                str(self._one(m, HYDRA.variable, f"mapping of {op}")), local_name(prop), prop,
            ))
        return OperationPath(op, str(template), tuple(sorted(mappings, key=lambda m: m.variable)))

    def channel_for_event(self, task) -> ChannelBinding:
        iri = self._task(task)
        for ch in sorted(set(self.ds.objects(iri, SEAM.publishesTo))):
            if (ch, RDF.type, COMM.Channel) in self.ds:
                event = self._one(ch, COMM.eventName, f"channel of {iri}")
                return ChannelBinding(ch, self.label(ch), str(event))
        raise ResolutionError(iri, SEAM.publishesTo, "no comm:Channel target")

    # ── processes, lifecycles, policies, shapes ──

    def process_for(self, curie) -> ProcessFacts:
        iri = self.curie(curie)
        if (iri, RDF.type, PROC.Process) not in self.ds:
            raise ResolutionError(iri, RDF.type, "not a proc:Process")
        model = self._one(iri, SEAM.detailedBy, "process has no BPMN model")
        return ProcessFacts(iri, self.label(iri), model, self.payload_path(model))

    def executing_container(self, process) -> Container:
        """The single container that seam:executes the process (in-process)."""
        iri = self.curie(process)
        containers = sorted(set(self.ds.subjects(SEAM.executes, iri)))
        if len(containers) != 1:
            raise ResolutionError(iri, SEAM.executes,
                                  f"expected one executing container, found {[str(c) for c in containers]}")
        return Container(containers[0], self.label(containers[0]), True)

    def triggering_operation(self, process) -> URIRef:
        """The operation that the event which seam:triggers the process
        seam:submitsTo."""
        iri = self.curie(process)
        ops = sorted({op for ev in self.ds.subjects(SEAM.triggers, iri)
                      for op in self.ds.objects(ev, SEAM.submitsTo)})
        if len(ops) != 1:
            raise ResolutionError(iri, SEAM.triggers,
                                  f"expected one triggering event submitting to one operation, "
                                  f"found {[str(o) for o in ops]}")
        return ops[0]

    # ── channel-started processes (ADR-0010) ──

    def _start_subscriptions(self, process) -> list[ChannelStart]:
        """(start event, channel) for each proc:MessageCatchEvent of the
        process's BPMN model that seam:subscribesTo a comm:Channel and is a
        bpmn:startEvent of its payload, sorted by (event, channel)."""
        iri = self.curie(process)
        if (iri, SEAM.detailedBy, None) not in self.ds:
            return []
        facts = self.process_for(iri)
        prefix = f"{facts.model}#"
        starts = bpmn_start_event_ids(facts.bpmn_path)
        found = set()
        for el, ch in self.ds.subject_objects(SEAM.subscribesTo):
            if str(el).startswith(prefix) and (el, RDF.type, PROC.MessageCatchEvent) in self.ds \
                    and (ch, RDF.type, COMM.Channel) in self.ds and str(el)[len(prefix):] in starts:
                found.add((el, ch))
        return [ChannelStart(facts.iri, el, ch) for el, ch in sorted(found)]

    def is_channel_started(self, process) -> bool:
        """True when the process has one channel start (``start_channel``),
        False when it has none. More than one raises ResolutionError."""
        subs = self._start_subscriptions(process)
        if len(subs) > 1:
            raise ResolutionError(self.curie(process), SEAM.subscribesTo,
                                  f"expected at most one subscribed start event, found "
                                  f"{[(str(s.event), str(s.channel)) for s in subs]}")
        return bool(subs)

    def start_channel(self, process) -> ChannelStart:
        """The start event of a channel-started process and the comm:Channel
        it seam:subscribesTo (there must be exactly one)."""
        subs = self._start_subscriptions(process)
        if len(subs) != 1:
            raise ResolutionError(self.curie(process), SEAM.subscribesTo,
                                  f"expected one proc:MessageCatchEvent start event subscribed to a "
                                  f"comm:Channel, found {[(str(s.event), str(s.channel)) for s in subs]}")
        return subs[0]

    def subscribed_processes(self, channel) -> list[URIRef]:
        """The channel-started processes whose start event seam:subscribesTo
        ``channel``, sorted by IRI."""
        ch = self.curie(channel)
        found = set()
        for process in self.ds.subjects(RDF.type, PROC.Process):
            if any(s.channel == ch for s in self._start_subscriptions(process)):
                found.add(process)
        return sorted(found)

    def accepted_shape(self, operation) -> URIRef:
        return self._one(self.curie(operation), SEAM.acceptsShape, "operation accepts no shape")

    def returned_shape(self, operation) -> URIRef:
        return self._one(self.curie(operation), SEAM.returnsShape, "operation returns no shape")

    def process_channel(self, process) -> ChannelBinding:
        """The comm:Channel that elements of the process's BPMN model
        seam:publishesTo (there must be exactly one)."""
        facts = self.process_for(process)
        prefix = f"{facts.model}#"
        channels = sorted({ch for el, ch in self.ds.subject_objects(SEAM.publishesTo)
                           if str(el).startswith(prefix) and (ch, RDF.type, COMM.Channel) in self.ds})
        if len(channels) != 1:
            raise ResolutionError(facts.iri, SEAM.publishesTo,
                                  f"expected one channel published to by {prefix}*, "
                                  f"found {[str(c) for c in channels]}")
        ch = channels[0]
        event = self._one(ch, COMM.eventName, f"channel of {facts.iri}")
        return ChannelBinding(ch, self.label(ch), str(event))

    def service_binding_key(self, container, service_of) -> str:
        """The deploy:key of ``container``'s deploy:binding whose
        deploy:serviceOf is ``service_of`` (e.g. LLM_GATEWAY_URL)."""
        c, target = self.curie(container), self.curie(service_of)
        keys = sorted({str(self.ds.value(b, DEPLOY.key))
                       for cfg in self.ds.objects(c, DEPLOY.configuration)
                       for b in self.ds.objects(cfg, DEPLOY.binding)
                       if (b, DEPLOY.serviceOf, target) in self.ds and self.ds.value(b, DEPLOY.key) is not None})
        if len(keys) != 1:
            raise ResolutionError(c, DEPLOY.binding,
                                  f"expected one deploy:binding with deploy:serviceOf {target}, found {keys}")
        return keys[0]

    def lifecycle_shape(self, transition) -> URIRef:
        """The shape whose seam:lifecycle machine state:hasTransition ``transition``."""
        t = self.curie(transition)
        shapes = sorted({shape for machine in self.ds.subjects(STATE.hasTransition, t)
                         for shape in self.ds.subjects(SEAM.lifecycle, machine)})
        if len(shapes) != 1:
            raise ResolutionError(t, STATE.hasTransition,
                                  f"expected one shape whose lifecycle owns this transition, "
                                  f"found {[str(s) for s in shapes]}")
        return shapes[0]

    def correlation_key_labels(self) -> set[str]:
        """rdfs:labels of every proc:correlationKey parameter in the model."""
        return {str(self.label(p)) for p in self.ds.objects(None, PROC.correlationKey)}

    def correlation_key(self, process) -> str:
        iri = self.curie(process)
        param = self._one(iri, PROC.correlationKey)
        label = self._one(param, RDFS.label, f"correlation key of {iri}")
        return str(label)

    def lifecycle_for(self, shape) -> Lifecycle:
        iri = self.curie(shape)
        machine = self._one(iri, SEAM.lifecycle, "shape has no lifecycle")
        initial = self._one(machine, STATE.initial, f"lifecycle of {iri}")
        states = {s: self.label(s) for s in self.ds.objects(machine, STATE.hasState)}
        states.setdefault(initial, self.label(initial))
        return Lifecycle(machine, self.label(initial), states)

    def policies_for(self, operation) -> list[PolicyFacts]:
        op = self.curie(operation)
        policies = sorted(set(self.ds.objects(op, SEAM.governedBy)))
        if not policies:
            raise ResolutionError(op, SEAM.governedBy, "operation is not governed by a policy")
        return [self.policy(p) for p in policies]

    def policy(self, policy) -> PolicyFacts:
        """Permissions of one odrl:Policy (target, action, assignee and its rdf:types)."""
        p = self.curie(policy)
        perms = []
        for node in self.ds.objects(p, ODRL.permission):
            assignee = self.ds.value(node, ODRL.assignee)
            types = () if assignee is None else tuple(sorted(set(self.ds.objects(assignee, RDF.type))))
            perms.append(Permission(self.ds.value(node, ODRL.target), self.ds.value(node, ODRL.action),
                                    assignee, types))
        perms.sort(key=lambda x: (str(x.target), str(x.action), str(x.assignee)))
        return PolicyFacts(p, self.label(p), tuple(perms))

    # ── IFML pages ──

    def landmark_page(self) -> URIRef:
        """The single ifml:ViewContainer with ifml:isLandmark true (the app entry page)."""
        pages = sorted({c for c in self.ds.subjects(RDF.type, IFML.ViewContainer)
                        if (c, IFML.isLandmark, Literal(True)) in self.ds})
        if len(pages) != 1:
            raise ResolutionError(self.subject, IFML.isLandmark,
                                  f"expected one ifml:ViewContainer with ifml:isLandmark true, "
                                  f"found {[str(p) for p in pages]}")
        return pages[0]

    def secondary_pages(self) -> list[URIRef]:
        """The other ifml:ViewContainers served as pages: each one with an
        ifml:path that is not the landmark and holds no form a user task is
        seam:completedOn (such a screen is reached through the task inbox,
        ADR-0009). Sorted by IRI."""
        landmark = self.landmark_page()
        pages = []
        for c in set(self.ds.subjects(RDF.type, IFML.ViewContainer)):
            if c == landmark or (c, IFML.path, None) not in self.ds:
                continue
            if any((None, SEAM.completedOn, part) in self.ds for part in self.ds.objects(c, IFML.contains)):
                continue
            pages.append(c)
        return sorted(pages, key=str)

    def page_path(self, page) -> str:
        """The ifml:path a page is served at."""
        return str(self._one(self.curie(page), IFML.path, "page has no ifml:path"))

    def page_components(self, page) -> list[URIRef]:
        """The components a page ifml:contains, by ifml:order (then IRI)."""
        def order(c):
            value = self.ds.value(c, IFML.order)
            return (int(value) if value is not None else 1 << 30, str(c))
        return sorted(set(self.ds.objects(self.curie(page), IFML.contains)), key=order)

    def parameter_labels(self, component) -> set[str]:
        """rdfs:labels of a component's ifml:hasParameter parameters."""
        return {self.label(p) for p in self.ds.objects(self.curie(component), IFML.hasParameter)}

    def shape_graph(self) -> Graph:
        """The named graph(s) holding sh:NodeShape subjects (merged when several)."""
        names = sorted({c for _s, _p, _o, c in self.ds.quads((None, RDF.type, SH.NodeShape))
                        if c is not None}, key=str)
        if not names:
            raise ResolutionError(self.subject, RDF.type, "no graph contains an sh:NodeShape")
        if len(names) == 1:
            return self.ds.graph(names[0])
        merged = Graph()
        for prefix, ns in self.ds.namespaces():
            merged.bind(prefix, ns)
        for name in names:
            for triple in self.ds.graph(name):
                merged.add(triple)
        return merged


def dmn_decision_ids(dmn_path) -> list[str]:
    root = etree.parse(str(dmn_path)).getroot()
    return [el.get("id") for el in root.iter()
            if isinstance(el.tag, str) and etree.QName(el).localname == "decision"]


def bpmn_start_event_ids(bpmn_path) -> set[str]:
    """ids of every bpmn:startEvent in the file."""
    root = etree.parse(str(bpmn_path)).getroot()
    return {el.get("id") for el in root.iter()
            if isinstance(el.tag, str) and etree.QName(el).localname == "startEvent"}


def dmn_input_types(dmn_path, decision_id: str) -> dict[str, str]:
    """inputExpression text -> its typeRef, for the decision table of
    ``decision_id``. An expression without a typeRef is left out."""
    root = etree.parse(str(dmn_path)).getroot()
    out = {}
    for decision in root.iter():
        if not (isinstance(decision.tag, str) and etree.QName(decision).localname == "decision"
                and decision.get("id") == decision_id):
            continue
        for el in decision.iter():
            if isinstance(el.tag, str) and etree.QName(el).localname == "inputExpression" \
                    and el.get("typeRef"):
                text = "".join(t.text or "" for t in el
                               if isinstance(t.tag, str) and etree.QName(t).localname == "text")
                out[text.strip()] = el.get("typeRef")
    return out
