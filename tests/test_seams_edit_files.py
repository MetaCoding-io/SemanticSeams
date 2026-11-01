"""File apply and undo (ADR-0017): a patch lands in the file that declares its graph.

Each case writes small inline TriG files into tmp_path and checks the bytes on disk:
routing over several files, all-or-nothing writes when any file fails, and undo by span
restore or, after an edit by another hand, by the inverse patch.
"""

import difflib
import os
from pathlib import Path

import pytest
import seams
from rdflib import Literal, Namespace, URIRef
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import RDFS

import seams_edit.files
from seams_edit import EditRecord, Patch, PatchError, apply, text_quads, undo

EX = Namespace("https://example.org/t/")

ONE = """@prefix ex: <https://example.org/t/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# The first graph.
ex:g1 {
    # About a.
    ex:a a ex:Thing ;
        rdfs:label "A" ;
        ex:links ex:b .
}
"""

TWO = """@prefix ex: <https://example.org/t/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# The second graph.
ex:g2 {
    ex:b a ex:Thing ;
        rdfs:label "B" .
}
"""

DEFAULT = """@prefix ex: <https://example.org/t/> .

ex:d ex:links ex:a .
"""


def _model(tmp_path: Path, **files: str) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, text in files.items():
        paths[name] = tmp_path / f"{name}.trig"
        paths[name].write_text(text, encoding="utf-8")
    return paths


def _snapshot(paths: dict[str, Path]) -> dict[str, bytes]:
    return {name: path.read_bytes() for name, path in paths.items()}


def _changed(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and line[:3] not in ("+++", "---")
    ]


def _quads(path: Path) -> set[tuple[object, ...]]:
    return set(text_quads(path.read_text(encoding="utf-8"), base=path.as_uri()))


def test_each_quad_lands_in_the_file_that_declares_its_graph(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1)],
        adds=[(EX.b, RDFS.comment, Literal("the second"), EX.g2)],
    )
    record = apply(seams.load(tmp_path).files, patch)

    assert _changed(ONE, paths["one"].read_text()) == [
        '-        rdfs:label "A" ;',
        "-        ex:links ex:b .",
        '+        rdfs:label "A" .',
    ]
    assert _changed(TWO, paths["two"].read_text()) == ['+        rdfs:comment "the second" ;']
    assert [edit.path for edit in record.files] == [paths["one"].resolve(), paths["two"].resolve()]
    assert [edit.patch for edit in record.files] == [
        Patch(removes=patch.removes),
        Patch(adds=patch.adds),
    ]
    assert record.patch == patch
    # The model as seams reads it is the old model with the patch applied.
    ds = seams.load(tmp_path).ds
    assert not list(ds.quads((EX.a, EX.links, EX.b, EX.g1)))
    assert list(ds.quads((EX.b, RDFS.comment, Literal("the second"), EX.g2)))


def test_the_record_holds_one_span_per_file(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE)
    patch = Patch(adds=[(EX.a, RDFS.comment, Literal("x"), EX.g1)])
    record = apply([paths["one"]], patch)

    (edit,) = record.files
    old, new = ONE.encode(), paths["one"].read_bytes()
    assert old[: edit.start] == new[: edit.start]
    assert old[: edit.start] + edit.before + old[edit.start + len(edit.before) :] == old
    assert new == old[: edit.start] + edit.after + old[edit.start + len(edit.before) :]
    # The smallest span: the added line, aligned wherever the old and new bytes differ.
    assert edit.before == b""
    assert edit.after.strip() == b'rdfs:comment "x" ;'


def test_a_default_graph_removal_goes_to_the_file_that_states_it(tmp_path: Path) -> None:
    paths = _model(tmp_path, default=DEFAULT, one=ONE)
    apply(paths.values(), Patch(removes=[(EX.d, EX.links, EX.a, DATASET_DEFAULT_GRAPH_ID)]))

    assert paths["one"].read_text() == ONE
    assert "ex:d" not in paths["default"].read_text()


def test_relative_iris_resolve_against_the_file(tmp_path: Path) -> None:
    text = "@prefix ex: <https://example.org/t/> .\n\nex:g1 {\n    <thing> ex:links ex:b .\n}\n"
    paths = _model(tmp_path, one=text, two=TWO)
    thing = URIRef((tmp_path / "thing").resolve().as_uri())
    assert list(seams.load(tmp_path).ds.quads((thing, EX.links, EX.b, EX.g1)))

    apply(paths.values(), Patch(adds=[(thing, EX.size, Literal(2), EX.g1)]))

    assert "<thing> ex:links ex:b ; ex:size 2 ." in paths["one"].read_text()
    assert str(tmp_path) not in paths["one"].read_text()


def test_an_empty_patch_writes_nothing(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE)
    stamp = paths["one"].stat().st_mtime_ns
    record = apply([paths["one"]], Patch())

    assert record == EditRecord(Patch(), ())
    assert paths["one"].stat().st_mtime_ns == stamp
    assert undo(record) == EditRecord(Patch(), ())


