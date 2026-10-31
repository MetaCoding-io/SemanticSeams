"""The tests generator: pytest files from what a model says it should do (M015/S03, ADR-0014).

``extract_tests`` reads the model's ``verify:`` facts through the seams views
(``model.scenarios``, ``model.decision_examples``, ``Shape.valid_examples``
and ``Shape.invalid_examples``) into frozen dataclasses, resolving each
scenario to the routes a person would use: the operation the events that
``seam:triggers`` its process ``seam:submitsTo`` (``Process.triggering_operations``),
and for each step the operation an event of the form its user task is
``seam:completedOn`` submits to. ``render_tests`` renders them through the
``tests_*.py.j2`` templates into three files:

- ``test_scenarios.py``: one test per ``verify:Scenario``, run in-process on
  the host app (``seams_runtime.verify.run_scenario``);
- ``test_decisions.py``: one test per ``verify:DecisionExample``, evaluated by
  the runtime's DMN engine (``Engine.decide``);
- ``test_shape_examples.py``: one test per valid or invalid shape example,
  validated by pyshacl against that shape alone.

Every value in the output comes from the model; the templates hold the fixed
harness calls only (principle 1). Test names embed IRI local names
(``test_scenario_manager_approved``), so a CI failure names the model fact
that broke. Scenarios, decision examples and shapes are sorted by IRI, givens
by field IRI, steps keep their list order and expected outputs are sorted by
variable (principle 6). Each file starts with the generator header and the
model hash, and the tests refuse to run against a model with another hash.

A fault the ADR-0014 shapes flag raises ``GeneratorError`` naming the subject
and predicate. Generator-only, because they are routing facts the fastapi
generator needs as well (the README lists them): the one serving route module
the scenarios run on, the one operation (with hydra:method and comm:path) that
starts a scenario's process or completes a step's task, the form a step's
task is seam:completedOn, and two IRIs whose local names would give two tests
one name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rdflib import XSD, Literal
from seams import COMM, HYDRA, SEAM, STATE, VERIFY, Model, Operation, Scenario, Shape, load, local_name

from . import GeneratorError
from ._views import required, view_errors
from .fastapi import route_module
from .htmx import _environment

FILES = {
    "test_scenarios.py": "tests_scenarios.py.j2",
    "test_decisions.py": "tests_decisions.py.j2",
    "test_shape_examples.py": "tests_shape_examples.py.j2",
}
NOT_IDENTIFIER = re.compile(r"[^0-9A-Za-z_]")


# ── the tests model ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RequestModel:
    """One form submission; every field is a Python literal."""

    method: str
    path: str
    actor: str
    data: tuple[tuple[str, str], ...]  # (field name literal, lexical value literal)


@dataclass(frozen=True)
class StepModel:
    task: str  # IRI literal
    curie: str
    request: RequestModel


@dataclass(frozen=True)
class ScenarioModel:
    name: str  # the test function name
    curie: str
    iri: str  # Python literals from here on
    process: str
    process_curie: str
    key_variable: str
    key: str
    start: RequestModel
    steps: tuple[StepModel, ...]
    entity_shape: str
    expect_state: str  # the state's label literal, or "None"
    expect_state_curie: str | None
    expect_end_event: str | None  # IRI literal
    expect_end_event_curie: str | None
    state_failure: str  # assertion message literals
    end_event_failure: str


@dataclass(frozen=True)
class OutputModel:
    variable: str  # Python literals
    lexical: str
    datatype: str


@dataclass(frozen=True)
class DecisionExampleModel:
    name: str
    curie: str
    decision: str  # IRI literal
    decision_curie: str
    inputs: tuple[tuple[str, str], ...]
    outputs: tuple[OutputModel, ...]


@dataclass(frozen=True)
class ShapeExampleModel:
    name: str
    shape: str  # IRI literal
    shape_curie: str
    node: str  # IRI literal
    node_curie: str
    valid: bool
    predicate: str  # verify:validExample or verify:invalidExample
    failure: str  # the invalid example's assertion message literal


@dataclass(frozen=True)
class TestsModel:
    model_stem: str
    model_hash: str
    routes: str | None  # the route module file name literal, when there are scenarios
    scenarios: tuple[ScenarioModel, ...]
    decision_examples: tuple[DecisionExampleModel, ...]
    shape_examples: tuple[ShapeExampleModel, ...]


# ── extraction ──────────────────────────────────────────────────────────────


def _py(value: object) -> str:
    """``value`` as a Python literal (strings double-quoted, as ruff formats them)."""
    if value is None:
        return "None"
    return json.dumps(str(value), ensure_ascii=False)


def _name(prefix: str, *iris: object) -> str:
    """A test function name from IRI local names."""
    return "_".join([prefix, *(NOT_IDENTIFIER.sub("_", local_name(i)) for i in iris)])


def _lexical(value: Literal) -> str:
    return str(value)


def _datatype(value: Literal) -> str:
    """The literal's datatype IRI; a plain or language-tagged literal is an xsd:string."""
    return str(value.datatype) if value.datatype is not None else str(XSD.string)


