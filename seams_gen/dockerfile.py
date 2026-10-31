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
- the model hash and the container IRI, in the header comment and as the
  ``io.semanticseams.model-hash`` and ``io.semanticseams.container`` labels.

Every path is written literally; the file has no ARG. A model without a
serving container raises ``GeneratorError(model, seam:executes)``, a serving
container without a development deploy:artifact or deploy:build raises it on
the container with that predicate, and a build context that does not hold
the model's directory raises it with deploy:context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from seams import DEPLOY, SEAM, Model, load

from . import GeneratorError
from ._views import required, view_errors
from .compose import DEVELOPMENT, _executing, _resolve_environment
from .fastapi import route_file_name
from .htmx import _environment

TEMPLATE_NAME = "runtime.Dockerfile.j2"
SUFFIX = ".Dockerfile"


@dataclass(frozen=True)
class DockerfileModel:
    model_stem: str
    model_hash: str
    container: str  # the serving container's IRI
    context: str  # the deploy:context, as the model states it
    app_dir: str  # the model file's directory, relative to the build context
    routes_file: str  # the route module's file name
    dockerfile: str  # this file, relative to the build context


def dockerfile_name(container_iri) -> str:
    """<route module stem>.Dockerfile."""
    return Path(route_file_name(container_iri)).stem + SUFFIX


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
    context_dir = (model.path.parent / artifact.build.context).resolve()
    app_dir = Path(os.path.relpath(model.path.parent.resolve(), context_dir)).as_posix()
    if app_dir == ".." or app_dir.startswith("../"):
        raise GeneratorError(
            container.iri,
            DEPLOY.context,
            f"the build context {artifact.build.context!r} does not hold the model's directory",
        )
    name = dockerfile_name(container.iri)
    dockerfile = f"{app_dir}/generated/{name}"
    return DockerfileModel(
        model_stem=model.path.stem,
        model_hash=model_hash,
        container=str(container.iri),
        context=artifact.build.context,
        app_dir=app_dir,
        routes_file=route_file_name(container.iri),
        dockerfile=dockerfile,
    )


def render_dockerfile(d: DockerfileModel) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(d=d)


def generate_dockerfiles(trig_path) -> dict[str, str]:
    """{<route module stem>.Dockerfile: text} for the model's serving container."""
    model = load(trig_path)
    d = extract_dockerfile(model)
    return {Path(d.dockerfile).name: render_dockerfile(d)}


__all__ = [
    "DockerfileModel",
    "dockerfile_name",
    "extract_dockerfile",
    "generate_dockerfiles",
    "render_dockerfile",
    "TEMPLATE_NAME",
]
