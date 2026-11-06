"""The untranslated cross-context call gate (ADR-0032 section 4, M029/S01/T04).

Chapter 11 declares finance a conformist downstream of expense, so the gate has no
rows there. A scratch copy without that relationship, or with a type that still
needs translation, lists every finance element that reads or writes an expense
shape. Chapter 11 checks the rule through the DDD profile it attaches (ADR-0033), so
its seams.toml no longer lists the gate; tests/test_ddd_profile.py pins the profile's
rule to this query. Inline graphs pin the exemptions the chapter does not exercise: a shared
kernel either way round, a translating operation, and an access against the
declared direction.
"""

import shutil
import tomllib
from pathlib import Path

import pytest
import seams
from rdflib import RDF, Graph, Namespace, URIRef
from seams_cli import load_project
from seams_cli.__main__ import main
from seams_cli.check import model_graph

ROOT = Path(__file__).resolve().parent.parent
GATE = Path("docs/queries/gates/untranslated-cross-context-calls.rq")
CHAPTER_11 = Path("examples/expenses/chapter-11")
EX = "https://example.org/expenses/"
SH = Namespace("http://www.w3.org/ns/shacl#")
RELATIONSHIP = """    :expense_to_finance a arch:ContextRelationship ;
        arch:upstream :expense_context ;
        arch:downstream :finance_context ;
        arch:relationshipType arch:Conformist .
"""

# Every finance element that reads or writes a shape the expense context owns.
# :PaymentShape is finance's own (finance.trig's :finance_data), so its accesses
# are not here.
FINANCE_ACCESSES = {
    ("paid_expenses", "ExpenseShape"),
    ("payout_bpmn#choose_payout", "ExpenseShape"),
    ("payout_bpmn#pay_expense", "ExpenseShape"),
    ("payout_method", "ExpenseShape"),
    ("vendor_bpmn#review_vendor", "VendorShape"),
}


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _query() -> str:
    return (ROOT / GATE).read_text(encoding="utf-8")


def _rows(graph: Graph) -> set[tuple[str, ...]]:
    return {tuple(str(v).removeprefix(EX) for v in row) for row in graph.query(_query())}


def _project_rows(path: Path) -> set[tuple[str, ...]]:
    return _rows(model_graph(load_project(path).model))


def _scratch(tmp_path: Path, replacement: str) -> Path:
    """A copy of chapter 11 with its relationship replaced, and the gate beside it."""
    app = tmp_path / CHAPTER_11
    shutil.copytree(ROOT / CHAPTER_11, app, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / GATE).parent.mkdir(parents=True)
    for gate in sorted((ROOT / GATE).parent.glob("*.rq")):
        shutil.copy2(gate, tmp_path / GATE.parent / gate.name)
    trig = app / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(RELATIONSHIP) == 1
    trig.write_text(text.replace(RELATIONSHIP, replacement), encoding="utf-8")
    return app


def test_chapter_11_has_no_untranslated_cross_context_calls():
    assert _project_rows(ROOT / CHAPTER_11) == set()


def test_chapter_11_checks_the_rule_through_its_profile_not_the_gate():
    project = load_project(ROOT / CHAPTER_11)
    assert (ROOT / GATE).resolve() not in [gate.resolve() for gate in project.gates]
    model = seams.load(project.model).ds
    profile = seams.resolve_profile(model, seams.model_dir(project.model))
    assert profile is not None
    assert (URIRef("https://example.org/profiles/ddd#TranslatedAccess"), RDF.type, SH.NodeShape) in profile.shapes
    gates = tomllib.loads((ROOT / CHAPTER_11 / "seams.toml").read_text(encoding="utf-8")).get("gates", [])
    assert all((ROOT / CHAPTER_11 / gate).is_file() for gate in gates)


