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

``run_import`` reads a CML file (``parse``: the relationships of every
``ContextMap`` and the context names it holds), decides each relationship's type
from its roles (``decide``, ADR-0034 section 3), resolves each name to the
model's arch:BoundedContext with that local name and builds one ``seams_edit``
patch of the four ADR-0032 facts per new relationship, in the graph that
declares the upstream context, applied as ``seams migrate`` applies its patch.
A relationship IRI is the upstream context's namespace plus the CML name, or
``<upstream>_to_<downstream>`` without one. The patch only adds facts missing
from the files as written, so an unchanged model keeps its bytes. Everything
it cannot map is returned as a ``(construct, reason)`` flag and skipped. A file
it cannot read raises ``CmlError`` naming the line, before anything is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import seams
from rdflib import RDF, URIRef
from seams import ARCH, local_name

import seams_edit

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


# --- import (ADR-0034 sections 3 to 5) ---------------------------------------

_TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<comment>//[^\n]*|/\*.*?\*/)|(?P<string>\"(?:[^\"\\\n]|\\.)*\")"
    r"|(?P<arrow><->|->|<-)|(?P<word>[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z_][A-Za-z0-9_]*)*)|(?P<other>\S)",
    re.DOTALL,
)

# The CML roles a relationship end can carry.
ROLES = frozenset({"U", "D", "S", "C", "OHS", "PL", "ACL", "CF", "SK", "P"})

# CML's keyword connectors: (left end is upstream, implied roles on (left, right)).
_KEYWORDS: dict[str, tuple[bool, frozenset[str], frozenset[str]]] = {
    "Upstream-Downstream": (True, frozenset(), frozenset()),
    "Downstream-Upstream": (False, frozenset(), frozenset()),
    "Supplier-Customer": (True, frozenset({"S"}), frozenset({"C"})),
    "Customer-Supplier": (False, frozenset({"C"}), frozenset({"S"})),
    "Shared-Kernel": (True, frozenset({"SK"}), frozenset({"SK"})),
    "Partnership": (True, frozenset({"P"}), frozenset({"P"})),
}

# The roles each type's rule reads (ADR-0034 section 3); U and D only mark the ends.
_USED: dict[URIRef, frozenset[str]] = {
    ARCH.AntiCorruptionLayer: frozenset({"ACL"}),
    ARCH.Conformist: frozenset({"CF"}),
    ARCH.CustomerSupplier: frozenset({"S", "C"}),
    ARCH.PublishedLanguage: frozenset({"PL", "OHS"}),
    ARCH.SharedKernel: frozenset({"SK"}),
}


class CmlError(Exception):
    """A CML file the import cannot read: ``line`` is the 1-based line of the fault."""

    def __init__(self, line: int, detail: str) -> None:
        super().__init__(f"line {line}: {detail}")
        self.line = line
        self.detail = detail


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str
    line: int


@dataclass(frozen=True)
class CmlRelationship:
    """One relationship line, oriented: ``upstream`` is the end the arrow leaves
    (the left end of ``<->`` and the symmetric keywords)."""

    upstream: str
    downstream: str
    up_roles: frozenset[str]
    down_roles: frozenset[str]
    symmetric: bool
    name: str | None
    text: str
    line: int


@dataclass(frozen=True)
class CmlFile:
    """What the import reads from a CML file: the relationships, in file order,
    the context names the maps contain and the files declare, and one
    ``(construct, reason)`` per item it skips without reading."""

    relationships: tuple[CmlRelationship, ...]
    contexts: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]


