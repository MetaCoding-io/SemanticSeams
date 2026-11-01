"""Round trip over every example (ADR-0017): the writer edits real models one line at a time.

Each case copies one example TriG file into tmp_path and edits the copy through
``seams_edit.apply``. An empty patch leaves the bytes alone. For every named graph, one
existing quad is removed and one new quad, built only from terms the graph already
uses, is added: each edit changes one line, re-parses to the model with the patch
applied, keeps every comment in order, and ``undo`` gives the original bytes back. The
last cases remove one member of a written object list (``p o1 , o2``) and a subject's
first pair, where an example has them.
"""

import difflib
import re
import shutil
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, NamespaceManager
from rdflib.term import Node

from seams_edit import Patch, Quad, apply, apply_text, text_quads, undo
from seams_edit.patch import quad_key

ROOT = Path(__file__).resolve().parents[1]


def _example_trig_files() -> list[Path]:
    paths = (ROOT / "examples").rglob("*.trig")
    return sorted(p for p in paths if "generated" not in p.relative_to(ROOT).parts)


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _graph_cases() -> list[object]:
    cases: list[object] = []
    for path in _example_trig_files():
        graphs = {q[3] for q in text_quads(path.read_text(encoding="utf-8"), base=path.as_uri())}
        cases.extend(
            pytest.param(path, g, id=f"{_name(path)}::{g}") for g in sorted(graphs, key=str) if isinstance(g, URIRef)
        )
    return cases


def _copy(path: Path, tmp_path: Path) -> Path:
    target = tmp_path / path.name
    shutil.copyfile(path, target)
    return target


def _changes(before: str, after: str) -> tuple[list[str], list[str]]:
    """The lines removed and the lines added. ``autojunk`` is off: with it, difflib
    treats a line as common as ``}`` as junk in a long file and reports it changed."""
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            removed.extend(old[i1:i2])
            added.extend(new[j1:j2])
    return removed, added


def _assert_one_line(before: str, after: str) -> tuple[list[str], list[str]]:
    """One line removed or added, or one line rewritten."""
    removed, added = _changes(before, after)
    assert (len(removed), len(added)) in {(1, 0), (0, 1), (1, 1)}, (removed, added)
    return removed, added


def _comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def _parse(path: Path) -> Dataset:
    ds = Dataset()
    ds.parse(path, format="trig", publicID=path.as_uri())
    return ds


def _graphs(ds: Dataset) -> dict[Node, Graph]:
    return {g.identifier: Graph() + g for g in ds.graphs() if len(g)}


def _assert_patched(path: Path, before: Dataset, patch: Patch) -> None:
    """The file re-parses to ``before`` with the patch applied, graph by graph."""
    expected = _graphs(before)
    for s, p, o, g in patch.removes:
        expected[g].remove((s, p, o))
    for s, p, o, g in patch.adds:
        expected.setdefault(g, Graph()).add((s, p, o))
    expected = {g: graph for g, graph in expected.items() if len(graph)}
    actual = _graphs(_parse(path))
    assert sorted(actual, key=str) == sorted(expected, key=str)
    for g, graph in expected.items():
        assert isomorphic(actual[g], graph), f"graph {g} differs"


def _round_trip(path: Path, patch: Patch) -> tuple[list[str], list[str]]:
    """Apply the patch to the file and check it; undo it and check the bytes."""
    original = path.read_bytes()
    before = _parse(path)
    record = apply([path], patch)
    edited = path.read_text(encoding="utf-8")
    text = original.decode("utf-8")
    assert _comments(edited) == _comments(text)
    _assert_patched(path, before, patch)
    changes = _assert_one_line(text, edited)
    undo(record)
    assert path.read_bytes() == original
    return changes


def _iri_quads(quads: tuple[Quad, ...], graph: URIRef) -> list[Quad]:
    """The graph's quads between IRIs, sorted; blank nodes and literals are left out."""
    return sorted(
        (q for q in quads if q[3] == graph and isinstance(q[0], URIRef) and isinstance(q[2], URIRef)),
        key=quad_key,
    )


def _removal(quads: tuple[Quad, ...], graph: URIRef) -> Quad:
    """The quad to remove: the graph's first ``rdf:type`` quad, which an author writes
    on the subject's line, else its first quad."""
    in_graph = _iri_quads(quads, graph)
    typed = [q for q in in_graph if q[1] == RDF.type]
    return (typed or in_graph)[0]


def _addition(quads: tuple[Quad, ...], graph: URIRef, subject: Node) -> Quad:
    """A quad the graph lacks, from the file's own terms: the subject, the first
    predicate the graph uses, and the first IRI of the file the subject does not yet
    have with it."""
    stated = set(quads)
    predicates = sorted({q[1] for q in _iri_quads(quads, graph) if q[1] not in (RDF.first, RDF.rest)}, key=str)
    iris = sorted({t for q in quads for t in (q[0], q[2]) if isinstance(t, URIRef)}, key=str)
    return next(
        (subject, p, o, graph)
        for p in predicates
        for o in iris
        if o != subject and (subject, p, o, graph) not in stated
    )


