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

``propose`` is the other half (D059). It sends the prompt on stdin to the
provider command (``--provider`` or seams.toml ``[propose] provider``; split
with shlex, never a shell) and reads the draft from stdout, stripping one
fenced code block around it. An LLM model label (``--llm-model`` or seams.toml
``[propose] model``, D063) reaches the provider as env ``SEAMS_LLM_MODEL``. The
raw response is cached in
``.seams/drafts/<sha256(context hash, template, provider[, model])>.py`` under
the project root, so an unchanged context does not call the provider again. The
draft is written at the handler path of a scratch copy of the project, the
module's acceptance tests run there with pytest in a subprocess, and only when
they pass is it written to the project's handlers module; an existing module is
kept unless ``force``. On acceptance the draft's record (task, path, context
hash, template, provider, model when set, sha256) is upserted into seams.lock (S05); the lock
is read before anything is written, so a malformed one raises LockError and
writes nothing. Nothing else is written outside the handlers directory.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

import seams
from seams import SEAM, ModelGraph, ResolutionError

from seams_gen.acceptance import extract_acceptance, render_acceptance
from seams_gen.stubs import DEFAULT_HANDLERS, StubModule, extract_stubs, render_module

from .lockfile import Draft, lock_path, read_lock, render_lock, with_draft
from .project import Project, ProjectError, resolve_model

TEMPLATE_NAME = "draft"
TEMPLATE_VERSION = 1
TEMPLATE_FILE = f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}.txt"
ACCEPTANCE_GENERATOR = "acceptance"

CACHE_DIR = Path(".seams") / "drafts"
PROVIDER_TIMEOUT = 600
TEST_TIMEOUT = 600
LLM_MODEL_ENV = "SEAMS_LLM_MODEL"

_BACKTICKS = re.compile(r"`+")
_FENCED = re.compile(r"\A\s*(`{3,})[^\n`]*\n(.*?\n)\1\s*\Z", re.DOTALL)
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)
_SCRATCH_IGNORE = shutil.ignore_patterns(".seams", "__pycache__", ".pytest_cache")


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
    handler_path = _relative(seams.model_dir(trig) / DEFAULT_HANDLERS / module.path, project.root)
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


class ProposeError(Exception):
    """The provider failed or the draft cannot be accepted; the message says why."""


@dataclass(frozen=True)
class Proposal:
    """What ``propose`` did. ``failures`` names the failing acceptance tests;
    ``written`` is the handlers module written (relative to the project root) or
    None, and ``sha256`` the draft's hash, for S05's record."""

    task: str
    context_hash: str
    template: str
    provider: str
    llm_model: str | None
    cache_hit: bool
    passed: bool
    failures: tuple[str, ...]
    written: str | None
    sha256: str
    output: str


def extract_draft(response: str) -> str:
    """``response`` without one fenced code block around it."""
    match = _FENCED.match(response)
    return match.group(2) if match else response


def cache_key(context_hash: str, template: str, provider: str, model: str | None = None) -> str:
    """The cache file stem. ``model`` joins the key only when set, so keys made
    without one are unchanged (D063)."""
    parts = (context_hash, template, provider) if model is None else (context_hash, template, provider, model)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def resolve_llm_model(project: Project, llm_model: str | None) -> str | None:
    """The LLM model label: ``llm_model``, else the project's ``[propose] model``,
    else None. ProjectError when the label is empty."""
    llm_model = llm_model if llm_model is not None else project.llm_model
    if llm_model is not None and not llm_model.strip():
        raise ProjectError("the LLM model name is empty: pass a non-empty --llm-model")
    return llm_model


