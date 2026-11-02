"""The XML payload writer: BPMN and DMN files saved and element ids renamed (ADR-0017).

Like the TriG writer, it never re-serialises a file. ``save_payload`` checks that the
new XML parses and writes it as given. ``rename_id`` edits the text of the payload at
each place the id is written (the element's ``id``, each reference to it) and leaves
every other byte alone, then builds the patch that moves the model's quads from the old
lifted IRI ``modelIRI#old`` to ``modelIRI#new``. It writes the payload and the model
files together or not at all: the atomic update ADR-0002 (rule 5) prefers.

The payload and the model IRI must come from the loaded model: the payload is a file
some model's ``seam:renderPayload`` names, and the model IRI is that model's.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from rdflib import Dataset
from rdflib.term import BNode, Literal, Node, URIRef
from seams import DEC, SEAM
from seams import payload_path as resolve_payload

from .files import EditRecord, Source, commit, read_source, read_sources, route, span, write_all
from .patch import Patch, PatchError, Quad
from .trig import text_quads

# An XML id is an NCName: a name without a colon.
_NCNAME = re.compile(r"[^\W\d][\w.\-]*")

# Attributes whose value is an element id. Every ``...Ref`` attribute is one too
# (sourceRef, targetRef, attachedToRef, processRef, messageRef, errorRef, dmnElementRef
# and the rest) except ``typeRef``, which names a type. ``href="#id"`` is DMN's form.
_ID_ATTRIBUTES = frozenset({"bpmnElement", "default", "calledElement", "sourceElement", "targetElement"})
# Elements whose text is an element id: BPMN's incoming and outgoing flows, and the
# ``...Ref``/``...Refs`` elements (flowNodeRef, sourceRef, dataInputRefs and the rest).
_ID_ELEMENTS = frozenset({"incoming", "outgoing"})


def _local(name: str) -> str:
    return name.rpartition("}")[2].rpartition(":")[2]


def _is_reference_attribute(name: str) -> bool:
    local = _local(name)
    return local in _ID_ATTRIBUTES or (local.endswith("Ref") and local != "typeRef")


def _is_reference_element(name: str) -> bool:
    local = _local(name)
    return local in _ID_ELEMENTS or local.endswith(("Ref", "Refs"))


def _renamed_attribute(name: str, value: str, old: str, new: str) -> str | None:
    """The attribute's new value when it names ``old``; None otherwise."""
    local = _local(name)
    if local == "id" and value == old:
        return new
    if local == "href" and value == f"#{old}":
        return f"#{new}"
    if _is_reference_attribute(name) and value == old:
        return new
    return None


def _renamed_text(text: str, old: str, new: str) -> str | None:
    """An id element's new text when it is ``old`` (whitespace kept); None otherwise."""
    if text.strip() != old:
        return None
    start = text.index(old)
    return text[:start] + new + text[start + len(old) :]


# ── reading the XML ──


def _parser() -> etree.XMLParser:
    # No entities expanded, no network: a payload is data, never a fetch.
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def _parse(path: Path, data: bytes) -> etree._Element:  # pyright: ignore[reportPrivateUsage]
    """The parsed payload; PatchError naming the line when it is not well-formed XML."""
    try:
        return etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as exc:
        raise PatchError(path, f"line {exc.lineno}", f"the payload is not well-formed XML: {exc.msg}") from None


def _ids(root: etree._Element) -> set[str]:  # pyright: ignore[reportPrivateUsage]
    return {
        str(value)
        for el in root.iter()
        if isinstance(el.tag, str)
        for name, value in el.attrib.items()
        if _local(str(name)) == "id"
    }


# ── the model ──


@dataclass(frozen=True)
class _Model:
    sources: tuple[Source, ...]
    ds: Dataset
    payloads: dict[Path, frozenset[URIRef]]  # payload file -> the models rendering it


def _model(model_files: Iterable[str | os.PathLike[str]]) -> _Model:
    sources = read_sources(model_files)
    ds = Dataset(default_union=True)
    payloads: dict[Path, set[URIRef]] = {}
    for source in sources:
        own = Dataset(default_union=True)
        own.parse(data=source.text, format="trig", publicID=source.base)
        for model, payload in own.subject_objects(SEAM.renderPayload):
            if isinstance(model, URIRef):
                payloads.setdefault(resolve_payload(payload, source.path.parent).resolve(), set()).add(model)
        ds.parse(data=source.text, format="trig", publicID=source.base)
    return _Model(sources, ds, {path: frozenset(models) for path, models in payloads.items()})