def _submits(subject: object, predicate: object, ops: list[Operation], detail: str) -> Operation:
    distinct = {op.iri: op for op in ops}
    if len(distinct) != 1:
        found = ", ".join(sorted(str(i) for i in distinct)) or "none"
        raise GeneratorError(subject, predicate, f"{detail}: expected exactly one operation, found {found}")
    return next(iter(distinct.values()))


def _request(op: Operation, actor: object, givens) -> RequestModel:
    method = required(op.method, op.iri, HYDRA.method)
    path = required(op.path, op.iri, COMM.path)
    return RequestModel(
        method=_py(method),
        path=_py(path.template),
        actor=_py(actor),
        data=tuple((_py(local_name(g.field)), _py(_lexical(g.value))) for g in givens),
    )


def _scenario(model: Model, scenario: Scenario) -> ScenarioModel:
    process = scenario.process
    start_op = _submits(
        process.iri,
        SEAM.triggers,
        list(process.triggering_operations),
        f"starting {scenario.iri}",
    )
    steps = []
    for step in scenario.steps:
        task = step.task
        form = required(task.completed_on, task.iri, SEAM.completedOn, f"step of {scenario.iri}")
        ops = [e.submits_to for e in form.events() if e.submits_to is not None]
        op = _submits(form.iri, SEAM.submitsTo, ops, f"completing {task.iri}")
        steps.append(StepModel(_py(task.iri), model.compact(task.iri), _request(op, step.actor, step.givens)))
    state = scenario.expect_state
    shape = None
    if state is not None:
        lifecycle = required(state.lifecycle, state.iri, STATE.hasState)
        shape = required(lifecycle.shape, lifecycle.iri, SEAM.lifecycle).iri
    end = scenario.expect_end_event
    if state is None and end is None:
        raise GeneratorError(scenario.iri, VERIFY.expectState, "a scenario needs an expected state or end event")
    return ScenarioModel(
        name=_name("test_scenario", scenario.iri),
        curie=model.compact(scenario.iri),
        iri=_py(scenario.iri),
        process=_py(process.iri),
        process_curie=model.compact(process.iri),
        key_variable=_py(process.correlation_key or ""),
        key=_py(local_name(scenario.iri)),
        start=_request(start_op, scenario.actor, scenario.givens),
        steps=tuple(steps),
        entity_shape=_py(shape),
        expect_state=_py(None if state is None else state.label),
        expect_state_curie=None if state is None else model.compact(state.iri),
        expect_end_event=None if end is None else _py(end),
        expect_end_event_curie=None if end is None else model.compact(end),
        state_failure=_py(
            None
            if state is None
            else f"{model.compact(scenario.iri)} expects {model.compact(state.iri)}; the entity is "
        ),
        end_event_failure=_py(
            None if end is None else f"{model.compact(scenario.iri)} expects {model.compact(end)}; the run reached "
        ),
    )


