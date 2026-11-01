"""The built-in generators as ``Generator`` objects (M018/S01, ADR-0016).

One module-level object per generator of ``seams_gen.__main__.GENERATORS``,
each at ``seams_gen.__version__`` and with its ``sources`` from
``seams_gen.sources.SOURCES``. Each ``extract`` loads the model and runs the
generator's own extract step; each ``render`` is its render step, so
``generate`` returns the same bytes as the generator's old ``generate``
function.
"""

from __future__ import annotations

import sys
from pathlib import Path

from seams import load

from . import __version__
from .compose import ComposeFile, extract_compose_environments, render_compose_environments
from .dockerfile import DockerfileModel, extract_dockerfile, render_dockerfile
from .fastapi import RoutesModel, extract_route_module, render_routes
from .htmx import ServedPage, extract_pages, render_pages
from .ifmledit import FILE as IFMLEDIT_FILE
from .ifmledit import IfmlEditDocument, extract_ifmledit, render_ifmledit, unmapped_summary
from .protocol import Files, Generator
from .smoke import SmokeModel, extract_smoke, render_smoke
from .sources import SOURCES
from .tests import TestsModel, extract_tests, render_tests


def _htmx_extract(trig: Path, out: Path) -> tuple[ServedPage, ...]:
    """The PageModel of every served page, the landmark first."""
    return extract_pages(load(trig))


def _fastapi_extract(trig: Path, out: Path) -> RoutesModel:
    """The routes model of the one container that seam:executes a process."""
    return extract_route_module(load(trig))


def _compose_extract(trig: Path, out: Path) -> tuple[ComposeFile, ...]:
    """The compose model of each arch:Environment, with paths relative to ``out`` (D018)."""
    return extract_compose_environments(load(trig), out)


def _tests_extract(trig: Path, out: Path) -> TestsModel:
    """The scenarios, decision examples, shape examples and ODRL permission targets."""
    return extract_tests(load(trig))


def _smoke_extract(trig: Path, out: Path) -> SmokeModel:
    """One probe per hydra:Operation with a method and a path."""
    return extract_smoke(load(trig))


def _dockerfile_extract(trig: Path, out: Path) -> DockerfileModel:
    """The development build of the serving container."""
    return extract_dockerfile(load(trig))


def _dockerfile_render(d: DockerfileModel) -> Files:
    """{<route module stem>.Dockerfile: text}."""
    return {Path(d.dockerfile).name: render_dockerfile(d)}


def _ifmledit_extract(trig: Path, out: Path) -> IfmlEditDocument:
    """The IFML layer as an IFMLEdit document. The ifml: terms IFMLEdit has no
    counterpart for are named on stderr."""
    doc = extract_ifmledit(load(trig))
    print(unmapped_summary(), file=sys.stderr)
    return doc


def _ifmledit_render(doc: IfmlEditDocument) -> Files:
    """{ifmledit.json: text}."""
    return {IFMLEDIT_FILE: render_ifmledit(doc)}


htmx = Generator(
    name="htmx",
    version=__version__,
    help="the htmx/Jinja2 page of the landmark IFML ViewContainer and its fragment partials",
    extract=_htmx_extract,
    render=render_pages,
    sources=SOURCES["htmx"],
)

fastapi = Generator(
    name="fastapi",
    version=__version__,
    help="the thin FastAPI route module of the container that executes the process",
    extract=_fastapi_extract,
    render=render_routes,
    sources=SOURCES["fastapi"],
)

compose = Generator(
    name="compose",
    version=__version__,
    help="a docker compose file of the arch:System's containers per arch:Environment",
    extract=_compose_extract,
    render=render_compose_environments,
    sources=SOURCES["compose"],
)

tests = Generator(
    name="tests",
    version=__version__,
    help="pytest files for the model's verify: scenarios and examples, and its ODRL permissions",
    extract=_tests_extract,
    render=render_tests,
    sources=SOURCES["tests"],
)

smoke = Generator(
    name="smoke",
    version=__version__,
    help="a pytest file calling each operation on a running app, checking seam:returnsShape",
    extract=_smoke_extract,
    render=render_smoke,
    sources=SOURCES["smoke"],
)

dockerfile = Generator(
    name="dockerfile",
    version=__version__,
    help="the runtime image Dockerfile of the serving container's development build",
    extract=_dockerfile_extract,
    render=_dockerfile_render,
    sources=SOURCES["dockerfile"],
)

ifmledit = Generator(
    name="ifmledit",
    version=__version__,
    help="the IFML interaction model as IFMLEdit.org JSON",
    extract=_ifmledit_extract,
    render=_ifmledit_render,
    sources=SOURCES["ifmledit"],
)

BUILTINS: tuple[Generator, ...] = (htmx, fastapi, compose, tests, smoke, dockerfile, ifmledit)

__all__ = ["BUILTINS", "compose", "dockerfile", "fastapi", "htmx", "ifmledit", "smoke", "tests"]