def _payload(model: _Model, payload_path: str | os.PathLike[str]) -> Path:
    path = Path(payload_path).resolve()
    if path not in model.payloads:
        raise PatchError(path, SEAM.renderPayload, "no model of these files names this payload")
    return path


# ── save ──


def save_payload(
    model_files: Iterable[str | os.PathLike[str]], payload_path: str | os.PathLike[str], new_xml: str | bytes
) -> EditRecord:
    """Write ``new_xml`` as the payload file ``payload_path``; return the record.

    ``model_files`` are the model's TriG files (``seams.load(...).files``); one of them
    must name the payload by ``seam:renderPayload``. The XML is parsed first and written
    as given, so a modeler's own layout is kept. Raises PatchError, writing nothing,
    when the XML is not well-formed or the payload is not the model's. The same bytes
    write nothing. The record's one edit is the payload's span; ``undo`` puts it back.
    """
    path = _payload(_model(model_files), payload_path)
    data = new_xml.encode("utf-8") if isinstance(new_xml, str) else new_xml
    _parse(path, data)
    before = read_source(path, "payload").data
    if data == before:
        return EditRecord(Patch(), ())
    write_all({path: (before, data)})
    return EditRecord(Patch(), (span(path, Patch(), before, data, payload=True),))


# ── rename ──


def _rename_text(text: str, old: str, new: str) -> str:
    """The payload text with every id and reference ``old`` written as ``new``.

    A scan of the text: comments, CDATA, processing instructions and the doctype are
    passed over; in each start tag, attribute values that name the id are replaced;
    the first text of an id element (``<incoming>old</incoming>``) is replaced when it
    is the id. Everything else is copied byte for byte.
    """
    out: list[str] = []
    stack: list[str] = []
    after_start = False
    pos = 0
    for match in _TOKEN.finditer(text):
        if match.start() > pos:
            segment = text[pos : match.start()]
            renamed = _renamed_text(segment, old, new) if after_start and _is_reference_element(stack[-1]) else None
            out.append(renamed if renamed is not None else segment)
        token = match.group()
        after_start = False
        if match["tag"]:
            out.append(_ATTRIBUTE.sub(lambda m: _attribute(m, old, new), token))
            if not token.endswith("/>"):
                stack.append(match["tag"])
                after_start = True
        else:
            if match["end"]:
                if not stack or stack[-1] != match["end"]:
                    raise PatchError(match["end"], "end tag", "the payload's tags do not nest")
                stack.pop()
            out.append(token)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


_TOKEN = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE(?:[^\[>]|\[.*?\])*>"
    r"|</(?P<end>[^\s>]+)\s*>"
    r"|<(?P<tag>[^\s/>!?]+)(?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*\s*/?>",
    re.DOTALL,
)
_ATTRIBUTE = re.compile(r"(?P<lead>\s+(?P<name>[^\s=/>]+)\s*=\s*)(?P<q>[\"'])(?P<value>.*?)(?P=q)", re.DOTALL)


def _attribute(match: re.Match[str], old: str, new: str) -> str:
    renamed = _renamed_attribute(match["name"], match["value"], old, new)
    if renamed is None:
        return match.group()
    return f"{match['lead']}{match['q']}{renamed}{match['q']}"


def _renamed_tree(root: etree._Element, old: str, new: str) -> None:  # pyright: ignore[reportPrivateUsage]
    """Apply the same rename to a parsed tree: what the edited text must parse to."""
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for name, value in list(el.attrib.items()):
            renamed = _renamed_attribute(str(name), str(value), old, new)
            if renamed is not None:
                el.set(name, renamed)
        if el.text is not None and _is_reference_element(el.tag):
            renamed = _renamed_text(el.text, old, new)
            if renamed is not None:
                el.text = renamed


def _canonical(root: etree._Element) -> bytes:  # pyright: ignore[reportPrivateUsage]
    return etree.tostring(root, method="c14n")


