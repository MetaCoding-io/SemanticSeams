"""``seams observed [PATH] RUN... [--db PATH] [--spans FILE] [--json]`` (M032/S01, ADR-0042).

The command loads recorded runs (trace JSON files, store instances, OTLP span
files) as an as-observed graph and prints the dead-model and conformance
answers, sorted, exit 0. An unknown run exits 2 naming it; a run that is
malformed exits 2 naming the row; no run at all is a usage error."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main as seams_main

from seams_runtime.telemetry import element_attributes

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "examples" / "chat-app"
TRACE = ROOT / "tests" / "fixtures" / "traces" / "chat_send_message.json"
ROWS: list[dict[str, object]] = json.loads(TRACE.read_text(encoding="utf-8"))["trace"]
PROCESS = "https://example.org/chat/send_message_process"
BPMN = "https://example.org/chat/chat_bpmn#"


def _observed(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[str], str]:
    code = seams_main(["observed", *args])
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


def _trace(tmp_path: Path, name: str, rows: list[dict[str, object]], instance: str | None = None) -> Path:
    path = tmp_path / name
    data: dict[str, object] = {"trace": rows}
    if instance is not None:
        data["instance"] = instance
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _store(tmp_path: Path, instance: str, rows: list[dict[str, object]]) -> Path:
    """A SQLite store with the runtime's workflow_state table holding one checkpoint."""
    db = tmp_path / "seams.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE workflow_state (instance_id TEXT PRIMARY KEY, state TEXT)")
        con.execute(
            "INSERT INTO workflow_state VALUES (?, ?)", (instance, json.dumps({"data": {"seams": {"trace": rows}}}))
        )
    return db


def _spans(tmp_path: Path, rows: list[dict[str, object]], instance: str) -> Path:
    def attrs(values: dict[str, object]) -> list[dict[str, object]]:
        return [{"key": k, "value": {"stringValue": str(v)}} for k, v in values.items()]

    run = {"seams.process.iri": PROCESS, "seams.instance.id": instance}
    spans = [
        {
            "spanId": f"s{i:02d}",
            "startTimeUnixNano": str(100 + i),
            "attributes": attrs({**run, **element_attributes(r)}),
        }
        for i, r in enumerate(rows)
    ]
    path = tmp_path / "spans.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}), encoding="utf-8")
    return path


def test_a_full_run_leaves_nothing_dead_and_nothing_unexplained(capsys: pytest.CaptureFixture[str]) -> None:
    code, lines, err = _observed(capsys, str(CHAT_DIR), str(TRACE))
    assert code == 0, err
    assert lines == []
    assert err == "seams observed: 1 run(s), 7 step(s): 0 unreached node(s), 0 unexplained step(s)\n"


def test_sections_list_unreached_nodes_then_unknown_steps_sorted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _trace(tmp_path, "partial.json", [*ROWS[:3], {"task": "ghost", "iri": f"{BPMN}ghost"}, {"task": "x"}], "p")
    code, lines, _ = _observed(capsys, str(CHAT_DIR), str(run))
    assert code == 0
    reached = {str(r["iri"]) for r in ROWS[:3]}
    dead = sorted(f"dead-model {r['iri']} {PROCESS}" for r in ROWS if str(r["iri"]) not in reached)
    assert lines == [*dead, f"conformance p 3 unknown-element {BPMN}ghost", "conformance p 4 unmapped -"]


