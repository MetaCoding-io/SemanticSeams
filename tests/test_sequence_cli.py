"""The sequence deriver's two command lines (M013/S02, D047):
``python -m seams_gen.sequence <trig> <event> --out DIR`` and
``seams sequence <event> [--project] [--model] [--out DIR]``. Both write the
golden bytes, report gaps on stderr with exit 0, and exit 2 for an unknown
event or an unloadable model. With ``--trace`` (M013/S04) both write the
as-executed golden from a recorded run's trace rows."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from seams_cli.__main__ import main as seams_main

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "examples" / "chat-app"
CHAPTER_08 = ROOT / "examples" / "expenses" / "chapter-08"
GOLDENS = ROOT / "docs" / "generation" / "sequences"
TRACE = ROOT / "tests" / "fixtures" / "traces" / "chat_send_message.json"
EXECUTED_GOLDEN = GOLDENS / "chat-app" / "send_message.executed.mmd"
EXPENSE_NAMES = [
    "submit_expense--auto.mmd",
    "submit_expense--manager--approved.mmd",
    "submit_expense--manager--rejected.mmd",
    "submit_expense--finance--approved.mmd",
    "submit_expense--finance--rejected.mmd",
]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "seams_gen.sequence", *args], cwd=ROOT, capture_output=True, text=True)


def _no_stored_in(tmp_path: Path) -> Path:
    """A copy of the chat app whose MessageShape has no seam:storedIn."""
    text = (CHAT_DIR / "chat-app.trig").read_text(encoding="utf-8")
    old = "    :MessageShape seam:storedIn :message_db .\n"
    assert old in text
    model = tmp_path / "model" / "chat-app.trig"
    model.parent.mkdir()
    model.write_text(text.replace(old, ""), encoding="utf-8")
    for payload in ("chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_DIR / payload, model.parent / payload)
    return model


def test_module_writes_the_chat_golden(tmp_path):
    out = tmp_path / "out"
    result = _run("examples/chat-app/chat-app.trig", ":send_message", "--out", str(out))
    assert result.returncode == 0, result.stderr
    written = out / "send_message.mmd"
    assert written.read_bytes() == (GOLDENS / "chat-app" / "send_message.mmd").read_bytes()
    assert result.stdout.splitlines() == [str(written)]
    assert result.stderr == ""


def test_module_writes_one_file_per_expense_path(tmp_path):
    result = _run(str(CHAPTER_08 / "expenses.trig"), ":submit_expense", "--out", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(EXPENSE_NAMES)
    for name in EXPENSE_NAMES:
        assert (tmp_path / name).read_bytes() == (GOLDENS / "expenses" / name).read_bytes(), name
    assert result.stdout.splitlines() == [str(tmp_path / n) for n in EXPENSE_NAMES]


def test_module_unknown_event_exits_2(tmp_path):
    result = _run("examples/chat-app/chat-app.trig", ":no_such_event", "--out", str(tmp_path / "out"))
    assert result.returncode == 2
    assert result.stderr.startswith("python -m seams_gen.sequence: ")
    assert ":no_such_event" in result.stderr
    assert not (tmp_path / "out").exists()


def test_module_missing_or_unparsable_model_exits_2(tmp_path):
    missing = _run(str(tmp_path / "absent.trig"), ":send_message", "--out", str(tmp_path / "out"))
    assert missing.returncode == 2
    assert "no such model file" in missing.stderr
    broken = tmp_path / "broken.trig"
    broken.write_text("this is not { TriG", encoding="utf-8")
    bad = _run(str(broken), ":send_message", "--out", str(tmp_path / "out"))
    assert bad.returncode == 2
    assert bad.stderr.startswith("python -m seams_gen.sequence: ")


def test_module_unwritable_out_exits_1(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    result = _run("examples/chat-app/chat-app.trig", ":send_message", "--out", str(blocker / "out"))
    assert result.returncode == 1
    assert result.stderr.startswith("python -m seams_gen.sequence: ")


def test_module_gaps_go_to_stderr_and_exit_0(tmp_path):
    model = _no_stored_in(tmp_path)
    result = _run(str(model), ":send_message", "--out", str(tmp_path / "out"))
    assert result.returncode == 0, result.stderr
    assert (
        "gap send_message: MessageShape written by persist_user_msg has no seam:storedIn" in result.stderr.splitlines()
    )
    assert "%% gap: MessageShape written by persist_user_msg has no seam:storedIn" in (
        tmp_path / "out" / "send_message.mmd"
    ).read_text(encoding="utf-8")


def test_seams_sequence_writes_the_chat_golden(tmp_path, capsys):
    code = seams_main(["sequence", ":send_message", "--project", str(CHAT_DIR), "--out", str(tmp_path)])
    assert code == 0
    written = tmp_path / "send_message.mmd"
    assert written.read_bytes() == (GOLDENS / "chat-app" / "send_message.mmd").read_bytes()
    out, err = capsys.readouterr()
    assert out.splitlines() == [str(written.resolve())]
    assert err == ""


def test_seams_sequence_defaults_out_to_project_sequences(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "seams.toml").write_text(f'model = "{CHAT_DIR / "chat-app.trig"}"\n', encoding="utf-8")
    assert seams_main(["sequence", "send_message", "--project", str(project)]) == 0
    assert (project / "sequences" / "send_message.mmd").read_bytes() == (
        GOLDENS / "chat-app" / "send_message.mmd"
    ).read_bytes()


def test_seams_sequence_model_override_reports_gaps(tmp_path, capsys):
    model = _no_stored_in(tmp_path)
    code = seams_main(
        ["sequence", ":send_message", "--project", str(CHAT_DIR), "--model", str(model), "--out", str(tmp_path / "o")]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert (
        "seams sequence: gap send_message: MessageShape written by persist_response has no seam:storedIn"
        in err.splitlines()
    )


def test_seams_sequence_unknown_event_exits_2(tmp_path, capsys):
    code = seams_main(["sequence", ":no_such_event", "--project", str(CHAT_DIR), "--out", str(tmp_path / "o")])
    assert code == 2
    err = capsys.readouterr().err
    assert err.startswith("seams sequence: ")
    assert ":no_such_event" in err
    assert not (tmp_path / "o").exists()


def test_seams_sequence_unloadable_model_exits_2(tmp_path, capsys):
    broken = tmp_path / "broken.trig"
    broken.write_text("this is not { TriG", encoding="utf-8")
    code = seams_main(["sequence", ":send_message", "--project", str(CHAT_DIR), "--model", str(broken)])
    assert code == 2
    assert "cannot load the model" in capsys.readouterr().err


def _empty_store(tmp_path: Path) -> Path:
    """A SQLite store with the runtime's workflow_state table and no rows."""
    db = tmp_path / "seams.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE workflow_state (instance_id TEXT PRIMARY KEY, state TEXT)")
    return db


