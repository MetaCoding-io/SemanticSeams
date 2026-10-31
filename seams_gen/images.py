"""The images a project publishes (M016/S03, ADR-0015, backlog A5).

``list_images(project)`` reads a project's seams.toml and returns one
``Image`` per Dockerfile its ``dockerfile`` generator writes: the generated
file and the build context it is relative to (from the serving container's
development deploy:build, as ``seams_gen.dockerfile`` computes them), and the
deploy:reference and deploy:version of the container's deploy:artifact in the
``production`` arch:Environment, through ``Container.for_environment``. Each
image is tagged ``<reference>:<version>`` and ``<reference>:sha-<short hash>``,
the short hash being the first ``SHORT_HASH`` hex digits of ``model.hash``,
so a published image names the model it serves. The publish workflow
(.github/workflows/publish-images.yml) builds and pushes these.

Command line: ``python -m seams_gen.images PROJECT...`` prints the images of
every project as one JSON array, with paths relative to the current
directory. A project file that is missing, unreadable or lists no
``dockerfile`` generator, or a generated Dockerfile that is not on disk,
prints the reason and exits 1; a model fact that is missing (no
``production`` environment, no production deploy:artifact) prints the
GeneratorError, naming subject and predicate, and exits 2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from seams import DEPLOY, load

from . import GeneratorError
from ._views import required, view_errors
from .compose import _executing, _resolve_environment
from .dockerfile import extract_dockerfile

PROJECT_FILE = "seams.toml"
GENERATOR = "dockerfile"
PRODUCTION = "production"
#: Hex digits of the sha256 model hash in the sha-<hash> tag.
SHORT_HASH = 12

EXIT_GENERATOR_ERROR = 2
EXIT_PROJECT_ERROR = 1


class ProjectError(Exception):
    """A project file or generated Dockerfile the image list cannot be read from."""


@dataclass(frozen=True)
class Image:
    container: str  # the serving container's IRI
    context: str  # the build context
    dockerfile: str  # the generated Dockerfile
    reference: str  # the production deploy:reference
    registry: str  # the registry host the reference names
    version: str  # the production deploy:version
    model_hash: str  # "sha256:<hex>"
    tags: tuple[str, ...]  # <reference>:<version>, <reference>:sha-<short hash>


def short_hash(model_hash: str) -> str:
    """The first SHORT_HASH hex digits of a ``sha256:<hex>`` model hash."""
    return model_hash.removeprefix("sha256:")[:SHORT_HASH]


def registry(reference: str) -> str:
    """The registry host of an image reference, Docker's rule: the first path
    component when it has a dot or a port or is localhost, else docker.io."""
    first, sep, _ = reference.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first
    return "docker.io"


def _project(path: Path) -> tuple[Path, Path, list[Path]]:
    """(project file, model, every ``dockerfile`` generator ``out``), absolute."""
    if path.is_dir():
        path = path / PROJECT_FILE
    path = path.resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ProjectError(f"{path}: no such project file") from err
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise ProjectError(f"{path}: {err}") from err
    model = data.get("model")
    if not isinstance(model, str):
        raise ProjectError(f"{path}: `model` must be a string")
    outs = [
        path.parent / entry["out"]
        for entry in data.get("generators", [])
        if isinstance(entry, dict) and entry.get("name") == GENERATOR and isinstance(entry.get("out"), str)
    ]
    if not outs:
        raise ProjectError(f"{path}: lists no `{GENERATOR}` generator, so it builds no image")
    return path, path.parent / model, outs


def _relative(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def list_images(project, cwd=None) -> list[Image]:
    """The images of ``project`` (a seams.toml or its directory), paths relative to ``cwd``."""
    cwd = Path(cwd or Path.cwd()).resolve()
    project_file, trig, outs = _project(Path(project))
    model = load(trig)
    d = extract_dockerfile(model)
    (container,) = _executing(model)  # extract_dockerfile found exactly one
    env = _resolve_environment(model, PRODUCTION)
    with view_errors():
        deployment = container.for_environment(env)
    artifact = required(deployment.artifact, d.container, DEPLOY.artifact, f"in the {PRODUCTION} environment")
    context = (model.path.parent / d.context).resolve()
    tags = (f"{artifact.reference}:{artifact.version}", f"{artifact.reference}:sha-{short_hash(d.model_hash)}")
    images = []
    for out in outs:
        dockerfile = (out / Path(d.dockerfile).name).resolve()
        if not dockerfile.is_file():
            raise ProjectError(f"{project_file}: {dockerfile} is missing; run `seams generate`")
        images.append(
            Image(
                container=d.container,
                context=_relative(context, cwd),
                dockerfile=_relative(dockerfile, cwd),
                reference=artifact.reference,
                registry=registry(artifact.reference),
                version=artifact.version,
                model_hash=d.model_hash,
                tags=tags,
            )
        )
    return images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m seams_gen.images", description="List the images projects publish, as JSON."
    )
    parser.add_argument("projects", nargs="+", type=Path, help="a seams.toml or the directory that holds it")
    args = parser.parse_args(argv)
    try:
        images = [image for project in args.projects for image in list_images(project)]
    except GeneratorError as err:
        print(f"seams_gen.images: {err}", file=sys.stderr)
        return EXIT_GENERATOR_ERROR
    except ProjectError as err:
        print(f"seams_gen.images: {err}", file=sys.stderr)
        return EXIT_PROJECT_ERROR
    print(json.dumps([asdict(image) for image in images], indent=2))
    return 0


__all__ = ["Image", "ProjectError", "list_images", "main", "registry", "short_hash", "SHORT_HASH"]


if __name__ == "__main__":
    sys.exit(main())
