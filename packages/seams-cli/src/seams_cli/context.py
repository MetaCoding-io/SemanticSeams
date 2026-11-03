"""``seams context``: the context manifest of a service task as a review report (M022/S01, backlog C3).

``run_context`` loads the project's model (``resolve_model``, so ``--model``
and SEAMS_MODEL apply as for generate) and returns ``seams.context_for`` of
the task, given as a BPMN id, CURIE or IRI. ``render`` prints the task, one
``<kind> <ref> <hash>`` line per item and ``context <hash>``; ``to_json``
gives the same with sorted keys and the items in manifest order. Refs are
IRIs or model-relative ``path#id``, so neither form holds an absolute path.
A model that cannot be loaded raises ProjectError (exit 2); an unknown task
or a missing hop raises ResolutionError, which the command reports with
exit 1.
"""

from __future__ import annotations

from pathlib import Path

import seams

from .project import Project, ProjectError, resolve_model


def run_context(project: Project, model: Path | None, task: str) -> seams.Manifest:
    """The context manifest of service task ``task`` in the project's model."""
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    return seams.context_for(loaded, task)


def render(manifest: seams.Manifest) -> str:
    """The text report: the task, one line per item, then the context hash."""
    lines = [f"task {manifest.task}"]
    lines.extend(f"{item.kind} {item.ref} {item.hash}" for item in manifest.items)
    lines.append(f"context {manifest.context_hash}")
    return "\n".join(lines) + "\n"


def to_json(manifest: seams.Manifest) -> dict[str, object]:
    """The JSON report: the task, the items in (kind, ref) order and the context hash."""
    return {
        "task": str(manifest.task),
        "items": [{"kind": i.kind, "ref": i.ref, "hash": i.hash} for i in manifest.items],
        "context_hash": manifest.context_hash,
    }