def test_module_trace_writes_the_executed_golden(tmp_path):
    out = tmp_path / "out"
    result = _run("examples/chat-app/chat-app.trig", ":send_message", "--out", str(out), "--trace", str(TRACE))
    assert result.returncode == 0, result.stderr
    written = out / "send_message.executed.mmd"
    assert written.read_bytes() == EXECUTED_GOLDEN.read_bytes()
    assert result.stdout.splitlines() == [str(written)]
    assert result.stderr == ""


def test_module_trace_unknown_instance_exits_2(tmp_path):
    db = _empty_store(tmp_path)
    result = _run(
        "examples/chat-app/chat-app.trig",
        ":send_message",
        "--out",
        str(tmp_path / "out"),
        "--trace",
        "no-such-run",
        "--db",
        str(db),
    )
    assert result.returncode == 2
    assert result.stderr.startswith("python -m seams_gen.sequence: ")
    assert "no-such-run" in result.stderr
    assert not (tmp_path / "out").exists()


def test_module_malformed_trace_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = _run("examples/chat-app/chat-app.trig", ":send_message", "--out", str(tmp_path / "o"), "--trace", str(bad))
    assert result.returncode == 2
    assert str(bad) in result.stderr


def test_module_db_without_trace_is_a_usage_error(tmp_path):
    result = _run("examples/chat-app/chat-app.trig", ":send_message", "--out", str(tmp_path), "--db", "x.sqlite")
    assert result.returncode == 2
    assert "--db needs --trace" in result.stderr


def test_seams_sequence_trace_writes_the_executed_golden(tmp_path, capsys):
    code = seams_main(
        ["sequence", ":send_message", "--project", str(CHAT_DIR), "--out", str(tmp_path), "--trace", str(TRACE)]
    )
    assert code == 0
    written = tmp_path / "send_message.executed.mmd"
    assert written.read_bytes() == EXECUTED_GOLDEN.read_bytes()
    out, err = capsys.readouterr()
    assert out.splitlines() == [str(written.resolve())]
    assert err == ""


def test_seams_sequence_trace_unknown_instance_exits_2(tmp_path, capsys):
    db = _empty_store(tmp_path)
    code = seams_main(
        [
            "sequence",
            ":send_message",
            "--project",
            str(CHAT_DIR),
            "--out",
            str(tmp_path / "o"),
            "--trace",
            "no-such-run",
            "--db",
            str(db),
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert err.startswith("seams sequence: ")
    assert "no-such-run" in err
    assert not (tmp_path / "o").exists()


def test_seams_sequence_db_defaults_to_seams_db(tmp_path, capsys, monkeypatch):
    db = _empty_store(tmp_path)
    monkeypatch.setenv("SEAMS_DB", str(db))
    code = seams_main(["sequence", ":send_message", "--project", str(CHAT_DIR), "--trace", "run-x"])
    assert code == 2
    assert str(db) in capsys.readouterr().err


def test_seams_sequence_db_without_trace_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        seams_main(["sequence", ":send_message", "--project", str(CHAT_DIR), "--db", "x.sqlite"])
    assert exc.value.code == 2
    assert "--db needs --trace" in capsys.readouterr().err