def _tokens(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos, line = 0, 1
    while pos < len(text):
        if text.startswith("/*", pos) and text.find("*/", pos + 2) < 0:
            raise CmlError(line, "unterminated /* comment")
        if text[pos] == '"' and not re.match(r"\"(?:[^\"\\\n]|\\.)*\"", text[pos:]):
            raise CmlError(line, "unterminated string")
        m = _TOKEN.match(text, pos)
        assert m is not None and m.lastgroup is not None  # the "other" group matches any non-space
        if m.lastgroup not in ("space", "comment"):
            tokens.append(_Tok(m.lastgroup, m.group(), line))
        line += m.group().count("\n")
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.tokens = tokens
        self.i = 0
        self.relationships: list[CmlRelationship] = []
        self.contexts: list[str] = []
        self.skipped: list[tuple[str, str]] = []

    def peek(self, ahead: int = 0) -> _Tok | None:
        j = self.i + ahead
        return self.tokens[j] if j < len(self.tokens) else None

    def take(self, what: str) -> _Tok:
        tok = self.peek()
        if tok is None:
            last = self.tokens[-1].line if self.tokens else 1
            raise CmlError(last, f"expected {what}, found the end of the file")
        self.i += 1
        return tok

    def expect(self, text: str) -> _Tok:
        tok = self.take(repr(text))
        if tok.text != text:
            raise CmlError(tok.line, f"expected {text!r}, found {tok.text!r}")
        return tok

    def word(self, what: str) -> _Tok:
        tok = self.take(what)
        if tok.kind != "word":
            raise CmlError(tok.line, f"expected {what}, found {tok.text!r}")
        return tok

    def block(self) -> bool:
        """Skip a balanced ``{ ... }`` at the cursor; True when it held anything."""
        open_ = self.expect("{")
        depth, empty = 1, True
        while depth:
            tok = self.peek()
            if tok is None:
                raise CmlError(open_.line, "unclosed '{'")
            self.i += 1
            if tok.text == "{":
                depth += 1
            elif tok.text == "}":
                depth -= 1
            if depth:
                empty = False
        return not empty

    def document(self) -> CmlFile:
        while self.peek() is not None:
            tok = self.word("a CML declaration")
            if tok.text == "ContextMap":
                self.context_map()
            elif tok.text == "BoundedContext":
                self.bounded_context()
            else:
                self.other(tok)
        return CmlFile(tuple(self.relationships), tuple(self.contexts), tuple(self.skipped))

    def other(self, keyword: _Tok) -> None:
        """A declaration the graph has its own sources for: skip its header and body."""
        name = self.peek()
        label = keyword.text + (f" {name.text}" if name is not None and name.kind in ("word", "string") else "")
        self.skipped.append((label, "the graph does not read this from CML (ADR-0034 section 4)"))
        while (tok := self.peek()) is not None and tok.text != "{" and not _starts_declaration(tok, keyword):
            self.i += 1
        if tok is not None and tok.text == "{":
            self.block()

    def bounded_context(self) -> None:
        name = self.word("a BoundedContext name")
        self.contexts.append(name.text)
        attributes = False
        while (tok := self.peek()) is not None and tok.text != "{" and not _starts_declaration(tok, name):
            attributes = True
            self.i += 1
        if tok is not None and tok.text == "{":
            attributes = self.block() or attributes
        if attributes:
            self.skipped.append(
                (
                    f"BoundedContext {name.text} attributes",
                    "BoundedContext attributes are not read (ADR-0034 section 1)",
                )
            )

    def context_map(self) -> None:
        tok = self.peek()
        if tok is not None and tok.kind == "word":
            self.i += 1
        self.expect("{")
        while (tok := self.peek()) is None or tok.text != "}":
            tok = self.word("a ContextMap statement or '}'")
            if tok.text == "contains":
                self.contexts.append(self.word("a context name").text)
                while (sep := self.peek()) is not None and sep.text == ",":
                    self.i += 1
                    self.contexts.append(self.word("a context name").text)
            elif tok.text in ("type", "state") and not self.is_relationship():
                if (eq := self.peek()) is not None and eq.text == "=":
                    self.i += 1
                value = self.word(f"a ContextMap {tok.text}")
                self.skipped.append((f"ContextMap {tok.text} {value.text}", "the graph has no fact for it"))
            else:
                self.relationship(tok)
        self.i += 1

    def is_relationship(self) -> bool:
        tok = self.peek()
        return tok is not None and (tok.text == "[" or tok.kind == "arrow" or tok.text in _KEYWORDS)

    def roles(self) -> tuple[str, ...]:
        """The roles of a ``[..]`` at the cursor, as written; none without one."""
        tok = self.peek()
        if tok is None or tok.text != "[":
            return ()
        self.i += 1
        roles: list[str] = []
        while True:
            role = self.word("a relationship role")
            if role.text not in ROLES:
                raise CmlError(role.line, f"unknown relationship role {role.text!r}")
            roles.append(role.text)
            sep = self.take("',' or ']'")
            if sep.text == "]":
                return tuple(roles)
            if sep.text != ",":
                raise CmlError(sep.line, f"expected ',' or ']', found {sep.text!r}")

    def relationship(self, left: _Tok) -> None:
        left_roles = self.roles()
        connector = self.take("a relationship arrow")
        if connector.kind == "arrow":
            left_up, symmetric = connector.text != "<-", connector.text == "<->"
            implied: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
        elif connector.text in _KEYWORDS:
            left_up, left_implied, right_implied = _KEYWORDS[connector.text]
            implied = (left_implied, right_implied)
            symmetric = connector.text in ("Shared-Kernel", "Partnership")
        else:
            raise CmlError(connector.line, f"{left.text}: expected a relationship arrow, found {connector.text!r}")
        right_roles = self.roles()
        right = self.word("the context on the right of the relationship")
        name: str | None = None
        if (colon := self.peek()) is not None and colon.text == ":":
            self.i += 1
            name = self.word("a relationship name").text
        if connector.kind == "arrow":
            link = f"{_bracket(left_roles)}{connector.text}{_bracket(right_roles)}"
        else:
            link = " ".join(part for part in (_bracket(left_roles), connector.text, _bracket(right_roles)) if part)
        text = f"{left.text} {link} {right.text}" + (f" : {name}" if name else "")
        if (body := self.peek()) is not None and body.text == "{" and self.block():
            self.skipped.append((f"{text} body", "relationship attributes are not read (ADR-0034 section 4)"))
        left_all, right_all = frozenset(left_roles) | implied[0], frozenset(right_roles) | implied[1]
        if left_up:
            up, down, up_roles, down_roles = left.text, right.text, left_all, right_all
        else:
            up, down, up_roles, down_roles = right.text, left.text, right_all, left_all
        self.relationships.append(CmlRelationship(up, down, up_roles, down_roles, symmetric, name, text, left.line))


def _starts_declaration(tok: _Tok, current: _Tok) -> bool:
    """A word at the start of a line below ``current`` that begins a top-level declaration."""
    return tok.kind == "word" and tok.line > current.line and tok.text in _DECLARATIONS


# The top-level CML declarations; a bodiless one ends where the next begins.
_DECLARATIONS = frozenset(
    {
        "ContextMap",
        "BoundedContext",
        "Domain",
        "Subdomain",
        "Aggregate",
        "Module",
        "UseCase",
        "UserStory",
        "UserRequirement",
        "Stakeholders",
        "ValueRegister",
        "import",
    }
)


def _bracket(roles: tuple[str, ...]) -> str:
    return f"[{','.join(roles)}]" if roles else ""


def parse(text: str) -> CmlFile:
    """The context maps and context names of a CML file; ``CmlError`` names the
    line of anything it cannot read."""
    return _Parser(_tokens(text)).document()


def decide(relationship: CmlRelationship) -> tuple[URIRef | None, str]:
    """The arch:relationshipType of a CML relationship (ADR-0034 section 3), or
    None with the reason it has none."""
    up, down = relationship.up_roles, relationship.down_roles
    if "P" in up | down:
        return None, "a partnership has no arch:RelationshipType (ADR-0032)"
    if "ACL" in down:
        return ARCH.AntiCorruptionLayer, ""
    if "CF" in down:
        return ARCH.Conformist, ""
    if {"S", "C"} & (up | down):
        return ARCH.CustomerSupplier, ""
    if "PL" in up:
        return ARCH.PublishedLanguage, ""
    if ("SK" in up and "SK" in down) or (relationship.symmetric and not (up | down)):
        return ARCH.SharedKernel, ""
    if "OHS" in up | down:
        return None, "an open host service alone has no arch:RelationshipType (ADR-0032 folds it into PL)"
    return None, "no role decides an arch:RelationshipType"


@dataclass(frozen=True)
class Import:
    """What ``run_import`` did: the relationships it added (sorted by IRI), the
    files it wrote and one ``(construct, reason)`` per flagged item, in file order."""

    added: tuple[URIRef, ...]
    files: tuple[Path, ...]
    flags: tuple[tuple[str, str], ...]


def _as_written(files: tuple[Path, ...]) -> set[seams_edit.Quad]:
    quads: set[seams_edit.Quad] = set()
    for path in files:
        quads |= set(seams_edit.text_quads(path.read_text(encoding="utf-8"), base=path.as_uri()))
    return quads


def import_patch(
    model: seams.Model, cml: CmlFile
) -> tuple[seams_edit.Patch, tuple[URIRef, ...], tuple[tuple[str, str], ...]]:
    """The patch of the arch facts ``cml`` adds to ``model``, the relationships it
    adds and the flags for what it skips. It never removes a fact."""
    flags = list(cml.skipped)
    written = _as_written(model.files)
    by_name: dict[str, list[URIRef]] = {}
    for c in model.architecture.contexts():
        by_name.setdefault(local_name(c.iri), []).append(c.iri)

    def resolve(name: str) -> tuple[URIRef | None, str]:
        iris = by_name.get(name, [])
        if len(iris) == 1:
            return iris[0], ""
        if not iris:
            return None, f"{name} matches no arch:BoundedContext in the model"
        return None, f"{name} names {len(iris)} arch:BoundedContexts: {', '.join(sorted(map(str, iris)))}"

    for name in sorted(set(cml.contexts)):
        if resolve(name)[0] is None:
            flags.append((f"BoundedContext {name}", resolve(name)[1]))
    # Each related pair, unordered, to (upstream, downstream, type): ADR-0032's one per pair.
    pairs: dict[frozenset[URIRef], tuple[URIRef, URIRef, URIRef]] = {}
    ds = model.ds
    for r in sorted({r for r in ds.subjects(RDF.type, ARCH.ContextRelationship) if isinstance(r, URIRef)}, key=str):
        up, down, kind = ds.value(r, ARCH.upstream), ds.value(r, ARCH.downstream), ds.value(r, ARCH.relationshipType)
        if isinstance(up, URIRef) and isinstance(down, URIRef) and isinstance(kind, URIRef):
            pairs.setdefault(frozenset((up, down)), (up, down, kind))
    adds: set[seams_edit.Quad] = set()
    added: list[URIRef] = []
    for r in cml.relationships:
        kind, reason = decide(r)
        if kind is None:
            flags.append((r.text, reason))
            continue
        unused = sorted((r.up_roles | r.down_roles) - _USED[kind] - {"U", "D"})
        if unused:
            flags.append((f"{r.text} role {', '.join(unused)}", f"the relationship keeps one type, {local_name(kind)}"))
        (up, up_reason), (down, down_reason) = resolve(r.upstream), resolve(r.downstream)
        if up is None or down is None:
            flags.append((r.text, up_reason or down_reason))
            continue
        if up == down:
            flags.append((r.text, "a context does not relate to itself"))
            continue
        held = pairs.get(frozenset((up, down)))
        if held == (up, down, kind):
            continue
        if held is not None:
            flags.append(
                (
                    r.text,
                    f"the model already relates {local_name(held[0])} to {local_name(held[1])} as {local_name(held[2])}",
                )
            )
            continue
        iri = URIRef(
            str(up)[: len(str(up)) - len(local_name(up))] + (r.name or f"{local_name(up)}_to_{local_name(down)}")
        )
        if (iri, None, None) in ds or iri in added:
            flags.append((r.text, f"{iri} is already in the model"))
            continue
        graphs = sorted({g for s, p, o, g in written if (s, p, o) == (up, RDF.type, ARCH.BoundedContext)}, key=str)
        if len(graphs) != 1:
            flags.append(
                (
                    r.text,
                    f"{local_name(up)} is declared in {len(graphs)} graphs, so the relationship's graph is ambiguous",
                )
            )
            continue
        g = graphs[0]
        facts = (
            (RDF.type, ARCH.ContextRelationship),
            (ARCH.upstream, up),
            (ARCH.downstream, down),
            (ARCH.relationshipType, kind),
        )
        adds |= {(iri, p, o, g) for p, o in facts} - written
        pairs[frozenset((up, down))] = (up, down, kind)
        added.append(iri)
    return seams_edit.Patch(adds=adds), tuple(sorted(added, key=str)), tuple(flags)


def run_import(project: Project, model: Path | None, cml_file: Path) -> Import:
    """Add the relationships of ``cml_file`` to the project's model. A parse error
    raises ``CmlError`` before anything is written."""
    cml = parse(cml_file.read_text(encoding="utf-8"))
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    patch, added, flags = import_patch(loaded, cml)
    if patch.is_empty:
        return Import(added, (), flags)
    record = seams_edit.apply(loaded.files, patch)
    return Import(added, tuple(sorted(edit.path for edit in record.files)), flags)
