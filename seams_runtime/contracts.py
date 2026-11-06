"""SHACL contract validation at the call boundary (ADR-0007).

A payload crossing a seam is a flat mapping of field name to value. A
field's name is ``Field.name`` of the typed shape view: its ``sh:name``,
else the local name of its ``sh:path`` (ADR-0023). ``to_rdf`` turns the payload into a one-node data graph. ``validate`` runs
pySHACL against just that shape and raises ``ContractViolation`` with one
entry per result (shape, focus, path, constraint, value, message).

The contract graph is the shape's own triples, **lowered** to the wire
(ADR-0023 section 5): ``sh:targetClass`` is left out, a category field
becomes ``sh:datatype xsd:string`` with ``sh:in`` of its members' labels in
option order, and a flattened ``sh:node`` field becomes a plain property on
its outer path with the free property's value constraints. A payload of a
migrated shape is then checked against the same constraints as the copied
string list or flat path it replaces, and a result's ``path`` is the field
name.

The boundary is closed-world: a key that names no field of the shape
is an "unknown-field" violation, not silently dropped. A field the payload
omits takes its property's ``sh:defaultValue``, if it has one, before
validation; nothing else is filled in.

``handler_values`` prepares an entity for a Python handler: each
``xsd:decimal`` value becomes a ``decimal.Decimal``, as the handler stub
types it. A ``Decimal`` in a payload (what such a handler returns) is
normalised back to its plain lexical form, so stored state stays JSON.

``problem_body`` builds and validates the RFC 9457 problem+json body of an
error an operation declares (ADR-0013): ``title`` from the status's
rdfs:label, ``status`` from its hydra:statusCode, ``detail`` and extension
members from the raiser, checked against the status's seam:returnsShape.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from pyshacl import validate as _shacl_validate
from rdflib import RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH, XSD

from .errors import ContractViolation, ResolutionError
from .model import HYDRA, SEAM, ModelGraph, local_name

# The predicates of a flattened field's free property that the outer
# property already says (its path, counts, name, label and order) or that do
# not constrain a value; every other one is a value constraint and is lowered
# onto the outer property (ADR-0023 section 5).
_OUTER = frozenset(
    {SH.path, SH.minCount, SH.maxCount, SH.name, SH.order, SH.description, SH.group, SH.defaultValue, RDFS.label}
)

# Echoed values in results are capped so a 16001-char payload is not mirrored
# back whole in a 422 body.
MAX_ECHO = 200

# Lexical-form checks for datatypes rdflib would otherwise cast noisily
# (it logs a traceback on an ill-formed xsd:dateTime).
_DECIMAL = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")


def _decimal(text: str) -> None:
    if not _DECIMAL.fullmatch(text):
        raise ValueError(f"{text!r} is not an xsd:decimal lexical form")


_LEXICAL = {
    XSD.dateTime: _dt.datetime.fromisoformat,
    XSD.date: _dt.date.fromisoformat,
    XSD.integer: int,
    XSD.decimal: _decimal,
}


def _echo(value):
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= MAX_ECHO else text[:MAX_ECHO] + f"... ({len(text)} chars)"


@dataclass(frozen=True)
class ShapeContract:
    """One shape's own triples (a standalone shapes graph) and its fields."""

    shape: URIRef
    graph: Graph
    fields: dict  # field name -> (path IRI, sh:datatype or None)
    defaults: dict  # field name -> sh:defaultValue as a Python value
    names: dict  # path IRI -> field name, for a result's path


def _copy_closure(src: Graph, dst: Graph, node) -> None:
    """Copy every triple of ``node`` and, recursively, of the blank nodes it
    reaches (property shapes, rdf:List cells for sh:in)."""
    stack, seen = [node], set()
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for p, o in src.predicate_objects(n):
            dst.add((n, p, o))
            if isinstance(o, BNode):
                stack.append(o)


def shape_contract(model: ModelGraph, shape) -> ShapeContract:
    """The cached contract of ``shape`` (CURIE or IRI) on this ModelGraph.

    Fields come from the typed view (``model.shape(...).fields()``), so a
    fault the view names (an empty category, an ambiguous ``sh:node``)
    raises its ``ResolutionError`` here, before any payload is read."""
    iri = model.curie(shape)
    cached = model._contract_cache.get(iri)
    if cached is not None:
        return cached
    src = model.shape_graph()
    if (iri, RDF.type, SH.NodeShape) not in src:
        raise ResolutionError(iri, RDF.type, "not an sh:NodeShape in the shape graph")
    g = Graph()
    for prefix, ns in model.ds.namespaces():
        g.bind(prefix, ns)
    _copy_closure(src, g, iri)
    g.remove((iri, SH.targetClass, None))
    by_path = {f.iri: f for f in model.shape(iri).fields()}
    fields, defaults, names = {}, {}, {}
    for prop in sorted(g.objects(iri, SH.property), key=str):
        f = by_path.get(g.value(prop, SH.path))
        if f is None:
            continue
        _lower(src, g, prop, f)
        fields[f.name] = (f.iri, f.datatype)
        names[f.iri] = f.name
        default = g.value(prop, SH.defaultValue)
        if isinstance(default, Literal):
            defaults[f.name] = default.toPython()
    contract = ShapeContract(iri, g, fields, defaults, names)
    model._contract_cache[iri] = contract
    return contract


