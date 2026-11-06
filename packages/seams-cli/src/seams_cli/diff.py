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
- Between two loaded models a property is read as it crosses the wire (ADR-0023
  section 5): it is matched by its field name (``Field.name``: sh:name, else the
  path's local name), and a category or flattened sh:node field compares by the
  datatype of its wire value, not its sh:class. Moving a field to a new path under
  its old name, or replacing a copied string sh:in with a category, is no change.
- Operations are the subjects of seam:acceptsShape or seam:returnsShape,
  matched by IRI. Added is compatible; removed, or a changed target, breaking.
- A shape change is also in the ``contract`` scope when an operation in either
  model accepts or returns that shape.
- Between two loaded models each change names the downstream contexts it reaches
  (ADR-0032 section 2): the subject's models (its ``seam:inModel``, else the
  ``seam:Model`` declared in each graph that types it), the arch:BoundedContexts that
  ``seam:owns`` them, then every ``arch:downstream`` of a relationship whose
  ``arch:upstream`` is one of them, in OLD and in NEW together. A model with no
  relationship gives every change no contexts. ``downstream`` groups the breaking
  changes by those contexts for the per-context section of the text output.

The verdicts and the ``Change`` record live in ``seams_cli.classification``, which the
vocabulary gate shares (ADR-0021 section 7); they are importable from here as well.
``diff_graphs`` runs the same rules over two plain graphs, matching properties by
path. A model whose typed shape view raises ``ResolutionError`` (an empty category, an
ambiguous sh:node) raises ProjectError naming the fault. A model that cannot be loaded
raises ProjectError. ``shorten`` turns the IRIs of a subject or detail into CURIEs for
the text output of ``seams diff``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

import rdflib
import seams
from rdflib.term import Node

from .classification import ABSENT, BREAKING, COMPATIBLE, Change, sort_changes
from .project import ProjectError

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
SEAM = rdflib.Namespace("https://w3id.org/seams/seam#")
ARCH = rdflib.Namespace("https://w3id.org/seams/arch#")
OWL_SAME_AS = rdflib.OWL.sameAs

DATA = "data"
CONTRACT = "contract"

CONTRACT_PREDICATES = {"accepts": SEAM.acceptsShape, "returns": SEAM.returnsShape}


class _Property(NamedTuple):
    path: str
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


# (shape IRI, sh:path IRI) -> the typed view's field, for reading a property as its wire value
Fields = Mapping[tuple[str, str], seams.Field]


def _fields(model: seams.Model) -> Fields:
    """Every field of the model's shapes, from the typed view (ADR-0023)."""
    try:
        return {(str(f.shape), str(f.iri)): f for shape in model.shapes for f in shape.fields()}
    except seams.ResolutionError as err:
        raise ProjectError(f"cannot read the model's shapes: {err}") from err


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


