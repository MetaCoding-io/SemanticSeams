"""Install docs point at the uv workspace, never at the deleted requirements files (M010/S01)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

INSTALL_DOCS = [
    "README.md",
    "docs/guide/getting-started.md",
    "docs/tutorial.md",
    "docs/tutorials/expenses/index.md",
    "docs/project/publishing.md",
    "seams_runtime/README.md",
    "seams_gen/README.md",
    "docs/scripts/generate.py",
]

# Historical records keep their original install instructions.
HISTORICAL = ("docs/research/", "docs/adr/")


@pytest.mark.parametrize("rel", INSTALL_DOCS)
def test_install_doc_does_not_use_pip_or_requirements(rel):
    text = (ROOT / rel).read_text()
    assert "pip install" not in text, f"{rel} still tells readers to pip install"
    assert "requirements" not in text.lower(), f"{rel} still mentions a requirements file"


@pytest.mark.parametrize("rel", ["README.md", "docs/guide/getting-started.md"])
def test_entry_docs_show_the_workspace_sync(rel):
    assert "uv sync --all-packages" in (ROOT / rel).read_text()


def test_getting_started_documents_lint_and_typecheck():
    text = (ROOT / "docs/guide/getting-started.md").read_text()
    for command in ("uv run ruff check", "uv run ruff format --check", "uv run pyright"):
        assert command in text


def _current_docs():
    for path in sorted((ROOT / "docs").rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if "node_modules" in path.parts or rel.startswith(HISTORICAL):
            continue
        yield rel, path


def test_glob_covers_the_install_docs_and_skips_history():
    found = {rel for rel, _ in _current_docs()}
    assert "docs/guide/getting-started.md" in found
    assert "docs/tutorial.md" in found
    assert not any(rel.startswith(HISTORICAL) for rel in found)


def test_no_current_doc_mentions_a_requirements_file():
    offenders = [
        rel
        for rel, path in _current_docs()
        if "requirements-dev.txt" in path.read_text() or "requirements.txt" in path.read_text()
    ]
    assert offenders == []
