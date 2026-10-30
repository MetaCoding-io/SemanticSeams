"""Every example's seams.toml regenerates its committed outputs byte-for-byte (M012/S01).

Each project under examples/ is copied into tmp_path at its repository-relative
path, without its outputs, so the chat app's compose target (``../..``, the
repository-root compose.yaml) lands at tmp_path/compose.yaml. ``seams generate``
then has to write exactly the committed generated files: nothing missing, which
catches a project file that forgets a generator, and nothing extra. The copy
keeps the committed seams.lock, which generate rewrites byte for byte (D043).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from seams_cli import load_project
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = sorted(p.parent.relative_to(ROOT) for p in (ROOT / "examples").rglob("seams.toml"))
COMPOSE = "compose.yaml"
LOCK = "seams.lock"


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _copy_without_outputs(rel: Path, tmp_path: Path) -> Path:
    dest = tmp_path / rel
    shutil.copytree(ROOT / rel, dest, ignore=shutil.ignore_patterns("generated", COMPOSE, "__pycache__"))
    return dest


def _committed_outputs(rel: Path) -> set[Path]:
    """Repository-relative paths of the committed generated files of the example at ``rel``:
    everything under generated/ but its README.md, its own compose.yaml, and the
    compose.yaml of every compose target its project file names."""
    app = ROOT / rel
    files = {
        p
        for p in (app / "generated").rglob("*")
        if p.is_file() and p.name != "README.md" and "__pycache__" not in p.parts
    }
    if (app / COMPOSE).is_file():
        files.add(app / COMPOSE)
    for target in load_project(app).generators:
        if target.name == "compose":
            files.add((target.out / COMPOSE).resolve())
    return {p.relative_to(ROOT) for p in files}


def _written(tmp_path: Path, before: set[Path]) -> set[Path]:
    return {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()} - before


def _assert_matches_committed(tmp_path: Path, written: set[Path], rel: Path) -> None:
    expected = _committed_outputs(rel)
    assert written == expected, (
        f"{rel}/seams.toml: missing {sorted(map(str, expected - written))}, "
        f"unexpected {sorted(map(str, written - expected))}"
    )
    for path in sorted(written):
        assert (tmp_path / path).read_bytes() == (ROOT / path).read_bytes(), f"{path} differs from the committed file"


def test_every_example_has_a_project_file():
    assert [str(p) for p in PROJECTS] == ["examples/chat-app"] + [
        f"examples/expenses/chapter-0{n}" for n in range(1, 9)
    ]


@pytest.mark.parametrize("rel", PROJECTS, ids=str)
def test_generate_rewrites_the_committed_outputs(rel, tmp_path):
    app = _copy_without_outputs(rel, tmp_path)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    assert main(["generate", "--project", str(app)]) == 0
    _assert_matches_committed(tmp_path, _written(tmp_path, before), rel)
    assert (app / LOCK).read_bytes() == (ROOT / rel / LOCK).read_bytes(), f"{rel / LOCK} is not current"


@pytest.mark.parametrize("rel", PROJECTS, ids=str)
def test_generate_recreates_a_removed_lockfile(rel, tmp_path):
    app = _copy_without_outputs(rel, tmp_path)
    (app / LOCK).unlink()
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    assert main(["generate", "--project", str(app)]) == 0
    written = _written(tmp_path, before)
    assert rel / LOCK in written
    _assert_matches_committed(tmp_path, written - {rel / LOCK}, rel)
    assert (app / LOCK).read_bytes() == (ROOT / rel / LOCK).read_bytes()


def test_console_script_generates_from_the_working_directory(tmp_path):
    """The installed ``seams`` imports seams_gen outside the repository root (D042),
    and ``--project`` defaults to the working directory."""
    seams = shutil.which("seams")
    if seams is None:
        pytest.skip("no `seams` console script on PATH; run `uv sync --all-packages`")
    rel = Path("examples/expenses/chapter-03")
    app = _copy_without_outputs(rel, tmp_path)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    env = {k: v for k, v in os.environ.items() if k not in ("SEAMS_MODEL", "PYTHONPATH")}
    result = subprocess.run([seams, "generate"], cwd=app, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == sorted(result.stdout.splitlines())
    _assert_matches_committed(tmp_path, _written(tmp_path, before), rel)
