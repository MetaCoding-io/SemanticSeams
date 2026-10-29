"""The complexity check (backlog E3, D025): seams_gen.complexity against the
chat app, the checkout example, the chapter-08 expense model (the passing
worked example) and a synthetic passing model, plus the CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from seams_gen.complexity import (
    MIN_MAX_REACH,
    MIN_MULTI_MODEL_NOTATIONS,
    load_model,
    main,
    measure,
)

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHECKOUT = ROOT / "examples" / "checkout.trig"
EXPENSES = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
SEAM = "https://w3id.org/seams/seam#"
NOTATIONS = ["BPMN", "C4", "DMN", "IFML", "ShapeGraph", "Statechart"]


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "seams_gen.complexity", *args],
                          cwd=ROOT, capture_output=True, text=True)


def test_thresholds():
    assert (MIN_MULTI_MODEL_NOTATIONS, MIN_MAX_REACH) == (3, 5)


def test_chat_app_scores_0_3_58_and_fails():
    r = measure(load_model(CHAT))
    assert r.models_per_notation == [(SEAM + n, 1) for n in NOTATIONS]
    assert r.multi_model_notations == 0
    chat = "https://example.org/chat/"
    assert r.most_reached[:2] == [(chat + "MessageShape", 3), (chat + "send_message_op", 3)]
    assert len(r.most_reached) == 5
    assert r.max_reach == 3
    assert r.edges == 58
    assert r.failures == [
        "notations with 2+ models: 0, need at least 3",
        "most models one element is reached from: 3, need at least 5",
    ]


def test_checkout_scores():
    r = measure(load_model(CHECKOUT))
    assert r.models_per_notation[0] == (SEAM + "BPMN", 2)
    assert sorted(r.models_per_notation[1:]) == [(SEAM + n, 1) for n in NOTATIONS if n != "BPMN"]
    assert r.multi_model_notations == 1
    assert r.max_reach == 4
    assert r.edges == 36
    shop = "https://example.org/shop/"
    # The fifth row is the IRI-first of many elements tied at 1 (deterministic tie-break).
    assert r.most_reached == [
        (shop + "OrderShape", 4),
        (shop + "order_events", 3),
        (shop + "submit_order_op", 3),
        (shop + "order_process", 2),
        (shop + "app01", 1),
    ]
    assert len(r.failures) == 2


def test_expense_chapter_8_scores_4_6_111_and_passes():
    """The finished expense tutorial: two models each of BPMN, DMN, IFML and
    statechart, and ExpenseShape reached from six models (the expense UI,
    both processes, both decisions and the finance console)."""
    r = measure(load_model(EXPENSES))
    assert r.models_per_notation == [
        (SEAM + "BPMN", 2), (SEAM + "DMN", 2), (SEAM + "IFML", 2), (SEAM + "Statechart", 2),
        (SEAM + "C4", 1), (SEAM + "ShapeGraph", 1),
    ]
    assert r.multi_model_notations == 4
    ex = "https://example.org/expenses/"
    assert r.most_reached == [
        (ex + "ExpenseShape", 6),
        (ex + "PaymentShape", 4),
        (ex + "payouts", 3),
        (ex + "submit_expense_op", 3),
        (ex + "ApprovalShape", 2),
    ]
    assert r.max_reach == 6
    assert r.edges == 111
    assert r.failures == []


def test_cli_expense_chapter_8_passes():
    p = _cli("examples/expenses/chapter-08/expenses.trig")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.splitlines()[-1] == "PASS"
    assert "  ExpenseShape: 6" in p.stdout
    assert "seam edges: 111 (reported, not gated)" in p.stdout


def test_measure_is_deterministic():
    assert measure(load_model(CHECKOUT)) == measure(load_model(CHECKOUT))


def test_ontology_is_not_loaded():
    """seam:reveal annotations in ontology/*.ttl must not count as edges."""
    g = load_model(CHAT)
    assert not any(str(p) == SEAM + "reveal" for p in g.predicates())


PASSING = """\
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix : <https://example.org/t/> .

:seams {
""" + "".join(
    f"  :{n.lower()}{i} a seam:Model ; seam:notation seam:{n} .\n"
    for n in ("BPMN", "IFML", "C4") for i in (1, 2)
) + """}

:bpmn1 { :a1 seam:inModel :bpmn1 ; seam:writes :Target . }
:bpmn2 { :a2 seam:inModel :bpmn2 ; seam:writes :Target . }
:ifml1 { :a3 seam:inModel :ifml1 ; seam:writes :Target . }
:ifml2 { :a4 seam:inModel :ifml2 ; seam:writes :Target . }
:c41   { :a5 seam:inModel :c41 ; seam:writes :Target . }
"""


@pytest.fixture
def passing_model(tmp_path: Path) -> Path:
    path = tmp_path / "passing.trig"
    path.write_text(PASSING, encoding="utf-8")
    return path


def test_synthetic_model_passes(passing_model: Path):
    r = measure(load_model(passing_model))
    assert r.multi_model_notations == 3
    assert r.most_reached[0] == ("https://example.org/t/Target", 5)
    assert r.edges == 5
    assert r.failures == []


def test_one_short_of_each_threshold_fails(tmp_path: Path):
    """Boundary: 2 multi-model notations and a max reach of 4 both fail."""
    text = PASSING.replace(":c42 a seam:Model ; seam:notation seam:C4 .\n", "")
    text = text.replace(":c41   { :a5 seam:inModel :c41 ; seam:writes :Target . }\n", "")
    path = tmp_path / "short.trig"
    path.write_text(text, encoding="utf-8")
    r = measure(load_model(path))
    assert (r.multi_model_notations, r.max_reach) == (2, 4)
    assert len(r.failures) == 2


def test_empty_model_reports_zero(tmp_path: Path):
    path = tmp_path / "empty.trig"
    path.write_text("", encoding="utf-8")
    r = measure(load_model(path))
    assert (r.models_per_notation, r.most_reached, r.edges, r.max_reach) == ([], [], 0, 0)
    assert len(r.failures) == 2


def test_main_in_process(passing_model: Path, capsys):
    assert main([str(passing_model)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "PASS"


def test_cli_chat_app_fails():
    p = _cli("examples/chat-app/chat-app.trig")
    assert p.returncode == 1, p.stderr
    assert "FAIL" in p.stdout
    assert "seam edges: 58 (reported, not gated)" in p.stdout
    assert "  C4: 1" in p.stdout
    assert "  MessageShape: 3" in p.stdout
    assert "notations with 2+ models: 0, need at least 3" in p.stdout
    assert "most models one element is reached from: 3, need at least 5" in p.stdout


def test_cli_passing_model(passing_model: Path):
    p = _cli(str(passing_model))
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.splitlines()[-1] == "PASS"


def test_cli_missing_file(tmp_path: Path):
    p = _cli(str(tmp_path / "nope.trig"))
    assert p.returncode == 2
    assert p.stderr.strip()
    assert p.stdout == ""


def test_cli_invalid_trig(tmp_path: Path):
    bad = tmp_path / "bad.trig"
    bad.write_text("this is { not trig", encoding="utf-8")
    p = _cli(str(bad))
    assert p.returncode == 2
    assert p.stderr.strip()


def test_cli_directory_is_an_error(tmp_path: Path):
    p = _cli(str(tmp_path))
    assert p.returncode == 2
    assert p.stderr.strip()


def test_complexity_queries_stay_off_the_reference_page():
    """docs/scripts/generate.py renders docs/queries/*.rq (top level only)."""
    complexity = {p.name for p in (ROOT / "docs" / "queries" / "complexity").glob("*.rq")}
    assert complexity == {"models-per-notation.rq", "most-reached.rq", "seam-edges.rq"}
    top = sorted(p.name for p in (ROOT / "docs" / "queries").glob("*.rq"))
    assert not complexity & set(top)


def test_each_query_states_its_question():
    for p in (ROOT / "docs" / "queries" / "complexity").glob("*.rq"):
        first = p.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("# ") and first.endswith("?"), p.name
