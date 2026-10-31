"""``seams coverage`` (M015/S04, D054): unexercised BPMN paths, unfired transitions and
permissions without a deny test, by IRI; exit 0 with no gap, 1 with gaps, 2 on a load error.

The chat app has a gap of each kind; expenses chapter 9 only has unexercised paths
(tests/test_seams_coverage.py pins which); chapter 1 has no process, lifecycle or policy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main
from seams_cli.coverage import coverage_report

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples" / "chat-app"
CH01 = ROOT / "examples" / "expenses" / "chapter-01"
CH09 = ROOT / "examples" / "expenses" / "chapter-09"
C = "https://example.org/chat/"
E = "https://example.org/expenses/"


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _run(capsys, *argv: str) -> tuple[int, list[str], str]:
    code = main(["coverage", *argv])
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_chat_app_names_every_gap_by_iri(capsys):
    code, lines, err = _run(capsys, "--project", str(CHAT))
    assert code == 1
    assert lines == [
        "path "
        + " ".join(
            [C + "send_message_process"]
            + [
                C + "chat_bpmn#" + n
                for n in (
                    "start",
                    "persist_user_msg",
                    "route_to_provider",
                    "invoke_llm",
                    "persist_response",
                    "stream_complete_event",
                    "end",
                )
            ]
        ),
        f"transition {C}message_lifecycle {C}t_fail_send",
        f"transition {C}message_lifecycle {C}t_fail_stream",
        f"policy {C}user_send_policy {C}send_message_op {C}authenticated_user",
    ]
    assert err == (
        "seams coverage: 1 unexercised path(s), 2 unfired transition(s), 1 permission(s) without a deny test\n"
    )


def test_chapter_9_has_only_path_gaps(capsys):
    code, lines, err = _run(capsys, str(CH09 / "expenses.trig"))
    assert code == 1
    assert [line.split()[0] for line in lines] == ["path"] * 6
    assert lines[0].split()[:2] == ["path", E + "approval_process"]
    assert lines[0].endswith(E + "approval_bpmn#rejected_end")
    assert lines[-1].split()[1] == E + "payout_process"
    assert "6 unexercised path(s), 0 unfired transition(s), 0 permission(s)" in err


def test_model_argument_and_project_agree(capsys):
    by_project = _run(capsys, "--project", str(CH09))
    by_model = _run(capsys, str(CH09))
    assert by_project == by_model


def test_json_lists_and_counts(capsys):
    code, lines, _err = _run(capsys, str(CHAT / "chat-app.trig"), "--json")
    report = json.loads("\n".join(lines))
    assert code == 1
    assert report["counts"] == {"paths": 1, "transitions": 2, "policies": 1}
    (path,) = report["paths"]
    assert path["process"] == C + "send_message_process"
    assert path["nodes"][0] == C + "chat_bpmn#start" and path["end"] == path["nodes"][-1] == C + "chat_bpmn#end"
    assert report["transitions"] == [
        {"lifecycle": C + "message_lifecycle", "transition": C + "t_fail_send"},
        {"lifecycle": C + "message_lifecycle", "transition": C + "t_fail_stream"},
    ]
    assert report["policies"] == [
        {"policy": C + "user_send_policy", "target": C + "send_message_op", "assignee": C + "authenticated_user"}
    ]


def test_nothing_uncovered_exits_0(capsys):
    assert _run(capsys, str(CH01)) == (0, [], "")
    assert json.loads("".join(_run(capsys, str(CH01), "--json")[1]))["counts"] == {
        "paths": 0,
        "transitions": 0,
        "policies": 0,
    }


def test_report_is_deterministic():
    model = seams.load(CHAT / "chat-app.trig")
    assert coverage_report(model) == coverage_report(seams.load(CHAT / "chat-app.trig"))


def test_an_unloadable_model_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.trig"
    bad.write_text("this is not trig {", encoding="utf-8")
    code, lines, err = _run(capsys, str(bad))
    assert (code, lines) == (2, [])
    assert err.startswith("seams coverage: ") and "cannot load the model" in err


def test_a_missing_project_exits_2(tmp_path, capsys):
    code, lines, err = _run(capsys, "--project", str(tmp_path))
    assert (code, lines) == (2, [])
    assert "no such project file" in err


def test_a_project_without_a_model_exits_2(tmp_path, capsys):
    (tmp_path / "seams.toml").write_text("", encoding="utf-8")
    code, _lines, err = _run(capsys, "--project", str(tmp_path))
    assert code == 2 and "no model" in err
