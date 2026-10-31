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
- ``render_module`` renders one module through templates/handler_stub.py.j2:
  the generated-once header with the model hash, then per function the
  signature ``def <fn>(entity: dict) -> dict`` (``-> None`` when no operation
  it implements has a ``seam:returnsShape``), a docstring naming the
  implementation, the operations and their accepted and returned shapes, and
  a body that raises ``NotImplementedError``.
- ``plan_stubs`` compares with the handlers directory: an absent file is
  written; an existing module that does not bind a function the model names
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
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from seams import COMM, SEAM, ModelGraph

from . import GeneratorError
from ._views import view_errors
from .htmx import _environment

TEMPLATE_NAME = "handler_stub.py.j2"
DEFAULT_HANDLERS = "handlers"
INIT = "__init__.py"

EXIT_OK = 0
EXIT_IO_ERROR = 1
EXIT_ERROR = 2
_PROG = "python -m seams_gen.stubs"


# ── the stubs model ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StubFunction:
    name: str
    handler: str  # the comm:handler dotted path
    implementations: tuple[str, ...]  # full IRIs, sorted
    returns: str  # the return annotation: "dict", "None" or "dict | None"
    summary: str  # the docstring's first line
    doc: tuple[str, ...]  # the docstring's other lines, indented ("" for a blank line)
    error_text: str  # the NotImplementedError argument, as a Python string literal


@dataclass(frozen=True)
class StubModule:
    path: str  # relative to the handlers package, POSIX separators
    header: tuple[str, ...]
    functions: tuple[StubFunction, ...]  # sorted by name; () for a bare package __init__.py


@dataclass(frozen=True)
class StubsModel:
    model_stem: str
    model_hash: str
    modules: tuple[StubModule, ...]  # sorted by path


@dataclass(frozen=True)
class StubPlan:
    writes: tuple[tuple[Path, str], ...]  # (absent file, text), sorted by path
    reports: tuple[str, ...]  # one line per function an existing module lacks


# ── extraction ──────────────────────────────────────────────────────────────


def _module_file(module: str, packages: set[str]) -> str:
    """The file of dotted ``module`` ("" is the package itself)."""
    if module == "":
        return INIT
    if module in packages:
        return "/".join(module.split(".")) + "/" + INIT
    return "/".join(module.split(".")) + ".py"


def _function(model: ModelGraph, name: str, handler: str, served: list) -> StubFunction:
    """One stub function for the (implementation IRI, operation) pairs that name ``handler``."""
    impls = sorted({str(impl) for impl, _ in served})
    doc: list[str] = []
    returned: list[bool] = []
    for impl, op in sorted(served, key=lambda pair: (str(pair[1].iri), str(pair[0]))):
        accepts, returns = op.accepts, op.returns
        returned.append(returns is not None)
        doc += [
            "",
            f"    Implements {model.compact(op.iri)} ({model.compact(SEAM.implementedBy)} {model.compact(impl)}).",
            f"    entity: the current {model.compact(accepts.iri)} entity ({model.compact(SEAM.acceptsShape)})."
            if accepts is not None
            else f"    entity: the operation states no {model.compact(SEAM.acceptsShape)}.",
            f"    Returns: a {model.compact(returns.iri)} entity ({model.compact(SEAM.returnsShape)})."
            if returns is not None
            else f"    Returns: None; the operation states no {model.compact(SEAM.returnsShape)}.",
        ]
    returns_type = "dict" if all(returned) else "None" if not any(returned) else "dict | None"
    named = ", ".join(model.compact(i) for i in impls)
    operations = ", ".join(sorted({model.compact(op.iri) for _, op in served}))
    return StubFunction(
        name=name,
        handler=handler,
        implementations=tuple(impls),
        returns=returns_type,
        summary=f'{model.compact(COMM.handler)} "{handler}" of {named} ({model.compact(COMM.PythonHandler)}).',
        doc=tuple(doc),
        error_text=json.dumps(f"{handler}: write the handler for {operations}"),
    )


def extract_stubs(model: ModelGraph) -> StubsModel:
    """Every module of the handlers package the model's comm:PythonHandlers name.

    A missing or ambiguous implementation fact (several seam:implementedBy, a
    bad kind, a missing or non-identifier comm:handler) raises
    ``GeneratorError`` naming the subject and predicate the library named."""
    by_function: dict[tuple[str, str], list] = {}
    with view_errors():
        model_hash = model.hash
        for op in sorted(model.operations, key=lambda o: str(o.iri)):
            impl = model.operation_implementation(op.iri)
            if impl is None or impl.kind != COMM.PythonHandler or impl.handler is None:
                continue
            module, _, name = impl.handler.rpartition(".")
            by_function.setdefault((module, name), []).append((impl.iri, op))

    packages = {""}
    for module, _ in by_function:
        parts = module.split(".") if module else []
        packages.update(".".join(parts[:i]) for i in range(1, len(parts)))
    files: dict[str, list[StubFunction]] = {_module_file(p, packages): [] for p in packages}
    with view_errors():
        for (module, name), served in sorted(by_function.items()):
            handler = f"{module}.{name}" if module else name
            files.setdefault(_module_file(module, packages), []).append(_function(model, name, handler, served))

    stem = model.path.stem
    header = (
        f"# Generated once by the seams handler stub generator from the {stem} model.",
        "# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).",
        f"# model-hash: {model_hash}",
    )
    modules = tuple(
        StubModule(path, header, tuple(sorted(fns, key=lambda f: f.name))) for path, fns in sorted(files.items())
    )
    if not by_function:
        modules = ()
    return StubsModel(stem, model_hash, modules)


# ── rendering ───────────────────────────────────────────────────────────────


def render_module(module: StubModule) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(module=module)


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
    """The absent files to write under ``handlers`` and the reports for existing
    modules that lack a function. Existing files are read, never written."""
    writes: list[tuple[Path, str]] = []
    reports: list[str] = []
    for module in stubs.modules:
        path = Path(handlers) / module.path
        if not path.exists():
            writes.append((path, render_module(module)))
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
