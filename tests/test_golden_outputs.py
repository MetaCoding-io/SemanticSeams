"""Doc-lint for the golden generator outputs in docs/generation/golden/ (M006/S06):
every non-blank line of a golden artifact carries exactly one producibility
marker, every `[graph: ...]` claim cites model terms that resolve in
examples/chat-app/chat-app.trig, every `[gap: GAP-NN]` names a gaps.md row,
and each artifact still parses in its own syntax. The gaps.md Status column is
linted too: closed rows must not be cited, open or deferred golden rows must be,
and `runtime (ADR-0007)` rows are exempt from citation.
"""

import ast
import re
import sys
from pathlib import Path

import jinja2
import pytest
import yaml
from rdflib import RDF, Dataset, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "docs" / "generation" / "golden"
GAPS = GOLDEN / "gaps.md"
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
ARTIFACT_NAMES = ("compose.yaml", "chat_page.html", "chat_api.py")
ARTIFACTS = [GOLDEN / name for name in ARTIFACT_NAMES if (GOLDEN / name).exists()]

CHAT = "https://example.org/chat/"
PREFIXES = {
    "seam": "https://w3id.org/seams/seam#",
    "arch": "https://w3id.org/seams/arch#",
    "ifml": "https://w3id.org/seams/ifml#",
    "deploy": "https://w3id.org/seams/deploy#",
    "hydra": "http://www.w3.org/ns/hydra/core#",
    "comm": "https://w3id.org/seams/comm#",
    "proc": "https://w3id.org/seams/proc#",
    "dec": "https://w3id.org/seams/dec#",
    "state": "https://w3id.org/seams/state#",
    "sh": "http://www.w3.org/ns/shacl#",
    "dash": "http://datashapes.org/dash#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
}

MARKER = re.compile(r"\[(graph: [^\]]+|fixed|gap: GAP-\d{2})\]")
# Any bracketed thing that looks like an attempted marker, so a malformed one
# ("[gap: GAP-1]", "[graph:]") is reported instead of silently not counting.
MARKER_LIKE = re.compile(r"\[(?:graph|fixed|gap)\b[^\]]*\]")
TERM = re.compile(r"^(?P<prefix>[a-z]*):(?P<local>[A-Za-z_][\w.#-]*)$")
IRI = re.compile(r"^<(?P<iri>[^>\s]+)>$")
GAP_ROW = re.compile(r"^\|\s*(GAP-\d{2})\s*\|", re.MULTILINE)
COMMENT_END = {".yaml": "#", ".py": "#", ".html": "{#"}
# ID | Artifact | What the graph cannot say | Proposed addition | Layer | Status
GAP_COLUMNS = 6
STATUS_FORMS = ("open", "closed (vocabulary)", "closed (rule)", "deferred: <reason>")
STATUS = re.compile(r"^(open|closed \((vocabulary|rule)\)|deferred:.*)$")


@pytest.fixture(scope="module")
def model_terms():
    ds = Dataset()
    ds.parse(TRIG, format="trig")
    nodes, predicates = set(), set()
    for s, p, o, _ in ds.quads((None, None, None, None)):
        predicates.add(p)
        for node in (s, o):
            if isinstance(node, URIRef):
                nodes.add(node)
    types = {o for o in ds.objects(None, RDF.type)}
    return nodes, predicates, types


def gap_ids():
    return GAP_ROW.findall(GAPS.read_text())


def gap_rows():
    """{id: (artifact, status)} for every GAP-NN row; Status is the last column."""
    rows = {}
    for line in GAPS.read_text().splitlines():
        if not GAP_ROW.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != GAP_COLUMNS:
            continue
        rows[cells[0]] = (cells[1], cells[-1])
    return rows


def numbered_lines(path):
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if line.strip():
            yield number, line


def markers(path):
    for number, line in numbered_lines(path):
        found = MARKER.findall(line)
        if len(found) == 1:
            yield number, found[0]


def resolve(token, model_terms):
    """Return the IRI a cited token names, or None when the token is prose."""
    nodes, predicates, types = model_terms
    if m := IRI.match(token):
        return URIRef(m["iri"]), URIRef(m["iri"]) in nodes
    m = TERM.match(token)
    if not m:
        return None
    if m["prefix"] == "":
        iri = URIRef(CHAT + m["local"])
        return iri, iri in nodes
    namespace = PREFIXES.get(m["prefix"])
    if namespace is None:
        return URIRef(token), False
    iri = URIRef(namespace + m["local"])
    return iri, iri in predicates or iri in types or iri in nodes


