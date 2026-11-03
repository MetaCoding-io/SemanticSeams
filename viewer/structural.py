"""Structural edit proposals (backlog T5, M021/S02, ADR-0019, ADR-0017).

A person edits a generated htmx page as a whole in the generation view, adding
or removing one form input. This module turns that edit into a model patch, or
refuses it:

- ``changed_block`` diffs the old output against the edited text by line
  (difflib). Exactly one contiguous changed block is required. The block may
  also change the lines next to the input, such as the form's "set by the
  runtime" comment, which lists the unbound fields.
- ``named_controls`` parses each side of the block (``lxml.html`` fragments)
  for the ``input``, ``textarea`` and ``select`` elements with a ``name``.
  Exactly one name must be added or removed.
- ``enclosing_form`` reads the trace terms (``TraceLine.terms``) of the nearest
  traced lines above and below the block. Both must name the same one
  ``ifml:Form`` with a ``seam:writes`` shape. An input line traces only the
  written shape (``Input.iri``), so the form is found around it.
- Removal: the form's one ``ifml:hasParameter`` whose ``ifml:boundTo`` path has
  the control's name as its local name (the generator's ``Field.name``) is
  dropped. The patch removes every quad with the parameter as subject, and the
  ``hasParameter`` quad, in their graphs. A parameter that anything else refers
  to is refused.
- Addition: the parameter is minted in the form's namespace as
  ``<name>_input``. It gets ``a ifml:Parameter``, ``rdfs:label "<name> input"``,
  ``ifml:boundTo`` the path, the form's ``seam:inModel`` and the form's
  ``ifml:hasParameter``, all in the form's graph. The path is the written
  shape's ``sh:property`` path with that local name. When the shape has none,
  the path is minted in the shape's namespace and a blank-node ``sh:property``
  is added in the shape's graph. Its values are copied from the edited control:
  ``sh:datatype`` (and ``dash:editor``) from the element by the inverse of the
  htmx generator's field kinds, ``sh:maxLength`` from ``maxlength``,
  ``sh:minCount 1`` from ``required`` and ``sh:name`` from the name. The path
  is declared ``a rdf:Property`` unless the model already declares it.
- ``writeback.regenerate`` regenerates in memory with the patch applied to a
  temporary copy. Every line of the edited output must come out as edited,
  hashes aside. The one exception is a line outside the edited block that the
  patch changes (a new field also shows in a ``Details`` of the same shape on
  the same page). That line is an effect, listed with the other outputs'
  effects. Otherwise the edit is a ``Refusal`` naming the first difference.

``propose`` runs these and logs each drafted and refused proposal with its
subject, predicate and files, as ``writeback.write_back`` does. Nothing here
writes the real model: the viewer applies the patch through ``seams_edit`` in
edit mode.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal as Kind

import lxml.html
from lxml import etree
from rdflib import RDF, RDFS, SH, XSD, BNode, Dataset, Literal, URIRef
from rdflib.term import Node
from seams import DASH, IFML, SEAM, local_name
from seams.review_check import PROPERTY_TYPES

from seams_edit import Patch, Quad
from seams_edit.patch import term_text
from viewer import writeback
from viewer.generation import GenerationIndex
from viewer.writeback import Effect, Refusal

logger = logging.getLogger("uvicorn.error")

_CONTROLS = ("input", "textarea", "select")
# A name the generator can write back as a path local name and an element id.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class Control:
    """A named form control of the edited block, as written."""

    name: str
    element: str  # "input", "textarea" or "select"
    attributes: tuple[tuple[str, str], ...]  # sorted (attribute, value)

    def attribute(self, key: str) -> str | None:
        return next((v for k, v in self.attributes if k == key), None)


@dataclass(frozen=True)
class Block:
    """The one changed block: old lines [start, end) became the edited lines [new_start, new_end)."""

    start: int
    end: int
    new_start: int
    new_end: int


@dataclass(frozen=True)
class Structural:
    output: str
    kind: Kind["add", "remove"]
    field: str  # the control's name: the path's local name
    form: str  # the enclosing ifml:Form
    parameter: str  # the ifml:Parameter added or removed
    path: str  # its ifml:boundTo sh:path
    first: int  # 1-based first old line of the edited block
    last: int  # 1-based last old line (first - 1 for a pure insertion)
    patch: Patch
    files: tuple[str, ...]  # project-relative model files the patch changes
    effects: tuple[Effect, ...]  # lines the patch changes outside the edited block, sorted


def changed_block(output: str, old: list[str], new: list[str]) -> Block:
    """The one contiguous block in which ``new`` differs from ``old`` (lines with ends)."""
    ops = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not ops:
        raise Refusal(output, "lines", "the edited output is the same as the generated one")
    if len(ops) > 1:
        where = ", ".join(str(i1 + 1) for _tag, i1, _i2, _j1, _j2 in ops)
        raise Refusal(
            output,
            "lines",
            f"a structural edit changes one block of lines; this edit changes {len(ops)} (at old lines {where})",
        )
    _tag, i1, i2, j1, j2 = ops[0]
    return Block(start=i1, end=i2, new_start=j1, new_end=j2)


def named_controls(text: str) -> list[Control]:
    """The named input, textarea and select elements of an HTML fragment, in document order."""
    if not text.strip():
        return []
    try:
        parts = lxml.html.fragments_fromstring(text)
    except etree.ParserError:
        return []
    found: list[Control] = []
    for part in parts:
        if not isinstance(part, lxml.html.HtmlElement):
            continue
        for el in part.iter(*_CONTROLS):
            name = el.get("name")
            if name is not None:
                attributes = tuple(sorted((str(k), str(v)) for k, v in el.attrib.items()))
                found.append(Control(name=name, element=str(el.tag), attributes=attributes))
    return found


def _is_form(ds: Dataset, term: URIRef) -> bool:
    return (term, RDF.type, IFML.Form, None) in ds and ds.value(term, SEAM.writes) is not None


def enclosing_form(index: GenerationIndex, ds: Dataset, output: str, block: Block) -> URIRef:
    """The one ifml:Form the nearest traced form lines above and below the block both name."""
    shown = index.output(output)
    assert shown is not None
    numbered = sorted(shown.lines, key=lambda tl: tl.line)

    def forms(lines: list[int]) -> set[URIRef]:
        for number in lines:
            traced = shown.line(number)
            found = {URIRef(t) for t in (traced.terms if traced else ()) if _is_form(ds, URIRef(t))}
            if found:
                return found
        return set()

    last = numbered[-1].line if numbered else 0
    above = forms(list(range(block.start, 0, -1)))
    below = forms(list(range(block.end + 1, last + 1)))
    where = f"{output}:{block.start + 1}"
    both = sorted(above & below, key=str)
    if not both:
        raise Refusal(
            where,
            str(IFML.Form),
            "the edited block is inside no ifml:Form with seam:writes: the traced lines around it name "
            f"{', '.join(sorted(str(f) for f in above)) or 'no form'} above and "
            f"{', '.join(sorted(str(f) for f in below)) or 'no form'} below",
        )
    if len(both) > 1:
        raise Refusal(where, str(IFML.Form), f"the edited block is inside {len(both)} forms: {', '.join(both)}")
    return both[0]


def _namespace(iri: URIRef) -> str:
    text = str(iri)
    return text[: max(text.rfind("/"), text.rfind("#")) + 1]


def _graph(ds: Dataset, subject: URIRef, kind: URIRef) -> URIRef:
    graphs = sorted(
        {g for _s, _p, _o, g in ds.quads((subject, RDF.type, kind, None)) if isinstance(g, URIRef)}, key=str
    )
    if len(graphs) != 1:
        raise Refusal(subject, RDF.type, f"is typed {kind} in {len(graphs)} graphs; a structural edit needs one")
    return graphs[0]


def _written_shape(ds: Dataset, form: URIRef) -> URIRef:
    shapes = sorted({o for o in ds.objects(form, SEAM.writes) if isinstance(o, URIRef)}, key=str)
    if len(shapes) != 1:
        raise Refusal(form, SEAM.writes, f"writes {len(shapes)} shapes; a structural edit needs one")
    return shapes[0]


def _shape_paths(ds: Dataset, shape: URIRef, name: str) -> list[URIRef]:
    paths = {ds.value(node, SH.path) for node in ds.objects(shape, SH.property)}
    return sorted((p for p in paths if isinstance(p, URIRef) and local_name(p) == name), key=str)


def _used(ds: Dataset, term: URIRef) -> bool:
    return any(True for _ in ds.quads((term, None, None, None))) or any(
        True for _ in ds.quads((None, None, term, None))
    )


def _removal(ds: Dataset, form: URIRef, control: Control) -> tuple[Patch, URIRef, URIRef]:
    bound = [
        (p, path)
        for p in ds.objects(form, IFML.hasParameter)
        if isinstance(p, URIRef)
        and isinstance(path := ds.value(p, IFML.boundTo), URIRef)
        and local_name(path) == control.name
    ]
    bound.sort(key=lambda b: str(b[0]))
    if len(bound) != 1:
        listed = ", ".join(str(p) for p, _ in bound)
        raise Refusal(
            form,
            IFML.hasParameter,
            f"{len(bound)} parameters of the form are ifml:boundTo a path named {control.name!r}"
            + (f": {listed}" if listed else ""),
        )
    param, path = bound[0]
    removes: list[Quad] = []
    for s, p, o, g in ds.quads((param, None, None, None)):
        assert g is not None  # a Dataset quad always names its graph
        removes.append((s, p, o, g))
    for s, p, o, g in ds.quads((None, None, param, None)):
        if (s, p) != (form, IFML.hasParameter):
            raise Refusal(s, p, f"refers to {param}, so removing the parameter would leave it dangling")
        assert g is not None
        removes.append((s, p, o, g))
    return Patch(removes=removes), param, path


def _new_property(control: Control, path: URIRef, graph: URIRef) -> list[Quad]:
    """A blank-node sh:property for ``path`` with the values the edited control states."""
    node = BNode(f"structural_{control.name}")
    kind = control.attribute("type")
    if control.element == "textarea":
        values: list[tuple[URIRef, Node]] = [(SH.datatype, XSD.string), (DASH.editor, DASH.TextAreaEditor)]
    elif control.element == "input" and kind == "datetime-local":
        values = [(SH.datatype, XSD.dateTime)]
    elif control.element == "input" and kind in (None, "text"):
        values = [(SH.datatype, XSD.string)]
    else:
        shown = control.element + (f' type="{kind}"' if kind is not None else "")
        raise Refusal(
            path,
            SH.datatype,
            f"no field kind of the htmx generator writes <{shown}>: a new path takes a textarea, "
            'an input type="text" or an input type="datetime-local"',
        )
    max_length = control.attribute("maxlength")
    if max_length is not None:
        if not max_length.isdigit():
            raise Refusal(path, SH.maxLength, f"maxlength {max_length!r} is not a non-negative integer")
        values.append((SH.maxLength, Literal(int(max_length))))
    if control.attribute("required") is not None:
        values.append((SH.minCount, Literal(1)))
    values.append((SH.name, Literal(control.name)))
    quads: list[Quad] = [(node, SH.path, path, graph)]
    return quads + [(node, p, o, graph) for p, o in values]


def _addition(ds: Dataset, form: URIRef, control: Control) -> tuple[Patch, URIRef, URIRef]:
    if not _NAME.match(control.name):
        raise Refusal(form, IFML.hasParameter, f"the control name {control.name!r} is not a usable path local name")
    form_graph = _graph(ds, form, IFML.Form)
    param = URIRef(f"{_namespace(form)}{control.name}_input")
    if _used(ds, param):
        raise Refusal(param, RDF.type, "the minted parameter IRI is already in the model")
    shape = _written_shape(ds, form)
    adds: list[Quad] = [
        (form, IFML.hasParameter, param, form_graph),
        (param, RDF.type, IFML.Parameter, form_graph),
        (param, RDFS.label, Literal(f"{control.name} input"), form_graph),
    ]
    adds += [(param, SEAM.inModel, m, form_graph) for m in sorted(ds.objects(form, SEAM.inModel), key=str)]
    paths = _shape_paths(ds, shape, control.name)
    if len(paths) > 1:
        raise Refusal(shape, SH.property, f"{len(paths)} sh:property paths are named {control.name!r}")
    if paths:
        path = paths[0]
    else:
        shape_graph = _graph(ds, shape, SH.NodeShape)
        path = URIRef(f"{_namespace(shape)}{control.name}")
        properties = _new_property(control, path, shape_graph)
        adds.append((shape, SH.property, properties[0][0], shape_graph))
        adds += properties
        if not any((path, RDF.type, t, None) in ds for t in PROPERTY_TYPES):
            adds.append((path, RDF.type, RDF.Property, shape_graph))
    adds.append((param, IFML.boundTo, path, form_graph))
    return Patch(adds=adds), param, path


def _reproduce(
    output: str, old: list[str], edited: list[str], block: Block, regenerated: writeback.Regenerated, about: Quad
) -> tuple[Effect, ...]:
    """Require the regenerated ``output`` to be the edit, with changes outside the block
    allowed; return those changes as effects."""
    old_hex = regenerated.old_hash.removeprefix("sha256:")
    new_hex = regenerated.new_hash.removeprefix("sha256:")
    subject, predicate = about[0], about[1]
    actual_text = regenerated.texts.get(output)
    if actual_text is None:
        raise Refusal(subject, predicate, f"regenerating no longer writes {output}")
    before = [line.replace(old_hex, new_hex) for line in old]
    after = [line.replace(old_hex, new_hex) for line in edited]
    actual = actual_text.splitlines(keepends=True)
    outside = [
        (i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before, actual, autojunk=False).get_opcodes()
        if tag != "equal" and (i2 < block.start or i1 > block.end)
    ]
    replaced = [(block.start, block.end, after[block.new_start : block.new_end])]
    replaced += [(i1, i2, actual[j1:j2]) for i1, i2, j1, j2 in outside]
    expected = list(before)
    for i1, i2, lines in sorted(replaced, key=lambda r: r[0], reverse=True):
        expected[i1:i2] = lines
    if expected != actual:
        raise Refusal(subject, predicate, writeback.first_difference(output, "".join(expected), actual_text))
    plain_before = [line.rstrip("\r\n") for line in before]
    plain_actual = [line.rstrip("\r\n") for line in actual]
    return tuple(e for op in outside for e in writeback.line_effects(output, plain_before, plain_actual, op))


def _draft(
    index: GenerationIndex, ds: Dataset, output: str, edited_text: str
) -> tuple[Kind["add", "remove"], Control, URIRef, URIRef, URIRef, Block, Patch]:
    shown = index.output(output)
    if shown is None or shown.text is None:
        raise Refusal(output, "output", "the generation index has no readable output of this name")
    old, edited = shown.text.splitlines(keepends=True), edited_text.splitlines(keepends=True)
    block = changed_block(output, old, edited)
    removed_side = named_controls("".join(old[block.start : block.end]))
    added_side = named_controls("".join(edited[block.new_start : block.new_end]))
    removed_names, added_names = {c.name for c in removed_side}, {c.name for c in added_side}
    removed = [c for c in removed_side if c.name not in added_names]
    added = [c for c in added_side if c.name not in removed_names]
    where = f"{output}:{block.start + 1}"
    if len(removed) + len(added) != 1:
        names = ", ".join(sorted({f"+{c.name}" for c in added} | {f"-{c.name}" for c in removed})) or "none"
        raise Refusal(
            where,
            "controls",
            "a structural edit adds or removes one named input, textarea or select; "
            f"this block adds and removes {names}",
        )
    form = enclosing_form(index, ds, output, block)
    if added:
        patch, param, path = _addition(ds, form, added[0])
        return "add", added[0], form, param, path, block, patch
    patch, param, path = _removal(ds, form, removed[0])
    return "remove", removed[0], form, param, path, block, patch


def propose(
    index: GenerationIndex, ds: Dataset, project_dir: Path, model_path: Path, output: str, edited_text: str
) -> Structural:
    """Draft and check the model patch for ``edited_text`` (the whole edited ``output``),
    which adds or removes one form input; raises ``Refusal`` naming the fact.
    Writes no model file."""
    try:
        kind, control, form, param, path, block, patch = _draft(index, ds, output, edited_text)
        about = (patch.removes or patch.adds)[0]
        regenerated = writeback.regenerate(project_dir, model_path, patch, about[0], about[1])
        shown = index.output(output)
        assert shown is not None and shown.text is not None  # _draft checked both
        old, edited = shown.text.splitlines(keepends=True), edited_text.splitlines(keepends=True)
        same_output = _reproduce(output, old, edited, block, regenerated, about)
    except Refusal as err:
        logger.warning("structural edit refused %s: %s %s: %s", output, err.subject, err.predicate, err.detail)
        raise
    result = Structural(
        output=output,
        kind=kind,
        field=control.name,
        form=str(form),
        parameter=str(param),
        path=str(path),
        first=block.start + 1,
        last=block.end,
        patch=patch,
        files=regenerated.files,
        effects=tuple(
            sorted(
                same_output + writeback.effects(index, regenerated, output),
                key=lambda e: (e.output, e.line, e.before, e.after),
            )
        ),
    )
    logger.info(
        "structural edit drafted %s:%s: %s %s %s %s (+%d -%d quads) in %s (%d other lines change)",
        output,
        result.first,
        result.kind,
        term_text(param),
        "to" if kind == "add" else "from",
        term_text(form),
        len(patch.adds),
        len(patch.removes),
        ", ".join(result.files),
        len(result.effects),
    )
    return result
