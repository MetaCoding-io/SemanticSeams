"""``seams generate``: run every generator of a project, then write the results.

All generators run in memory first; a GeneratorError from any of them leaves
every output untouched, so a project is never half-regenerated. Files are
written as ``python -m seams_gen`` writes them: UTF-8 with ``\\n`` newlines.
"""

from __future__ import annotations

from pathlib import Path

from .project import Project


def generate_project(project: Project, model: Path) -> dict[Path, str]:
    """{absolute output path: text} for every generator target of ``project``."""
    from seams_gen.__main__ import GENERATORS

    files: dict[Path, str] = {}
    for target in project.generators:
        generate = GENERATORS[target.name][1]
        for name, text in generate(model, target.out).items():
            files[(target.out / name).resolve()] = text
    return files


def write_outputs(files: dict[Path, str]) -> None:
    for path, text in sorted(files.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
