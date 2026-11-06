"""The runtime image build file generator (M016/S03, ADR-0015).

The generator writes one Dockerfile per serving container
(``seams_gen.fastapi.serving_containers``, at most one, D026) whose
deploy:artifact in the ``development`` arch:Environment has a deploy:build:
``<route module stem>.Dockerfile``, beside the route module in the app's
``generated/`` directory. The build's deploy:dockerfile names that file
relative to the deploy:context, so the compose file builds the image from it.

``extract_dockerfile`` reads, through the seams views:

- the app directory: the model file's directory relative to the
  deploy:context of the build (which the model states relative to the
  model file's directory), as ``compose`` computes the build context;
- the route module, ``route_file_name(container)``; the image copies it, the
  app's ``generated/templates`` and its ``seed.json`` from the app directory;
- the uv workspace members, from ``[tool.uv.workspace].members`` of the
  ``pyproject.toml`` at the root of the build context (backlog A12): the image
  copies each member's ``pyproject.toml``, and its ``[project].readme`` when
  that is a string, so ``uv sync --locked`` sees the whole workspace;
- the model hash and the container IRI, in the header comment and as the
  ``io.semanticseams.model-hash`` and ``io.semanticseams.container`` labels.

Every path is written literally; the file has no ARG. A model without a
serving container raises ``GeneratorError(model, seam:executes)``, a serving
container without a development deploy:artifact or deploy:build raises it on
the container with that predicate, and a build context that does not hold
the model's directory raises it with deploy:context, as does a build context
whose root ``pyproject.toml`` or a member's ``pyproject.toml`` is missing or
unreadable, lists no workspace members, or names a member with a glob
pattern. A deploy:dockerfile that
does not name the file this generator writes (compared as normalised posix
paths), or a deploy:build without one, raises it with deploy:dockerfile:
compose would build the image from another file (backlog A11).

The workspace files are the generator's inputs beyond the model (ADR-0016):
``dockerfile_inputs`` names the root ``pyproject.toml`` and each member's, so
a tool that regenerates in a scratch copy copies them too.
"""

from __future__ import annotations

import os
import posixpath
import tomllib
from dataclasses import dataclass
from pathlib import Path

from seams import DEPLOY, SEAM, Model, SeamsError, load

from . import GeneratorError
from ._views import required, view_errors
from .compose import DEVELOPMENT, _executing, _resolve_environment
from .fastapi import route_file_name
from .htmx import _environment, _tracing_environment
from .trace import Trace, trace_template

TEMPLATE_NAME = "runtime.Dockerfile.j2"
SUFFIX = ".Dockerfile"


GLOB_CHARACTERS = frozenset("*?[]")


@dataclass(frozen=True)
class WorkspaceMember:
    path: str  # the member's directory, relative to the build context
    files: tuple[str, ...]  # pyproject.toml and its readme, relative to path, sorted


@dataclass(frozen=True)
class DockerfileModel:
    model_stem: str
    model_hash: str
    container: str  # the serving container's IRI
    context: str  # the deploy:context, as the model states it
    app_dir: str  # the model file's directory, relative to the build context
    routes_file: str  # the route module's file name
    dockerfile: str  # this file, relative to the build context
    members: tuple[WorkspaceMember, ...]  # the uv workspace members, sorted by path


def dockerfile_name(container_iri) -> str:
    """<route module stem>.Dockerfile."""
    return Path(route_file_name(container_iri)).stem + SUFFIX


def _read_pyproject(path: Path, subject, context: str) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GeneratorError(
            subject,
            DEPLOY.context,
            f"the build context {context!r} needs a readable {path.name} at {path.as_posix()}: {exc}",
        ) from exc


def _workspace_members(context_dir: Path, subject, context: str) -> tuple[WorkspaceMember, ...]:
    """The uv workspace members named by the build context's root pyproject.toml."""
    root = _read_pyproject(context_dir / "pyproject.toml", subject, context)
    members = root.get("tool", {}).get("uv", {}).get("workspace", {}).get("members")
    if not isinstance(members, list) or not members or not all(isinstance(m, str) for m in members):
        raise GeneratorError(
            subject,
            DEPLOY.context,
            f"the build context {context!r} pyproject.toml at {(context_dir / 'pyproject.toml').as_posix()} "
            "needs a non-empty list of [tool.uv.workspace] members",
        )
    result: list[WorkspaceMember] = []
    for member in members:
        if GLOB_CHARACTERS & set(member):
            raise GeneratorError(
                subject,
                DEPLOY.context,
                f"the build context {context!r} pyproject.toml names the workspace member {member!r} "
                "with a glob pattern; name each member's directory",
            )
        path = posixpath.normpath(member)
        project = _read_pyproject(context_dir / path / "pyproject.toml", subject, context).get("project", {})
        readme = project.get("readme") if isinstance(project, dict) else None
        files = {"pyproject.toml"} | ({readme} if isinstance(readme, str) else set())
        result.append(WorkspaceMember(path=path, files=tuple(sorted(files))))
    return tuple(sorted(result, key=lambda m: m.path))


