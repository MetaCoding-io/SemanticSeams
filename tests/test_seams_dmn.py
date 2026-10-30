"""seams.dmn and Decision.table (M010/S04): DMN decision tables read with lxml."""

import dataclasses
from pathlib import Path

import pytest
import seams
from seams import DecisionTable, ResolutionError
from seams.dmn import decision_table, parse_dmn

ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = ROOT / "examples/chat-app"
CHAT = CHAT_DIR / "chat-app.trig"
CH08_DIR = ROOT / "examples/expenses/chapter-08"
CH08 = CH08_DIR / "expenses.trig"

DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"


@pytest.fixture(scope="module")
def chat() -> seams.Model:
    return seams.load(CHAT)


@pytest.fixture(scope="module", params=[CH08, CH08_DIR], ids=["file", "dir"])
def ch08(request: pytest.FixtureRequest) -> seams.Model:
    return seams.load(request.param)


def _write_dmn(tmp_path: Path, decision_body: str) -> Path:
    path = tmp_path / "t.dmn"
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<definitions xmlns="{DMN_NS}" id="defs" name="T" namespace="https://example.org/t">\n'
        f'  <decision id="d1" name="D1">{decision_body}</decision>\n'
        f"</definitions>\n"
    )
    return path


ONE_BY_ONE = """
<decisionTable id="t1"{hit}>
  <input id="i1" label="In"><inputExpression id="ie1" typeRef="number"><text> x </text></inputExpression></input>
  <output id="o1" label="Out" name="out" typeRef="string" />
  <rule id="r1">{entries}</rule>
</decisionTable>
"""


# --- the example files ----------------------------------------------------


def test_routing_decision_table() -> None:
    table = decision_table(CHAT_DIR / "routing.dmn", "routing_decision")
    assert table.decision_name == "Route to Provider"
    assert table.table_id == "routing_table"
    assert table.hit_policy == "FIRST"
    assert table.aggregation is None
    assert [(i.id, i.label, i.expression, i.type_ref) for i in table.inputs] == [
        ("input_role", "Message Role", "message_role", "string"),
        ("input_length", "Message Length", "message_length", "number"),
    ]
    assert [(o.id, o.label, o.name, o.type_ref) for o in table.outputs] == [
        ("output_provider", "Provider", None, "string")
    ]
    assert [r.id for r in table.rules] == ["rule_long", "rule_default"]
    assert [r.outputs for r in table.rules] == [('"long-context-provider"',), ('"default-provider"',)]
    assert table.rules[0].inputs == ('"user"', "> 4000")
    assert table.rules[1].inputs == ("-", "-")
    assert all(r.description is None for r in table.rules)


def test_approval_routing_table() -> None:
    table = decision_table(CH08_DIR / "approval.dmn", "approval_routing")
    assert table.hit_policy == "FIRST"
    assert [i.expression for i in table.inputs] == ["amount"]
    assert [o.label for o in table.outputs] == ["Route"]
    assert [r.id for r in table.rules] == ["rule_auto", "rule_manager", "rule_finance"]
    assert [r.inputs for r in table.rules] == [("<= 100",), ("<= 1000",), ("-",)]
    assert [r.outputs for r in table.rules] == [('"auto"',), ('"manager"',), ('"finance"',)]


def test_payout_method_table() -> None:
    tables = parse_dmn(CH08_DIR / "payout.dmn")
    assert list(tables) == ["payout_method"]
    assert len(tables["payout_method"].rules) == 2


def test_tables_are_frozen() -> None:
    table = decision_table(CH08_DIR / "approval.dmn", "approval_routing")
    with pytest.raises(dataclasses.FrozenInstanceError):
        table.hit_policy = "ANY"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        table.rules[0].id = "x"  # type: ignore[misc]


# --- through the views ----------------------------------------------------


def test_decision_table_through_views(ch08: seams.Model) -> None:
    decision = ch08.processes.element("route_expense").only().decided_by
    assert decision is not None
    table = decision.table
    assert isinstance(table, DecisionTable)
    assert table.decision_id == decision.decision_id == "approval_routing"
    assert len(table.rules) == 3
    assert decision.table is table  # parsed once per file per registry


def test_chat_decision_table_through_views(chat: seams.Model) -> None:
    decision = chat.processes.element("route_to_provider").only().decided_by
    assert decision is not None
    assert decision.table.hit_policy == "FIRST"
    assert [i.id for i in decision.table.inputs] == ["input_role", "input_length"]


def test_every_decision_has_a_table(chat: seams.Model, ch08: seams.Model) -> None:
    for model in (chat, ch08):
        for decision in model.decisions:
            assert decision.table.decision_id == decision.decision_id


# --- malformed payloads -----------------------------------------------------


def test_missing_hit_policy_defaults_to_unique(tmp_path: Path) -> None:
    path = _write_dmn(
        tmp_path,
        ONE_BY_ONE.format(
            hit="", entries="<inputEntry><text>1</text></inputEntry><outputEntry><text>2</text></outputEntry>"
        ),
    )
    table = decision_table(path, "d1")
    assert table.hit_policy == "UNIQUE"
    assert table.inputs[0].expression == "x"
    assert table.outputs[0].name == "out"


def test_collect_aggregation(tmp_path: Path) -> None:
    path = _write_dmn(
        tmp_path,
        ONE_BY_ONE.format(
            hit=' hitPolicy="COLLECT" aggregation="SUM"',
            entries="<description> why </description><inputEntry><text>1</text></inputEntry>"
            "<outputEntry><text>2</text></outputEntry>",
        ),
    )
    table = decision_table(path, "d1")
    assert (table.hit_policy, table.aggregation) == ("COLLECT", "SUM")
    assert table.rules[0].description == "why"


def test_literal_expression_decision_raises(tmp_path: Path) -> None:
    path = _write_dmn(tmp_path, '<literalExpression id="le"><text>42</text></literalExpression>')
    with pytest.raises(ResolutionError, match="dmn:decisionTable") as err:
        decision_table(path, "d1")
    assert err.value.subject == "t.dmn#d1"


def test_missing_input_entry_raises(tmp_path: Path) -> None:
    path = _write_dmn(tmp_path, ONE_BY_ONE.format(hit="", entries="<outputEntry><text>2</text></outputEntry>"))
    with pytest.raises(ResolutionError, match="dmn:inputEntry") as err:
        parse_dmn(path)
    assert err.value.subject == "t.dmn#r1"


def test_extra_output_entry_raises(tmp_path: Path) -> None:
    entries = "<inputEntry><text>1</text></inputEntry><outputEntry><text>2</text></outputEntry>"
    entries += "<outputEntry><text>3</text></outputEntry>"
    path = _write_dmn(tmp_path, ONE_BY_ONE.format(hit="", entries=entries))
    with pytest.raises(ResolutionError, match="dmn:outputEntry"):
        parse_dmn(path)


def test_unknown_decision_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ResolutionError, match="dmn:decision"):
        decision_table(CH08_DIR / "payout.dmn", "nope")