def _lower(src: Graph, g: Graph, prop, f) -> None:
    """Rewrite property shape ``prop`` of field ``f`` in ``g`` to the
    constraints of its wire value (ADR-0023 section 5)."""
    if f.node is not None:
        g.remove((prop, SH.node, None))
        free = next(p for p in src.objects(f.node.shape, SH.property) if src.value(p, SH.path) == f.node.free_path)
        for p, o in sorted(src.predicate_objects(free), key=str):
            if p in _OUTER:
                continue
            g.add((prop, p, o))
            if isinstance(o, BNode):
                _copy_closure(src, g, o)
    if f.members:
        listed = g.value(prop, SH["in"])
        if listed is not None:
            Collection(g, listed).clear()
        g.remove((prop, SH["in"], None))
        g.remove((prop, SH["class"], None))
        g.set((prop, SH.datatype, f.datatype))
        head = BNode()
        Collection(g, head, [Literal(o) for o in f.options])
        g.add((prop, SH["in"], head))


def _items(payload) -> list[tuple[str, object]]:
    """(key, value) pairs; MultiDict-style inputs keep every value of a key,
    single values unwrap to the value itself. In MultiDict-style (form)
    inputs an empty string is no value: HTML forms submit every field, so an
    empty textarea must fail sh:minCount rather than pass as ""."""
    getlist = getattr(payload, "getlist", None)
    out = []
    for key in dict.fromkeys(payload.keys()):
        if getlist is not None:
            values = [v for v in getlist(key) if v != ""]
        else:
            values = payload[key]
        if isinstance(values, (list, tuple)):
            values = [v for v in values if v is not None]
            if not values:
                continue
            value = values[0] if len(values) == 1 else values
        else:
            value = values
        if value is None:
            continue
        out.append((str(key), value))
    return out


def _well_formed(value, datatype) -> bool:
    if isinstance(value, Decimal):
        return value.is_finite()  # xsd:decimal has no NaN or infinity
    check = _LEXICAL.get(datatype)
    if check is None or not isinstance(value, str):
        return True
    try:
        check(value)
    except ValueError:
        return False
    return True


def _literal(value, datatype) -> Literal:
    """Strings take the property's sh:datatype; other Python values keep their
    natural datatype (so an int for an xsd:string path fails sh:datatype)."""
    if isinstance(value, str) and datatype not in (None, XSD.string):
        return Literal(value, datatype=datatype)
    if isinstance(value, str):
        # Plain literal: RDF 1.1 equates it with xsd:string, but rdflib does
        # not, and the shape's sh:in lists are plain ("composing" ...).
        return Literal(value)
    return Literal(value)


def to_rdf(model: ModelGraph, shape, payload: Mapping, focus=None, operation=None) -> tuple[Graph, URIRef, dict]:
    """(data graph, focus node, normalised payload) for ``payload`` against ``shape``.

    Raises ContractViolation before any SHACL run for keys the shape has no
    sh:path for ("unknown-field") and for strings that are not a lexical form
    of the path's sh:datatype ("DatatypeConstraintComponent")."""
    contract = shape_contract(model, shape)
    focus = URIRef(focus) if focus is not None else URIRef(f"urn:uuid:{uuid.uuid4()}")
    items = _items(payload)
    name = local_name(contract.shape)
    errors = []
    for key, value in items:
        if key not in contract.fields:
            errors.append(
                {
                    "shape": str(contract.shape),
                    "focus": str(focus),
                    "path": key,
                    "constraint": "unknown-field",
                    "value": None,
                    "message": f"{key!r} is not a sh:path of {name}",
                }
            )
            continue
        datatype = contract.fields[key][1]
        for v in value if isinstance(value, list) else [value]:
            if not _well_formed(v, datatype):
                errors.append(
                    {
                        "shape": str(contract.shape),
                        "focus": str(focus),
                        "path": key,
                        "constraint": "DatatypeConstraintComponent",
                        "value": _echo(v),
                        "message": f"{key} of {name}: not a valid {local_name(datatype)}",
                    }
                )
    if errors:
        errors.sort(key=lambda d: (d["path"], d["constraint"]))
        raise ContractViolation(contract.shape, errors, focus=focus, operation=operation)
    given = {key for key, _value in items}
    items += [(key, value) for key, value in sorted(contract.defaults.items()) if key not in given]
    g = Graph()
    normalised = {}
    for key, value in items:
        path, datatype = contract.fields[key]
        for v in value if isinstance(value, list) else [value]:
            g.add((focus, path, _literal(v, datatype)))
        normalised[key] = [_stored(v) for v in value] if isinstance(value, list) else _stored(value)
    return g, focus, normalised


