"""The TriG text writer: applies a patch by editing the source text at the triple level.

ADR-0017: the writer never re-serialises the graph. It reads enough of TriG (prefixes,
graph blocks, statements, ``;`` and ``,`` lists, ``a``, ``[ ]`` blank nodes,
collections, long and multi-line literals, comments) to know where each triple is
written, and edits only that text. Comments and layout it does not touch are kept byte
for byte. After editing it re-parses the result with rdflib and checks, per named graph
by isomorphism, that it means the old text with the patch applied.

Blank nodes have no names of their own in the text, so the writer labels them in
document order under a hash of the text; :func:`text_quads` returns the quads under
those labels, and a patch that names an existing blank node uses them. A label from an
older version of the text names nothing in the current one, so the inverse of a patch
that removed a ``[ ]`` writes it back as new. A blank node new to the text is written
inline as ``[ ... ]`` under the added quad that has it as its object.

Everything here is a pure function on text: reading and writing files is the caller's.
"""

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from rdflib import Dataset, Graph
from rdflib.compare import isomorphic
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import RDF, XSD
from rdflib.term import BNode, Literal, Node, URIRef

from .patch import Patch, PatchError, Quad, quad_key
from .patch import term_text as _n3

# Tokens -----------------------------------------------------------------------

_NAME_CHAR = r"[^\s<>\"'{}\[\](),;#^\\.]"
_INTEGER = r"[+-]?\d+"
_DECIMAL = r"[+-]?\d*\.\d+"
_DOUBLE = r"[+-]?(?:\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+|\d+[eE][+-]?\d+)"

_TOKEN = re.compile(
    "|".join(
        [
            r"(?P<ws>\s+)",
            r"(?P<comment>#[^\r\n]*)",
            r"(?P<iri><(?:[^<>\"{}|^`\\\x00-\x20]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*>)",
            "(?P<string>"
            + r'"""(?:(?:"|"")?(?:[^"\\]|\\.))*"""'
            + r"|'''(?:(?:'|'')?(?:[^'\\]|\\.))*'''"
            + r'|"(?:[^"\\\r\n]|\\.)*"'
            + r"|'(?:[^'\\\r\n]|\\.)*'"
            + ")",
            rf"(?P<number>{_DOUBLE}|{_DECIMAL}|{_INTEGER})",
            rf"(?P<name>[A-Za-z_:\u00C0-\U000EFFFF](?:{_NAME_CHAR}|\\.|\.(?={_NAME_CHAR}))*)",
            r"(?P<at>@[A-Za-z]+(?:-[A-Za-z0-9]+)*)",
            r"(?P<punct>\^\^|[.;,\[\](){}])",
        ]
    ),
    re.DOTALL,
)

_ECHAR = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}
_STRING_ESCAPE = re.compile(r"\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(.))", re.DOTALL)
_LOCAL_ESCAPE = re.compile(r"\\(.)")
# The local names the writer itself spells with a prefix: a safe subset of PN_LOCAL.
_PLAIN_LOCAL = re.compile(r"(?:[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?)?")
_BARE = {XSD.integer: re.compile(_INTEGER), XSD.decimal: re.compile(_DECIMAL), XSD.double: re.compile(_DOUBLE)}
# Relative IRIs resolve against the caller's base: the file's URI, as when seams.load
# parses the file. Without one, a fixed base keeps the result independent of the host.
DEFAULT_BASE = "file:///"


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str
    start: int
    end: int


class _Unreadable(Exception):
    """TriG the writer cannot read; names the line."""

    def __init__(self, text: str, pos: int, detail: str) -> None:
        self.line = text.count("\n", 0, pos) + 1
        self.detail = detail
        super().__init__(f"line {self.line}: {detail}")


def _tokenise(text: str) -> tuple[list[_Tok], list[int]]:
    tokens: list[_Tok] = []
    comments: list[int] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or m.lastgroup is None:
            raise _Unreadable(text, pos, f"unexpected {text[pos]!r}")
        if m.lastgroup == "comment":
            comments.append(pos)
        elif m.lastgroup != "ws":
            tokens.append(_Tok(m.lastgroup, m.group(), pos, m.end()))
        pos = m.end()
    return tokens, comments


