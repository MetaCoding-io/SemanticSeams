"""``seams cml``: the context map as Context Mapper DSL (M029/S03, backlog B5, ADR-0034).

``run_export`` loads the project's model (``resolve_model``, so ``--model`` and
SEAMS_MODEL apply as for generate), extracts its arch:BoundedContexts and
arch:ContextRelationships (``extract``) and renders them as CML (``render``):
one ``ContextMap`` that ``contains`` every context, one relationship line per
arch:ContextRelationship in the bracket form ADR-0034 section 2 gives its
arch:relationshipType, then one bodiless ``BoundedContext`` per context. Every
name is an IRI's local name and every list is sorted by IRI, so the same model
exports the same bytes. With ``out`` the text is written there; the file is not a
generator output, so seams.lock does not record it.

A model that cannot be loaded raises ProjectError. A relationship without exactly
one arch:upstream, arch:downstream or arch:relationshipType, or with a type that
has no CML form, raises ``ResolutionError(relationship, predicate, detail)``
(both exit 2), and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import seams
from rdflib import RDF, URIRef
from seams import ARCH, local_name

from .project import Project, ProjectError, resolve_model

# arch:relationshipType -> (upstream roles, arrow, downstream roles), ADR-0034 section 2.
FORMS: dict[URIRef, tuple[str, str, str]] = {
    ARCH.CustomerSupplier: ("U,S", "->", "D,C"),
    ARCH.Conformist: ("U", "->", "D,CF"),
    ARCH.AntiCorruptionLayer: ("U", "->", "D,ACL"),
    ARCH.PublishedLanguage: ("U,PL", "->", "D"),
    ARCH.SharedKernel: ("SK", "<->", "SK"),
}


@dataclass(frozen=True)
class Relationship:
    """One arch:ContextRelationship: its IRI, its two contexts and its type."""

    iri: URIRef
    upstream: URIRef
    downstream: URIRef
    type: URIRef


@dataclass(frozen=True)
class ContextMap:
    """The model's contexts and relationships, each sorted by IRI."""

    contexts: tuple[URIRef, ...]
    relationships: tuple[Relationship, ...]


def extract(model: seams.Model) -> ContextMap:
    """The context map of ``model``; a relationship that is not fully stated raises
    ``ResolutionError`` naming it and the predicate."""
    contexts = tuple(sorted((c.iri for c in model.architecture.contexts()), key=str))
    ds = model.ds
    iris = sorted({r for r in ds.subjects(RDF.type, ARCH.ContextRelationship) if isinstance(r, URIRef)}, key=str)
    relationships = tuple(
        Relationship(
            iri,
            _one(model, iri, ARCH.upstream),
            _one(model, iri, ARCH.downstream),
            _one(model, iri, ARCH.relationshipType),
        )
        for iri in iris
    )
    for relationship in relationships:
        if relationship.type not in FORMS:
            detail = f"{relationship.type} has no Context Mapper form (ADR-0034 section 2)"
            raise seams.ResolutionError(relationship.iri, ARCH.relationshipType, detail)
    return ContextMap(contexts, relationships)


def _one(model: seams.Model, subject: URIRef, predicate: URIRef) -> URIRef:
    values = sorted({o for o in model.ds.objects(subject, predicate)}, key=str)
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise seams.ResolutionError(subject, predicate, f"expected exactly one IRI, found {[str(v) for v in values]}")
    return values[0]


def render(context_map: ContextMap) -> str:
    """The CML text of ``context_map`` (ADR-0034 section 2)."""
    lines = ["ContextMap {"]
    if context_map.contexts:
        lines.append(f"  contains {', '.join(local_name(c) for c in context_map.contexts)}")
    for r in context_map.relationships:
        up_roles, arrow, down_roles = FORMS[r.type]
        lines.append(
            f"  {local_name(r.upstream)} [{up_roles}]{arrow}[{down_roles}] {local_name(r.downstream)}"
            f" : {local_name(r.iri)}"
        )
    lines.append("}")
    for context in context_map.contexts:
        lines += ["", f"BoundedContext {local_name(context)}"]
    return "\n".join(lines) + "\n"


def run_export(project: Project, model: Path | None, out: Path | None = None) -> str:
    """The CML text of the project's context map. With ``out``, it is also written there."""
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    text = render(extract(loaded))
    if out is not None:
        out.write_text(text, encoding="utf-8")
    return text
