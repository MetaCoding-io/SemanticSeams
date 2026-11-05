"""The ``condition-to-dmn`` change builder of ``seams suggest`` (M025/S01, ADR-0028).

The fixture is a copy of the expense tutorial's chapter 10 whose
``decision_gateway`` routes on the submitted amount inline (``amount <= 2000``)
instead of on the approver's decision. The suggestion that moves that rule into
a DMN decision is built here, test-side; no provider runs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import seams
from lxml import etree
from rdflib import Literal, URIRef
from seams import DEC, SEAM
from seams_cli.project import load_project
from seams_cli.suggest import (
    Change,
    ConditionToDmn,
    SuggestionError,
    build_change,
    check_change,
    parse_suggestion,
)

from seams_edit import Patch
from tests.workspace_copy import copy_example

ROOT = Path(__file__).resolve().parent.parent
CH10 = ROOT / "examples" / "expenses" / "chapter-10"
EX = "https://example.org/expenses/"
BPMN = f"{EX}approval_bpmn#"
# The inline rule the fixture puts on decision_gateway's two flows.
INLINE = {"flow_approved": "amount <= 2000", "flow_rejected": "amount > 2000"}


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def app(tmp_path) -> Path:
    root = copy_example(CH10, tmp_path, ignore=shutil.ignore_patterns("__pycache__"))
    bpmn = root / "approval.bpmn"
    text = bpmn.read_text(encoding="utf-8")
    for outcome, condition in (("approved", INLINE["flow_approved"]), ("rejected", INLINE["flow_rejected"])):
        old = f'>decision == "{outcome}"<'
        assert old in text
        text = text.replace(old, f">{condition.replace('<', '&lt;').replace('>', '&gt;')}<")
    bpmn.write_text(text, encoding="utf-8")
    return root


def _model(app: Path) -> seams.Model:
    return seams.load(app / "expenses.trig")


def _answer(**changes: object) -> str:
    answer: dict[str, object] = {
        "kind": "condition-to-dmn",
        "gateway": "decision_gateway",
        "decision_id": "approval_outcome",
        "decision_name": "Approval Outcome",
        "inputs": ["amount"],
        "output": "outcome",
        "rules": [{"when": {"amount": "<= 2000"}, "then": '"approved"'}, {"then": '"rejected"'}],
        "conditions": {"flow_approved": 'outcome == "approved"', "flow_rejected": 'outcome == "rejected"'},
    }
    answer.update(changes)
    return json.dumps(answer)


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_fixture_gateway_holds_an_inline_condition_the_checks_accept(app):
    model = _model(app)
    process = model.processes.for_bpmn_process("approval_process").only()
    gateway = next(n for n in process.gateways() if n.bpmn_id == "decision_gateway")
    assert {f.id: f.condition for f in gateway.outgoing} == INLINE
    assert seams.decision_findings(model) == []


def test_a_valid_suggestion_builds_a_change_that_validates_and_generates(app):
    model = _model(app)
    suggestion = parse_suggestion(model, _answer())
    assert isinstance(suggestion, ConditionToDmn)
    assert suggestion.conditions == (
        ("flow_approved", 'outcome == "approved"'),
        ("flow_rejected", 'outcome == "rejected"'),
    )
    change = build_change(model, suggestion)

    decision, task = URIRef(f"{EX}approval_outcome"), URIRef(f"{BPMN}approval_outcome")
    adds = set(change.patch.adds)
    assert (
        decision,
        DEC.payloadElement,
        Literal("approval_outcome"),
        URIRef("urn:seams:graph:model:approval_dmn"),
    ) in adds
    assert (task, SEAM.decidedBy, decision, URIRef("urn:seams:graph:seams")) in adds
    assert (task, SEAM.reads, URIRef(f"{EX}ExpenseShape"), URIRef("urn:seams:graph:seams")) in adds
    assert {(p, o) for _, p, o, _ in adds if p in (DEC.fromPath, DEC.processVariable)} == {
        (DEC.fromPath, URIRef(f"{EX}amount")),
        (DEC.processVariable, Literal("outcome")),
    }
    assert not change.patch.removes

    payloads = dict(change.payloads)
    assert sorted(p.name for p in payloads) == ["approval.bpmn", "approval.dmn"]
    bpmn = etree.fromstring(payloads[app / "approval.bpmn"].encode())
    ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
    rule_task = bpmn.find(".//bpmn:businessRuleTask[@id='approval_outcome']", ns)
    assert rule_task is not None and rule_task.get("name") == "Approval Outcome"
    for flow in ("flow_manager_decided", "flow_finance_decided"):
        assert bpmn.find(f".//bpmn:sequenceFlow[@id='{flow}']", ns).get("targetRef") == "approval_outcome"
    joined = bpmn.find(".//bpmn:sequenceFlow[@id='approval_outcome_to_decision_gateway']", ns)
    assert joined is not None and joined.get("targetRef") == "decision_gateway"
    assert "approval_outcome" in seams.parse_dmn(_write_tmp(app, payloads[app / "approval.dmn"]))

    # The same model and answer give the same bytes.
    assert build_change(_model(app), parse_suggestion(_model(app), _answer())) == change

    verdicts = check_change(load_project(app), change)
    assert verdicts.findings == ()
    assert verdicts.validated and verdicts.generated and verdicts.passed
    assert verdicts.outputs > 0


def _write_tmp(app: Path, text: str) -> Path:
    path = app.parent / "suggested.dmn"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_suggestion_leaves_the_project_bytes_unchanged(app):
    before = _snapshot(app)
    model = _model(app)
    change = build_change(model, parse_suggestion(model, _answer()))
    assert check_change(load_project(app), change).passed
    assert _snapshot(app) == before


def test_a_missing_field_is_rejected_naming_the_gateway_and_the_field(app):
    model = _model(app)
    suggestion = parse_suggestion(
        model, _answer(inputs=["mileage"], rules=[{"when": {"mileage": "> 1"}, "then": '"x"'}])
    )
    with pytest.raises(SuggestionError) as err:
        build_change(model, suggestion)
    assert err.value.subject == f"{BPMN}decision_gateway"
    assert err.value.predicate == str(SEAM.reads)
    assert "'mileage'" in err.value.detail


def test_a_nonexistent_gateway_is_rejected_naming_it(app):
    with pytest.raises(SuggestionError) as err:
        parse_suggestion(_model(app), _answer(gateway="no_such_gateway"))
    assert err.value.subject == "no_such_gateway"
    assert err.value.predicate == "gateway"


@pytest.mark.parametrize(
    ("answer", "subject", "predicate", "detail"),
    [
        ("not json", "suggestion", "json", "not JSON"),
        ("[1]", "suggestion", "json", "one JSON object"),
        (_answer(kind="merge-shapes"), "suggestion", "kind", "'merge-shapes'"),
        (_answer(extra=1), "suggestion", "extra", "unknown key"),
        (_answer(decision_id="1bad id"), "suggestion", "decision_id", "not an XML id"),
        (_answer(inputs=[]), "suggestion", "inputs", "non-empty list"),
        (_answer(output="not a name"), "suggestion", "output", "not a name"),
        (_answer(rules=[{"when": {"date": "-"}, "then": '"x"'}]), "suggestion", "rules[0].when", "name no input"),
        (_answer(rules=[{"when": {}}]), "suggestion", "then", "non-empty string"),
        (
            _answer(conditions={"flow_approved": 'outcome == "approved"', "flow_auto": 'outcome == "x"'}),
            f"{BPMN}flow_auto",
            "conditions",
            "not an outgoing flow",
        ),
        (
            _answer(conditions={"flow_approved": 'outcome == "approved"'}),
            f"{BPMN}flow_rejected",
            "conditionExpression",
            "no condition",
        ),
        (
            _answer(conditions={"flow_approved": "amount <= 2000", "flow_rejected": 'outcome == "rejected"'}),
            f"{BPMN}flow_approved",
            "conditionExpression",
            "not only the output",
        ),
        (
            _answer(conditions={"flow_approved": "outcome ==", "flow_rejected": 'outcome == "rejected"'}),
            f"{BPMN}flow_approved",
            "conditionExpression",
            "is not Python",
        ),
    ],
)
def test_a_malformed_answer_is_rejected_naming_the_fact(app, answer, subject, predicate, detail):
    with pytest.raises(SuggestionError) as err:
        parse_suggestion(_model(app), answer)
    assert (err.value.subject, err.value.predicate) == (subject, predicate)
    assert detail in err.value.detail


def test_an_id_the_payload_already_uses_is_rejected(app):
    model = _model(app)
    with pytest.raises(SuggestionError) as err:
        build_change(model, parse_suggestion(model, _answer(decision_id="amount")))
    assert err.value.predicate == "id"
    assert "'amount'" in err.value.detail


def test_mixed_output_types_are_rejected(app):
    model = _model(app)
    rules = [{"when": {"amount": "<= 2000"}, "then": '"approved"'}, {"then": "7"}]
    with pytest.raises(SuggestionError) as err:
        build_change(model, parse_suggestion(model, _answer(rules=rules)))
    assert (err.value.subject, err.value.predicate) == ("approval_outcome", "rules")


def test_a_change_that_breaks_a_condition_fails_the_check_and_names_the_flow(app):
    before = _snapshot(app)
    bpmn = app / "approval.bpmn"
    broken = bpmn.read_text(encoding="utf-8").replace("amount &lt;= 2000", "outcome == 1")
    verdicts = check_change(load_project(app), Change(Patch(), ((bpmn, broken),)))
    assert not verdicts.validated and not verdicts.passed
    assert [(f.kind, f.subject, f.predicate) for f in verdicts.findings] == [
        ("decision", f"{BPMN}flow_approved", "outcome")
    ]
    assert _snapshot(app) == before


def test_a_patch_the_writer_refuses_is_a_patch_finding(app):
    quad = (URIRef(f"{EX}nothing"), SEAM.reads, URIRef(f"{EX}ExpenseShape"), URIRef("urn:seams:graph:seams"))
    verdicts = check_change(load_project(app), Change(Patch(removes=[quad]), ()))
    assert (verdicts.validated, verdicts.generated) == (False, False)
    assert [(f.kind, f.subject, f.predicate) for f in verdicts.findings] == [("patch", f"{EX}nothing", str(SEAM.reads))]
