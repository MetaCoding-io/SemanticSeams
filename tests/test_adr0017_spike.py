"""ADR-0017 spike: a patch-based text writer keeps hand-written TriG comments and bytes.

The patcher below is deliberately minimal and lives only in this test; it is evidence for
the ADR, not the write path. A patch is the quads it adds and removes. Applying it edits
the source TriG text at the triple level:

- an added quad becomes one new statement line just before its graph's closing ``}``;
- a removed quad must sit alone on a ``predicate object ;`` line inside its subject's
  statement, and that one line is dropped.

Everything else in the file, comments and layout included, is left byte for byte. The
last tests show why re-serialising with rdflib is not an option: it drops every comment.
"""

import difflib
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, NamespaceManager
from rdflib.term import Node

ROOT = Path(__file__).resolve().parents[1]
CHAT_APP = ROOT / "examples" / "chat-app" / "chat-app.trig"

CHAT = Namespace("https://example.org/chat/")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
ARCH = Namespace("https://w3id.org/seams/arch#")
ARCHITECTURE = URIRef("urn:seams:graph:model:chat_architecture")

Quad = tuple[Node, Node, Node, URIRef]

_BARE_LITERAL_TYPES = tuple(
    URIRef(f"http://www.w3.org/2001/XMLSchema#{name}") for name in ("boolean", "decimal", "double", "integer")
)


def _example_trig_files() -> list[Path]:
    paths = (ROOT / "examples").rglob("*.trig")
    return sorted(p for p in paths if "generated" not in p.relative_to(ROOT).parts)


class PatchError(Exception):
    """A patch the text writer cannot apply; names the quad and the reason."""

    def __init__(self, quad: Quad, detail: str) -> None:
        super().__init__(f"{' '.join(t.n3() for t in quad)}: {detail}")
        self.quad = quad


def _parse(text: str) -> Dataset:
    ds = Dataset()
    ds.parse(data=text, format="trig")
    return ds


def _spell(term: Node, nm: NamespaceManager) -> str:
    """How an author writes a term: prefixed names, bare numbers and booleans."""
    if isinstance(term, Literal) and term.datatype in _BARE_LITERAL_TYPES:
        return str(term)
    return term.n3(nm)


def _spellings(term: Node, nm: NamespaceManager) -> set[str]:
    """The ways a term can be written in the source, given its prefixes."""
    return {term.n3(), term.n3(nm), _spell(term, nm)}


