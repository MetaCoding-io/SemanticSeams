"""Write-back from output (backlog T4, M021/S01, ADR-0019, ADR-0017).

A person edits one line of a generated output in the generation view. This
module turns that edit into a one-triple patch to the model, or refuses it:

- ``locate`` diffs the old and new line to the changed span, and among the
  literals of the line's trace terms (``TraceLine.terms``, as subjects) finds the
  quads whose value is written on the old line over the whole span. Exactly one
  is required; none or several is a ``Refusal`` listing the candidates, sorted.
- ``draft`` is the patch: remove that quad, add the same subject, predicate and
  graph with the edited value, keeping the literal's language and datatype.
- ``check`` (``regenerate``, then the comparison) copies the model files and payloads to a temporary directory laid
  out as the project is (generated paths are relative to the model), applies the
  patch there through ``seams_edit.apply`` and regenerates in memory with
  ``seams_cli.generate_project``. The regenerated output must equal the old
  output with the line replaced, every embedded model hash read as the new one
  (the hash covers the model bytes, so every output's hash lines change with any
  edit). Otherwise it is a ``Refusal`` naming the first differing line. The real
  model files are never opened for writing.
- ``effects`` lists every other output line the patch changes, sorted, beyond
  the hash lines.

``write_back`` runs the four and logs each drafted and refused write-back with
its subject, predicate and files. Nothing here applies the patch to the real
model: the viewer does that through ``seams_edit`` in edit mode. Every path in a
``WriteBack`` is project-relative posix, as the lock writes them.
"""

from __future__ import annotations

import difflib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import seams
from rdflib import Dataset, Literal, URIRef
from rdflib.term import Node
from seams import SeamsError
from seams_cli import Generated, ProjectError, generate_project, load_project
from seams_cli.project import PROJECT_FILE

from seams_edit import Patch, PatchError, Quad, apply
from seams_edit.patch import term_text
from viewer.generation import SIDECAR_SUFFIX, GenerationIndex

logger = logging.getLogger("uvicorn.error")

# The longest line text a refusal quotes before eliding it.
_QUOTE = 80


class Refusal(Exception):
    """A write-back that is not drafted or not safe to apply.

    ``subject`` and ``predicate`` name the fact (the model quad, or the output line
    when no quad was found), and ``detail`` says why.
    """

    def __init__(self, subject: object, predicate: object, detail: str) -> None:
        self.subject = str(subject)
        self.predicate = str(predicate)
        self.detail = detail
        super().__init__(f"{self.subject}: {self.predicate}: {detail}")


@dataclass(frozen=True)
class Located:
    """The one model literal behind an edited span, and its edited value."""

    quad: Quad  # (subject, predicate, old literal, graph)
    new: Literal


@dataclass(frozen=True)
class Regenerated:
    """What ``check`` produced: project-relative path to regenerated text (sidecars
    excluded), the model files the patch changes, and the old and new model hashes."""

    texts: dict[str, str]
    files: tuple[str, ...]
    old_hash: str
    new_hash: str


@dataclass(frozen=True)
class Effect:
    output: str  # project-relative posix path
    line: int  # 1-based line of the old output
    before: str  # "" for a line the patch adds
    after: str  # "" for a line the patch removes


@dataclass(frozen=True)
class WriteBack:
    output: str
    line: int
    before: str  # the output line as generated
    after: str  # the line as edited
    subject: str
    predicate: str
    graph: str
    old: Literal
    new: Literal
    patch: Patch
    files: tuple[str, ...]  # project-relative model files the patch changes
    effects: tuple[Effect, ...]


def _quote(text: str) -> str:
    return repr(text if len(text) <= _QUOTE else text[: _QUOTE - 1] + "…")


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _span(old: str, new: str) -> tuple[int, int]:
    """(start, end) in ``old`` of the text the edit replaced, by common prefix and suffix."""
    limit = min(len(old), len(new))
    start = 0
    while start < limit and old[start] == new[start]:
        start += 1
    tail = 0
    while tail < limit - start and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    return start, len(old) - tail


def _covering(value: str, line: str, start: int, end: int) -> int | None:
    """The start of an occurrence of ``value`` in ``line`` covering [start, end), else None."""
    at = line.find(value)
    while at != -1:
        if at <= start and end <= at + len(value):
            return at
        at = line.find(value, at + 1)
    return None


