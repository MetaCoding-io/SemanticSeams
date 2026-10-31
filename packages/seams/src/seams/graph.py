"""The model as a resolver: one answer per graph question.

``ModelGraph`` is a ``Model`` plus the resolvers the runtime and the generators
share, such as which operation a BPMN task invokes, which container implements
that operation, which DMN decision a business-rule task is bound to, which
lifecycle transition it fires and which page is the landmark. Each answer comes
from graph facts. When a hop is missing, the resolver raises
``ResolutionError`` naming the subject IRI and the predicate it could not
follow.

These one-of-each resolvers are transitional: the S03 views supersede them.
The resolvers that used to assume one BPMN model or one served page now ask
the views: ``task_iri`` resolves through ``model.processes`` (any number of
BPMN models; an id in two of them raises) and ``landmark_page`` is
``model.interfaces.landmark()``. The pages the app serves are
``model.interfaces.served_pages()``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from rdflib import RDF, Dataset, Graph, Literal, URIRef
from rdflib.namespace import SH

from ._xml import elements as _elements
from ._xml import localname as _localname
from .errors import ResolutionError
from .loader import Model
from .namespaces import COMM, DEPLOY, IFML, PROC, SEAM, STATE

if TYPE_CHECKING:
    # The views import this module (for the resolver results), so they are
    # imported lazily inside the resolvers.
    from .views.architecture import Container as ContainerView
    from .views.interfaces import Component, Page
    from .views.operations import Channel as ChannelView
    from .views.operations import Operation
    from .views.processes import Process, ProcessElement
    from .views.shapes import Shape

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
    transitions: frozenset[URIRef] = field(default_factory=frozenset[URIRef])  # its state:hasTransition


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


#: The implementation kinds of ADR-0012: the rdf:type of a seam:implementedBy node.
IMPLEMENTATION_KINDS = (COMM.HTTPEndpoint, COMM.LLMCompletion, COMM.PythonHandler)

#: A comm:handler dotted path: Python identifier segments only, so it can name
#: nothing outside the handlers package (the same pattern as seamsh:PythonHandlerShape).
HANDLER_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True)
class Implementation:
    """What serves an operation (ADR-0012), from ``ModelGraph.operation_implementation``.

    ``kind`` is an ``IMPLEMENTATION_KINDS`` member. ``handler`` is the
    comm:handler dotted path of a comm:PythonHandler, relative to the handlers
    package, and None for the other kinds.
    """

    iri: URIRef
    kind: URIRef
    handler: str | None


#: The deploy:StoreKinds the runtime can open (ADR-0011).
SUPPORTED_STORE_KINDS = (DEPLOY.PostgreSQL, DEPLOY.SQLite)


@dataclass(frozen=True)
class StorePlan:
    """Where the runtime keeps its rows (ADR-0011), from ``ModelGraph.store_plan()``.

    ``kind`` is a ``SUPPORTED_STORE_KINDS`` member and ``store`` the store
    container (None for the undeclared default). ``container`` is the runtime
    container whose binding deploy:connectsTo the store and ``key`` that
    binding's deploy:key, the environment variable holding the connection
    string; both are None without a connecting binding (always so for the
    default, and allowed for deploy:SQLite, whose path comes from
    ``SEAMS_DB``). ``declared`` is False only for the embedded SQLite default
    of a model that declares no store.
    """

    kind: URIRef
    store: URIRef | None
    container: URIRef | None
    key: str | None
    declared: bool


#: ``StoreFinding.severity`` values, most severe first (SHACL's sh:Violation,
#: sh:Warning and sh:Info local names).
STORE_FINDING_SEVERITIES = ("Violation", "Warning", "Info")


@dataclass(frozen=True)
class StoreFinding:
    """One storage health finding (ADR-0011), from ``ModelGraph.store_health()``.

    ``severity`` is a ``STORE_FINDING_SEVERITIES`` member: a Violation is a
    store the runtime cannot resolve (``subject``/``predicate`` name the
    missing hop, as ``ResolutionError`` does), a Warning a store container no
    shape is seam:storedIn (predicate seam:storedIn), an Info the embedded
    SQLite default of a model that declares no store (no subject).
    """

    severity: str
    subject: URIRef | None
    predicate: URIRef | None
    message: str


# ── the graph ───────────────────────────────────────────────────────────────


class ModelGraph(Model):
    """A loaded seams model plus the resolvers the worker and generators dispatch on.

    A facade over the views: every resolver below reads the graph through
    ``model.processes``, ``model.operations``, ``model.lifecycles`` and the
    other views, and turns a missing hop into ``ResolutionError`` naming the
    subject IRI and the predicate it could not follow."""

    def __init__(self, trig_path: str | os.PathLike[str], dataset: Dataset | None = None) -> None:
        super().__init__(trig_path, dataset)
        # Per-instance caches (never module-level id()-keyed dicts; see MEM010).
        self._contract_cache: dict[Any, Any] = {}

    @classmethod
    def load(cls, trig_path: str | os.PathLike[str]) -> ModelGraph:
        return cls(trig_path)

    # ── view elements by IRI (interned; any IRI, typed or not) ──

    def task_element(self, task: object) -> ProcessElement:
        """The ``ProcessElement`` view of a BPMN element (bpmn id, CURIE or IRI)."""
        from .views.processes import ProcessElement

        return self.views.intern(ProcessElement, self._task(task))

    def shape(self, shape: object) -> Shape:
        """The ``Shape`` view of ``shape`` (CURIE or IRI)."""
        from .views.shapes import Shape

        return self.views.intern(Shape, self.curie(shape))

    def page(self, page: object) -> Page:
        """The ``Page`` view of ``page`` (CURIE or IRI)."""
        from .views.interfaces import Page

        return self.views.intern(Page, self.curie(page))

    def component(self, component: object) -> Component:
        """The ``Component`` view of ``component`` (CURIE or IRI)."""
        from .views.interfaces import Component

        return self.views.intern(Component, self.curie(component))

    def _operation(self, operation: object) -> Operation:
        from .views.operations import Operation

        return self.views.intern(Operation, self.curie(operation))

    def _process(self, process: object) -> Process:
        """The typed proc:Process ``process``; anything else raises
        ``ResolutionError(iri, rdf:type)``."""
        iri = self.curie(process)
        found = self.processes.where(lambda p: p.iri == iri)
        if not found:
            raise ResolutionError(iri, RDF.type, "not a proc:Process")
        return found[0]

    # ── BPMN element IRIs ──

    def task_iri(self, bpmn_id: str) -> URIRef:
        """Fragment IRI of a BPMN element, ``<BPMN model IRI>#<bpmn id>``
        (``model.processes``): the graph element with that id, else (an
        element not lifted into the TriG) the process whose BPMN file holds an
        element with that id. An id in several BPMN models, or in none, raises
        ``ResolutionError``."""
        processes = self.processes
        lifted = processes.element(bpmn_id)
        if lifted:
            return lifted.only().iri
        holders = [p for p in processes if len(p.bpmn_models) == 1 and bpmn_id in self._bpmn_ids(p.bpmn_path)]
        if len(holders) != 1:
            raise ResolutionError(
                self.subject,
                SEAM.detailedBy,
                f"expected one BPMN model with an element {bpmn_id!r}, found {[str(p.bpmn_model) for p in holders]}",
            )
        return holders[0].element_iri(bpmn_id)

    def _bpmn_ids(self, path: Path) -> frozenset[str]:
        """ids of every element of a BPMN file (read once per model)."""
        return self.views.view(
            f"bpmn-element-ids:{path}", lambda: frozenset(str(el.get("id")) for el in _elements(path) if el.get("id"))
        )

    def _task(self, task: object) -> URIRef:
        if isinstance(task, URIRef) or "://" in str(task) or ":" in str(task):
            return self.curie(task)
        return self.task_iri(str(task))

    # ── task facts ──

    def invoked_operation(self, task: object) -> URIRef:
        element = self.task_element(task)
        op = element.invokes
        if op is None:
            raise ResolutionError(element.iri, SEAM.invokes, "task invokes no operation")
        return op.iri

    def fired_transition(self, task: object) -> Transition:
        element = self.task_element(task)
        t = element.fires
        if t is None:
            raise ResolutionError(element.iri, SEAM.fires, "task fires no transition")
        return self._transition(t.iri)

    def _transition(self, transition: object) -> Transition:
        """The (iri, from label, to label, trigger) of a state:Transition; a
        missing state:from or state:to raises ``ResolutionError(transition, predicate)``."""
        from .views.lifecycles import Transition as TransitionView

        t = self.views.intern(TransitionView, self.curie(transition))
        return Transition(t.iri, t.from_state.label, t.to_state.label, t.trigger)

    def transitions_from(self, state_label: str, trigger: str | None = None) -> list[Transition]:
        """Transitions leaving the state labelled ``state_label`` (and with the
        given state:trigger, if any), sorted by IRI."""
        from .views.lifecycles import Transition as TransitionView

        out: list[Transition] = []
        for t in self.views.all(TransitionView, STATE.Transition):
            if not t.from_states or t.from_states[0].label != state_label:
                continue
            tr = self._transition(t.iri)
            if trigger is None or tr.trigger == trigger:
                out.append(tr)
        return out

    def read_shapes(self, task: object) -> list[URIRef]:
        return list(self.task_element(task).reads.iris())

    def written_shapes(self, task: object) -> list[URIRef]:
        return list(self.task_element(task).writes.iris())

    # ── user tasks (ADR-0009) ──

    def user_task_form(self, task: object) -> URIRef:
        """The ifml:Form a user task is seam:completedOn."""
        element = self.task_element(task)
        form = element.completed_on
        if form is None:
            raise ResolutionError(element.iri, SEAM.completedOn, "user task names no form it is completed on")
        return form.iri

    def task_output_shape(self, task: object) -> URIRef:
        """The shape completing a user task writes: its form's seam:writes,
        else the task's own seam:writes (there must be exactly one)."""
        iri = self._task(task)
        shapes = list(self.component(self.user_task_form(iri)).writes.iris())
        if not shapes:
            shapes = self.written_shapes(iri)
        if len(shapes) != 1:
            raise ResolutionError(
                iri, SEAM.writes, f"expected one output shape for the user task, found {[str(s) for s in shapes]}"
            )
        return shapes[0]

    def form_screen(self, form: object) -> URIRef | None:
        """The ifml:ViewContainer that ifml:contains ``form``, or None."""
        screens = self.component(form).screens
        return screens[0].iri if screens else None

    # ── decisions ──

    def decision_binding(self, task: object) -> DecisionBinding:
        """task -seam:decidedBy-> decision -dec:payloadElement-> DMN decision id;
        decision -seam:inModel-> model -seam:renderPayload-> DMN file
        (``model.decisions``)."""
        element = self.task_element(task)
        decision = element.decided_by
        if decision is None:
            raise ResolutionError(element.iri, SEAM.decidedBy, "business-rule task has no decision")
        return DecisionBinding(
            element.iri,
            decision.iri,
            decision.dmn_model,
            decision.dmn_path,
            decision.decision_id,
            decision.inputs,
            decision.outputs,
        )

    # ── operations, containers, channels ──

    def implementing_container(self, operation: object, process: object = None) -> Container:
        """The container that seam:exposes the operation. ``in_process`` is
        True when it also seam:executes ``process`` (or any process, when no
        process is given)."""
        op = self._operation(operation)
        containers = op.exposed_by
        if not containers:
            raise ResolutionError(op.iri, SEAM.exposes, "no container exposes this operation")
        if len(containers) > 1:
            raise ResolutionError(
                op.iri,
                SEAM.exposes,
                f"ambiguous: exposed by {[str(c) for c in containers.iris()]}",
            )
        c = containers[0]
        executes = c.executes.iris()
        in_process = bool(executes) if process is None else self.curie(process) in executes
        return Container(c.iri, c.label, in_process)

    def operation_implementation(self, operation: object) -> Implementation | None:
        """The implementation the operation is seam:implementedBy (ADR-0012), or
        None when it declares none. Several, or one that is not an IRI, raise
        ``ResolutionError(operation, seam:implementedBy)``; no kind, several or
        one outside ``IMPLEMENTATION_KINDS`` raise ``ResolutionError(implementation,
        rdf:type)``; a comm:PythonHandler without exactly one comm:handler of
        identifier segments raises ``ResolutionError(implementation, comm:handler)``."""
        from .views._base import one_value

        op = self._operation(operation)
        stated = sorted(set(self.ds.objects(op.iri, SEAM.implementedBy)), key=str)
        if not stated:
            return None
        if len(stated) > 1:
            raise ResolutionError(
                op.iri, SEAM.implementedBy, f"expected at most one, found {', '.join(map(str, stated))}"
            )
        # A literal or blank node is no implementation: the IRI collection is empty.
        impl = op.implemented_by.only()
        kind = one_value(self.ds, impl.iri, RDF.type)
        if not isinstance(kind, URIRef) or kind not in IMPLEMENTATION_KINDS:
            raise ResolutionError(
                impl.iri,
                RDF.type,
                f"{kind} is not an implementation kind ({', '.join(map(str, IMPLEMENTATION_KINDS))})",
            )
        if kind != COMM.PythonHandler:
            return Implementation(impl.iri, kind, None)
        handler = one_value(self.ds, impl.iri, COMM.handler)
        if not isinstance(handler, Literal) or not HANDLER_PATH.fullmatch(str(handler)):
            raise ResolutionError(
                impl.iri,
                COMM.handler,
                f"expected a dotted path of Python identifiers inside the handlers package, found {str(handler)!r}",
            )
        return Implementation(impl.iri, kind, str(handler))

    def operation_path(self, operation: object) -> OperationPath:
        op = self._operation(operation)
        path = op.path
        if path is None:
            raise ResolutionError(op.iri, COMM.path, "operation has no comm:path")
        return OperationPath(op.iri, path.template, path.mappings)

    def _channel(self, channel: ChannelView, via: URIRef) -> ChannelBinding:
        event = channel.event_name
        if event is None:
            raise ResolutionError(channel.iri, COMM.eventName, f"channel of {via}")
        return ChannelBinding(channel.iri, channel.label, event)

    def published_channel(self, element: object) -> ChannelBinding | None:
        """The single comm:Channel the element seam:publishesTo, None when it
        declares none. More than one raises ResolutionError (D046)."""
        el = self.task_element(element)
        typed = self.channels
        found = {ch.iri: ch for ch in el.publishes_to if ch in typed}
        if len(found) > 1:
            raise ResolutionError(
                el.iri, SEAM.publishesTo, f"expected at most one comm:Channel, found {[str(i) for i in sorted(found)]}"
            )
        if not found:
            return None
        return self._channel(next(iter(found.values())), el.iri)

    def published_channels(self, process: object) -> list[ChannelBinding]:
        """The distinct comm:Channels that any element of the process's BPMN
        model seam:publishesTo, sorted by IRI (none, one or many)."""
        facts = self.process_for(process)
        typed = self.channels
        found = {ch.iri: ch for el in self._process(facts.iri).elements() for ch in el.publishes_to if ch in typed}
        return [self._channel(found[i], facts.iri) for i in sorted(found)]

    def channel_for_event(self, task: object) -> ChannelBinding:
        channel = self.published_channel(task)
        if channel is None:
            raise ResolutionError(self.task_element(task).iri, SEAM.publishesTo, "no comm:Channel target")
        return channel

    # ── processes, lifecycles, policies, shapes ──

    def process_for(self, curie: object) -> ProcessFacts:
        process = self._process(curie)
        if not process.bpmn_models:
            raise ResolutionError(process.iri, SEAM.detailedBy, "process has no BPMN model")
        return ProcessFacts(process.iri, process.label, process.bpmn_model, process.bpmn_path)

    def executing_container(self, process: object) -> Container:
        """The single container that seam:executes the process (in-process)."""
        from .views.processes import Process

        iri = self.curie(process)
        containers = self.views.intern(Process, iri).executed_by
        if len(containers) != 1:
            raise ResolutionError(
                iri, SEAM.executes, f"expected one executing container, found {[str(c) for c in containers.iris()]}"
            )
        return Container(containers[0].iri, containers[0].label, True)

    def triggering_operation(self, process: object) -> URIRef:
        """The operation that the event which seam:triggers the process
        seam:submitsTo."""
        from .views.processes import Process

        iri = self.curie(process)
        ops = self.views.intern(Process, iri).triggering_operations
        if len(ops) != 1:
            raise ResolutionError(
                iri,
                SEAM.triggers,
                f"expected one triggering event submitting to one operation, found {[str(o) for o in ops.iris()]}",
            )
        return ops[0].iri

    # ── channel-started processes (ADR-0010) ──

    def _start_subscriptions(self, process: object) -> list[ChannelStart]:
        """(start event, channel) for each proc:MessageCatchEvent of the
        process's BPMN model that seam:subscribesTo a comm:Channel and is a
        bpmn:startEvent of its payload (``Process.channel_starts``), sorted
        by (event, channel)."""
        from .views.processes import Process

        iri = self.curie(process)
        if not self.views.intern(Process, iri).bpmn_models:
            return []
        p = self._process(iri)
        return [ChannelStart(p.iri, s.event.iri, s.channel.iri) for s in p.channel_starts]

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
        return [p.iri for p in self.processes if any(s.channel == ch for s in self._start_subscriptions(p.iri))]

    def accepted_shape(self, operation: object) -> URIRef:
        op = self._operation(operation)
        shape = op.accepts
        if shape is None:
            raise ResolutionError(op.iri, SEAM.acceptsShape, "operation accepts no shape")
        return shape.iri

    def returned_shape(self, operation: object) -> URIRef:
        op = self._operation(operation)
        shape = op.returns
        if shape is None:
            raise ResolutionError(op.iri, SEAM.returnsShape, "operation returns no shape")
        return shape.iri

    def service_binding_key(self, container: object, service_of: object) -> str:
        """The deploy:key of ``container``'s deploy:binding whose
        deploy:serviceOf is ``service_of`` (e.g. LLM_GATEWAY_URL)."""
        from .views.architecture import Container as ContainerView

        c, target = self.curie(container), self.curie(service_of)
        bindings = self.views.intern(ContainerView, c).service_bindings
        keys = sorted(key for key, bound in bindings.items() if bound == target)
        if len(keys) != 1:
            raise ResolutionError(
                c, DEPLOY.binding, f"expected one deploy:binding with deploy:serviceOf {target}, found {keys}"
            )
        return keys[0]

    def lifecycle_shape(self, transition: object) -> URIRef:
        """The shape whose seam:lifecycle machine state:hasTransition ``transition``."""
        from .views.lifecycles import Transition as TransitionView

        t = self.curie(transition)
        view = self.views.intern(TransitionView, t)
        shapes = sorted({s.iri for lc in view.lifecycles for s in lc.shapes})
        if len(shapes) != 1:
            raise ResolutionError(
                t,
                STATE.hasTransition,
                f"expected one shape whose lifecycle owns this transition, found {[str(s) for s in shapes]}",
            )
        return shapes[0]

    def correlation_key_labels(self) -> set[str]:
        """rdfs:labels of every proc:correlationKey parameter in the model."""
        return {self.label(param) for p in self.processes for param in p.correlation_parameters}

    def correlation_key(self, process: object) -> str:
        from .views.processes import Process

        iri = self.curie(process)
        params = self.views.intern(Process, iri).correlation_parameters
        if not params:
            raise ResolutionError(iri, PROC.correlationKey)
        return self.label(params[0], strict=True)

    def has_lifecycle(self, shape: object) -> bool:
        """True when ``shape`` names a seam:lifecycle state machine."""
        return self.shape(shape).lifecycle is not None

    def lifecycle_for(self, shape: object) -> Lifecycle:
        """The seam:lifecycle machine of ``shape``: its IRI, initial state
        label, state labels by IRI and its state:hasTransition transitions."""
        view = self.shape(shape)
        machine = view.lifecycle
        if machine is None:
            raise ResolutionError(view.iri, SEAM.lifecycle, "shape has no lifecycle")
        initial = machine.initial
        states = {s.iri: s.label for s in machine.states()}
        return Lifecycle(machine.iri, initial.label, states, frozenset(machine.transitions().iris()))

    def governing_policies(self, element: object) -> list[PolicyFacts]:
        """The policies ``element`` (an operation, user task or event) is
        seam:governedBy, by IRI; empty when it is ungoverned."""
        iri = self.curie(element)
        return [self.policy(p.iri) for p in self.policies if iri in p.governs.iris()]

    def policies_for(self, operation: object) -> list[PolicyFacts]:
        op = self._operation(operation)
        policies = op.governed_by
        if not policies:
            raise ResolutionError(op.iri, SEAM.governedBy, "operation is not governed by a policy")
        return [self.policy(p.iri) for p in policies]

    def policy(self, policy: object) -> PolicyFacts:
        """Permissions of one odrl:Policy (target, action, assignee and its rdf:types)."""
        from .views.policies import Policy

        p = self.views.intern(Policy, self.curie(policy))
        return PolicyFacts(p.iri, p.label, p.permissions)

    # ── storage (ADR-0011) ──

    def store_plan(self) -> StorePlan:
        """The store the runtime keeps its rows in, from deploy:storeKind,
        deploy:connectsTo and seam:storedIn (ADR-0011).

        Runtime containers are those that seam:execute a process or
        seam:expose an operation that seam:writes a shape. A model with no
        connecting binding on one and no seam:storedIn at all gets the
        undeclared embedded SQLite default. Otherwise the store is the one a
        runtime container connects to, else the one the written shapes are
        stored in. Every failure raises ``ResolutionError(subject, predicate)``:
        a container connecting to two stores, or two containers to different
        stores (container, deploy:connectsTo); a store without exactly one
        deploy:storeKind, or an unsupported one (store, deploy:storeKind); a
        PostgreSQL store no runtime container connects to (the container, or
        the store when there is none; deploy:connectsTo); a written shape not
        stored in exactly that store (shape, seam:storedIn).
        """
        from .views.shapes import Shape

        ds = self.ds
        views = self.views
        written = views.many(Shape, views.iris(ds.objects(None, SEAM.writes)), self.subject, SEAM.writes)
        writers = {w.iri for shape in written for w in shape.written_by}
        runtime = [
            c
            for c in self.architecture.containers()
            if c.executes or any(endpoint.iri in writers for endpoint in c.exposes)
        ]

        # The connections: at most one store per container, and one per model.
        connected: list[tuple[ContainerView, URIRef, str]] = []
        for c in runtime:
            bindings = c.connecting_bindings
            stores = sorted({b.connects_to.iri for b in bindings if b.connects_to is not None}, key=str)
            if len(stores) > 1:
                raise ResolutionError(
                    c.iri, DEPLOY.connectsTo, f"bindings connect to several stores {[str(s) for s in stores]}"
                )
            if stores:
                connected.append((c, stores[0], bindings[0].key))
        for c, store, _key in connected[1:]:
            if store != connected[0][1]:
                raise ResolutionError(
                    c.iri,
                    DEPLOY.connectsTo,
                    f"v1 runs one store per model: {connected[0][0].iri} connects to {connected[0][1]}, this to {store}",
                )

        stored = views.iris(ds.objects(None, SEAM.storedIn))
        if not connected and not stored:
            return StorePlan(DEPLOY.SQLite, None, None, None, declared=False)

        # The store: the connected one, else the one the written shapes are stored in.
        if connected:
            store = connected[0][1]
        else:
            candidates = sorted({c.iri for shape in written for c in shape.stored_in}, key=str) or stored
            store = candidates[0]
            if len(candidates) > 1:
                pool = written
                if not any(s.stored_in for s in written):
                    pool = views.many(Shape, views.iris(ds.subjects(SEAM.storedIn, None)), self.subject, SEAM.storedIn)
                offender = next(s for s in pool if s.stored_in and s.stored_in.iris() != (store,))
                raise ResolutionError(
                    offender.iri,
                    SEAM.storedIn,
                    f"v1 runs one store per model; shapes are stored in {[str(c) for c in candidates]}",
                )

        kinds = sorted(set(ds.objects(store, DEPLOY.storeKind)), key=str)
        if len(kinds) != 1:
            found = "none" if not kinds else ", ".join(map(str, kinds))
            raise ResolutionError(store, DEPLOY.storeKind, f"a store needs exactly one deploy:storeKind, found {found}")
        kind = kinds[0]
        if not isinstance(kind, URIRef) or kind not in SUPPORTED_STORE_KINDS:
            supported = ", ".join(map(str, SUPPORTED_STORE_KINDS))
            raise ResolutionError(store, DEPLOY.storeKind, f"unsupported store kind {kind}; supported: {supported}")
        if kind == DEPLOY.PostgreSQL and not connected:
            raise ResolutionError(
                runtime[0].iri if runtime else store,
                DEPLOY.connectsTo,
                f"a deploy:PostgreSQL store needs a deploy:connectsTo binding to {store} on the executing container",
            )

        for shape in written:
            if shape.stored_in.iris() != (store,):
                where = [str(c) for c in shape.stored_in.iris()] or "no store"
                raise ResolutionError(
                    shape.iri, SEAM.storedIn, f"a written shape must be stored in {store}; it is stored in {where}"
                )

        container, key = (connected[0][0].iri, connected[0][2]) if connected else (None, None)
        return StorePlan(kind, store, container, key, declared=True)

    def store_health(self) -> list[StoreFinding]:
        """Storage health findings for model-health tools (ADR-0011 Observability).

        A Violation when ``store_plan()`` raises; an Info when the model
        declares no store, so the runtime keeps embedded SQLite at
        ``SEAMS_DB``; and, either way, a Warning for each store container (one
        with a deploy:storeKind or that a binding deploy:connectsTo) no shape
        is seam:storedIn. Sorted by severity, then subject. Never raises.
        """
        findings: list[StoreFinding] = []
        try:
            plan = self.store_plan()
        except ResolutionError as err:
            findings.append(StoreFinding("Violation", URIRef(err.subject), URIRef(err.predicate), str(err)))
        else:
            if not plan.declared:
                findings.append(
                    StoreFinding(
                        "Info",
                        None,
                        None,
                        "no store is declared, so the runtime keeps embedded SQLite at SEAMS_DB",
                    )
                )

        ds = self.ds
        stores = {s for s in ds.subjects(DEPLOY.storeKind, None) if isinstance(s, URIRef)}
        stores |= {o for o in ds.objects(None, DEPLOY.connectsTo) if isinstance(o, URIRef)}
        stored = set(ds.objects(None, SEAM.storedIn))
        for store in stores - stored:
            findings.append(
                StoreFinding(
                    "Warning",
                    store,
                    SEAM.storedIn,
                    f"store {store} is declared but no shape is seam:storedIn it",
                )
            )

        order = {severity: i for i, severity in enumerate(STORE_FINDING_SEVERITIES)}
        return sorted(findings, key=lambda f: (order[f.severity], str(f.subject or "")))

    # ── IFML pages ──

    def landmark_page(self) -> URIRef:
        """The single ifml:ViewContainer with ifml:isLandmark true (the app
        entry page; ``model.interfaces.landmark()``)."""
        return self.interfaces.landmark().iri

    def page_path(self, page: object) -> str:
        """The ifml:path a page is served at."""
        view = self.page(page)
        path = view.path
        if path is None:
            raise ResolutionError(view.iri, IFML.path, "page has no ifml:path")
        return path

    def page_components(self, page: object) -> list[URIRef]:
        """The components a page ifml:contains, by ifml:order (then IRI)."""
        return list(self.page(page).components().iris())

    def parameter_labels(self, component: object) -> set[str]:
        """rdfs:labels of a component's ifml:hasParameter parameters."""
        return set(self.component(component).parameters())

    def rendered_components(self) -> list[URIRef]:
        """The components an operation seam:rendersComponent (UI fragments), by IRI."""
        return sorted({c.iri for op in self.operations for c in op.renders})

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
