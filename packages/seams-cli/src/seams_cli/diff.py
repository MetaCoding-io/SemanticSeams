"""``seams diff``: is a model change safe for stored data and operation contracts? (M015/S01, D052)

``diff_models(old, new)`` loads two model versions (a TriG file or a directory
of them) and returns one ``Change`` per difference, sorted. Every change has a
verdict, ``compatible`` or ``breaking``, and the scopes it touches: ``data``
for stored instances of a shape, ``contract`` for an operation's request or
response.

- sh:NodeShapes are matched by IRI (ADR-0002). An ``owl:sameAs`` between a
  shape only in NEW and a shape only in OLD, stated in NEW, is a rename.
- Property shapes are matched by (node shape, sh:path), since they are often
  blank nodes. sh:datatype, sh:class, sh:minCount and sh:maxCount are compared:
  a new or changed constraint is breaking, a dropped or looser one compatible.
  An added property is breaking only when it is required (sh:minCount > 0).
- Operations are the subjects of seam:acceptsShape or seam:returnsShape,
  matched by IRI. Added is compatible; removed, or a changed target, breaking.
- A shape change is also in the ``contract`` scope when an operation in either
  model accepts or returns that shape.

A model that cannot be loaded raises ProjectError. ``shorten`` turns the IRIs of a
subject or detail into CURIEs for the text output of ``seams diff``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import rdflib
import seams
from rdflib.term import Node

from .project import ProjectError

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
SEAM = rdflib.Namespace("https://w3id.org/seams/seam#")
OWL_SAME_AS = rdflib.OWL.sameAs

COMPATIBLE = "compatible"
BREAKING = "breaking"
DATA = "data"
CONTRACT = "contract"
ABSENT = "-"

CONTRACT_PREDICATES = {"accepts": SEAM.acceptsShape, "returns": SEAM.returnsShape}


class Change(NamedTuple):
    """One difference. ``subject`` is a shape or operation IRI; ``detail`` names the path and values."""

    verdict: str
    kind: str
    subject: str
    detail: str
    scopes: tuple[str, ...]


class _Property(NamedTuple):
    datatypes: frozenset[str]
    classes: frozenset[str]
    min_count: int
    max_count: int | None


def load_model(path: Path) -> seams.Model:
    """The model at ``path`` (a TriG file or a directory); ProjectError when it cannot be loaded."""
    try:
        return seams.load(path)
    except Exception as err:
        raise ProjectError(f"{path}: cannot load the model: {err}") from err


def _union(model: seams.Model) -> rdflib.Graph:
    graph = rdflib.Graph()
    for s, p, o, _ctx in model.ds.quads((None, None, None, None)):
        graph.add((s, p, o))
    return graph


def _key(graph: rdflib.Graph, node: Node) -> str:
    """A stable string for a term; a blank node (a complex sh:path) is spelled out from its triples."""
    if not isinstance(node, rdflib.BNode):
        return str(node)
    parts = sorted(f"{p} {_key(graph, o)}" for p, o in graph.predicate_objects(node))
    return "[" + "; ".join(parts) + "]"


def _ints(graph: rdflib.Graph, node: Node, predicate: rdflib.URIRef) -> list[int]:
    return [int(v) for v in graph.objects(node, predicate) if isinstance(v, rdflib.Literal)]


def _properties(graph: rdflib.Graph, shape: rdflib.URIRef) -> dict[str, _Property]:
    """The shape's property shapes by path. Several shapes on one path merge into the tightest bounds."""
    grouped: dict[str, list[Node]] = {}
    for prop in graph.objects(shape, SH.property):
        for path in graph.objects(prop, SH.path):
            grouped.setdefault(_key(graph, path), []).append(prop)
    result = {}
    for path, props in grouped.items():
        mins = [n for p in props for n in _ints(graph, p, SH.minCount)]
        maxes = [n for p in props for n in _ints(graph, p, SH.maxCount)]
        result[path] = _Property(
            datatypes=frozenset(str(v) for p in props for v in graph.objects(p, SH.datatype)),
            classes=frozenset(str(v) for p in props for v in graph.objects(p, SH["class"])),
            min_count=max(mins, default=0),
            max_count=min(maxes, default=None),
        )
    return result


def _shapes(graph: rdflib.Graph) -> set[rdflib.URIRef]:
    return {s for s in graph.subjects(rdflib.RDF.type, SH.NodeShape) if isinstance(s, rdflib.URIRef)}


def _renames(new: rdflib.Graph, old_only: set[rdflib.URIRef], new_only: set[rdflib.URIRef]) -> dict[str, str]:
    """Old shape IRI to new shape IRI, from an owl:sameAs in NEW, in either direction."""
    renames = {}
    for a, b in sorted(new.subject_objects(OWL_SAME_AS)):
        for newer, older in ((a, b), (b, a)):
            if newer in new_only and older in old_only and str(older) not in renames:
                renames[str(older)] = str(newer)
    return renames


def _operations(graph: rdflib.Graph) -> dict[str, dict[str, frozenset[str]]]:
    ops: dict[str, dict[str, frozenset[str]]] = {}
    for role, predicate in CONTRACT_PREDICATES.items():
        for op in {s for s in graph.subjects(predicate, None) if isinstance(s, rdflib.URIRef)}:
            targets = frozenset(str(t) for t in graph.objects(op, predicate))
            ops.setdefault(str(op), {r: frozenset() for r in CONTRACT_PREDICATES})[role] = targets
    return ops


def _values(values: Iterable[str]) -> str:
    return ",".join(sorted(values)) or ABSENT