def _quad_rename(model: _Model, model_iri: URIRef, old: str, new: str) -> Patch:
    """The patch moving the model's quads from ``modelIRI#old`` to ``modelIRI#new``.

    Every quad with the old IRI as subject or object is replaced. A decision
    ``seam:inModel`` the model that names the old id by ``dec:payloadElement`` gets the
    new id. A blank node object of the old IRI is written inside its pair, so it moves
    with all of its triples under a fresh node.
    """
    old_iri, new_iri = URIRef(f"{model_iri}#{old}"), URIRef(f"{model_iri}#{new}")
    quads = [q for source in model.sources for q in text_quads(source.text, base=source.base)]
    decisions = set(model.ds.subjects(SEAM.inModel, model_iri))
    by_subject: dict[Node, list[Quad]] = {}
    for q in quads:
        by_subject.setdefault(q[0], []).append(q)
    moved: set[Quad] = set()
    removes: set[Quad] = set()
    adds: set[Quad] = set()
    fresh: dict[Node, BNode] = {}

    def node(term: Node) -> Node:
        if term == old_iri:
            return new_iri
        if isinstance(term, BNode) and term in fresh:
            return fresh[term]
        return term

    def move_inside(blank: BNode) -> None:
        if blank in fresh:
            return
        fresh[blank] = BNode(f"seamsrename{len(fresh)}")
        for q in by_subject.get(blank, []):
            moved.add(q)
            if isinstance(q[2], BNode):
                move_inside(q[2])

    for q in quads:
        s, p, o, g = q
        if s == old_iri and isinstance(o, BNode):
            move_inside(o)
        if old_iri in (s, o):
            moved.add(q)
        elif p == DEC.payloadElement and s in decisions and isinstance(o, Literal) and str(o) == old:
            removes.add(q)
            adds.add((s, p, Literal(new, lang=o.language, datatype=o.datatype), g))
    adds |= {(node(s), p, node(o), g) for s, p, o, g in moved}
    return Patch(adds=adds, removes=removes | moved)


def rename_id(
    model_files: Iterable[str | os.PathLike[str]],
    payload_path: str | os.PathLike[str],
    model_iri: object,
    old: str,
    new: str,
) -> EditRecord:
    """Rename the payload element ``old`` to ``new`` and every model quad with it.

    The payload's ``id="old"`` and each reference to it (``...Ref`` attributes and
    elements, ``bpmnElement``, ``default``, ``incoming``/``outgoing``, DMN's
    ``href="#old"``) are rewritten in place; the model's quads naming
    ``<model_iri#old>`` move to ``<model_iri#new>``, and a decision of the model whose
    ``dec:payloadElement`` is ``old`` gets ``new``. ``model_iri`` must be a model whose
    ``seam:renderPayload`` is the payload. All the files are written together or none.

    Raises PatchError, writing nothing, when ``old`` is not an id of the payload, ``new``
    already is one or is not an XML name, the model does not render the payload, or the
    edited text would not parse to the payload with the id renamed.
    """
    model = _model(model_files)
    path = _payload(model, payload_path)
    iri = URIRef(str(model_iri))
    subject = URIRef(f"{iri}#{old}")
    if iri not in model.payloads[path]:
        raise PatchError(iri, SEAM.renderPayload, f"the model does not render {path.name}")
    if not _NCNAME.fullmatch(new):
        raise PatchError(subject, "id", f"{new!r} is not an XML id")
    source = read_source(path, "payload")
    root = _parse(path, source.data)
    ids = _ids(root)
    if old not in ids:
        raise PatchError(subject, "id", f"{path.name} has no element with id {old!r}")
    if new in ids:
        raise PatchError(subject, "id", f"{path.name} already has an element with id {new!r}")
    text = _rename_text(source.text, old, new)
    _renamed_tree(root, old, new)
    if _canonical(_parse(path, text.encode("utf-8"))) != _canonical(root):
        raise PatchError(subject, "id", f"the edited {path.name} does not parse to the payload with the id renamed")
    patch = _quad_rename(model, iri, old, new)
    sources = {s.path: s for s in model.sources}
    shares = route(model.sources, patch) if not patch.is_empty else {}
    return commit(patch, sources, shares, {path: (source.data, text.encode("utf-8"))})
