"""The ungoverned-writes gate: no rows where policies govern every write, rows where none do (M012/S03, D044).

Rows are counted on the union graph `seams check` builds (model plus ontology).
Chapter 4 adds expense submission before chapter 7 adds permissions, so it is
the expected negative.
"""

import shutil
import tomllib
from pathlib import Path

import pytest
from seams_cli import load_project
from seams_cli.__main__ import main
from seams_cli.check import model_graph

ROOT = Path(__file__).resolve().parent.parent
GATE = Path("docs/queries/gates/ungoverned-writes.rq")
GATED = ["examples/chat-app", "examples/expenses/chapter-07", "examples/expenses/chapter-08"]
CHAPTER_04 = Path("examples/expenses/chapter-04")


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _rows(rel: str | Path) -> list:
    graph = model_graph(load_project(ROOT / rel).model)
    return list(graph.query((ROOT / GATE).read_text(encoding="utf-8")))


@pytest.mark.parametrize("rel", GATED)
def test_no_ungoverned_writes_in_gated_projects(rel):
    assert _rows(rel) == []


@pytest.mark.parametrize("rel", GATED)
def test_gated_projects_declare_the_gate(rel):
    project = load_project(ROOT / rel)
    assert (ROOT / GATE).resolve() in [gate.resolve() for gate in project.gates]
    gates = tomllib.loads((ROOT / rel / "seams.toml").read_text(encoding="utf-8"))["gates"]
    assert all((ROOT / rel / gate).is_file() for gate in gates)


def test_chapter_04_has_ungoverned_writes():
    ex = "https://example.org/expenses/"
    rows = {tuple(str(v) for v in row) for row in _rows(CHAPTER_04)}
    assert rows == {
        (f"{ex}submit_expense", f"{ex}approval_bpmn#approve_expense", f"{ex}ApprovalShape"),
        (f"{ex}submit_expense", f"{ex}approval_bpmn#persist_expense", f"{ex}ExpenseShape"),
    }


def test_seams_check_fails_on_chapter_04_with_the_gate(tmp_path, capsys):
    app = tmp_path / CHAPTER_04
    shutil.copytree(ROOT / CHAPTER_04, app, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / GATE).parent.mkdir(parents=True)
    shutil.copy2(ROOT / GATE, tmp_path / GATE)
    toml = app / "seams.toml"
    toml.write_text(f'gates = ["../../../{GATE.as_posix()}"]\n' + toml.read_text(encoding="utf-8"), encoding="utf-8")

    code = main(["check", "--project", str(app)])
    out, err = capsys.readouterr()

    lines = out.splitlines()
    assert code == 1
    gate = f"gate ../../../{GATE.as_posix()} https://example.org/expenses/submit_expense"
    assert len(lines) == 2
    assert all(line.startswith(gate + " ") for line in lines)
    assert err.strip() == "seams check: 2 problem(s)"
