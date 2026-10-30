"""seams.lock: what ``seams generate`` last wrote, and from what (M012/S02, D043).

The lockfile sits next to seams.toml. It is JSON with sorted keys and no
timestamps, so regenerating an unchanged project rewrites it byte for byte::

    {
      "lockfile_version": 1,
      "model": "expenses.trig",
      "model_hash": "...",
      "outputs": [
        {
          "generator": "fastapi",
          "generator_version": "0.1.0",
          "model_hash": "...",
          "path": "generated/expense_api.py",
          "sha256": "...",
          "sources": ["https://...", ...]
        }
      ]
    }

Paths are posix and relative to the project root; a target outside it (the
chat app's ``../..``) gives paths starting with ``../``. ``audit`` compares a
lock, the files on disk and the files produced now; ``seams generate`` uses it
to delete orphans and report hand edits, and ``seams check`` (S03) to fail on them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from seams import model_hash as hash_model

from .project import Project, ProjectError

LOCK_FILE = "seams.lock"
LOCKFILE_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


class LockError(ProjectError):
    """seams.lock is not valid JSON or does not follow the schema; the message names the file and the key."""


class Output(NamedTuple):
    """One produced file: the generator that wrote it, its text and its source element IRIs."""

    generator: str
    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class LockedOutput:
    path: str
    generator: str
    generator_version: str
    model_hash: str
    sha256: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Lock:
    model: str
    model_hash: str
    outputs: tuple[LockedOutput, ...]


@dataclass(frozen=True)
class Audit:
    """Project-relative paths, each tuple sorted.

    ``missing``: locked and produced now, but absent on disk. ``edited``: locked
    and on disk with a sha256 that is neither the locked one nor that of the
    new text. ``orphans``: locked but not produced now."""

    missing: tuple[str, ...] = ()
    edited: tuple[str, ...] = ()
    orphans: tuple[str, ...] = ()


def lock_path(project: Project) -> Path:
    return project.root / LOCK_FILE


def sha256_text(text: str) -> str:
    """The hex sha256 of ``text`` as written: UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(project: Project, path: Path) -> str:
    """``path`` relative to the project root, posix, possibly starting with ``../``."""
    return Path(os.path.relpath(path, project.root)).as_posix()


def locate(project: Project, rel: str) -> Path:
    """The absolute path of a lock path, with ``..`` folded but no symlink followed."""
    return Path(os.path.normpath(project.root / rel))


def _require(path: Path, value: object, key: str, kind: type) -> object:
    if not isinstance(value, kind):
        raise LockError(f"{path}: `{key}` must be a {kind.__name__}, got {type(value).__name__}")
    return value


def _output(path: Path, index: int, entry: object) -> LockedOutput:
    key = f"outputs[{index}]"
    _require(path, entry, key, dict)
    fields = {
        name: _require(path, entry.get(name), f"{key}.{name}", str)
        for name in ("path", "generator", "generator_version", "model_hash", "sha256")
    }
    if not _SHA256.fullmatch(fields["sha256"]):
        raise LockError(f"{path}: `{key}.sha256` must be 64 lowercase hex digits")
    sources = _require(path, entry.get("sources"), f"{key}.sources", list)
    for i, iri in enumerate(sources):
        _require(path, iri, f"{key}.sources[{i}]", str)
    return LockedOutput(sources=tuple(sources), **fields)


def read_lock(project: Project) -> Lock | None:
    """The project's seams.lock, or None when there is none. Raises LockError when malformed."""
    path = lock_path(project)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise LockError(f"{path}: invalid JSON: {err}") from err
    _require(path, data, "(top level)", dict)
    if data.get("lockfile_version") != LOCKFILE_VERSION:
        raise LockError(f"{path}: `lockfile_version` must be {LOCKFILE_VERSION}, got {data.get('lockfile_version')!r}")
    model = _require(path, data.get("model"), "model", str)
    model_hash = _require(path, data.get("model_hash"), "model_hash", str)
    entries = _require(path, data.get("outputs"), "outputs", list)
    return Lock(model, model_hash, tuple(_output(path, i, entry) for i, entry in enumerate(entries)))


def build_lock(project: Project, model: Path, outputs: Mapping[Path, Output]) -> Lock:
    """The lock for ``outputs`` ({absolute path: Output}) generated from ``model``."""
    from seams_gen import __version__

    digest = hash_model(model)
    locked = [
        LockedOutput(relative(project, path), out.generator, __version__, digest, sha256_text(out.text), out.sources)
        for path, out in outputs.items()
    ]
    return Lock(relative(project, Path(model).resolve()), digest, tuple(sorted(locked, key=lambda o: o.path)))


def render_lock(lock: Lock) -> str:
    data = {
        "lockfile_version": LOCKFILE_VERSION,
        "model": lock.model,
        "model_hash": lock.model_hash,
        "outputs": [
            {
                "generator": o.generator,
                "generator_version": o.generator_version,
                "model_hash": o.model_hash,
                "path": o.path,
                "sha256": o.sha256,
                "sources": list(o.sources),
            }
            for o in sorted(lock.outputs, key=lambda o: o.path)
        ],
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def audit(project: Project, lock: Lock | None, files: Mapping[Path, str]) -> Audit:
    """Compare ``lock`` with the files on disk and ``files`` ({absolute path: new text}).
    Reads files, writes nothing. Without a lock there is nothing to report."""
    if lock is None:
        return Audit()
    produced = {relative(project, path): text for path, text in files.items()}
    missing, edited, orphans = [], [], []
    for entry in lock.outputs:
        if entry.path not in produced:
            orphans.append(entry.path)
            continue
        on_disk = locate(project, entry.path)
        if not on_disk.is_file():
            missing.append(entry.path)
        elif sha256_file(on_disk) not in (entry.sha256, sha256_text(produced[entry.path])):
            edited.append(entry.path)
    return Audit(tuple(sorted(missing)), tuple(sorted(edited)), tuple(sorted(orphans)))


__all__ = [
    "LOCK_FILE",
    "Audit",
    "Lock",
    "LockError",
    "LockedOutput",
    "Output",
    "audit",
    "build_lock",
    "read_lock",
    "render_lock",
]