def _stored(value):
    """A Decimal (a handler's xsd:decimal) is kept as its plain lexical form,
    so instance state stays JSON (``handler_values`` turns it back)."""
    return format(value, "f") if isinstance(value, Decimal) else value


def handler_values(model: ModelGraph, shape, data: Mapping) -> dict:
    """``data`` of ``shape`` as a Python handler gets it: each value of an
    xsd:decimal field becomes a ``decimal.Decimal`` (element-wise for a
    list), so a handler stub's ``Decimal`` annotation holds at run time.
    Values of other fields, and booleans, are passed as they are. HTTP and
    LLM bodies stay JSON and never go through this."""
    contract = shape_contract(model, shape)
    out = dict(data)
    for key, value in out.items():
        field = contract.fields.get(key)
        if field is None or field[1] != XSD.decimal:
            continue
        out[key] = [_decimal_value(v) for v in value] if isinstance(value, list) else _decimal_value(value)
    return out


def _decimal_value(value):
    if isinstance(value, bool) or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _results(results: Graph, shape: URIRef, names: dict) -> list[dict]:
    """The report's results as error dicts, a result's path named by its
    field name; a sh:Warning result is never an error (ADR-0021)."""
    out = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        if results.value(r, SH.resultSeverity) == SH.Warning:
            continue
        path = results.value(r, SH.resultPath)
        comp = results.value(r, SH.sourceConstraintComponent)
        value = results.value(r, SH.value)
        msg = results.value(r, SH.resultMessage)
        out.append(
            {
                "shape": str(shape),
                "focus": str(results.value(r, SH.focusNode)),
                "path": None if path is None else names.get(path, local_name(path)),
                "constraint": None if comp is None else local_name(comp),
                "value": _echo(value),
                "message": _echo(msg),
            }
        )
    out.sort(key=lambda d: (d["path"] or "", d["constraint"] or "", d["value"] or ""))
    return out


def validate(model: ModelGraph, shape, payload: Mapping, operation=None) -> dict:
    """Validate ``payload`` against ``shape``; return the normalised payload
    (a plain dict, single-valued form inputs as str) or raise ContractViolation."""
    contract = shape_contract(model, shape)
    data, focus, normalised = to_rdf(model, contract.shape, payload, operation=operation)
    _conforms, results, _text = _shacl_validate(
        data,
        shacl_graph=contract.graph,
        focus_nodes=[focus],
        use_shapes=[contract.shape],
        inference="none",
        advanced=False,
    )
    errors = _results(results, contract.shape, contract.names)
    if errors:
        raise ContractViolation(contract.shape, errors, focus=focus, operation=operation)
    return normalised


def with_correlation_key(model: ModelGraph, shape, payload: Mapping, correlation_key: str | None) -> Mapping:
    """``payload`` with every field of ``shape`` whose sh:name is a
    proc:correlationKey label, and that the payload omits, set to
    ``correlation_key`` (ADR-0036 section 3). The field is found by matching
    the contract's names against ``model.correlation_key_labels()``, so a
    payment names the expense its instance is keyed by. A payload that gives
    the field keeps its value; with no key field to fill, or no key, the
    payload is returned unchanged."""
    if not correlation_key:
        return payload
    names = sorted(set(shape_contract(model, shape).fields) & model.correlation_key_labels())
    items = _items(payload)
    given = {key for key, _value in items}
    missing = [name for name in names if name not in given]
    if not missing:
        return payload
    return {**dict(items), **dict.fromkeys(missing, str(correlation_key))}


def problem_body(model: ModelGraph, operation, code: str, detail=None, extensions=None) -> tuple[int, dict]:
    """(HTTP status, validated problem+json body) for the error ``code`` of
    ``operation`` (CURIE or IRI), ADR-0013.

    Raises ``ResolutionError`` when the operation declares no
    hydra:possibleStatus with that comm:errorCode (subject the operation,
    predicate comm:errorCode) or the status lacks its hydra:statusCode or
    seam:returnsShape, and ``ContractViolation`` naming the status (as its
    ``operation``) when the body does not conform to the error shape: an
    extension member the shape has no sh:path for, a value of the wrong
    datatype, a missing required member."""
    op = model.operations.by_iri(model.curie(operation))
    status = op.error(code)
    status_code = status.status_code
    if status_code is None:
        raise ResolutionError(status.iri, HYDRA.statusCode, "an error status needs its HTTP status code")
    shape = status.returns
    if shape is None:
        raise ResolutionError(status.iri, SEAM.returnsShape, "an error status needs an error shape")
    body: dict = {"title": model.label(status.iri), "status": status_code}
    if detail is not None:
        body["detail"] = detail
    body.update(extensions or {})
    return status_code, validate(model, shape.iri, body, operation=status.iri)
