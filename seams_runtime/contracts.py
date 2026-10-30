"""SHACL contract validation at the call boundary (ADR-0007).

A payload crossing a seam is a flat mapping of field name to value. Field
names are the local names of the shape's ``sh:path`` properties.
``to_rdf`` turns the payload into a one-node data graph. ``validate`` runs
pySHACL against just that shape and raises ``ContractViolation`` with one
entry per result (shape, focus, path, constraint, value, message).

The boundary is closed-world: a key that names no ``sh:path`` of the shape
is an "unknown-field" violation, not silently dropped. A field the payload
omits takes its property's ``sh:defaultValue``, if it has one, before
validation; nothing else is filled in.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from pyshacl import validate as _shacl_validate
from rdflib import RDF, BNode, Graph, Literal, URIRef
from rdflib.namespace import SH, XSD

from .errors import ContractViolation, ResolutionError
from .model import ModelGraph, local_name

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
    fields: dict  # local name -> (path IRI, sh:datatype or None)
    defaults: dict  # local name -> sh:defaultValue as a Python value


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
    """The cached contract of ``shape`` (CURIE or IRI) on this ModelGraph."""
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
    fields, defaults = {}, {}
    for prop in g.objects(iri, SH.property):
        path = g.value(prop, SH.path)
        if isinstance(path, URIRef):
            fields[local_name(path)] = (path, g.value(prop, SH.datatype))
            default = g.value(prop, SH.defaultValue)
            if isinstance(default, Literal):
                defaults[local_name(path)] = default.toPython()
    contract = ShapeContract(iri, g, fields, defaults)
    model._contract_cache[iri] = contract
    return contract


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
        normalised[key] = value
    return g, focus, normalised


def _results(results: Graph, shape: URIRef) -> list[dict]:
    out = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        path = results.value(r, SH.resultPath)
        comp = results.value(r, SH.sourceConstraintComponent)
        value = results.value(r, SH.value)
        msg = results.value(r, SH.resultMessage)
        out.append(
            {
                "shape": str(shape),
                "focus": str(results.value(r, SH.focusNode)),
                "path": None if path is None else local_name(path),
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
    conforms, results, _text = _shacl_validate(
        data,
        shacl_graph=contract.graph,
        focus_nodes=[focus],
        use_shapes=[contract.shape],
        inference="none",
        advanced=False,
    )
    if not conforms:
        raise ContractViolation(contract.shape, _results(results, contract.shape), focus=focus, operation=operation)
    return normalised
