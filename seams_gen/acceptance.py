"""The acceptance generator: pytest files that check hand-written handlers against the model (backlog C2).

``extract_acceptance`` reads, through ``seams_gen.stubs.extract_stubs``, every
``comm:PythonHandler`` function the stub generator writes, grouped into the
same modules of the handlers package, and ``render_acceptance`` renders one
pytest file per module through templates/acceptance.py.j2:
``test_<module>.py``, the module path with ``/`` as ``_`` (``notify.py``
gives ``test_notify.py``). Each function gets a ``Handler`` value
(``seams_runtime.verify.Handler``) holding its ``comm:handler`` path, its
implementation and, per operation it implements (by IRI), the
(field, required) pairs of the shape it accepts and returns, read from the
stub's TypedDicts; then these tests, each calling one check of
``seams_runtime.verify`` and asserting what it returns:

- ``test_types_<fn>`` (``handler_types``): the function takes one entity
  parameter, annotated ``dict`` or a TypedDict with the accepted shape's keys
  and required-ness, and returns ``dict``, such a TypedDict of the returned
  shape, or ``None`` for an operation with no ``seam:returnsShape``.
- ``test_shape_<fn>_<example>`` (``handler_result``), per
  ``verify:validExample`` of each operation's ``seam:acceptsShape``: called
  with the example, it returns what the runtime's validator accepts for the
  ``seam:returnsShape``, or raises an ``OperationError`` whose code is one of
  the operation's ``hydra:possibleStatus``.
- ``test_transition_<fn>_<task>`` (``transition_guard``), per
  ``proc:ServiceTask`` that ``seam:invokes`` an operation and ``seam:fires``
  a transition: the lifecycle guard lets the task run in the transition's
  ``state:from`` and moves the entity to its ``state:to``, and refuses it in
  every other state. A task that fires none gets no transition test; its
  decision tests check that its run fires nothing.
- ``test_decision_<fn>_<example>`` (``decision_route``), per
  ``verify:DecisionExample`` of each decision ``seams.context_for`` lists
  for such a task: the task's process runs in-process with the handlers
  package, started with the triggering operation's first valid example and
  the example's givens, and the task is reached exactly when the example's
  expected outputs take a gateway flow into it. A process no operation
  starts (a channel-started one) gets the test skipped with the
  ``ResolutionError``'s message.

A function with several invoking tasks has the task's local name after the
function's in its transition and decision test names. Every value is a
Python literal prepared here (principle 1, templates hold text); modules are
sorted by path, functions by name, operations, examples and tasks by IRI
(principle 6). Each file starts with the generator header and the model
hash, and ``load_model`` refuses a model with another hash.
``trace_acceptance`` traces each file (ADR-0019): a test's lines cite the
fact it derives from (the implementation, the example, the transition or the
decision example) and what it reads (operations, shapes, states, the task,
the decision and the gateway flows). The one generator-only fault (the
README lists it): two handler modules whose paths give one file name, or two
tests one name.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from rdflib import URIRef
from seams import COMM, ModelGraph, ResolutionError, context_for, local_name

from . import GeneratorError
from ._views import view_errors
from .htmx import _environment, _tracing_environment
from .stubs import StubClass, StubFunction, extract_stubs
from .tests import NOT_IDENTIFIER, _py
from .trace import Trace, trace_template

TEMPLATE = "acceptance.py.j2"
GENERATOR = "acceptance"
NOT_REQUIRED = "NotRequired["


# ── the acceptance model ────────────────────────────────────────────────────


@dataclass(frozen=True)
class AcceptanceHandler:
    """One function's ``Handler`` constant; the fields after ``comment`` are Python literals."""

    iri: str  # the first implementation IRI
    origins: tuple[str, ...]  # the other implementations, the operations and their shapes, sorted
    constant: str
    comment: tuple[str, ...]  # the comment lines above it, without "# "
    handler: str
    implementation: str
    accepts: str
    returns: str


