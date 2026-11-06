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
from seams_cli.check import ADVISORY_KINDS, check_drafts, check_ontology, check_review
from seams_cli.generate import generate_project
from seams_cli.lockfile import Draft, Fault, read_lock, render_lock, with_draft
from seams_cli.project import resolve_model
from seams_cli.propose import build_prompt

from tests.workspace_copy import copy_workspace

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
    copy_workspace(tmp_path)
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
    return f"seams check: {count} warning(s)\n" if count else ""


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


def _profile_lines(app: Path) -> list[str]:
    """The ``profile <IRI> 0 result(s)`` line of a project whose model attaches a
    profile (ADR-0033 section 1), else nothing: an example's profile holds."""
    model = load_project(app).model
    profile = seams.resolve_profile(seams.load(model).ds, seams.model_dir(model))
    return [] if profile is None else [f"profile {profile.iri} 0 result(s)"]


@pytest.mark.parametrize("rel", PROJECTS, ids=str)
def test_every_example_passes_in_place(rel, capsys):
    code, lines, err = _check(ROOT / rel, capsys)
    assert (code, lines, err) == (0, _profile_lines(ROOT / rel), _warnings(ROOT / rel))


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
    assert _check(app, capsys) == (0, [], "seams check: 8 warning(s)\n")


def test_review_findings_are_printed_but_do_not_fail(app, capsys):
    """Chapter 5's shapes have no target class and its paths are undeclared: eight review lines, exit 0."""
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    assert (code, out.splitlines(), err) == (0, CHAPTER_5_REVIEW, "seams check: 8 warning(s)\n")


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


def test_review_vocabulary_ontology_and_profile_warnings_are_the_advisory_kinds():
    assert ADVISORY_KINDS == frozenset(
        {"ontology-superclass", "profile-warning", "review", "shacl-warning", "vocabulary-migrated"}
    )


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


def _unset_coverage(app: Path) -> None:
    toml = app / "seams.toml"
    text = toml.read_text(encoding="utf-8")
    assert text.count('coverage = ["paths"]\n') == 1
    toml.write_text(text.replace('coverage = ["paths"]\n', ""), encoding="utf-8")


def test_chapter_9_passes_with_the_paths_gate_on(tmp_path, capsys):
    """Every chapter 9 path is run by a scenario (D054, tests/test_seams_coverage.py), so its gate is on and clean."""
    app = _chapter_9(tmp_path)
    assert load_project(app).coverage == ("paths",)
    assert _check(app, capsys) == (0, [], _warnings(app))


def test_coverage_paths_reports_each_unexercised_path(tmp_path, capsys):
    """Without two of chapter 9's scenarios, the paths only they run are findings."""
    app = _chapter_9(tmp_path)
    trig = app / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    for name in ("manager_rejected", "paid_now"):
        start = text.index(f"    :{name} a verify:Scenario ;")
        text = text[:start] + text[text.index("\n\n", start) + 2 :]
    trig.write_text(text, encoding="utf-8")
    assert main(["generate", "--project", str(app)]) == 0
    capsys.readouterr()
    code, lines, err = _check(app, capsys)
    expected = sorted(
        "coverage " + " ".join((str(p.process.iri), *(str(i) for i in p.iris)))
        for p in seams.unexercised_paths(seams.load(trig))
    )
    assert code == 1
    assert len(expected) == 2
    assert lines == expected
    assert err.strip() == "seams check: 2 problem(s)"
    assert lines[0].endswith("https://example.org/expenses/approval_bpmn#rejected_end")
    assert lines[1].endswith("https://example.org/expenses/payout_bpmn#paid_out")


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