def _unescape_string(body: str) -> str:
    def one(m: re.Match[str]) -> str:
        hex_code = m.group(1) or m.group(2)
        if hex_code:
            return chr(int(hex_code, 16))
        return _ECHAR.get(m.group(3), "\\" + m.group(3))

    return _STRING_ESCAPE.sub(one, body)


# Where the triples are --------------------------------------------------------


@dataclass
class _Obj:
    node: Node
    start: int
    end: int
    # quads written inside this object's [ ] or ( ), which go with it when it goes
    owned: tuple[Quad, ...]


@dataclass
class _Pair:
    pred: Node
    start: int
    objects: list[_Obj]
    end: int  # after the `;` that follow the pair; else after its last object


@dataclass
class _Block:
    graph: Node
    start: int
    close_start: int = 0
    statements: list["_PList"] = field(default_factory=lambda: [])


@dataclass
class _PList:
    """The predicate-object list of one subject: a statement, or a ``[ ... ]``."""

    subject: Node
    graph: Node
    bracket: bool
    start: int  # statement: subject start; bracket: `[` start
    open_end: int  # statement: subject end; bracket: `[` end
    block: _Block | None
    pairs: list[_Pair] = field(default_factory=lambda: [])
    end: int = 0  # statement: its `.` end (or last pair end); bracket: `]` end
    has_dot: bool = False
    subject_owned: tuple[Quad, ...] = ()  # a statement whose subject is [ ... ] or ( ... )


@dataclass
class _Doc:
    text: str
    quads: list[Quad]
    plists: list[_PList]
    blocks: list[_Block]
    comments: list[int]
    prefixes: dict[str, str]
    base: str
    anonymous: set[BNode]  # blank nodes with no label in the text
    cells: set[BNode]  # collection cells


