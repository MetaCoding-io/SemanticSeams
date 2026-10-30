"""The repository is a uv workspace with a locked environment (M010/S01, backlog L1).

Pins the workspace layout: the six members, the virtual status of the four
existing packages (D033), the packaged seams-cli member and its `seams` script
(D042), the seams library's dependency allowlist (D031) and the removal of the
old pip requirements files.
"""

import importlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MEMBERS = ["packages/seams", "seams_runtime", "seams_gen", "seams_gateway", "viewer", "packages/seams-cli"]
VIRTUAL_MEMBERS = ["seams_runtime", "seams_gen", "seams_gateway", "viewer"]
SEAMS_ALLOWED_DEPENDENCIES = {"rdflib", "lxml"}
REMOVED_REQUIREMENTS = [
    "requirements-dev.txt",
    "seams_runtime/requirements.txt",
    "seams_gateway/requirements.txt",
    "viewer/requirements.txt",
]


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _requirement_name(requirement: str) -> str:
    """'uvicorn[standard]>=0.30' -> 'uvicorn' (PEP 503 normalised)."""
    name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    assert name, f"unparseable requirement {requirement!r}"
    return re.sub(r"[-_.]+", "-", name.group(1)).lower()


def test_root_lists_exactly_the_six_members():
    root = _toml(ROOT / "pyproject.toml")
    assert root["tool"]["uv"]["workspace"]["members"] == MEMBERS


def test_every_member_has_a_pyproject():
    for member in MEMBERS:
        assert (ROOT / member / "pyproject.toml").is_file(), f"{member}/pyproject.toml is missing"


def test_existing_members_are_virtual():
    for member in VIRTUAL_MEMBERS:
        pyproject = _toml(ROOT / member / "pyproject.toml")
        assert pyproject.get("tool", {}).get("uv", {}).get("package") is False, (
            f"{member} must set [tool.uv] package = false (D033)"
        )


def test_seams_library_is_a_real_package():
    pyproject = _toml(ROOT / "packages/seams/pyproject.toml")
    assert pyproject["project"]["name"] == "semanticseams"
    assert pyproject["build-system"]["build-backend"] == "uv_build"
    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == "seams"
    assert pyproject.get("tool", {}).get("uv", {}).get("package") is not False


def test_seams_cli_is_packaged_and_declares_the_seams_script():
    # uv installs no console scripts for virtual members (D033), so the CLI is packaged (D042).
    pyproject = _toml(ROOT / "packages/seams-cli/pyproject.toml")
    assert pyproject["project"]["name"] == "semanticseams-cli"
    assert pyproject.get("tool", {}).get("uv", {}).get("package") is not False
    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    assert pyproject["project"]["scripts"] == {"seams": "seams_cli.__main__:main"}
    assert "semanticseams" in {_requirement_name(r) for r in pyproject["project"]["dependencies"]}


def test_seams_depends_only_on_rdflib_and_lxml():
    pyproject = _toml(ROOT / "packages/seams/pyproject.toml")
    names = {_requirement_name(r) for r in pyproject["project"].get("dependencies", [])}
    assert names <= SEAMS_ALLOWED_DEPENDENCIES, f"disallowed: {sorted(names - SEAMS_ALLOWED_DEPENDENCIES)}"
    assert not pyproject["project"].get("optional-dependencies"), "seams may not add optional dependencies"


def test_requirement_name_strips_specifiers_and_extras():
    assert _requirement_name("uvicorn[standard]>=0.30") == "uvicorn"
    assert _requirement_name("SpiffWorkflow>=3.0") == "spiffworkflow"
    assert _requirement_name("python_multipart ; python_version>'3'") == "python-multipart"


def test_seams_is_marked_typed():
    assert (ROOT / "packages/seams/src/seams/py.typed").is_file()


def test_requirements_files_are_gone():
    present = [path for path in REMOVED_REQUIREMENTS if (ROOT / path).exists()]
    assert not present, f"replaced by pyproject.toml and uv.lock: {present}"


def test_lock_exists_and_names_the_library():
    lock = ROOT / "uv.lock"
    assert lock.is_file()
    names = {package["name"] for package in _toml(lock)["package"]}
    assert "semanticseams" in names


def test_python_version_is_pinned():
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_seams_imports():
    seams = importlib.import_module("seams")
    assert seams.__all__ == sorted(seams.__all__)
    assert {"load", "Model", "model_hash", "ResolutionError", "SEAM"} <= set(seams.__all__)
