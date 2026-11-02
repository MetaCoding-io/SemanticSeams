"""File apply and undo: a patch lands in the model files that hold its graphs (ADR-0017).

``apply`` reads every TriG file of a model, routes each quad to the one file that
declares its graph, edits each file's text with the writer and writes the files only
when every one of them has succeeded. It returns an ``EditRecord``: the patch and, per
file, the one byte span it changed with the bytes before and after. ``undo`` puts the
before bytes back while the files still hold the after bytes at those spans, and
otherwise applies the inverse patch through the writer. A record may also hold a
BPMN or DMN payload file's span (``seams_edit.xml``), which undo puts back the same
way. The record is the session's history; nothing about it is written to disk.
"""

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.term import Node

from .patch import Patch, PatchError, Quad
from .patch import term_text as _n3
from .trig import apply_text, declared_graphs, text_quads


@dataclass(frozen=True)
class FileEdit:
    """One file's change: its share of the patch, and at byte ``start``, ``before``
    became ``after``. A ``payload`` edit is a BPMN or DMN file's; its share is empty."""

    path: Path
    patch: Patch
    start: int
    before: bytes
    after: bytes
    payload: bool = False


@dataclass(frozen=True)
class EditRecord:
    """A patch as applied: the patch and each changed file's edit, sorted by path."""

    patch: Patch
    files: tuple[FileEdit, ...]


@dataclass(frozen=True)
class Source:
    path: Path
    data: bytes
    text: str
    base: str


def read_source(path: Path, what: str = "model") -> Source:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError(path, f"byte {exc.start}", f"the {what} file is not UTF-8") from None
    return Source(path, data, text, path.as_uri())


def read_sources(paths: Iterable[str | os.PathLike[str]]) -> tuple[Source, ...]:
    resolved = sorted({Path(p).resolve() for p in paths})
    if not resolved:
        raise ValueError("no model files given")
    return tuple(read_source(p) for p in resolved)


def route(sources: tuple[Source, ...], patch: Patch) -> dict[Path, Patch]:
    """Each file's share of the patch; PatchError for a quad no one file can take."""
    declaring: dict[Node, list[Path]] = {}
    for source in sources:
        for graph in declared_graphs(source.text, base=source.base):
            declaring.setdefault(graph, []).append(source.path)
    stated: dict[Path, frozenset[Quad]] = {}

    def stating(quad: Quad) -> list[Path]:
        for source in sources:
            if source.path not in stated:
                stated[source.path] = frozenset(text_quads(source.text, base=source.base))
        return [path for path, quads in stated.items() if quad in quads]

    def target(quad: Quad, removing: bool) -> Path:
        s, p, o, g = quad
        where = f"object {_n3(o)}, graph {_n3(g)}"
        files = declaring.get(g, []) if g != DATASET_DEFAULT_GRAPH_ID else []
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise PatchError(s, p, f"{where}: the graph is declared in more than one model file ({names})")
        if files:
            return files[0]
        if removing:
            files = stating(quad)
            if not files:
                raise PatchError(s, p, f"removed quad ({where}) is not in the model")
            if len(files) > 1:
                raise PatchError(s, p, f"removed quad ({where}) is stated in more than one model file")
            return files[0]
        if len(sources) == 1:
            return sources[0].path
        raise PatchError(s, p, f"added quad ({where}): no model file declares the graph, so its file is ambiguous")

    removes: dict[Path, list[Quad]] = {}
    adds: dict[Path, list[Quad]] = {}
    for quad in patch.removes:
        removes.setdefault(target(quad, removing=True), []).append(quad)
    for quad in patch.adds:
        adds.setdefault(target(quad, removing=False), []).append(quad)
    return {
        path: Patch(adds=adds.get(path, ()), removes=removes.get(path, ())) for path in sorted(set(removes) | set(adds))
    }


def span(path: Path, share: Patch, before: bytes, after: bytes, payload: bool = False) -> FileEdit:
    """The smallest single span that turns ``before`` into ``after``."""
    limit = min(len(before), len(after))
    start = 0
    while start < limit and before[start] == after[start]:
        start += 1
    end = 0
    while end < limit - start and before[-1 - end] == after[-1 - end]:
        end += 1
    return FileEdit(path, share, start, before[start : len(before) - end], after[start : len(after) - end], payload)