def _nm(path: Path) -> NamespaceManager:
    return _parse(path).namespace_manager


def _expand(token: str, nm: NamespaceManager) -> URIRef:
    return RDF.type if token == "a" else URIRef(nm.expand_curie(token))


# Discovery ------------------------------------------------------------------------


def test_round_trip_covers_the_examples():
    names = [_name(p) for p in _example_trig_files()]
    assert "examples/chat-app/chat-app.trig" in names
    assert "examples/expenses/chapter-09/expenses.trig" in names
    assert not [n for n in names if "/generated/" in n]


# Empty patch ----------------------------------------------------------------------


@pytest.mark.parametrize("path", _example_trig_files(), ids=_name)
def test_empty_patch_gives_identical_bytes(path: Path, tmp_path: Path):
    copy = _copy(path, tmp_path)
    original = copy.read_bytes()
    text = original.decode("utf-8")
    assert apply_text(text, Patch(), base=copy.as_uri()) == text
    record = apply([copy], Patch())
    assert record.files == ()
    assert copy.read_bytes() == original


# One quad per named graph ---------------------------------------------------------


@pytest.mark.parametrize(("path", "graph"), _graph_cases())
def test_removing_one_quad_per_graph_round_trips(path: Path, graph: URIRef, tmp_path: Path):
    copy = _copy(path, tmp_path)
    quads = text_quads(copy.read_text(encoding="utf-8"), base=copy.as_uri())
    removed, _ = _round_trip(copy, Patch(removes=[_removal(quads, graph)]))
    assert len(removed) == 1


@pytest.mark.parametrize(("path", "graph"), _graph_cases())
def test_adding_one_quad_per_graph_round_trips(path: Path, graph: URIRef, tmp_path: Path):
    copy = _copy(path, tmp_path)
    quads = text_quads(copy.read_text(encoding="utf-8"), base=copy.as_uri())
    subject = _removal(quads, graph)[0]
    _, added = _round_trip(copy, Patch(adds=[_addition(quads, graph, subject)]))
    assert len(added) == 1


# Object lists and first pairs, where an example has them ---------------------------

# `predicate o1 , o2 ...` with prefixed names only, optionally after the subject.
_OBJECT_LIST = re.compile(r"^\s+(?:(?P<s>\S+) )?(?P<p>\S+) (?P<o>[^\s\"<>]+) , [^\"]*[;.]$")
# `subject a Type ;` opening a statement of several pairs.
_FIRST_PAIR = re.compile(r"^(?P<indent>\s+)(?P<s>\S+) a (?P<o>[^\s\",]+) ;$")


def _files_with(pattern: re.Pattern[str]) -> list[Path]:
    """The examples with a line the pattern matches."""
    return [
        p
        for p in _example_trig_files()
        if any(pattern.match(line) for line in p.read_text(encoding="utf-8").splitlines())
    ]


def _first_quad(path: Path, pattern: re.Pattern[str], subject: bool) -> tuple[str, re.Match[str], Quad]:
    """The first matching line that states exactly one quad of the model, and that quad.

    The pattern's ``s``, ``p`` and ``o`` groups are prefixed names; with no ``p`` group
    the predicate is ``a``."""
    text = path.read_text(encoding="utf-8")
    quads, nm = text_quads(text, base=path.as_uri()), _nm(path)
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        s = _expand(match["s"], nm) if subject or match["s"] else None
        p = _expand(match.groupdict().get("p") or "a", nm)
        found = [q for q in quads if q[1] == p and q[2] == _expand(match["o"], nm) and s in (None, q[0])]
        if len(found) == 1:
            return line, match, found[0]
    raise AssertionError(f"{_name(path)}: no matching line states exactly one quad")


def test_examples_have_object_lists_and_first_pairs():
    assert _files_with(_OBJECT_LIST)
    assert _files_with(_FIRST_PAIR)


@pytest.mark.parametrize("path", _files_with(_OBJECT_LIST), ids=_name)
def test_removing_one_member_of_an_object_list(path: Path, tmp_path: Path):
    copy = _copy(path, tmp_path)
    line, match, quad = _first_quad(copy, _OBJECT_LIST, subject=False)
    removed, added = _round_trip(copy, Patch(removes=[quad]))
    assert removed == [line + "\n"]
    assert added == [line.replace(f" {match['o']} , ", " ", 1) + "\n"]


@pytest.mark.parametrize("path", _files_with(_FIRST_PAIR), ids=_name)
def test_removing_a_first_pair_keeps_the_subject(path: Path, tmp_path: Path):
    copy = _copy(path, tmp_path)
    line, match, quad = _first_quad(copy, _FIRST_PAIR, subject=True)
    removed, added = _round_trip(copy, Patch(removes=[quad]))
    assert removed == [line + "\n"]
    assert added == [f"{match['indent']}{match['s']}\n"]
