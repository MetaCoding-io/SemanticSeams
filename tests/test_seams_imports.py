"""Importing seams never pulls in the runtime stack, and seams_gen reads the
model only through seams (M010/S02, D034)."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

RUNTIME_STACK = [
    "SpiffWorkflow",
    "fastapi",
    "starlette",
    "uvicorn",
    "pyshacl",
    "httpx",
    "seams_runtime",
    "seams_gateway",
    "viewer",
]
# seams itself uses neither; seams_gen renders with jinja2 and yaml
FORBIDDEN = [*RUNTIME_STACK, "jinja2", "yaml"]

GENERATORS = ["compose", "fastapi", "htmx", "fragments", "facts"]


def _blocker(forbidden: list[str]) -> str:
    return f"""
import sys

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {forbidden!r}:
            raise ImportError(f"blocked import of {{name}}")
        return None

sys.meta_path.insert(0, _Block())
"""


def _run(code: str, forbidden: list[str] = FORBIDDEN) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _blocker(forbidden) + code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )


def test_blocker_blocks():
    result = _run("import yaml")
    assert result.returncode != 0
    assert "blocked import of yaml" in result.stderr


def test_seams_loads_without_runtime_stack():
    result = _run("import seams\nprint(seams.load('examples/chat-app/chat-app.trig').hash)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("sha256:")


def test_seams_gen_imports_without_runtime_stack():
    modules = ["seams_gen", *(f"seams_gen.{name}" for name in GENERATORS)]
    result = _run("import importlib\n" + "".join(f"importlib.import_module({m!r})\n" for m in modules), RUNTIME_STACK)
    assert result.returncode == 0, result.stderr


def test_blocker_blocks_runtime_from_seams_gen():
    result = _run("import seams_runtime", RUNTIME_STACK)
    assert result.returncode != 0
    assert "blocked import of seams_runtime" in result.stderr


@pytest.mark.parametrize(
    ("trig", "code"),
    [
        # the exit codes tests/test_complexity.py expects: chat-app fails the
        # gate (EXIT_FAIL), the chapter-08 expense model passes (EXIT_PASS)
        ("examples/chat-app/chat-app.trig", 1),
        ("examples/expenses/chapter-08/expenses.trig", 0),
    ],
)
def test_complexity_runs_without_runtime_stack(trig: str, code: int):
    script = f"""
import runpy
sys.argv = ["seams_gen.complexity", {trig!r}]
try:
    runpy.run_module("seams_gen.complexity", run_name="__main__")
except SystemExit as exit:
    print("exit", exit.code)
"""
    result = _run(script, RUNTIME_STACK)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == f"exit {code}", result.stdout + result.stderr
    assert ("PASS" if code == 0 else "FAIL") in result.stdout.splitlines()


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.append(node.module)
    return names


def test_seams_gen_never_imports_seams_runtime():
    sources = sorted((ROOT / "seams_gen").glob("*.py"))
    assert sources
    offenders = [
        f"{path.name}: {name}"
        for path in sources
        for name in _imported_modules(ast.parse(path.read_text(), filename=str(path)))
        if name == "seams_runtime" or name.startswith("seams_runtime.")
    ]
    assert offenders == []


def test_import_scan_sees_seams_runtime():
    tree = ast.parse("import seams_runtime.model\nfrom seams_runtime import Runtime\nfrom .facts import Facts\n")
    assert _imported_modules(tree) == ["seams_runtime.model", "seams_runtime"]