def write_all(contents: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """Write each file's new bytes; on an OS error, put back the files already written."""
    written: list[Path] = []
    try:
        for path, (_, new) in sorted(contents.items()):
            temporary = path.with_name(f".{path.name}.seams-edit")
            temporary.write_bytes(new)
            os.replace(temporary, path)
            written.append(path)
    except OSError:
        for path in contents:
            path.with_name(f".{path.name}.seams-edit").unlink(missing_ok=True)
        for path in written:
            path.write_bytes(contents[path][0])
        raise


def commit(
    patch: Patch,
    sources: Mapping[Path, Source],
    shares: Mapping[Path, Patch],
    payloads: Mapping[Path, tuple[bytes, bytes]] | None = None,
) -> EditRecord:
    """Edit every file's text, then write them all, with each payload file's old and new
    bytes; nothing is written if one fails."""
    payloads = payloads or {}
    contents: dict[Path, tuple[bytes, bytes]] = {}
    for path, share in sorted(shares.items()):
        source = sources[path]
        contents[path] = (source.data, apply_text(source.text, share, base=source.base).encode("utf-8"))
    contents.update({path: pair for path, pair in payloads.items() if pair[0] != pair[1]})
    write_all(contents)
    return EditRecord(
        patch,
        tuple(
            span(path, shares.get(path, Patch()), *contents[path], payload=path in payloads)
            for path in sorted(contents)
        ),
    )


def apply(paths: Iterable[str | os.PathLike[str]], patch: Patch) -> EditRecord:
    """Apply ``patch`` to the model made of the TriG files ``paths``; return the record.

    Pass ``seams.load(model).files`` for a loaded model. Each quad goes to the one file
    that declares its graph; a default-graph quad being removed goes to the one file
    that states it, and an added quad whose graph no file declares goes to the only
    file of a one-file model. Raises PatchError, writing nothing, when a graph is
    declared in more than one file, a quad has no single file, or the writer refuses
    any file's share. An empty patch reads the files and writes nothing.
    """
    sources = read_sources(paths)
    if patch.is_empty:
        return EditRecord(patch, ())
    return commit(patch, {source.path: source for source in sources}, route(sources, patch))


def undo(record: EditRecord) -> EditRecord:
    """Undo ``record``; return the record of the undo, which ``undo`` can redo.

    When every file still holds the record's after bytes at its span, the before bytes
    go back and the rest of each file is kept as it is now. Otherwise, after an edit by
    another hand inside or before a span, each model file's share of the inverse patch
    is applied to it through the writer, which raises PatchError, writing nothing, if a
    file no longer holds what the patch added there. A payload file has no patch to
    invert: when it no longer holds its after bytes, undo raises PatchError and writes
    nothing.
    """
    inverse = record.patch.inverse()
    if not record.files:
        return EditRecord(inverse, ())
    sources = {source.path: source for source in read_sources(edit.path for edit in record.files)}

    def holds(edit: FileEdit) -> bool:
        return sources[edit.path].data[edit.start : edit.start + len(edit.after)] == edit.after

    def restored(edit: FileEdit) -> tuple[bytes, bytes]:
        data = sources[edit.path].data
        return data, data[: edit.start] + edit.before + data[edit.start + len(edit.after) :]

    for edit in record.files:
        if edit.payload and not holds(edit):
            raise PatchError(
                edit.path, f"byte {edit.start}", "the payload file changed after the edit; undo cannot restore it"
            )
    if not all(holds(e) for e in record.files):
        payloads = {e.path: restored(e) for e in record.files if e.payload}
        shares = {e.path: e.patch.inverse() for e in record.files if not e.payload}
        return commit(inverse, sources, shares, payloads)
    write_all({edit.path: restored(edit) for edit in record.files})
    return EditRecord(
        inverse,
        tuple(FileEdit(e.path, e.patch.inverse(), e.start, e.after, e.before, e.payload) for e in record.files),
    )