class _Parser:
    def __init__(self, text: str, base: str) -> None:
        self.text = text
        self.toks, self.comments = _tokenise(text)
        self.i = 0
        self.prefixes: dict[str, str] = {}
        self.base = base
        self.quads: list[Quad] = []
        self.plists: list[_PList] = []
        self.blocks: list[_Block] = []
        self.anonymous: set[BNode] = set()
        self.cells: set[BNode] = set()
        self.graph: Node = DATASET_DEFAULT_GRAPH_ID
        self.block: _Block | None = None
        # Unlabelled blank nodes are numbered in document order under a hash of the
        # text, so a label from one version of the text never names a node of another.
        self.label = "e" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    # token access

    def peek(self, ahead: int = 0) -> _Tok | None:
        j = self.i + ahead
        return self.toks[j] if j < len(self.toks) else None

    def is_next(self, *texts: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "punct" and tok.text in texts

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise _Unreadable(self.text, len(self.text), "unexpected end of text")
        self.i += 1
        return tok

    def expect(self, punct: str) -> _Tok:
        tok = self.take()
        if tok.kind != "punct" or tok.text != punct:
            raise _Unreadable(self.text, tok.start, f"expected {punct!r}, found {tok.text!r}")
        return tok

    def last_end(self) -> int:
        return self.toks[self.i - 1].end

    def fail(self, tok: _Tok, detail: str) -> _Unreadable:
        return _Unreadable(self.text, tok.start, detail)

    def fresh(self) -> BNode:
        node = BNode(f"{self.label}_{len(self.anonymous)}")
        self.anonymous.add(node)
        return node

    # terms

    def iri(self, tok: _Tok) -> URIRef:
        if tok.kind == "iri":
            value = _unescape_string(tok.text[1:-1])
            return URIRef(urljoin(self.base, value))
        if tok.kind == "name" and ":" in tok.text and not tok.text.startswith("_:"):
            prefix, local = tok.text.split(":", 1)
            if prefix not in self.prefixes:
                raise self.fail(tok, f"undeclared prefix {prefix + ':'!r}")
            return URIRef(self.prefixes[prefix] + _LOCAL_ESCAPE.sub(r"\1", local))
        raise self.fail(tok, f"expected an IRI, found {tok.text!r}")

    def term(self, tok: _Tok) -> Node:
        if tok.kind == "name" and tok.text.startswith("_:"):
            return BNode(tok.text[2:])
        if tok.kind == "name" and tok.text in ("true", "false"):
            return Literal(tok.text, datatype=XSD.boolean)
        if tok.kind == "number":
            datatype = next(dt for dt, rx in _BARE.items() if rx.fullmatch(tok.text))
            return Literal(tok.text, datatype=datatype)
        if tok.kind == "string":
            quote = 3 if tok.text[:3] in ('"""', "'''") else 1
            value = _unescape_string(tok.text[quote:-quote])
            nxt = self.peek()
            if nxt is not None and nxt.kind == "at":
                self.take()
                return Literal(value, lang=nxt.text[1:])
            if self.is_next("^^"):
                self.take()
                return Literal(value, datatype=self.iri(self.take()))
            return Literal(value)
        return self.iri(tok)

    # document

    def document(self) -> _Doc:
        while (tok := self.peek()) is not None:
            word = tok.text.upper() if tok.kind == "name" and ":" not in tok.text else ""
            nxt = self.peek(1)
            if tok.kind == "at" and tok.text in ("@prefix", "@base"):
                self.directive(tok.text[1:], dot=True)
            elif word in ("PREFIX", "BASE"):
                self.directive(word.lower(), dot=False)
            elif word == "GRAPH":
                self.take()
                self.graph_block(self.take())
            elif tok.kind == "punct" and tok.text == "{":
                self.graph_block(None)
            elif tok.kind in ("iri", "name") and nxt is not None and nxt.text == "{":
                self.graph_block(self.take())
            else:
                self.statement()
        return _Doc(
            self.text,
            self.quads,
            self.plists,
            self.blocks,
            self.comments,
            self.prefixes,
            self.base,
            self.anonymous,
            self.cells,
        )

    def directive(self, kind: str, *, dot: bool) -> None:
        self.take()
        if kind == "prefix":
            name = self.take()
            if name.kind != "name" or not name.text.endswith(":"):
                raise self.fail(name, f"expected a prefix name, found {name.text!r}")
            self.prefixes[name.text[:-1]] = str(self.iri(self.take()))
        else:
            self.base = str(self.iri(self.take()))
        if dot:
            self.expect(".")

    def graph_block(self, label: _Tok | None) -> None:
        opening = self.peek()
        assert opening is not None
        start = label.start if label is not None else opening.start
        graph: Node = DATASET_DEFAULT_GRAPH_ID
        if label is not None:
            graph = self.term(label)
            if not isinstance(graph, URIRef):
                raise self.fail(label, "the writer reads only IRI graph names")
        self.expect("{")
        block = _Block(graph, start)
        self.graph, self.block = graph, block
        while not self.is_next("}"):
            self.statement()
        block.close_start = self.expect("}").start
        self.graph, self.block = DATASET_DEFAULT_GRAPH_ID, None
        self.blocks.append(block)

    def statement(self) -> None:
        first = self.peek()
        assert first is not None
        mark = len(self.quads)
        bracketed = self.is_next("[")
        if bracketed:
            subject = self.bracket()
        elif self.is_next("("):
            subject = self.collection()
        else:
            subject = self.term(self.take())
            if isinstance(subject, Literal):
                raise self.fail(first, "a literal cannot be a subject")
        plist = _PList(subject, self.graph, False, first.start, self.last_end(), self.block)
        plist.subject_owned = tuple(self.quads[mark:])
        if not (bracketed and self.is_next(".", "}")):
            self.pairs(plist)
        if self.is_next("."):
            plist.end, plist.has_dot = self.take().end, True
        elif self.block is not None and self.is_next("}"):
            plist.end = self.last_end()
        else:
            tok = self.peek()
            raise _Unreadable(self.text, tok.start if tok else len(self.text), "expected '.' after the statement")
        self.plists.append(plist)
        if self.block is not None:
            self.block.statements.append(plist)

    def pairs(self, plist: _PList) -> None:
        while True:
            verb = self.take()
            pred = RDF.type if verb.kind == "name" and verb.text == "a" else self.iri(verb)
            pair = _Pair(pred, verb.start, [], 0)
            while True:
                obj = self.object()
                pair.objects.append(obj)
                self.quads.append((plist.subject, pred, obj.node, self.graph))
                if not self.is_next(","):
                    break
                self.take()
            pair.end = pair.objects[-1].end
            plist.pairs.append(pair)
            if not self.is_next(";"):
                return
            while self.is_next(";"):
                pair.end = self.take().end
            if self.peek() is None or self.is_next(".", "]", "}"):
                return

    def object(self) -> _Obj:
        tok = self.peek()
        if tok is None:
            raise _Unreadable(self.text, len(self.text), "expected an object")
        mark = len(self.quads)
        if self.is_next("["):
            node: Node = self.bracket()
        elif self.is_next("("):
            node = self.collection()
        else:
            node = self.term(self.take())
        return _Obj(node, tok.start, self.last_end(), tuple(self.quads[mark:]))

    def bracket(self) -> BNode:
        opening = self.expect("[")
        node = self.fresh()
        plist = _PList(node, self.graph, True, opening.start, opening.end, self.block)
        if not self.is_next("]"):
            self.pairs(plist)
        plist.end = self.expect("]").end
        self.plists.append(plist)
        return node

    def collection(self) -> Node:
        self.expect("(")
        items: list[Node] = []
        while not self.is_next(")"):
            items.append(self.object().node)
        self.expect(")")
        if not items:
            return RDF.nil
        cells = [self.fresh() for _ in items]
        self.cells.update(cells)
        for k, (cell, item) in enumerate(zip(cells, items, strict=True)):
            self.quads.append((cell, RDF.first, item, self.graph))
            self.quads.append((cell, RDF.rest, cells[k + 1] if k + 1 < len(cells) else RDF.nil, self.graph))
        return cells[0]


def _read(text: str, base: str) -> _Doc:
    return _Parser(text, base).document()


# Spelling terms as an author would --------------------------------------------


def _spell_iri(iri: URIRef, doc: _Doc) -> str:
    for prefix, ns in sorted(doc.prefixes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if iri.startswith(ns) and _PLAIN_LOCAL.fullmatch(iri[len(ns) :]):
            return f"{prefix}:{iri[len(ns) :]}"
    folder = doc.base[: doc.base.rfind("/") + 1]
    if folder and iri.startswith(folder) and _PLAIN_LOCAL.fullmatch(iri[len(folder) :]):
        iri = URIRef(iri[len(folder) :])  # relative, as the author wrote it; never a host path
    if any(c in '<>"{}|^`\\' or ord(c) <= 0x20 for c in iri):
        raise _BadTerm(f"{_n3(iri)} is not a valid IRI")
    return f"<{iri}>"


class _BadTerm(Exception):
    """A term the writer cannot write as TriG."""


def _spell_string(value: str) -> str:
    out = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return '"' + out.replace("\t", "\\t") + '"'


# Editing ----------------------------------------------------------------------


@dataclass
class _Edits:
    doc: _Doc
    removed: frozenset[Quad]
    deletions: list[tuple[int, int, bool]] = field(default_factory=lambda: [])
    insertions: list[tuple[int, int, str]] = field(default_factory=lambda: [])
    # pairs of each predicate-object list left after the removals: (pair, its last kept object)
    kept: dict[int, list[tuple[_Pair, _Obj]]] = field(default_factory=lambda: {})
    gone: set[int] = field(default_factory=lambda: set())  # statements removed whole
    # the added quads of each blank node new to the text, written inline under its parent
    children: dict[Node, list[Quad]] = field(default_factory=lambda: {})

    @property
    def text(self) -> str:
        return self.doc.text

    def delete(self, a: int, b: int, *, widen: bool = False) -> None:
        self.deletions.append((a, b, widen))

    def insert(self, pos: int, text: str) -> None:
        self.insertions.append((pos, len(self.insertions), text))

    # removals

    def remove(self, quads: tuple[Quad, ...]) -> None:
        covered: set[Quad] = set()
        direct: set[Quad] = set()
        for plist in self.doc.plists:
            self._remove_in(plist, covered, direct)
        for quad in quads:
            if quad not in direct and quad not in covered:
                raise PatchError(
                    quad[0], quad[1], "it is written inside a collection; remove the collection's triple as a whole"
                )

    def _remove_in(self, plist: _PList, covered: set[Quad], direct: set[Quad]) -> None:
        flags: list[list[bool]] = []
        for pair in plist.pairs:
            row: list[bool] = []
            for obj in pair.objects:
                quad = (plist.subject, pair.pred, obj.node, plist.graph)
                hit = quad in self.removed
                if hit:
                    direct.add(quad)
                    missing = [q for q in obj.owned if q not in self.removed]
                    if missing:
                        raise PatchError(
                            plist.subject,
                            pair.pred,
                            f"its object {_n3(obj.node)} is written as [ ] or ( ) holding {len(obj.owned)} more"
                            f" triples, and the patch removes only {len(obj.owned) - len(missing)} of them",
                        )
                    covered.update(obj.owned)
                row.append(hit)
            flags.append(row)
        kept: list[tuple[int, _Obj]] = []
        for i, pair in enumerate(plist.pairs):
            alive = [obj for obj, hit in zip(pair.objects, flags[i], strict=True) if not hit]
            if alive:
                kept.append((i, alive[-1]))
        self.kept[id(plist)] = [(plist.pairs[i], obj) for i, obj in kept]
        if not any(any(row) for row in flags):
            return
        if not kept:
            if not plist.bracket and all(q in self.removed for q in plist.subject_owned):
                self.gone.add(id(plist))
                self.delete(plist.start, plist.end, widen=True)
            elif plist.bracket:
                self.delete(plist.pairs[0].start, plist.pairs[-1].end, widen=True)
            else:  # a [ ... ] subject keeps its statement: `[ ... ] .`
                self.delete(plist.open_end, plist.pairs[-1].end)
            return
        last = kept[-1][0]
        for i, pair in enumerate(plist.pairs):
            row = flags[i]
            if all(row):
                if i < last:
                    self.delete(pair.start, pair.end, widen=True)
                continue
            for j, obj in enumerate(pair.objects):
                if not row[j]:
                    continue
                if not all(row[:j]):
                    self.delete(pair.objects[j - 1].end, obj.end)
                else:
                    self.delete(obj.start, pair.objects[j + 1].start)
        if last == len(plist.pairs) - 1:
            return
        # the pairs after the last kept one go; the terminator stays where it is
        last_pair, last_obj = plist.pairs[last], kept[-1][1]
        run_end = plist.pairs[-1].end
        if not any(last_obj.end <= c < run_end for c in self.doc.comments):
            self.delete(last_obj.end, run_end)
            return
        # comments sit among them: keep the comments, and move the `.` up
        self.delete(last_obj.end, last_pair.end)
        for pair in plist.pairs[last + 1 : -1]:
            self.delete(pair.start, pair.end, widen=True)
        self.delete(plist.pairs[-1].start, plist.end if plist.has_dot else plist.pairs[-1].end, widen=True)
        if plist.has_dot:
            self.insert(last_obj.end, " .")

    # additions

    def add(self, quads: tuple[Quad, ...]) -> None:
        doc = self.doc
        known = {t for q in doc.quads for t in (q[0], q[2]) if isinstance(t, BNode)}
        new_nodes = {t for q in quads for t in (q[0], q[2]) if isinstance(t, BNode) and t not in known}
        parents: dict[Node, list[Quad]] = {}
        for quad in quads:
            if not isinstance(quad[1], URIRef):
                raise PatchError(quad[0], quad[1], "the predicate is not an IRI")
            if quad[0] in new_nodes:
                self.children.setdefault(quad[0], []).append(quad)
            if quad[2] in new_nodes:
                parents.setdefault(quad[2], []).append(quad)
        for node in sorted(new_nodes, key=_n3):
            owners = parents.get(node, [])
            if len(owners) != 1:
                s, p, _, _ = self.children[node][0] if not owners else owners[1]
                where = "no added quad has it as its object" if not owners else "two added quads have it as object"
                raise PatchError(s, p, f"new blank node {_n3(node)}: {where}; the writer writes it inline as [ ]")
            if any(q[3] != owners[0][3] for q in self.children.get(node, [])):
                child = next(q for q in self.children[node] if q[3] != owners[0][3])
                raise PatchError(child[0], child[1], "a new blank node's triples must be in its parent's graph")
        top = [q for q in quads if q[0] not in new_nodes]
        groups: dict[tuple[Node, Node], list[Quad]] = {}
        for quad in top:
            groups.setdefault((quad[3], quad[0]), []).append(quad)
        fresh: dict[Node, list[tuple[Node, list[Quad]]]] = {}
        for (graph, subject), group in groups.items():
            if not self._join(graph, subject, group):
                fresh.setdefault(graph, []).append((subject, group))
        self._new_statements(fresh)

    def _spell(self, term: Node, *, verb: bool = False, depth: int = 0) -> str:
        if isinstance(term, URIRef):
            return "a" if verb and term == RDF.type else _spell_iri(term, self.doc)
        if isinstance(term, Literal):
            lexical, dt = str(term), term.datatype
            if term.language:
                return f"{_spell_string(lexical)}@{term.language}"
            if dt == XSD.boolean and lexical in ("true", "false"):
                return lexical
            if dt is None:
                return _spell_string(lexical)
            if dt in _BARE and _BARE[dt].fullmatch(lexical):
                return lexical
            return f"{_spell_string(lexical)}^^{_spell_iri(dt, self.doc)}"
        if isinstance(term, BNode):
            if term in self.children:
                if depth > len(self.children):
                    raise _BadTerm("new blank nodes nest in a cycle")
                inner = " ; ".join(self._pair(q, depth + 1) for q in self.children[term])
                return f"[ {inner} ]" if inner else "[]"
            if term in self.doc.anonymous:
                raise _BadTerm(f"{_n3(term)} is an unlabelled blank node of the text; it cannot be referred to again")
            return f"_:{term}"
        raise _BadTerm(f"the writer cannot write {_n3(term)}")

    def _pair(self, quad: Quad, depth: int = 0) -> str:
        return f"{self._spell(quad[1], verb=True)} {self._spell(quad[2], depth=depth)}"

    def _pairs(self, group: list[Quad]) -> list[str]:
        spelled: list[str] = []
        for quad in group:
            try:
                spelled.append(self._pair(quad))
            except _BadTerm as exc:
                raise PatchError(quad[0], quad[1], str(exc)) from None
        return spelled

    def _join(self, graph: Node, subject: Node, group: list[Quad]) -> bool:
        """Add the pairs to the subject's existing list in the graph; False if it has none."""
        doc = self.doc
        if subject in doc.cells:
            raise PatchError(subject, group[0][1], "it is a collection cell; replace the collection as a whole")
        if isinstance(subject, BNode) and subject in doc.anonymous:
            brackets = [pl for pl in doc.plists if pl.bracket and pl.subject == subject and pl.graph == graph]
            if not brackets:
                raise PatchError(subject, group[0][1], f"the blank node is not written in graph {_n3(graph)}")
            plist = brackets[0]
            pairs = self._pairs(group)
            kept = self.kept.get(id(plist), [])
            if kept:
                self.insert(kept[-1][1].end, "".join(f" ; {p}" for p in pairs))
            else:
                self.insert(plist.open_end, " " + " ; ".join(pairs))
            return True
        statements = [
            pl
            for pl in doc.plists
            if not pl.bracket and pl.subject == subject and pl.graph == graph and self.kept.get(id(pl))
        ]
        if not statements:
            return False
        last_pair, last_obj = self.kept[id(statements[-1])][-1]
        pairs = self._pairs(group)
        line_start = self.text.rfind("\n", 0, last_pair.start) + 1
        indent = self.text[line_start : last_pair.start]
        if not indent.strip(" \t"):
            self.insert(line_start, "".join(f"{indent}{p} ;\n" for p in pairs))
        else:
            self.insert(last_obj.end, "".join(f" ; {p}" for p in pairs))
        return True

    def _statement(self, subject: Node, group: list[Quad], indent: str) -> str:
        try:
            head = self._spell(subject)
        except _BadTerm as exc:
            raise PatchError(subject, group[0][1], str(exc)) from None
        pairs = self._pairs(group)
        if len(pairs) == 1:
            return f"{indent}{head} {pairs[0]} .\n"
        lines = [f"{indent}{head} {pairs[0]} ;\n"]
        lines += [f"{indent}    {p} ;\n" for p in pairs[1:-1]]
        return "".join(lines) + f"{indent}    {pairs[-1]} .\n"

    def _new_statements(self, fresh: dict[Node, list[tuple[Node, list[Quad]]]]) -> None:
        text = self.text
        new_blocks: list[Node] = []
        for graph in sorted(fresh, key=_n3):
            if graph == DATASET_DEFAULT_GRAPH_ID:
                continue
            blocks = [b for b in self.doc.blocks if b.graph == graph]
            if not blocks:
                new_blocks.append(graph)
                continue
            block = blocks[-1]
            indent = "    "
            for st in block.statements:
                line_start = text.rfind("\n", 0, st.start) + 1
                if not text[line_start : st.start].strip(" \t"):
                    indent = text[line_start : st.start]
                    break
            alive = [st for st in block.statements if id(st) not in self.gone]
            if alive and not alive[-1].has_dot:
                self.insert(alive[-1].end, " .")
            body = "".join(self._statement(s, g, indent) for s, g in fresh[graph])
            line_start = text.rfind("\n", 0, block.close_start) + 1
            if text[line_start : block.close_start].strip(" \t"):
                self.insert(block.close_start, "\n" + body)
            else:
                self.insert(line_start, body)
        tail = [""] if text.endswith("\n") or not text else ["\n"]
        for subject, group in fresh.get(DATASET_DEFAULT_GRAPH_ID, []):
            tail.append(self._statement(subject, group, ""))
        for graph in new_blocks:
            subject, group = fresh[graph][0]
            if not isinstance(graph, URIRef):
                raise PatchError(subject, group[0][1], f"the graph name {_n3(graph)} is not an IRI")
            try:
                name = _spell_iri(graph, self.doc)
            except _BadTerm as exc:
                raise PatchError(subject, group[0][1], str(exc)) from None
            body = "".join(self._statement(s, g, "    ") for s, g in fresh[graph])
            tail.append(f"\n{name} {{\n{body}}}\n")
        if len(tail) > 1:
            self.insert(len(text), "".join(tail))

    # the edited text

    def _widen(self, a: int, b: int) -> tuple[int, int]:
        """Take a deletion out to the whole line when nothing else is on it, else tidy its spaces."""
        text = self.text
        line_start = text.rfind("\n", 0, a) + 1
        line_end = text.find("\n", b)
        line_end = len(text) if line_end < 0 else line_end
        if not text[line_start:a].strip(" \t") and not text[b:line_end].strip(" \t\r"):
            return line_start, min(line_end + 1, len(text))
        while b < line_end and text[b] in " \t":
            b += 1
        if not text[b:line_end].strip("\r"):
            while a > line_start and text[a - 1] in " \t":
                a -= 1
        return a, b

    def result(self) -> str:
        merged: list[list[int]] = []  # [a, b, widen]
        for a, b, widen in sorted(self.deletions):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
                merged[-1][2] = merged[-1][2] and widen
            else:
                merged.append([a, b, widen])
        spans: list[tuple[int, int]] = []
        for a, b, widen in merged:
            a, b = self._widen(a, b) if widen else (a, b)
            if spans and a <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], b))
            else:
                spans.append((a, b))
        events: list[tuple[int, int, int, int, str]] = [(a, 1, 0, b, "") for a, b in spans]
        events += [(pos, 0, seq, pos, text) for pos, seq, text in self.insertions]
        for pos, _, _, _, _ in events:
            for a, b in spans:
                if a < pos < b:
                    raise _Misplaced(pos)
        out: list[str] = []
        cursor = 0
        for pos, _, _, end, text in sorted(events):
            out.append(self.text[cursor:pos])
            out.append(text)
            cursor = end
        out.append(self.text[cursor:])
        return "".join(out)


