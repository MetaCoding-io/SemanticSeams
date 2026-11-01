"""The "Write your own generator" guide's generator runs on both example models (M010/S07).

The `# checklist.py` block in docs/guide/write-your-own-generator.md is extracted and
executed as written, so the guide cannot drift from the seams API: its chat-app output
must equal the guide's text block, and it must cover the expenses model's processes and
decision rules.

The "Start from a reference output" section (M018/S04) is run the same way: its
reference goes through its `seams new-generator` command, which must print the guide's
text block, and the template, `extract` and golden it shows must pass the scaffold's
golden test on chat-app and fail it on the expenses model.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import seams

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs/guide/write-your-own-generator.md"
CHAT = "examples/chat-app/chat-app.trig"
EXPENSES = "examples/expenses/chapter-08"

CODE_BLOCK = re.compile(r"^```python\n(# checklist\.py\n.*?)^```$", re.M | re.S)
TEXT_BLOCK = re.compile(r"^```text\n(.*?)^```$", re.M | re.S)
REFERENCE_SECTION = re.compile(r"^## Start from a reference output\n(.*?)^## ", re.M | re.S)
FENCE = re.compile(r"^```(\w+)\n(.*?)^```$", re.M | re.S)


def extract(markdown: str) -> tuple[str, str]:
    """The `# checklist.py` source and the first text block after it."""
    blocks = list(CODE_BLOCK.finditer(markdown))
    assert len(blocks) == 1, (
        f"{GUIDE.relative_to(ROOT)} must have exactly one ```python block starting "
        f"with '# checklist.py', found {len(blocks)}"
    )
    output = TEXT_BLOCK.search(markdown, blocks[0].end())
    assert output is not None, f"{GUIDE.relative_to(ROOT)} has no ```text block after the checklist.py block"
    return blocks[0].group(1), output.group(1)


@pytest.fixture(scope="module")
def guide() -> tuple[str, str]:
    assert GUIDE.is_file(), f"missing guide {GUIDE.relative_to(ROOT)}"
    return extract(GUIDE.read_text())


@pytest.fixture(scope="module")
def script(guide: tuple[str, str], tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("guide") / "checklist.py"
    path.write_text(guide[0])
    return path


def env_without_model() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("SEAMS_MODEL", None)
    return env


def run(script: Path, *args: str, env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=env_without_model() if env is None else env,
        capture_output=True,
        text=True,
        check=check,
    )


def test_chat_app_output_matches_the_guide(guide: tuple[str, str], script: Path):
    out = run(script, CHAT).stdout
    assert out == guide[1], "chat-app output differs from the guide's text block; regenerate it by running the script"


def test_output_is_deterministic(script: Path):
    for model in (CHAT, EXPENSES):
        assert run(script, model).stdout == run(script, model).stdout, f"two runs on {model} differ"


def test_expenses_output_names_both_processes_and_a_rule(script: Path):
    out = run(script, EXPENSES).stdout
    model = seams.load(ROOT / EXPENSES)
    labels = [p.label for p in model.processes]
    assert len(labels) == 2, f"expected two processes in {EXPENSES}, found {labels}"
    for label in labels:
        assert f"## {label}" in out, f"checklist for {EXPENSES} does not name process {label!r}"
    rule_ids = [rule.id for d in model.decisions for rule in d.table.rules]
    assert any(rule_id in out for rule_id in rule_ids), (
        f"checklist for {EXPENSES} names none of the DMN rules {rule_ids}"
    )


def test_seams_model_env_is_the_fallback(script: Path):
    env = env_without_model() | {"SEAMS_MODEL": CHAT}
    assert run(script, env=env).stdout == run(script, CHAT).stdout


def test_no_model_is_a_usage_error(script: Path):
    result = run(script, check=False)
    assert result.returncode == 2, result.stderr
    assert "SEAMS_MODEL" in result.stderr
    assert result.stdout == ""


def test_missing_model_path_is_a_usage_error(script: Path):
    result = run(script, "examples/no-such-model.trig", check=False)
    assert result.returncode == 2, result.stderr
    assert "no-such-model.trig" in result.stderr


def test_generator_imports_only_seams(script: Path):
    code = (
        "import runpy, sys, seams\n"
        f"ns = runpy.run_path({str(script)!r}, run_name='checklist')\n"
        f"ns['checklist'](seams.load({CHAT!r}))\n"
        "loaded = [m for m in ('SpiffWorkflow', 'fastapi', 'seams_runtime') if m in sys.modules]\n"
        "assert not loaded, f'the guide generator imported {loaded}'\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env_without_model(), check=True)


def test_extract_rejects_a_guide_without_the_block():
    with pytest.raises(AssertionError, match="exactly one"):
        extract("# Guide\n\n```python\nprint('hi')\n```\n")


def test_extract_rejects_two_blocks():
    block = "```python\n# checklist.py\nprint('hi')\n```\n\n```text\nhi\n```\n"
    with pytest.raises(AssertionError, match="found 2"):
        extract(block + block)


@pytest.fixture(scope="module")
def walkthrough() -> dict[str, list[str]]:
    """The fenced blocks of the "Start from a reference output" section, by language."""
    section = REFERENCE_SECTION.search(GUIDE.read_text())
    assert section is not None, f"{GUIDE.relative_to(ROOT)} has no '## Start from a reference output' section"
    blocks: dict[str, list[str]] = {}
    for language, body in FENCE.findall(section.group(1)):
        blocks.setdefault(language, []).append(body)
    counts = {language: len(bodies) for language, bodies in blocks.items()}
    assert counts == {"yaml": 3, "sh": 1, "text": 1, "python": 1}, (
        "expected the reference, template and golden (yaml), the command (sh), its output (text) "
        f"and extract (python) in the section, found {counts}"
    )
    return blocks


def run_scaffold_tests(package: Path, model: str | None = None) -> subprocess.CompletedProcess:
    env = env_without_model() | {"PYTHONPATH": str(package)}
    if model is not None:
        env["SEAMS_MODEL"] = str(ROOT / model)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=package,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def scaffold(walkthrough: dict[str, list[str]], tmp_path_factory: pytest.TempPathFactory):
    """Run the section's command on its reference; (working directory, package, stdout)."""
    args = shlex.split(walkthrough["sh"][0])
    assert args[:2] == ["seams", "new-generator"], f"unexpected command {args}"
    cwd = tmp_path_factory.mktemp("reference-first")
    (cwd / args[args.index("--reference") + 1]).write_text(walkthrough["yaml"][0])
    result = subprocess.run(
        [sys.executable, "-m", "seams_cli", *args[1:]],
        cwd=cwd,
        env=env_without_model(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return cwd, cwd / f"seams-{args[2]}", result.stdout


def test_new_generator_prints_the_guides_layout(walkthrough: dict[str, list[str]], scaffold):
    _, _, stdout = scaffold
    assert stdout == walkthrough["text"][0], "seams new-generator output differs from the guide's text block"


def test_reference_first_loop_runs_as_written(walkthrough: dict[str, list[str]], scaffold):
    _, package, _ = scaffold
    result = run_scaffold_tests(package)
    assert result.returncode == 0, "the scaffold's test fails as generated:\n" + result.stdout + result.stderr

    _, template, golden = walkthrough["yaml"]
    name = package.name.removeprefix("seams-")
    module = package / f"seams_{name}" / "__init__.py"
    source, count = re.subn(
        r"^def extract\(.*?\n\n\n", lambda _: walkthrough["python"][0] + "\n\n", module.read_text(), flags=re.M | re.S
    )
    assert count == 1, f"no extract function in {module}"
    assert "`import json`" in GUIDE.read_text(), "the guide no longer tells the reader to import json"
    module.write_text(source.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n", 1))
    reference = next((package / f"seams_{name}" / "templates").iterdir()).name
    (package / f"seams_{name}" / "templates" / reference).write_text(template)
    (package / "tests" / "golden" / reference).write_text(golden)

    result = run_scaffold_tests(package)
    assert result.returncode == 0, "the guide's template, extract and golden fail:\n" + result.stdout + result.stderr

    result = run_scaffold_tests(package, EXPENSES)
    assert result.returncode != 0, "the golden test passes on the expenses model; the template still restates it"
    for process in seams.load(ROOT / EXPENSES).processes:
        assert process.label in result.stdout, f"the expenses diff does not name {process.label!r}"
