"""The XML payload writer over every example payload (ADR-0017, ADR-0002 rule 5).

Each case copies one example's TriG and payload files into tmp_path and loads the copy
with ``seams.load``. ``rename_id`` renames one element per payload: a lifted element
(``modelIRI#id`` in the seams graph) where the payload has one, else the DMN decision a
``dec:payloadElement`` binds, else an element other elements refer to. Afterwards no
quad names the old IRI, the new IRI has the old one's seam edges, the payload has no
old id or reference and only the lines that wrote it changed, and ``undo`` gives every
file its bytes back. Bad XML, a colliding or missing id and a payload or model IRI the
model does not have raise PatchError and leave every byte as it was.
"""

import difflib
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import seams
from lxml import etree
from rdflib import Dataset, Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.term import BNode, Literal, Node
from seams import DEC, SEAM

from seams_edit import EditRecord, Patch, PatchError, rename_id, save_payload, undo

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = (".trig", ".bpmn", ".dmn")


def _example_payloads() -> list[Path]:
    paths = [p for suffix in (".bpmn", ".dmn") for p in (ROOT / "examples").rglob(f"*{suffix}")]
    return sorted(p for p in paths if "generated" not in p.relative_to(ROOT).parts)


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _copy(payload: Path, tmp_path: Path) -> Path:
    """The payload's example (its TriG and payload files) copied; the copied payload."""
    for path in sorted(payload.parent.iterdir()):
        if path.suffix in SUFFIXES:
            shutil.copyfile(path, tmp_path / path.name)
    return tmp_path / payload.name


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.suffix in SUFFIXES}


def _model_iri(model: seams.Model, payload: Path) -> URIRef:
    (iri,) = [
        m
        for m, p in model.ds.subject_objects(SEAM.renderPayload)
        if isinstance(m, URIRef) and seams.payload_path(p, model.base_dir).resolve() == payload.resolve()
    ]
    return iri


def _xml_ids(payload: Path) -> list[str]:
    root = etree.parse(str(payload)).getroot()
    return sorted({str(v) for el in root.iter() if isinstance(el.tag, str) for k, v in el.attrib.items() if k == "id"})


def _lifted(model: seams.Model, iri: URIRef) -> set[URIRef]:
    prefix = f"{iri}#"
    return {t for q in model.ds.quads() for t in (q[0], q[2]) if isinstance(t, URIRef) and str(t).startswith(prefix)}


def _target(model: seams.Model, iri: URIRef, payload: Path) -> str:
    """The id to rename: lifted, else bound by dec:payloadElement, else referred to."""
    ids = _xml_ids(payload)
    lifted = sorted(str(t).partition("#")[2] for t in _lifted(model, iri))
    bound = sorted(
        str(o)
        for d in model.ds.subjects(SEAM.inModel, iri)
        for o in model.ds.objects(d, DEC.payloadElement)
        if isinstance(o, Literal)
    )
    text = payload.read_text(encoding="utf-8")
    referred = [i for i in ids if re.search(rf'Ref="{re.escape(i)}"|href="#{re.escape(i)}"', text)]
    return next(i for i in [*lifted, *bound, *referred] if i in ids)


def _edges(ds: Dataset, iri: URIRef, rename: dict[Node, Node]) -> tuple[set[tuple[Node, ...]], set[tuple[Node, ...]]]:
    """``iri``'s edges out and in; blank nodes as one placeholder, terms renamed."""

    def norm(term: Node) -> Node:
        return Literal("_:") if isinstance(term, BNode) else rename.get(term, term)

    out = {(p, norm(o)) for _, p, o, _ in ds.quads((iri, None, None, None))}
    into = {(norm(s), p) for s, p, _, _ in ds.quads((None, None, iri, None))}
    return out, into


def _changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    old, new = before.splitlines(), after.splitlines()
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            removed.extend(old[i1:i2])
            added.extend(new[j1:j2])
    return removed, added


def _graphs(ds: Dataset) -> dict[Node, Graph]:
    return {g.identifier: Graph() + g for g in ds.graphs() if len(g)}


def _assert_same_quads(left: Dataset, right: Dataset) -> None:
    a, b = _graphs(left), _graphs(right)
    assert sorted(a, key=str) == sorted(b, key=str)
    for g in a:
        assert isomorphic(a[g], b[g]), f"graph {g} differs"


