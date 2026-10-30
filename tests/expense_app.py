"""Shared helpers for the expense tutorial app tests (chapters 3 onward).

Each chapter with generated code commits examples/expenses/chapter-NN/generated/
(route module plus templates/) and a seams.toml naming its generators.
``generate_command(chapter)`` is the ``seams generate`` command the tutorial
page shows and the generated README names; ``commands(chapter)`` maps each
generator to that command, the failure hint the drift checks print;
``assert_generated_current`` regenerates both into tmp_path and diffs them
against the committed copy (helpers shared with
tests/test_generated_outputs_current.py). ``serve`` builds the host app for a
chapter's committed route module on a temp store (``serve_directory`` for a
copied checkpoint, which ``copy_checkpoint`` makes with one edit and both
generators rerun), and ``until``/``status`` poll a running instance, as
tests/test_human_task_app.py does.
"""

from __future__ import annotations

import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402
from test_generated_outputs_current import (  # noqa: E402
    HAND_WRITTEN,
    assert_current,
    committed_files,
    regenerate,
)

from seams_runtime.host import build_app  # noqa: E402

EXPENSES = ROOT / "examples" / "expenses"
# The first chapter whose checkpoint runs a BPMN process.
FIRST_PROCESS_CHAPTER = 4
PROCESS_CHAPTERS = sorted(
    p.name
    for p in EXPENSES.glob("chapter-*")
    if (p / "generated").is_dir() and int(p.name.split("-")[1]) >= FIRST_PROCESS_CHAPTER
)
# The first chapter whose checkpoint governs the submit operation and the
# user tasks with role policies. From there only the "manager" identity sees
# the approval task, and an approved expense waits on pay_expense for finance.
FIRST_ROLES_CHAPTER = 7
# The first chapter with a second, channel-started process (ADR-0010): from
# there a paid expense's correlation key also names a payout instance, so
# ``status`` and ``trace`` read the approval instance by default.
FIRST_PAYOUT_CHAPTER = 8
APPROVAL_PROCESS = "https://example.org/expenses/approval_process"
PAYOUT_PROCESS = "https://example.org/expenses/payout_process"


def chapter_number(chapter: str) -> int:
    return int(chapter.split("-")[1])


def has_roles(chapter: str) -> bool:
    return chapter_number(chapter) >= FIRST_ROLES_CHAPTER


def has_payout(chapter: str) -> bool:
    return chapter_number(chapter) >= FIRST_PAYOUT_CHAPTER


def chapter_dir(chapter: str) -> Path:
    return EXPENSES / chapter


def generate_command(chapter: str) -> str:
    """The regenerate command, run from the repository root."""
    return f"seams generate --project examples/expenses/{chapter}"


def commands(chapter: str) -> dict[str, str]:
    """The regenerate command to hint for each generator of the chapter."""
    return {"fastapi": generate_command(chapter), "htmx": generate_command(chapter)}


def host_command(chapter: str) -> list[str]:
    """The fragments of the host command a chapter page must show."""
    return [
        f"SEAMS_MODEL=examples/expenses/{chapter}/expenses.trig",
        f"SEAMS_TEMPLATES=examples/expenses/{chapter}/generated/templates",
        "SEAMS_DB=",
        f"python -m seams_runtime.host --routes examples/expenses/{chapter}/generated/expense_api.py",
    ]


def assert_generated_current(chapter: str, tmp_path: Path, generator: str) -> None:
    """The committed route module (``fastapi``) or templates (``htmx``) equal
    a fresh run of the generator on the chapter's checkpoint."""
    generated = chapter_dir(chapter) / "generated"
    trig = chapter_dir(chapter) / "expenses.trig"
    if generator == "fastapi":
        committed_dir, committed = generated, committed_files(generated, HAND_WRITTEN)
    else:
        committed_dir = generated / "templates"
        committed = committed_files(committed_dir)
    assert_current(
        regenerate(generator, trig, tmp_path / generator), committed, committed_dir, commands(chapter)[generator]
    )


def copy_checkpoint(chapter: str, tmp_path: Path, file: str, old: str, new: str) -> tuple[Path, dict[str, str]]:
    """The chapter's checkpoint copied to tmp_path with ``old`` replaced by
    ``new`` (exactly once) in ``file``, and both generators rerun into the
    copy's generated/. Returns the copy and its regenerated files by path
    (``templates/<name>`` for templates)."""
    copy = tmp_path / chapter
    shutil.copytree(chapter_dir(chapter), copy, ignore=shutil.ignore_patterns("__pycache__"))
    edited = copy / file
    text = edited.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    edited.write_text(text.replace(old, new), encoding="utf-8")
    generated = copy / "generated"
    for name in committed_files(generated, HAND_WRITTEN):
        (generated / name).unlink()
    shutil.rmtree(generated / "templates")
    routes = {
        name: text
        for name, text in regenerate("fastapi", copy / "expenses.trig", generated).items()
        if name not in HAND_WRITTEN
    }
    templates = regenerate("htmx", copy / "expenses.trig", generated / "templates")
    return copy, {**routes, **{f"templates/{n}": t for n, t in templates.items()}}


@contextmanager
def serve(chapter: str, tmp_path: Path, monkeypatch):
    """(TestClient, Runtime) for the chapter's committed route module, with
    SEAMS_MODEL / SEAMS_TEMPLATES on the checkpoint, SEAMS_DB in tmp_path (with
    SEAMS_STORE_OVERRIDE=sqlite, whatever store the chapter declares), and
    no dev user or seed, so every identity comes from X-Forwarded-User."""
    with serve_directory(chapter_dir(chapter), tmp_path, monkeypatch) as served:
        yield served


@contextmanager
def serve_directory(directory: Path, tmp_path: Path, monkeypatch):
    """``serve`` for a checkpoint directory anywhere (for example a copy in
    tmp_path): its expenses.trig, generated/expense_api.py and templates."""
    monkeypatch.setenv("SEAMS_MODEL", str(directory / "expenses.trig"))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(directory / "generated" / "templates"))
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "seams.sqlite"))
    # chapter 08 declares PostgreSQL; the harness runs every chapter on SQLite
    monkeypatch.setenv("SEAMS_STORE_OVERRIDE", "sqlite")
    monkeypatch.delenv("SEAMS_DEV_USER", raising=False)
    monkeypatch.delenv("SEAMS_SEED", raising=False)
    app = build_app(directory / "generated" / "expense_api.py")
    with TestClient(app) as client:
        yield client, app.state.runtime


def until(predicate, timeout=5.0):
    """Poll ``predicate`` until it returns something truthy, and return that."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {predicate.__doc__ or predicate}")


def instances(runtime, key, process=APPROVAL_PROCESS) -> list[dict]:
    """The stored instances of ``process`` with correlation key ``key``, oldest update first."""
    return [r for r in runtime.store.list_instances(correlation_key=key) if r["process"] == process]


def status(runtime, key, process=APPROVAL_PROCESS):
    """the instance's stored status"""
    rows = instances(runtime, key, process)
    return rows[-1]["status"] if rows else None


def trace(runtime, key, process=APPROVAL_PROCESS) -> list[dict]:
    """The latest instance's trace rows, read back from its checkpoint."""
    [*_, row] = instances(runtime, key, process)
    wf = runtime.engine.deserialize(runtime.store.load_state(row["instance_id"]))
    return wf.data["seams"]["trace"]
