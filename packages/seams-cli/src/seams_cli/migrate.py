"""``seams migrate``: write a model's vocabulary migrations into its files (ADR-0021 section 5).

``seams.load`` migrates a model that targets an older vocabulary in memory
only. ``migrate`` reads the model's TriG files as written, runs the same
check and steps (``seams.check_versions``) on a copy, and applies the
difference, per named graph, as one patch through the ``seams_edit`` text
writer (ADR-0017). Comments and layout outside the changed triples survive.

The quads come from ``seams_edit.text_quads``, so a blank node carries the
label the writer gives it when it reads the same text. When no step applies,
or the check fails (a newer model, a missing step), nothing is written.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import rdflib
import seams
from rdflib.term import IdentifiedNode

import seams_edit

from .check import ONTOLOGY_DIR


@dataclass(frozen=True)
class Migration:
    """The steps applied, sorted, and the files written, sorted; both empty
    when the model already targets the shipped vocabularies."""

    steps: tuple[seams.MigrationStep, ...]
    files: tuple[Path, ...]


def _as_written(files: tuple[Path, ...]) -> rdflib.Dataset:
    ds = rdflib.Dataset(default_union=True)
    for path in files:
        _add(ds, seams_edit.text_quads(path.read_text(encoding="utf-8"), base=path.as_uri()))
    return ds


def _add(ds: rdflib.Dataset, quads: Iterable[seams_edit.Quad]) -> None:
    for s, p, o, g in quads:
        # A TriG graph name is an IRI or a blank node, never a literal.
        ds.graph(cast(IdentifiedNode, g)).add((s, p, o))


def _quads(ds: rdflib.Dataset) -> set[seams_edit.Quad]:
    return {(s, p, o, g) for s, p, o, g in ds.quads((None, None, None, None)) if g is not None}


def migration_patch(
    model: Path, ontology_dir: Path = ONTOLOGY_DIR
) -> tuple[tuple[Path, ...], tuple[seams.MigrationStep, ...], seams_edit.Patch]:
    """The model's TriG files, the steps that apply and the patch that takes
    the files to the migrated model; no steps and an empty patch when the
    model is current. Raises ``ResolutionError`` when the version check fails."""
    files = seams.load(model, check_versions=False).files
    before = _quads(_as_written(files))
    migrated = rdflib.Dataset(default_union=True)
    _add(migrated, before)
    steps = seams.check_versions(migrated, ontology_dir)
    after = _quads(migrated)
    return files, steps, seams_edit.Patch(adds=sorted(after - before), removes=sorted(before - after))


def migrate(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> Migration:
    """Migrate the model's files to the vocabularies in ``ontology_dir``."""
    files, steps, patch = migration_patch(model, ontology_dir)
    if patch.is_empty:
        return Migration(steps, ())
    record = seams_edit.apply(files, patch)
    return Migration(steps, tuple(sorted(edit.path for edit in record.files)))
