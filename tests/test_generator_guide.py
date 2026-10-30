"""The "Write your own generator" guide's generator runs on both example models (M010/S07).

The `# checklist.py` block in docs/guide/write-your-own-generator.md is extracted and
executed as written, so the guide cannot drift from the seams API: its chat-app output
must equal the guide's text block, and it must cover the expenses model's processes and
decision rules.
"""

import os
import re
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