def test_a_run_reached_by_one_trace_is_not_dead_for_the_other(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _trace(tmp_path, "a.json", ROWS[:3], "a")
    second = _trace(tmp_path, "b.json", ROWS[3:], "b")
    code, lines, err = _observed(capsys, str(CHAT_DIR), str(second), str(first))
    assert code == 0
    assert lines == []
    assert "2 run(s), 7 step(s)" in err


def test_a_trace_file_without_instance_is_named_by_its_argument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _trace(tmp_path, "bare.json", [{"task": "ghost", "iri": f"{BPMN}ghost"}, *ROWS])
    code, lines, _ = _observed(capsys, str(CHAT_DIR), "bare.json")
    assert code == 0
    assert lines == [f"conformance bare.json 0 unknown-element {BPMN}ghost"]


def test_instance_ids_are_read_from_the_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _store(tmp_path, "inst-7", ROWS[:6])
    code, lines, _ = _observed(capsys, str(CHAT_DIR), "inst-7", "--db", str(db))
    assert code == 0
    assert lines == [f"dead-model {ROWS[6]['iri']} {PROCESS}"]


def test_seams_db_names_the_default_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEAMS_DB", str(_store(tmp_path, "inst-8", ROWS)))
    code, lines, _ = _observed(capsys, str(CHAT_DIR), "inst-8")
    assert (code, lines) == (0, [])


def test_spans_files_load_as_runs_with_their_process(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spans = _spans(tmp_path, ROWS[:6], "span-run")
    code, lines, err = _observed(capsys, str(CHAT_DIR), "--spans", str(spans))
    assert code == 0, err
    assert lines == [f"dead-model {ROWS[6]['iri']} {PROCESS}"]


def test_the_model_path_is_accepted_and_json_is_sorted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _trace(tmp_path, "partial.json", [*ROWS[:6], {"task": "x"}], "p")
    code, lines, _ = _observed(capsys, str(CHAT_DIR / "chat-app.trig"), str(run), "--json")
    assert code == 0
    data = json.loads("\n".join(lines))
    assert data["graph"].startswith("urn:seams:observed:")
    assert (data["runs"], data["steps"]) == (1, 7)
    assert data["dead-model"] == [{"node": str(ROWS[6]["iri"]), "process": PROCESS}]
    assert data["conformance"] == [
        {"index": "6", "reason": "unmapped", "run": "p", "step": "urn:seams:observed:run:p:step:6"}
    ]
    again = _observed(capsys, str(CHAT_DIR / "chat-app.trig"), str(run), "--json")[1]
    assert again == lines


def test_the_model_hash_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = seams.load(CHAT_DIR / "chat-app.trig").hash
    assert _observed(capsys, str(CHAT_DIR), str(TRACE))[0] == 0
    assert seams.load(CHAT_DIR / "chat-app.trig").hash == before


def test_an_unknown_instance_exits_2_naming_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _store(tmp_path, "inst-7", ROWS)
    code, lines, err = _observed(capsys, str(CHAT_DIR), "no-such-run", "--db", str(db))
    assert (code, lines) == (2, [])
    assert err.startswith("seams observed: no-such-run: trace: no workflow_state row for instance no-such-run")


def test_a_missing_store_exits_2_naming_the_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _observed(capsys, str(CHAT_DIR), "ghost-run", "--db", str(tmp_path / "none.sqlite"))
    assert code == 2
    assert "ghost-run" in err and "no SQLite store" in err


def test_a_malformed_row_exits_2_naming_the_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _trace(tmp_path, "bad.json", [ROWS[0], {"task": "x", "iri": "not an iri"}], "bad")
    code, lines, err = _observed(capsys, str(CHAT_DIR), str(run))
    assert (code, lines) == (2, [])
    assert "run bad row 1" in err and "iri" in err


def test_a_trace_file_that_is_not_json_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, _, err = _observed(capsys, str(CHAT_DIR), str(bad))
    assert code == 2
    assert str(bad) in err


def test_a_span_file_that_is_not_otlp_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "spans.json"
    bad.write_text('{"spans": []}', encoding="utf-8")
    code, _, err = _observed(capsys, str(CHAT_DIR), "--spans", str(bad))
    assert code == 2
    assert "resourceSpans" in err


def test_a_missing_span_file_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _observed(capsys, str(CHAT_DIR), "--spans", str(tmp_path / "absent.json"))
    assert code == 1
    assert "absent.json" in err


def test_a_run_given_twice_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _observed(capsys, str(CHAT_DIR), str(TRACE), str(TRACE))
    assert code == 2
    assert "given twice" in err


def test_no_run_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        seams_main(["observed", str(CHAT_DIR)])
    assert exc.value.code == 2
    assert "give at least one RUN or --spans FILE" in capsys.readouterr().err


def test_path_and_project_together_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        seams_main(["observed", str(CHAT_DIR), str(TRACE), "--project", str(CHAT_DIR)])
    assert exc.value.code == 2
    assert "give PATH or --project, not both" in capsys.readouterr().err
