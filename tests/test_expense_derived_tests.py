"""Run chapter 9's generated tests in CI (M015/S03, ADR-0014).

pytest only collects tests/ (``testpaths``), so the tests the ``tests``
generator writes to examples/expenses/chapter-09/generated/tests would not
run in CI's ``uv run pytest -q`` step. This module runs them once, in a
subprocess with its own rootdir so their conftest-free imports and module
names cannot clash with this suite, and reads the outcome of each generated
test from a JUnit report. One test per generated file asserts that every
``def test_`` in it ran and passed, so a CI failure names the file and the
generated test, whose name carries the scenario, policy or example IRI.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from expense_app import ROOT, chapter_dir

GENERATED = chapter_dir("chapter-09") / "generated" / "tests"
FILES = sorted(p.name for p in GENERATED.glob("test_*.py"))
TIMEOUT = 600


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory) -> dict[str, dict[str, str]]:
    """Outcome ("passed", "failed", "error", "skipped") of each generated test, by file then test name."""
    report = tmp_path_factory.mktemp("derived") / "report.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(GENERATED),
            "-q",
            "-p",
            "no:cacheprovider",
            "--import-mode=importlib",
            "-W",
            "ignore",
            f"--junitxml={report}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert report.exists(), (
        f"the generated tests did not run (exit {result.returncode}):\n{result.stdout}{result.stderr}"
    )
    by_file: dict[str, dict[str, str]] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        module = case.get("classname", "").rsplit(".", 1)[-1]
        outcome = "passed"
        for tag in ("failure", "error", "skipped"):
            if case.find(tag) is not None:
                outcome = tag if tag != "failure" else "failed"
        by_file.setdefault(f"{module}.py", {})[case.get("name", "")] = outcome
    if result.returncode not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
        pytest.fail(f"the generated tests did not run cleanly (exit {result.returncode}):\n{result.stdout[-4000:]}")
    return by_file


def test_every_generator_output_is_run():
    assert FILES == ["test_decisions.py", "test_policies.py", "test_scenarios.py", "test_shape_examples.py"]


@pytest.mark.parametrize("name", FILES)
def test_generated_tests_pass(outcomes, name):
    declared = re.findall(r"^def (test_\w+)\(", (GENERATED / name).read_text(encoding="utf-8"), re.M)
    ran = outcomes.get(name, {})
    assert declared, f"{name} declares no tests"
    assert sorted(ran) == sorted(declared), f"{name}: tests that did not run: {sorted(set(declared) - set(ran))}"
    failed = {test: outcome for test, outcome in ran.items() if outcome != "passed"}
    assert not failed, f"{name}: generated tests not passing: {failed}"
