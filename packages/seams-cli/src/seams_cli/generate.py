"""``seams generate``: run every generator of a project, then write the results.

All generators run in memory first; a GeneratorError from any of them leaves
every output untouched, so a project is never half-regenerated. Files are
written as ``python -m seams_gen`` writes them: UTF-8 with ``\\n`` newlines.

``apply`` then reconciles the project with its seams.lock (D043): it reads the
old lock before writing anything (a malformed one raises LockError), writes the
outputs, deletes each orphan the old lock still knows byte for byte, and writes
the new lock last. An orphan that is a symlink, not a regular file, or no longer
matches its locked sha256 is kept, so a lockfile can only delete content it
already holds the hash of.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .lockfile import Audit, Output, audit, build_lock, locate, lock_path, read_lock, render_lock, sha256_file
from .project import Project


def generate_project(project: Project, model: Path) -> dict[Path, Output]:
    """{absolute output path: Output} for every generator target of ``project``."""
    from seams_gen.__main__ import GENERATORS
    from seams_gen.sources import output_sources

    files: dict[Path, Output] = {}
    for target in project.generators:
        generate = GENERATORS[target.name][1]
        sources = output_sources(target.name, model, target.out)
        for name, text in generate(model, target.out).items():
            files[(target.out / name).resolve()] = Output(target.name, text, sources[name])
    return files


def write_outputs(files: dict[Path, Output]) -> None:
    for path, out in sorted(files.items()):
        _write(path, out.text)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@dataclass(frozen=True)
class Applied:
    """What ``apply`` did. ``removed`` and ``kept`` are absolute orphan paths;
    ``audit`` is the comparison made before writing; ``lock`` the lockfile written."""

    audit: Audit
    removed: tuple[Path, ...]
    kept: tuple[Path, ...]
    lock: Path


def apply(project: Project, model: Path, files: dict[Path, Output]) -> Applied:
    """Write ``files``, delete unchanged orphans of the old lock, then write the new lock."""
    old = read_lock(project)
    report = audit(project, old, {path: out.text for path, out in files.items()})
    lock = build_lock(project, model, files)
    write_outputs(files)
    locked = {entry.path: entry.sha256 for entry in old.outputs} if old else {}
    removed, kept = [], []
    for rel in report.orphans:
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
