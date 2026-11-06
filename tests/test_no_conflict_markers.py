"""No tracked file holds a merge conflict marker.

Merge commit f925033 committed unresolved markers into a template, its generated
outputs, their locks and two goldens; the failure showed up only as unrelated test
failures in CI. This names the files directly. The same check runs as the
.githooks pre-commit and pre-merge-commit hooks.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_tracked_file_has_conflict_markers() -> None:
    result = subprocess.run(
        ["git", "grep", "-nIE", "^(<<<<<<<|>>>>>>>)( |$)", "--", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # git grep exits 1 when nothing matches, 0 on a match, and above 1 on an error.
    assert result.returncode != 0, f"conflict markers in tracked files:\n{result.stdout}"
    assert result.returncode == 1, result.stderr
