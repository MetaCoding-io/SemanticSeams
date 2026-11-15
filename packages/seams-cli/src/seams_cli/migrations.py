"""Stored-data migrations from the shape diff (M031/S03, ADR-0041).

``migrations(old, new, changes)`` reads the breaking ``data``-scope changes that
``seams_cli.diff.diff_loaded(old, new)`` returns for the shapes OLD stores (a shape
``seam:storedIn`` a container, or one some element ``seam:writes``), and gives for each
either a ``Migration`` per relational store kind or a ``Refusal``:

- ``property-removed``: SQL that drops the field's JSON key from every row of the shape;
- ``property-added`` (required): SQL that sets the key to NEW's one literal
  ``sh:defaultValue`` on every row of the shape that lacks it, or a refusal when there is
  no such default;
- ``shape-removed`` and every tightening change: a refusal;
- any change of a shape ``seam:storedIn`` a ``deploy:SemPKM`` store, in OLD or NEW: a
  refusal, since its data lives in SemPKM, not in ``entities.data``.

The rows are those of the ``entities`` table, matched by ``shape`` (the node shape's
full IRI, as ``put_entity`` writes it); ``data`` is JSON keyed by the field name
(``Field.name``). SQLite keeps it as TEXT, PostgreSQL as ``jsonb``. A shape renamed with
``owl:sameAs`` is matched by the IRI OLD gave it, which is the one its rows carry. The
JSON value of a default is the one the runtime's contract boundary stores for a
payload that omits the field: a boolean or number as itself, every other literal as
its lexical form, encoded with ``json.dumps(value, sort_keys=True)``.

Nothing here runs the SQL; ``seams plan`` writes it into the change plan.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from typing import NamedTuple

import rdflib
import seams
from rdflib.term import Node

from .classification import ABSENT, BREAKING, Change
from .diff import DATA, SEAM, SH
from .project import ProjectError

OWL_SAME_AS = rdflib.OWL.sameAs

#: The table every relational store keeps entities in (``seams_runtime.store``).
TABLE = "entities"

PROPERTY_REMOVED = "property-removed"
PROPERTY_ADDED = "property-added"
SHAPE_REMOVED = "shape-removed"

#: Characters a SQLite JSON path member cannot carry without escaping (ADR-0041 section 4).
UNQUOTABLE = ('"', "\\")


class Migration(NamedTuple):
    """One SQL statement for store kind ``kind`` over the rows of ``shape`` (its IRI in
    ``entities.shape``) for the property ``path``."""

    kind: str
    shape: str
    path: str
    sql: str


class Refusal(NamedTuple):
    """A breaking stored change with no mechanical rewrite: ``kind`` is the change kind,
    ``path`` the property's ``sh:path`` (``-`` for a whole shape), ``reason`` the missing
    fact or the store that cannot be rewritten."""

    kind: str
    shape: str
    path: str
    reason: str


def _sort_key(record: Migration | Refusal) -> tuple[str, str, str, str, str]:
    detail = record.sql if isinstance(record, Migration) else record.reason
    return (record.shape, record.path, record.kind, type(record).__name__, detail)


def _shapes(model: seams.Model) -> set[str]:
    return {str(s) for s in model.ds.subjects(rdflib.RDF.type, SH.NodeShape) if isinstance(s, rdflib.URIRef)}


def _stored(model: seams.Model) -> set[str]:
    """The shapes ``model`` has rows for: seam:storedIn a container, or seam:writes'd."""
    ds = model.ds
    stored = {str(s) for s, _o in ds.subject_objects(SEAM.storedIn)}
    stored |= {str(o) for _s, o in ds.subject_objects(SEAM.writes)}
    return stored & _shapes(model)


def _sempkm_stores(model: seams.Model, shape: str) -> list[str]:
    """The deploy:SemPKM stores ``shape`` is seam:storedIn in ``model``, sorted."""
    ds = model.ds
    stores = ds.objects(rdflib.URIRef(shape), SEAM.storedIn)
    return sorted(str(s) for s in stores if (s, seams.DEPLOY.storeKind, seams.DEPLOY.SemPKM) in ds)


def _old_iri(old_shapes: set[str], new: seams.Model, subject: str) -> str:
    """The IRI OLD gave ``subject``: itself, or the old shape NEW links to it with owl:sameAs."""
    if subject in old_shapes:
        return subject
    node = rdflib.URIRef(subject)
    linked = {str(o) for o in new.ds.objects(node, OWL_SAME_AS)} | {str(s) for s in new.ds.subjects(OWL_SAME_AS, node)}
    return min(linked & old_shapes, default=subject)


def _fields(model: seams.Model) -> dict[tuple[str, str], seams.Field]:
    try:
        return {(str(f.shape), str(f.iri)): f for shape in model.shapes for f in shape.fields()}
    except seams.ResolutionError as err:
        raise ProjectError(f"cannot read the model's shapes: {err}") from err