@dataclass(frozen=True)
class AcceptanceTest:
    """One test: ``call`` is the verify check it asserts, as Python text."""

    iri: str  # the fact it derives from
    origins: tuple[str, ...]  # what else it reads, sorted
    name: str
    comment: tuple[str, ...]
    params: str  # the test function's parameters
    call: str
    skip: str  # a Python string literal, "" when the test runs


@dataclass(frozen=True)
class AcceptanceModule:
    file: str  # test_<module>.py
    path: str  # the handlers module, relative to the package
    imports: str  # the seams_runtime.verify names it uses, sorted
    handlers: tuple[AcceptanceHandler, ...]  # by function name
    tests: tuple[AcceptanceTest, ...]  # per function: types, shapes, transitions, decisions

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({i for v in (*self.handlers, *self.tests) for i in (v.iri, *v.origins)}))


@dataclass(frozen=True)
class AcceptanceModel:
    model_stem: str
    model_hash: str
    modules: tuple[AcceptanceModule, ...]  # by file name
    generator: str = GENERATOR


# ── extraction ──────────────────────────────────────────────────────────────


def _identifier(iri: object) -> str:
    return NOT_IDENTIFIER.sub("_", local_name(iri))


def _tuple(items: list[str]) -> str:
    """A tuple literal of already-rendered items."""
    if not items:
        return "()"
    if len(items) == 1:
        return f"({items[0]},)"
    return f"({', '.join(items)})"


def _fields(cls: StubClass | None) -> str:
    """The (field, required) pairs of a stub TypedDict, by name, as a literal; None without one."""
    if cls is None:
        return "None"
    pairs = sorted((f.name, not f.annotation.startswith(NOT_REQUIRED)) for f in cls.fields)
    return _tuple([f"({_py(name)}, {required})" for name, required in pairs])


def _operations(model: ModelGraph, fn: StubFunction) -> list:
    """The operations ``fn`` implements, by IRI."""
    ops = []
    for op in sorted(model.operations, key=lambda o: str(o.iri)):
        impl = model.operation_implementation(op.iri)
        if impl is not None and str(impl.iri) in fn.implementations:
            ops.append(op)
    return ops


def _handler(model: ModelGraph, fn: StubFunction, ops: list, classes: dict[str, StubClass]) -> AcceptanceHandler:
    curie = model.compact
    accepts = [None if op.accepts is None else classes[str(op.accepts.iri)] for op in ops]
    returns = [None if op.returns is None else classes[str(op.returns.iri)] for op in ops]
    comment = [f'{curie(URIRef(fn.iri))} {curie(COMM.handler)} "{fn.handler}"']
    for op in ops:
        shown = [curie(s.iri) if s is not None else "none" for s in (op.accepts, op.returns)]
        comment.append(f"  {curie(op.iri)}: accepts {shown[0]}, returns {shown[1]}")
    return AcceptanceHandler(
        iri=fn.iri,
        origins=fn.origins,
        constant=fn.name.upper(),
        comment=tuple(comment),
        handler=_py(fn.handler),
        implementation=_py(fn.iri),
        accepts=_tuple([_fields(c) for c in accepts]),
        returns=_tuple([_fields(c) for c in returns]),
    )


def _types_test(model: ModelGraph, fn: StubFunction, constant: str) -> AcceptanceTest:
    curie = model.compact
    return AcceptanceTest(
        iri=fn.iri,
        origins=fn.origins,
        name=f"test_types_{fn.name}",
        comment=(
            f"{curie(URIRef(fn.iri))} ({curie(COMM.PythonHandler)}): {fn.name} takes one entity, typed and returning",
            "  as the stub does: dict or the TypedDict of seam:acceptsShape and seam:returnsShape",
        ),
        params="model",
        call=f"handler_types(model, {constant})",
        skip="",
    )