def test_a_graph_declared_in_two_files_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, also=ONE.replace("ex:a", "ex:z"))
    before = _snapshot(paths)

    with pytest.raises(PatchError) as raised:
        apply(paths.values(), Patch(adds=[(EX.a, RDFS.comment, Literal("x"), EX.g1)]))

    assert raised.value.subject == str(EX.a)
    assert raised.value.predicate == str(RDFS.comment)
    assert "declared in more than one model file (also.trig, one.trig)" in raised.value.detail
    assert _snapshot(paths) == before


def test_an_added_quad_in_an_undeclared_graph_needs_a_one_file_model(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    before = _snapshot(paths)
    quad = (EX.c, RDFS.label, Literal("C"), EX.g3)

    with pytest.raises(PatchError, match="no model file declares the graph, so its file is ambiguous"):
        apply(paths.values(), Patch(adds=[quad]))
    assert _snapshot(paths) == before

    apply([paths["one"]], Patch(adds=[quad]))
    assert quad in _quads(paths["one"])


def test_a_removed_quad_no_file_states_is_an_error(tmp_path: Path) -> None:
    paths = _model(tmp_path, default=DEFAULT, one=ONE)
    before = _snapshot(paths)

    with pytest.raises(PatchError, match="is not in the model") as raised:
        apply(paths.values(), Patch(removes=[(EX.d, EX.links, EX.b, DATASET_DEFAULT_GRAPH_ID)]))
    assert raised.value.subject == str(EX.d)
    assert _snapshot(paths) == before


def test_a_failure_in_the_second_file_leaves_the_first_unchanged(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    before = _snapshot(paths)
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1), (EX.b, RDFS.label, Literal("not B"), EX.g2)],
    )

    with pytest.raises(PatchError, match="is not in the model") as raised:
        apply(paths.values(), patch)

    assert raised.value.subject == str(EX.b)
    assert raised.value.predicate == str(RDFS.label)
    assert _snapshot(paths) == before


def test_an_os_error_writing_the_second_file_restores_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    before = _snapshot(paths)
    replace = os.replace
    calls: list[object] = []

    def failing_replace(source: object, target: object) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise PermissionError("read-only file")
        replace(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(seams_edit.files.os, "replace", failing_replace)
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1)],
        adds=[(EX.b, RDFS.comment, Literal("x"), EX.g2)],
    )

    with pytest.raises(PermissionError):
        apply(paths.values(), patch)

    assert len(calls) == 2
    assert _snapshot(paths) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one.trig", "two.trig"]


def test_a_file_that_is_not_utf8_is_an_error(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE)
    bad = tmp_path / "bad.trig"
    bad.write_bytes(b"# caf\xe9\n")

    with pytest.raises(PatchError, match="the model file is not UTF-8"):
        apply([paths["one"], bad], Patch(adds=[(EX.a, RDFS.comment, Literal("x"), EX.g1)]))
    assert paths["one"].read_text() == ONE


def test_undo_restores_the_spans_byte_for_byte(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    before = _snapshot(paths)
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1)],
        adds=[(EX.b, RDFS.comment, Literal("x"), EX.g2), (EX.a, RDFS.comment, Literal("y"), EX.g1)],
    )
    record = apply(paths.values(), patch)
    after = _snapshot(paths)

    redo = undo(record)

    assert _snapshot(paths) == before
    assert redo.patch == patch.inverse()
    undo(redo)
    assert _snapshot(paths) == after


def test_undo_keeps_a_later_edit_after_the_span(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE)
    record = apply([paths["one"]], Patch(adds=[(EX.a, RDFS.comment, Literal("x"), EX.g1)]))
    paths["one"].write_text(paths["one"].read_text() + "# A note added by hand.\n")

    undo(record)

    assert paths["one"].read_text() == ONE + "# A note added by hand.\n"


def test_undo_after_a_hand_edit_before_the_span_applies_the_inverse(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    original = {name: _quads(path) for name, path in paths.items()}
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1)],
        adds=[(EX.b, RDFS.comment, Literal("x"), EX.g2)],
    )
    record = apply(paths.values(), patch)
    note = "# A note added by hand.\n"
    for path in paths.values():
        path.write_text(note + path.read_text())

    redo = undo(record)

    for name, path in paths.items():
        text = path.read_text()
        assert text.startswith(note)
        assert _quads(path) == original[name]
    assert "# About a." in paths["one"].read_text()
    assert redo.patch == patch.inverse()
    assert [edit.patch for edit in redo.files] == [
        Patch(adds=[(EX.a, EX.links, EX.b, EX.g1)]),
        Patch(removes=[(EX.b, RDFS.comment, Literal("x"), EX.g2)]),
    ]


def test_undo_after_a_hand_edit_removed_the_addition_is_an_error(tmp_path: Path) -> None:
    paths = _model(tmp_path, one=ONE, two=TWO)
    patch = Patch(
        removes=[(EX.a, EX.links, EX.b, EX.g1)],
        adds=[(EX.b, RDFS.comment, Literal("x"), EX.g2)],
    )
    record = apply(paths.values(), patch)
    paths["two"].write_text(TWO.replace("# The second graph.", "# Edited by hand."))
    before = _snapshot(paths)

    with pytest.raises(PatchError, match="is not in the model") as raised:
        undo(record)

    assert raised.value.subject == str(EX.b)
    assert raised.value.predicate == str(RDFS.comment)
    assert _snapshot(paths) == before