def _compare_property(path: str, old: _Property, new: _Property) -> list[tuple[str, str, str]]:
    """(verdict, kind, detail) for each constraint that differs."""
    found = []
    for kind, before, after in (
        ("datatype-changed", old.datatypes, new.datatypes),
        ("class-changed", old.classes, new.classes),
    ):
        if before != after:
            verdict = COMPATIBLE if not after else BREAKING
            found.append((verdict, kind, f"{path} {_values(before)} -> {_values(after)}"))
    if old.min_count != new.min_count:
        verdict = BREAKING if new.min_count > old.min_count else COMPATIBLE
        found.append((verdict, "min-count-changed", f"{path} {old.min_count} -> {new.min_count}"))
    if old.max_count != new.max_count:
        tighter = new.max_count is not None and (old.max_count is None or new.max_count < old.max_count)
        before = ABSENT if old.max_count is None else str(old.max_count)
        after = ABSENT if new.max_count is None else str(new.max_count)
        found.append((BREAKING if tighter else COMPATIBLE, "max-count-changed", f"{path} {before} -> {after}"))
    return found


def diff_models(old: Path, new: Path) -> list[Change]:
    """Every shape and operation-contract change from OLD to NEW, sorted."""
    return diff_loaded(load_model(old), load_model(new))


def diff_loaded(old: seams.Model, new: seams.Model) -> list[Change]:
    """``diff_models`` over two models already loaded with ``load_model``."""
    old_graph, new_graph = _union(old), _union(new)
    old_shapes, new_shapes = _shapes(old_graph), _shapes(new_graph)
    renames = _renames(new_graph, old_shapes - new_shapes, new_shapes - old_shapes)
    old_ops, new_ops = _operations(old_graph), _operations(new_graph)

    def renamed(iri: str) -> str:
        return renames.get(iri, iri)

    contract_shapes = {
        renamed(t)
        for ops in (old_ops, new_ops)
        for roles in ops.values()
        for targets in roles.values()
        for t in targets
    }

    def shape_scopes(iri: str) -> tuple[str, ...]:
        return tuple(sorted({DATA, CONTRACT} if renamed(iri) in contract_shapes else {DATA}))

    changes: list[Change] = []

    def shape_change(verdict: str, kind: str, iri: str, detail: str) -> None:
        changes.append(Change(verdict, kind, iri, detail, shape_scopes(iri)))

    old_iris = {str(s) for s in old_shapes}
    new_iris = {str(s) for s in new_shapes}
    for old_iri, new_iri in renames.items():
        shape_change(COMPATIBLE, "shape-renamed", new_iri, f"{old_iri} -> {new_iri}")
    for iri in sorted(old_iris - new_iris - renames.keys()):
        shape_change(BREAKING, "shape-removed", iri, ABSENT)
    for iri in sorted(new_iris - old_iris - set(renames.values())):
        shape_change(COMPATIBLE, "shape-added", iri, ABSENT)

    pairs = [(iri, iri) for iri in old_iris & new_iris] + list(renames.items())
    for old_iri, new_iri in pairs:
        before = _properties(old_graph, rdflib.URIRef(old_iri))
        after = _properties(new_graph, rdflib.URIRef(new_iri))
        for path in sorted(before.keys() - after.keys()):
            shape_change(BREAKING, "property-removed", new_iri, path)
        for path in sorted(after.keys() - before.keys()):
            required = after[path].min_count > 0
            detail = f"{path} minCount {after[path].min_count}"
            shape_change(BREAKING if required else COMPATIBLE, "property-added", new_iri, detail)
        for path in sorted(before.keys() & after.keys()):
            for verdict, kind, detail in _compare_property(path, before[path], after[path]):
                shape_change(verdict, kind, new_iri, detail)

    for op in sorted(old_ops.keys() - new_ops.keys()):
        changes.append(Change(BREAKING, "operation-removed", op, ABSENT, (CONTRACT,)))
    for op in sorted(new_ops.keys() - old_ops.keys()):
        changes.append(Change(COMPATIBLE, "operation-added", op, ABSENT, (CONTRACT,)))
    for op in sorted(old_ops.keys() & new_ops.keys()):
        for role in CONTRACT_PREDICATES:
            before = frozenset(renamed(t) for t in old_ops[op][role])
            after = new_ops[op][role]
            if before != after:
                detail = f"{_values(old_ops[op][role])} -> {_values(after)}"
                changes.append(Change(BREAKING, f"{role}-changed", op, detail, (CONTRACT,)))

    return sorted(changes, key=lambda c: (c.subject, c.kind, c.detail, c.verdict))


def shorten(text: str, *models: seams.Model) -> str:
    """``text`` with each IRI token (split on spaces and commas) as a CURIE of the first model binding its
    namespace; a token no model binds stays as it is."""

    def token(word: str) -> str:
        if "://" not in word or word.startswith("["):
            return word
        for model in models:
            short = model.compact(word, whole=True)
            if short != word:
                return short
        return word

    return " ".join(",".join(token(w) for w in part.split(",")) for part in text.split(" "))


def to_json(changes: Iterable[Change]) -> dict:
    """A deterministic dict: the changes, sorted, and how many are breaking and compatible."""
    ordered = sorted(changes, key=lambda c: (c.subject, c.kind, c.detail, c.verdict))
    return {
        "changes": [
            {"verdict": c.verdict, "kind": c.kind, "subject": c.subject, "detail": c.detail, "scopes": list(c.scopes)}
            for c in ordered
        ],
        "counts": {
            BREAKING: sum(c.verdict == BREAKING for c in ordered),
            COMPATIBLE: sum(c.verdict == COMPATIBLE for c in ordered),
        },
    }
