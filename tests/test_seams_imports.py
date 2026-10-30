"""Importing seams never pulls in the runtime stack (M010/S02, D034)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = [
    "SpiffWorkflow",
    "fastapi",
    "starlette",
    "uvicorn",
    "pyshacl",
    "httpx",
    "jinja2",
    "yaml",
    "seams_runtime",
    "seams_gateway",
    "viewer",
]

BLOCKER = f"""
import sys

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {FORBIDDEN!r}:
            raise ImportError(f"blocked import of {{name}}")
        return None

sys.meta_path.insert(0, _Block())
"""


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", BLOCKER + code], cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_blocker_blocks():
    result = _run("import yaml")
    assert result.returncode != 0
    assert "blocked import of yaml" in result.stderr


def test_seams_loads_without_runtime_stack():
    result = _run("import seams\nprint(seams.load('examples/chat-app/chat-app.trig').hash)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("sha256:")
