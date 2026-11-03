"""The write-once handler stub generator (ADR-0012 regeneration rule, D050).

``python -m seams_gen.stubs <trig> [--handlers DIR]`` writes a stub module for
each ``comm:PythonHandler`` whose module is absent from the handlers package
(default ``handlers/`` beside the model file, the runtime's default). From then
on the file is owned code (principle 8): this generator never opens an
existing file for writing, and it is not a ``GENERATORS`` entry, so neither
``seams generate`` nor ``seams.lock`` knows about it.

- ``extract_stubs`` reads, through the seams library, every operation's
  ``seam:implementedBy`` (``ModelGraph.operation_implementation``), keeps the
  ``comm:PythonHandler``s and groups their ``comm:handler`` dotted paths into
  modules of the package: ``"notify.notify_manager"`` is the function
  ``notify_manager`` in ``notify.py``. Every package on the way gets an
  ``__init__.py``; a module that is also a package prefix is that package's
  ``__init__.py``, and a one-segment path names a function of the package's
  own ``__init__.py`` (as the runtime imports them).
- Each ``seam:acceptsShape`` and ``seam:returnsShape`` a module's functions
  use becomes a ``TypedDict`` named after the shape's local name, with one
  key per ``sh:property`` (``Shape.fields()`` order): the ``sh:path`` local
  name, typed by ``PYTHON_TYPES`` from its ``sh:datatype``. A field without
  a datatype (``sh:class``, ``sh:node``) holds an IRI, a ``str``. A field
  without a positive ``sh:minCount`` is ``NotRequired``. A datatype outside
  the table raises ``GeneratorError(shape, sh:datatype)``.
- For each operation, the ``proc:ServiceTask``s that ``seam:invokes`` it are
  passed to ``seams.context_for``: the docstring names each task, the
  decisions its manifest lists, and the transition it fires with its from
  and to states. The module header records ``# context-hash:``: the task's
  ``Manifest.context_hash`` when one task invokes the module's operations,
  ``sha256:`` over their sorted hashes (each followed by a newline) when
  several do, and no line when none does.
- ``render_module`` renders one module through templates/handler_stub.py.j2:
  the generated-once header with the model and context hashes, the typing
  import and the classes, then per function the signature
  ``def <fn>(entity: <Accepts>) -> <Returns>`` (``dict`` for an operation
  with no ``seam:acceptsShape``, ``None`` for one with no
  ``seam:returnsShape``, unions when the operations differ), a docstring
  naming the implementation, the operations, their shapes, tasks, decisions
  and transitions, and a body that raises ``NotImplementedError``.
- ``trace_module`` renders the module a second time with
  ``seams_gen.trace.trace_template`` (ADR-0019): each field cites its
  ``sh:path``, its shape and the operations of the module that use the shape;
  each class line its shape and those operations; the signature, summary and
  body the implementations, operations and shapes; each docstring line the
  operation, shape, task, decision or transition it names (the task with its
  process and operation, the decision with its task, the transition with its
  task and states). The header lines take every IRI of the module's functions.
- ``plan_stubs`` compares with the handlers directory: an absent file is
  written, with its ``<module>.trace.json`` sidecar (``render_trace_json``)
  beside it; a package ``__init__.py`` with no functions gets one too. The
  sidecar is write-once like its module: it is written only when the module
  is, with mode ``x``, and it is not in ``seams.lock`` (M022/S05 owns lock
  entries). An existing module that does not bind a function the model names
  is reported (subject the implementation IRI, predicate ``comm:handler``),
  never patched. Existing files are only read, and parsed with ``ast``, never
  imported.

Exit codes: 0 when the run succeeds, reports included (they are printed on
stderr, each written path on stdout); 2 for a ``GeneratorError`` or a model
that cannot be parsed; 1 for a file that cannot be read or written. Nothing
is written unless extraction and planning both succeed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import keyword
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import RDF, XSD, URIRef
from rdflib.namespace import SH
from seams import COMM, PROC, SEAM, ModelGraph, context_for, local_name

from . import GeneratorError
from ._views import view_errors
from .htmx import _environment, _tracing_environment
from .trace import Trace, render_trace_json, trace_template

TEMPLATE_NAME = "handler_stub.py.j2"
GENERATOR = "stubs"
TRACE_SUFFIX = ".trace.json"
DEFAULT_HANDLERS = "handlers"
INIT = "__init__.py"

EXIT_OK = 0
EXIT_IO_ERROR = 1
EXIT_ERROR = 2
_PROG = "python -m seams_gen.stubs"


# ── the stubs model ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StubField:
    name: str  # the sh:path local name
    annotation: str  # the Python type, wrapped in NotRequired when not required
    iri: str  # the sh:path IRI
    origins: tuple[str, ...] = ()  # the shape, then the module's operations that use it (sorted)


@dataclass(frozen=True)
class StubClass:
    name: str  # the shape's local name
    iri: str  # the shape IRI
    summary: str  # the class docstring
    fields: tuple[StubField, ...]  # in the shape's fields() order (sh:order, then path IRI)
    origins: tuple[str, ...] = ()  # the module's operations that use the shape, sorted


@dataclass(frozen=True)
class StubDocLine:
    text: str  # indented; "" for a blank line
    iri: str = ""  # the model element the line names ("" for none)
    origins: tuple[str, ...] = ()  # the further elements the line was read from, sorted


@dataclass(frozen=True)
class StubFunction:
    iri: str  # the first implementation IRI
    origins: tuple[str, ...]  # the other implementations, the operations and their shapes, sorted
    name: str
    handler: str  # the comm:handler dotted path
    implementations: tuple[str, ...]  # full IRIs, sorted
    accepts: str  # the entity annotation: shape classes, "dict" where an operation states none
    returns: str  # the return annotation: shape classes, "None" where an operation states none
    summary: str  # the docstring's first line
    doc: tuple[StubDocLine, ...]  # the docstring's other lines
    error_text: str  # the NotImplementedError argument, as a Python string literal
    tasks: tuple[str, ...] = ()  # the service tasks that seam:invoke its operations, sorted IRIs
    context_hashes: tuple[str, ...] = ()  # context_for(model, task).context_hash, in ``tasks`` order
    shape_operations: tuple[tuple[str, str], ...] = ()  # (shape IRI, operation IRI) it accepts or returns, sorted


@dataclass(frozen=True)
class StubModule:
    path: str  # relative to the handlers package, POSIX separators
    header: tuple[str, ...]
    functions: tuple[StubFunction, ...]  # sorted by name; () for a bare package __init__.py
    classes: tuple[StubClass, ...] = ()  # sorted by name
    typing_import: str = ""  # the names imported from typing, "" when there are no classes


@dataclass(frozen=True)
class StubsModel:
    model_stem: str
    model_hash: str
    modules: tuple[StubModule, ...]  # sorted by path


@dataclass(frozen=True)
class StubPlan:
    writes: tuple[tuple[Path, str], ...]  # (absent file, text): each module, then its trace sidecar
    reports: tuple[str, ...]  # one line per function an existing module lacks


# ── extraction ──────────────────────────────────────────────────────────────

#: The Python type of each mapped sh:datatype. A field without one (sh:class,
#: sh:node) holds an IRI, so it is a str.
PYTHON_TYPES = {
    XSD.string: "str",
    XSD.integer: "int",
    XSD.decimal: "float",
    XSD.double: "float",
    XSD.boolean: "bool",
    XSD.date: "str",
    XSD.dateTime: "str",
}
OBJECT_TYPE = "str"


def _module_file(module: str, packages: set[str]) -> str:
    """The file of dotted ``module`` ("" is the package itself)."""
    if module == "":
        return INIT
    if module in packages:
        return "/".join(module.split(".")) + "/" + INIT
    return "/".join(module.split(".")) + ".py"


def _identifier(name: str, subject, predicate, what: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise GeneratorError(subject, predicate, f"{what} {name!r} is not a Python identifier")
    return name


def _stub_class(model: ModelGraph, shape) -> StubClass:
    """The TypedDict of ``shape``: one field per sh:property, typed from its sh:datatype."""
    name = _identifier(local_name(shape.iri), shape.iri, RDF.type, "the shape's local name")
    fields: list[StubField] = []
    for f in shape.fields():
        if f.datatype is None:
            python = OBJECT_TYPE
        elif f.datatype in PYTHON_TYPES:
            python = PYTHON_TYPES[f.datatype]
        else:
            known = ", ".join(sorted(model.compact(d) for d in PYTHON_TYPES))
            raise GeneratorError(
                shape.iri, SH.datatype, f"{model.compact(f.iri)}: no Python type for {f.datatype} (mapped: {known})"
            )
        if any(seen.name == f.name for seen in fields):
            raise GeneratorError(shape.iri, SH.path, f"two sh:path local names are {f.name!r}")
        _identifier(f.name, shape.iri, SH.path, "the sh:path local name")
        fields.append(StubField(f.name, python if f.required else f"NotRequired[{python}]", str(f.iri)))
    summary = f"{model.compact(shape.iri)} ({model.compact(SH.NodeShape)}): one key per {model.compact(SH.property)}."
    return StubClass(name, str(shape.iri), summary, tuple(fields))


def _annotation(names: list[str | None], fallback: str) -> str:
    """The union of the shape classes in ``names``, ``fallback`` last for a None."""
    classes = sorted({n for n in names if n is not None})
    return " | ".join(classes + ([fallback] if None in names else []))


def _invoking_tasks(model: ModelGraph) -> dict[str, list]:
    """The proc:ServiceTask elements that seam:invoke each operation, by operation IRI."""
    tasks: dict[str, list] = {}
    for process in model.processes:
        for node in process.nodes():
            element, op = node.element, node.invokes
            if element is None or op is None or PROC.ServiceTask not in element.types:
                continue
            tasks.setdefault(str(op.iri), []).append(element)
    return tasks


def _task_doc(model: ModelGraph, element, op_iri: str) -> tuple[list[StubDocLine], str]:
    """The docstring lines naming ``element``, its deciding decisions and fired
    transition (from ``context_for``), and its context hash."""
    manifest = context_for(model, element.iri)
    process = element.process
    of = f", a {model.compact(PROC.ServiceTask)} of {model.compact(process.iri)}" if process is not None else ""
    task = str(element.iri)
    invoked = sorted({op_iri, *((str(process.iri),) if process is not None else ())})
    lines = [
        StubDocLine(
            f"    Invoked by {model.compact(element.iri)} ({model.compact(SEAM.invokes)}){of}.", task, tuple(invoked)
        )
    ]
    for item in manifest.items:
        if item.kind == "decision":
            lines.append(
                StubDocLine(
                    f"    Decided by {model.compact(URIRef(item.ref))} ({model.compact(SEAM.decidedBy)}):"
                    " a gateway before the task routes on its output.",
                    item.ref,
                    (task,),
                )
            )
    transition = element.fires
    for item in manifest.items:
        if item.kind == "transition" and transition is not None and str(transition.iri) == item.ref:
            states = {str(transition.from_state.iri), str(transition.to_state.iri)}
            lines.append(
                StubDocLine(
                    f"    Fires {model.compact(transition.iri)} ({model.compact(SEAM.fires)}):"
                    f" {model.compact(transition.from_state.iri)} -> {model.compact(transition.to_state.iri)}.",
                    item.ref,
                    tuple(sorted(states | {task})),
                )
            )
    return lines, manifest.context_hash


def _function(
    model: ModelGraph, name: str, handler: str, served: list, classes: dict[str, StubClass], tasks: dict[str, list]
) -> StubFunction:
    """One stub function for the (implementation IRI, operation) pairs that name ``handler``."""
    impls = sorted({str(impl) for impl, _ in served})
    doc: list[StubDocLine] = []
    read: set[str] = set(impls)
    uses: set[tuple[str, str]] = set()
    accepted: list[str | None] = []
    returned: list[str | None] = []
    invokers: dict[str, str] = {}
    for impl, op in sorted(served, key=lambda pair: (str(pair[1].iri), str(pair[0]))):
        accepts, returns = op.accepts, op.returns
        for shape, names in ((accepts, accepted), (returns, returned)):
            if shape is not None and str(shape.iri) not in classes:
                classes[str(shape.iri)] = _stub_class(model, shape)
            names.append(None if shape is None else classes[str(shape.iri)].name)
        operation = str(op.iri)
        shapes = [str(shape.iri) for shape in (accepts, returns) if shape is not None]
        read.update([operation, *shapes])
        uses.update((shape, operation) for shape in shapes)
        doc += [
            StubDocLine(""),
            StubDocLine(
                f"    Implements {model.compact(op.iri)} ({model.compact(SEAM.implementedBy)} {model.compact(impl)}).",
                operation,
                (str(impl),),
            ),
            StubDocLine(
                f"    entity: the current {model.compact(accepts.iri)} entity ({model.compact(SEAM.acceptsShape)}).",
                str(accepts.iri),
                (operation,),
            )
            if accepts is not None
            else StubDocLine(f"    entity: the operation states no {model.compact(SEAM.acceptsShape)}.", operation),
            StubDocLine(
                f"    Returns: a {model.compact(returns.iri)} entity ({model.compact(SEAM.returnsShape)}).",
                str(returns.iri),
                (operation,),
            )
            if returns is not None
            else StubDocLine(
                f"    Returns: None; the operation states no {model.compact(SEAM.returnsShape)}.", operation
            ),
        ]
        for element in sorted(tasks.get(operation, []), key=lambda e: str(e.iri)):
            lines, invokers[str(element.iri)] = _task_doc(model, element, operation)
            doc += lines
    named = ", ".join(model.compact(i) for i in impls)
    operations = ", ".join(sorted({model.compact(op.iri) for _, op in served}))
    ordered = sorted(invokers)
    read.discard(impls[0])
    return StubFunction(
        iri=impls[0],
        origins=tuple(sorted(read)),
        name=name,
        handler=handler,
        implementations=tuple(impls),
        accepts=_annotation(accepted, "dict"),
        returns=_annotation(returned, "None"),
        summary=f'{model.compact(COMM.handler)} "{handler}" of {named} ({model.compact(COMM.PythonHandler)}).',
        doc=tuple(doc),
        error_text=json.dumps(f"{handler}: write the handler for {operations}"),
        tasks=tuple(ordered),
        context_hashes=tuple(invokers[t] for t in ordered),
        shape_operations=tuple(sorted(uses)),
    )


def context_hash(functions: tuple[StubFunction, ...]) -> str | None:
    """The context hash a module's header records: None when no service task
    invokes its operations, the task's ``Manifest.context_hash`` when one does,
    and with several, ``sha256:`` over their sorted hashes, each followed by a
    newline."""
    hashes = sorted({h for fn in functions for h in fn.context_hashes})
    if not hashes:
        return None
    if len(hashes) == 1:
        return hashes[0]
    return "sha256:" + hashlib.sha256("".join(f"{h}\n" for h in hashes).encode()).hexdigest()


def _with_operations(cls: StubClass, functions: tuple[StubFunction, ...]) -> StubClass:
    """``cls`` with the operations of ``functions`` that accept or return its shape as origins."""
    ops = tuple(sorted({op for fn in functions for shape, op in fn.shape_operations if shape == cls.iri}))
    fields = tuple(replace(f, origins=(cls.iri, *ops)) for f in cls.fields)
    return replace(cls, fields=fields, origins=ops)


def _module(path: str, header: tuple[str, ...], functions: list[StubFunction], classes: dict[str, StubClass]):
    fns = tuple(sorted(functions, key=lambda f: f.name))
    used = {shape for fn in fns for shape, _ in fn.shape_operations}
    own = sorted((c for c in classes.values() if c.iri in used), key=lambda c: (c.name, c.iri))
    own = [_with_operations(c, fns) for c in own]
    for first, second in itertools.pairwise(own):
        if first.name == second.name:
            shapes = f"{first.iri}, {second.iri}"
            raise GeneratorError(first.iri, RDF.type, f"two shapes of {path} share a local name: {shapes}")
    for c in own:
        if any(fn.name == c.name for fn in fns):
            raise GeneratorError(c.iri, RDF.type, f"the shape's local name is also a function of {path}")
    imports = ["NotRequired"] if any(f.annotation.startswith("NotRequired[") for c in own for f in c.fields) else []
    imports += ["TypedDict"] if own else []
    hashed = context_hash(fns)
    lines = header + ((f"# context-hash: {hashed}",) if hashed is not None else ())
    return StubModule(path, lines, fns, tuple(own), ", ".join(imports))


def extract_stubs(model: ModelGraph) -> StubsModel:
    """Every module of the handlers package the model's comm:PythonHandlers name.

    A missing or ambiguous implementation fact (several seam:implementedBy, a
    bad kind, a missing or non-identifier comm:handler), a shape field whose
    sh:datatype has no Python type, or a context hop ``context_for`` cannot
    make raises ``GeneratorError`` naming the subject and predicate."""
    by_function: dict[tuple[str, str], list] = {}
    with view_errors():
        model_hash = model.hash
        for op in sorted(model.operations, key=lambda o: str(o.iri)):
            impl = model.operation_implementation(op.iri)
            if impl is None or impl.kind != COMM.PythonHandler or impl.handler is None:
                continue
            module, _, name = impl.handler.rpartition(".")
            by_function.setdefault((module, name), []).append((impl.iri, op))
        tasks = _invoking_tasks(model) if by_function else {}

    packages = {""}
    for module, _ in by_function:
        parts = module.split(".") if module else []
        packages.update(".".join(parts[:i]) for i in range(1, len(parts)))
    files: dict[str, list[StubFunction]] = {_module_file(p, packages): [] for p in packages}
    classes: dict[str, StubClass] = {}
    with view_errors():
        for (module, name), served in sorted(by_function.items()):
            handler = f"{module}.{name}" if module else name
            files.setdefault(_module_file(module, packages), []).append(
                _function(model, name, handler, served, classes, tasks)
            )

    stem = model.path.stem
    header = (
        f"# Generated once by the seams handler stub generator from the {stem} model.",
        "# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).",
        f"# model-hash: {model_hash}",
    )
    modules = tuple(_module(path, header, fns, classes) for path, fns in sorted(files.items()))
    if not by_function:
        modules = ()
    return StubsModel(stem, model_hash, modules)


# ── rendering ───────────────────────────────────────────────────────────────


def render_module(module: StubModule) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(module=module)


def trace_module(module: StubModule, expected: str | None = None) -> Trace:
    """The trace of ``render_module(module)`` (``expected``, when already
    rendered). A line no origin-carrying value lands on (the header, the
    typing import) takes every IRI of the module's functions."""
    fallback = {iri for fn in module.functions for iri in (fn.iri, *fn.origins, *fn.tasks)}
    return trace_template(
        _tracing_environment(),
        TEMPLATE_NAME,
        {"module": module},
        output=module.path,
        generator=GENERATOR,
        expected=render_module(module) if expected is None else expected,
        fallback=sorted(fallback),
    )


