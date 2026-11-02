"""Edit mode's forms from shapes and the patches they save (ADR-0017, backlog I2).

``form_fields`` builds an element's form from the SHACL shapes that target it: the
seam shapes (ontology/shapes/seam-shapes.ttl) and any shapes in the model itself.
Each property shape with an IRI ``sh:path`` gives one field, with its name, datatype,
``sh:in`` options, counts, order and the element's current values. ``build_patch``
turns a submitted field into a ``seams_edit.Patch``. ``palette`` lists the classes an
attached domain profile offers (ADR-0018), with the profile's labels.

Nothing here refuses a value because a shape would: an edit that breaks the shapes is
saved and flagged on the health badge (principle 5). Only a value the patch cannot
state (a malformed IRI, a blank-node value the form cannot rewrite) raises
``PatchError``. The module writes nothing; the viewer saves through ``seams_edit``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import rdflib
from rdflib import RDF, RDFS, XSD, BNode, Dataset, Literal, URIRef
from rdflib.collection import Collection
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import SH
from rdflib.term import Node

from seams_edit import Patch, PatchError, Quad
from viewer.profiles import Profile
from viewer.validation import ONTOLOGY_FILES, SHAPES_FILE

# Characters an IRI may not contain (RFC 3987 excludes them; Turtle cannot write them).
_IRI_FORBIDDEN = set(' <>"{}|^`\\\t\n\r')

_shapes: rdflib.Graph | None = None
_ontology: rdflib.Graph | None = None


def _seam_shapes() -> rdflib.Graph:
    global _shapes
    if _shapes is None:
        _shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    return _shapes


def _ontology_graph() -> rdflib.Graph:
    """The ontology files, for subclass closure and property labels."""
    global _ontology
    if _ontology is None:
        g = rdflib.Graph()
        for p in ONTOLOGY_FILES:
            g.parse(p, format="turtle")
        _ontology = g
    return _ontology


def ontology_graph() -> rdflib.Graph:
    """The SemanticSeams ontology files, read once (the IFML diagram's swap strategies)."""
    return _ontology_graph()


@dataclass(frozen=True)
class FormField:
    """One shaped property of an element, as the edit form shows it.

    ``kind`` is the widget: "select" for an ``sh:in`` list, "checkbox" for
    ``xsd:boolean``, "text" otherwise. ``iri_valued`` fields take IRIs (the options or
    the current values are IRIs, or a shape asks for ``sh:class`` or ``sh:nodeKind
    sh:IRI``). ``editable`` is false when a current value is a blank node, which the
    form cannot rewrite.
    """

    path: str
    name: str
    kind: str
    datatype: str | None
    options: tuple[str, ...]
    min_count: int | None
    max_count: int | None
    order: float | None
    values: tuple[str, ...]
    iri_valued: bool
    editable: bool
    shapes: tuple[str, ...]
    messages: tuple[str, ...]


def subject_graphs(ds: Dataset, iri: str) -> list[Node]:
    """The graphs that state triples about ``iri``, the one with its rdf:type first."""
    subject = URIRef(iri)
    typed = {g for _s, _p, _o, g in ds.quads((subject, RDF.type, None, None)) if g is not None}
    every = {g for _s, _p, _o, g in ds.quads((subject, None, None, None)) if g is not None}
    return sorted(typed, key=str) + sorted(every - typed, key=str)


def element_graph(ds: Dataset, iri: str) -> Node | None:
    """The element's own graph, where new triples about it go; None if no graph has it."""
    graphs = subject_graphs(ds, iri)
    return graphs[0] if graphs else None


def _classes(ds: Dataset, subject: URIRef) -> set[Node]:
    """The element's types and their superclasses in the ontology and the model."""
    ontology = _ontology_graph()
    found: set[Node] = set()
    for t in set(ds.objects(subject, RDF.type)):
        found.update(ontology.transitive_objects(t, RDFS.subClassOf))
        found.update(ds.transitive_objects(t, RDFS.subClassOf))
    return found


def _targets(shapes: rdflib.Graph, shape: Node, ds: Dataset, subject: URIRef, classes: set[Node]) -> bool:
    """Whether ``shape`` has ``subject`` as a focus node (SHACL 2.1.3)."""
    if any(c in classes for c in shapes.objects(shape, SH.targetClass)):
        return True
    if shape in classes and ((shape, RDF.type, RDFS.Class) in shapes or (shape, RDF.type, RDFS.Class) in ds):
        return True
    if subject in set(shapes.objects(shape, SH.targetNode)):
        return True
    if any((subject, p, None) in ds for p in shapes.objects(shape, SH.targetSubjectsOf)):
        return True
    return any((None, p, subject) in ds for p in shapes.objects(shape, SH.targetObjectsOf))


def _int(value: Node | None) -> int | None:
    return int(value) if isinstance(value, Literal) and isinstance(value.toPython(), int) else None


def _number(value: Node | None) -> float | None:
    if isinstance(value, Literal) and isinstance(value.toPython(), (int, float)):
        return float(value.toPython())
    return None


def _term_text(term: Node) -> str:
    return str(term)


@dataclass
class _Acc:
    name: str | None = None
    datatype: str | None = None
    options: tuple[Node, ...] = ()
    min_count: int | None = None
    max_count: int | None = None
    order: float | None = None
    wants_iri: bool = False
    shapes: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()


def _merge(acc: _Acc, shapes: rdflib.Graph, shape: Node, prop: Node) -> None:
    """Fold one property shape into the field: the tightest counts, the first name,
    datatype and options, every shape and message."""
    name = shapes.value(prop, SH.name)
    if acc.name is None and name is not None:
        acc.name = str(name)
    datatype = shapes.value(prop, SH.datatype)
    if acc.datatype is None and datatype is not None:
        acc.datatype = str(datatype)
    options = shapes.value(prop, SH["in"])
    if not acc.options and options is not None:
        acc.options = tuple(Collection(shapes, options))
    lo, hi = _int(shapes.value(prop, SH.minCount)), _int(shapes.value(prop, SH.maxCount))
    if lo is not None:
        acc.min_count = lo if acc.min_count is None else max(acc.min_count, lo)
    if hi is not None:
        acc.max_count = hi if acc.max_count is None else min(acc.max_count, hi)
    order = _number(shapes.value(prop, SH.order))
    if order is not None:
        acc.order = order if acc.order is None else min(acc.order, order)
    if shapes.value(prop, SH["class"]) is not None or shapes.value(prop, SH.nodeKind) == SH.IRI:
        acc.wants_iri = True
    acc.shapes = tuple(sorted(set(acc.shapes) | ({str(shape)} if isinstance(shape, URIRef) else set())))
    message = shapes.value(prop, SH.message)
    if message is not None:
        acc.messages = tuple(sorted(set(acc.messages) | {str(message)}))


def _label(ds: Dataset, shapes: rdflib.Graph, path: URIRef) -> str:
    label = _ontology_graph().value(path, RDFS.label) or ds.value(path, RDFS.label)
    if label is not None:
        return str(label)
    for g in (ds, shapes):
        try:
            return g.namespace_manager.normalizeUri(path)
        except Exception:
            continue
    return str(path)


def form_fields(ds: Dataset, iri: str, profile_shapes: rdflib.Graph | None = None) -> list[FormField]:
    """The element's form: one field per IRI ``sh:path`` of the shapes that target it.

    ``profile_shapes`` are the attached domain profile's shapes (ADR-0018), read after
    the seam shapes and before the model's own. Sorted by ``sh:order`` (unordered
    fields last), then name, then path, so the same model gives the same form.
    """
    subject = URIRef(iri)
    classes = _classes(ds, subject)
    acc: dict[URIRef, _Acc] = {}
    sources = (_seam_shapes(), *(() if profile_shapes is None else (profile_shapes,)), ds)
    for shapes in sources:
        for shape in sorted(set(shapes.subjects(RDF.type, SH.NodeShape)), key=str):
            if not _targets(shapes, shape, ds, subject, classes):
                continue
            for prop in sorted(set(shapes.objects(shape, SH.property)), key=str):
                path = shapes.value(prop, SH.path)
                if isinstance(path, URIRef):
                    _merge(acc.setdefault(path, _Acc()), shapes, shape, prop)

    fields: list[FormField] = []
    for path, a in acc.items():
        current = sorted(set(ds.objects(subject, path)), key=_term_text)
        iri_valued = (
            a.wants_iri or any(isinstance(o, URIRef) for o in a.options) or any(isinstance(v, URIRef) for v in current)
        )
        kind = "select" if a.options else "checkbox" if a.datatype == str(XSD.boolean) else "text"
        fields.append(
            FormField(
                path=str(path),
                name=a.name or _label(ds, _seam_shapes(), path),
                kind=kind,
                datatype=a.datatype,
                options=tuple(_term_text(o) for o in a.options),
                min_count=a.min_count,
                max_count=a.max_count,
                order=a.order,
                values=tuple(_term_text(v) for v in current),
                iri_valued=iri_valued,
                editable=not any(isinstance(v, BNode) for v in current),
                shapes=a.shapes,
                messages=a.messages,
            )
        )
    return sorted(fields, key=lambda f: (f.order is None, f.order or 0.0, f.name, f.path))


def palette(profile: Profile) -> list[dict[str, str]]:
    """The classes the editor offers under ``profile`` (ADR-0018), in IRI order.

    Each entry is the class IRI, its prefixed name and its label: the profile's
    (skos:prefLabel, else rdfs:label), else the ontology's rdfs:label, else the
    prefixed name, which is what the editor shows without a profile.
    """
    ontology = _ontology_graph()
    entries: list[dict[str, str]] = []
    for cls in profile.classes:
        try:
            qname = ontology.namespace_manager.normalizeUri(cls)
        except Exception:
            qname = str(cls)
        fallback = ontology.value(cls, RDFS.label)
        label = profile.labels.get(cls) or (str(fallback) if fallback is not None else qname)
        entries.append({"iri": str(cls), "qname": qname, "label": label})
    return entries


def _iri(ds: Dataset, subject: str, path: str, text: str) -> URIRef:
    """A submitted IRI: absolute, or a prefixed name the model declares."""
    prefix, _, local = text.partition(":")
    namespaces = dict(ds.namespace_manager.namespaces())
    if prefix in namespaces and not local.startswith("//"):
        text = f"{namespaces[prefix]}{local}"
    if not urlsplit(text).scheme or any(c in _IRI_FORBIDDEN for c in text):
        raise PatchError(subject, path, f"not an IRI: {text!r}")
    return URIRef(text)


def _literal(text: str, datatype: str | None, language: str | None) -> Literal:
    """A typed literal when the text is a valid form of the field's datatype, else a
    plain string: the shapes flag it, the form does not refuse it (principle 5)."""
    if datatype and datatype != str(XSD.string):
        typed = Literal(text, datatype=URIRef(datatype))
        if not typed.ill_typed:
            return typed
        return Literal(text)
    if language:
        return Literal(text, lang=language)
    return Literal(text)


def _new_terms(ds: Dataset, iri: str, field: FormField, values: Iterable[str], current: list[Node]) -> set[Node]:
    texts = sorted({v.strip() for v in values if v.strip()})
    if field.kind == "checkbox":
        texts = ["true" if "true" in texts else "false"]
    if field.iri_valued:
        return {_iri(ds, iri, field.path, t) for t in texts}
    languages = {v.language for v in current if isinstance(v, Literal)}
    language = next(iter(languages)) if len(languages) == 1 else None
    return {_literal(t, field.datatype, language) for t in texts}


def build_patch(ds: Dataset, iri: str, field: FormField, new_values: Iterable[str]) -> Patch:
    """The patch that gives ``iri`` exactly ``new_values`` for ``field``.

    Values that stay are not touched, so an unchanged field is an empty patch. A
    removed value goes from the graph that states it; an added one goes to the
    element's own graph.
    """
    subject, path = URIRef(iri), URIRef(field.path)
    stated = sorted(
        {(o, g) for _s, _p, o, g in ds.quads((subject, path, None, None)) if g is not None},
        key=lambda pair: (_term_text(pair[0]), str(pair[1])),
    )
    current = [o for o, _g in stated]
    if any(isinstance(o, BNode) for o in current):
        raise PatchError(iri, field.path, "a current value is a blank node, which the form cannot rewrite")
    new = _new_terms(ds, iri, field, new_values, current)
    removes: list[Quad] = [(subject, path, o, g) for o, g in stated if o not in new]
    graph = element_graph(ds, iri) or DATASET_DEFAULT_GRAPH_ID
    adds: list[Quad] = [(subject, path, o, graph) for o in new if o not in set(current)]
    return Patch(adds=adds, removes=removes)