def test_seams_check_passes_on_chapter_11_with_the_profile(capsys):
    code = main(["check", "--project", str(ROOT / CHAPTER_11)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert [line for line in out.splitlines() if line.startswith(("gate ", "profile "))] == [
        "profile https://example.org/profiles/ddd 0 result(s)"
    ]


def test_without_the_relationship_every_finance_access_is_a_row(tmp_path):
    rows = _project_rows(_scratch(tmp_path, ""))
    assert rows == {(element, shape, "finance_context", "expense_context") for element, shape in FINANCE_ACCESSES}


@pytest.mark.parametrize("kind", ["CustomerSupplier", "AntiCorruptionLayer", "PublishedLanguage"])
def test_a_relationship_that_keeps_the_downstream_model_needs_translation(tmp_path, kind):
    rows = _project_rows(_scratch(tmp_path, RELATIONSHIP.replace("arch:Conformist", f"arch:{kind}")))
    assert {(element, shape) for element, shape, *_ in rows} == FINANCE_ACCESSES


def test_conformist_the_other_way_round_does_not_exempt(tmp_path):
    reversed_ = RELATIONSHIP.replace("arch:upstream :expense_context", "arch:upstream :finance_context").replace(
        "arch:downstream :finance_context", "arch:downstream :expense_context"
    )
    rows = _project_rows(_scratch(tmp_path, reversed_))
    assert {(element, shape) for element, shape, *_ in rows} == FINANCE_ACCESSES


def test_a_shared_kernel_either_way_round_exempts(tmp_path):
    kernel = RELATIONSHIP.replace("arch:upstream :expense_context", "arch:upstream :finance_context").replace(
        "arch:downstream :finance_context", "arch:downstream :expense_context"
    )
    assert _project_rows(_scratch(tmp_path, kernel.replace("arch:Conformist", "arch:SharedKernel"))) == set()


def test_seams_check_fails_on_chapter_11_without_the_relationship(tmp_path, capsys):
    app = _scratch(tmp_path, "")

    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()

    # The DDD profile's translated-access rule reports what the gate's rows would.
    summary = f"profile https://example.org/profiles/ddd {len(FINANCE_ACCESSES)} result(s)"
    lines = out.splitlines()
    assert summary in lines
    problems = [line for line in lines if not line.startswith("review ") and line != summary]
    found = sorted(line for line in problems if line.startswith("profile "))
    assert code == 1
    assert found == sorted(
        f"profile {EX}{element} - in {EX}finance_context, seam:reads or seam:writes {EX}{shape}, which "
        f"{EX}expense_context seam:owns, with no arch:Conformist or arch:SharedKernel relationship and no "
        "translating hydra:Operation"
        for element, shape in FINANCE_ACCESSES
    )
    # Editing the model changes its hash, so the lock and the generated outputs
    # are reported out of date too; nothing else is.
    rest = [line for line in problems if not line.startswith("profile ")]
    assert rest and all(line.startswith(("stale ", "lock-out-of-date ")) for line in rest)
    assert err.strip() == f"seams check: {len(problems)} problem(s)"


# Two contexts, :up owning :up_model (with :UpShape) and :down owning :down_model
# (with :DownShape). Each test adds the accesses and relationship it is about.
CONTEXTS = """
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix : <https://example.org/expenses/> .

:up a arch:BoundedContext ; seam:owns :up_model .
:down a arch:BoundedContext ; seam:owns :down_model .
:UpShape seam:inModel :up_model .
:DownShape seam:inModel :down_model .
"""


def _inline(facts: str) -> set[tuple[str, ...]]:
    return _rows(Graph().parse(data=CONTEXTS + facts, format="turtle"))


def test_an_access_within_one_context_is_not_a_row():
    assert _inline(":task seam:inModel :down_model ; seam:reads :DownShape ; seam:writes :DownShape .") == set()


def test_an_element_in_no_context_is_not_a_row():
    assert _inline(":task seam:inModel :other_model ; seam:reads :UpShape .") == set()


def test_with_no_relationship_reads_and_writes_are_rows():
    rows = _inline(":task seam:inModel :down_model ; seam:reads :UpShape ; seam:writes :UpShape .")
    assert rows == {("task", "UpShape", "down", "up")}


def test_an_upstream_element_reading_a_downstream_shape_is_a_row_under_conformist():
    facts = """
    :rel a arch:ContextRelationship ; arch:upstream :up ; arch:downstream :down ;
        arch:relationshipType arch:Conformist .
    :down_task seam:inModel :down_model ; seam:reads :UpShape .
    :up_task seam:inModel :up_model ; seam:reads :DownShape .
    """
    assert _inline(facts) == {("up_task", "DownShape", "up", "down")}


@pytest.mark.parametrize("accepts, returns", [("UpShape", "DownShape"), ("DownShape", "UpShape")])
def test_a_translating_operation_is_not_a_row(accepts, returns):
    facts = f"""
    :rel a arch:ContextRelationship ; arch:upstream :up ; arch:downstream :down ;
        arch:relationshipType arch:AntiCorruptionLayer .
    :translate a hydra:Operation ; seam:inModel :down_model ;
        seam:acceptsShape :{accepts} ; seam:returnsShape :{returns} ; seam:reads :UpShape .
    """
    assert _inline(facts) == set()


def test_an_operation_whose_other_side_is_not_its_own_is_a_row():
    facts = """
    :rel a arch:ContextRelationship ; arch:upstream :up ; arch:downstream :down ;
        arch:relationshipType arch:AntiCorruptionLayer .
    :passthrough a hydra:Operation ; seam:inModel :down_model ;
        seam:acceptsShape :UpShape ; seam:returnsShape :UpShape ; seam:reads :UpShape .
    """
    assert _inline(facts) == {("passthrough", "UpShape", "down", "up")}