def test_golden_artifacts_present():
    assert ARTIFACTS, f"no golden artifacts under {GOLDEN.relative_to(ROOT)}"


def test_all_three_golden_artifacts_exist():
    missing = [name for name in ARTIFACT_NAMES if not (GOLDEN / name).exists()]
    assert not missing, f"missing golden artifacts under {GOLDEN.relative_to(ROOT)}: {missing}"


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_every_line_has_exactly_one_trailing_marker(path):
    problems = []
    opener = COMMENT_END[path.suffix]
    closer = "#}" if path.suffix == ".html" else ""
    for number, line in numbered_lines(path):
        found = MARKER.findall(line)
        attempted = MARKER_LIKE.findall(line)
        where = f"{path.name}:{number}"
        if len(found) != 1 or len(attempted) != 1:
            problems.append(f"{where}: expected exactly one marker, found {attempted or 'none'}")
            continue
        tail = line.rstrip()
        if closer:
            ok = tail.endswith(closer) and opener in tail and tail.rindex(opener) < tail.rindex("[")
        else:
            ok = tail.endswith("]") and opener in tail[: tail.rindex("[")]
        if not ok:
            problems.append(f"{where}: marker is not in a trailing {opener} comment")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_graph_markers_cite_resolvable_model_terms(path, model_terms):
    problems = []
    for number, marker in markers(path):
        if not marker.startswith("graph: "):
            continue
        where = f"{path.name}:{number}"
        cited = 0
        for token in marker[len("graph: "):].split():
            result = resolve(token, model_terms)
            if result is None:
                continue
            cited += 1
            iri, ok = result
            if not ok:
                problems.append(f"{where}: unresolved model term {token!r} ({iri})")
        if not cited:
            problems.append(f"{where}: graph marker cites no model term: [{marker}]")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_gap_markers_name_existing_gap_rows(path):
    known = set(gap_ids())
    problems = [
        f"{path.name}:{number}: {marker[len('gap: '):]} has no row in gaps.md"
        for number, marker in markers(path)
        if marker.startswith("gap: ") and marker[len("gap: "):] not in known
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_artifact_parses(path):
    text = path.read_text()
    if path.suffix == ".yaml":
        assert isinstance(yaml.safe_load(text), dict), f"{path.name}: not a YAML mapping"
    elif path.suffix == ".py":
        ast.parse(text, filename=path.name)
    elif path.suffix == ".html":
        jinja2.Environment().parse(text)
    else:
        pytest.fail(f"{path.name}: no syntax check for {path.suffix}")


def test_gap_ids_unique_and_sequential():
    ids = gap_ids()
    assert ids, "gaps.md has no GAP-NN rows"
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"gaps.md: duplicate gap IDs {duplicates}"
    expected = [f"GAP-{n:02d}" for n in range(1, len(ids) + 1)]
    for position, (got, want) in enumerate(zip(ids, expected), start=1):
        assert got == want, f"gaps.md: row {position} is {got}, expected {want}"


def test_resolver_rejects_invented_terms(model_terms):
    assert resolve(":chat_api", model_terms)[1]
    assert resolve("deploy:replicas", model_terms)[1]
    assert resolve("deploy:Artifact", model_terms)[1]
    assert resolve(":chat_bpmn#invoke_llm", model_terms)[1]
    assert not resolve(":no_such_container", model_terms)[1]
    assert resolve("deploy:port", model_terms)[1]
    assert not resolve("deploy:nodeSelector", model_terms)[1]
    assert not resolve("nope:thing", model_terms)[1]
    assert resolve("->", model_terms) is None
    assert resolve("image", model_terms) is None


def _cited_gaps():
    return {
        marker[len("gap: "):]
        for path in ARTIFACTS
        for _, marker in markers(path)
        if marker.startswith("gap: ")
    }


def test_gap_statuses_are_well_formed():
    problems = []
    for gap, (_, status) in gap_rows().items():
        if not STATUS.match(status):
            problems.append(f"{gap}: status {status!r} is not one of {STATUS_FORMS}")
        elif status.startswith("deferred") and not status[len("deferred:"):].strip():
            problems.append(f"{gap}: deferred status has no reason")
    assert not problems, "gaps.md:\n" + "\n".join(problems)


def test_every_gap_row_has_a_status():
    rows = gap_rows()
    assert list(rows) == gap_ids(), "gaps.md: some GAP rows could not be parsed into ID/Artifact/Status"


def test_closed_gap_rows_are_not_cited():
    cited = _cited_gaps()
    stale = [gap for gap, (_, status) in gap_rows().items() if status.startswith("closed") and gap in cited]
    assert not stale, f"gaps.md: closed rows still cited by a golden [gap: ...] marker: {stale}"


def test_open_gap_rows_for_golden_files_are_cited():
    cited = _cited_gaps()
    orphans = [
        gap
        for gap, (artifact, status) in gap_rows().items()
        if not artifact.startswith("runtime")
        and not status.startswith("closed")
        and gap not in cited
    ]
    assert not orphans, f"gaps.md: open/deferred rows not referenced by any golden artifact line: {orphans}"


def test_gap_rows_name_a_golden_file_or_runtime():
    problems = [
        f"{gap}: Artifact {artifact!r} is neither a golden file nor runtime"
        for gap, (artifact, _) in gap_rows().items()
        if artifact not in ARTIFACT_NAMES and not artifact.startswith("runtime")
    ]
    assert not problems, "gaps.md:\n" + "\n".join(problems)


def test_status_parser_rejects_malformed_statuses():
    assert STATUS.match("open")
    assert STATUS.match("closed (vocabulary)")
    assert STATUS.match("closed (rule)")
    assert STATUS.match("deferred: needs an auth ADR")
    assert not STATUS.match("closed")
    assert not STATUS.match("closed (vocab)")
    assert not STATUS.match("done")
    assert not STATUS.match("")
    # "deferred:" with no reason matches the form; the reason check catches it.
    assert not "deferred:   "[len("deferred:"):].strip()


def test_gap_table_covers_backlog_g2_list():
    # docs/backlog.md G2 names the expected vocabulary additions; each must
    # surface in the gap table.
    text = GAPS.read_text().lower()
    assert "path" in text, "gaps.md: no gap about operation paths"
    assert "event" in text, "gaps.md: no gap about event-to-operation binding"
    assert "field" in text, "gaps.md: no gap about form fields"
    assert "sse" in text, "gaps.md: no gap about SSE transport"
    assert "channel" in text, "gaps.md: no gap about channel transport"
    assert "artifact" in text, "gaps.md: no gap about container artifacts"
    assert "image" in text, "gaps.md: no gap about container images"
    assert "port" in text, "gaps.md: no gap about ports"


def _functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _is_post_route(func):
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "post"
        for d in func.decorator_list
    )


