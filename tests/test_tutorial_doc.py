"""docs/tutorial.md shows the commands CI actually runs (M004/S07/T06).

The project list is read from the "Generated outputs are current" step of
.github/workflows/ci.yml, which runs the seams-check action on each project, so
changing the chat-app check in CI without updating the tutorial (or the
reverse) fails here.
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

from test_tutorial_e2e import COMPOSE_FILE, PSQL, landed_sql  # noqa: E402

TUTORIAL = ROOT / "docs" / "tutorial.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _ci_steps() -> dict:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    return {
        (job, step.get("name") or step.get("run") or step.get("uses")): step
        for job, spec in jobs.items()
        for step in spec["steps"]
    }


def _checked_projects() -> list[str]:
    step = _ci_steps()[("acceptance", "Generated outputs are current")]
    assert step["uses"] == "./.github/actions/seams-check", step
    return [ln.strip() for ln in step["with"]["projects"].splitlines() if ln.strip()]


def _code_lines() -> set[str]:
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", TUTORIAL.read_text(), re.S | re.M)
    return {ln.strip() for block in blocks for ln in block.splitlines() if ln.strip()}


def test_tutorial_shows_the_ci_check_command():
    projects = _checked_projects()
    # The chat app, then every expenses chapter with a project file.
    chapters = sorted(p.parent.name for p in (ROOT / "examples" / "expenses").glob("chapter-*/seams.toml"))
    assert projects == ["examples/chat-app"] + [f"examples/expenses/{c}" for c in chapters], projects
    lines = _code_lines()
    assert "seams generate --project examples/chat-app" in lines
    check = "seams check --project examples/chat-app"
    assert check in lines, f"docs/tutorial.md lacks the CI check command: {check}"


def test_tutorial_shows_the_compose_lines_the_e2e_job_exercises():
    lines = _code_lines()
    # one generated file per environment (ADR-0015); the tutorial runs development
    assert f"docker compose -f {COMPOSE_FILE} up --build" in lines
    assert f"docker compose -f {COMPOSE_FILE} down -v" in lines
    assert "mkdir -p .secrets && : > .secrets/llm_api_key" in lines


def test_tutorial_shows_the_store_checks_the_e2e_test_runs():
    lines = _code_lines()
    psql = f'docker compose -f {COMPOSE_FILE} {" ".join(PSQL)} "{landed_sql("hello")}"'
    assert psql in lines, f"docs/tutorial.md lacks {psql}"
    assert "curl localhost:8080/healthz" in lines


def test_ci_runs_the_tutorial_e2e_job():
    step = _ci_steps()[("tutorial-e2e", "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py")]
    assert step["run"] == "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py"
    e2e = (ROOT / "tests" / "test_tutorial_e2e.py").read_text()
    assert '"up", "-d", "--build", "--wait"' in e2e and '"down", "-v"' in e2e


def test_readme_links_the_tutorial():
    assert "(docs/tutorial.md)" in (ROOT / "README.md").read_text()
