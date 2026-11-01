"""seams.decisions_check (M017/S02, backlog K2): decision faults found statically.

Each broken fixture is a copy of an example's model and payloads with one
mutation (a DMN typeRef, a sh:datatype or a BPMN conditionExpression), and the
test asserts the exact findings. Every example model yields none.
"""

import shutil
from pathlib import Path

import pytest
import seams
from seams import DecisionFinding, decision_findings
from seams.decisions_check import condition_findings, condition_names, type_ref_findings

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "examples").rglob("*.trig"))
CH09_DIR = ROOT / "examples/expenses/chapter-09"
CHAT_DIR = ROOT / "examples/chat-app"

EX = "https://example.org/expenses/"
CHAT = "https://example.org/chat/"


def _copy(src: Path, dest: Path, trig: str, edits: dict[str, tuple[str, str]]) -> seams.Model:
    """Copy ``src``'s model and BPMN/DMN payloads into ``dest``, apply each
    ``file: (old, new)`` edit (which must match), and load the copy."""
    for path in [src / trig, *src.glob("*.bpmn"), *src.glob("*.dmn")]:
        shutil.copy(path, dest / path.name)
    for name, (old, new) in edits.items():
        target = dest / name
        text = target.read_text()
        assert old in text, f"{old!r} not in {name}"
        target.write_text(text.replace(old, new, 1))
    return seams.load(dest / trig)


def ch09(tmp_path: Path, **edits: tuple[str, str]) -> seams.Model:
    return _copy(CH09_DIR, tmp_path, "expenses.trig", {k.replace("_", "."): v for k, v in edits.items()})


