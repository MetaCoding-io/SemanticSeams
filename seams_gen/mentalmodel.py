"""The SemPKM Mental Model generator (M024/S03, backlog O5, ADR-0026).

``extract_mentalmodel`` reads the model's one ``seam:Ontology`` model, its
target-classed shapes and its IFML lists and details views into a frozen
``MentalModel``; ``render_mentalmodel`` writes the package SemPKM installs:

- ``manifest.yaml``: ``modelId`` from the ontology IRI's local name
  (lowercased, ``_`` replaced by ``-``), ``version`` its one
  ``owl:versionInfo``, ``name`` its one ``rdfs:label``, ``description`` its
  ``rdfs:comment`` when stated, ``namespace`` and ``entrypoints`` fixed by
  SemPKM. Keys in that order, every value a JSON string (ADR-0026 section 4).
- ``ontology/<modelId>.jsonld``: the ontology node, with its label, version,
  comment, ``owl:imports`` and ``prov:wasDerivedFrom`` its version IRI.
- ``shapes/<modelId>.jsonld``: every shape with a ``sh:targetClass`` and every
  shape those reach by ``sh:node``, transitively, with their SHACL triples
  (and ``rdfs:label``, ``rdfs:comment``) and the blank nodes those reach;
  ``seam:`` facts are not copied (ADR-0001).
- ``views/<modelId>.jsonld``: one ``urn:sempkm:vocab:ViewSpec`` table per
  ``ifml:List`` or ``ifml:Details`` that ``seam:reads`` a shape, one column
  per ``Field.name`` and a SPARQL query with one ``OPTIONAL`` per field.

Package nodes (the ontology node, the shapes, the views) are minted at
``urn:sempkm:model:<modelId>:<local name>`` with ``prov:wasDerivedFrom`` the
model term; domain terms (classes, paths, members) keep their IRIs and only
appear as objects, since SemPKM refuses subjects outside its namespace
(ADR-0026 section 3). JSON-LD has no ``@context``: full IRIs, ``{"@id": …}``
for IRI objects, plain strings for ``xsd:string``, ``{"@value", "@type"}``
for other literals, blank nodes nested and RDF lists as ``{"@list": […]}``.
``@graph`` nodes are sorted by ``@id``, a shape's property shapes in
``Shape.fields()`` order and other multi-valued properties by value; a file
is sorted ``json.dumps`` plus a newline, with no header or model hash.

Faults, each a ``GeneratorError`` naming the fact (ADR-0026 section 10): no
ontology model or several (``seam:notation``); a ``modelId`` SemPKM refuses
(``rdf:type``); a missing, repeated or non-semver ``owl:versionInfo``; a
missing, repeated or over-long ``rdfs:label``; a repeated or over-long
``rdfs:comment``; a gistCore import other than 14.0.0 (``owl:imports``); two
package nodes with one local name (``rdf:type``); a view reading several
shapes (``seam:reads``) or a shape with no target class
(``sh:targetClass``); a field name that is not a SPARQL variable
(``sh:name``). A view ``ResolutionError`` is passed on as the
``GeneratorError`` on the same fact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rdflib import OWL, RDF, RDFS, XSD, BNode, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH
from rdflib.term import Node
from seams import IFML, SEAM, SEMPKM_GIST_VERSION, Model, local_name
from seams.views.shapes import Field, Shape

from . import GeneratorError
from ._views import view_errors
from .protocol import Files, Sources

PROV = Namespace("http://www.w3.org/ns/prov#")
VOCAB = Namespace("urn:sempkm:vocab:")
NAMESPACE = "urn:sempkm:model:{}:"
MANIFEST = "manifest.yaml"
KINDS = ("ontology", "shapes", "views")
RENDERER = "table"

# SemPKM's manifest schema (backend/app/models/manifest.py, ADR-0026 section 4).
MODEL_ID = re.compile(r"[a-z][a-z0-9-]*")
MODEL_ID_LENGTH = (2, 64)
SEMVER = re.compile(r"\d+\.\d+\.\d+")
NAME_LENGTH = 200
DESCRIPTION_LENGTH = 2000
# A SPARQL variable name, which a view's column must be (ADR-0026 section 8).
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Imports that start with this name a gistCore version (ADR-0022).
GIST_CORE = "https://w3id.org/semanticarts/ontology/gistCore"
# The predicates a shape keeps besides the SHACL namespace (ADR-0026 section 6).
ANNOTATIONS = (RDFS.label, RDFS.comment)
VIEW_TYPES = (IFML.List, IFML.Details)


@dataclass(frozen=True)
class Manifest:
    """The manifest's facts; ``description`` is None when the model states none."""

    model_id: str
    version: str
    name: str
    description: str | None

    @property
    def namespace(self) -> str:
        return NAMESPACE.format(self.model_id)

    def entrypoint(self, kind: str) -> str:
        return f"{kind}/{self.model_id}.jsonld"