def locate(index: GenerationIndex, ds: Dataset, output: str, line: int, new_text: str) -> Located:
    """The one literal of line ``line``'s trace terms written over the span the edit changes."""
    where = f"{output}:{line}"
    shown = index.output(output)
    if shown is None or shown.text is None:
        raise Refusal(where, "output", "the generation index has no readable output of this name")
    texts = _lines(shown.text)
    if not 1 <= line <= len(texts):
        raise Refusal(where, "line", f"the output has {len(texts)} lines")
    if "\n" in new_text or "\r" in new_text:
        raise Refusal(where, "line", "a write-back edits one line; the edited text has a line break")
    old_text = texts[line - 1]
    if new_text == old_text:
        raise Refusal(where, "line", "the edited line is the same as the generated one")
    traced = shown.line(line)
    if traced is None or not traced.terms:
        raise Refusal(where, "terms", "the trace names no model term behind this line")
    start, end = _span(old_text, new_text)
    grown = len(new_text) - len(old_text)
    found: list[tuple[Quad, Literal]] = []
    for term in traced.terms:
        for s, p, o, g in ds.quads((URIRef(term), None, None, None)):
            if not isinstance(o, Literal) or not str(o):
                continue
            at = _covering(str(o), old_text, start, end)
            if at is None:
                continue
            value = new_text[at : at + len(str(o)) + grown]
            assert g is not None  # a Dataset quad always names its graph
            found.append(((s, p, o, g), Literal(value, lang=o.language, datatype=o.datatype)))
    found.sort(key=lambda c: tuple(term_text(t) for t in c[0]))
    if not found:
        raise Refusal(
            where,
            "terms",
            f"no literal of the line's terms ({', '.join(traced.terms)}) is written over the edited "
            f"span {_quote(old_text[start:end])}",
        )
    if len(found) > 1:
        listed = "; ".join(f"{term_text(q[0])} {term_text(q[1])} {term_text(q[2])}" for q, _ in found)
        raise Refusal(where, "terms", f"{len(found)} literals are written over the edited span: {listed}")
    quad, new = found[0]
    return Located(quad=quad, new=new)


def draft(located: Located) -> Patch:
    """The one-triple replace: the old quad removed, its value edited, same graph."""
    s, p, _old, g = located.quad
    return Patch(adds=[(s, p, located.new, g)], removes=[located.quad])


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def _rebase_term(term: Node, old: str, new: str) -> Node:
    if isinstance(term, URIRef) and term.startswith(old):
        return URIRef(new + term[len(old) :])
    return term


def _rebase(patch: Patch, old: Path, new: Path) -> Patch:
    """``patch`` with file IRIs under ``old`` moved under ``new``, as the copied model reads them."""
    a, b = old.as_uri() + "/", new.as_uri() + "/"

    def quad(q: Quad) -> Quad:
        s, p, o, g = (_rebase_term(t, a, b) for t in q)
        return s, p, o, g

    return Patch(adds=[quad(q) for q in patch.adds], removes=[quad(q) for q in patch.removes])


def first_difference(output: str, expected: str, actual: str) -> str:
    """The refusal detail naming the first line where ``actual`` differs from ``expected``."""
    want, got = _lines(expected), _lines(actual)
    for number, (w, a) in enumerate(zip(want, got, strict=False), start=1):
        if w != a:
            return f"regenerating gives {output} line {number} as {_quote(a)}, not {_quote(w)}"
    if len(want) != len(got):
        return f"regenerating gives {output} {len(got)} lines, not {len(want)}"
    return f"regenerating gives {output} with different line endings"


def regenerate(project_dir: Path, model_path: Path, patch: Patch, subject: object, predicate: object) -> Regenerated:
    """Regenerate in memory with ``patch`` applied to a temporary copy of the model.
    A refusal for a model that cannot be read or generated names ``subject`` and
    ``predicate`` (the fact the patch is about)."""
    try:
        project = load_project(project_dir)
        model = seams.load(model_path)
        payloads = [path for _rel, path in model.payloads()]
    except ProjectError as err:
        raise Refusal(PROJECT_FILE, "project", str(err)) from err
    except (SeamsError, OSError) as err:
        raise Refusal(subject, predicate, f"the model cannot be read: {err}") from err
    outs = [Path(os.path.normpath(t.out)) for t in project.generators]
    sources = [*model.files, *payloads]
    anchor = Path(os.path.commonpath([project.root, model.path, *outs, *sources]))

    with tempfile.TemporaryDirectory(prefix="seams-writeback-") as scratch:
        tmp = Path(scratch).resolve()

        def moved(path: Path) -> Path:
            return tmp / os.path.relpath(path, anchor)

        for source in sources:
            moved(source).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, moved(source))
        tmp_model = moved(model.path)
        tmp_root = moved(project.root)
        tmp_files = [moved(f) for f in model.files]
        old_hash = seams.load(tmp_model).hash
        try:
            record = apply(tmp_files, _rebase(patch, anchor, tmp))
        except PatchError as err:
            raise Refusal(err.subject, err.predicate, f"the write path refuses the patch: {err.detail}") from err
        new_hash = seams.load(tmp_model).hash
        rebased = replace(
            project,
            path=moved(project.path),
            root=tmp_root,
            model=tmp_model if project.model is not None else None,
            generators=tuple(replace(t, out=moved(out)) for t, out in zip(project.generators, outs, strict=True)),
        )
        try:
            generated: Generated = generate_project(rebased, tmp_model, lenient=True)
        except (SeamsError, OSError) as err:
            raise Refusal(subject, predicate, f"the generators cannot read the edited model: {err}") from err
        if generated.faults:
            fault = generated.faults[0]
            raise Refusal(
                fault.focus, fault.shape, f"the {fault.generator} generator faults on the edit: {fault.message}"
            )
        texts = {
            _relative(path, tmp_root): out.text
            for path, out in sorted(generated.files.items())
            if not path.name.endswith(SIDECAR_SUFFIX)
        }
        files = tuple(sorted(_relative(Path(e.path), tmp_root) for e in record.files))
    return Regenerated(texts=texts, files=files, old_hash=old_hash, new_hash=new_hash)


