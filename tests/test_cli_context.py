"""``seams context`` (M022/S01, backlog C3): the context manifest of a service task as a
review report; exit 0 with the manifest, 1 on an unknown task or a missing hop.

Run on Send Now in the expense tutorial's chapter 9, the same task
tests/test_context_assembly.py pins the items of.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
CH09 = ROOT / "examples" / "expenses" / "chapter-09"
SEND_NOW = "https://example.org/expenses/payout_bpmn#send_now"


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(["context", *argv, "--project", str(CH09)])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture(scope="module")
def manifest() -> seams.Manifest:
    return seams.context_for(seams.load(CH09 / "expenses.trig"), "send_now")


def test_json_report_matches_context_for(capsys, manifest):
    code, out, err = _run(capsys, "send_now", "--json")
    assert (code, err) == (0, "")
    report = json.loads(out)
    assert sorted(report) == ["context_hash", "items", "task"]
    assert report["task"] == SEND_NOW
    assert report["context_hash"] == manifest.context_hash
    assert report["items"] == [{"kind": i.kind, "ref": i.ref, "hash": i.hash} for i in manifest.items]


def test_text_report_lists_task_items_and_context_hash(capsys, manifest):
    code, out, err = _run(capsys, SEND_NOW)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == f"task {SEND_NOW}"
    assert lines[1:-1] == [f"{i.kind} {i.ref} {i.hash}" for i in manifest.items]
    assert lines[-1] == f"context {manifest.context_hash}"


@pytest.mark.parametrize("fmt", [(), ("--json",)])
def test_two_runs_give_identical_bytes_without_absolute_paths(capsys, fmt):
    first = _run(capsys, "send_now", *fmt)
    second = _run(capsys, "send_now", *fmt)
    assert first == second
    assert str(ROOT) not in first[1]


def test_model_override_elsewhere_gives_the_same_context_hash(capsys, manifest, tmp_path):
    copy = tmp_path / "ch09"
    shutil.copytree(CH09, copy, ignore=shutil.ignore_patterns("generated", "handlers"))
    code, out, err = _run(capsys, "send_now", "--model", str(copy / "expenses.trig"), "--json")
    assert (code, err) == (0, "")
    assert json.loads(out)["context_hash"] == manifest.context_hash
    assert str(tmp_path) not in out


@pytest.mark.parametrize("task", ["no_such_task", "https://example.org/expenses/payout_bpmn#method_gateway"])
def test_unknown_or_non_service_task_exits_1(capsys, task):
    code, out, err = _run(capsys, task)
    assert code == 1
    assert out == ""
    assert err.startswith("seams context: ")


def test_unloadable_model_exits_2(capsys, tmp_path):
    bad = tmp_path / "bad.trig"
    bad.write_text("this is not trig", encoding="utf-8")
    code = main(["context", "send_now", "--model", str(bad), "--project", str(CH09)])
    _, err = capsys.readouterr()
    assert code == 2
    assert "cannot load the model" in err
