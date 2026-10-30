"""docs/tutorial.md shows the commands CI actually runs (M004/S07/T06).

The ``seams generate`` lines are read from the "Generated outputs are current"
step of .github/workflows/ci.yml, so changing the chat-app regeneration in CI
without updating the tutorial (or the reverse) fails here.
The "See where it landed" psql command is the one tests/test_tutorial_e2e.py
runs against the live stack.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_tutorial_e2e import PSQL, landed_sql  # noqa: E402

TUTORIAL = ROOT / "docs" / "tutorial.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _ci_steps() -> dict:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    return {
        (job, step.get("name") or step.get("run") or step.get("uses")): step
        for job, spec in jobs.items()
        for step in spec["steps"]
    }


def _regeneration_commands() -> list[str]:
    script = _ci_steps()[("acceptance", "Generated outputs are current")]["run"]
    return [ln.strip() for ln in script.splitlines() if ln.strip().startswith("seams generate")]


def _code_lines() -> set[str]:
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", TUTORIAL.read_text(), re.S | re.M)
    return {ln.strip() for block in blocks for ln in block.splitlines() if ln.strip()}


def test_tutorial_shows_the_ci_regeneration_commands():
    commands = _regeneration_commands()
    chat_app = "seams generate --project examples/chat-app"
    assert chat_app in commands, commands
    # Every expenses chapter with a project file is regenerated too.
    chapters = sorted(p.parent.name for p in (ROOT / "examples" / "expenses").glob("chapter-*/seams.toml"))
    assert [c for c in commands if c != chat_app] == [
        f"seams generate --project examples/expenses/{chapter}" for chapter in chapters
    ], commands
    assert chat_app in _code_lines(), f"docs/tutorial.md lacks the CI regeneration command: {chat_app}"


def test_tutorial_shows_the_compose_lines_the_e2e_job_exercises():
    lines = _code_lines()
    assert "docker compose up --build" in lines
    assert "docker compose down -v" in lines
    assert "mkdir -p .secrets && : > .secrets/llm_api_key" in lines


def test_tutorial_shows_the_store_checks_the_e2e_test_runs():
    lines = _code_lines()
    psql = f'docker compose {" ".join(PSQL)} "{landed_sql("hello")}"'
    assert psql in lines, f"docs/tutorial.md lacks {psql}"
    assert "curl localhost:8080/healthz" in lines


def test_ci_runs_the_tutorial_e2e_job():
    step = _ci_steps()[("tutorial-e2e", "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py")]
    assert step["run"] == "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py"
    e2e = (ROOT / "tests" / "test_tutorial_e2e.py").read_text()
    assert '"up", "-d", "--build", "--wait"' in e2e and '"down", "-v"' in e2e


def test_readme_links_the_tutorial():
    assert "(docs/tutorial.md)" in (ROOT / "README.md").read_text()
