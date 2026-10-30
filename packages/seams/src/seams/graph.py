"""The model as a resolver: one answer per graph question.

``ModelGraph`` is a ``Model`` plus the resolvers the runtime and the generators
share, such as which operation a BPMN task invokes, which container implements
that operation, which DMN decision a business-rule task is bound to, which
lifecycle transition it fires and which page is the landmark. Each answer comes
from graph facts. When a hop is missing, the resolver raises
``ResolutionError`` naming the subject IRI and the predicate it could not
follow.

These one-of-each resolvers are transitional: the S03 views supersede them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, cast

from rdflib import RDF, RDFS, Dataset, Graph, Literal, URIRef
from rdflib.namespace import SH
from rdflib.term import Node

from ._xml import elements as _elements
from ._xml import localname as _localname
from .errors import ResolutionError
from .loader import Model, payload_path
from .namespaces import COMM, DEC, DEPLOY, HYDRA, IFML, ODRL, PROC, SEAM, STATE, local_name

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
    event: URIRef  # the proc:MessageCatchEvent start event
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
    states: dict[URIRef, str]  # state IRI -> label


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


def _iri(node: Node) -> URIRef:
    """A graph term the model writes as an IRI (typing only; no conversion)."""
    return cast(URIRef, node)


def _opt_iri(node: Node | None) -> URIRef | None:
    return None if node is None else cast(URIRef, node)


def _iris(nodes: Any) -> list[URIRef]:
    """Distinct terms, sorted (typing only; no conversion)."""
    return sorted(set(cast("list[URIRef]", nodes)))


# ── the graph ───────────────────────────────────────────────────────────────


class ModelGraph(Model):
    """A loaded seams model plus the resolvers the worker and generators dispatch on."""

    def __init__(self, trig_path: str | os.PathLike[str], dataset: Dataset | None = None) -> None:
        super().__init__(trig_path, dataset)
        # Per-instance caches (never module-level id()-keyed dicts; see MEM010).
        self._contract_cache: dict[Any, Any] = {}

    @classmethod
    def load(cls, trig_path: str | os.PathLike[str]) -> ModelGraph:
        return cls(trig_path)

    # ── term helpers ──

    def _one(self, subject: Node, predicate: Node, detail: str = "") -> Node:
        value = self.ds.value(subject, predicate)
        if value is None:
            raise ResolutionError(subject, predicate, detail)
        return value

    # ── BPMN element IRIs ──

    def _bpmn_model(self) -> URIRef:
        found: list[Node] = [
            m for m in self.ds.subjects(SEAM.notation, SEAM.BPMN) if (m, SEAM.renderPayload, None) in self.ds
        ]
        if not found:
            found = [m for m, p in self.ds.subject_objects(SEAM.renderPayload) if str(p).lower().endswith(".bpmn")]
        models = _iris(found)
        if len(models) != 1:
            raise ResolutionError(
                self.subject,
                SEAM.renderPayload,
                f"expected one model rendering a BPMN payload, found {[str(m) for m in models]}",
            )
        return models[0]

    def task_iri(self, bpmn_id: str) -> URIRef:
        """Fragment IRI of a BPMN element: <BPMN model IRI>#<bpmn id>."""
        return URIRef(f"{self._bpmn_model()}#{bpmn_id}")

    def _task(self, task: object) -> URIRef:
        if isinstance(task, URIRef) or "://" in str(task) or ":" in str(task):
            return self.curie(task)
        return self.task_iri(str(task))

    # ── task facts ──

    def invoked_operation(self, task: object) -> URIRef:
        return _iri(self._one(self._task(task), SEAM.invokes, "task invokes no operation"))

    def fired_transition(self, task: object) -> Transition:
        t = self._one(self._task(task), SEAM.fires, "task fires no transition")
        return self._transition(t)

    def _transition(self, t: Node) -> Transition:
        src = self._one(t, STATE["from"])
        dst = self._one(t, STATE.to)
        trigger = self.ds.value(t, STATE.trigger)
        return Transition(_iri(t), self.label(src), self.label(dst), None if trigger is None else str(trigger))

    def transitions_from(self, state_label: str, trigger: str | None = None) -> list[Transition]:
        """Transitions leaving the state labelled ``state_label`` (and with the
        given state:trigger, if any), sorted by IRI."""
        out: list[Transition] = []
        for t in _iris(self.ds.subjects(RDF.type, STATE.Transition)):
            src = self.ds.value(t, STATE["from"])
            if src is None or self.label(src) != state_label:
                continue
            tr = self._transition(t)
            if trigger is None or tr.trigger == trigger:
                out.append(tr)
        return out

    def read_shapes(self, task: object) -> list[URIRef]:
        return _iris(self.ds.objects(self._task(task), SEAM.reads))

    def written_shapes(self, task: object) -> list[URIRef]:
        return _iris(self.ds.objects(self._task(task), SEAM.writes))

    # ── user tasks (ADR-0009) ──

    def user_task_form(self, task: object) -> URIRef:
        """The ifml:Form a user task is seam:completedOn."""
        return _iri(self._one(self._task(task), SEAM.completedOn, "user task names no form it is completed on"))

    def task_output_shape(self, task: object) -> URIRef:
        """The shape completing a user task writes: its form's seam:writes,
        else the task's own seam:writes (there must be exactly one)."""
        iri = self._task(task)
        shapes = _iris(self.ds.objects(self.user_task_form(iri), SEAM.writes))
        if not shapes:
            shapes = self.written_shapes(iri)
        if len(shapes) != 1:
            raise ResolutionError(
                iri, SEAM.writes, f"expected one output shape for the user task, found {[str(s) for s in shapes]}"
            )
        return shapes[0]

    def form_screen(self, form: object) -> URIRef | None:
        """The ifml:ViewContainer that ifml:contains ``form``, or None."""
        pages = sorted(
            _iri(p)
            for p in self.ds.subjects(IFML.contains, self.curie(form))
            if (p, RDF.type, IFML.ViewContainer) in self.ds
        )
        return pages[0] if pages else None

    # ── decisions ──

    def decision_binding(self, task: object) -> DecisionBinding:
        """task -seam:decidedBy-> decision -dec:payloadElement-> DMN decision id;
        decision -seam:inModel-> model -seam:renderPayload-> DMN file."""
        iri = self._task(task)
        decision = _iri(self._one(iri, SEAM.decidedBy, "business-rule task has no decision"))
        element = self._one(decision, DEC.payloadElement, f"via {iri}")
        model = _iri(self._one(decision, SEAM.inModel, f"via {iri}"))
        payload = self._one(model, SEAM.renderPayload, f"via {iri}")
        dmn_path = payload_path(payload, self.base_dir)
        if not dmn_path.is_file():
            raise ResolutionError(model, SEAM.renderPayload, f"payload {dmn_path} not found, via {iri}")
        decision_id = str(element)
        ids = dmn_decision_ids(dmn_path)
        if decision_id not in ids:
            raise ResolutionError(
                decision,
                DEC.payloadElement,
                f"{decision_id!r} not among DMN decision ids {ids} in {dmn_path.name}, via {iri}",
            )
        inputs: list[InputBinding] = []
        types = dmn_input_types(dmn_path, decision_id)
        for node in self.ds.objects(decision, DEC.input):
            path = _iri(self._one(node, DEC.fromPath, f"input of {decision}"))
            variable = str(self._one(node, DEC.variable, f"input of {decision}"))
            inputs.append(
                InputBinding(
                    variable=variable,
                    from_path=local_name(path),
                    from_path_iri=path,
                    measure=_opt_iri(self.ds.value(node, DEC.measure)),
                    type_ref=types.get(variable),
                )
            )
        outputs: list[OutputBinding] = []
        for node in self.ds.objects(decision, DEC.output):
            outputs.append(
                OutputBinding(
                    variable=str(self._one(node, DEC.variable, f"output of {decision}")),
                    process_variable=str(self._one(node, DEC.processVariable, f"output of {decision}")),
                )
            )
        return DecisionBinding(
            iri,
            decision,
            model,
            dmn_path,
            decision_id,
            tuple(sorted(inputs, key=lambda b: b.variable)),
            tuple(sorted(outputs, key=lambda b: b.variable)),
        )

    # ── operations, containers, channels ──

    def implementing_container(self, operation: object, process: object = None) -> Container:
        """The container that seam:exposes the operation. ``in_process`` is
        True when it also seam:executes ``process`` (or any process, when no
        process is given)."""
        op = self.curie(operation)
        containers = _iris(self.ds.subjects(SEAM.exposes, op))
        if not containers:
            raise ResolutionError(op, SEAM.exposes, "no container exposes this operation")
        if len(containers) > 1:
            raise ResolutionError(
                op,
                SEAM.exposes,
                f"ambiguous: exposed by {[str(c) for c in containers]}",
            )
        c = containers[0]
        if process is None:
            in_process = (c, SEAM.executes, None) in self.ds
        else:
            in_process = (c, SEAM.executes, self.curie(process)) in self.ds
        return Container(c, self.label(c), in_process)

    def operation_path(self, operation: object) -> OperationPath:
        op = self.curie(operation)
        tpl_node = self._one(op, COMM.path, "operation has no comm:path")
        template = self._one(tpl_node, HYDRA.template, f"comm:path of {op}")
        mappings: list[PathMapping] = []
        for m in self.ds.objects(tpl_node, HYDRA.mapping):
            prop = _iri(self._one(m, HYDRA.property, f"mapping of {op}"))
            mappings.append(
                PathMapping(
                    str(self._one(m, HYDRA.variable, f"mapping of {op}")),
                    local_name(prop),
                    prop,
                )
            )
        return OperationPath(op, str(template), tuple(sorted(mappings, key=lambda m: m.variable)))

    def channel_for_event(self, task: object) -> ChannelBinding:
        iri = self._task(task)
        for ch in _iris(self.ds.objects(iri, SEAM.publishesTo)):
            if (ch, RDF.type, COMM.Channel) in self.ds:
                event = self._one(ch, COMM.eventName, f"channel of {iri}")
                return ChannelBinding(ch, self.label(ch), str(event))
        raise ResolutionError(iri, SEAM.publishesTo, "no comm:Channel target")

    # ── processes, lifecycles, policies, shapes ──

    def process_for(self, curie: object) -> ProcessFacts:
        iri = self.curie(curie)
        if (iri, RDF.type, PROC.Process) not in self.ds:
            raise ResolutionError(iri, RDF.type, "not a proc:Process")
        model = _iri(self._one(iri, SEAM.detailedBy, "process has no BPMN model"))
        return ProcessFacts(iri, self.label(iri), model, self.payload_path(model))

    def executing_container(self, process: object) -> Container:
        """The single container that seam:executes the process (in-process)."""
        iri = self.curie(process)
        containers = _iris(self.ds.subjects(SEAM.executes, iri))
        if len(containers) != 1:
            raise ResolutionError(
                iri, SEAM.executes, f"expected one executing container, found {[str(c) for c in containers]}"
            )
        return Container(containers[0], self.label(containers[0]), True)

    def triggering_operation(self, process: object) -> URIRef:
        """The operation that the event which seam:triggers the process
        seam:submitsTo."""
        iri = self.curie(process)
        ops = _iris(op for ev in self.ds.subjects(SEAM.triggers, iri) for op in self.ds.objects(ev, SEAM.submitsTo))
        if len(ops) != 1:
            raise ResolutionError(
                iri,
                SEAM.triggers,
                f"expected one triggering event submitting to one operation, found {[str(o) for o in ops]}",
            )
        return ops[0]

    # ── channel-started processes (ADR-0010) ──

    def _start_subscriptions(self, process: object) -> list[ChannelStart]:
        """(start event, channel) for each proc:MessageCatchEvent of the
        process's BPMN model that seam:subscribesTo a comm:Channel and is a
        bpmn:startEvent of its payload, sorted by (event, channel)."""
        iri = self.curie(process)
        if (iri, SEAM.detailedBy, None) not in self.ds:
            return []
        facts = self.process_for(iri)
        prefix = f"{facts.model}#"
        starts = bpmn_start_event_ids(facts.bpmn_path)
        found: set[tuple[URIRef, URIRef]] = set()
        for el, ch in self.ds.subject_objects(SEAM.subscribesTo):
            if (
                str(el).startswith(prefix)
                and (el, RDF.type, PROC.MessageCatchEvent) in self.ds
                and (ch, RDF.type, COMM.Channel) in self.ds
                and str(el)[len(prefix) :] in starts
            ):
                found.add((_iri(el), _iri(ch)))
        return [ChannelStart(facts.iri, el, ch) for el, ch in sorted(found)]

    def is_channel_started(self, process: object) -> bool:
        """True when the process has one channel start (``start_channel``),
        False when it has none. More than one raises ResolutionError."""
        subs = self._start_subscriptions(process)
        if len(subs) > 1:
            raise ResolutionError(
                self.curie(process),
                SEAM.subscribesTo,
                f"expected at most one subscribed start event, found {[(str(s.event), str(s.channel)) for s in subs]}",
            )
        return bool(subs)

    def start_channel(self, process: object) -> ChannelStart:
        """The start event of a channel-started process and the comm:Channel
        it seam:subscribesTo (there must be exactly one)."""
        subs = self._start_subscriptions(process)
        if len(subs) != 1:
            raise ResolutionError(
                self.curie(process),
                SEAM.subscribesTo,
                f"expected one proc:MessageCatchEvent start event subscribed to a "
                f"comm:Channel, found {[(str(s.event), str(s.channel)) for s in subs]}",
            )
        return subs[0]

    def subscribed_processes(self, channel: object) -> list[URIRef]:
        """The channel-started processes whose start event seam:subscribesTo
        ``channel``, sorted by IRI."""
        ch = self.curie(channel)
        found: set[URIRef] = set()
        for process in self.ds.subjects(RDF.type, PROC.Process):
            if any(s.channel == ch for s in self._start_subscriptions(process)):
                found.add(_iri(process))
        return sorted(found)

    def accepted_shape(self, operation: object) -> URIRef:
        return _iri(self._one(self.curie(operation), SEAM.acceptsShape, "operation accepts no shape"))

    def returned_shape(self, operation: object) -> URIRef:
        return _iri(self._one(self.curie(operation), SEAM.returnsShape, "operation returns no shape"))

    def process_channel(self, process: object) -> ChannelBinding:
        """The comm:Channel that elements of the process's BPMN model
        seam:publishesTo (there must be exactly one)."""
        facts = self.process_for(process)
        prefix = f"{facts.model}#"
        channels = _iris(
            ch
            for el, ch in self.ds.subject_objects(SEAM.publishesTo)
            if str(el).startswith(prefix) and (ch, RDF.type, COMM.Channel) in self.ds
        )
        if len(channels) != 1:
            raise ResolutionError(
                facts.iri,
                SEAM.publishesTo,
                f"expected one channel published to by {prefix}*, found {[str(c) for c in channels]}",
            )
        ch = channels[0]
        event = self._one(ch, COMM.eventName, f"channel of {facts.iri}")
        return ChannelBinding(ch, self.label(ch), str(event))

    def service_binding_key(self, container: object, service_of: object) -> str:
        """The deploy:key of ``container``'s deploy:binding whose
        deploy:serviceOf is ``service_of`` (e.g. LLM_GATEWAY_URL)."""
        c, target = self.curie(container), self.curie(service_of)
        keys = sorted(
            {
                str(self.ds.value(b, DEPLOY.key))
                for cfg in self.ds.objects(c, DEPLOY.configuration)
                for b in self.ds.objects(cfg, DEPLOY.binding)
                if (b, DEPLOY.serviceOf, target) in self.ds and self.ds.value(b, DEPLOY.key) is not None
            }
        )
        if len(keys) != 1:
            raise ResolutionError(
                c, DEPLOY.binding, f"expected one deploy:binding with deploy:serviceOf {target}, found {keys}"
            )
        return keys[0]

    def lifecycle_shape(self, transition: object) -> URIRef:
        """The shape whose seam:lifecycle machine state:hasTransition ``transition``."""
        t = self.curie(transition)
        shapes = _iris(
            shape
            for machine in self.ds.subjects(STATE.hasTransition, t)
            for shape in self.ds.subjects(SEAM.lifecycle, machine)
        )
        if len(shapes) != 1:
            raise ResolutionError(
                t,
                STATE.hasTransition,
                f"expected one shape whose lifecycle owns this transition, found {[str(s) for s in shapes]}",
            )
        return shapes[0]

    def correlation_key_labels(self) -> set[str]:
        """rdfs:labels of every proc:correlationKey parameter in the model."""
        return {str(self.label(p)) for p in self.ds.objects(None, PROC.correlationKey)}

    def correlation_key(self, process: object) -> str:
        iri = self.curie(process)
        param = self._one(iri, PROC.correlationKey)
        label = self._one(param, RDFS.label, f"correlation key of {iri}")
        return str(label)

    def lifecycle_for(self, shape: object) -> Lifecycle:
        iri = self.curie(shape)
        machine = _iri(self._one(iri, SEAM.lifecycle, "shape has no lifecycle"))
        initial = _iri(self._one(machine, STATE.initial, f"lifecycle of {iri}"))
        states = {_iri(s): self.label(s) for s in self.ds.objects(machine, STATE.hasState)}
        states.setdefault(initial, self.label(initial))
        return Lifecycle(machine, self.label(initial), states)

    def policies_for(self, operation: object) -> list[PolicyFacts]:
        op = self.curie(operation)
        policies = _iris(self.ds.objects(op, SEAM.governedBy))
        if not policies:
            raise ResolutionError(op, SEAM.governedBy, "operation is not governed by a policy")
        return [self.policy(p) for p in policies]

    def policy(self, policy: object) -> PolicyFacts:
        """Permissions of one odrl:Policy (target, action, assignee and its rdf:types)."""
        p = self.curie(policy)
        perms: list[Permission] = []
        for node in self.ds.objects(p, ODRL.permission):
            assignee = _opt_iri(self.ds.value(node, ODRL.assignee))
            types = () if assignee is None else tuple(_iris(self.ds.objects(assignee, RDF.type)))
            perms.append(
                Permission(
                    _opt_iri(self.ds.value(node, ODRL.target)),
                    _opt_iri(self.ds.value(node, ODRL.action)),
                    assignee,
                    types,
                )
            )
        perms.sort(key=lambda x: (str(x.target), str(x.action), str(x.assignee)))
        return PolicyFacts(p, self.label(p), tuple(perms))

    # ── IFML pages ──

    def landmark_page(self) -> URIRef:
        """The single ifml:ViewContainer with ifml:isLandmark true (the app entry page)."""
        pages = _iris(
            c for c in self.ds.subjects(RDF.type, IFML.ViewContainer) if (c, IFML.isLandmark, Literal(True)) in self.ds
        )
        if len(pages) != 1:
            raise ResolutionError(
                self.subject,
                IFML.isLandmark,
                f"expected one ifml:ViewContainer with ifml:isLandmark true, found {[str(p) for p in pages]}",
            )
        return pages[0]

    def secondary_pages(self) -> list[URIRef]:
        """The other ifml:ViewContainers served as pages: each one with an
        ifml:path that is not the landmark and holds no form a user task is
        seam:completedOn (such a screen is reached through the task inbox,
        ADR-0009). Sorted by IRI."""
        landmark = self.landmark_page()
        pages: list[URIRef] = []
        for c in set(self.ds.subjects(RDF.type, IFML.ViewContainer)):
            if c == landmark or (c, IFML.path, None) not in self.ds:
                continue
            if any((None, SEAM.completedOn, part) in self.ds for part in self.ds.objects(c, IFML.contains)):
                continue
            pages.append(_iri(c))
        return sorted(pages, key=str)

    def page_path(self, page: object) -> str:
        """The ifml:path a page is served at."""
        return str(self._one(self.curie(page), IFML.path, "page has no ifml:path"))

    def page_components(self, page: object) -> list[URIRef]:
        """The components a page ifml:contains, by ifml:order (then IRI)."""

        def order(c: URIRef) -> tuple[int, str]:
            value = self.ds.value(c, IFML.order)
            return (int(cast(Literal, value)) if value is not None else 1 << 30, str(c))

        return sorted(_iris(self.ds.objects(self.curie(page), IFML.contains)), key=order)

    def parameter_labels(self, component: object) -> set[str]:
        """rdfs:labels of a component's ifml:hasParameter parameters."""
        return {self.label(p) for p in self.ds.objects(self.curie(component), IFML.hasParameter)}

    def shape_graph(self) -> Graph:
        """The named graph(s) holding sh:NodeShape subjects (merged when several)."""
        names = sorted({c for _s, _p, _o, c in self.ds.quads((None, RDF.type, SH.NodeShape)) if c is not None}, key=str)
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


# ── payload XML ─────────────────────────────────────────────────────────────


def dmn_decision_ids(dmn_path: str | os.PathLike[str]) -> list[str]:
    return [cast(str, el.get("id")) for el in _elements(dmn_path) if _localname(el.tag) == "decision"]


def bpmn_start_event_ids(bpmn_path: str | os.PathLike[str]) -> set[str]:
    """ids of every bpmn:startEvent in the file."""
    return {cast(str, el.get("id")) for el in _elements(bpmn_path) if _localname(el.tag) == "startEvent"}


def dmn_input_types(dmn_path: str | os.PathLike[str], decision_id: str) -> dict[str, str]:
    """inputExpression text -> its typeRef, for the decision table of
    ``decision_id``. An expression without a typeRef is left out."""
    out: dict[str, str] = {}
    for decision in _elements(dmn_path):
        if not (_localname(decision.tag) == "decision" and decision.get("id") == decision_id):
            continue
        for el in decision.iter():
            type_ref = el.get("typeRef")
            if _localname(el.tag) == "inputExpression" and type_ref:
                text = "".join(t.text or "" for t in el if _localname(t.tag) == "text")
                out[text.strip()] = type_ref
    return out