class _Misplaced(Exception):
    def __init__(self, pos: int) -> None:
        super().__init__(pos)
        self.pos = pos


# Checking ---------------------------------------------------------------------


def _graphs(quads: set[Quad]) -> dict[Node, Graph]:
    graphs: dict[Node, Graph] = {}
    for s, p, o, g in quads:
        graphs.setdefault(g, Graph()).add((s, p, o))
    return graphs


def _split(graph: Graph) -> tuple[set[tuple[Node, Node, Node]], Graph]:
    ground: set[tuple[Node, Node, Node]] = set()
    blank = Graph()
    for s, p, o in graph:
        if isinstance(s, BNode) or isinstance(o, BNode):
            blank.add((s, p, o))
        else:
            ground.add((s, p, o))
    return ground, blank


def _same(a: Graph, b: Graph) -> bool:
    """Isomorphic graphs. A blank-node mapping fixes every ground triple, so only the
    triples that touch a blank node need the (costly) canonical comparison."""
    if len(a) != len(b):
        return False
    ground_a, blank_a = _split(a)
    ground_b, blank_b = _split(b)
    return ground_a == ground_b and isomorphic(blank_a, blank_b)


def _verify(doc: _Doc, patch: Patch, edited: str, first: Quad) -> None:
    expected = _graphs((set(doc.quads) - set(patch.removes)) | set(patch.adds))
    actual = Dataset()
    try:
        actual.parse(data=edited, format="trig", publicID=doc.base)
    except Exception as exc:  # rdflib raises several syntax error types
        raise PatchError(first[0], first[1], f"the writer produced text that does not parse: {exc}") from None
    names = set(expected) | {g.identifier for g in actual.graphs()}
    for name in sorted(names, key=_n3):
        got = Graph()
        if isinstance(name, URIRef | BNode):
            for triple in actual.graph(name):
                got.add(triple)
        want = expected.get(name, Graph())
        if not _same(got, want):
            raise PatchError(
                first[0], first[1], f"the edited text does not mean the patched model in graph {_n3(name)}"
            )


