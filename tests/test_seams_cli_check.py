"""`seams check` fails on SHACL violations, gate rows and drifted outputs, and writes nothing (M012/S03, D044).

Review findings (seams.review_findings, M017/S04) are printed but never fail
the check. ``_check`` asserts that the printed ``review`` lines are exactly the
model's review findings and returns the other lines, so each test pins its
problems while the expected review warnings ride along.

Each example is copied into tmp_path at its repository-relative path, so the
chat app's compose target (``../..``) lands at tmp_path/compose.<environment>.yaml, as in
tests/test_seams_generate_examples.py. Checking a copy keeps the committed
outputs untouched while a test breaks them.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import seams
from seams_cli import Finding, load_project, run_check
from seams_cli.__main__ import main
from seams_cli.check import ADVISORY_KINDS, check_review

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = sorted(p.parent.relative_to(ROOT) for p in (ROOT / "examples").rglob("seams.toml"))
CHAPTER = Path("examples/expenses/chapter-05")
LOCK = "seams.lock"
API = "generated/expense_api.py"

EVERY_EVENT = """\
PREFIX ifml: <https://w3id.org/seams/ifml#>
SELECT ?event WHERE { ?event a ifml:Event }
"""


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _copy(rel: Path, tmp_path: Path) -> Path:
    dest = tmp_path / rel
    shutil.copytree(ROOT / rel, dest, ignore=shutil.ignore_patterns("__pycache__"))
    for target in load_project(ROOT / rel).generators:
        out = target.out.resolve()
        if target.name != "compose" or out.is_relative_to(ROOT / rel):
            continue
        # Each compose file with its trace sidecar (ADR-0019).
        for compose in [*out.glob("compose.*.yaml"), *out.glob("compose.*.yaml.trace.json")]:
            copied = tmp_path / compose.relative_to(ROOT)
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compose, copied)
    return dest


@pytest.fixture
def app(tmp_path: Path) -> Path:
    return _copy(CHAPTER, tmp_path)


def _review_lines(app: Path) -> list[str]:
    model = seams.load(load_project(app).model)
    return [f"review {f.subject} {f.fact} {f.message}" for f in seams.review_findings(model)]


def _warnings(app: Path) -> str:
    """The stderr of a check whose only findings are review findings."""
    count = len(_review_lines(app))
    return f"seams check: {count} review warning(s)\n" if count else ""


def _check(app: Path, capsys) -> tuple[int, list[str], str]:
    """Exit code, the non-review lines and stderr; the review lines must be the model's review findings."""
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    lines = out.splitlines()
    review = [line for line in lines if line.startswith("review ")]
    if code != 2:
        assert review == _review_lines(app)
    return code, [line for line in lines if not line.startswith("review ")], err


def _kinds(lines: list[str]) -> set[str]:
    return {line.split(" ", 1)[0] for line in lines}


def _set_gates(app: Path, value: str) -> None:
    toml = app / "seams.toml"
    toml.write_text(f"gates = {value}\n" + toml.read_text(encoding="utf-8"), encoding="utf-8")


def _hashes(root: Path) -> dict[Path, str]:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("rel", PROJECTS, ids=str)
def test_every_example_passes_in_place(rel, capsys):
    code, lines, err = _check(ROOT / rel, capsys)
    assert (code, lines, err) == (0, [], _warnings(ROOT / rel))


EX = "https://example.org/expenses/"
UNDECLARED = "no rdf:type rdf:Property, owl:ObjectProperty, owl:DatatypeProperty or owl:AnnotationProperty declares it"
NO_TARGET = "has no sh:targetClass, so it says what a form holds but not what class of thing it describes"
CHAPTER_5_REVIEW = [
    f"review {EX}ApprovalShape http://www.w3.org/ns/shacl#targetClass ApprovalShape {NO_TARGET}",
    f"review {EX}ExpenseShape http://www.w3.org/ns/shacl#targetClass ExpenseShape {NO_TARGET}",
    *(
        f"review {EX}{path} http://www.w3.org/ns/shacl#path {path} is a sh:path (used by {shape}), but {UNDECLARED}"
        for path, shape in [
            ("amount", "ExpenseShape"),
            ("comment", "ApprovalShape"),
            ("date", "ExpenseShape"),
            ("decision", "ApprovalShape"),
            ("description", "ExpenseShape"),
            ("id", "ExpenseShape"),
        ]
    ),
]


def test_a_clean_copy_passes(app, capsys):
    assert _check(app, capsys) == (0, [], "seams check: 8 review warning(s)\n")