# Discovery ------------------------------------------------------------------------


def test_cases_cover_the_example_payloads():
    names = [_name(p) for p in _example_payloads()]
    assert "examples/chat-app/chat_process.bpmn" in names
    assert "examples/chat-app/routing.dmn" in names
    assert "examples/expenses/chapter-09/payout.dmn" in names
    assert not [n for n in names if "/generated/" in n]


# Rename ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", _example_payloads(), ids=_name)
def test_rename_moves_every_quad_and_reference_and_undoes(payload: Path, tmp_path: Path):
    copy = _copy(payload, tmp_path)
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    iri = _model_iri(model, copy)
    old = _target(model, iri, copy)
    new = f"{old}_renamed"
    old_iri, new_iri = URIRef(f"{iri}#{old}"), URIRef(f"{iri}#{new}")
    edges = _edges(model.ds, old_iri, {old_iri: new_iri})
    bound = sorted(
        d for d in model.ds.subjects(SEAM.inModel, iri) if model.ds.value(d, DEC.payloadElement) == Literal(old)
    )

    record = rename_id(model.files, copy, iri, old, new)

    after = seams.load(tmp_path)
    assert not [q for q in after.ds.quads() if old_iri in q]
    assert _edges(after.ds, new_iri, {}) == edges
    for decision in bound:
        assert after.ds.value(decision, DEC.payloadElement) == Literal(new)
    ids = _xml_ids(copy)
    assert old not in ids
    assert new in ids
    text = copy.read_text(encoding="utf-8")
    assert not re.search(rf'="#?{re.escape(old)}"|>\s*{re.escape(old)}\s*<', text)
    removed, added = _changed_lines(original[copy.name].decode("utf-8"), text)
    assert removed
    assert all(old in line for line in removed)
    assert all(new in line for line in added)
    assert {e.path.name for e in record.files if e.payload} == {copy.name}

    undo(record)
    assert _snapshot(tmp_path) == original


def test_rename_gives_the_same_bytes_every_time(tmp_path: Path):
    payload = ROOT / "examples/expenses/chapter-09/approval.bpmn"
    results: list[dict[str, bytes]] = []
    for run in ("a", "b"):
        directory = tmp_path / run
        directory.mkdir()
        copy = _copy(payload, directory)
        model = seams.load(directory)
        iri = _model_iri(model, copy)
        rename_id(model.files, copy, iri, _target(model, iri, copy), "renamed_element")
        results.append(_snapshot(directory))
    assert results[0] == results[1]


_BNODE_TRIG = """\
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix :     <https://example.org/t/> .

<urn:seams:graph:model:t> {
    :t_bpmn a seam:Model ;
        seam:renderPayload <t.bpmn> .
    # The task carries a written blank node.
    <https://example.org/t/t_bpmn#task_a> rdfs:label "A" ;
        rdfs:seeAlso [ rdfs:label "note" ; rdfs:seeAlso [ rdfs:label "inner" ] ] .
}
"""

_BNODE_BPMN = """\
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="defs">
  <bpmn:process id="p">
    <bpmn:task id="task_a"><bpmn:outgoing>f</bpmn:outgoing></bpmn:task>
    <bpmn:endEvent id="end"><bpmn:incoming>f</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f" sourceRef="task_a" targetRef="end" />
  </bpmn:process>
</bpmn:definitions>
"""


def test_rename_moves_a_written_blank_node_with_its_triples(tmp_path: Path):
    (tmp_path / "t.trig").write_text(_BNODE_TRIG, encoding="utf-8")
    (tmp_path / "t.bpmn").write_text(_BNODE_BPMN, encoding="utf-8")
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    iri = URIRef("https://example.org/t/t_bpmn")
    before = _edges(model.ds, URIRef(f"{iri}#task_a"), {})

    record = rename_id(model.files, tmp_path / "t.bpmn", iri, "task_a", "task_b")

    after = seams.load(tmp_path)
    assert _edges(after.ds, URIRef(f"{iri}#task_b"), {}) == before
    assert not list(after.ds.quads((URIRef(f"{iri}#task_a"), None, None, None)))
    assert len(after.ds) == len(model.ds)
    assert 'sourceRef="task_b"' in (tmp_path / "t.bpmn").read_text(encoding="utf-8")
    undo(record)
    assert _snapshot(tmp_path) == original


