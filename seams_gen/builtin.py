"""The built-in generators as ``Generator`` objects (M018/S01, ADR-0016).

One module-level object per generator of ``seams_gen.__main__.GENERATORS``,
each at ``seams_gen.__version__`` and with its ``sources`` from
``seams_gen.sources.SOURCES``. Each ``extract`` loads the model and runs the
generator's own extract step; each ``render`` is its render step, so
``generate`` returns the same bytes as the generator's old ``generate``
function. ``htmx``, ``fastapi``, ``compose``, ``dockerfile`` and
``acceptance`` also have a ``trace`` (ADR-0019).
"""

from __future__ import annotations

import sys
from pathlib import Path

from seams import ModelGraph, load

from . import __version__
from .acceptance import AcceptanceModel, extract_acceptance, render_acceptance, trace_acceptance
from .compose import ComposeFile, extract_compose_environments, render_compose_environments, trace_compose_environments
from .dockerfile import DockerfileModel, extract_dockerfile, render_dockerfile, trace_dockerfile
from .fastapi import RoutesModel, extract_route_module, render_routes, trace_routes
from .htmx import ServedPage, extract_pages, render_pages, trace_pages
from .ifmledit import FILE as IFMLEDIT_FILE
from .ifmledit import IfmlEditDocument, extract_ifmledit, render_ifmledit, unmapped_summary
from .jsonld import JsonLdModel, extract_jsonld, render_jsonld
from .mentalmodel import MentalModel, extract_mentalmodel, render_mentalmodel
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


def _acceptance_extract(trig: Path, out: Path) -> AcceptanceModel:
    """One acceptance module per handlers module the comm:PythonHandlers name."""
    return extract_acceptance(ModelGraph.load(trig))


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


def _jsonld_extract(trig: Path, out: Path) -> JsonLdModel:
    """The JSON-LD context of every shape with a sh:targetClass (ADR-0024)."""
    return extract_jsonld(load(trig))


def _mentalmodel_extract(trig: Path, out: Path) -> MentalModel:
    """The SemPKM Mental Model of the model's ontology model (ADR-0026)."""
    return extract_mentalmodel(load(trig))


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
    trace=trace_pages,
)

fastapi = Generator(
    name="fastapi",
    version=__version__,
    help="the thin FastAPI route module of the container that executes the process",
    extract=_fastapi_extract,
    render=render_routes,
    sources=SOURCES["fastapi"],
    trace=trace_routes,
)

compose = Generator(
    name="compose",
    version=__version__,
    help="a docker compose file of the arch:System's containers per arch:Environment",
    extract=_compose_extract,
    render=render_compose_environments,
    sources=SOURCES["compose"],
    trace=trace_compose_environments,
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

acceptance = Generator(
    name="acceptance",
    version=__version__,
    help="pytest files checking each hand-written comm:PythonHandler against its shapes, transitions and decisions",
    extract=_acceptance_extract,
    render=render_acceptance,
    sources=SOURCES["acceptance"],
    trace=trace_acceptance,
)

dockerfile = Generator(
    name="dockerfile",
    version=__version__,
    help="the runtime image Dockerfile of the serving container's development build",
    extract=_dockerfile_extract,
    render=_dockerfile_render,
    sources=SOURCES["dockerfile"],
    trace=trace_dockerfile,
)

ifmledit = Generator(
    name="ifmledit",
    version=__version__,
    help="the IFML interaction model as IFMLEdit.org JSON",
    extract=_ifmledit_extract,
    render=_ifmledit_render,
    sources=SOURCES["ifmledit"],
)

jsonld = Generator(
    name="jsonld",
    version=__version__,
    help="a JSON-LD context per shape with a sh:targetClass, for the API's payloads",
    extract=_jsonld_extract,
    render=render_jsonld,
    sources=SOURCES["jsonld"],
)

mentalmodel = Generator(
    name="mentalmodel",
    version=__version__,
    help="a SemPKM Mental Model: the manifest, the ontology node, the target-classed shapes and the IFML views",
    extract=_mentalmodel_extract,
    render=render_mentalmodel,
    sources=SOURCES["mentalmodel"],
)

BUILTINS: tuple[Generator, ...] = (
    htmx,
    fastapi,
    compose,
    tests,
    smoke,
    dockerfile,
    ifmledit,
    acceptance,
    jsonld,
    mentalmodel,
)

__all__ = [
    "BUILTINS",
    "acceptance",
    "compose",
    "dockerfile",
    "fastapi",
    "htmx",
    "ifmledit",
    "jsonld",
    "mentalmodel",
    "smoke",
    "tests",
]