def test_review_findings_are_printed_but_do_not_fail(app, capsys):
    """Chapter 5's shapes have no target class and its paths are undeclared: eight review lines, exit 0."""
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    assert (code, out.splitlines(), err) == (0, CHAPTER_5_REVIEW, "seams check: 8 review warning(s)\n")


def test_review_findings_are_not_counted_as_problems(app, capsys):
    """A review finding plus a real problem exits 1, and the problem count leaves the review out."""
    (app / API).unlink()
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    assert code == 1
    assert out.splitlines() == sorted([f"missing {app / API}", *CHAPTER_5_REVIEW])
    assert err == "seams check: 1 problem(s)\n"


def test_a_shacl_violation_with_review_findings_exits_1(tmp_path, capsys):
    """Chapter 2 without its notation: one shacl finding beside its review findings."""
    app = _copy(Path("examples/expenses/chapter-02"), tmp_path)
    model = app / "expenses.trig"
    text = model.read_text(encoding="utf-8")
    model.write_text(text.replace(":expense_data seam:notation seam:ShapeGraph .", ""), encoding="utf-8")
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    lines = out.splitlines()
    problems = [line for line in lines if not line.startswith("review ")]
    assert code == 1
    assert len([line for line in lines if line.startswith("review ")]) == 5
    assert [line.split(" ", 1)[0] for line in problems].count("shacl") == 1
    assert err == f"seams check: {len(problems)} problem(s)\n"


def test_run_check_reports_review_findings(app):
    project = load_project(app)
    assert run_check(project, project.model) == [Finding("review", line.split(" ", 1)[1]) for line in CHAPTER_5_REVIEW]
    assert check_review(project.model) == run_check(project, project.model)


def test_a_changed_model_makes_outputs_stale(app, capsys):
    model = app / "expenses.trig"
    with model.open("a", encoding="utf-8") as fh:
        fh.write('\n<urn:x:note> <http://www.w3.org/2000/01/rdf-schema#comment> "drift" .\n')
    code, lines, err = _check(app, capsys)
    assert code == 1
    assert f"stale {app / API}" in lines
    assert _kinds(lines) == {"stale", "lock-out-of-date"}
    assert err == f"seams check: {len(lines)} problem(s)\n"


def test_a_hand_edit_is_reported_as_hand_edited(app, capsys):
    with (app / API).open("a", encoding="utf-8") as fh:
        fh.write("# edited by hand\n")
    code, lines, _err = _check(app, capsys)
    assert (code, lines) == (1, [f"hand-edited {app / API}"])


def test_a_deleted_output_is_missing(app, capsys):
    (app / API).unlink()
    code, lines, _err = _check(app, capsys)
    assert (code, lines) == (1, [f"missing {app / API}"])


def test_a_locked_file_no_longer_produced_is_an_orphan(app, capsys):
    extra = app / "generated" / "old.py"
    extra.write_text("old\n", encoding="utf-8")
    data = json.loads((app / LOCK).read_text(encoding="utf-8"))
    entry = dict(data["outputs"][0], path="generated/old.py", sha256=hashlib.sha256(b"old\n").hexdigest())
    data["outputs"].append(entry)
    (app / LOCK).write_text(json.dumps(data), encoding="utf-8")
    code, lines, _err = _check(app, capsys)
    assert code == 1
    assert lines == [f"lock-out-of-date {app / LOCK}", f"orphan {extra}"]


def test_a_removed_orphan_is_not_reported(app, capsys):
    data = json.loads((app / LOCK).read_text(encoding="utf-8"))
    data["outputs"].append(dict(data["outputs"][0], path="generated/gone.py"))
    (app / LOCK).write_text(json.dumps(data), encoding="utf-8")
    _code, lines, _err = _check(app, capsys)
    assert lines == [f"lock-out-of-date {app / LOCK}"]


def test_a_missing_lock_is_out_of_date(app, capsys):
    (app / LOCK).unlink()
    assert _check(app, capsys)[:2] == (1, [f"lock-out-of-date {app / LOCK}"])


def test_a_tampered_lock_hash_is_out_of_date(app, capsys):
    data = json.loads((app / LOCK).read_text(encoding="utf-8"))
    data["outputs"][0]["sha256"] = "0" * 64
    (app / LOCK).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert _check(app, capsys)[:2] == (1, [f"lock-out-of-date {app / LOCK}"])