def trace_path(path: Path) -> Path:
    """The ``<module>.trace.json`` sidecar beside ``path``."""
    return path.with_name(path.name + TRACE_SUFFIX)


# ── planning and writing ────────────────────────────────────────────────────


def _bound_names(text: str) -> set[str]:
    """The names a module binds at top level: defs, classes, assignments and imports."""
    names: set[str] = set()
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
    return names


def _report(fn: StubFunction, detail: str) -> list[str]:
    return [f"{impl}: {COMM.handler}: {detail}" for impl in fn.implementations]


def plan_stubs(stubs: StubsModel, handlers: Path) -> StubPlan:
    """The absent files to write under ``handlers``, each with its trace
    sidecar, and the reports for existing modules that lack a function.
    Existing files are read, never written; an existing module gets no
    sidecar."""
    writes: list[tuple[Path, str]] = []
    reports: list[str] = []
    for module in stubs.modules:
        path = Path(handlers) / module.path
        if not path.exists():
            text = render_module(module)
            writes.append((path, text))
            writes.append((trace_path(path), render_trace_json(trace_module(module, text))))
            continue
        if not module.functions:
            continue
        text = path.read_text(encoding="utf-8")
        try:
            bound = _bound_names(text)
        except SyntaxError as err:
            for fn in module.functions:
                reports += _report(fn, f'"{fn.handler}": {path} does not parse ({err.msg}, line {err.lineno})')
            continue
        for fn in module.functions:
            if fn.name not in bound:
                reports += _report(
                    fn, f'"{fn.handler}": {path} exists but defines no {fn.name}; add it (the file is owned code)'
                )
    return StubPlan(tuple(writes), tuple(reports))


