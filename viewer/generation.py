"""The generation view's trace index (backlog T3, M020/S02, ADR-0019).

``get_index(base_dir)`` joins, for the project in ``base_dir`` (the viewer's
MODEL_DIR), the outputs ``seams.lock`` lists, their ``<output>.trace.json``
sidecars and the template files the traces cite:

- ``outputs``: one ``GeneratedOutput`` per locked output that is not itself a
  sidecar, sorted by lock path, with the output's text and its trace lines (an
  output of a generator with no ``trace`` hook is ``traced=False``: it has no
  sidecar by design, so that is no notice);
- ``fanout``: each model term IRI to the sorted ``(output, line)`` pairs whose
  trace lines cite it;
- ``templates``: each cited template name to its source text, found in the
  ``templates`` directory beside the module that defines the generator's
  ``render`` (the registry's ``Generator``), else in seams_gen's own;
- ``drafts``: the lock's ``seams propose`` llm-draft records (ADR-0020), sorted
  by task; ``draft_rows`` gives each its state (current, stale or hand-edited)
  by the comparison ``seams check``'s ``check_drafts`` makes.

Nothing here raises for a bad file: a missing or malformed lock, sidecar,
output or template is one ``Notice`` naming the file, and the rest of the
index is built without it. Every collection is sorted, and every path in the
index is the lock's project-relative posix path, never an absolute one.

Indexes are cached per base directory; ``_clear_cache()`` drops them for tests
that rewrite files (as validation._clear_cache, MEM010).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

import seams
from seams_cli import LOCK_FILE

from seams_gen.protocol import Generator
from seams_gen.registry import RegistryError, discover
from seams_gen.trace import TraceLine

SIDECAR_SUFFIX = ".trace.json"
TRACE_VERSION = 1
# seams_gen's own templates: the fallback for a generator whose module has none.
DEFAULT_TEMPLATE_DIR = Path(str(files("seams_gen") / "templates"))


@dataclass(frozen=True)
class Notice:
    file: str  # project-relative posix path, or a template name
    message: str


@dataclass(frozen=True)
class GeneratedOutput:
    path: str  # the lock's project-relative posix path
    generator: str
    text: str | None  # None when the output file cannot be read
    lines: tuple[TraceLine, ...]  # empty when the sidecar is missing or malformed
    traced: bool = True  # False when the generator has no trace hook and so writes no sidecar

    @property
    def trace_path(self) -> str:
        return self.path + SIDECAR_SUFFIX

    def line(self, number: int) -> TraceLine | None:
        """The trace line of 1-based output line ``number``, None for a blank or untraced line."""
        return next((tl for tl in self.lines if tl.line == number), None)


@dataclass(frozen=True)
class Draft:
    """One llm-draft record of seams.lock (ADR-0020)."""

    task: str
    path: str  # the lock's project-relative posix path
    context_hash: str
    template: str
    provider: str
    sha256: str


DRAFT_FIELDS = ("context_hash", "path", "provider", "sha256", "task", "template")


@dataclass(frozen=True)
class GenerationIndex:
    outputs: tuple[GeneratedOutput, ...] = ()
    drafts: tuple[Draft, ...] = ()
    fanout: dict[str, tuple[tuple[str, int], ...]] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)
    notices: tuple[Notice, ...] = ()

    def output(self, path: str) -> GeneratedOutput | None:
        return next((o for o in self.outputs if o.path == path), None)

    def citing(self, iri: str) -> tuple[tuple[str, int], ...]:
        """The sorted (output, line) pairs whose trace cites ``iri``."""
        return self.fanout.get(iri, ())


_cache: dict[str, GenerationIndex] = {}


def _clear_cache() -> None:
    _cache.clear()


def _locked_outputs(base_dir: Path, notices: list[Notice]) -> list[tuple[str, str]]:
    """Sorted (path, generator) of the lock's outputs, sidecars excluded."""
    lock = base_dir / LOCK_FILE
    if not lock.is_file():
        notices.append(Notice(LOCK_FILE, "no seams.lock: nothing has been generated for this model"))
        return []
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        entries = data["outputs"]
        found = {(str(e["path"]), str(e["generator"])) for e in entries}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as err:
        notices.append(Notice(LOCK_FILE, f"cannot be read: {type(err).__name__}: {err}"))
        return []
    return sorted((p, g) for p, g in found if not p.endswith(SIDECAR_SUFFIX))


