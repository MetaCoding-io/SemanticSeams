"""``seams draft-generator``: a generator an LLM drafts from a reference output, kept when its golden test passes (M025/S02, backlog R3, ADR-0029).

``build_prompt`` is the deterministic half. It fills the versioned template
``prompts/draft-generator-v<N>.txt`` with three DATA blocks (``propose.quote``):
the reference file verbatim, the model's names (one ``IRI<TAB>label`` line per
``rdfs:label`` of the loaded model, sorted) and the package module
``seams new-generator`` scaffolds for the reference. The same reference and
model give the same prompt, byte for byte.

``parse_answer`` reads the provider's answer: one JSON object with exactly the
string keys ``extract``, ``template`` and ``golden`` (one fenced code block
around it is stripped). ``check_template`` refuses a template line that holds
logic (anything but ``[[ name ]]``, ``[[ name.attr ]]``, ``[% for x in xs %]``
and ``[% endfor %]``) or restates a model label that occurs in the reference.
``assemble`` is the scaffold with the answer's extract step, template and
golden in place of its own, and ``run_tests`` runs its tests in a scratch copy
with ``SEAMS_MODEL`` set to the project's model. Every refusal is a
DraftGeneratorError naming the key, line, label or failed tests.

``draft_generator`` asks the provider (``propose.call_provider``) unless an
accepted answer for the same reference, model, template, provider and LLM model
label (``--llm-model``, else ``[propose] model``) is cached
in ``.seams/generator-drafts/<key>.json`` below the project root, checks it,
and only then caches it and writes the package with ``new_generator.write``.
Nothing is written on failure.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import cast

import seams
from rdflib import RDFS, Literal

from seams_gen.testing import MARKER

from . import new_generator
from .new_generator import COMMENT, NewGeneratorError
from .project import Project, ProjectError, resolve_model
from .propose import TEST_TIMEOUT, ProposeError, call_provider, extract_draft, quote, resolve_llm_model

TEMPLATE_NAME = "draft-generator"
TEMPLATE_VERSION = 1
TEMPLATE_FILE = f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}.txt"
CACHE_DIR = Path(".seams") / "generator-drafts"
KEYS = ("extract", "golden", "template")
# Names the scaffold's package module defines around the extract step.
RESERVED = frozenset({"OUTPUT", "TEMPLATES", "generator", "render", "sources"})

_NAME = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
_ALLOWED_TAG = re.compile(rf"\[\[\s*{_NAME}\s*\]\]|\[%\s*for\s+[A-Za-z_]\w*\s+in\s+{_NAME}\s*%\]|\[%\s*endfor\s*%\]")
_OPENERS = ("[[", "[%", "[#")
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)


class DraftGeneratorError(Exception):
    """The draft cannot be accepted, or the provider failed; nothing was written.
    ``failures`` names the scratch tests that failed, if that was the reason."""

    def __init__(self, message: str, failures: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.failures = failures


@dataclass(frozen=True)
class Draft:
    """The answer's three texts."""

    extract: str
    template: str
    golden: str


@dataclass(frozen=True)
class GeneratorPrompt:
    """An assembled prompt. ``template`` is ``<name>-v<version>``; ``names`` the
    model's (IRI, label) pairs it quotes, sorted; ``reference_hash`` the sha256
    of the reference file's bytes."""

    text: str
    template: str
    model_hash: str
    reference_hash: str
    names: tuple[tuple[str, str], ...]

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DraftedGenerator:
    """What ``draft_generator`` did: the prompt's hash, whether the answer came
    from the cache, the package files written, sorted, and the LLM model label
    the provider was asked for, if any."""

    name: str
    template: str
    provider: str
    prompt_sha256: str
    cache_hit: bool
    written: tuple[Path, ...]
    llm_model: str | None = None


def _scaffold(name: str, reference: Path, extract: str | None = None) -> dict[str, str]:
    try:
        return new_generator.scaffold(name, reference, extract)
    except NewGeneratorError as err:
        raise DraftGeneratorError(str(err)) from None


def model_names(model: seams.Model) -> tuple[tuple[str, str], ...]:
    """Every (IRI, label) of an ``rdfs:label`` in the model, sorted."""
    pairs = {
        (str(subject), str(label))
        for subject, label in model.ds.subject_objects(RDFS.label)
        if isinstance(label, Literal) and str(label).strip()
    }
    return tuple(sorted(pairs))


