"""The seams-plan composite action and ci.yml's change-plan job (M015/S02, D053).

The action's bash step is extracted from action.yml and run for real, under the
``bash -eo pipefail`` GitHub uses for ``shell: bash``, with the venv's ``seams``
on PATH and ``GITHUB_STEP_SUMMARY`` pointing at a temp file, in a throwaway git
repository whose HEAD holds expense chapter 8.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "seams-plan" / "action.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CH08 = ROOT / "examples" / "expenses" / "chapter-08"
CH09 = ROOT / "examples" / "expenses" / "chapter-09"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _step() -> dict:
    (step,) = [s for s in _action()["runs"]["steps"] if "run" in s]
    return step


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]


def _projects(steps: list[dict], uses: str) -> list[str]:
    (step,) = [s for s in steps if s.get("uses") == uses]
    return [ln.strip() for ln in step["with"]["projects"].splitlines() if ln.strip()]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A git repository whose HEAD holds chapter 8 at model/."""
    repo = tmp_path / "repo"
    shutil.copytree(CH08, repo / "model", ignore=shutil.ignore_patterns("generated", "handlers"))
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "chapter 8")
    return repo


def _run(repo: Path, projects: str, base: str = "HEAD") -> tuple[subprocess.CompletedProcess[str], str]:
    summary = repo.parent / "summary.md"
    summary.write_text("")
    bindir = str(Path(sys.executable).parent)
    env = {
        **os.environ,
        "INPUT_PROJECTS": projects,
        "INPUT_BASE": base,
        "GITHUB_STEP_SUMMARY": str(summary),
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
    }
    env.pop("SEAMS_MODEL", None)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _step()["run"]],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, summary.read_text()


def test_action_is_composite_with_projects_and_base_inputs():
    action = _action()
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["projects"]["default"] == "."
    assert action["inputs"]["base"]["required"] is True
    assert action["name"] and action["description"]


def test_inputs_arrive_through_env_and_the_plan_goes_to_the_job_summary():
    step = _step()
    assert step["shell"] == "bash"
    assert "${{" not in step["run"]
    assert step["env"] == {"INPUT_PROJECTS": "${{ inputs.projects }}", "INPUT_BASE": "${{ inputs.base }}"}
    assert "GITHUB_STEP_SUMMARY" in step["run"]
    assert 'seams plan "$INPUT_BASE:$p" "$p"' in step["run"]


def test_change_plan_job_runs_on_pull_requests_with_full_history():
    job = _jobs()["change-plan"]
    assert job["if"] == "github.event_name == 'pull_request'"
    steps = job["steps"]
    assert steps[0]["uses"] == "actions/checkout@v4"
    assert steps[0]["with"]["fetch-depth"] == 0
    runs = [s.get("run") for s in steps]
    assert "uv sync --locked --all-packages" in runs
    uses = [s.get("uses") for s in steps]
    action = uses.index("./.github/actions/seams-plan")
    # seams must be on PATH before the action runs.
    assert steps[action - 1]["run"] == 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"'
    assert steps[action]["with"]["base"] == "origin/${{ github.base_ref }}"


def test_change_plan_projects_match_the_seams_check_projects():
    jobs = _jobs()
    planned = _projects(jobs["change-plan"]["steps"], "./.github/actions/seams-plan")
    checked = _projects(jobs["acceptance"]["steps"], "./.github/actions/seams-check")
    assert planned == checked
    assert planned


def test_unchanged_project_writes_no_plan(repo):
    result, summary = _run(repo, "model\n\n  \n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "model is unchanged against HEAD." in result.stdout
    assert "No model changed against `HEAD`." in summary
    assert "## Change plan" not in summary


def test_changed_project_appends_its_plan(repo):
    shutil.copy(CH09 / "expenses.trig", repo / "model" / "expenses.trig")
    result, summary = _run(repo, "model/seams.toml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert summary.startswith("# model\n\n## Change plan\n")
    assert "### Compatible changes" in summary
    assert "- operation-added :notify_manager_op" in summary
    assert "#### Operations" in summary
    assert "No model changed" not in summary


def test_breaking_change_warns_but_does_not_fail(repo):
    shutil.copy(CH09 / "expenses.trig", repo / "model" / "expenses.trig")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "chapter 9")
    shutil.copy(CH08 / "expenses.trig", repo / "model" / "expenses.trig")
    result, summary = _run(repo, "model")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::seams plan: model has breaking changes against HEAD" in result.stdout
    assert "### Breaking changes\n\n- " in summary


def test_pull_request_adding_a_required_expense_field_shows_a_breaking_plan(repo):
    """M015 UAT: a PR that adds a required field to ExpenseShape gets a breaking-change plan."""
    trig = repo / "model" / "expenses.trig"
    date = "sh:property [ sh:path :date ; sh:datatype xsd:date ; sh:minCount 1 ; sh:maxCount 1 ;"
    text = trig.read_text()
    assert text.count(date) == 1
    required = (
        "sh:property [ sh:path :cost_centre ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;\n        "
    )
    trig.write_text(text.replace(date, required + date))
    result, summary = _run(repo, "model")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::seams plan: model has breaking changes against HEAD" in result.stdout
    breaking = summary.split("### Breaking changes\n\n", 1)[1].split("\n\n", 1)[0]
    assert "property-added" in breaking
    assert "ExpenseShape" in breaking
    assert "cost_centre minCount 1" in breaking


def test_project_absent_at_base_is_reported_as_new(repo):
    shutil.copytree(repo / "model", repo / "other")
    result, summary = _run(repo, "other\nmodel")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# other\n\nNew project: not present at `HEAD`." in summary
    assert "No model changed" not in summary


def test_unloadable_model_fails_after_every_project(repo):
    (repo / "model" / "expenses.trig").write_text("not turtle {")
    shutil.copytree(repo / "model", repo / "other")
    result, summary = _run(repo, "model\nother")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::seams plan failed for model" in result.stdout
    assert result.stdout.count("::endgroup::") == 2
    assert "seams plan:" in result.stderr
    assert "## Change plan" not in summary


def test_unknown_base_ref_fails(repo):
    result, _ = _run(repo, "model", base="no-such-ref")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::seams plan: unknown base ref no-such-ref" in result.stdout


def test_project_paths_and_refs_are_not_executed(repo):
    result, _ = _run(repo, "$(touch injected)", base="`touch injected2`")
    assert result.returncode == 1
    assert not (repo / "injected").exists()
    assert not (repo / "injected2").exists()
