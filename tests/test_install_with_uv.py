"""CI, the Pages deploy and both images install with uv from the committed uv.lock (M010/S01).

Plain YAML and text reads: the laptop, CI and the images must resolve the same locked
versions, so nothing may fall back to pip or a requirements file.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
RUNTIME_DOCKERFILE = ROOT / "examples" / "chat-app" / "generated" / "chat_api.Dockerfile"
DOCKERFILES = [RUNTIME_DOCKERFILE, ROOT / "docker" / "gateway.Dockerfile"]


def _jobs(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]


def _runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _uses(job: dict) -> list[str]:
    return [step["uses"] for step in job.get("steps", []) if "uses" in step]


def _local_action_runs(job: dict) -> str:
    """The run scripts of the repository's own composite actions (``uses: ./...``) a job calls."""
    runs = []
    for uses in _uses(job):
        if uses.startswith("./"):
            action = yaml.safe_load((ROOT / uses / "action.yml").read_text(encoding="utf-8"))
            runs += [step.get("run", "") for step in action["runs"].get("steps", [])]
    return "\n".join(runs)


def _runs_python(job: dict) -> bool:
    # A local composite action counts as the job's own steps; the seams CLI is Python.
    runs = _runs(job) + "\n" + _local_action_runs(job)
    return any(word in runs for word in ("python", "pytest", "npm run build", "ruff", "pyright", "seams "))


def test_workflows_are_found():
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "deploy-pages.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_uses_setup_python_or_pip(path):
    text = path.read_text(encoding="utf-8")
    assert "actions/setup-python" not in text
    assert "pip install" not in text
    assert "requirements" not in text


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_python_job_installs_with_uv_from_the_lock(path):
    python_jobs = {name: job for name, job in _jobs(path).items() if _runs_python(job)}
    for name, job in python_jobs.items():
        assert any(u.startswith("astral-sh/setup-uv@") for u in _uses(job)), name
        assert "uv sync --locked --all-packages" in _runs(job), name


def test_the_python_job_detector_sees_every_ci_job():
    # Guards the check above: if _runs_python missed a job, it would silently pass.
    jobs = _jobs(ROOT / ".github" / "workflows" / "ci.yml")
    assert {name for name, job in jobs.items() if _runs_python(job)} == set(jobs)


def test_ci_has_lint_and_typecheck_jobs():
    jobs = _jobs(ROOT / ".github" / "workflows" / "ci.yml")
    lint = _runs(jobs["lint"]).splitlines()
    assert "uv run ruff check" in lint
    assert "uv run ruff format --check" in lint
    assert "uv run pyright" in _runs(jobs["typecheck"]).splitlines()


def test_docs_builds_run_through_uv():
    # uv run puts the venv's absolute bin on PATH; a relative .venv/bin breaks under npm.
    for path, job in (
        (ROOT / ".github/workflows/ci.yml", "docs"),
        (ROOT / ".github/workflows/deploy-pages.yml", "build"),
    ):
        assert "uv run npm run build" in _runs(_jobs(path)[job]).splitlines(), path.name


def test_pages_redeploys_when_the_locked_environment_changes():
    spec = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8"))
    paths = spec[True]["push"]["paths"]  # PyYAML reads the bare `on` key as True
    assert {"pyproject.toml", "uv.lock"} <= set(paths)


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.name)
def test_dockerfiles_install_from_the_lock_without_dev_deps(path):
    text = path.read_text(encoding="utf-8")
    assert "requirements.txt" not in text
    assert "pip install" not in text
    assert "uv sync --locked --no-dev" in text
    lines = text.splitlines()
    assert "FROM python:3.12-slim" in lines
    assert any(line.startswith("COPY --from=ghcr.io/astral-sh/uv:") for line in lines)
    assert "COPY pyproject.toml uv.lock .python-version /app/" in lines


@pytest.mark.parametrize(
    ("path", "package"),
    [(DOCKERFILES[0], "semanticseams-runtime"), (DOCKERFILES[1], "semanticseams-gateway")],
    ids=["runtime", "gateway"],
)
def test_each_image_syncs_only_its_own_member(path, package):
    text = path.read_text(encoding="utf-8")
    assert f"--package {package}" in text
    assert "--all-packages" not in text


def test_dockerignore_keeps_the_local_venv_out_of_the_images():
    entries = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".venv" in entries
    assert "uv.lock" not in entries
    assert "pyproject.toml" not in entries


def test_runtime_image_installs_the_seams_library():
    # seams_runtime imports ModelGraph and the errors from seams (D034).
    lines = RUNTIME_DOCKERFILE.read_text(encoding="utf-8").splitlines()
    assert "COPY packages/seams /app/packages/seams" in lines
    assert any(line.startswith("RUN uv sync --locked --no-dev") and "--no-editable" in line for line in lines)
