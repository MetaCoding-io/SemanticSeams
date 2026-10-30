"""The committed generated outputs equal what the generators produce now.

examples/chat-app/generated/ (route module and templates) and the root
compose.yaml are committed so the docker images and `docker compose up` use
stable paths. Each test regenerates through the same entry point CI uses and
compares against the committed copy: the same set of files (no stale extra
file survives) and byte-equal contents. A mismatch fails with a unified diff
naming the committed path and the command that regenerates it.
"""

from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from seams_gen import generate_compose
from seams_gen.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "chat-app"
TRIG = EXAMPLE / "chat-app.trig"
GENERATED = EXAMPLE / "generated"
TEMPLATES = GENERATED / "templates"
COMPOSE = ROOT / "compose.yaml"

TRIG_ARG = "examples/chat-app/chat-app.trig"
COMMANDS = {
    "fastapi": f"python -m seams_gen fastapi {TRIG_ARG} --out examples/chat-app/generated",
    "htmx": f"python -m seams_gen htmx {TRIG_ARG} --out examples/chat-app/generated/templates",
    "compose": f"python -m seams_gen compose {TRIG_ARG} --out .",
}
# Files in examples/chat-app/generated/ that no generator writes.
HAND_WRITTEN = {"README.md"}


def committed_files(directory: Path, ignore=frozenset()) -> dict[str, str]:
    """{file name: text} of the regular files directly in ``directory``."""
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(directory.iterdir())
        if p.is_file() and p.name not in ignore
    }


def regenerate(generator: str, trig: Path, out: Path) -> dict[str, str]:
    """Run the CLI into ``out`` (empty) and return {file name: text}."""
    assert main([generator, str(trig), "--out", str(out)]) == 0
    return committed_files(out)


def output_diffs(generated: dict[str, str], committed: dict[str, str], committed_dir: Path, command: str) -> list[str]:
    """Problems with the committed copy, each naming its path; empty when current."""
    problems = []
    rel = committed_dir.relative_to(ROOT)
    for name in sorted(generated.keys() - committed.keys()):
        problems.append(f"{rel / name} is generated but not committed; run: {command}")
    for name in sorted(committed.keys() - generated.keys()):
        problems.append(f"{rel / name} is committed but no longer generated; delete it and run: {command}")
    for name in sorted(generated.keys() & committed.keys()):
        if generated[name] != committed[name]:
            path = str(rel / name)
            diff = "".join(
                difflib.unified_diff(
                    committed[name].splitlines(keepends=True),
                    generated[name].splitlines(keepends=True),
                    fromfile=f"{path} (committed)",
                    tofile=f"{path} (regenerated)",
                )
            )
            problems.append(f"{path} is stale; run: {command}\n{diff}")
    return problems


def assert_current(generated, committed, committed_dir, command):
    problems = output_diffs(generated, committed, committed_dir, command)
    assert not problems, "\n".join(problems)


def test_route_module_is_current(tmp_path):
    assert_current(
        regenerate("fastapi", TRIG, tmp_path), committed_files(GENERATED, HAND_WRITTEN), GENERATED, COMMANDS["fastapi"]
    )


def test_templates_are_current(tmp_path):
    assert_current(regenerate("htmx", TRIG, tmp_path), committed_files(TEMPLATES), TEMPLATES, COMMANDS["htmx"])


def test_compose_file_is_current():
    # Bind-mount sources are relative to the output directory, so compare the
    # repository-root rendering with the committed root compose.yaml.
    generated = {"compose.yaml": generate_compose(TRIG, base_dir=ROOT)}
    assert_current(generated, {"compose.yaml": COMPOSE.read_text(encoding="utf-8")}, ROOT, COMMANDS["compose"])


def test_generated_readme_names_the_regenerate_commands():
    readme = (GENERATED / "README.md").read_text(encoding="utf-8")
    assert "Do not edit" in readme
    for command in COMMANDS.values():
        assert command in readme


def test_checker_reports_a_model_edit(tmp_path):
    # Copy the whole example: seam:renderPayload IRIs resolve next to the trig.
    example = tmp_path / "chat-app"
    shutil.copytree(EXAMPLE, example, ignore=shutil.ignore_patterns("generated"))
    trig = example / "chat-app.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count('ifml:title "Chat"@en') == 1
    trig.write_text(text.replace('ifml:title "Chat"@en', 'ifml:title "Chat (edited)"@en'), encoding="utf-8")

    out = tmp_path / "templates"
    problems = output_diffs(regenerate("htmx", trig, out), committed_files(TEMPLATES), TEMPLATES, COMMANDS["htmx"])
    page = [p for p in problems if p.startswith("examples/chat-app/generated/templates/chat_page.html is stale")]
    assert len(page) == 1, problems
    assert COMMANDS["htmx"] in page[0]
    diff_lines = page[0].splitlines()
    assert any(line.startswith("+") and "Chat (edited)" in line for line in diff_lines)
    assert any(line.startswith("-") and "<title>Chat</title>" in line for line in diff_lines)


def test_checker_reports_stale_and_missing_files(tmp_path):
    generated = {"a.html": "x\n", "b.html": "y\n"}
    committed = {"b.html": "y\n", "old.html": "z\n"}
    problems = output_diffs(generated, committed, TEMPLATES, COMMANDS["htmx"])
    assert problems == [
        f"examples/chat-app/generated/templates/a.html is generated but not committed; run: {COMMANDS['htmx']}",
        f"examples/chat-app/generated/templates/old.html is committed but no longer generated; "
        f"delete it and run: {COMMANDS['htmx']}",
    ]
