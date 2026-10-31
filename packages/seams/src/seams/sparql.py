"""SPARQL over a loaded model, with the project's prefixes bound.

``sparql`` runs a read-only query against ``model.ds`` with ``PREFIXES``
pre-declared, so a query needs no PREFIX lines for the seams vocabularies.
``question_names`` and ``load_question`` read the canned questions bundled
as package data in ``seams/queries`` (byte-identical copies of
``docs/queries/*.rq``; ``tests/test_seams_query.py`` guards the drift).
``Model.sparql`` and ``Model.question`` wrap these and return rows.
"""

from __future__ import annotations

import re
from importlib import resources
from typing import TYPE_CHECKING, Any, cast

from rdflib import RDF, RDFS, XSD, Literal, Namespace, URIRef
from rdflib.namespace import SH
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.query import Result, ResultRow
from rdflib.term import Identifier, Node

from .namespaces import ARCH, COMM, DEC, DEPLOY, HYDRA, IFML, ODRL, PROC, SEAM, STATE

if TYPE_CHECKING:
    from .loader import Model

#: Prefix -> namespace, pre-declared for every query.
PREFIXES: dict[str, Namespace] = {
    "seam": SEAM,
    "comm": COMM,
    "dec": DEC,
    "proc": PROC,
    "state": STATE,
    "hydra": HYDRA,
    "odrl": ODRL,
    "deploy": DEPLOY,
    "ifml": IFML,
    "arch": ARCH,
    "rdf": Namespace(str(RDF)),
    "rdfs": Namespace(str(RDFS)),
    "sh": Namespace(str(SH)),
    "xsd": Namespace(str(XSD)),
}

#: A row: variable name -> bound term. Unbound variables are absent.
Row = dict[str, Node]

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_PROLOGUE = re.compile(r"\s*(?:#[^\n]*|(?i:PREFIX)\s+[\w.-]*:\s*<[^>]*>|(?i:BASE)\s*<[^>]*>)")
_UPDATES = {"INSERT", "DELETE", "LOAD", "CLEAR", "DROP", "CREATE", "ADD", "MOVE", "COPY", "WITH"}


def _first_keyword(query: str) -> str:
    """The first word after comments and PREFIX/BASE declarations, upper-cased."""
    pos = 0
    while (m := _PROLOGUE.match(query, pos)) and m.end() > pos:
        pos = m.end()
    word = re.match(r"\s*([A-Za-z]*)", query[pos:])
    return word.group(1).upper() if word else ""


def _is_ordered(algebra: object) -> bool:
    """Whether the query algebra contains an ORDER BY."""
    if isinstance(algebra, CompValue):
        node = algebra
        if node.name == "OrderBy":
            return True
        return any(_is_ordered(v) for v in cast(dict[str, object], node).values())
    if isinstance(algebra, (list, tuple)):
        return any(_is_ordered(v) for v in cast("list[object]", algebra))
    return False


def _term(model: Model, value: object) -> Identifier:
    """URIRefs and Literals pass through; a str containing ':' is a CURIE or
    IRI expanded via ``Model.curie``; anything else becomes a Literal."""
    if isinstance(value, (URIRef, Literal)):
        return value
    if isinstance(value, str) and ":" in value:
        return model.curie(value)
    return Literal(value)


def _execute(model: Model, query: str, bindings: dict[str, Any]) -> tuple[Result, bool]:
    keyword = _first_keyword(query)
    if keyword in _UPDATES:
        raise ValueError(f"seams SPARQL is read-only: refusing a {keyword} update")
    prepared = prepareQuery(query, initNs=dict(PREFIXES))
    init = {name: _term(model, value) for name, value in bindings.items()}
    result = model.ds.query(prepared, initBindings=init)
    return result, _is_ordered(prepared.algebra)


def sparql(model: Model, query: str, /, **bindings: Any) -> Result:
    """Run a read-only query against ``model.ds`` with ``PREFIXES`` bound.

    Each keyword binds the variable of that name (see ``_term`` for how
    values become terms). An update (INSERT, DELETE, LOAD, ...) raises
    ValueError before anything runs.
    """
    return _execute(model, query, bindings)[0]


def rows(model: Model, query: str, /, **bindings: Any) -> list[Row]:
    """A SELECT query's rows in deterministic order: the query's ORDER BY
    when it has one, else sorted by the tuple of their str values (in
    projection order, unbound as "")."""
    result, ordered = _execute(model, query, bindings)
    if result.type != "SELECT":
        raise ValueError(f"rows() needs a SELECT query, got {result.type}; use sparql() instead")
    names = [str(v) for v in result.vars or ()]
    out: list[Row] = [{str(k): v for k, v in row.asdict().items()} for row in result if isinstance(row, ResultRow)]
    if not ordered:
        out.sort(key=lambda row: tuple(str(row.get(n, "")) for n in names))
    return out


def question_names() -> list[str]:
    """The bundled canned questions, by name (the .rq file stem), sorted."""
    folder = resources.files("seams") / "queries"
    return sorted(p.name[:-3] for p in folder.iterdir() if p.is_file() and p.name.endswith(".rq"))


def load_question(name: str) -> str:
    """The SPARQL text of a bundled question. An unknown or malformed name
    raises KeyError before any path is built from it."""
    available = question_names()
    if not _NAME.fullmatch(name) or name not in available:
        raise KeyError(f"unknown question {name!r}; available: {', '.join(available)}")
    return (resources.files("seams") / "queries" / f"{name}.rq").read_text(encoding="utf-8")
