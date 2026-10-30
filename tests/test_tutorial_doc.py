"""docs/tutorial.md shows the commands CI actually runs (M004/S07/T06).

The seams_gen lines are read from the "Generated outputs are current" step of
.github/workflows/ci.yml, with its ``$trig`` variable expanded, so changing
the CI regeneration without updating the tutorial (or the reverse) fails here.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
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
    trig = re.search(r"^\s*trig=(\S+)\s*$", script, re.M).group(1)
    lines = [ln.strip() for ln in script.splitlines() if ln.strip().startswith("python -m seams_gen")]
    return [ln.replace('"$trig"', trig).replace("$trig", trig) for ln in lines]


def _code_lines() -> set[str]:
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", TUTORIAL.read_text(), re.S | re.M)
    return {ln.strip() for block in blocks for ln in block.splitlines() if ln.strip()}


def test_tutorial_shows_the_ci_regeneration_commands():
    commands = _regeneration_commands()
    assert [c.split()[3] for c in commands] == ["fastapi", "htmx", "compose"], commands
    missing = [c for c in commands if c not in _code_lines()]
    assert not missing, f"docs/tutorial.md lacks the CI regeneration commands: {missing}"


def test_tutorial_shows_the_compose_lines_the_e2e_job_exercises():
    lines = _code_lines()
    assert "docker compose up --build" in lines
    assert "docker compose down -v" in lines
    assert "mkdir -p .secrets && : > .secrets/llm_api_key" in lines


def test_ci_runs_the_tutorial_e2e_job():
    step = _ci_steps()[("tutorial-e2e", "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py")]
    assert step["run"] == "SEAMS_E2E=1 pytest -q tests/test_tutorial_e2e.py"
    e2e = (ROOT / "tests" / "test_tutorial_e2e.py").read_text()
    assert '"up", "-d", "--build", "--wait"' in e2e and '"down", "-v"' in e2e


def test_readme_links_the_tutorial():
    assert "(docs/tutorial.md)" in (ROOT / "README.md").read_text()