def _path(change: Change) -> str:
    """The property path the diff's ``detail`` spells, or ``-`` for a whole-shape change."""
    if change.kind == SHAPE_REMOVED:
        return ABSENT
    if change.kind == PROPERTY_REMOVED:
        return change.detail
    if change.kind == PROPERTY_ADDED:
        return change.detail.rpartition(" minCount ")[0] or change.detail
    parts = change.detail.rsplit(" ", 3)
    return parts[0] if len(parts) == 4 and parts[2] == "->" else change.detail


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _json_value(literal: rdflib.Literal) -> object:
    """The JSON value the runtime stores for a default (``seams_runtime.contracts``)."""
    value: object = literal.toPython()
    if isinstance(value, (bool, int, float)) and not isinstance(value, Decimal):
        return value
    return str(literal)


def _defaults(model: seams.Model, shape: str, path: str) -> list[Node]:
    ds = model.ds
    props = [p for p in ds.objects(rdflib.URIRef(shape), SH.property) if str(ds.value(p, SH.path)) == path]
    return sorted({d for p in props for d in ds.objects(p, SH.defaultValue)}, key=str)


def _name(kind: rdflib.URIRef) -> str:
    """The store kind's name in a ``Migration``: its deploy:StoreKind local name, lower-cased."""
    return seams.local_name(kind).lower()


def _member(key: str) -> str:
    return f'$."{key}"'


def _drop(rows: str, key: str) -> dict[rdflib.URIRef, str]:
    where = f"WHERE shape = {_quote(rows)};"
    return {
        seams.DEPLOY.PostgreSQL: f"UPDATE {TABLE} SET data = data - {_quote(key)} {where}",
        seams.DEPLOY.SQLite: f"UPDATE {TABLE} SET data = json_remove(data, {_quote(_member(key))}) {where}",
    }


def _fill(rows: str, key: str, value: object) -> dict[rdflib.URIRef, str]:
    encoded = _quote(json.dumps(value, sort_keys=True))
    member = _quote(_member(key))
    return {
        seams.DEPLOY.PostgreSQL: (
            f"UPDATE {TABLE} SET data = jsonb_set(data, ARRAY[{_quote(key)}], {encoded}::jsonb) "
            f"WHERE shape = {_quote(rows)} AND NOT (data ? {_quote(key)});"
        ),
        seams.DEPLOY.SQLite: (
            f"UPDATE {TABLE} SET data = json_set(data, {member}, json({encoded})) "
            f"WHERE shape = {_quote(rows)} AND json_type(data, {member}) IS NULL;"
        ),
    }


class _Models(NamedTuple):
    old: seams.Model
    new: seams.Model
    old_fields: dict[tuple[str, str], seams.Field]
    new_fields: dict[tuple[str, str], seams.Field]


def _records(models: _Models, change: Change, rows: str) -> list[Migration | Refusal]:
    """The migrations or the refusal for one breaking stored change of the shape whose rows carry ``rows``."""
    path = _path(change)

    def refuse(reason: str) -> list[Migration | Refusal]:
        return [Refusal(change.kind, rows, path, reason)]

    sempkm = _sempkm_stores(models.old, rows) or _sempkm_stores(models.new, change.subject)
    if sempkm:
        return refuse(f"stored in the SemPKM store {sempkm[0]}; SemPKM data is not rewritten by SQL")
    if change.kind == SHAPE_REMOVED:
        return refuse("the shape is removed: its rows have no shape to conform to, and deleting them is not mechanical")
    if change.kind not in (PROPERTY_REMOVED, PROPERTY_ADDED):
        return refuse(f"{change.detail}: converting or trimming a stored value needs a rule the model does not state")
    removed = change.kind == PROPERTY_REMOVED
    field = models.old_fields.get((rows, path)) if removed else models.new_fields.get((change.subject, path))
    if field is None:
        return refuse("no field of the shape's typed view has this sh:path, so its JSON key is unknown")
    if any(c in field.name for c in UNQUOTABLE):
        return refuse(f"the field name {field.name!r} holds a character a JSON path cannot quote for both stores")
    if removed:
        statements = _drop(rows, field.name)
    else:
        defaults = _defaults(models.new, change.subject, path)
        if not defaults:
            return refuse("no sh:defaultValue to fill the rows that lack it")
        default = defaults[0]
        if len(defaults) > 1 or not isinstance(default, rdflib.Literal):
            return refuse("sh:defaultValue must be exactly one literal to fill the rows that lack it")
        statements = _fill(rows, field.name, _json_value(default))
    return [Migration(_name(kind), rows, path, statements[kind]) for kind in seams.RELATIONAL_STORE_KINDS]


def migrations(old: seams.Model, new: seams.Model, changes: Iterable[Change]) -> list[Migration | Refusal]:
    """A ``Migration`` per relational store kind, or a ``Refusal``, for each breaking ``data``-scope
    change of a shape OLD stores, sorted by (shape, path, kind)."""
    old_shapes, stored = _shapes(old), _stored(old)
    selected = [
        (change, rows)
        for change in changes
        if change.verdict == BREAKING and DATA in change.scopes
        for rows in (_old_iri(old_shapes, new, change.subject),)
        if rows in stored
    ]
    if not selected:
        return []
    models = _Models(old, new, _fields(old), _fields(new))
    return sorted((r for change, rows in selected for r in _records(models, change, rows)), key=_sort_key)