@pytest.mark.parametrize("trig", EXAMPLES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_example_yields_no_finding(trig: Path) -> None:
    assert decision_findings(seams.load(trig)) == []


def test_the_example_conditions_are_checked_not_skipped() -> None:
    """Chapter 9 has seven conditions; each reads one name the check resolves."""
    model = seams.load(CH09_DIR / "expenses.trig")
    conditions = [f.condition for p in model.processes for n in p.nodes() for f in n.outgoing if f.condition]
    assert len(conditions) == 7
    assert sorted({n for c in conditions for n in condition_names(c)}) == ["decision", "method", "route"]


# ── typeRef against sh:datatype ──


def test_dmn_type_ref_disagreeing_with_the_datatype_is_a_finding(tmp_path: Path) -> None:
    model = ch09(
        tmp_path,
        approval_dmn=('<inputExpression id="input_amount_expr" typeRef="number">',
                      '<inputExpression id="input_amount_expr" typeRef="string">'),
    )
    assert decision_findings(model) == [
        DecisionFinding(
            f"{EX}approval_routing",
            f"{EX}amount",
            "input 'amount' of 'approval_routing' in approval.dmn is typeRef string, "
            "but ExpenseShape gives 'amount' sh:datatype xsd:decimal",
        )
    ]


def test_shape_datatype_disagreeing_with_every_reading_decision(tmp_path: Path) -> None:
    model = ch09(
        tmp_path,
        expenses_trig=("sh:path :amount ; sh:datatype xsd:decimal", "sh:path :amount ; sh:datatype xsd:string"),
    )
    assert type_ref_findings(model) == [
        DecisionFinding(
            f"{EX}approval_routing",
            f"{EX}amount",
            "input 'amount' of 'approval_routing' in approval.dmn is typeRef number, "
            "but ExpenseShape gives 'amount' sh:datatype xsd:string",
        ),
        DecisionFinding(
            f"{EX}payout_method",
            f"{EX}amount",
            "input 'amount' of 'payout_method' in payout.dmn is typeRef number, "
            "but ExpenseShape gives 'amount' sh:datatype xsd:string",
        ),
    ]


def test_integer_datatype_satisfies_a_number_type_ref(tmp_path: Path) -> None:
    model = ch09(
        tmp_path,
        expenses_trig=("sh:path :amount ; sh:datatype xsd:decimal", "sh:path :amount ; sh:datatype xsd:integer"),
    )
    assert decision_findings(model) == []


def test_missing_type_ref_is_no_finding(tmp_path: Path) -> None:
    model = ch09(
        tmp_path,
        approval_dmn=('<inputExpression id="input_amount_expr" typeRef="number">',
                      '<inputExpression id="input_amount_expr">'),
        expenses_trig=("sh:path :amount ; sh:datatype xsd:decimal", "sh:path :amount ; sh:datatype xsd:string"),
    )
    assert [f.subject for f in type_ref_findings(model)] == [f"{EX}payout_method"]


def test_length_measure_needs_a_number_type_ref(tmp_path: Path) -> None:
    model = _copy(
        CHAT_DIR,
        tmp_path,
        "chat-app.trig",
        {"routing.dmn": ('<inputExpression id="input_length_expr" typeRef="number">',
                         '<inputExpression id="input_length_expr" typeRef="string">')},
    )
    assert decision_findings(model) == [
        DecisionFinding(
            f"{CHAT}routing_decision",
            f"{CHAT}content",
            "input 'message_length' of 'routing_decision' in routing.dmn is typeRef string, "
            "but dec:Length measures a number",
        )
    ]


def test_unknown_payload_element_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    model = ch09(tmp_path, expenses_trig=('dec:payloadElement "payout_method"', 'dec:payloadElement "nope"'))
    [finding] = type_ref_findings(model)
    assert (finding.subject, finding.fact) == (f"{EX}payout_method", "https://w3id.org/seams/dec#payloadElement")
    assert "'nope' not among DMN decision ids" in finding.message


# ── gateway conditions ──


def test_condition_reading_an_unset_variable_is_a_finding(tmp_path: Path) -> None:
    model = ch09(tmp_path, approval_bpmn=('route == "auto"', 'rout == "auto"'))
    assert decision_findings(model) == [
        DecisionFinding(
            f"{EX}approval_bpmn#flow_auto",
            "rout",
            "condition 'rout == \"auto\"' reads 'rout', but no decision or user task "
            "upstream of 'route_gateway' sets it",
        )
    ]


def test_condition_before_the_user_task_that_sets_it_is_a_finding(tmp_path: Path) -> None:
    """``decision`` is an ApprovalShape field, set only after the approval
    user tasks, so the route gateway cannot read it."""
    model = ch09(tmp_path, approval_bpmn=('route == "manager"', 'decision == "manager"'))
    assert [(f.subject, f.fact) for f in condition_findings(model)] == [
        (f"{EX}approval_bpmn#flow_manager", "decision")
    ]


def test_condition_reading_another_process_variable_is_a_finding(tmp_path: Path) -> None:
    """``route`` is set in the approval process; the payout process cannot read it."""
    model = ch09(tmp_path, payout_bpmn=('method == "now"', 'route == "now"'))
    assert [(f.subject, f.fact) for f in condition_findings(model)] == [(f"{EX}payout_bpmn#flow_now", "route")]


def test_condition_that_does_not_parse_is_a_finding(tmp_path: Path) -> None:
    model = ch09(tmp_path, payout_bpmn=('method == "now"', "method =="))
    [finding] = condition_findings(model)
    assert (finding.subject, finding.fact) == (f"{EX}payout_bpmn#flow_now", "method ==")
    assert finding.message.startswith("is not a Python expression the engine can evaluate")


def test_condition_names_skip_builtins_constants_and_bound_names() -> None:
    assert condition_names('route == "auto" and len(comment) > 0') == ("comment", "route")
    assert condition_names("any(x > limit for x in amounts) or flag is None") == ("amounts", "flag", "limit")
    assert condition_names("True") == ()
    with pytest.raises(SyntaxError):
        condition_names("route ==")


def test_findings_are_exported_from_seams() -> None:
    assert seams.decision_findings is decision_findings
    assert seams.DecisionFinding is DecisionFinding