@dataclass(frozen=True)
class Document:
    """One JSON-LD entrypoint: its kind (``ontology``, ``shapes`` or ``views``),
    its ``@graph`` nodes sorted by ``@id`` (JSON-ready, never mutated) and the
    full IRIs of the model elements it comes from."""

    kind: str
    nodes: tuple[Mapping[str, Any], ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class MentalModel:
    """The package: the manifest, its ontology IRI and the three documents in ``KINDS`` order."""

    manifest: Manifest
    ontology: str
    documents: tuple[Document, ...]


# ── the manifest (ADR-0026 sections 2 and 4) ──


def _ontology(model: Model) -> URIRef:
    """The one seam:Model with seam:notation seam:Ontology."""
    with view_errors():
        found = sorted(model.ontologies.iris(), key=str)
    if not found:
        detail = "a Mental Model is written for the model's seam:Ontology model, and there is none"
        raise GeneratorError(SEAM.Ontology, SEAM.notation, detail)
    if len(found) > 1:
        listed = ", ".join(model.compact(o) for o in found)
        detail = f"a Mental Model is written for one seam:Ontology model, found {listed}"
        raise GeneratorError(found[1], SEAM.notation, detail)
    return found[0]


def _values(model: Model, subject: URIRef, predicate: URIRef) -> list[Node]:
    return sorted(set(model.ds.objects(subject, predicate)), key=str)


def _model_id(model: Model, ontology: URIRef) -> str:
    model_id = local_name(ontology).lower().replace("_", "-")
    low, high = MODEL_ID_LENGTH
    if MODEL_ID.fullmatch(model_id) and low <= len(model_id) <= high:
        return model_id
    detail = (
        f'the modelId "{model_id}" from {model.compact(ontology)}\'s IRI must match {MODEL_ID.pattern} '
        f"and have {low} to {high} characters (SemPKM's manifest schema)"
    )
    raise GeneratorError(ontology, RDF.type, detail)


def _version(model: Model, ontology: URIRef) -> str:
    found = _values(model, ontology, OWL.versionInfo)
    if len(found) == 1 and isinstance(found[0], Literal) and SEMVER.fullmatch(str(found[0])):
        return str(found[0])
    listed = ", ".join(f'"{v}"' for v in found) or "none"
    detail = f"a Mental Model's version is one owl:versionInfo of the form MAJOR.MINOR.PATCH, found {listed}"
    raise GeneratorError(ontology, OWL.versionInfo, detail)


def _name(model: Model, ontology: URIRef) -> str:
    found = _values(model, ontology, RDFS.label)
    if len(found) == 1 and 1 <= len(str(found[0])) <= NAME_LENGTH:
        return str(found[0])
    listed = ", ".join(f'"{v}"' for v in found) or "none"
    detail = f"a Mental Model's name is one rdfs:label of 1 to {NAME_LENGTH} characters, found {listed}"
    raise GeneratorError(ontology, RDFS.label, detail)


def _description(model: Model, ontology: URIRef) -> str | None:
    found = _values(model, ontology, RDFS.comment)
    if not found:
        return None
    if len(found) == 1 and len(str(found[0])) <= DESCRIPTION_LENGTH:
        return str(found[0])
    detail = (
        f"a Mental Model's description is at most one rdfs:comment of at most {DESCRIPTION_LENGTH} characters, "
        f"found {len(found)} of {', '.join(str(len(str(v))) for v in found)} characters"
    )
    raise GeneratorError(ontology, RDFS.comment, detail)


def _imports(model: Model, ontology: URIRef) -> list[URIRef]:
    """Its owl:imports, sorted; a gistCore other than the one SemPKM bundles is a fault (ADR-0026 section 7)."""
    found = [i for i in _values(model, ontology, OWL.imports) if isinstance(i, URIRef)]
    for imported in found:
        if str(imported).startswith(GIST_CORE) and imported != SEMPKM_GIST_VERSION:
            detail = f"imports {imported}; a Mental Model states {SEMPKM_GIST_VERSION}, the gist SemPKM bundles"
            raise GeneratorError(ontology, OWL.imports, detail)
    return found


# ── JSON-LD terms (ADR-0026 section 9) ──


def _iri(iri: object) -> dict[str, str]:
    return {"@id": str(iri)}


def _literal(value: Literal) -> Any:
    if value.language:
        return {"@language": value.language, "@value": str(value)}
    if value.datatype is None or value.datatype == XSD.string:
        return str(value)
    return {"@type": str(value.datatype), "@value": str(value)}


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _one_or_many(values: list[Any]) -> Any:
    return values[0] if len(values) == 1 else values


def _copied(predicate: Node) -> bool:
    return str(predicate).startswith(str(SH)) or predicate in ANNOTATIONS


def _is_list(model: Model, node: Node) -> bool:
    return node == RDF.nil or (isinstance(node, BNode) and (node, RDF.first, None) in model.ds)


def _field_order(model: Model, node: Node) -> tuple[bool, int, str]:
    """``Shape.fields()``'s key for a property shape: sh:order (none last), then path IRI."""
    order = model.ds.value(node, SH.order)
    number = int(order) if isinstance(order, Literal) else None
    return (number is None, number or 0, str(model.ds.value(node, SH.path)))


class _Shapes:
    """Writes the shapes' SHACL triples, a ``sh:node`` to a written shape as its package IRI."""

    def __init__(self, model: Model, archive: Mapping[URIRef, str]) -> None:
        self.model = model
        self.archive = archive

    def value(self, predicate: Node, node: Node) -> Any:
        if _is_list(self.model, node):
            return {"@list": [self.value(predicate, item) for item in Collection(self.model.ds, node)]}
        if isinstance(node, BNode):
            return self.describe(node, {})
        if isinstance(node, Literal):
            return _literal(node)
        if predicate == SH.node and node in self.archive:
            return _iri(self.archive[node])
        return _iri(node)

    def describe(self, subject: Node, out: dict[str, Any]) -> dict[str, Any]:
        """``out`` plus ``subject``'s SHACL types and copied triples."""
        ds = self.model.ds
        types = sorted({str(t) for t in ds.objects(subject, RDF.type) if str(t).startswith(str(SH))})
        if types:
            out["@type"] = _one_or_many(types)
        pairs = {(p, o) for p, o in ds.predicate_objects(subject) if _copied(p)}
        for predicate in sorted({p for p, _ in pairs}, key=str):
            objects = [o for p, o in pairs if p == predicate]
            if predicate == SH.property:
                values = [self.value(predicate, o) for o in sorted(objects, key=lambda o: _field_order(self.model, o))]
            else:
                values = sorted((self.value(predicate, o) for o in objects), key=_key)
            out[str(predicate)] = _one_or_many(values)
        return out


def _reached(model: Model, start: URIRef) -> list[URIRef]:
    """The shapes ``start``'s copied triples name by ``sh:node``, through its blank nodes."""
    found: list[URIRef] = []
    stack: list[Node] = [start]
    seen: set[Node] = set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for predicate, value in model.ds.predicate_objects(node):
            if not _copied(predicate) and predicate not in (RDF.first, RDF.rest):
                continue
            if predicate == SH.node and isinstance(value, URIRef):
                found.append(value)
            elif isinstance(value, BNode):
                stack.append(value)
    return found


def _written_shapes(model: Model) -> tuple[list[Shape], list[URIRef]]:
    """The target-classed shapes, and every shape they reach by sh:node, by IRI."""
    with view_errors():
        targeted = [s for s in model.shapes if s.target_class is not None]
    written: set[URIRef] = set()
    stack = [s.iri for s in targeted]
    while stack:
        shape = stack.pop()
        if shape not in written:
            written.add(shape)
            stack.extend(_reached(model, shape))
    return targeted, sorted(written, key=str)


# ── views (ADR-0026 section 8) ──


@dataclass(frozen=True)
class _View:
    component: URIRef
    shape: Shape
    target: URIRef


def _views(model: Model) -> list[_View]:
    """One view per ifml:List or ifml:Details that seam:reads a shape, by component IRI."""
    out: list[_View] = []
    with view_errors():
        components = [c for c in model.interfaces.components() if any(t in VIEW_TYPES for t in c.types)]
        for component in components:
            reads = component.reads
            if not reads:
                continue
            if len(reads) > 1:
                listed = ", ".join(model.compact(s) for s in reads.iris())
                detail = f"a SemPKM view is a table of one shape's entities, and {model.compact(component.iri)} reads {listed}"
                raise GeneratorError(component.iri, SEAM.reads, detail)
            shape = reads[0]
            target = shape.target_class
            if target is None:
                detail = (
                    f"{model.compact(component.iri)} reads {model.compact(shape.iri)}, and a SemPKM view selects "
                    "its entities by the shape's sh:targetClass"
                )
                raise GeneratorError(shape.iri, SH.targetClass, detail)
            out.append(_View(component.iri, shape, target.iri))
    return out


def _columns(model: Model, shape: Shape) -> tuple[Field, ...]:
    with view_errors():
        fields = tuple(shape.fields())
    for field in fields:
        if not VARIABLE.fullmatch(field.name):
            detail = (
                f'the field name "{field.name}" of {model.compact(field.path)} is a view column and a SPARQL '
                f"variable, so it must match {VARIABLE.pattern}"
            )
            raise GeneratorError(shape.iri, SH.name, detail)
    return fields


def _pattern(field: Field) -> str:
    if field.node is not None:
        return f"OPTIONAL {{ ?s <{field.path}> [ <{field.node.free_path}> ?{field.name} ] }}"
    return f"OPTIONAL {{ ?s <{field.path}> ?{field.name} }}"


def query(target: URIRef, fields: tuple[Field, ...]) -> str:
    """The view's SPARQL: ``?s`` and one variable per field, one OPTIONAL per field, in field order."""
    variables = " ".join(["?s", *(f"?{f.name}" for f in fields)])
    patterns = "".join(f" {_pattern(f)}" for f in fields)
    return f"SELECT {variables} WHERE {{ ?s a <{target}> .{patterns} }}"


def _view_node(model: Model, view: _View, iri: str) -> dict[str, Any]:
    fields = _columns(model, view.shape)
    return {
        "@id": iri,
        "@type": str(VOCAB.ViewSpec),
        str(RDFS.label): model.label(view.component),
        str(PROV.wasDerivedFrom): _iri(view.component),
        str(VOCAB.targetClass): _iri(view.target),
        str(VOCAB.rendererType): RENDERER,
        str(VOCAB.columns): ",".join(f.name for f in fields),
        str(VOCAB.sparqlQuery): query(view.target, fields),
    }


# ── the package ──


def _archive(model: Model, namespace: str, terms: list[URIRef]) -> dict[URIRef, str]:
    """Each model term's package IRI; two terms with one local name are one node (ADR-0026 section 3)."""
    out: dict[URIRef, str] = {}
    seen: dict[str, URIRef] = {}
    for term in sorted(set(terms), key=str):
        iri = f"{namespace}{local_name(term)}"
        if iri in seen:
            detail = (
                f"{model.compact(seen[iri])} and {model.compact(term)} share the local name "
                f'"{local_name(term)}", so both would be the package node {iri}'
            )
            raise GeneratorError(term, RDF.type, detail)
        seen[iri] = term
        out[term] = iri
    return out


def _ontology_node(model: Model, ontology: URIRef, manifest: Manifest, iri: str) -> dict[str, Any]:
    imports = _imports(model, ontology)
    with view_errors():
        version_iri = model.ontologies.by_iri(ontology).version_iri
    node: dict[str, Any] = {
        "@id": iri,
        "@type": str(OWL.Ontology),
        str(RDFS.label): manifest.name,
        str(OWL.versionInfo): manifest.version,
        str(PROV.wasDerivedFrom): _iri(ontology if version_iri is None else version_iri),
    }
    if manifest.description is not None:
        node[str(RDFS.comment)] = manifest.description
    if imports:
        node[str(OWL.imports)] = _one_or_many([_iri(i) for i in imports])
    return node


def _sorted_nodes(nodes: list[dict[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(sorted(nodes, key=lambda n: str(n["@id"])))


def _sources(iris: list[URIRef]) -> tuple[str, ...]:
    return tuple(sorted({str(i) for i in iris}))


def extract_mentalmodel(model: Model) -> MentalModel:
    """The Mental Model of the model's one ontology model (ADR-0026)."""
    ontology = _ontology(model)
    model_id = _model_id(model, ontology)
    manifest = Manifest(
        model_id=model_id,
        version=_version(model, ontology),
        name=_name(model, ontology),
        description=_description(model, ontology),
    )
    targeted, shapes = _written_shapes(model)
    views = _views(model)
    archive = _archive(model, manifest.namespace, [ontology, *shapes, *(v.component for v in views)])

    writer = _Shapes(model, archive)
    shape_nodes = [
        writer.describe(s, {"@id": archive[s], str(PROV.wasDerivedFrom): _iri(s)}) | {"@type": _shape_types(model, s)}
        for s in shapes
    ]
    view_nodes = [_view_node(model, v, archive[v.component]) for v in views]
    targets = [t.iri for s in targeted if (t := s.target_class) is not None]
    documents = (
        Document("ontology", (_ontology_node(model, ontology, manifest, archive[ontology]),), _sources([ontology])),
        Document("shapes", _sorted_nodes(shape_nodes), _sources([*shapes, *targets])),
        Document(
            "views",
            _sorted_nodes(view_nodes),
            _sources([x for v in views for x in (v.component, v.shape.iri, v.target)]),
        ),
    )
    return MentalModel(manifest=manifest, ontology=str(ontology), documents=documents)


def _shape_types(model: Model, shape: URIRef) -> Any:
    """A written shape is an sh:NodeShape, with any other SHACL type it states."""
    types = {str(SH.NodeShape)} | {str(t) for t in model.ds.objects(shape, RDF.type) if str(t).startswith(str(SH))}
    return _one_or_many(sorted(types))


def manifest_text(manifest: Manifest) -> str:
    """The manifest in ADR-0026 section 4's key order, every value a JSON (YAML double-quoted) string."""
    pairs = [("modelId", manifest.model_id), ("version", manifest.version), ("name", manifest.name)]
    if manifest.description is not None:
        pairs.append(("description", manifest.description))
    pairs.append(("namespace", manifest.namespace))
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in pairs]
    lines.append("entrypoints:")
    lines.extend(f"  {kind}: {json.dumps(manifest.entrypoint(kind))}" for kind in KINDS)
    return "\n".join(lines) + "\n"


def document_text(document: Document) -> str:
    """A JSON-LD document: one ``@graph``, sorted keys, two-space indent, trailing newline."""
    return json.dumps({"@graph": list(document.nodes)}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_mentalmodel(view: MentalModel) -> Files:
    """{``manifest.yaml``: text, ``<kind>/<modelId>.jsonld``: text} for the three entrypoints."""
    files = {MANIFEST: manifest_text(view.manifest)}
    files.update((view.manifest.entrypoint(d.kind), document_text(d)) for d in view.documents)
    return files


def mentalmodel_sources(model: Model) -> Sources:
    """{file name: the full IRIs it comes from}: the ontology for the manifest
    and the ontology file, the written shapes and their target classes, and
    each view's component, shape and target class."""
    view = extract_mentalmodel(model)
    found: dict[str, tuple[str, ...]] = {MANIFEST: (view.ontology,)}
    found.update((view.manifest.entrypoint(d.kind), d.sources) for d in view.documents)
    return found


__all__ = [
    "MANIFEST",
    "Document",
    "Manifest",
    "MentalModel",
    "document_text",
    "extract_mentalmodel",
    "manifest_text",
    "mentalmodel_sources",
    "query",
    "render_mentalmodel",
]