# Public API -------------------------------------------------------------------


def text_quads(text: str, *, base: str = DEFAULT_BASE) -> tuple[Quad, ...]:
    """The quads a TriG text states, sorted, with blank nodes under the writer's labels.

    Relative IRIs resolve against ``base`` (pass the file's URI to match ``seams.load``).
    Raises PatchError naming the line when the writer cannot read the text.
    """
    try:
        doc = _read(text, base)
    except _Unreadable as exc:
        raise PatchError("the TriG text", f"line {exc.line}", exc.detail) from None
    return tuple(sorted(set(doc.quads), key=quad_key))


def declared_graphs(text: str, *, base: str = DEFAULT_BASE) -> tuple[Node, ...]:
    """The graphs a TriG text has a ``{ }`` block for, sorted."""
    try:
        doc = _read(text, base)
    except _Unreadable as exc:
        raise PatchError("the TriG text", f"line {exc.line}", exc.detail) from None
    return tuple(sorted({b.graph for b in doc.blocks}, key=_n3))


def apply_text(text: str, patch: Patch, *, base: str = DEFAULT_BASE) -> str:
    """Apply a patch to TriG source text, touching only the text of the triples it changes.

    Relative IRIs resolve against ``base`` (pass the file's URI to match ``seams.load``);
    the writer spells IRIs under the base's folder relatively again, so no host path
    reaches the text. An empty patch returns ``text`` itself. Raises PatchError, naming the quad and the
    reason, for a removed quad the text does not state, an added quad it already
    states, a quad the writer cannot place, or an edit that would not re-parse to the
    old model with the patch applied.
    """
    if patch.is_empty:
        return text
    first = (patch.removes + patch.adds)[0]
    try:
        doc = _read(text, base)
    except _Unreadable as exc:
        raise PatchError(first[0], first[1], f"the writer cannot read the TriG text: {exc}") from None
    present = set(doc.quads)
    for s, p, o, g in patch.removes:
        if (s, p, o, g) not in present:
            raise PatchError(s, p, f"removed quad (object {_n3(o)}, graph {_n3(g)}) is not in the model")
    for s, p, o, g in patch.adds:
        if (s, p, o, g) in present:
            raise PatchError(s, p, f"added quad (object {_n3(o)}, graph {_n3(g)}) is already in the model")
    edits = _Edits(doc, frozenset(patch.removes))
    edits.remove(patch.removes)
    edits.add(patch.adds)
    try:
        edited = edits.result()
    except _Misplaced as exc:
        line = text.count("\n", 0, exc.pos) + 1
        raise PatchError(first[0], first[1], f"an addition falls inside text the patch removes (line {line})") from None
    _verify(doc, patch, edited, first)
    return edited