def write_stubs(plan: StubPlan) -> list[Path]:
    """Create each planned file (UTF-8, ``\\n`` newlines). Mode ``x`` refuses a
    file that appeared since planning, so an existing file is never written."""
    written = []
    for path, text in plan.writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(path)
    return written


def generate_stubs(trig, handlers=None) -> StubPlan:
    """The plan for the model ``trig`` and the handlers directory (default ``handlers/`` beside it)."""
    model = ModelGraph.load(trig)
    directory = Path(handlers) if handlers is not None else Path(trig).resolve().parent / DEFAULT_HANDLERS
    return plan_stubs(extract_stubs(model), directory)


# ── command line ────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Write a stub for each comm:PythonHandler whose module is absent. Never overwrites."
    )
    parser.add_argument("trig", type=Path, help="the model's TriG file")
    parser.add_argument(
        "--handlers", type=Path, help=f"the handlers package directory (default: {DEFAULT_HANDLERS}/ beside the model)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.trig.is_file():
            raise FileNotFoundError(f"no such model file: {args.trig}")
        plan = generate_stubs(args.trig, args.handlers)
    except GeneratorError as err:
        print(f"{_PROG}: {err}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as err:
        print(f"{_PROG}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    except Exception as err:  # an rdflib parse error: a model that cannot be read as TriG
        print(f"{_PROG}: {err}", file=sys.stderr)
        return EXIT_ERROR
    try:
        written = write_stubs(plan)
    except OSError as err:
        print(f"{_PROG}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    for path in written:
        print(path)
    for line in plan.reports:
        print(f"{_PROG}: {line}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