def test_a_shacl_violation_is_reported(tmp_path, capsys):
    """Chapter 2's deliberate mistake (tests/test_expense_checkpoints.py): a model without its notation."""
    app = _copy(Path("examples/expenses/chapter-02"), tmp_path)
    model = app / "expenses.trig"
    text = model.read_text(encoding="utf-8")
    assert ":expense_data seam:notation seam:ShapeGraph ." in text
    model.write_text(text.replace(":expense_data seam:notation seam:ShapeGraph .", ""), encoding="utf-8")
    code, lines, _err = _check(app, capsys)
    assert code == 1
    shacl = [line for line in lines if line.startswith("shacl ")]
    assert len(shacl) == 1
    assert "https://example.org/expenses/expense_data https://w3id.org/seams/seam#notation" in shacl[0]


def test_gate_rows_are_findings(app, capsys):
    (app / "gates").mkdir()
    (app / "gates" / "events.rq").write_text(EVERY_EVENT, encoding="utf-8")
    _set_gates(app, '["gates/events.rq"]')
    code, lines, _err = _check(app, capsys)
    assert code == 1
    assert "gate gates/events.rq https://example.org/expenses/submit_expense" in lines
    assert _kinds(lines) == {"gate"}


def test_review_is_the_only_advisory_kind():
    assert ADVISORY_KINDS == frozenset({"review"})


def test_run_check_returns_sorted_findings(app):
    (app / API).unlink()
    (app / LOCK).unlink()
    project = load_project(app)
    assert run_check(project, project.model) == [
        Finding("lock-out-of-date", str(app / LOCK)),
        Finding("missing", str(app / API)),
        *(Finding("review", line.split(" ", 1)[1]) for line in CHAPTER_5_REVIEW),
    ]