def test_chat_api_handlers_hold_no_domain_if():
    # ADR-0007 rule 1: a generated handler with an `if` about the domain is a
    # generator bug; branching belongs to the runtime-interpreted payloads.
    path = GOLDEN / "chat_api.py"
    tree = ast.parse(path.read_text(), filename=path.name)
    functions = _functions(tree)
    assert functions, f"{path.name}: no handler functions"
    problems = [
        f"{path.name}:{node.lineno}: {type(node).__name__} in handler {func.name}()"
        for func in functions
        for node in ast.walk(func)
        if isinstance(node, (ast.If, ast.IfExp, ast.Match))
    ]
    assert not problems, "\n".join(problems)


def test_chat_api_send_handler_starts_the_process():
    path = GOLDEN / "chat_api.py"
    tree = ast.parse(path.read_text(), filename=path.name)
    posts = [f for f in _functions(tree) if _is_post_route(f)]
    assert len(posts) == 1, f"{path.name}: expected one POST route (:send_message_op), found {len(posts)}"
    handler = posts[0]
    starts = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "start_process"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runtime"
    ]
    assert starts, f"{path.name}:{handler.lineno}: {handler.name}() does not call runtime.start_process"
    first = starts[0].args[0] if starts[0].args else None
    assert isinstance(first, ast.Constant) and first.value == ":send_message_process", (
        f"{path.name}:{starts[0].lineno}: runtime.start_process does not start :send_message_process"
    )
