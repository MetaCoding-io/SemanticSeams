"""``seams import-storm FILE --out PATH [--base IRI]`` (M033/S03, backlog X12, ADR-0046).

``run_import_storm`` parses a big-picture event storm (``seams_gen.storm_import``) and
writes the skeleton model to ``out`` and its BPMN payload beside it through the
seams_edit create path, which refuses a path that exists and writes both or neither.
``base`` replaces the storm's ``<!-- base: IRI -->``. It returns the paths written
and the gaps the skeleton leaves for the author: the seam shapes flag them and
``seams generate`` refuses the model until they are filled.

A line the import cannot read raises GeneratorError naming the line; an existing
output raises PatchError; a base that is not an absolute IRI ending in ``/`` or ``#``
raises ProjectError (all exit 2, writing nothing).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from seams_gen.storm_import import is_base, parse, write

from .project import ProjectError


def run_import_storm(storm: Path, out: Path, base: str | None = None) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """(paths written, sorted; gaps) for the storm file ``storm`` imported to ``out``."""
    draft = parse(storm.read_text(encoding="utf-8"))
    if base is not None:
        if not is_base(base):
            raise ProjectError(f"--base <{base}> is not an absolute IRI ending in / or #")
        draft = dataclasses.replace(draft, base=base)
    gaps = write(draft, out)
    payload = out.resolve().parent / draft.payload_name
    return tuple(sorted((out.resolve(), payload))), gaps
