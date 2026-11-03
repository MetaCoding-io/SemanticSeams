"""``seams propose``: an LLM draft of a handler body, gated by its acceptance tests (M022/S04, backlog C4).

``build_prompt`` is the deterministic half. For a ``proc:ServiceTask`` (a
BPMN id, CURIE or IRI) it reads, through public names only:

- the task's ``seams.context_for`` manifest: every item's kind, ref, hash and
  content (the container item carries binding ``deploy:key``s, never values);
- the stub ``seams_gen.stubs`` renders for the handlers module that holds the
  ``comm:PythonHandler`` of an operation the task ``seam:invokes``;
- the acceptance tests ``seams_gen.acceptance`` renders for that module.

and fills the versioned template ``prompts/draft-v<N>.txt`` with them. Every
model-derived text goes in a DATA block: a backtick fence one longer than the
longest backtick run in the text, so no label, comment or fragment can close
it, under a template sentence saying it is data, not instructions. Items are
in manifest order, so the same model gives the same prompt, byte for byte.
Paths are relative to the project root; no value of a binding is read.

A model that cannot be loaded raises ProjectError; an unknown task, a missing
context hop or a task whose operations have no ``comm:PythonHandler`` raises
ResolutionError naming the fact; a stub or acceptance fault, GeneratorError.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

import seams
from seams import SEAM, ModelGraph, ResolutionError

from seams_gen.acceptance import extract_acceptance, render_acceptance
from seams_gen.stubs import DEFAULT_HANDLERS, StubModule, extract_stubs, render_module

from .project import Project, ProjectError, resolve_model

TEMPLATE_NAME = "draft"
TEMPLATE_VERSION = 1
TEMPLATE_FILE = f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}.txt"
ACCEPTANCE_GENERATOR = "acceptance"

_BACKTICKS = re.compile(r"`+")


@dataclass(frozen=True)
class Prompt:
    """An assembled prompt. ``template`` is ``<name>-v<version>``;
    ``handler_path`` the handlers module (POSIX, relative to the project root)
    and ``module`` the same path within the handlers package; ``acceptance``
    the acceptance file name and ``acceptance_text`` its content."""

    text: str
    template: str
    task: str
    context_hash: str
    handler_path: str
    module: str
    acceptance: str
    acceptance_text: str


def quote(label: str, text: str) -> str:
    """``text`` as a DATA block that no backtick run inside it can close."""
    longest = max((len(m.group()) for m in _BACKTICKS.finditer(text)), default=0)
    fence = "`" * max(3, longest + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{fence}DATA {label}\n{body}{fence}"


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _module_for(stubs_modules: tuple[StubModule, ...], task: str) -> StubModule:
    found = [m for m in stubs_modules if any(task in fn.tasks for fn in m.functions)]
    if len(found) != 1:
        detail = (
            "no operation it invokes is implemented by a comm:PythonHandler"
            if not found
            else "its operations' comm:PythonHandlers lie in several modules: " + ", ".join(m.path for m in found)
        )
        raise ResolutionError(task, SEAM.invokes, detail)
    return found[0]


def _acceptance_path(project: Project, file: str) -> str:
    target = next((g for g in project.generators if g.name == ACCEPTANCE_GENERATOR), None)
    return _relative(target.out / file, project.root) if target is not None else file


def build_prompt(project: Project, model: Path | None, task: str) -> Prompt:
    """The draft prompt for service task ``task`` of the project's model."""
    trig = resolve_model(project, model)
    try:
        graph = ModelGraph(trig, seams.load(trig).ds)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    manifest = seams.context_for(graph, task)
    iri = str(manifest.task)
    module = _module_for(extract_stubs(graph).modules, iri)
    tests = extract_acceptance(graph)
    acceptance = next(m for m in tests.modules if m.path == module.path)
    acceptance_text = render_acceptance(tests)[acceptance.file]
    handler_path = _relative(trig.parent / DEFAULT_HANDLERS / module.path, project.root)
    acceptance_path = _acceptance_path(project, acceptance.file)

    items = "\n\n".join(f"{i.kind} {i.ref} {i.hash}\n{quote(i.kind, i.content)}" for i in manifest.items)
    source = resources.files(__package__).joinpath("prompts", TEMPLATE_FILE).read_text(encoding="utf-8")
    text = Template(source).substitute(
        task=iri,
        handler_path=handler_path,
        context_hash=manifest.context_hash,
        items=items,
        stub=quote("stub", render_module(module)),
        acceptance_path=acceptance_path,
        acceptance=quote("acceptance", acceptance_text),
    )
    return Prompt(
        text=text,
        template=f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}",
        task=iri,
        context_hash=manifest.context_hash,
        handler_path=handler_path,
        module=module.path,
        acceptance=acceptance.file,
        acceptance_text=acceptance_text,
    )
