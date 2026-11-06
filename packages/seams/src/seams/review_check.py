"""Model review checks (backlog R1): facts stated twice or not stated at all.

``review_findings(model)`` asks four questions of ``model.ds`` and returns one
``ReviewFinding`` (subject IRI, fact, message) per finding, sorted. A finding
flags the model for review; it never refuses it (principle 5).

- **Lifecycle labels copied into sh:in.** For each shape with an effective
  lifecycle (its own seam:lifecycle or its sh:targetClass's, ADR-0031), a
  sh:property whose sh:in list holds only literals equal to
  the rdfs:labels of that lifecycle's states (state:hasState) restates the
  lifecycle, and the two can drift (principle 1). The subject is the shape,
  the fact the property's sh:path; the message names the lifecycle and the
  state IRIs to use instead.
- **sh:class pointing at a shape.** A sh:property whose sh:class is a
  sh:NodeShape names a form, not a class of thing (principle 9). The subject
  is the shape, the fact the property's sh:path.
- **Shapes without a target class.** A sh:NodeShape with no sh:targetClass
  that is not itself an rdfs:Class or owl:Class (an implicit class target)
  says what a form looks like but not what it describes. The subject is the
  shape, the fact sh:targetClass.
- **Undeclared paths.** Every IRI used as a sh:path must be typed
  rdf:Property, owl:ObjectProperty, owl:DatatypeProperty or
  owl:AnnotationProperty somewhere in the model. Path expressions (blank
  nodes such as sh:inversePath) are skipped. The subject is the path IRI, the
  fact sh:path.

The checks read SHACL, RDFS and OWL terms only (principle 4). A malformed
RDF list in sh:in is read up to the point it breaks, so the function never
raises on a model that loaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import OWL, RDF, RDFS, SH, Literal, URIRef
from rdflib.term import Node

from .namespaces import STATE, local_name
from .views.shapes import effective_lifecycles

if TYPE_CHECKING:
    from rdflib import Dataset

    from .loader import Model

#: The rdf:types that declare an IRI a property.
PROPERTY_TYPES: frozenset[URIRef] = frozenset(
    {RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty}
)

_CLASS_TYPES = frozenset({RDFS.Class, OWL.Class})


@dataclass(frozen=True, order=True)
class ReviewFinding:
    """One review finding: the shape or path IRI, the fact it is about (a
    sh:path IRI or sh:targetClass/sh:path) and why it needs review."""

    subject: str
    fact: str
    message: str


def _rdf_list(ds: Dataset, head: Node) -> Iterator[Node]:
    """The members of an RDF list, stopping where the list is malformed or loops."""
    seen: set[Node] = set()
    node: Node | None = head
    while node is not None and node != RDF.nil and node not in seen:
        seen.add(node)
        first = ds.value(node, RDF.first)
        if first is None:
            return
        yield first
        node = ds.value(node, RDF.rest)


def _shapes(ds: Dataset) -> list[Node]:
    return sorted(set(ds.subjects(RDF.type, SH.NodeShape)), key=str)


def _properties(ds: Dataset, shape: Node) -> list[Node]:
    return sorted(set(ds.objects(shape, SH.property)), key=str)


def _path_fact(ds: Dataset, prop: Node, fallback: URIRef) -> str:
    path = ds.value(prop, SH.path)
    return str(path) if isinstance(path, URIRef) else str(fallback)


# ── lifecycle labels copied into sh:in ──


def lifecycle_label_findings(model: Model) -> list[ReviewFinding]:
    """Every sh:in list that holds only a lifecycle's state labels."""
    ds = model.ds
    found: list[ReviewFinding] = []
    for shape in _shapes(ds):
        for lifecycle in effective_lifecycles(ds, shape):
            states: dict[str, Node] = {}
            for state in sorted(set(ds.objects(lifecycle, STATE.hasState)), key=str):
                for label in ds.objects(state, RDFS.label):
                    states.setdefault(str(label), state)
            if not states:
                continue
            for prop in _properties(ds, shape):
                fact = _path_fact(ds, prop, SH["in"])
                for in_list in ds.objects(prop, SH["in"]):
                    members = list(_rdf_list(ds, in_list))
                    if not members or not all(isinstance(m, Literal) and str(m) in states for m in members):
                        continue
                    iris = ", ".join(local_name(states[str(m)]) for m in members)
                    found.append(
                        ReviewFinding(
                            str(shape),
                            fact,
                            f"sh:in on {local_name(fact)} copies the rdfs:labels "
                            f"of {local_name(lifecycle)}'s states, so it can drift from the lifecycle; "
                            f"use the state IRIs ({iris})",
                        )
                    )
    return sorted(found)


