"""``seams plan``: a Markdown change plan, or release notes, between two model versions (M015/S02, D053).

``render(old, new, changes)`` writes the breaking and then the compatible
changes ``seams diff`` finds (D052), and then, per layer, the elements NEW adds
and removes against OLD. Elements are matched by IRI (ADR-0002) and read
through the ``seams.Model`` views; a compound layer lists the IRIs of all its
element collections (a lifecycle's states and transitions, a process's BPMN
elements, the interaction models with their pages, components, events and
flows, the architecture's systems, containers, deployment nodes and
environments). The output is deterministic.

``resolve(spec, workdir)`` turns a model argument into a path. ``REF:PATH``,
where the part before the colon is not an existing path, is a git ref and a
path in it: ``git archive`` extracts PATH at REF into ``workdir``. A failing
git, or a ref or path git does not know, raises ProjectError naming the ref.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import seams

from .diff import BREAKING, COMPATIBLE, Change, shorten
from .project import ProjectError

LAYERS = (
    "architecture",
    "operations",
    "channels",
    "shapes",
    "lifecycles",
    "policies",
    "interfaces",
    "processes",
    "decisions",
)


class LayerChange(NamedTuple):
    """The element IRIs one layer adds and removes, each sorted."""

    added: tuple[str, ...]
    removed: tuple[str, ...]


def _git(args: list[str], cwd: Path, ref: str) -> bytes:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except OSError as err:
        raise ProjectError(f"{ref}: cannot run git: {err}") from err
    if done.returncode != 0:
        message = done.stderr.decode(errors="replace").strip() or f"git {args[0]} exited {done.returncode}"
        raise ProjectError(f"{ref}: {message}")
    return done.stdout


def resolve(spec: str, workdir: Path) -> Path:
    """The model path ``spec`` names: a plain path, or ``REF:PATH`` extracted from git into ``workdir``."""
    ref, sep, rel = spec.partition(":")
    if not sep or not ref or not rel or Path(ref).exists():
        return Path(spec)
    cwd = Path.cwd()
    root = Path(_git(["rev-parse", "--show-toplevel"], cwd, ref).decode().strip())
    try:
        inside = (cwd / rel).resolve().relative_to(root.resolve()).as_posix()
    except ValueError as err:
        raise ProjectError(f"{ref}: {rel} is outside the git repository {root}") from err
    archive = _git(["archive", "--format=tar", ref, "--", inside], root, ref)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(workdir, filter="data")
    except (tarfile.TarError, OSError) as err:
        raise ProjectError(f"{ref}: cannot extract {inside}: {err}") from err
    return workdir / inside


def _iris(collections: Iterable[Iterable[object]]) -> set[str]:
    return {str(item.iri) for items in collections for item in items}  # type: ignore[attr-defined]


def _layer_iris(model: seams.Model, layer: str) -> set[str]:
    if layer == "architecture":
        arch = model.architecture
        return _iris([arch.systems(), arch.containers(), arch.deployment_nodes(), arch.environments()])
    if layer == "lifecycles":
        lifecycles = model.lifecycles
        return _iris([lifecycles, *(lc.states() for lc in lifecycles), lifecycles.transitions()])
    if layer == "interfaces":
        ifml = model.interfaces
        return _iris([ifml.models(), ifml.pages(), ifml.components(), ifml.events(), ifml.flows()])
    if layer == "processes":
        processes = model.processes
        # A process with no single BPMN model has no elements to list; the shapes flag it.
        return _iris([processes, *(p.elements() for p in processes if len(p.bpmn_models) == 1)])
    return _iris([getattr(model, layer)])


def layer_changes(old: seams.Model, new: seams.Model) -> dict[str, LayerChange]:
    """Every layer in ``LAYERS`` order with the element IRIs NEW adds and removes against OLD."""
    result = {}
    for layer in LAYERS:
        before, after = _layer_iris(old, layer), _layer_iris(new, layer)
        result[layer] = LayerChange(tuple(sorted(after - before)), tuple(sorted(before - after)))
    return result


def _bullets(lines: list[str]) -> list[str]:
    return [f"- {line}" for line in lines] or ["None"]


def render(old: seams.Model, new: seams.Model, changes: Iterable[Change]) -> str:
    """The Markdown change plan from OLD to NEW for ``seams diff``'s ``changes``."""
    ordered = sorted(changes, key=lambda c: (c.subject, c.kind, c.detail, c.verdict))

    def described(verdict: str) -> list[str]:
        return [
            shorten(f"{c.kind} {c.subject} {c.detail}", new, old).removesuffix(" -")
            for c in ordered
            if c.verdict == verdict
        ]

    out = ["# Change plan", "", "## Breaking changes", "", *_bullets(described(BREAKING)), ""]
    out += ["## Compatible changes", "", *_bullets(described(COMPATIBLE)), ""]
    out += ["## Elements by layer", ""]
    layers = [(layer, change) for layer, change in layer_changes(old, new).items() if change.added or change.removed]
    if not layers:
        out += ["None", ""]
    for layer, change in layers:
        out += [f"### {layer.capitalize()}", ""]
        for title, iris in (("Added", change.added), ("Removed", change.removed)):
            if iris:
                out += [f"{title}:", "", *(f"- {shorten(iri, new, old)}" for iri in iris), ""]
    return "\n".join(out).rstrip("\n") + "\n"