def build_prompt(name: str, reference: Path, model: seams.Model) -> GeneratorPrompt:
    """The draft-generator prompt for generator ``name`` from ``reference`` on ``model``."""
    files = _scaffold(name, reference)
    package = f"seams_{name}"
    names = model_names(model)
    source = resources.files(__package__).joinpath("prompts", TEMPLATE_FILE).read_text(encoding="utf-8")
    text = Template(source).substitute(
        model_hash=model.hash,
        output=reference.name,
        name=name,
        package=package,
        comment=COMMENT[reference.suffix].strip(),
        reference=quote(f"reference {reference.name}", files[f"{package}/templates/{reference.name}"]),
        names=quote("names", "".join(f"{iri}\t{label}\n" for iri, label in names)),
        module=quote("package", files[f"{package}/__init__.py"]),
    )
    return GeneratorPrompt(
        text=text,
        template=f"{TEMPLATE_NAME}-v{TEMPLATE_VERSION}",
        model_hash=model.hash,
        reference_hash=hashlib.sha256(reference.read_bytes()).hexdigest(),
        names=names,
    )


def parse_answer(text: str) -> Draft:
    """The answer's extract step, template and golden; DraftGeneratorError naming
    the key when the answer is not one JSON object of exactly KEYS, all strings."""
    try:
        data: object = json.loads(extract_draft(text))
    except ValueError as err:
        raise DraftGeneratorError(f"the answer is not JSON: {err}") from None
    if not isinstance(data, dict):
        raise DraftGeneratorError(f"the answer is not a JSON object with the keys {', '.join(KEYS)}")
    answer = cast(dict[str, object], data)
    for key in KEYS:
        if key not in answer:
            raise DraftGeneratorError(f"the answer has no `{key}`")
        if not isinstance(answer[key], str):
            raise DraftGeneratorError(f"the answer's `{key}` is not a string")
    extra = sorted(set(answer) - set(KEYS))
    if extra:
        raise DraftGeneratorError(f"the answer has the unknown key `{extra[0]}` (keys: {', '.join(KEYS)})")
    return Draft(extract=str(answer["extract"]), template=str(answer["template"]), golden=str(answer["golden"]))


def _bound(node: ast.stmt) -> list[tuple[str, int]]:
    """The top-level names ``node`` binds, with its line."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [(node.name, node.lineno)]
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [((alias.asname or alias.name).split(".")[0], node.lineno) for alias in node.names]
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return [(n.id, node.lineno) for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


def check_extract(source: str) -> None:
    """The extract step parses, defines ``extract`` at the top level and none of
    the names the scaffold's module defines around it."""
    try:
        tree = ast.parse(source)
    except SyntaxError as err:
        raise DraftGeneratorError(f"the answer's `extract` line {err.lineno}: not Python: {err.msg}") from None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            raise DraftGeneratorError(
                f"the answer's `extract` line {node.lineno}: a __future__ import cannot follow the package's imports"
            )
        for bound, line in _bound(node):
            if bound in RESERVED:
                raise DraftGeneratorError(
                    f"the answer's `extract` line {line}: defines `{bound}`, which the scaffold's package owns"
                )
    if not any(isinstance(node, ast.FunctionDef) and node.name == "extract" for node in tree.body):
        raise DraftGeneratorError("the answer's `extract` defines no top-level `def extract(trig, out)`")


def check_golden(golden: str) -> None:
    """Every non-blank line of the golden carries a producibility marker."""
    for number, line in enumerate(golden.split("\n"), start=1):
        if line.strip() and not MARKER.search(line):
            raise DraftGeneratorError(
                f"the answer's `golden` line {number}: carries no [fixed] or [graph: ...] marker: {line!r}"
            )


def _occurs(label: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(label)}(?!\w)", text) is not None


def check_template(template: str, reference: str, names: Iterable[tuple[str, str]]) -> None:
    """The template holds no logic and restates no model label that occurs in the reference."""
    restated: dict[str, str] = {}
    # Longest label first, so a line is reported by the whole label it restates.
    for iri, label in sorted(names, key=lambda pair: (-len(pair[1]), pair[1], pair[0])):
        if label not in restated and _occurs(label, reference):
            restated[label] = iri
    for number, line in enumerate(template.split("\n"), start=1):
        rest = _ALLOWED_TAG.sub("", line)
        if any(opener in rest for opener in _OPENERS):
            raise DraftGeneratorError(
                f"template line {number}: holds logic a template may not "
                f"(only [[ name ]], [% for x in xs %] and [% endfor %]): {line!r}"
            )
        for label, iri in restated.items():
            if _occurs(label, rest):
                raise DraftGeneratorError(
                    f"template line {number}: restates the model label {label!r} of {iri}; read it in extract"
                )


def assemble(name: str, reference: Path, draft: Draft) -> dict[str, str]:
    """The scaffold for ``reference`` with the draft's extract step, template and golden."""
    files = _scaffold(name, reference, draft.extract)
    package = f"seams_{name}"
    files[f"{package}/templates/{reference.name}"] = draft.template
    files[f"tests/golden/{reference.name}"] = draft.golden
    return files


def _scrub(text: str, root: Path) -> str:
    return text.replace(f"{root}{os.sep}", "").replace(str(root), ".")