def _properties(graph: rdflib.Graph, shape: rdflib.URIRef, fields: Fields | None = None) -> dict[str, _Property]:
    """The shape's property shapes by path, or by field name when ``fields`` is given. Several shapes on
    one key merge into the tightest bounds. A category or flattened field's sh:class is not on the wire:
    it reads as the field's datatype instead."""
    grouped: dict[str, list[Node]] = {}
    paths: dict[str, str] = {}
    wire: dict[str, str] = {}
    for prop in graph.objects(shape, SH.property):
        for path in graph.objects(prop, SH.path):
            key = _key(graph, path)
            field = fields.get((str(shape), key)) if fields is not None else None
            name = key if field is None else field.name
            grouped.setdefault(name, []).append(prop)
            paths[name] = key
            if field is not None and (field.members or field.node is not None) and field.datatype is not None:
                wire[name] = str(field.datatype)
    result = {}
    for name, props in grouped.items():
        mins = [n for p in props for n in _ints(graph, p, SH.minCount)]
        maxes = [n for p in props for n in _ints(graph, p, SH.maxCount)]
        lowered = wire.get(name)
        result[name] = _Property(
            path=paths[name],
            datatypes=frozenset(str(v) for p in props for v in graph.objects(p, SH.datatype))
            if lowered is None
            else frozenset({lowered}),
            classes=frozenset(str(v) for p in props for v in graph.objects(p, SH["class"]))
            if lowered is None
            else frozenset(),
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
    """``diff_models`` over two models already loaded with ``load_model``; fields read as their wire values,
    and each change carries the downstream contexts it reaches in either model."""
    changes = diff_graphs(_union(old), _union(new), _fields(old), _fields(new))
    old_reach, new_reach = _reach(old), _reach(new)
    return [c._replace(contexts=tuple(sorted(old_reach(c.subject) | new_reach(c.subject)))) for c in changes]


def _reach(model: seams.Model) -> Callable[[str], frozenset[str]]:
    """The downstream contexts a change to a subject reaches in ``model`` (ADR-0032 section 2)."""
    ds = model.ds
    contexts = set(ds.subjects(rdflib.RDF.type, ARCH.BoundedContext))
    owners: dict[Node, set[Node]] = {}
    for context, owned in ds.subject_objects(SEAM.owns):
        if context in contexts:
            owners.setdefault(owned, set()).add(context)
    downstream: dict[Node, set[str]] = {}
    for relationship in ds.subjects(rdflib.RDF.type, ARCH.ContextRelationship):
        for up in ds.objects(relationship, ARCH.upstream):
            downstream.setdefault(up, set()).update(str(d) for d in ds.objects(relationship, ARCH.downstream))

    def reach(subject: str) -> frozenset[str]:
        if not downstream:
            return frozenset()
        node = rdflib.URIRef(subject)
        models = set(ds.objects(node, SEAM.inModel))
        if not models:
            graphs = {g for _s, _p, _o, g in ds.quads((node, rdflib.RDF.type, None, None))}
            models = {m for g in graphs for m, _p, _o, _g in ds.quads((None, rdflib.RDF.type, SEAM.Model, g))}
        return frozenset(d for m in models for c in owners.get(m, ()) for d in downstream.get(c, ()))

    return reach


def downstream(changes: Iterable[Change]) -> dict[str, list[Change]]:
    """The breaking changes by each downstream context they reach, contexts and changes sorted."""
    grouped: dict[str, list[Change]] = {}
    for change in sort_changes(list(changes)):
        if change.verdict == BREAKING:
            for context in change.contexts:
                grouped.setdefault(context, []).append(change)
    return {context: grouped[context] for context in sorted(grouped)}


def diff_graphs(
    old_graph: rdflib.Graph,
    new_graph: rdflib.Graph,
    old_fields: Fields | None = None,
    new_fields: Fields | None = None,
) -> list[Change]:
    """Every shape and operation-contract change from OLD_GRAPH to NEW_GRAPH, sorted. With each
    graph's ``fields``, properties match by field name and compare as their wire values."""
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
        before = _properties(old_graph, rdflib.URIRef(old_iri), old_fields)
        after = _properties(new_graph, rdflib.URIRef(new_iri), new_fields)
        for key in sorted(before.keys() - after.keys()):
            shape_change(BREAKING, "property-removed", new_iri, before[key].path)
        for key in sorted(after.keys() - before.keys()):
            required = after[key].min_count > 0
            detail = f"{after[key].path} minCount {after[key].min_count}"
            shape_change(BREAKING if required else COMPATIBLE, "property-added", new_iri, detail)
        for key in sorted(before.keys() & after.keys()):
            for verdict, kind, detail in _compare_property(after[key].path, before[key], after[key]):
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

    return sort_changes(changes)


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
    ordered = sort_changes(list(changes))
    return {
        "changes": [
            {
                "verdict": c.verdict,
                "kind": c.kind,
                "subject": c.subject,
                "detail": c.detail,
                "scopes": list(c.scopes),
                "contexts": list(c.contexts),
            }
            for c in ordered
        ],
        "counts": {
            BREAKING: sum(c.verdict == BREAKING for c in ordered),
            COMPATIBLE: sum(c.verdict == COMPATIBLE for c in ordered),
        },
    }