def _shape_tests(model: ModelGraph, fn: StubFunction, ops: list, constant: str) -> list[AcceptanceTest]:
    curie = model.compact
    tests = []
    for op in ops:
        accepts, returns = op.accepts, op.returns
        if accepts is None:
            continue
        errors = sorted(op.errors, key=lambda s: str(s.iri))
        statuses = ", ".join(curie(s.iri) for s in errors) or "none"
        shown = curie(returns.iri) if returns is not None else "None (no seam:returnsShape)"
        for node in sorted(accepts.valid_examples, key=str):
            read = {str(op.iri), str(accepts.iri), fn.iri, *(str(s.iri) for s in errors)}
            read.update(str(s.returns.iri) for s in errors if s.returns is not None)
            if returns is not None:
                read.add(str(returns.iri))
            tests.append(
                AcceptanceTest(
                    iri=str(node),
                    origins=tuple(sorted(read - {str(node)})),
                    name=f"test_shape_{fn.name}_{_identifier(node)}",
                    comment=(
                        f"{curie(node)} (verify:validExample of {curie(accepts.iri)}) through {curie(op.iri)}:",
                        f"  returns {shown}, or raises one of hydra:possibleStatus ({statuses})",
                    ),
                    params="model",
                    call=f"handler_result(model, {constant}, {_py(op.iri)}, {_py(node)})",
                    skip="",
                )
            )
    return tests


def _invokers(model: ModelGraph, fn: StubFunction) -> list:
    """The service task elements that seam:invoke ``fn``'s operations, by IRI."""
    return [model.task_element(URIRef(task)) for task in fn.tasks]


def _transition_test(model: ModelGraph, fn: StubFunction, element, suffix: str) -> AcceptanceTest | None:
    transition = element.fires
    if transition is None:
        return None
    curie = model.compact
    source, target = transition.from_state.iri, transition.to_state.iri
    read = {str(element.iri), str(source), str(target), fn.iri}
    return AcceptanceTest(
        iri=str(transition.iri),
        origins=tuple(sorted(read)),
        name=f"test_transition_{fn.name}{suffix}",
        comment=(
            f"{curie(element.iri)} seam:fires {curie(transition.iri)}: {curie(source)} -> {curie(target)};",
            "  the lifecycle guard refuses the task in every other state",
        ),
        params="model",
        call=f"transition_guard(model, {_py(element.iri)}, {_py(transition.iri)})",
        skip="",
    )


def _decision_tests(model: ModelGraph, fn: StubFunction, element, suffix: str) -> list[AcceptanceTest]:
    curie = model.compact
    manifest = context_for(model, element.iri)
    decisions = sorted(item.ref for item in manifest.items if item.kind == "decision")
    process = element.process
    skip = ""
    try:
        model.triggering_operation(process.iri)
    except ResolutionError as err:
        skip = _py(f"{curie(process.iri)} is started by no operation, so no example can start it: {err}")
    process_node = next(fn_ for fn_ in process.nodes() if fn_.iri == element.iri)
    gateways = {n.bpmn_id for n in process.nodes() if n.node.is_gateway}
    flows = sorted(str(process.element_iri(f.id)) for f in process_node.incoming if f.source in gateways)
    fired = [] if element.fires is None else [str(element.fires.iri)]
    tests = []
    for example in sorted(model.decision_examples, key=lambda e: str(e.iri)):
        decision = str(example.decision.iri)
        if decision not in decisions:
            continue
        read = {decision, str(element.iri), str(process.iri), fn.iri, *flows, *fired}
        tests.append(
            AcceptanceTest(
                iri=str(example.iri),
                origins=tuple(sorted(read)),
                name=f"test_decision_{fn.name}{suffix}_{_identifier(example.iri)}",
                comment=(
                    f"{curie(example.iri)} (verify:DecisionExample of {curie(URIRef(decision))}) on {curie(process.iri)}:",
                    f"  {curie(element.iri)} is reached exactly when the expected outputs take a gateway flow into it",
                ),
                params="model, tmp_path",
                call=f'decision_route(model, {_py(element.iri)}, {_py(example.iri)}, tmp_path / "seams.sqlite")',
                skip=skip,
            )
        )
    return tests


