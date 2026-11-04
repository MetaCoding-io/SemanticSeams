"""The JSON-LD context generator (M023/S05, backlog O3, ADR-0024).

``extract_jsonld`` reads every sh:NodeShape with a ``sh:targetClass``
through ``model.shapes`` (D036) into a frozen ``JsonLdModel``, and
``render_jsonld`` writes one JSON-LD 1.1 context document per shape,
``<shape local name>.jsonld``. Per field of ``Shape.fields()`` the term is
``Field.name`` and its ``@id`` is ``Field.path``:

- a datatype field is typed by its ``sh:datatype`` (``xsd:string`` too);
- a field with neither datatype, members nor node has only its ``@id``;
- a category field is coerced with ``"@type": "@vocab"`` and carries a
  property-scoped context mapping each member's label to its IRI, so the
  wire value stays the label;
- a flattened ``sh:node`` field and a reference field (``Field.reference``)
  map to ``null``: a context never states a triple the shape would reject.

The target class is one more term, its local name mapped to its IRI. Full
IRIs only, no prefixes and no top-level ``@vocab``; ``@version`` is always
1.1. A shape without a target class gets no context, and a model with none
gives no files. The text is ``json.dumps`` with sorted keys and a trailing
newline, with no header or model hash (ADR-0024 section 6): the trace of
``seams generate`` and seams.lock say where it came from.

Faults, each a ``GeneratorError`` naming the fact: two fields of one shape
with one name (``sh:name``, the seam shapes' case); a target class whose
local name is a field name, two target-classed shapes with one local name
(``sh:targetClass``) and a category label that is not a JSON-LD term
(``rdfs:label``), which only a context needs. A view ``ResolutionError`` is
passed on as the ``GeneratorError`` on the same fact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rdflib import RDFS, URIRef
from rdflib.namespace import SH
from seams import Model, local_name
from seams.views.shapes import Field, Shape

from . import GeneratorError
from ._views import view_errors
from .protocol import Files, Sources

SUFFIX = ".jsonld"
VERSION = 1.1
VOCAB = "@vocab"


@dataclass(frozen=True)
class Term:
    """One term of a context: ``iri`` None maps it to ``null``; ``type`` is
    a datatype IRI or ``@vocab``; ``scoped`` the (label, member IRI) pairs
    of a category field, sorted by label. A field term is an expanded
    definition (``{"@id": …}``); the class term (``field`` False) is the
    IRI string."""

    name: str
    iri: str | None
    type: str | None = None
    scoped: tuple[tuple[str, str], ...] = ()
    field: bool = True


@dataclass(frozen=True)
class Context:
    """The context of one target-classed shape: its file name, its terms
    (the class and the fields) sorted by name, and the full IRIs it comes
    from (the shape, the class, the fields' paths, the category members)."""

    shape: str
    file_name: str
    terms: tuple[Term, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class JsonLdModel:
    """Every context, by file name."""

    contexts: tuple[Context, ...]


def _check_label(field: Field, shape: str, label: str, member: URIRef, compact: str) -> None:
    """A label is a usable JSON-LD term: not empty, no leading ``@``, no ``:`` (ADR-0024 section 3)."""
    if label and not label.startswith("@") and ":" not in label:
        return
    detail = (
        f'{field.name} of {shape}: label "{label}" of {compact} is not a JSON-LD term '
        '(it must be non-empty, not start with "@" and contain no ":")'
    )
    raise GeneratorError(member, RDFS.label, detail)


def _term(model: Model, shape: str, field: Field) -> Term:
    if field.node is not None or field.reference is not None:
        return Term(field.name, None)
    if field.members:
        for label, member in zip(field.options, field.members, strict=True):
            _check_label(field, shape, label, member, model.compact(member))
        scoped = tuple(sorted((label, str(m)) for label, m in zip(field.options, field.members, strict=True)))
        return Term(field.name, str(field.path), VOCAB, scoped)
    return Term(field.name, str(field.path), None if field.datatype is None else str(field.datatype))


def _unique_names(model: Model, shape: Shape, fields: tuple[Field, ...]) -> None:
    """Two fields of one shape with one name are one term for two properties."""
    seen: dict[str, Field] = {}
    for field in fields:
        if field.name in seen:
            pair = f"{model.compact(seen[field.name].path)} and {model.compact(field.path)}"
            detail = f'fields {pair} of {model.compact(shape.iri)} both have the name "{field.name}"; a term names one property'
            raise GeneratorError(shape.iri, SH.name, detail)
        seen[field.name] = field


def _class_term(model: Model, shape: Shape, target: URIRef, fields: tuple[Field, ...]) -> Term:
    """The target class's term; a field with its local name would be one term for two IRIs."""
    name = local_name(target)
    if any(f.name == name for f in fields):
        detail = (
            f"{model.compact(shape.iri)}: the target class {model.compact(target)} and a field are both "
            f'named "{name}"; a context has one term per name'
        )
        raise GeneratorError(shape.iri, SH.targetClass, detail)
    return Term(name, str(target), field=False)


def _context(model: Model, shape: Shape, target: URIRef) -> Context:
    with view_errors():
        fields = tuple(shape.fields())
    name = model.compact(shape.iri)
    _unique_names(model, shape, fields)
    terms = [_class_term(model, shape, target, fields), *(_term(model, name, f) for f in fields)]
    sources = {
        str(shape.iri),
        str(target),
        *(str(f.path) for f in fields),
        *(str(m) for f in fields for m in f.members),
    }
    return Context(
        shape=str(shape.iri),
        file_name=f"{local_name(shape.iri)}{SUFFIX}",
        terms=tuple(sorted(terms, key=lambda t: t.name)),
        sources=tuple(sorted(sources)),
    )


def _unique_files(model: Model, contexts: list[Context]) -> None:
    """Two target-classed shapes with one local name would write one file."""
    seen: dict[str, Context] = {}
    for ctx in contexts:
        if ctx.file_name in seen:
            detail = (
                f"{model.compact(URIRef(seen[ctx.file_name].shape))} and {model.compact(URIRef(ctx.shape))} "
                f"both name the context file {ctx.file_name}"
            )
            raise GeneratorError(URIRef(ctx.shape), SH.targetClass, detail)
        seen[ctx.file_name] = ctx


def extract_jsonld(model: Model) -> JsonLdModel:
    """The context of every shape with a sh:targetClass, by file name."""
    contexts: list[Context] = []
    with view_errors():
        shapes = [(shape, shape.target_class) for shape in model.shapes]
    for shape, target in shapes:
        if target is not None:
            contexts.append(_context(model, shape, target.iri))
    _unique_files(model, contexts)
    return JsonLdModel(contexts=tuple(sorted(contexts, key=lambda c: c.file_name)))


def _definition(term: Term) -> Any:
    if term.iri is None or not term.field:
        return term.iri
    out: dict[str, Any] = {"@id": term.iri}
    if term.type is not None:
        out["@type"] = term.type
    if term.scoped:
        out["@context"] = dict(term.scoped)
    return out


def context_document(ctx: Context) -> str:
    """The context document of ``ctx``: sorted JSON, two-space indent, trailing newline."""
    body: dict[str, Any] = {"@version": VERSION}
    body.update((t.name, _definition(t)) for t in ctx.terms)
    return json.dumps({"@context": body}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_jsonld(view: JsonLdModel) -> Files:
    """{``<shape>.jsonld``: context document} for every context."""
    return {ctx.file_name: context_document(ctx) for ctx in view.contexts}


def jsonld_sources(model: Model) -> Sources:
    """{``<shape>.jsonld``: the full IRIs it comes from}."""
    return {ctx.file_name: ctx.sources for ctx in extract_jsonld(model).contexts}


__all__ = [
    "SUFFIX",
    "Context",
    "JsonLdModel",
    "Term",
    "context_document",
    "extract_jsonld",
    "jsonld_sources",
    "render_jsonld",
]