def _is_code(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _graph_block(lines: Sequence[str], graph: URIRef, quad: Quad) -> tuple[int, int]:
    """Indices of a graph's opening ``<g> {`` line and its closing ``}`` line."""
    opening = f"{graph.n3()} {{"
    starts = [i for i, line in enumerate(lines) if line.strip() == opening]
    if len(starts) != 1:
        raise PatchError(quad, f"expected one block for graph {graph}, found {len(starts)}")
    start = starts[0]
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "}":
            return start, i
    raise PatchError(quad, f"graph {graph} has no closing brace")


def _statement_subject(lines: Sequence[str], start: int, index: int) -> str:
    """The first token of the statement that line ``index`` belongs to."""
    for i in range(index - 1, start, -1):
        if _is_code(lines[i]) and lines[i].rstrip().endswith("."):
            first = i + 1
            break
    else:
        first = start + 1
    while not _is_code(lines[first]):
        first += 1
    return lines[first].split()[0]


def _remove(lines: list[str], quad: Quad, nm: NamespaceManager) -> None:
    s, p, o, g = quad
    start, end = _graph_block(lines, g, quad)
    wanted = {f"{ps} {os} ;" for ps in _spellings(p, nm) for os in _spellings(o, nm)}
    subjects = _spellings(s, nm)
    hits = [
        i
        for i in range(start + 1, end)
        if lines[i].strip() in wanted and _statement_subject(lines, start, i) in subjects
    ]
    if len(hits) != 1:
        raise PatchError(quad, f"expected one 'predicate object ;' line for it, found {len(hits)}")
    del lines[hits[0]]


def _add(lines: list[str], quad: Quad, nm: NamespaceManager) -> None:
    s, p, o, g = quad
    _, end = _graph_block(lines, g, quad)
    lines.insert(end, f"    {_spell(s, nm)} {_spell(p, nm)} {_spell(o, nm)} .\n")


def apply_patch(text: str, adds: Iterable[Quad] = (), removes: Iterable[Quad] = ()) -> str:
    """Apply a quad patch to TriG source text, touching only the lines it must."""
    adds, removes = sorted(adds), sorted(removes)
    if not adds and not removes:
        return text
    ds = _parse(text)
    nm = ds.namespace_manager
    lines = text.splitlines(keepends=True)
    for quad in removes:
        if quad not in ds:
            raise PatchError(quad, "removed quad is not in the model")
        _remove(lines, quad, nm)
    for quad in adds:
        if quad in ds:
            raise PatchError(quad, "added quad is already in the model")
        _add(lines, quad, nm)
    return "".join(lines)


def _changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), n=0)
    return [line for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def _comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def _assert_same_graphs(actual: Dataset, expected: Dataset) -> None:
    names = sorted({g.identifier for g in actual.graphs()} | {g.identifier for g in expected.graphs()})
    for name in names:
        a, e = actual.graph(name), expected.graph(name)
        assert isomorphic(Graph() + a, Graph() + e), f"graph {name} differs"


# Empty patch: identity on every example ---------------------------------------


def test_spike_covers_the_examples():
    names = [p.relative_to(ROOT).as_posix() for p in _example_trig_files()]
    assert "examples/chat-app/chat-app.trig" in names
    assert "examples/expenses/chapter-08/expenses.trig" in names
    assert not [n for n in names if "/generated/" in n]


@pytest.mark.parametrize("path", _example_trig_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_empty_patch_returns_identical_bytes(path: Path):
    original = path.read_bytes()
    assert apply_patch(original.decode("utf-8")).encode("utf-8") == original


# One-triple edits: one-line diffs, comments kept, graph as expected -----------

REPLICAS = (CHAT.chat_api, DEPLOY.replicas, Literal(3), ARCHITECTURE)
NEW_REPLICAS = (CHAT.message_db, DEPLOY.replicas, Literal(1), ARCHITECTURE)


@pytest.fixture
def chat_text() -> str:
    return CHAT_APP.read_text(encoding="utf-8")


def test_removing_one_triple_changes_exactly_one_line(chat_text: str):
    after = apply_patch(chat_text, removes=[REPLICAS])
    assert _changed_lines(chat_text, after) == ["-        deploy:replicas 3 ;\n"]


def test_adding_one_triple_changes_exactly_one_line(chat_text: str):
    after = apply_patch(chat_text, adds=[NEW_REPLICAS])
    assert _changed_lines(chat_text, after) == ["+    :message_db deploy:replicas 1 .\n"]


@pytest.mark.parametrize("patch", ["add", "remove"])
def test_edit_reparses_to_the_expected_graph(chat_text: str, patch: str):
    expected = _parse(chat_text)
    if patch == "add":
        after = apply_patch(chat_text, adds=[NEW_REPLICAS])
        expected.graph(ARCHITECTURE).add(NEW_REPLICAS[:3])
    else:
        after = apply_patch(chat_text, removes=[REPLICAS])
        expected.graph(ARCHITECTURE).remove(REPLICAS[:3])
    _assert_same_graphs(_parse(after), expected)


def test_edit_keeps_every_comment_in_order(chat_text: str):
    after = apply_patch(chat_text, adds=[NEW_REPLICAS], removes=[REPLICAS])
    assert _comment_lines(after) == _comment_lines(chat_text)
    assert len(_changed_lines(chat_text, after)) == 2


# Error paths: a patch the writer cannot place is refused, naming the quad -----


def test_removing_a_quad_not_in_the_model_is_refused(chat_text: str):
    with pytest.raises(PatchError, match="not in the model"):
        apply_patch(chat_text, removes=[(CHAT.chat_api, DEPLOY.replicas, Literal(99), ARCHITECTURE)])


def test_adding_a_quad_already_in_the_model_is_refused(chat_text: str):
    with pytest.raises(PatchError, match="already in the model"):
        apply_patch(chat_text, adds=[REPLICAS])


def test_adding_to_a_graph_with_no_block_is_refused(chat_text: str):
    quad = (CHAT.chat_api, DEPLOY.replicas, Literal(1), URIRef("urn:seams:graph:model:absent"))
    with pytest.raises(PatchError, match="expected one block"):
        apply_patch(chat_text, adds=[quad])


def test_removing_a_triple_not_on_its_own_line_is_refused(chat_text: str):
    # `:chat_api a arch:Container ;` shares the subject's opening line; the spike
    # writer only removes lines that hold one `predicate object ;` pair.
    quad = (CHAT.chat_api, RDF.type, ARCH.Container, ARCHITECTURE)
    with pytest.raises(PatchError, match="expected one 'predicate object ;' line"):
        apply_patch(chat_text, removes=[quad])


# Why not re-serialise: rdflib keeps the graph but drops every comment ---------


@pytest.mark.parametrize("path", [CHAT_APP, ROOT / "examples/expenses/chapter-08/expenses.trig"], ids=lambda p: p.name)
def test_rdflib_reserialisation_drops_comments(path: Path):
    source = path.read_text(encoding="utf-8")
    ds = _parse(source)
    reserialised = ds.serialize(format="trig")
    assert _comment_lines(source), "the example has hand-written comments to lose"
    assert _comment_lines(reserialised) == []
    assert reserialised != source
    _assert_same_graphs(_parse(reserialised), ds)