def _unique(names: list[str], subject: str, what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise GeneratorError(URIRef(subject), COMM.handler, f"two {what} would be named {name}; rename one")
        seen.add(name)


def _file(path: str) -> str:
    """``test_<module>.py`` for the handlers module at ``path``."""
    return "test_" + path.removesuffix(".py").replace("/", "_") + ".py"


def extract_acceptance(model: ModelGraph) -> AcceptanceModel:
    """One acceptance module per handlers module that defines functions.

    Every fault ``extract_stubs`` or ``context_for`` raises is raised here
    too, naming the subject and predicate."""
    stubs = extract_stubs(model)
    modules = []
    with view_errors():
        for module in stubs.modules:
            if not module.functions:
                continue
            classes = {c.iri: c for c in module.classes}
            handlers, tests = [], []
            for fn in module.functions:
                ops = _operations(model, fn)
                handler = _handler(model, fn, ops, classes)
                handlers.append(handler)
                tests.append(_types_test(model, fn, handler.constant))
                tests += _shape_tests(model, fn, ops, handler.constant)
                invokers = _invokers(model, fn)
                for element in invokers:
                    suffix = f"_{_identifier(element.iri)}" if len(invokers) > 1 else ""
                    transition = _transition_test(model, fn, element, suffix)
                    tests += [transition] if transition is not None else []
                    tests += _decision_tests(model, fn, element, suffix)
            _unique([t.name for t in tests], module.functions[0].iri, f"tests of {_file(module.path)}")
            used = {"load_model", "Handler", *(t.call.split("(")[0] for t in tests)}
            imports = ", ".join(sorted(used, key=lambda n: (not n.isupper(), not n[:1].isupper(), n)))
            modules.append(AcceptanceModule(_file(module.path), module.path, imports, tuple(handlers), tuple(tests)))
    _unique([m.file for m in modules], next((m.handlers[0].iri for m in modules), ""), "acceptance files")
    return AcceptanceModel(stubs.model_stem, stubs.model_hash, tuple(sorted(modules, key=lambda m: m.file)))


# ── rendering ───────────────────────────────────────────────────────────────


def render_acceptance(acceptance: AcceptanceModel) -> dict[str, str]:
    """{test_<module>.py: text} for each module."""
    template = _environment().get_template(TEMPLATE)
    return {m.file: template.render(t=acceptance, m=m) for m in acceptance.modules}


def trace_acceptance(acceptance: AcceptanceModel) -> dict[str, Trace]:
    """{test_<module>.py: Trace}: each test's lines cite its fact and what it
    reads; the fixed lines take every IRI of the module."""
    files = render_acceptance(acceptance)
    return {
        m.file: trace_template(
            _tracing_environment(),
            TEMPLATE,
            {"t": acceptance, "m": m},
            output=m.file,
            generator=GENERATOR,
            expected=files[m.file],
            fallback=list(m.sources),
        )
        for m in acceptance.modules
    }


def generate_acceptance(trig_path) -> dict[str, str]:
    """{test_<module>.py: text} for the model at ``trig_path``."""
    return render_acceptance(extract_acceptance(ModelGraph.load(trig_path)))


def acceptance_sources(trig_path) -> dict[str, tuple[str, ...]]:
    """{test_<module>.py: full IRIs}: each function's implementations,
    operations and shapes, the examples, transitions, states, tasks,
    decisions and gateway flows its tests read."""
    acceptance = extract_acceptance(ModelGraph.load(trig_path))
    return {m.file: m.sources for m in acceptance.modules}


def main(argv: list[str] | None = None) -> int:
    """``python -m seams_gen.acceptance <trig> --out <dir>``, as ``python -m seams_gen acceptance``."""
    from .__main__ import main as gen_main

    return gen_main(["acceptance", *(sys.argv[1:] if argv is None else argv)])


__all__ = [
    "AcceptanceHandler",
    "AcceptanceModel",
    "AcceptanceModule",
    "AcceptanceTest",
    "acceptance_sources",
    "extract_acceptance",
    "generate_acceptance",
    "render_acceptance",
    "trace_acceptance",
]

if __name__ == "__main__":
    sys.exit(main())