def call_provider(provider: str, text: str, answer: str = "draft", model: str | None = None) -> str:
    """The provider command's answer to the prompt ``text``: ``provider`` split
    with shlex (never a shell), ``text`` on stdin, the answer on stdout, and
    ``model``, when given, in env LLM_MODEL_ENV (an inherited one is dropped, so
    the cache key always names the model asked for). ProposeError when the command
    is empty or missing, runs over PROVIDER_TIMEOUT, exits non-zero or prints
    no ``answer``."""
    argv = shlex.split(provider)
    if not argv:
        raise ProposeError("the provider command is empty")
    env = {key: value for key, value in os.environ.items() if key != LLM_MODEL_ENV}
    if model is not None:
        env[LLM_MODEL_ENV] = model
    try:
        done = subprocess.run(
            argv,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=PROVIDER_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as err:
        raise ProposeError(f"provider {provider!r}: command not found: {err.filename}") from err
    except subprocess.TimeoutExpired as err:
        raise ProposeError(f"provider {provider!r}: no answer in {PROVIDER_TIMEOUT}s") from err
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()[-1:] or ["no stderr"]
        raise ProposeError(f"provider {provider!r} exited {done.returncode}: {detail[0]}")
    if not done.stdout.strip():
        raise ProposeError(f"provider {provider!r} returned no {answer}")
    return done.stdout


def _run_acceptance(project: Project, prompt: Prompt, draft: str) -> tuple[bool, tuple[str, ...], str]:
    with tempfile.TemporaryDirectory(prefix="seams-propose-") as tmp:
        scratch = Path(tmp) / "project"
        shutil.copytree(project.root, scratch, ignore=_SCRATCH_IGNORE, symlinks=True)
        (scratch / prompt.handler_path).parent.mkdir(parents=True, exist_ok=True)
        (scratch / prompt.handler_path).write_text(draft, encoding="utf-8")
        test = scratch / _acceptance_path(project, prompt.acceptance)
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_text(prompt.acceptance_text, encoding="utf-8")
        argv = [sys.executable, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", str(test)]
        try:
            done = subprocess.run(argv, cwd=scratch, capture_output=True, text=True, timeout=TEST_TIMEOUT, check=False)
        except subprocess.TimeoutExpired as err:
            raise ProposeError(f"the acceptance tests ran over {TEST_TIMEOUT}s") from err
        output = done.stdout.replace(str(scratch) + os.sep, "")
        failures = tuple(sorted({m.split("::")[-1] for m in _FAILED.findall(output)}))
        if done.returncode != 0 and not failures:
            failures = (f"pytest exited {done.returncode}",)
        return done.returncode == 0, failures, output


def _handlers_target(project: Project, model: Path | None, prompt: Prompt) -> Path:
    handlers = seams.model_dir(resolve_model(project, model)) / DEFAULT_HANDLERS
    target = (project.root / prompt.handler_path).resolve()
    if not target.is_relative_to(handlers) or target == handlers:
        raise ProjectError(f"{prompt.handler_path}: not inside the handlers directory {handlers}")
    return target


def propose(
    project: Project,
    model: Path | None,
    task: str,
    provider: str | None = None,
    force: bool = False,
    llm_model: str | None = None,
) -> Proposal:
    """Draft, test and (on pass) write the handlers module of service task ``task``.
    ``model`` is the TriG model path; ``llm_model`` the LLM model label, else
    the project's ``[propose] model``."""
    provider = provider if provider is not None else project.provider
    if provider is None or not provider.strip():
        raise ProjectError(f"no provider: set `[propose] provider` in {project.path} or pass --provider")
    llm_model = resolve_llm_model(project, llm_model)
    prompt = build_prompt(project, model, task)
    target = _handlers_target(project, model, prompt)
    lock = read_lock(project)
    if target.exists() and not force:
        raise ProjectError(f"{prompt.handler_path}: already exists; pass --force to replace it")
    cached = project.root / CACHE_DIR / f"{cache_key(prompt.context_hash, prompt.template, provider, llm_model)}.py"
    cache_hit = cached.is_file()
    if cache_hit:
        response = cached.read_text(encoding="utf-8")
    else:
        response = call_provider(provider, prompt.text, model=llm_model)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(response, encoding="utf-8")
    draft = extract_draft(response)
    passed, failures, output = _run_acceptance(project, prompt, draft)
    digest = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    if passed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft, encoding="utf-8")
        record = Draft(
            prompt.task, prompt.handler_path, prompt.context_hash, prompt.template, provider, digest, llm_model
        )
        text = render_lock(with_draft(project, resolve_model(project, model), lock, record))
        with open(lock_path(project), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return Proposal(
        task=prompt.task,
        context_hash=prompt.context_hash,
        template=prompt.template,
        provider=provider,
        llm_model=llm_model,
        cache_hit=cache_hit,
        passed=passed,
        failures=failures,
        written=prompt.handler_path if passed else None,
        sha256="sha256:" + digest,
        output=output,
    )