def _locked_drafts(base_dir: Path, notices: list[Notice]) -> list[Draft]:
    """The lock's draft records sorted by task; a malformed one is a notice."""
    try:
        data = json.loads((base_dir / LOCK_FILE).read_text(encoding="utf-8"))
        entries = data.get("drafts", []) if isinstance(data, dict) else []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []  # _locked_outputs already names the lock
    if not isinstance(entries, list):
        notices.append(Notice(LOCK_FILE, "`drafts` must be a list"))
        return []
    drafts: list[Draft] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in DRAFT_FIELDS):
            notices.append(Notice(LOCK_FILE, f"`drafts[{i}]` must be an object of strings {', '.join(DRAFT_FIELDS)}"))
            continue
        drafts.append(Draft(**{k: str(entry[k]) for k in DRAFT_FIELDS}))
    return sorted(drafts, key=lambda d: (d.task, d.path))


def _trace_line(entry: object) -> TraceLine:
    if not isinstance(entry, dict):
        raise TypeError(f"a line entry must be an object, got {type(entry).__name__}")
    number, templates, terms = entry["line"], entry["templates"], entry["terms"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError(f"`line` must be a positive integer, got {number!r}")
    if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
        raise ValueError(f"line {number}: `templates` must be a list of strings")
    if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
        raise ValueError(f"line {number}: `terms` must be a list of strings")
    return TraceLine(line=number, templates=tuple(templates), terms=tuple(sorted(set(terms))))


def _read_trace(path: Path) -> tuple[TraceLine, ...]:
    """The sidecar's lines in line order; raises on any malformation."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"top level must be an object, got {type(data).__name__}")
    if data.get("trace_version") != TRACE_VERSION:
        raise ValueError(f"`trace_version` must be {TRACE_VERSION}, got {data.get('trace_version')!r}")
    lines = data["lines"]
    if not isinstance(lines, list):
        raise TypeError("`lines` must be a list")
    return tuple(sorted((_trace_line(e) for e in lines), key=lambda tl: tl.line))


def _registered(notices: list[Notice]) -> dict[str, Generator[Any]] | None:
    """The generator registry, or None (with a notice) when it cannot be loaded."""
    try:
        return discover()
    except RegistryError as err:
        notices.append(Notice(LOCK_FILE, f"generator registry cannot be loaded: {err}"))
        return None


def _template_dirs(registered: dict[str, Generator[Any]], generators: set[str]) -> dict[str, Path]:
    """{generator name: the templates directory beside its render module} for those that have one."""
    dirs: dict[str, Path] = {}
    for name in sorted(generators):
        gen = registered.get(name)
        source = None if gen is None else inspect.getsourcefile(gen.render)
        if source is not None and (Path(source).parent / "templates").is_dir():
            dirs[name] = Path(source).parent / "templates"
    return dirs


def _template_name(origin: str) -> str:
    """``name.j2`` of a ``name.j2:N`` origin."""
    return origin.rpartition(":")[0] or origin


def _build(base_dir: Path) -> GenerationIndex:
    notices: list[Notice] = []
    locked = _locked_outputs(base_dir, notices)
    drafts = _locked_drafts(base_dir, notices)
    registered = _registered(notices) if locked else {}
    outputs: list[GeneratedOutput] = []
    for rel, generator in locked:
        try:
            text: str | None = (base_dir / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            notices.append(Notice(rel, f"output cannot be read: {type(err).__name__}"))
            text = None
        gen = None if registered is None else registered.get(generator)
        if gen is not None and gen.trace is None:
            outputs.append(GeneratedOutput(path=rel, generator=generator, text=text, lines=(), traced=False))
            continue
        sidecar = rel + SIDECAR_SUFFIX
        try:
            lines = _read_trace(base_dir / sidecar)
        except FileNotFoundError:
            notices.append(Notice(sidecar, "trace sidecar is missing"))
            lines = ()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as err:
            notices.append(Notice(sidecar, f"trace sidecar is malformed: {type(err).__name__}: {err}"))
            lines = ()
        outputs.append(GeneratedOutput(path=rel, generator=generator, text=text, lines=lines))

    fanout: dict[str, set[tuple[str, int]]] = {}
    wanted: dict[str, set[str]] = {}  # template name -> generators citing it
    for out in outputs:
        for tl in out.lines:
            for iri in tl.terms:
                fanout.setdefault(iri, set()).add((out.path, tl.line))
            for origin in tl.templates:
                wanted.setdefault(_template_name(origin), set()).add(out.generator)

    dirs = _template_dirs(registered or {}, {g for gens in wanted.values() for g in gens})
    templates: dict[str, str] = {}
    for name in sorted(wanted):
        candidates = [dirs[g] / name for g in sorted(wanted[name]) if g in dirs] + [DEFAULT_TEMPLATE_DIR / name]
        found = next((p for p in candidates if p.is_file()), None)
        if found is None:
            notices.append(Notice(name, "template cannot be found in the generator's template directory"))
            continue
        try:
            templates[name] = found.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            notices.append(Notice(name, f"template cannot be read: {type(err).__name__}"))

    return GenerationIndex(
        outputs=tuple(outputs),
        drafts=tuple(drafts),
        fanout={iri: tuple(sorted(pairs)) for iri, pairs in sorted(fanout.items())},
        templates=templates,
        notices=tuple(sorted(notices, key=lambda n: (n.file, n.message))),
    )


def get_index(base_dir: Path) -> GenerationIndex:
    """The trace index of the project in ``base_dir``, cached per resolved directory."""
    key = str(base_dir.resolve())
    if key not in _cache:
        _cache[key] = _build(base_dir)
    return _cache[key]


# -- the generation view (T02) ---------------------------------------------------
#
# view() computes everything generation.html renders: the template only loops.
# Model facts (label, qname, layer) come from the caller's ``describe`` so this
# module never reads the graph; links come from its ``href``.


@dataclass(frozen=True)
class TermRow:
    iri: str
    label: str
    qname: str
    layer: str
    count: int  # lines of the shown output citing the term
    focus: bool  # the element the view was opened for


@dataclass(frozen=True)
class CodeLine:
    number: int
    text: str
    templates: tuple[str, ...] = ()  # "name.j2:N" origins, output lines only
    terms: tuple[str, ...] = ()  # cited IRIs, output lines only
    cites: bool = False  # cites the focused element
    on: bool = False  # the selected line (output) or one of its origins (template)


@dataclass(frozen=True)
class TemplatePane:
    name: str
    lines: tuple[CodeLine, ...]


@dataclass(frozen=True)
class FanoutEntry:
    output: str
    line: int
    text: str
    href: str
    selected: bool


@dataclass(frozen=True)
class FanoutGroup:
    output: str
    generator: str
    entries: tuple[FanoutEntry, ...]


@dataclass(frozen=True)
class GenerationView:
    iri: str
    output: GeneratedOutput | None  # the output shown, None when nothing cites the IRI
    line: int | None  # the selected output line
    terms: tuple[TermRow, ...]
    templates: tuple[TemplatePane, ...]
    lines: tuple[CodeLine, ...]
    fanout: tuple[FanoutGroup, ...]
    notices: tuple[Notice, ...]


# (label, qname, layer) of a model term, and the view's link to an output line.
Describe = Callable[[str], tuple[str, str, str]]
Href = Callable[[str, int], str]


def _text_lines(out: GeneratedOutput) -> list[str]:
    return [] if out.text is None else out.text.splitlines()


def view(
    index: GenerationIndex,
    iri: str,
    describe: Describe,
    href: Href,
    output: str = "",
    line: int = 0,
) -> GenerationView:
    """The generation view of ``iri``: the shown output is ``output`` when the
    index has it, else the first output citing ``iri``; the selected line is
    ``line`` when the output has it, else the output's first line citing ``iri``.
    An IRI no line cites gets no output and one notice saying so."""
    citing = index.citing(iri)
    shown = index.output(output) if output else None
    if shown is None and citing:
        shown = index.output(citing[0][0])
    notices = list(index.notices)
    if not citing:
        notices.append(Notice(iri, "no generated line cites this element"))

    selected: int | None = None
    lines: list[CodeLine] = []
    terms: tuple[TermRow, ...] = ()
    panes: list[TemplatePane] = []
    if shown is not None:
        texts = _text_lines(shown)
        own = [n for p, n in citing if p == shown.path]
        selected = line if 1 <= line <= len(texts) else (own[0] if own else None)
        focus_line = shown.line(selected) if selected is not None else None
        on_origins = set(focus_line.templates) if focus_line is not None else set()
        for number, text in enumerate(texts, start=1):
            tl = shown.line(number)
            lines.append(
                CodeLine(
                    number=number,
                    text=text,
                    templates=tl.templates if tl is not None else (),
                    terms=tl.terms if tl is not None else (),
                    cites=tl is not None and iri in tl.terms,
                    on=number == selected,
                )
            )
        counts: dict[str, int] = {}
        for tl in shown.lines:
            for term in tl.terms:
                counts[term] = counts.get(term, 0) + 1
        rows = [TermRow(t, *describe(t), count=n, focus=t == iri) for t, n in counts.items()]
        if iri not in counts:
            rows.append(TermRow(iri, *describe(iri), count=0, focus=True))
        terms = tuple(sorted(rows, key=lambda r: (not r.focus, r.label, r.iri)))
        cited = sorted({_template_name(o) for tl in shown.lines for o in tl.templates})
        for name in cited:
            source = index.templates.get(name)
            if source is None:
                continue  # its notice is already in the index
            panes.append(
                TemplatePane(
                    name=name,
                    lines=tuple(
                        CodeLine(number=n, text=t, on=f"{name}:{n}" in on_origins)
                        for n, t in enumerate(source.splitlines(), start=1)
                    ),
                )
            )
    else:
        terms = (TermRow(iri, *describe(iri), count=0, focus=True),)

    groups: list[FanoutGroup] = []
    for path in sorted({p for p, _ in citing}):
        out = index.output(path)
        if out is None:
            continue
        texts = _text_lines(out)
        entries = tuple(
            FanoutEntry(
                output=path,
                line=n,
                text=texts[n - 1] if n <= len(texts) else "",
                href=href(path, n),
                selected=shown is not None and path == shown.path and n == selected,
            )
            for p, n in citing
            if p == path
        )
        groups.append(FanoutGroup(output=path, generator=out.generator, entries=entries))

    return GenerationView(
        iri=iri,
        output=shown,
        line=selected,
        terms=terms,
        templates=tuple(panes),
        lines=tuple(lines),
        fanout=tuple(groups),
        notices=tuple(sorted(notices, key=lambda n: (n.file, n.message))),
    )


# -- the inspector's Generated section (T03) ---------------------------------------


@dataclass(frozen=True)
class GeneratedRow:
    output: str
    generator: str
    lines: int  # lines of the output citing the element
    href: str  # the generation view opened on the output's first citing line


def generated(index: GenerationIndex, iri: str, href: Href) -> tuple[GeneratedRow, ...]:
    """Per output citing ``iri``, sorted by output path: how many of its lines
    cite it, linked into the generation view. Empty when no line cites it."""
    by_output: dict[str, list[int]] = {}
    for path, line in index.citing(iri):
        by_output.setdefault(path, []).append(line)
    rows: list[GeneratedRow] = []
    for path in sorted(by_output):
        out = index.output(path)
        if out is None:
            continue
        lines = sorted(by_output[path])
        rows.append(GeneratedRow(output=path, generator=out.generator, lines=len(lines), href=href(path, lines[0])))
    return tuple(rows)


# -- the generation view's drafts (M022/S05) ---------------------------------------


@dataclass(frozen=True)
class DraftRow:
    task: str
    path: str
    provider: str
    template: str
    state: str  # "current", or "stale", "hand-edited" or both, comma-separated


def draft_rows(index: GenerationIndex, base_dir: Path, model: seams.Model) -> tuple[DraftRow, ...]:
    """Each lock draft with its state, by ``seams check``'s comparison: stale when
    the task's context hash differs from the record (or the task no longer
    resolves), hand-edited when the file's sha256 differs (or it is missing)."""
    rows: list[DraftRow] = []
    for draft in index.drafts:
        states: list[str] = []
        try:
            if seams.context_for(model, draft.task).context_hash != draft.context_hash:
                states.append("stale")
        except seams.ResolutionError:
            states.append("stale")
        path = base_dir / draft.path
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != draft.sha256:
                states.append("hand-edited")
        except OSError:
            states.append("hand-edited")
        rows.append(DraftRow(draft.task, draft.path, draft.provider, draft.template, ", ".join(states) or "current"))
    return tuple(rows)