def extract_dockerfile(model: Model) -> DockerfileModel:
    """The Dockerfile model of the serving container's development build."""
    executing = _executing(model)
    if not executing:
        raise GeneratorError(model.subject, SEAM.executes, "expected one serving container, found none")
    (container,) = executing
    env = _resolve_environment(model, DEVELOPMENT)
    with view_errors():
        deployment = container.for_environment(env)
        model_hash = model.hash
    artifact = required(deployment.artifact, container.iri, DEPLOY.artifact, f"in {env.iri}")
    if artifact.build is None:
        raise GeneratorError(
            container.iri,
            DEPLOY.build,
            f"the {env.iri} deploy:artifact needs a deploy:build to generate the runtime image's Dockerfile",
        )
    context_dir = (model.base_dir / artifact.build.context).resolve()
    app_dir = Path(os.path.relpath(model.base_dir, context_dir)).as_posix()
    if app_dir == ".." or app_dir.startswith("../"):
        raise GeneratorError(
            container.iri,
            DEPLOY.context,
            f"the build context {artifact.build.context!r} does not hold the model's directory",
        )
    name = dockerfile_name(container.iri)
    dockerfile = f"{app_dir}/generated/{name}"
    stated = artifact.build.dockerfile
    if stated is None or posixpath.normpath(stated) != posixpath.normpath(dockerfile):
        raise GeneratorError(
            container.iri,
            DEPLOY.dockerfile,
            f"the {env.iri} deploy:build states {stated!r}; it must name the generated Dockerfile, "
            f"{posixpath.normpath(dockerfile)!r} relative to the build context",
        )
    return DockerfileModel(
        model_stem=model.path.stem,
        model_hash=model_hash,
        container=str(container.iri),
        context=artifact.build.context,
        app_dir=app_dir,
        routes_file=route_file_name(container.iri),
        dockerfile=dockerfile,
        members=_workspace_members(context_dir, container.iri, artifact.build.context),
    )


def dockerfile_inputs(trig: Path, out: Path) -> tuple[Path, ...]:
    """The workspace files ``extract_dockerfile`` reads, as absolute paths, sorted:
    the build context's root pyproject.toml and each member's that exists. It
    never raises; a file or fact it cannot find is left out, and
    ``extract_dockerfile`` raises on it."""
    try:
        model = load(trig)
        executing = _executing(model)
        if len(executing) != 1:
            return ()
        (container,) = executing
        env = _resolve_environment(model, DEVELOPMENT)
        with view_errors():
            artifact = container.for_environment(env).artifact
    except (GeneratorError, SeamsError, OSError):
        return ()
    if artifact is None or artifact.build is None:
        return ()
    context_dir = (model.base_dir / artifact.build.context).resolve()
    root = context_dir / "pyproject.toml"
    if not root.is_file():
        return ()
    found = {root}
    try:
        with root.open("rb") as f:
            members = tomllib.load(f).get("tool", {}).get("uv", {}).get("workspace", {}).get("members")
    except (OSError, tomllib.TOMLDecodeError):
        return (root,)
    for member in members if isinstance(members, list) else []:
        if isinstance(member, str) and not GLOB_CHARACTERS & set(member):
            path = context_dir / posixpath.normpath(member) / "pyproject.toml"
            if path.is_file():
                found.add(path)
    return tuple(sorted(found))


def render_dockerfile(d: DockerfileModel) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(d=d)


def trace_dockerfile(d: DockerfileModel, generator: str = "dockerfile") -> dict[str, Trace]:
    """{<route module stem>.Dockerfile: Trace}; a line no origin-carrying value
    lands on takes the serving container's IRI."""
    name = Path(d.dockerfile).name
    trace = trace_template(
        _tracing_environment(),
        TEMPLATE_NAME,
        {"d": d},
        output=name,
        generator=generator,
        expected=render_dockerfile(d),
        fallback=(d.container,),
    )
    return {name: trace}


def generate_dockerfiles(trig_path) -> dict[str, str]:
    """{<route module stem>.Dockerfile: text} for the model's serving container."""
    model = load(trig_path)
    d = extract_dockerfile(model)
    return {Path(d.dockerfile).name: render_dockerfile(d)}


__all__ = [
    "DockerfileModel",
    "WorkspaceMember",
    "dockerfile_inputs",
    "dockerfile_name",
    "extract_dockerfile",
    "generate_dockerfiles",
    "render_dockerfile",
    "trace_dockerfile",
    "TEMPLATE_NAME",
]
