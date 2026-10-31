"""Expense tutorial chapter 9: hand-written code behind a service task (M014/S03).

examples/expenses/chapter-09/ puts a ``notify_manager`` service task on the
manager's path. It seam:invokes :notify_manager_op, which is
seam:implementedBy a comm:PythonHandler whose comm:handler
"notify.notify_manager" names the function in the chapter's handlers/
package (ADR-0012). The runtime calls it in-process with the expense,
validates its dict against :NotificationShape, and the task's seam:writes
stores it. No UI event submits to the operation, so the route module gives
it no route. The handlers package is owned code: ``seams generate`` never
writes it, and the stub generator, run again, writes nothing.
"""

import shutil
from pathlib import Path

import pytest
from expense_app import ROOT, assert_generated_current, chapter_dir, serve, status, trace, until
from seams_cli.__main__ import main as seams_main

from seams_gen import extract_routes
from seams_gen.stubs import generate_stubs
from seams_gen.stubs import main as stubs_main
from seams_runtime import ModelGraph

CHAPTER = "chapter-09"
EX = "https://example.org/expenses/"
NOTIFY_OP = EX + "notify_manager_op"
NOTIFICATION = EX + "NotificationShape"
EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
ALICE = {"X-Forwarded-User": "alice", "X-Forwarded-Groups": "employee"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMS_HANDLERS", raising=False)  # the default: handlers/ beside the model
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def _submit(c, runtime, key, amount):
    r = c.post(f"/expenses/{key}", data={**EXPENSE, "amount": amount}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, key) in ("waiting", "complete", "failed"))
    assert status(runtime, key) == "waiting", trace(runtime, key)


def _handler_files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((directory / "handlers").glob("*.py"))}


# ── generated code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("generator", ["fastapi", "htmx"])
def test_committed_generated_code_is_current(generator, tmp_path):
    assert_generated_current(CHAPTER, tmp_path, generator)


def test_the_invoked_only_operation_gets_no_route():
    """:expense_api exposes :notify_manager_op, but only a task invokes it, so
    the module lists it as not routed; :submit_expense_op is invoked too but
    an event submits to it, so it keeps its route."""
    (module,) = extract_routes(ModelGraph.load(chapter_dir(CHAPTER) / "expenses.trig")).modules
    assert module.invoked_only == (":notify_manager_op",)
    assert ":notify_manager_op" in module.exposes
    curies = {e.curie for e in module.endpoints}
    assert ":notify_manager_op" not in curies
    assert ":submit_expense_op" in curies
    text = (chapter_dir(CHAPTER) / "generated" / "expense_api.py").read_text(encoding="utf-8")
    assert "# :notify_manager_op is not routed:" in text
    assert "def notify_manager" not in text


def test_no_http_route_reaches_the_handler(app):
    c, _ = app
    assert not any("notification" in path for path in c.get("/openapi.json").json()["paths"])


# ── the hand-written handler at run time ─────────────────────────────────────


def test_the_notify_step_runs_the_python_handler_and_stores_its_notification(app):
    c, runtime = app
    _submit(c, runtime, "e1", "250.00")  # up to 1000 routes to the manager
    rows = {r["task"]: r for r in trace(runtime, "e1")}
    notify = rows["notify_manager"]
    assert notify["invokes"] == NOTIFY_OP
    assert notify["in_process"] is True
    assert notify["implementation"] == "PythonHandler"
    assert notify["handler"] == "notify.notify_manager"
    [entity_id] = notify["writes"]
    stored = runtime.store.get_entity(entity_id)
    assert stored["shape"] == NOTIFICATION
    assert stored["correlation_key"] == "e1"
    assert stored["data"] == {
        "recipient": "manager",
        "message": "Train to Leeds (250.00, 2026-10-01) is waiting for your approval.",
    }
    # the step fires nothing: the expense still waits, submitted, for the manager
    assert "fires" not in notify
    [expense] = runtime.query(":ExpenseShape", expense="e1")
    assert expense["status"] == "submitted"


@pytest.mark.parametrize(("amount", "route"), [("50.00", "auto"), ("5000.00", "finance")])
def test_other_routes_do_not_notify_the_manager(app, amount, route):
    c, runtime = app
    r = c.post(f"/expenses/k-{route}", data={**EXPENSE, "amount": amount}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, f"k-{route}") in ("waiting", "complete", "failed"))
    tasks = [row["task"] for row in trace(runtime, f"k-{route}")]
    assert "route_expense" in tasks and "notify_manager" not in tasks
    assert runtime.query(":NotificationShape") == []


def test_a_handler_fault_fails_the_instance_naming_the_operation(app, monkeypatch):
    """A handler that raises is a run-time fault, not a model fault: the
    instance fails and its error names the operation and the kind."""
    c, runtime = app
    impl = runtime.implementations
    op = next(k for k in impl if str(k) == NOTIFY_OP)

    def broken(entity):
        raise RuntimeError("mail server down")

    monkeypatch.setitem(impl, op, (impl[op][0], broken))
    r = c.post("/expenses/e-bad", data={**EXPENSE, "amount": "250.00"}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, "e-bad") == "failed")
    [row] = runtime.store.list_instances(correlation_key="e-bad")
    error = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"])).data["seams"]["error"]
    assert error["type"] == "HandlerError"
    assert "mail server down" in error["message"]
    assert error["operation"] == NOTIFY_OP
    assert error["implementation"] == "PythonHandler"
    assert runtime.query(":NotificationShape") == []


# ── owned code survives regeneration ─────────────────────────────────────────


def test_seams_generate_never_touches_the_handlers_package(tmp_path, capsys):
    copy = tmp_path / CHAPTER
    shutil.copytree(chapter_dir(CHAPTER), copy, ignore=shutil.ignore_patterns("__pycache__"))
    before = _handler_files(copy)
    assert set(before) == {"__init__.py", "notify.py"}

    assert seams_main(["generate", "--project", str(copy)]) == 0
    assert _handler_files(copy) == before

    # the stub generator finds every module present and writes nothing
    assert generate_stubs(copy / "expenses.trig").writes == ()
    capsys.readouterr()
    assert stubs_main([str(copy / "expenses.trig")]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert _handler_files(copy) == before


def test_the_handlers_package_is_linted_like_any_owned_code():
    """ADR-0012: generated directories are excluded from ruff; handlers/ is not."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "chapter-09/handlers" not in pyproject
    assert "handlers" not in pyproject.split("extend-exclude", 1)[1].split("]", 1)[0]