def test_overlapping_rules_of_a_unique_table_are_decision_findings(tmp_path, capsys):
    """Backlog X13 (seams.table_findings): chapter 9's FIRST approval table as UNIQUE."""
    app = _chapter_9(tmp_path)
    dmn = app / "approval.dmn"
    text = dmn.read_text(encoding="utf-8")
    assert 'hitPolicy="FIRST"' in text
    dmn.write_text(text.replace('hitPolicy="FIRST"', 'hitPolicy="UNIQUE"', 1), encoding="utf-8")
    code, lines, _err = _check(app, capsys)
    assert code == 1
    table = "of UNIQUE table 'approval_routing' in approval.dmn both match amount = 99"
    assert [line for line in lines if line.startswith("decision ")] == [
        f"decision https://example.org/expenses/approval_routing dmn:rule rules {pair} {table}"
        for pair in (
            "'rule_auto' and 'rule_finance'",
            "'rule_auto' and 'rule_manager'",
            "'rule_manager' and 'rule_finance'",
        )
    ]


def test_coverage_unset_adds_no_findings(tmp_path, capsys):
    app = _chapter_9(tmp_path)
    _unset_coverage(app)
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


DRAFT_TASK = "notify_manager"


@pytest.fixture
def drafted(tmp_path: Path) -> Path:
    """Chapter 9 with its handlers/notify.py recorded in seams.lock as an accepted draft."""
    root = _copy(Path("examples/expenses/chapter-09"), tmp_path)
    toml = root / "seams.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("../../../docs", str(ROOT / "docs")), encoding="utf-8")
    project = load_project(root)
    model = resolve_model(project, None)
    prompt = build_prompt(project, None, DRAFT_TASK)
    digest = hashlib.sha256((root / prompt.handler_path).read_bytes()).hexdigest()
    record = Draft(prompt.task, prompt.handler_path, prompt.context_hash, prompt.template, "fake", digest)
    (root / "seams.lock").write_text(render_lock(with_draft(project, model, read_lock(project), record)))
    return root


def _draft_findings(root: Path) -> list[Finding]:
    project = load_project(root)
    return check_drafts(project, resolve_model(project, None))


def test_a_recorded_draft_that_still_matches_gives_no_findings(drafted):
    assert _draft_findings(drafted) == []
    assert [f for f in run_check(load_project(drafted), drafted / "expenses.trig") if f.kind.startswith("draft")] == []


def test_a_changed_shape_the_task_depends_on_makes_the_draft_stale(drafted):
    trig = drafted / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    trig.write_text(text.replace('rdfs:label "Notification"', 'rdfs:label "Notice"'), encoding="utf-8")
    task = "https://example.org/expenses/approval_bpmn#notify_manager"
    assert _draft_findings(drafted) == [Finding("draft-stale", f"{task} handlers/notify.py")]


