"""The gated image publish workflow and the image list it builds from (M016/S03, backlog A5).

.github/workflows/publish-images.yml runs only by hand or on a v* tag and pushes
only on the tag or when the manual run sets `push` (default false). The images it
builds come from ``python -m seams_gen.images``; each listed reference must be the
production deploy:artifact reference of its container, so the production compose
file names an image the workflow produces.
"""

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from seams import load

from seams_gen import GeneratorError
from seams_gen.compose import _executing, _resolve_environment
from seams_gen.images import ProjectError, list_images, registry, short_hash

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-images.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers() -> dict:
    data = _workflow()
    return data.get("on", data.get(True))  # YAML 1.1 reads a bare `on` as True


def _projects() -> list[str]:
    return _workflow()["env"]["SEAMS_IMAGE_PROJECTS"].split()


def _production_artifact(project: str):
    model = load(ROOT / project / _model_name(project))
    (container,) = _executing(model)
    return container, container.for_environment(_resolve_environment(model, "production")).artifact


def _model_name(project: str) -> str:
    return tomllib.loads((ROOT / project / "seams.toml").read_text())["model"]


# ── the workflow ────────────────────────────────────────────────────────────


def test_triggers_are_only_manual_dispatch_and_version_tags():
    triggers = _triggers()
    assert set(triggers) == {"workflow_dispatch", "push"}
    assert triggers["push"] == {"tags": ["v*"]}
    assert "pull_request" not in triggers
    assert "branches" not in triggers["push"]


def test_manual_push_input_is_boolean_and_defaults_to_false():
    push = _triggers()["workflow_dispatch"]["inputs"]["push"]
    assert push["type"] == "boolean"
    assert push["default"] is False


def test_permissions_are_read_contents_write_packages():
    assert _workflow()["permissions"] == {"contents": "read", "packages": "write"}


def test_push_is_gated_on_the_tag_or_the_manual_input():
    job = _workflow()["jobs"]["publish"]
    gate = job["env"]["PUSH"]
    assert "startsWith(github.ref, 'refs/tags/v')" in gate
    assert "inputs.push == true" in gate
    (build,) = [s for s in job["steps"] if s.get("uses", "").startswith("docker/build-push-action@")]
    assert build["with"]["push"] == "${{ env.PUSH == 'true' }}"
    (login,) = [s for s in job["steps"] if s.get("uses", "").startswith("docker/login-action@")]
    assert login["if"] == "env.PUSH == 'true'"


def test_build_uses_the_listed_context_dockerfile_tags_and_labels():
    job = _workflow()["jobs"]["publish"]
    assert job["strategy"]["matrix"]["include"] == "${{ fromJSON(needs.images.outputs.images) }}"
    (build,) = [s for s in job["steps"] if s.get("uses", "").startswith("docker/build-push-action@")]
    assert build["with"]["context"] == "${{ matrix.context }}"
    assert build["with"]["file"] == "${{ matrix.dockerfile }}"
    assert build["with"]["tags"] == "${{ join(matrix.tags, ',') }}"
    labels = build["with"]["labels"]
    assert "org.opencontainers.image.revision=${{ github.sha }}" in labels
    assert "io.semanticseams.model-hash=${{ matrix.model_hash }}" in labels


def test_the_list_job_syncs_and_lists_the_named_projects():
    steps = _workflow()["jobs"]["images"]["steps"]
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "uv sync --locked --all-packages" in runs
    assert "python -m seams_gen.images $SEAMS_IMAGE_PROJECTS" in runs
    assert _projects() == ["examples/chat-app", "examples/expenses/chapter-09"]


# ── the image list ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("project", ["examples/chat-app", "examples/expenses/chapter-09"])
def test_each_listed_reference_is_the_production_artifact_reference(project):
    container, artifact = _production_artifact(project)
    (image,) = list_images(ROOT / project, cwd=ROOT)
    assert image.container == str(container.iri)
    assert image.reference == artifact.reference
    assert image.version == artifact.version
    assert image.tags == (
        f"{artifact.reference}:{artifact.version}",
        f"{artifact.reference}:sha-{short_hash(image.model_hash)}",
    )