def _decision_example(model: Model, example) -> DecisionExampleModel:
    decision = example.decision
    if not example.expected:
        raise GeneratorError(example.iri, VERIFY.expectOutput, "expected at least one, found none")
    return DecisionExampleModel(
        name=_name("test_decision", example.iri),
        curie=model.compact(example.iri),
        decision=_py(decision.iri),
        decision_curie=model.compact(decision.iri),
        inputs=tuple((_py(local_name(g.field)), _py(_lexical(g.value))) for g in example.givens),
        outputs=tuple(
            OutputModel(_py(o.variable), _py(_lexical(o.value)), _py(_datatype(o.value))) for o in example.expected
        ),
    )


def _shape_examples(model: Model, shape: Shape) -> list[ShapeExampleModel]:
    out = []
    for valid, nodes, predicate in (
        (True, shape.valid_examples, VERIFY.validExample),
        (False, shape.invalid_examples, VERIFY.invalidExample),
    ):
        for node in nodes:
            out.append(
                ShapeExampleModel(
                    name=_name("test_valid_example" if valid else "test_invalid_example", shape.iri, node),
                    shape=_py(shape.iri),
                    shape_curie=model.compact(shape.iri),
                    node=_py(node),
                    node_curie=model.compact(node),
                    valid=valid,
                    predicate=model.compact(predicate),
                    failure=_py(
                        f"{model.compact(node)} conforms to {model.compact(shape.iri)}, "
                        f"but it is a {model.compact(predicate)}"
                    ),
                )
            )
    return out


def _unique(names: list[str], subject: object, predicate: object) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise GeneratorError(subject, predicate, f"two tests would be named {name}; rename one IRI")
        seen.add(name)


def extract_tests(model: Model) -> TestsModel:
    """The tests model of ``model``: its scenarios, decision examples and shape examples."""
    with view_errors():
        scenarios = tuple(_scenario(model, s) for s in model.scenarios)
        examples = tuple(_decision_example(model, e) for e in model.decision_examples)
        shapes = tuple(x for shape in model.shapes for x in _shape_examples(model, shape))
    _unique([s.name for s in scenarios], model.subject, VERIFY.Scenario)
    _unique([e.name for e in examples], model.subject, VERIFY.DecisionExample)
    _unique([x.name for x in shapes], model.subject, VERIFY.validExample)
    routes = None
    if scenarios:
        routes = _py(route_module(model.path)[0])
    return TestsModel(
        model_stem=model.path.stem,
        model_hash=model.hash,
        routes=routes,
        scenarios=scenarios,
        decision_examples=examples,
        shape_examples=shapes,
    )


# ── rendering ───────────────────────────────────────────────────────────────


def render_tests(tests: TestsModel) -> dict[str, str]:
    """{file name: text} of the three test files."""
    env = _environment()
    return {name: env.get_template(template).render(t=tests) for name, template in sorted(FILES.items())}


def generate_tests(trig_path) -> dict[str, str]:
    """{file name: text}: test_scenarios.py, test_decisions.py and test_shape_examples.py."""
    return render_tests(extract_tests(load(trig_path)))


def tests_sources(trig_path) -> dict[str, tuple[str, ...]]:
    """{file name: full IRIs}: each file's scenarios, decision examples or example shapes and nodes."""
    model = load(trig_path)
    tests = extract_tests(model)  # the generator's own checks
    with view_errors():
        scenario_iris = {str(s.iri) for s in model.scenarios}
        for s in model.scenarios:
            scenario_iris.add(str(s.process.iri))
            scenario_iris.update(str(step.task.iri) for step in s.steps)
        decision_iris = {str(e.iri) for e in model.decision_examples}
        decision_iris.update(str(e.decision.iri) for e in model.decision_examples)
        shape_iris = {json.loads(x.shape) for x in tests.shape_examples}
        shape_iris.update(json.loads(x.node) for x in tests.shape_examples)
    return {
        "test_decisions.py": tuple(sorted(decision_iris)),
        "test_scenarios.py": tuple(sorted(scenario_iris)),
        "test_shape_examples.py": tuple(sorted(shape_iris)),
    }


__all__ = ["FILES", "TestsModel", "extract_tests", "generate_tests", "render_tests", "tests_sources"]
