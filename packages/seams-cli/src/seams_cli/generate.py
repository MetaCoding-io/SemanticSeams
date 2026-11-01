"""``seams generate``: run every generator of a project, then write the results.

All generators run in memory first; a GeneratorError from any of them leaves
every output untouched, so a project is never half-regenerated. Files are
written as ``python -m seams_gen`` writes them: UTF-8 with ``\\n`` newlines.

Generators come from the ``seams.generators`` registry (D056). Before any
runs, a generator that declares precondition shapes has them checked: the model,
unioned with ``ontology/*.ttl``, is validated against ontology/shapes once, and
a result of one of its shapes raises GeneratorError naming the generator, the
shape and the focus node (strict mode, M018/S01).

With ``lenient=True`` (D057) nothing raises. Every precondition result becomes
a ``Fault`` and its generator still runs; a generator that raises
GeneratorError contributes no files and one ``Fault``. ``generate_project``
returns the files and the sorted faults as ``Generated``, and ``apply`` records
the faults in seams.lock, which flags it.

``apply`` then reconciles the project with its seams.lock (D043): it reads the
old lock before writing anything (a malformed one raises LockError), writes the
outputs, deletes each orphan the old lock still knows byte for byte, and writes
the new lock last. An orphan that is a symlink, not a regular file, or no longer
matches its locked sha256 is kept, so a lockfile can only delete content it
already holds the hash of. An orphan whose generator faulted this run is not
deleted either: its locked entry is carried into the new lock unchanged, so the
file stays tracked until that generator runs cleanly again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import Graph

from seams_gen import GeneratorError

from .lockfile import (
    Audit,
    Fault,
    Lock,
    Output,
    audit,
    build_lock,
    locate,
    lock_path,
    read_lock,
    render_lock,
    sha256_file,
)
from .project import Project


@dataclass(frozen=True)
class Generated:
    """What ``generate_project`` produced: {absolute output path: Output}, and
    the faults lenient mode collected, sorted (always empty in strict mode)."""

    files: dict[Path, Output]
    faults: tuple[Fault, ...] = ()


def _fault(generator: str, err: GeneratorError) -> Fault:
    return Fault(generator, err.predicate, err.subject, err.detail)


def generate_project(project: Project, model: Path, *, lenient: bool = False) -> Generated:
    """Every generator target of ``project`` run on ``model``. Strict mode raises
    the first GeneratorError; ``lenient`` collects them as faults."""
    from seams_gen.registry import discover

    registry = discover()
    generators = [(registry[target.name], target.out) for target in project.generators]
    faults: list[Fault] = []
    if any(gen.preconditions for gen, _out in generators):
        from .check import SHAPES_FILE

        shapes = Graph().parse(SHAPES_FILE, format="turtle")
        results = shape_results(model, shapes)
        for gen, _out in generators:
            if lenient:
                faults += (_fault(gen.name, err) for err in gen.precondition_faults(results, shapes))
            else:
                gen.check_preconditions(results, shapes)
    files: dict[Path, Output] = {}
    for gen, out in generators:
        try:
            sources = gen.sources(model, out)
            produced = gen.generate(model, out)
        except GeneratorError as err:
            if not lenient:
                raise
            faults.append(_fault(gen.name, err))
            continue
        for name, text in produced.items():
            files[(out / name).resolve()] = Output(gen.name, gen.version, text, sources[name])
    return Generated(files, tuple(sorted(faults)))


def shape_results(model: Path, shapes: Graph) -> Graph:
    """The SHACL validation report graph of ``model`` against ``shapes``, validated as ``seams check`` does."""
    import pyshacl

    from .check import model_graph

    _conforms, results, _text = pyshacl.validate(model_graph(model), shacl_graph=shapes, inference="none")
    return results


def write_outputs(files: dict[Path, Output]) -> None:
    for path, out in sorted(files.items()):
        _write(path, out.text)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def next_lock(project: Project, model: Path, generated: Generated, old: Lock | None, report: Audit) -> Lock:
    """The lock ``apply`` writes: the generated outputs and faults, plus the old
    entry of every orphan whose generator faulted this run."""
    lock = build_lock(project, model, generated.files, generated.faults)
    faulted = {fault.generator for fault in generated.faults}
    entries = {entry.path: entry for entry in old.outputs} if old else {}
    carried = [entries[rel] for rel in report.orphans if entries[rel].generator in faulted]
    if carried:
        lock = replace(lock, outputs=tuple(sorted((*lock.outputs, *carried), key=lambda o: o.path)))
    return lock


@dataclass(frozen=True)
class Applied:
    """What ``apply`` did. ``removed`` and ``kept`` are absolute orphan paths;
    ``audit`` is the comparison made before writing; ``lock`` the lockfile written."""

    audit: Audit
    removed: tuple[Path, ...]
    kept: tuple[Path, ...]
    lock: Path


def apply(project: Project, model: Path, generated: Generated) -> Applied:
    """Write the generated files, delete unchanged orphans of the old lock, then
    write the new lock with the faults. Orphans of a faulted generator are carried."""
    files = generated.files
    old = read_lock(project)
    report = audit(project, old, {path: out.text for path, out in files.items()})
    lock = next_lock(project, model, generated, old, report)
    write_outputs(files)
    entries = {entry.path: entry for entry in old.outputs} if old else {}
    faulted = {fault.generator for fault in generated.faults}
    locked = {rel: entry.sha256 for rel, entry in entries.items()}
    removed, kept = [], []
    for rel in report.orphans:
        if entries[rel].generator in faulted:
            continue
        path = locate(project, rel)
        if not path.exists() and not path.is_symlink():
            continue
        if not path.is_symlink() and path.is_file() and sha256_file(path) == locked[rel]:
            path.unlink()
            removed.append(path)
        else:
            kept.append(path)
    target = lock_path(project)
    _write(target, render_lock(lock))
    return Applied(report, tuple(removed), tuple(kept), target)
