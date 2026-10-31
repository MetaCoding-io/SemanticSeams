"""The as-executed sequence renderer (backlog U4, M013/S04): seams_gen.sequence
``executed`` draws a recorded run from the worker's trace rows on the same
lifelines as the as-designed ``derive``, and ``read_trace`` reads those rows
from a JSON file or the runtime's SQLite store. The chat send_message golden
is pinned from a captured fixture and from a live run with a mocked LLM; an
unknown element or channel is a gap, an error row a note, and an expenses
user task completed by a person draws that identity as an actor."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import seams

from seams_gen import GeneratorError
from seams_gen.sequence import derive, executed, file_name, read_trace, render

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_runtime_worker import PROCESS, SHORT, TRIG, FakeLLM  # noqa: E402

from seams_runtime import Runtime  # noqa: E402
from seams_runtime.store import SQLiteStore  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "traces" / "chat_send_message.json"
GOLDEN = ROOT / "docs" / "generation" / "sequences" / "chat-app" / "send_message.executed.mmd"
EXPENSES = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
EX = "https://example.org/expenses/"
EXB = EX + "approval_bpmn#"
CHAT = "https://example.org/chat/"


@pytest.fixture(scope="module")
def chat_model():
    return seams.load(TRIG)


def _live_run(db: Path) -> dict:
    rt = Runtime.load(
        TRIG, store=SQLiteStore(db), llm_transport=FakeLLM().transport, llm_base_url="http://llm-gateway.test"
    )

    async def main():
        inst = await rt.start_process(PROCESS, SHORT, correlation_key="c1")
        return await inst.wait()

    result = asyncio.run(main())
    assert result["status"] == "complete", result["error"]
    return result


def _golden() -> str:
    return GOLDEN.read_bytes().decode("utf-8")


# ── the chat golden ──────────────────────────────────────────────────────────


def test_fixture_renders_the_golden(chat_model):
    run, rows = read_trace(FIXTURE)
    assert run == "run-1"
    d = executed(chat_model, ":send_message", rows, run=run)
    assert d.name == "send_message.executed" and file_name(d) == "send_message.executed.mmd"
    assert d.path == tuple(r["task"] for r in rows)
    assert d.gaps == ()
    assert render(d) == _golden()


def test_live_run_renders_the_same_golden(chat_model, tmp_path):
    result = _live_run(tmp_path / "seams.sqlite")
    text = render(executed(chat_model, ":send_message", result["trace"]))
    # run=None: no %% run line; the rest is byte-for-byte the golden
    assert "%% run:" not in text
    assert text == _golden().replace("    %% run: run-1\n", "")


def test_same_lifelines_as_designed(chat_model):
    (designed,) = derive(chat_model, ":send_message")
    d = executed(chat_model, ":send_message", read_trace(FIXTURE)[1])
    assert [p.iri for p in d.participants] == [p.iri for p in designed.participants]
    assert render(d).splitlines()[1] == "    %% executed from https://example.org/chat/send_message"


# ── read_trace ───────────────────────────────────────────────────────────────


def test_read_trace_bare_list(tmp_path):
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["trace"]
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert read_trace(path) == (None, rows)


def test_read_trace_sqlite_store(tmp_path, monkeypatch):
    db = tmp_path / "seams.sqlite"
    result = _live_run(db)
    assert read_trace(result["instance"], db) == (result["instance"], result["trace"])
    monkeypatch.setenv("SEAMS_DB", str(db))
    assert read_trace(result["instance"]) == (result["instance"], result["trace"])


def test_read_trace_unknown_instance(tmp_path):
    db = tmp_path / "seams.sqlite"
    SQLiteStore(db)  # an empty store with the runtime's schema
    with pytest.raises(GeneratorError) as err:
        read_trace("no-such-run", db)
    assert "no-such-run" in str(err.value) and str(db) in str(err.value)


def test_read_trace_missing_store(tmp_path):
    db = tmp_path / "absent.sqlite"
    with pytest.raises(GeneratorError) as err:
        read_trace("run-x", db)
    assert "run-x" in str(err.value) and str(db) in str(err.value)
    assert not db.exists()  # reading never creates a store


@pytest.mark.parametrize("text", ["{not json", '{"instance": "r"}', "42", '["row"]'])
def test_read_trace_malformed_json(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(GeneratorError) as err:
        read_trace(path)
    assert str(path) in str(err.value)


# ── gaps and error rows ──────────────────────────────────────────────────────


def test_unknown_iri_is_a_gap_and_no_row_is_dropped(chat_model):
    rows = read_trace(FIXTURE)[1]
    rows.insert(2, {"task": "ghost", "iri": CHAT + "chat_bpmn#ghost", "fires": CHAT + "t_send", "status": "x"})
    rows.insert(3, {"task": "orphan"})
    rows.insert(4, {"task": "loud", "iri": CHAT + "chat_bpmn#start", "published": {"channel": CHAT + "nope"}})
    d = executed(chat_model, ":send_message", rows)
    text = render(d)
    assert "    %% gap: row 3 ghost: https://example.org/chat/chat_bpmn#ghost is not an element of " in text
    assert "    %% gap: row 4 orphan has no iri\n" in text
    assert "    %% gap: row 5 loud: channel https://example.org/chat/nope is not a comm:Channel\n" in text
    assert len(d.gaps) == 3
    # the unknown element's own facts are still drawn, and every golden line survives
    assert "Note over chat_api: t_send → x" in text
    golden = [line for line in _golden().splitlines() if "%% " not in line]
    assert [line for line in text.splitlines() if line in golden] == golden
    assert d.path[2:5] == ("ghost", "orphan", "loud")


def test_unknown_container_is_a_gap(chat_model):
    rows = read_trace(FIXTURE)[1]
    invoke = next(r for r in rows if r["task"] == "invoke_llm")
    invoke["container"] = CHAT + "nowhere"
    d = executed(chat_model, ":send_message", rows)
    assert d.gaps == ("row 4 invoke_llm: container https://example.org/chat/nowhere is not an arch:Container",)
    assert "llm_gateway" not in render(d)


def test_error_row_is_a_note(chat_model):
    rows = read_trace(FIXTURE)[1][:4]
    rows.append({"task": None, "fires": CHAT + "t_fail", "status": "failed", "error": "ResolutionError"})
    d = executed(chat_model, ":send_message", rows)
    assert d.gaps == ()
    assert d.path[-1] == "error"
    assert render(d).splitlines()[-1] == "    Note over chat_api: error ResolutionError, t_fail → failed"


# ── a person completing a user task (expenses chapter 8) ─────────────────────


def test_expense_by_actor_and_decision():
    rows = [
        {"task": "start", "iri": EXB + "start"},
        {
            "task": "persist_expense",
            "iri": EXB + "persist_expense",
            "fires": EX + "t_submit",
            "writes": ["e1"],
            "status": "submitted",
        },
        {
            "task": "route_expense",
            "iri": EXB + "route_expense",
            "decision": EX + "approval_routing",
            "outputs": {"route": "manager"},
        },
        {"task": "approve_expense", "iri": EXB + "approve_expense", "by": "manager", "writes": ["a1"]},
        {
            "task": "pay_expense",
            "iri": EXB + "pay_expense",
            "by": "finance",
            "fires": EX + "t_pay",
            "status": "paid",
            "writes": ["p1"],
            "started": [{"process": EX + "payout_process", "instance": "i2"}],
        },
    ]
    d = executed(seams.load(EXPENSES), ":submit_expense", rows, run="exp-1")
    lines = render(d).splitlines()
    assert d.gaps == ()
    assert "    %% run: exp-1" in lines
    assert "    actor by_manager as manager" in lines
    assert "    actor by_finance as finance" in lines
    assert "    expense_api->>expense_api: route_expense (DMN approval_routing) = manager" in lines
    i = lines.index("    by_manager->>employee_portal: approve_expense on approve_form")
    assert lines[i + 1] == "    employee_portal->>expense_api: complete approve_expense"
    assert lines[i + 2] == "    expense_api->>expense_db: approve_expense writes ApprovalShape"
    assert "    by_finance->>employee_portal: pay_expense on payment_form" in lines
    assert "    Note over expense_api: t_pay → paid" in lines
    assert "    expense_api->>expense_api: start payout_process" in lines
