"""seams.decisions_check (M017/S02, backlog K2): decision faults found statically.

Each broken fixture is a copy of an example's model and payloads with one
mutation (a DMN typeRef, a sh:datatype or a BPMN conditionExpression), and the
test asserts the exact findings. Every example model yields none. The UNIQUE
table checks (backlog X13, M027/S04) switch an example table's hitPolicy from
FIRST to UNIQUE, then edit its input entries.
"""

import shutil
from pathlib import Path

import pytest
import seams
from seams import DecisionFinding, decision_findings
from seams.decisions_check import condition_findings, condition_names, table_findings, type_ref_findings

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
        approval_dmn=(
            '<inputExpression id="input_amount_expr" typeRef="number">',
            '<inputExpression id="input_amount_expr" typeRef="string">',
        ),
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
        expenses_trig=(
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal',
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:string',
        ),
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
        expenses_trig=(
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal',
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:integer',
        ),
    )
    assert decision_findings(model) == []


def test_missing_type_ref_is_no_finding(tmp_path: Path) -> None:
    model = ch09(
        tmp_path,
        approval_dmn=(
            '<inputExpression id="input_amount_expr" typeRef="number">',
            '<inputExpression id="input_amount_expr">',
        ),
        expenses_trig=(
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal',
            'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:string',
        ),
    )
    assert [f.subject for f in type_ref_findings(model)] == [f"{EX}payout_method"]