def run_tests(files: dict[str, str], trig: Path) -> None:
    """Run the package's tests in a scratch copy, on the model at ``trig``;
    DraftGeneratorError with one line per failed test unless pytest exits 0."""
    with tempfile.TemporaryDirectory(prefix="seams-draft-generator-") as tmp:
        scratch = Path(tmp) / "package"
        new_generator.write(scratch, files)
        path = [str(scratch), *([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(path), "SEAMS_MODEL": str(trig.resolve())}
        argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
        try:
            done = subprocess.run(
                argv, cwd=scratch, env=env, capture_output=True, text=True, timeout=TEST_TIMEOUT, check=False
            )
        except subprocess.TimeoutExpired:
            raise DraftGeneratorError(f"the drafted generator's tests ran over {TEST_TIMEOUT}s") from None
        if done.returncode == 0:
            return
        output = _scrub(done.stdout + done.stderr, Path(tmp))
    found = _FAILED.findall(output)
    failures = tuple(sorted({test for test, _ in found}))
    lines = sorted({f"{test} - {detail}" if detail else test for test, detail in found})
    if not lines:
        last = output.strip().splitlines()[-1:] or ["no output"]
        failures = (f"pytest exited {done.returncode}",)
        lines = [f"pytest exited {done.returncode}: {last[0]}"]
    raise DraftGeneratorError("the drafted generator's tests failed:\n" + "\n".join(lines), failures)


def cache_key(reference_hash: str, model_hash: str, template: str, provider: str, llm_model: str | None = None) -> str:
    """The cache file stem. ``llm_model`` joins the key only when set, so keys
    made without one are unchanged (ADR-0020 amendment)."""
    parts = (reference_hash, model_hash, template, provider)
    return hashlib.sha256("\n".join(parts if llm_model is None else (*parts, llm_model)).encode("utf-8")).hexdigest()


def _accept(name: str, reference: Path, prompt: GeneratorPrompt, draft: Draft, trig: Path) -> dict[str, str]:
    """The package files of an accepted draft (ADR-0029 section 5)."""
    check_extract(draft.extract)
    check_golden(draft.golden)
    reference_text = reference.read_bytes().decode("utf-8")
    check_template(draft.template, reference_text, prompt.names)
    files = assemble(name, reference, draft)
    run_tests(files, trig)
    return files


def draft_generator(
    project: Project,
    name: str,
    reference: Path,
    provider: str | None = None,
    out: Path | None = None,
    force: bool = False,
    model: Path | None = None,
    llm_model: str | None = None,
) -> DraftedGenerator:
    """Draft, check and (on acceptance) write generator ``name`` from ``reference``
    on the project's model. ``force`` lets the package's files replace files of
    the same path in a non-empty ``out``. ``llm_model`` is the LLM model label,
    else the project's ``[propose] model`` (ADR-0020 amendment)."""
    provider = provider if provider is not None else project.provider
    if provider is None or not provider.strip():
        raise ProjectError(f"no provider: set `[propose] provider` in {project.path} or pass --provider")
    llm_model = resolve_llm_model(project, llm_model)
    _scaffold(name, reference)
    out = new_generator.default_out(name) if out is None else out
    if not force:
        try:
            new_generator.check_out(out)
        except NewGeneratorError as err:
            raise DraftGeneratorError(f"{err}; pass --force to write into it") from None
    elif out.exists() and not out.is_dir():
        raise DraftGeneratorError(f"{out}: exists and is not a directory")
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    prompt = build_prompt(name, reference, loaded)
    key = cache_key(prompt.reference_hash, prompt.model_hash, prompt.template, provider, llm_model)
    cached = project.root / CACHE_DIR / f"{key}.json"
    cache_hit = cached.is_file()
    if cache_hit:
        response = cached.read_text(encoding="utf-8")
    else:
        try:
            response = call_provider(provider, prompt.text, "answer", model=llm_model)
        except ProposeError as err:
            raise DraftGeneratorError(str(err)) from None
    draft = parse_answer(response)
    files = _accept(name, reference, prompt, draft, trig)
    if not cache_hit:
        record = {"extract": draft.extract, "golden": draft.golden, "template": draft.template}
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written = new_generator.write(out, files)
    return DraftedGenerator(
        name=name,
        template=prompt.template,
        provider=provider,
        prompt_sha256=prompt.sha256,
        cache_hit=cache_hit,
        written=tuple(written),
        llm_model=llm_model,
    )


__all__ = [
    "CACHE_DIR",
    "Draft",
    "DraftGeneratorError",
    "DraftedGenerator",
    "GeneratorPrompt",
    "assemble",
    "build_prompt",
    "cache_key",
    "check_extract",
    "check_golden",
    "check_template",
    "draft_generator",
    "model_names",
    "parse_answer",
    "run_tests",
]
