"""The seams.toml project file: which model an app is generated from, and where.

A project file names the model, the generators and their output directories,
and the app's environments::

    model = "expenses.trig"

    [[generators]]
    name = "fastapi"
    out = "generated"

    [[generators]]
    name = "htmx"
    out = "generated/templates"

    [environments.dev]

Relative paths resolve against the directory of the project file, so the
command gives the same result from any working directory. ``environments``
is a placeholder: only the names are read for now.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from seams.loader import MODEL_ENV

PROJECT_FILE = "seams.toml"


class ProjectError(ValueError):
    """The project file is missing or malformed; the message names the file and the key."""


@dataclass(frozen=True)
class GeneratorTarget:
    """One generator run: a seams_gen generator name and its absolute output directory."""

    name: str
    out: Path


@dataclass(frozen=True)
class Project:
    """A loaded project file. ``path`` is the file, ``root`` its directory;
    ``model`` and every ``out`` are absolute."""

    path: Path
    root: Path
    model: Path | None
    generators: tuple[GeneratorTarget, ...]
    environments: tuple[str, ...]


def _known_generators() -> dict:
    from seams_gen.__main__ import GENERATORS

    return GENERATORS


def load_project(path: Path | str) -> Project:
    """Read ``path``, a seams.toml file or a directory that holds one."""
    path = Path(path)
    if path.is_dir():
        path = path / PROJECT_FILE
    path = path.resolve()
    if not path.is_file():
        raise ProjectError(f"{path}: no such project file")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as err:
        raise ProjectError(f"{path}: invalid TOML: {err}") from err
    root = path.parent

    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise ProjectError(f"{path}: `model` must be a string, got {type(model).__name__}")

    generators = data.get("generators", [])
    if not isinstance(generators, list) or not all(isinstance(entry, dict) for entry in generators):
        raise ProjectError(f"{path}: `generators` must be an array of tables ([[generators]])")
    known = _known_generators()
    targets = []
    for index, entry in enumerate(generators):
        for key in ("name", "out"):
            if not isinstance(entry.get(key), str):
                raise ProjectError(f"{path}: `generators[{index}]` needs a string `{key}`")
        if entry["name"] not in known:
            raise ProjectError(
                f"{path}: `generators[{index}].name` is {entry['name']!r}; known generators: {', '.join(sorted(known))}"
            )
        targets.append(GeneratorTarget(entry["name"], root / entry["out"]))

    environments = data.get("environments", {})
    if not isinstance(environments, dict) or not all(isinstance(env, dict) for env in environments.values()):
        raise ProjectError(f"{path}: `environments` must be a table of tables ([environments.<name>])")

    return Project(
        path=path,
        root=root,
        model=root / model if model is not None else None,
        generators=tuple(targets),
        environments=tuple(environments),
    )


def resolve_model(project: Project, override: Path | None = None) -> Path:
    """The model to generate from: ``override`` (``--model``), then the project's
    ``model``, then ``SEAMS_MODEL`` when non-empty. An explicit path beats the
    environment, as in ``seams.load`` (D034)."""
    if override is not None:
        return Path(override)
    if project.model is not None:
        return project.model
    env = os.environ.get(MODEL_ENV, "")
    if env:
        return Path(env)
    raise ProjectError(f"no model: set `model` in {project.path} or {MODEL_ENV}")
