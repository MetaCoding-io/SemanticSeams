"""``seams sequence``: derive a project's as-designed sequence diagrams (M013/S02, D047).

``run_sequence`` loads the project's model (``resolve_model``, so ``--model``
and SEAMS_MODEL apply as for generate), derives one Mermaid diagram per
gateway path of the process the IFML event triggers (``seams_gen.sequence``)
and writes each as ``<out>/<name>.mmd``; ``out`` defaults to
``<project root>/sequences``. The diagrams are not generator outputs, so
seams.lock does not record them. A model that cannot be loaded raises
ProjectError; an unknown event raises GeneratorError (both exit 2).

With ``trace`` (backlog U4) it draws one recorded run instead:
``read_trace`` reads the worker's trace rows from a JSON file or from an
instance id in the runtime's SQLite store at ``db`` (default SEAMS_DB, else
``<project root>/seams.sqlite``), and ``executed`` writes the single
as-executed ``<out>/<event>.executed.mmd``. A missing instance or a malformed
trace file raises GeneratorError (exit 2).
"""

from __future__ import annotations

import os
from pathlib import Path

import seams

from seams_gen.sequence import derive, executed, read_trace, write_diagrams

from .project import Project, ProjectError, resolve_model


def run_sequence(
    project: Project,
    model: Path | None,
    event: str,
    out: Path | None = None,
    trace: str | None = None,
    db: Path | None = None,
) -> tuple[list[Path], list[tuple[str, str]]]:
    """(paths written, [(diagram name, gap detail)]) for ``event`` in the project's model."""
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    if trace is None:
        diagrams = derive(loaded, event)
    else:
        if db is None:
            db = Path(os.environ.get("SEAMS_DB") or project.root / "seams.sqlite")
        run, rows = read_trace(trace, db)
        diagrams = [executed(loaded, event, rows, run=run)]
    paths = write_diagrams(diagrams, out if out is not None else project.root / "sequences")
    return paths, [(d.name, gap) for d in diagrams for gap in d.gaps]