def test_an_edited_draft_is_hand_edited(drafted):
    module = drafted / "handlers" / "notify.py"
    module.write_text(module.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    task = "https://example.org/expenses/approval_bpmn#notify_manager"
    assert _draft_findings(drafted) == [Finding("draft-hand-edited", f"{task} handlers/notify.py")]


def test_a_deleted_draft_is_hand_edited_and_missing(drafted):
    (drafted / "handlers" / "notify.py").unlink()
    task = "https://example.org/expenses/approval_bpmn#notify_manager"
    assert _draft_findings(drafted) == [Finding("draft-hand-edited", f"{task} handlers/notify.py missing")]


def test_a_draft_whose_task_no_longer_resolves_is_stale(drafted):
    lock = json.loads((drafted / "seams.lock").read_text(encoding="utf-8"))
    lock["drafts"][0]["task"] = "no_such_task"
    (drafted / "seams.lock").write_text(json.dumps(lock), encoding="utf-8")
    [finding] = _draft_findings(drafted)
    assert finding.kind == "draft-stale" and finding.detail.startswith("no_such_task handlers/notify.py ")


# ── ontology faults and warnings (ADR-0022 section 5) ──

CHAPTER_01 = Path("examples/expenses/chapter-01")
GIST = "https://w3id.org/semanticarts/ns/ontology/gist/"

ONTOLOGY_GRAPH = """
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <{imports}> .

    :Expense a owl:Class ;
        rdfs:subClassOf <https://w3id.org/semanticarts/ns/ontology/gist/Transaction> ;
        rdfs:label "Expense" ;
        seam:inModel :expense_ontology .

    :TravelExpense a owl:Class ;
        rdfs:subClassOf :Expense , <https://w3id.org/semanticarts/ns/ontology/gist/Transation> ;
        rdfs:label "Travel expense" ;
        seam:inModel :expense_ontology .
}}
"""


def _with_ontology(tmp_path: Path, imports: str) -> Path:
    app = _copy(CHAPTER_01, tmp_path)
    trig = app / "expenses.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + ONTOLOGY_GRAPH.format(imports=imports), encoding="utf-8")
    return app


def test_an_undeclared_superclass_is_an_advisory_ontology_finding(tmp_path, capsys):
    app = _with_ontology(tmp_path, "https://w3id.org/semanticarts/ontology/gistCore14.0.0")
    project = load_project(app)
    finding = Finding(
        "ontology-superclass",
        "https://example.org/expenses/TravelExpense http://www.w3.org/2000/01/rdf-schema#subClassOf "
        f"{GIST}Transation declared neither in the ontology nor in a resolved import",
    )
    assert check_ontology(project.model) == [finding]
    assert finding in run_check(project, project.model)
    # The edited model changes the locked model hash; regenerate, then the warning is the only finding.
    assert main(["generate", "--project", str(app)]) == 0
    capsys.readouterr()
    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()
    assert code == 0, out
    assert f"ontology-superclass {finding.detail}" in out.splitlines()
    assert "warning(s)" in err


def test_an_import_version_mismatch_fails_the_check_as_a_model_fault(tmp_path, capsys):
    app = _with_ontology(tmp_path, "https://w3id.org/semanticarts/ontology/gistCore14.1.0")
    code = main(["check", "--project", str(app)])
    _out, err = capsys.readouterr()
    assert code == 2
    assert "imports gistCore14.1.0; the vendored version is gistCore14.0.0" in err
    assert "http://www.w3.org/2002/07/owl#imports" in err


@pytest.mark.parametrize("form", ["dir", "toml", "model"])
def test_a_path_positional_is_the_project_or_its_model(app, capsys, form):
    """``seams check PATH`` takes the project directory, its seams.toml or its model, like the flags."""
    path = {"dir": app, "toml": app / "seams.toml", "model": load_project(app).model}[form]
    code = main(["check", str(path)])
    out, err = capsys.readouterr()
    assert (code, out.splitlines(), err) == (0, CHAPTER_5_REVIEW, "seams check: 8 warning(s)\n")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--project", "."], "give PATH or --project, not both"),
        (["--model", "other.trig"], "give PATH or --model, not both"),
    ],
)
def test_a_path_positional_and_its_flag_is_a_usage_error(app, capsys, argv, message):
    path = app if argv[0] == "--project" else load_project(app).model
    with pytest.raises(SystemExit) as exc:
        main(["check", str(path), *argv])
    assert exc.value.code == 2
    assert f"check: {message}" in capsys.readouterr().err


def test_a_stale_deploy_dockerfile_fails_the_check(tmp_path, capsys):
    """Backlog A11: a deploy:dockerfile naming a file the dockerfile generator does not write. Lenient
    generation collects the fault, so the check reports the lock it would write as out of date."""
    app = _chapter_9(tmp_path)
    model = app / "expenses.trig"
    stated = 'deploy:dockerfile "examples/expenses/chapter-09/generated/expense_api.Dockerfile"'
    text = model.read_text(encoding="utf-8")
    assert text.count(stated) == 1
    model.write_text(text.replace(stated, 'deploy:dockerfile "docker/runtime.Dockerfile"'), encoding="utf-8")
    code, lines, _err = _check(app, capsys)
    assert code == 1
    assert f"lock-out-of-date {app / LOCK}" in lines
    faults = generate_project(load_project(app), model, lenient=True).faults
    assert [f for f in faults if f.generator == "dockerfile"] == [
        Fault(
            "dockerfile",
            "https://w3id.org/seams/deploy#dockerfile",
            f"{EX}expense_api",
            f"the {EX}development deploy:build states 'docker/runtime.Dockerfile'; it must name the generated "
            "Dockerfile, 'examples/expenses/chapter-09/generated/expense_api.Dockerfile' relative to the build context",
        )
    ]
