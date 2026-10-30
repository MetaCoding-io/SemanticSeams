"""The model elements each generated file comes from (M012/S02, D043).

``SOURCES`` maps each generator of ``seams_gen.__main__.GENERATORS`` to a
``sources(trig, out)`` returning ``{relative file name: IRIs}``, with exactly
the file names the generator returns for the same model and, per file, the
full IRIs of the elements it renders, sorted and de-duplicated. ``seams
generate`` records them in seams.lock. They are read the way the generators
read the model, through their own extract functions and the seams views
(D036), so a missing or ambiguous fact raises the same ``GeneratorError``:

- ``htmx``: a page lists the page and its components; a fragment partial the
  component it renders and the operations that render it (unioned when two
  pages name the same partial); a task form partial the form, the user task
  completed on it, the shape the form writes and the shape the task reads.
- ``fastapi``: the serving container, the processes it executes and the
  operation or channel of each endpoint.
- ``compose``: the arch:System and each of its containers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from seams import PROC, Model, ProcessElement, load
from seams import Component as ComponentView

from ._views import only, optional, view_errors
from .compose import extract_compose
from .fastapi import extract_routes, route_module
from .htmx import extract_page, generate_pages

Sources = dict[str, tuple[str, ...]]


def _iris(model: Model, terms: Iterable[object]) -> tuple[str, ...]:
    """Each curie or IRI expanded to its full IRI, sorted and de-duplicated."""
    return tuple(sorted({str(model.curie(t)) for t in terms}))


def _htmx(trig: Path, out: Path) -> Sources:
    model = load(trig)
    names = generate_pages(model).keys()  # the generator's own checks and file names
    found: dict[str, set[str]] = {}

    def add(name: str, terms: Iterable[object]) -> None:
        found.setdefault(name, set()).update(str(model.curie(t)) for t in terms)

    with view_errors():
        tasks = {
            task.completed_on.iri: task
            for task in model.views.all(ProcessElement, PROC.UserTask)
            if task.completed_on is not None
        }
        for view in model.interfaces.served_pages():
            page = extract_page(model, view.iri)
            add(f"{page.id}.html", [view.iri, *(c.curie for c in page.components)])
            by_id = {c.id: c for c in page.components + page.screen_components}
            for fr in page.fragments:
                add(fr.name, [by_id[fr.component].curie, *fr.operations])
            if not page.landmark:
                continue
            for tf in page.task_forms:
                form_iri = model.curie(tf.curie)
                form = model.views.intern(ComponentView, form_iri)
                reads = optional(tasks[form_iri].reads)
                shapes = [only(form.writes).iri] + ([reads.iri] if reads is not None else [])
                add(tf.name, [form_iri, tf.task, *shapes])
    return {name: tuple(sorted(found[name])) for name in names}


def _fastapi(trig: Path, out: Path) -> Sources:
    name, _ = route_module(trig)  # the generator's one-serving-container check
    model = load(trig)
    module = next(m for m in extract_routes(model).modules if m.file_name == name)
    with view_errors():
        container = model.architecture.containers().by_iri(model.curie(module.curie))
        processes = [p.iri for p in container.executes if p in model.processes]
    return {name: _iris(model, [module.curie, *processes, *(e.curie for e in module.endpoints)])}


def _compose(trig: Path, out: Path) -> Sources:
    model = load(trig)
    extract_compose(model, out)  # the generator's checks: one system with containers
    with view_errors():
        system = model.architecture.systems()[0]
        containers = [c.iri for c in system.containers]
    return {"compose.yaml": _iris(model, [system.iri, *containers])}


# generator name -> sources(trig, out) -> {relative file name: full IRIs}
SOURCES: dict[str, Callable[[Path, Path], Sources]] = {
    "htmx": _htmx,
    "fastapi": _fastapi,
    "compose": _compose,
}


def output_sources(name: str, trig: Path, out: Path) -> Sources:
    """{relative file name: full IRIs} of generator ``name`` for the model ``trig``."""
    return SOURCES[name](trig, out)


__all__ = ["SOURCES", "Sources", "output_sources"]
