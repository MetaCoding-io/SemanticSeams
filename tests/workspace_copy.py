"""The uv workspace files a copied example's build context needs (backlog A12).

The ``dockerfile`` generator reads the workspace members from the
``pyproject.toml`` at the root of the deploy:context (the repository root for
every example) and each member's ``pyproject.toml``. A test that copies an
example with a serving container into tmp_path and generates or checks it
copies these beside it with ``copy_workspace``, or copies the example at its
place under the repository root with them using ``copy_example``.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workspace_members() -> list[str]:
    """The [tool.uv.workspace] members of the repository root, as written."""
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["tool"]["uv"]["workspace"]["members"]


def copy_workspace(context: Path) -> None:
    """Copy the root pyproject.toml and each member's into ``context``."""
    context.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "pyproject.toml", context / "pyproject.toml")
    for member in workspace_members():
        (context / member).mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / member / "pyproject.toml", context / member / "pyproject.toml")


def copy_example(src: Path, tmp_path: Path, ignore=None) -> Path:
    """``src``, an example directory, copied to tmp_path at its place under the
    repository root, with the workspace files at tmp_path (``copy_workspace``),
    so its deploy:context resolves inside tmp_path. Returns the copy."""
    dest = tmp_path / src.relative_to(ROOT)
    shutil.copytree(src, dest, ignore=ignore)
    copy_workspace(tmp_path)
    return dest