def test_length_measure_needs_a_number_type_ref(tmp_path: Path) -> None:
    model = _copy(
        CHAT_DIR,
        tmp_path,
        "chat-app.trig",
        {
            "routing.dmn": (
                '<inputExpression id="input_length_expr" typeRef="number">',
                '<inputExpression id="input_length_expr" typeRef="string">',
            )
        },
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
    assert [(f.subject, f.fact) for f in condition_findings(model)] == [(f"{EX}approval_bpmn#flow_manager", "decision")]


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


# ── UNIQUE tables: overlap and gaps ──

UNIQUE = ('hitPolicy="FIRST"', 'hitPolicy="UNIQUE"')
APPROVAL = "UNIQUE table 'approval_routing' in approval.dmn"
ROUTING = "UNIQUE table 'routing_decision' in routing.dmn"


def _unique(src: Path, tmp_path: Path, trig: str, dmn: str, *edits: tuple[str, str]) -> seams.Model:
    """``src`` copied with ``dmn``'s first table made UNIQUE and each edit applied in turn."""
    model = _copy(src, tmp_path, trig, {dmn: UNIQUE})
    target = tmp_path / dmn
    text = target.read_text()
    for old, new in edits:
        assert old in text, f"{old!r} not in {dmn}"
        text = text.replace(old, new, 1)
    target.write_text(text)
    return seams.load(model.path)


def _finding(message: str, subject: str = f"{EX}approval_routing") -> DecisionFinding:
    return DecisionFinding(subject, "dmn:rule", message)


def test_overlapping_rules_of_a_unique_table_are_findings(tmp_path: Path) -> None:
    """Chapter 9's FIRST table relies on rule order: as UNIQUE every pair overlaps."""
    model = _unique(CH09_DIR, tmp_path, "expenses.trig", "approval.dmn")
    assert decision_findings(model) == [
        _finding(f"rules 'rule_auto' and 'rule_finance' of {APPROVAL} both match amount = 99"),
        _finding(f"rules 'rule_auto' and 'rule_manager' of {APPROVAL} both match amount = 99"),
        _finding(f"rules 'rule_manager' and 'rule_finance' of {APPROVAL} both match amount = 99"),
    ]


def test_uncovered_input_of_a_unique_table_is_a_finding(tmp_path: Path) -> None:
    model = _unique(
        CH09_DIR,
        tmp_path,
        "expenses.trig",
        "approval.dmn",
        (
            '<inputEntry id="rule_manager_amount"><text>&lt;= 1000',
            '<inputEntry id="rule_manager_amount"><text>]100..1000]',
        ),
        ('<inputEntry id="rule_finance_amount"><text>-', '<inputEntry id="rule_finance_amount"><text>&gt; 2000'),
    )
    assert table_findings(model) == [_finding(f"no rule of {APPROVAL} matches amount = 1500")]


def test_boundary_point_left_open_is_a_gap(tmp_path: Path) -> None:
    model = _unique(
        CH09_DIR,
        tmp_path,
        "expenses.trig",
        "approval.dmn",
        ('<inputEntry id="rule_auto_amount"><text>&lt;= 100', '<inputEntry id="rule_auto_amount"><text>&lt; 100'),
        (
            '<inputEntry id="rule_manager_amount"><text>&lt;= 1000',
            '<inputEntry id="rule_manager_amount"><text>(100..1000]',
        ),
        ('<inputEntry id="rule_finance_amount"><text>-', '<inputEntry id="rule_finance_amount"><text>&gt; 1000'),
    )
    assert table_findings(model) == [_finding(f"no rule of {APPROVAL} matches amount = 100")]


def test_disjoint_complete_unique_table_has_no_finding(tmp_path: Path) -> None:
    model = _unique(
        CH09_DIR,
        tmp_path,
        "expenses.trig",
        "approval.dmn",
        (
            '<inputEntry id="rule_auto_amount"><text>&lt;= 100',
            '<inputEntry id="rule_auto_amount"><text>&lt;= 100, = 100',
        ),
        (
            '<inputEntry id="rule_manager_amount"><text>&lt;= 1000',
            '<inputEntry id="rule_manager_amount"><text>]100..1000[',
        ),
        ('<inputEntry id="rule_finance_amount"><text>-', '<inputEntry id="rule_finance_amount"><text>&gt;= 1000'),
    )
    assert decision_findings(model) == []


@pytest.mark.parametrize("entry", ["amount &gt; 1000", "not(1000)", "", '&gt; 1000, "big"'])
def test_entry_outside_the_subset_skips_the_table(tmp_path: Path, entry: str) -> None:
    """FEEL the check does not read, an empty entry, or numbers mixed with strings: no guess."""
    model = _unique(
        CH09_DIR,
        tmp_path,
        "expenses.trig",
        "approval.dmn",
        ('<inputEntry id="rule_finance_amount"><text>-', f'<inputEntry id="rule_finance_amount"><text>{entry}'),
    )
    assert table_findings(model) == []


def test_unique_table_over_strings_and_numbers(tmp_path: Path) -> None:
    """The chat app's two-input table: the default rule overlaps the long one,
    and once it lists only "user" every other role is uncovered."""
    model = _unique(CHAT_DIR, tmp_path, "chat-app.trig", "routing.dmn")
    overlap = (
        f"rules 'rule_long' and 'rule_default' of {ROUTING} both match message_role = \"user\", message_length = 4001"
    )
    assert table_findings(model) == [_finding(overlap, f"{CHAT}routing_decision")]
    model = _unique(
        CHAT_DIR,
        tmp_path,
        "chat-app.trig",
        "routing.dmn",
        ('<inputEntry id="rule_default_role"><text>-', '<inputEntry id="rule_default_role"><text>"user"'),
    )
    gap = f'no rule of {ROUTING} matches message_role not "user", message_length = 3999'
    assert table_findings(model) == [
        _finding(gap, f"{CHAT}routing_decision"),
        _finding(overlap, f"{CHAT}routing_decision"),
    ]


def test_first_tables_are_not_checked(tmp_path: Path) -> None:
    model = ch09(tmp_path)
    assert sorted(d.table.hit_policy for d in model.decisions) == ["FIRST", "FIRST"]
    assert table_findings(model) == []


def test_findings_are_exported_from_seams() -> None:
    assert seams.decision_findings is decision_findings
    assert seams.table_findings is table_findings
    assert seams.DecisionFinding is DecisionFinding
