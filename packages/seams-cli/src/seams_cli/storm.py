"""``seams storm``: derive a process's event-storm timeline (M028/S01, backlog B4).

``run_storm`` loads the project's model (``resolve_model``, so ``--model`` and
SEAMS_MODEL apply as for generate) and renders the Markdown timeline of the
process named by IRI, CURIE or local name, or by the ifml:Event that
seam:triggers it (``seams_gen.storm``). With ``out`` the timeline is written
there; the file is not a generator output, so seams.lock does not record it.
A model that cannot be loaded raises ProjectError; an unknown name raises
GeneratorError naming it (both exit 2).
"""

from __future__ import annotations

from pathlib import Path

import seams
from seams import local_name

from seams_gen.storm import derive, render

from .project import Project, ProjectError, resolve_model


def run_storm(
    project: Project, model: Path | None, name: str, out: Path | None = None
) -> tuple[str, list[tuple[str, str]]]:
    """(rendered timeline, [(process name, gap detail)]) for ``name`` in the
    project's model. With ``out``, the timeline is also written there."""
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    storm = derive(loaded, name)
    text = render(storm)
    if out is not None:
        out.write_text(text, encoding="utf-8")
    process = local_name(storm.process)
    return text, [(process, gap) for gap in storm.gaps]
