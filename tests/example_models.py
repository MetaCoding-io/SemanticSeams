"""The committed example models, for tests that check every one.

A model is a TriG file, or a directory whose seams.toml names the directory
itself (``model = "."``): its TriG files are one dataset (ADR-0030 section 3),
and one of them alone may not load (chapter 11's expenses.trig imports the
finance ontology that finance.trig declares).
"""

from __future__ import annotations

from pathlib import Path

from seams_cli import load_project

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def example_models() -> list[Path]:
    """Every model under examples/ (generated outputs excluded), sorted."""
    models: set[Path] = set()
    for trig in EXAMPLES.rglob("*.trig"):
        if "generated" in trig.relative_to(ROOT).parts:
            continue
        directory = trig.parent
        is_directory_model = (directory / "seams.toml").is_file() and (
            load_project(directory).model == directory.resolve()
        )
        models.add(directory if is_directory_model else trig)
    return sorted(models)
