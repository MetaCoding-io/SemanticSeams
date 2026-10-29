"""SpiffWorkflow execution bound to the graph (ADR-0007 rule 2, D013).

The engine parses the BPMN that the process is ``seam:detailedBy`` and the DMN
files its business-rule tasks are ``seam:decidedBy``. No file name is fixed
here, and neither file carries a vendor extension:

- ``GraphBoundBusinessRuleTaskParser.get_decision_ref`` is a classmethod,
  because Spiff's ``BpmnDmnParser._find_dependencies`` calls it on the class.
  It resolves the task's decision through ``ModelGraph.decision_binding``
  (seam:decidedBy -> dec:payloadElement), so a decision id missing from the
  DMN is a ``ResolutionError`` at parse time.
- ``evaluate_inputs`` fills each dec:input variable from the entity
  (dec:fromPath, optionally dec:measure). Validated form values are strings,
  so an input whose DMN inputExpression has ``typeRef="number"`` is coerced
  to a ``Decimal`` (registered with the serializer) and compares numerically
  with entries such as ``<= 100``; a value that is not a number is a
  ``ResolutionError`` naming the decision. ``map_outputs`` copies each
  dec:output variable into its dec:processVariable. ``before_task`` fills the
  inputs before a business-rule task runs. The output mapping runs inside the
  task, on the spec's run_event, so the children inherit the process
  variables. ``after_task`` returns them. The worker calls these hooks, or
  calls ``run_task``, which wraps ``task.run()`` with them.

Plain bpmn:serviceTask specs stay STARTED after ``task.run()``. The caller
completes them once its handler has finished.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree
from rdflib import RDFS, URIRef

from SpiffWorkflow.bpmn.parser.TaskParser import TaskParser
from SpiffWorkflow.bpmn.parser.util import full_tag
from SpiffWorkflow.bpmn.serializer import BpmnWorkflowSerializer
from SpiffWorkflow.bpmn.serializer.config import DEFAULT_CONFIG
from SpiffWorkflow.bpmn.serializer.default.task_spec import BpmnTaskSpecConverter
from SpiffWorkflow.bpmn.specs.defaults import ServiceTask
from SpiffWorkflow.bpmn.specs.event_definitions.message import MessageEventDefinition
from SpiffWorkflow.bpmn.specs.mixins import BpmnSpecMixin
from SpiffWorkflow.bpmn.util.event import BpmnEvent
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.dmn.parser.BpmnDmnParser import BpmnDmnParser
from SpiffWorkflow.dmn.serializer import BaseBusinessRuleTaskConverter
from SpiffWorkflow.dmn.specs import BusinessRuleTaskMixin
from SpiffWorkflow.util.task import TaskState

from .errors import ResolutionError
from .model import DEC, SEAM, DecisionBinding, ModelGraph, ProcessFacts

log = logging.getLogger(__name__)

BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_NS = {"bpmn": BPMN_MODEL_NS}


# ── Spiff specs, parser and serializer ──────────────────────────────────────


class BusinessRuleTask(BusinessRuleTaskMixin, BpmnSpecMixin):
    """Vendor-neutral business-rule spec (no camunda/spiff extensions)."""


class GraphBoundBusinessRuleTaskParser(TaskParser):
    """bpmn:businessRuleTask parser whose decision ref comes from the graph.

    ``model`` and ``bpmn_model`` are bound per engine by ``_parser_classes``.
    """

    model: ModelGraph = None
    bpmn_model: URIRef = None

    @classmethod
    def task_iri(cls, node) -> URIRef:
        return URIRef(f"{cls.bpmn_model}#{node.get('id')}")

    @classmethod
    def binding(cls, node) -> DecisionBinding:
        return cls.model.decision_binding(cls.task_iri(node))

    @classmethod
    def get_decision_ref(cls, node) -> str:
        return cls.binding(node).decision_id

    def create_task(self):
        ref = self.get_decision_ref(self.node)
        engine = self.process_parser.parser.get_engine(ref, self.node)
        return self.spec_class(self.spec, self.bpmn_id, dmnEngine=engine, **self.bpmn_attributes)


class GraphBoundParser(BpmnDmnParser):
    OVERRIDE_PARSER_CLASSES = {}


def _parser_classes(model: ModelGraph, bpmn_model: URIRef):
    brt = type("BoundBusinessRuleTaskParser", (GraphBoundBusinessRuleTaskParser,),
               {"model": model, "bpmn_model": bpmn_model})
    parser_cls = type("BoundGraphParser", (GraphBoundParser,), {
        "OVERRIDE_PARSER_CLASSES": {full_tag("businessRuleTask"): (brt, BusinessRuleTask)},
    })
    return brt, parser_cls


def make_serializer() -> BpmnWorkflowSerializer:
    config = dict(DEFAULT_CONFIG)
    config[BusinessRuleTask] = BaseBusinessRuleTaskConverter
    # Spiff 3.2's DEFAULT_CONFIG registers only the spiff/camunda service-task
    # flavours. The plain bpmn ServiceTask has no extra state to save.
    config[ServiceTask] = BpmnTaskSpecConverter
    registry = BpmnWorkflowSerializer.configure(config)
    # Numeric DMN inputs (evaluate_inputs) are Decimals in the task data.
    registry.register(Decimal, lambda v: {"value": str(v)}, lambda v: Decimal(v["value"]))
    return BpmnWorkflowSerializer(registry)


def bpmn_process_ids(bpmn_path: Path) -> list[tuple[str, str | None, bool]]:
    """(id, name, isExecutable) of every bpmn:process in the file."""
    root = etree.parse(str(bpmn_path)).getroot()
    return [(p.get("id"), p.get("name"), p.get("isExecutable", "false").lower() == "true")
            for p in root.iterfind("bpmn:process", _NS)]


# ── the engine ──────────────────────────────────────────────────────────────


def _is_business_rule(task) -> bool:
    return isinstance(task.task_spec, BusinessRuleTask)


class Engine:
    """Builds, steps and (de)serializes workflows of one ``ModelGraph``."""

    def __init__(self, model: ModelGraph):
        self.model = model
        self.serializer = make_serializer()
        self._specs: dict = {}  # process IRI -> (ProcessFacts, process id, spec, subprocess specs)
        self._bindings: dict = {}  # task IRI -> DecisionBinding

    # ── parsing ──

    def process_id(self, process_curie) -> str:
        """The bpmn:process id inside the process's BPMN payload: the process
        whose name equals the proc:Process rdfs:label, else the only
        executable process."""
        facts = self.model.process_for(process_curie)
        return self._process_id(facts)

    def _process_id(self, facts: ProcessFacts) -> str:
        procs = bpmn_process_ids(facts.bpmn_path)
        named = [pid for pid, name, _ in procs if name is not None and name == facts.label]
        if len(named) == 1:
            return named[0]
        executable = [pid for pid, _, exe in procs if exe]
        if not named and len(executable) == 1:
            return executable[0]
        raise ResolutionError(
            facts.iri, RDFS.label,
            f"cannot pick a bpmn:process in {facts.bpmn_path.name}: "
            f"label {facts.label!r} matches {named}, executable processes {executable}",
        )

    def _spec(self, process_curie):
        iri = self.model.curie(process_curie)
        if iri not in self._specs:
            facts = self.model.process_for(iri)
            pid = self._process_id(facts)
            brt, parser_cls = _parser_classes(self.model, facts.model)
            parser = parser_cls()
            # Load exactly the DMN files the graph binds: no glob, no XML attribute.
            root = etree.parse(str(facts.bpmn_path)).getroot()
            for node in root.iterfind(".//bpmn:businessRuleTask", _NS):
                binding = brt.binding(node)
                self._bindings[binding.task] = binding
                parser.add_dmn_file(str(binding.dmn_path))
            parser.add_bpmn_file(str(facts.bpmn_path))
            spec = parser.get_spec(pid)
            subprocesses = parser.get_subprocess_specs(pid)
            self._specs[iri] = (facts, pid, spec, subprocesses)
            log.info("parsed %s -> bpmn process %r from %s (%d decision binding(s))",
                     iri, pid, facts.bpmn_path.name, len(self._bindings))
        return self._specs[iri]

    def new_workflow(self, process_curie) -> BpmnWorkflow:
        _facts, _pid, spec, subprocesses = self._spec(process_curie)
        return self._wire(BpmnWorkflow(spec, subprocesses))

    def _wire(self, wf: BpmnWorkflow) -> BpmnWorkflow:
        """Connect the output mapping to every business-rule spec's run_event.
        BusinessRuleTaskMixin emits it after merging the DMN result and before
        Task.complete() copies the data to the children, so process variables
        reach the rest of the process. Events are not serialized, so
        deserialize() wires again."""
        specs = [wf.spec, *wf.subprocess_specs.values()]
        for ts in (t for s in specs for t in s.task_specs.values()):
            if isinstance(ts, BusinessRuleTask) and not ts.run_event.is_connected(self._on_decided):
                ts.run_event.connect(self._on_decided)
        return wf

    def _on_decided(self, _workflow, task) -> None:
        mapped = self.map_outputs(self.binding(task), task.data)
        log.debug("decision %s -> %s", self.binding(task).decision_id, mapped)

    @staticmethod
    def deliver_start(wf: BpmnWorkflow, start_event: URIRef) -> bool:
        """Run Spiff's internal start and deliver the (empty) message the
        message start event ``start_event`` (``<BPMN model>#<bpmn id>``) waits
        for, leaving it READY for the worker (ADR-0010). The worker state
        carries the entities, not the message. A start event without a
        message definition is already reachable: returns False, changes nothing."""
        start_id = str(start_event).rsplit("#", 1)[-1]
        ready = [t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.bpmn_id is None]
        spec = wf.spec.task_specs.get(start_id)
        definition = getattr(spec, "event_definition", None)
        if not isinstance(definition, MessageEventDefinition):
            return False
        for t in ready:
            t.run()
        wf.catch(BpmnEvent(definition, {}))
        waiting = [t for t in wf.get_tasks(spec_name=start_id) if t.state != TaskState.READY]
        if waiting:
            raise ResolutionError(start_event, "bpmn:messageEventDefinition",
                                  f"start event is {TaskState.get_name(waiting[0].state)} "
                                  f"after its message was delivered")
        return True

    def serialize(self, wf: BpmnWorkflow) -> str:
        return self.serializer.serialize_json(wf)

    def deserialize(self, state: str) -> BpmnWorkflow:
        """No parser runs here: the spec (and the DMN tables) come from the JSON."""
        return self._wire(self.serializer.deserialize_json(state))

    # ── decision bindings ──

    def task_iri(self, task) -> URIRef:
        """Fragment IRI of a Spiff task's BPMN element, under the BPMN model
        the task's workflow was parsed from."""
        bpmn_id = task.task_spec.bpmn_id
        for facts, pid, _spec, _subs in self._specs.values():
            if pid == task.workflow.spec.name:
                return URIRef(f"{facts.model}#{bpmn_id}")
        # A deserialized workflow whose process this engine never parsed (a
        # resume after a restart): parse the process its seams state names.
        top = task.workflow
        while getattr(top, "parent_workflow", None) is not None:
            top = top.parent_workflow
        process = (top.data.get("seams") or {}).get("process")
        if process is not None and URIRef(process) not in self._specs:
            facts, pid, _spec, _subs = self._spec(URIRef(process))
            if pid == task.workflow.spec.name:
                return URIRef(f"{facts.model}#{bpmn_id}")
        return self.model.task_iri(bpmn_id)

    def binding(self, task) -> DecisionBinding:
        """The DecisionBinding of a business-rule Spiff task (or bpmn id / IRI)."""
        iri = self.task_iri(task) if hasattr(task, "task_spec") else self.model._task(task)
        if iri not in self._bindings:
            self._bindings[iri] = self.model.decision_binding(iri)
        return self._bindings[iri]

    def evaluate_inputs(self, binding: DecisionBinding, entity: dict) -> dict:
        """dec:input variable -> entity[dec:fromPath], measured by dec:measure."""
        out = {}
        for b in binding.inputs:
            if b.from_path not in entity:
                raise ResolutionError(
                    b.from_path_iri, DEC.fromPath,
                    f"entity has no field {b.from_path!r} for input {b.variable!r} of {binding.decision}",
                )
            value = entity[b.from_path]
            if b.measure is None:
                out[b.variable] = self._typed(binding, b, value)
            elif b.measure == DEC.Length:
                try:
                    out[b.variable] = len(value)
                except TypeError:
                    raise ResolutionError(
                        b.from_path_iri, DEC.measure,
                        f"dec:Length of non-sized {type(value).__name__} for input {b.variable!r}",
                    ) from None
            else:
                raise ResolutionError(
                    binding.decision, DEC.measure,
                    f"unknown measure {b.measure} for input {b.variable!r}",
                )
        return out

    @staticmethod
    def _typed(binding: DecisionBinding, b, value):
        """``value`` as the DMN input's typeRef expects: a Decimal for
        "number" (form values arrive as strings), else unchanged."""
        if b.type_ref != "number":
            return value
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return value
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            number = None
        if isinstance(value, bool) or number is None or not number.is_finite():
            raise ResolutionError(
                binding.decision, DEC.input,
                f"input {b.variable!r} of decision {binding.decision_id!r} is typeRef number, "
                f"but {b.from_path!r} is {value!r}",
            )
        return number

    def map_outputs(self, binding: DecisionBinding, task_data: dict) -> dict:
        """Copy each dec:output variable into its dec:processVariable (in place);
        returns the mapped values."""
        mapped = {}
        for b in binding.outputs:
            if b.variable not in task_data:
                raise ResolutionError(
                    binding.decision, DEC.output,
                    f"decision {binding.decision_id!r} produced no {b.variable!r} "
                    f"(have {sorted(task_data)})",
                )
            mapped[b.process_variable] = task_data[b.variable]
        task_data.update(mapped)
        return mapped

    # ── hooks around a task run ──

    def before_task(self, task, entity: dict | None) -> dict:
        """Populate a business-rule task's DMN inputs from ``entity``. Other
        tasks pass through untouched. Returns the values set."""
        if not _is_business_rule(task):
            return {}
        if entity is None:
            raise ResolutionError(self.task_iri(task), SEAM.decidedBy,
                                  "business-rule task needs an entity to evaluate inputs")
        inputs = self.evaluate_inputs(self.binding(task), entity)
        task.data.update(inputs)
        return inputs

    def after_task(self, task) -> dict:
        """The process variables a completed business-rule task produced. The
        mapping itself already ran inside the task (``_wire``); re-mapping is
        idempotent and fails if the decision produced no output."""
        if not _is_business_rule(task):
            return {}
        return self.map_outputs(self.binding(task), task.data)

    def run_task(self, task, entity: dict | None = None) -> None:
        """``task.run()`` wrapped in before_task/after_task. A service task is
        left STARTED for the caller's handler to complete."""
        self.before_task(task, entity)
        task.run()
        self.after_task(task)

    @staticmethod
    def is_service_task(task) -> bool:
        return isinstance(task.task_spec, ServiceTask)

    @staticmethod
    def is_business_rule(task) -> bool:
        return _is_business_rule(task)