# ── sh:class pointing at a shape ──


def shape_class_findings(model: Model) -> list[ReviewFinding]:
    """Every sh:property whose sh:class is a sh:NodeShape."""
    ds = model.ds
    found: list[ReviewFinding] = []
    for shape in _shapes(ds):
        for prop in _properties(ds, shape):
            fact = _path_fact(ds, prop, SH["class"])
            for target in sorted(set(ds.objects(prop, SH["class"])), key=str):
                if (target, RDF.type, SH.NodeShape) not in ds:
                    continue
                found.append(
                    ReviewFinding(
                        str(shape),
                        fact,
                        f"sh:class on {local_name(fact)} is {local_name(target)}, a sh:NodeShape, "
                        "not a class; declare the class and give the shape sh:targetClass",
                    )
                )
    return sorted(found)


# ── shapes without a target class ──


def target_class_findings(model: Model) -> list[ReviewFinding]:
    """Every sh:NodeShape with no sh:targetClass that is not itself a class."""
    ds = model.ds
    found: list[ReviewFinding] = []
    for shape in _shapes(ds):
        if ds.value(shape, SH.targetClass) is not None:
            continue
        if any((shape, RDF.type, t) in ds for t in _CLASS_TYPES):
            continue
        found.append(
            ReviewFinding(
                str(shape),
                str(SH.targetClass),
                f"{local_name(shape)} has no sh:targetClass, so it says what a form holds "
                "but not what class of thing it describes",
            )
        )
    return sorted(found)


# ── undeclared paths ──


def undeclared_path_findings(model: Model) -> list[ReviewFinding]:
    """Every sh:path IRI that nothing in the model declares a property."""
    ds = model.ds
    users: dict[URIRef, set[str]] = {}
    for prop, path in ds.subject_objects(SH.path):
        if not isinstance(path, URIRef):
            continue
        names = users.setdefault(path, set())
        names.update(local_name(s) for s in ds.subjects(SH.property, prop) if isinstance(s, URIRef))
    found: list[ReviewFinding] = []
    for path, shapes in users.items():
        if any((path, RDF.type, t) in ds for t in PROPERTY_TYPES):
            continue
        used_by = f" (used by {', '.join(sorted(shapes))})" if shapes else ""
        found.append(
            ReviewFinding(
                str(path),
                str(SH.path),
                f"{local_name(path)} is a sh:path{used_by}, but no rdf:type rdf:Property, "
                "owl:ObjectProperty, owl:DatatypeProperty or owl:AnnotationProperty declares it",
            )
        )
    return sorted(found)


def review_findings(model: Model) -> list[ReviewFinding]:
    """All four checks' findings, sorted by subject, fact and message."""
    return sorted(
        lifecycle_label_findings(model)
        + shape_class_findings(model)
        + target_class_findings(model)
        + undeclared_path_findings(model)
    )


__all__ = [
    "PROPERTY_TYPES",
    "ReviewFinding",
    "lifecycle_label_findings",
    "review_findings",
    "shape_class_findings",
    "target_class_findings",
    "undeclared_path_findings",
]