@pytest.mark.parametrize(
    ("gates", "gate_text", "message"),
    [
        ('["gates/none.rq"]', None, "does not exist"),
        ('["gates/g.rq"]', "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "must be a SELECT query"),
        ('["gates/g.rq"]', "SELECT WHERE {", "invalid SPARQL"),
        ('"gates/g.rq"', None, "`gates` must be an array of strings"),
        ("[1]", None, "`gates[0]` must be a string"),
    ],
    ids=["missing", "construct", "unparsable", "not-an-array", "not-a-string"],
)
def test_a_bad_gate_exits_2(app, capsys, gates, gate_text, message):
    if gate_text is not None:
        (app / "gates").mkdir()
        (app / "gates" / "g.rq").write_text(gate_text, encoding="utf-8")
    _set_gates(app, gates)
    code, lines, err = _check(app, capsys)
    assert (code, lines) == (2, [])
    assert err.startswith("seams check: ") and message in err


def test_a_malformed_lock_exits_2(app, capsys):
    (app / LOCK).write_text("{not json", encoding="utf-8")
    code, lines, err = _check(app, capsys)
    assert (code, lines) == (2, [])
    assert "invalid JSON" in err


def test_an_unparsable_model_exits_2(app, capsys):
    (app / "expenses.trig").write_text("this is not trig {", encoding="utf-8")
    code, _lines, err = _check(app, capsys)
    assert code == 2
    assert "cannot load the model" in err


def test_check_writes_nothing(app, tmp_path, capsys):
    (app / API).unlink()
    with (app / "expenses.trig").open("a", encoding="utf-8") as fh:
        fh.write('\n<urn:x:note> <http://www.w3.org/2000/01/rdf-schema#comment> "drift" .\n')
    (app / LOCK).unlink()
    before = _hashes(tmp_path)
    assert _check(app, capsys)[0] == 1
    assert _hashes(tmp_path) == before


def _set_coverage(app: Path, value: str) -> None:
    toml = app / "seams.toml"
    toml.write_text(f"coverage = {value}\n" + toml.read_text(encoding="utf-8"), encoding="utf-8")


def _chapter_9(tmp_path: Path) -> Path:
    """A copy of chapter 9 with the docs/queries its gate climbs out of the project to reach."""
    shutil.copytree(ROOT / "docs" / "queries", tmp_path / "docs" / "queries")
    return _copy(Path("examples/expenses/chapter-09"), tmp_path)


def test_coverage_paths_reports_each_unexercised_path(tmp_path, capsys):
    """Chapter 9 runs three of its approval paths; the other six (D054, tests/test_seams_coverage.py) are findings."""
    app = _chapter_9(tmp_path)
    _set_coverage(app, '["paths"]')
    code, lines, err = _check(app, capsys)
    expected = sorted(
        "coverage " + " ".join((str(p.process.iri), *(str(i) for i in p.iris)))
        for p in seams.unexercised_paths(seams.load(app / "expenses.trig"))
    )
    assert code == 1
    assert len(expected) == 6
    assert lines == expected
    assert err.strip() == "seams check: 6 problem(s)"
    assert "https://example.org/expenses/approval_bpmn#rejected_end" in lines[0]


def test_a_type_ref_disagreeing_with_the_datatype_is_a_decision_finding(tmp_path, capsys):
    """Backlog K2 (seams.decision_findings, tests/test_decision_static_checks.py) through ``seams check``."""
    app = _chapter_9(tmp_path)
    dmn = app / "approval.dmn"
    old = '<inputExpression id="input_amount_expr" typeRef="number">'
    text = dmn.read_text(encoding="utf-8")
    assert old in text
    dmn.write_text(text.replace(old, old.replace("number", "string")), encoding="utf-8")
    code, lines, err = _check(app, capsys)
    assert code == 1
    assert [line for line in lines if line.startswith("decision ")] == [
        "decision https://example.org/expenses/approval_routing https://example.org/expenses/amount "
        "input 'amount' of 'approval_routing' in approval.dmn is typeRef string, "
        "but ExpenseShape gives 'amount' sh:datatype xsd:decimal"
    ]
    assert err.strip().startswith("seams check: ")


def test_a_condition_reading_an_unset_variable_is_a_decision_finding(tmp_path, capsys):
    app = _chapter_9(tmp_path)
    bpmn = app / "approval.bpmn"
    text = bpmn.read_text(encoding="utf-8")
    assert "route ==" in text
    bpmn.write_text(text.replace("route ==", "routing ==", 1), encoding="utf-8")
    code, lines, _err = _check(app, capsys)
    decision = [line for line in lines if line.startswith("decision ")]
    assert code == 1
    assert len(decision) == 1
    assert decision[0].startswith("decision https://example.org/expenses/approval_bpmn#")
    assert " routing " in decision[0]


def test_coverage_unset_adds_no_findings(tmp_path, capsys):
    app = _chapter_9(tmp_path)
    assert load_project(app).coverage == ()
    assert _check(app, capsys) == (0, [], _warnings(app))


def test_coverage_paths_passes_a_model_without_processes(tmp_path, capsys):
    app = _copy(Path("examples/expenses/chapter-01"), tmp_path)
    _set_coverage(app, '["paths", "paths"]')
    assert load_project(app).coverage == ("paths",)
    assert _check(app, capsys) == (0, [], "")
    assert _review_lines(app) == []


@pytest.mark.parametrize(
    ("coverage", "message"),
    [
        ('"paths"', "`coverage` must be an array of strings"),
        ('["transitions"]', "`coverage[0]` is 'transitions'; known coverage checks: paths"),
        ("[1]", "`coverage[0]` is 1"),
    ],
    ids=["not-an-array", "unknown", "not-a-string"],
)
def test_a_bad_coverage_exits_2(app, capsys, coverage, message):
    _set_coverage(app, coverage)
    code, lines, err = _check(app, capsys)
    assert (code, lines) == (2, [])
    assert err.startswith("seams check: ") and message in err


def _replace_gates(app: Path, up: str) -> None:
    """Swap the project's gates for the two coverage queries, ``up`` being the climb to the repository root."""
    toml = app / "seams.toml"
    kept = [line for line in toml.read_text(encoding="utf-8").splitlines() if not line.startswith("gates =")]
    gates = f'gates = ["{up}docs/queries/coverage/unfired-transitions.rq", "{up}docs/queries/coverage/policies-without-deny.rq"]'
    toml.write_text("\n".join([gates, *kept]) + "\n", encoding="utf-8")


def test_the_coverage_queries_are_gates(tmp_path, capsys):
    """Chapter 9 fires every transition and denies every permission to some party, so both gates pass."""
    app = _chapter_9(tmp_path)
    _replace_gates(app, "../../../")
    assert _check(app, capsys) == (0, [], _warnings(app))


def test_the_coverage_gates_report_the_chat_app_gaps(tmp_path, capsys):
    shutil.copytree(ROOT / "docs" / "queries", tmp_path / "docs" / "queries")
    app = _copy(Path("examples/chat-app"), tmp_path)
    _replace_gates(app, "../../")
    code, lines, _err = _check(app, capsys)
    chat = "https://example.org/chat/"
    assert code == 1
    assert lines == [
        f"gate ../../docs/queries/coverage/policies-without-deny.rq {chat}user_send_policy "
        f"{chat}send_message_op {chat}authenticated_user",
        f"gate ../../docs/queries/coverage/unfired-transitions.rq {chat}message_lifecycle {chat}t_fail_send",
        f"gate ../../docs/queries/coverage/unfired-transitions.rq {chat}message_lifecycle {chat}t_fail_stream",
    ]