def check(project_dir: Path, model_path: Path, patch: Patch, output: str, edited: str) -> Regenerated:
    """Regenerate with ``patch`` applied to a temporary copy of the model; require
    ``output`` to come out as ``edited`` (the whole edited output text), hashes aside."""
    subject, predicate = (patch.removes or patch.adds or ((output, "output", None, None),))[0][:2]
    regenerated = regenerate(project_dir, model_path, patch, subject, predicate)
    old_hex = regenerated.old_hash.removeprefix("sha256:")
    new_hex = regenerated.new_hash.removeprefix("sha256:")
    expected = edited.replace(old_hex, new_hex)
    actual = regenerated.texts.get(output)
    if actual is None:
        raise Refusal(subject, predicate, f"regenerating no longer writes {output}")
    if actual != expected:
        raise Refusal(subject, predicate, first_difference(output, expected, actual))
    return regenerated


def effects(index: GenerationIndex, regenerated: Regenerated, output: str) -> tuple[Effect, ...]:
    """Every line of an output other than ``output`` that the patch changes, sorted
    by (output, line). Old text is read with the new model hash, so hash lines are
    not effects."""
    old_hex = regenerated.old_hash.removeprefix("sha256:")
    new_hex = regenerated.new_hash.removeprefix("sha256:")
    before_texts = {o.path: (o.text or "").replace(old_hex, new_hex) for o in index.outputs}
    found: list[Effect] = []
    for path in sorted(set(before_texts) | set(regenerated.texts)):
        if path == output:
            continue
        before, after = _lines(before_texts.get(path, "")), _lines(regenerated.texts.get(path, ""))
        matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                found.extend(line_effects(path, before, after, (i1, i2, j1, j2)))
    return tuple(sorted(found, key=lambda e: (e.output, e.line, e.before, e.after)))


def line_effects(output: str, before: list[str], after: list[str], opcode: tuple[int, int, int, int]) -> list[Effect]:
    """One ``Effect`` per line of a difflib opcode (i1, i2, j1, j2) from ``before`` to ``after``."""
    i1, i2, j1, j2 = opcode
    return [
        Effect(
            output=output,
            line=i1 + k + 1 if i1 + k < i2 else i2 + 1,
            before=before[i1 + k] if i1 + k < i2 else "",
            after=after[j1 + k] if j1 + k < j2 else "",
        )
        for k in range(max(i2 - i1, j2 - j1))
    ]


def write_back(
    index: GenerationIndex,
    ds: Dataset,
    project_dir: Path,
    model_path: Path,
    output: str,
    line: int,
    new_text: str,
) -> WriteBack:
    """Locate, draft, check and list the effects of editing ``output`` line ``line``
    to ``new_text``; raises ``Refusal`` naming the fact. Writes no model file."""
    try:
        located = locate(index, ds, output, line, new_text)
        patch = draft(located)
        shown = index.output(output)
        assert shown is not None and shown.text is not None  # locate checked both
        parts = shown.text.splitlines(keepends=True)
        old_line = parts[line - 1]
        parts[line - 1] = new_text + old_line[len(old_line.rstrip("\r\n")) :]
        regenerated = check(project_dir, model_path, patch, output, "".join(parts))
    except Refusal as err:
        logger.warning("write-back refused %s:%s: %s %s: %s", output, line, err.subject, err.predicate, err.detail)
        raise
    s, p, old, g = located.quad
    assert isinstance(old, Literal)  # locate takes literals only
    result = WriteBack(
        output=output,
        line=line,
        before=old_line.rstrip("\r\n"),
        after=new_text,
        subject=str(s),
        predicate=str(p),
        graph=str(g),
        old=old,
        new=located.new,
        patch=patch,
        files=regenerated.files,
        effects=effects(index, regenerated, output),
    )
    logger.info(
        "write-back drafted %s:%s: %s %s %s -> %s in %s (%d other lines change)",
        output,
        line,
        result.subject,
        result.predicate,
        term_text(old),
        term_text(located.new),
        ", ".join(result.files),
        len(result.effects),
    )
    return result
