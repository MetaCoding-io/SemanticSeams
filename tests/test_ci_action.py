"""The seams-check composite action, the pre-commit hook and ci.yml's use of them (M012/S03).

The action's bash step is extracted from action.yml and run for real with the
venv's ``seams`` on PATH, so the loop and its exit code are exercised, not only
parsed.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "seams-check" / "action.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
HOOKS = ROOT / ".pre-commit-hooks.yaml"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _run_script() -> str:
    (step,) = [s for s in _action()["runs"]["steps"] if "run" in s]
    return step["run"]


def _run_action(projects: str) -> subprocess.CompletedProcess[str]:
    bindir = str(Path(sys.executable).parent)
    env = {**os.environ, "INPUT_PROJECTS": projects, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("SEAMS_MODEL", None)
    return subprocess.run(["bash", "-c", _run_script()], cwd=ROOT, env=env, capture_output=True, text=True, check=False)


def test_action_is_composite_with_a_projects_input():
    action = _action()
    assert action["runs"]["using"] == "composite"
    assert "projects" in action["inputs"]
    assert action["inputs"]["projects"]["default"] == "."
    assert action["inputs"]["projects"]["required"] is False
    assert action["name"] and action["description"]


def test_no_step_script_interpolates_inputs():
    for step in _action()["runs"]["steps"]:
        assert "${{" not in step.get("run", ""), step
    (step,) = [s for s in _action()["runs"]["steps"] if "run" in s]
    assert step["shell"] == "bash"
    assert step["env"]["INPUT_PROJECTS"] == "${{ inputs.projects }}"


def test_ci_acceptance_job_uses_the_action_and_no_longer_regenerates():
    text = CI.read_text()
    assert not re.search(r"^\s*seams generate", text, re.M)
    steps = yaml.safe_load(text)["jobs"]["acceptance"]["steps"]
    uses = [s.get("uses") for s in steps]
    assert "./.github/actions/seams-check" in uses
    # seams must be on PATH before the action runs.
    path_step = uses.index("./.github/actions/seams-check") - 1
    assert steps[path_step]["run"] == 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"'


def test_pre_commit_hook_runs_seams_check():
    (hook,) = yaml.safe_load(HOOKS.read_text())
    assert hook["id"] == "seams-check"
    assert hook["entry"] == "seams check"
    assert hook["language"] == "system"
    assert hook["pass_filenames"] is False
    files = re.compile(hook["files"])
    for path in ["examples/chat-app/seams.toml", "a/seams.lock", "m.trig", "g.rq", "p.bpmn", "d.dmn"]:
        assert files.search(path), path
    assert files.search("examples/chat-app/generated/chat_api.py")
    assert not files.search("README.md")


def test_action_script_passes_on_current_projects_and_skips_blank_lines():
    result = _run_action("examples/chat-app\n\n   \nexamples/expenses/chapter-01\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("::group::") == 2
    assert "::group::seams check --project examples/chat-app" in result.stdout
    assert "::group::seams check --project examples/expenses/chapter-01" in result.stdout
    assert "::error::" not in result.stdout


def test_action_script_runs_every_project_before_failing(tmp_path):
    missing = tmp_path / "no-such-project"
    result = _run_action(f"{missing}\nexamples/chat-app")
    assert result.returncode == 1, result.stdout + result.stderr
    # The failing project does not stop the loop: the chat app still ran.
    assert "::group::seams check --project examples/chat-app" in result.stdout
    assert f"::error::seams check failed for {missing}" in result.stdout
    assert result.stdout.count("::endgroup::") == 2
    assert "seams check:" in result.stderr


def test_action_script_does_not_execute_a_project_path():
    result = _run_action("$(touch injected); `touch injected2`")
    assert result.returncode == 1
    assert not (ROOT / "injected").exists()
    assert not (ROOT / "injected2").exists()