# Save -----------------------------------------------------------------------------


@pytest.mark.parametrize("payload", _example_payloads(), ids=_name)
def test_save_payload_writes_the_xml_and_undoes(payload: Path, tmp_path: Path):
    copy = _copy(payload, tmp_path)
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    text = copy.read_text(encoding="utf-8")
    edited = text.replace(' name="', ' name="Edited ', 1)
    assert edited != text

    assert save_payload(model.files, copy, text) == EditRecord(Patch(), ())
    record = save_payload(model.files, copy, edited)
    assert copy.read_text(encoding="utf-8") == edited
    assert [(e.path, e.payload) for e in record.files] == [(copy.resolve(), True)]
    undo(record)
    assert _snapshot(tmp_path) == original


# Refusals: PatchError, nothing written ---------------------------------------------


def _assert_refused(tmp_path: Path, original: dict[str, bytes], call: Callable[[], object], match: str) -> None:
    with pytest.raises(PatchError, match=match):
        call()
    assert _snapshot(tmp_path) == original


@pytest.mark.parametrize("payload", _example_payloads(), ids=_name)
def test_bad_xml_and_colliding_ids_write_nothing(payload: Path, tmp_path: Path):
    copy = _copy(payload, tmp_path)
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    iri = _model_iri(model, copy)
    old = _target(model, iri, copy)
    other = next(i for i in _xml_ids(copy) if i != old)
    files = model.files

    _assert_refused(tmp_path, original, lambda: save_payload(files, copy, "<definitions>"), "not well-formed XML")
    _assert_refused(tmp_path, original, lambda: rename_id(files, copy, iri, old, other), "already has an element")
    _assert_refused(tmp_path, original, lambda: rename_id(files, copy, iri, "no_such_id", "x"), "has no element")


def test_names_the_model_does_not_have_write_nothing(tmp_path: Path):
    copy = _copy(ROOT / "examples/chat-app/chat_process.bpmn", tmp_path)
    stray = tmp_path / "stray.bpmn"
    shutil.copyfile(copy, stray)
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    iri = _model_iri(model, copy)
    old = _target(model, iri, copy)
    dmn_iri = _model_iri(model, tmp_path / "routing.dmn")
    files = model.files

    _assert_refused(tmp_path, original, lambda: save_payload(files, stray, copy.read_text()), "names this payload")
    _assert_refused(tmp_path, original, lambda: rename_id(files, stray, iri, old, "x"), "names this payload")
    _assert_refused(tmp_path, original, lambda: rename_id(files, copy, dmn_iri, old, "x"), "does not render")
    _assert_refused(tmp_path, original, lambda: rename_id(files, copy, iri, old, "a b"), "not an XML id")
    _assert_refused(tmp_path, original, lambda: rename_id(files, copy, iri, old, "a:b"), "not an XML id")


# Undo after another hand ------------------------------------------------------------


def test_undo_refuses_a_payload_changed_after_the_edit(tmp_path: Path):
    copy = _copy(ROOT / "examples/chat-app/chat_process.bpmn", tmp_path)
    model = seams.load(tmp_path)
    iri = _model_iri(model, copy)
    old = _target(model, iri, copy)
    record = rename_id(model.files, copy, iri, old, "renamed_task")
    copy.write_text(copy.read_text(encoding="utf-8").replace("renamed_task", "hand_edit"), encoding="utf-8")
    edited = _snapshot(tmp_path)

    _assert_refused(tmp_path, edited, lambda: undo(record), "payload file changed")


def test_undo_after_a_model_hand_edit_restores_the_payload_and_the_quads(tmp_path: Path):
    copy = _copy(ROOT / "examples/chat-app/chat_process.bpmn", tmp_path)
    original = _snapshot(tmp_path)
    model = seams.load(tmp_path)
    iri = _model_iri(model, copy)
    record = rename_id(model.files, copy, iri, _target(model, iri, copy), "renamed_task")
    trig = tmp_path / "chat-app.trig"
    trig.write_text("# a hand edit above every span\n" + trig.read_text(encoding="utf-8"), encoding="utf-8")

    undo(record)

    assert copy.read_bytes() == original[copy.name]
    assert trig.read_text(encoding="utf-8").startswith("# a hand edit above every span\n")
    _assert_same_quads(seams.load(tmp_path).ds, model.ds)
