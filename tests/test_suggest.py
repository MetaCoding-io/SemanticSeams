"""``seams suggest`` (M025/S01, backlog R2, ADR-0028) with fake provider commands.

The fixture is the expense tutorial's chapter 10 with ``decision_gateway``
routing on the submitted amount inline, as in test_suggest_change.py. No
provider but the fakes in tests/fixtures/suggest runs, and no network.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main
from seams_cli.project import load_project
from seams_cli.suggest import (
    CACHE_DIR,
    SUGGESTION_FILE,
    SUGGESTIONS_DIR,
    build_prompt,
    pending,
    suggest,
)

from tests.workspace_copy import copy_workspace

ROOT = Path(__file__).resolve().parent.parent
CH10 = ROOT / "examples" / "expenses" / "chapter-10"
CH05 = ROOT / "examples" / "expenses" / "chapter-05"
FIXTURES = ROOT / "tests" / "fixtures" / "suggest"
GATEWAY = "https://example.org/expenses/approval_bpmn#decision_gateway"
INLINE = {"approved": "amount &lt;= 2000", "rejected": "amount &gt; 2000"}


def _provider(name: str, *args: str) -> str:
    return shlex.join([sys.executable, str(FIXTURES / name), *args])


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def app(tmp_path) -> Path:
    # At the depth chapter 10's seams.toml expects, so its gate query resolves.
    root = tmp_path / CH10.relative_to(ROOT)
    shutil.copytree(CH10, root, ignore=shutil.ignore_patterns("__pycache__"))
    copy_workspace(tmp_path)
    shutil.copytree(ROOT / "docs" / "queries" / "gates", tmp_path / "docs" / "queries" / "gates")
    bpmn = root / "approval.bpmn"
    text = bpmn.read_text(encoding="utf-8")
    for outcome, condition in INLINE.items():
        old = f'>decision == "{outcome}"<'
        assert old in text
        text = text.replace(old, f">{condition}<")
    bpmn.write_text(text, encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _value(lines: list[str], key: str) -> str:
    return next(line.split(" ", 1)[1] for line in lines if line.startswith(key + " "))


def test_the_prompt_offers_the_inline_gateway_in_data_blocks_byte_for_byte(app):
    prompt = build_prompt(load_project(app))
    assert prompt.template == "suggest-v1"
    assert prompt.gateways == (GATEWAY,)
    assert prompt.model_hash == seams.model_hash(app / "expenses.trig")
    text = prompt.text
    assert "```DATA gateway\ngateway: decision_gateway\n" in text
    assert "flow_approved -> " in text and ": amount <= 2000" in text
    assert "https://example.org/expenses/ExpenseShape amount number " in text
    # The existing decision, as its native DMN element, with its payload path.
    assert "```DATA decision\ndecision: https://example.org/expenses/approval_routing\n" in text
    assert 'payload: approval.dmn#approval_routing\n  <decision id="approval_routing" name="Route Approval">' in text
    # route_gateway reads the route decision's output: not offered.
    assert "gateway: route_gateway" not in text
    assert '"kind": "condition-to-dmn"' in text
    assert str(app) not in text
    assert build_prompt(load_project(app)).text == text


def test_suggest_then_accept_leaves_a_project_that_checks_and_generates(app, capsys):
    before = _snapshot(app)
    code = main(["suggest", "--project", str(app), "--provider", _provider("good_provider.py")])
    out = capsys.readouterr().out.splitlines()
    assert code == 0, out
    assert out[0] == "template suggest-v1"
    assert out[3] == "cache miss"
    ident = _value(out, "suggestion")
    assert _value(out, "gateway") == GATEWAY
    assert [line for line in out if line.startswith("changed ")] == [
        "changed approval.bpmn",
        "changed approval.dmn",
        "changed expenses.trig",
    ]
    assert "validated pass" in out
    assert any(line.startswith("generated pass (") for line in out)
    assert _value(out, "stored") == f"{SUGGESTIONS_DIR.as_posix()}/{ident}"

    # Pending, not applied: only .seams/ is new.
    after = _snapshot(app)
    assert {p: b for p, b in after.items() if p.parts[0] != ".seams"} == before
    stored = app / SUGGESTIONS_DIR / ident
    assert sorted(p.name for p in stored.iterdir()) == [
        "approval.bpmn.diff",
        "approval.dmn.diff",
        "expenses.trig.diff",
        SUGGESTION_FILE,
    ]
    record = json.loads((stored / SUGGESTION_FILE).read_text())
    assert (record["id"], record["kind"], record["gateway"]) == (ident, "condition-to-dmn", GATEWAY)
    assert record["model_hash"] == seams.model_hash(app / "expenses.trig")
    diff = (stored / "approval.bpmn.diff").read_text()
    assert diff.startswith("--- a/approval.bpmn\n+++ b/approval.bpmn\n")
    assert '+    <bpmn:businessRuleTask id="approval_outcome" name="Approval Outcome">' in diff
    assert str(app) not in diff + (stored / "expenses.trig.diff").read_text()

    assert main(["suggest", "--project", str(app), "--list"]) == 0
    assert capsys.readouterr().out == f"{ident} condition-to-dmn {GATEWAY} current\n"

    code = main(["suggest", "--project", str(app), "--accept", ident[:12]])
    out = capsys.readouterr().out.splitlines()
    assert code == 0, out
    assert out[-4:] == [f"accepted {ident}", "wrote approval.bpmn", "wrote approval.dmn", "wrote expenses.trig"]
    assert not stored.exists()
    model = seams.load(app / "expenses.trig")
    assert seams.decision_findings(model) == []
    gateway = next(n for p in model.processes for n in p.gateways() if n.bpmn_id == "decision_gateway")
    assert {f.id: f.condition for f in gateway.outgoing} == {
        "flow_approved": 'outcome == "approved"',
        "flow_rejected": 'outcome == "rejected"',
    }

    assert main(["generate", str(app)]) == 0
    capsys.readouterr()
    code = main(["check", str(app)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err


def test_a_bad_answer_is_rejected_naming_the_fact_and_writes_nothing(app, capsys):
    before = _snapshot(app)
    code = main(["suggest", "--project", str(app), "--provider", _provider("bad_provider.py")])
    captured = capsys.readouterr()
    assert code == 1
    assert "rejected suggestion no_such_gateway gateway no gateway of the model's processes" in captured.out
    assert "nothing stored or written" in captured.err
    assert not (app / ".seams").exists()
    assert _snapshot(app) == before


def test_a_cache_hit_does_not_call_the_provider(app, tmp_path):
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    first = suggest(load_project(app), None, provider)
    second = suggest(load_project(app), None, provider)
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert first.passed and second.passed
    assert first.id == second.id
    assert (tmp_path / "calls").read_text() == "1"
    assert len(list((app / CACHE_DIR).iterdir())) == 1
    assert [p.id for p in pending(load_project(app))] == [first.id]


def test_accept_is_refused_on_a_changed_model(app, capsys):
    result = suggest(load_project(app), None, _provider("good_provider.py"))
    assert result.passed
    trig = app / "expenses.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + "# edited after the suggestion\n", encoding="utf-8")
    before = _snapshot(app)

    assert main(["suggest", "--project", str(app), "--list"]) == 0
    assert capsys.readouterr().out == f"{result.id} condition-to-dmn {GATEWAY} stale\n"
    code = main(["suggest", "--project", str(app), "--accept", result.id])
    captured = capsys.readouterr()
    assert code == 1
    assert f"suggestion {result.id} was made for model {result.model_hash}" in captured.err
    assert "run seams suggest again" in captured.err
    assert _snapshot(app) == before


def test_provider_failure_is_reported_and_nothing_written(app, capsys):
    before = _snapshot(app)
    code = main(["suggest", "--project", str(app), "--provider", _provider("bad_provider.py", "--exit", "3")])
    captured = capsys.readouterr()
    assert code == 1
    assert "exited 3: quota exceeded" in captured.err
    assert _snapshot(app) == before


def test_an_unknown_id_and_a_missing_provider_are_project_errors(app, capsys):
    assert main(["suggest", "--project", str(app), "--accept", "0" * 64]) == 2
    assert "no pending suggestion matches" in capsys.readouterr().err
    assert main(["suggest", "--project", str(app)]) == 2
    assert "no provider" in capsys.readouterr().err


def test_a_model_without_an_inline_gateway_calls_no_provider(tmp_path, capsys):
    root = tmp_path / "chapter-05"
    shutil.copytree(CH05, root, ignore=shutil.ignore_patterns("__pycache__"))
    before = _snapshot(root)
    code = main(["suggest", "--project", str(root), "--provider", _provider("bad_provider.py", "--exit", "3")])
    assert code == 0
    assert "seams suggest: nothing to suggest:" in capsys.readouterr().err
    assert _snapshot(root) == before