@pytest.mark.parametrize("project", ["examples/chat-app", "examples/expenses/chapter-09"])
def test_the_listed_dockerfile_is_generated_for_the_listed_model_hash(project):
    (image,) = list_images(ROOT / project, cwd=ROOT)
    assert image.context == "."
    assert image.dockerfile.startswith(f"{project}/generated/") and image.dockerfile.endswith(".Dockerfile")
    text = (ROOT / image.dockerfile).read_text()
    assert f"# model-hash: {image.model_hash}" in text
    assert re.search(rf'^LABEL .*io\.semanticseams\.model-hash="?{re.escape(image.model_hash)}', text, re.M)
    assert image.model_hash == load(ROOT / project / _model_name(project)).hash


def test_the_chat_app_reference_matches_the_model_literal():
    (image,) = list_images(ROOT / "examples/chat-app", cwd=ROOT)
    assert image.reference == "ghcr.io/example/chat-api"
    assert image.registry == "ghcr.io"


def test_paths_are_relative_to_the_working_directory():
    (image,) = list_images(ROOT / "examples/chat-app", cwd=ROOT / "examples")
    assert image.context == ".."
    assert image.dockerfile == "chat-app/generated/chat_api.Dockerfile"


def test_short_hash_and_registry():
    assert short_hash("sha256:" + "ab" * 32) == "ab" * 6
    assert registry("ghcr.io/example/chat-api") == "ghcr.io"
    assert registry("localhost:5000/x") == "localhost:5000"
    assert registry("seams/chat-api") == "docker.io"
    assert registry("postgres") == "docker.io"


def test_cli_prints_one_json_array_for_every_project():
    result = subprocess.run(
        [sys.executable, "-m", "seams_gen.images", *_projects()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    images = json.loads(result.stdout)
    assert [i["reference"] for i in images] == ["ghcr.io/example/chat-api", "ghcr.io/example/expense-api"]
    assert set(images[0]) == {
        "container",
        "context",
        "dockerfile",
        "reference",
        "registry",
        "version",
        "model_hash",
        "tags",
    }


# ── failures ────────────────────────────────────────────────────────────────


def test_a_project_without_the_dockerfile_generator_is_an_error():
    with pytest.raises(ProjectError, match="lists no `dockerfile` generator"):
        list_images(ROOT / "examples/expenses/chapter-01")


def test_a_missing_project_file_is_an_error(tmp_path):
    with pytest.raises(ProjectError, match="no such project file"):
        list_images(tmp_path)


def _copy_chapter_09(tmp_path) -> Path:
    src = ROOT / "examples/expenses/chapter-09"
    dst = tmp_path / "examples/expenses/chapter-09"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dst


def test_a_missing_generated_dockerfile_is_an_error(tmp_path):
    project = _copy_chapter_09(tmp_path)
    (project / "generated" / "expense_api.Dockerfile").unlink()
    with pytest.raises(ProjectError, match="expense_api.Dockerfile is missing; run `seams generate`"):
        list_images(project)


def test_a_model_without_a_production_environment_names_the_fact(tmp_path):
    project = _copy_chapter_09(tmp_path)
    trig = project / "expenses.trig"
    text = trig.read_text()
    assert ":production a arch:Environment" in text
    trig.write_text(text.replace(":production a arch:Environment", ":staging a arch:Environment"))
    with pytest.raises(GeneratorError, match="no arch:Environment 'production'"):
        list_images(project)


def test_cli_exit_codes(tmp_path):
    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "seams_gen.images", *args], cwd=ROOT, capture_output=True, text=True, check=False
        )

    missing = run(str(tmp_path))
    assert missing.returncode == 1 and "no such project file" in missing.stderr
    project = _copy_chapter_09(tmp_path)
    trig = project / "expenses.trig"
    trig.write_text(trig.read_text().replace(":production a arch:Environment", ":staging a arch:Environment"))
    model_error = run(str(project))
    assert model_error.returncode == 2 and "rdf-syntax-ns#type" in model_error.stderr
