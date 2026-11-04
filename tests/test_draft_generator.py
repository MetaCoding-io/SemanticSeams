"""``seams draft-generator`` (M025/S02, backlog R3, ADR-0029) with fake provider commands.

The project is a copy of the chat-app example's model; the reference is
tests/fixtures/draft_generator/processes.yaml, the chat app's processes as a
person would write them. No provider but the fakes beside it runs, and no
network. The scratch golden test and the written package's own tests run with
a subprocess pytest, PYTHONPATH set to the package, as an author would.
"""

from __future__ import annotations

import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main
from seams_cli.draft_generator import (
    CACHE_DIR,
    Draft,
    DraftGeneratorError,
    assemble,
    build_prompt,
    check_extract,
    check_template,
    draft_generator,
    parse_answer,
)
from seams_cli.project import ProjectError, load_project

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples" / "chat-app"
FIXTURES = ROOT / "tests" / "fixtures" / "draft_generator"
REFERENCE = FIXTURES / "processes.yaml"
ANSWERS = runpy.run_path(str(FIXTURES / "answers.py"))
EXTRACT, TEMPLATE, GOLDEN, GOOD = (ANSWERS[key] for key in ("EXTRACT", "TEMPLATE", "GOLDEN", "GOOD"))

EXPECTED = [
    "pyproject.toml",
    "seams_procs/__init__.py",
    "seams_procs/templates/processes.yaml",
    "tests/golden/processes.yaml",
    "tests/test_procs.py",
]


def _provider(name: str, *args: str) -> str:
    return shlex.join([sys.executable, str(FIXTURES / name), *args])


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def app(tmp_path) -> Path:
    root = tmp_path / "chat-app"
    shutil.copytree(CHAT, root, ignore=shutil.ignore_patterns("generated", "__pycache__", "seams.toml", "seams.lock"))
    (root / "seams.toml").write_text('model = "chat-app.trig"\n', encoding="utf-8")
    return root


def _files(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def _run_package_tests(out: Path, model: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(out), "SEAMS_MODEL": str(model)}
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    return subprocess.run(argv, cwd=out, env=env, capture_output=True, text=True, check=False)


# ── the prompt ──


def test_the_prompt_quotes_the_reference_names_and_package_and_is_deterministic(app):
    model = seams.load(app / "chat-app.trig")
    first = build_prompt("procs", REFERENCE, model)
    assert first == build_prompt("procs", REFERENCE, model)
    assert first.template == "draft-generator-v1"
    assert first.model_hash == model.hash
    assert first.sha256.startswith("sha256:")
    text = first.text
    assert "```DATA reference processes.yaml\n" + REFERENCE.read_text(encoding="utf-8") + "```" in text
    assert "https://example.org/chat/send_message_process\tSend Message Process\n" in text
    assert "```DATA package\n" in text and "def extract(trig: Path, out: Path) -> dict:" in text
    assert "$" not in text.replace("$extract", "")
    lines = text.split("```DATA names\n", 1)[1].split("```", 1)[0].splitlines()
    assert lines == sorted(lines) and len(lines) == len(set(lines))


# ── the answer ──


def test_one_fenced_json_object_is_read():
    draft = parse_answer("```json\n" + json.dumps(GOOD) + "\n```\n")
    assert draft == Draft(extract=EXTRACT, template=TEMPLATE, golden=GOLDEN)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "the answer is not JSON"),
        ('["extract"]', "not a JSON object"),
        ('{"extract": "", "template": ""}', "the answer has no `golden`"),
        ('{"extract": "", "template": 1, "golden": ""}', "the answer's `template` is not a string"),
        ('{"extract": "", "template": "", "golden": "", "notes": ""}', "the unknown key `notes`"),
    ],
)
def test_a_malformed_answer_names_the_key(text, message):
    with pytest.raises(DraftGeneratorError, match=message):
        parse_answer(text)


@pytest.mark.parametrize(
    ("line", "shown"),
    [
        ("[% if processes %]", "[% if processes %]"),
        ("[% set x = 1 %]", "[% set x = 1 %]"),
        ("label: [[ process.label | upper ]]", "| upper"),
        ("label: [[ label() ]]", "label()"),
        ("label: [[ a + b ]]", "a + b"),
        ("[# a comment #]", "[# a comment #]"),
        ("label: [[ process.label", "[[ process.label"),
    ],
)
def test_template_logic_is_refused_naming_the_line(line, shown):
    template = f"processes:\n{line}\n"
    with pytest.raises(DraftGeneratorError, match=r"template line 2: holds logic") as err:
        check_template(template, "processes:\n", ())
    assert shown in str(err.value)


def test_loops_and_values_are_allowed():
    check_template(TEMPLATE, REFERENCE.read_text(encoding="utf-8"), ())


def test_a_restated_label_is_refused_only_when_the_reference_holds_it():
    names = [("https://example.org/chat/send_message_process", "Send Message Process")]
    template = 'label: "Send Message Process"\n'
    with pytest.raises(DraftGeneratorError, match="template line 1: restates the model label 'Send Message Process'"):
        check_template(template, REFERENCE.read_text(encoding="utf-8"), names)
    check_template(template, "processes: []\n", names)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def extract(trig, out):\n    return {\n", "`extract` line 2: not Python"),
        ("from __future__ import annotations\n" + EXTRACT, "`extract` line 1: a __future__ import"),
        (EXTRACT + "\n\ndef render(view):\n    return {}\n", "defines `render`, which the scaffold's package owns"),
        ("import json\n", "defines no top-level `def extract"),
    ],
)
def test_an_extract_step_that_cannot_stand_in_the_package_is_refused(source, message):
    with pytest.raises(DraftGeneratorError, match=message):
        check_extract(source)


def test_assemble_replaces_only_the_extract_step_template_and_golden(tmp_path):
    from seams_cli.new_generator import scaffold

    files = assemble("procs", REFERENCE, Draft(EXTRACT, TEMPLATE, GOLDEN))
    plain = scaffold("procs", REFERENCE)
    assert sorted(files) == EXPECTED
    assert files["pyproject.toml"] == plain["pyproject.toml"]
    assert files["tests/test_procs.py"] == plain["tests/test_procs.py"]
    assert files["seams_procs/templates/processes.yaml"] == TEMPLATE
    assert files["tests/golden/processes.yaml"] == GOLDEN
    module = files["seams_procs/__init__.py"]
    assert EXTRACT.strip("\n") in module and 'return {"model_hash": model.hash}\n' not in module
    assert module.split("def render(")[1] == plain["seams_procs/__init__.py"].split("def render(")[1]


# ── draft_generator ──


def test_a_good_draft_writes_the_package_whose_tests_pass(app, tmp_path):
    out = tmp_path / "out"
    done = draft_generator(load_project(app), "procs", REFERENCE, _provider("good_provider.py"), out)
    assert not done.cache_hit
    assert done.template == "draft-generator-v1"
    assert done.written == tuple(out / rel for rel in EXPECTED)
    files = _files(out)
    assert sorted(files) == EXPECTED
    template = files["seams_procs/templates/processes.yaml"].decode("utf-8")
    assert template == TEMPLATE != REFERENCE.read_text(encoding="utf-8")
    result = _run_package_tests(out, app / "chat-app.trig")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    assert len(list((app / CACHE_DIR).glob("*.json"))) == 1


def test_a_cache_hit_calls_no_provider_and_gives_the_same_package(app, tmp_path):
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    project = load_project(app)
    first = draft_generator(project, "procs", REFERENCE, provider, tmp_path / "one")
    second = draft_generator(project, "procs", REFERENCE, provider, tmp_path / "two")
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert (tmp_path / "calls").read_text() == "1"
    assert first.prompt_sha256 == second.prompt_sha256
    assert _files(tmp_path / "one") == _files(tmp_path / "two")


def test_a_changed_model_misses_the_cache(app, tmp_path):
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    draft_generator(load_project(app), "procs", REFERENCE, provider, tmp_path / "one")
    trig = app / "chat-app.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(DraftGeneratorError, match="called again"):
        draft_generator(load_project(app), "procs", REFERENCE, provider, tmp_path / "two")
    assert not (tmp_path / "two").exists()


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        ("golden", r"tests failed:\ntests/test_procs.py::test_output_matches_golden - AssertionError"),
        ("logic", r"template line 5: holds logic .*\| upper"),
        (
            "restates",
            "template line 5: restates the model label 'Send Message Process' of "
            "https://example.org/chat/send_message_process",
        ),
        ("missing", "the answer has no `golden`"),
        ("malformed", "the answer is not JSON"),
    ],
)
def test_a_refused_draft_writes_nothing_and_names_the_fact(app, tmp_path, variant, message):
    out = tmp_path / "out"
    with pytest.raises(DraftGeneratorError, match=message) as err:
        draft_generator(load_project(app), "procs", REFERENCE, _provider("bad_provider.py", variant), out)
    assert not out.exists()
    assert not (app / CACHE_DIR).exists()
    assert "seams-draft-generator-" not in str(err.value)
    if variant == "golden":
        assert err.value.failures == ("tests/test_procs.py::test_output_matches_golden",)


def test_no_provider_is_a_project_error(app, tmp_path):
    with pytest.raises(ProjectError, match=r"no provider: set `\[propose\] provider`"):
        draft_generator(load_project(app), "procs", REFERENCE, None, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_project_provider_is_the_default(app, tmp_path):
    (app / "seams.toml").write_text(
        f'model = "chat-app.trig"\n\n[propose]\nprovider = {json.dumps(_provider("good_provider.py"))}\n',
        encoding="utf-8",
    )
    done = draft_generator(load_project(app), "procs", REFERENCE, out=tmp_path / "out")
    assert done.provider == _provider("good_provider.py")


def test_a_failing_provider_writes_nothing(app, tmp_path):
    provider = shlex.join([sys.executable, "-c", "import sys; sys.exit('no key')"])
    with pytest.raises(DraftGeneratorError, match="exited 1: no key"):
        draft_generator(load_project(app), "procs", REFERENCE, provider, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not (app / CACHE_DIR).exists()


def test_a_bad_name_or_reference_is_refused_before_the_provider(app, tmp_path):
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    with pytest.raises(DraftGeneratorError, match="generator name 'Procs'"):
        draft_generator(load_project(app), "Procs", REFERENCE, provider, tmp_path / "out")
    with pytest.raises(DraftGeneratorError, match="no such file"):
        draft_generator(load_project(app), "procs", tmp_path / "missing.yaml", provider, tmp_path / "out")
    assert not (tmp_path / "calls").exists()


def test_a_non_empty_out_needs_force(app, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "README.md").write_text("mine\n", encoding="utf-8")
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    with pytest.raises(DraftGeneratorError, match="directory is not empty; pass --force"):
        draft_generator(load_project(app), "procs", REFERENCE, provider, out)
    assert not (tmp_path / "calls").exists()
    draft_generator(load_project(app), "procs", REFERENCE, provider, out, force=True)
    assert sorted(_files(out)) == sorted(["README.md", *EXPECTED])
    assert (out / "README.md").read_text(encoding="utf-8") == "mine\n"


# ── the command ──


def test_the_command_prints_the_prompt_hash_cache_state_and_written_paths(app, tmp_path, capsys):
    out = tmp_path / "out"
    argv = ["draft-generator", "procs", "--reference", str(REFERENCE), "--project", str(app)]
    provider = ["--provider", _provider("good_provider.py", str(tmp_path / "calls"))]
    assert main([*argv, *provider, "--out", str(out)]) == 0
    lines = capsys.readouterr().out.splitlines()
    prompt = build_prompt("procs", REFERENCE, seams.load(app / "chat-app.trig"))
    assert lines[:4] == [
        "template draft-generator-v1",
        f"provider {provider[1]}",
        f"prompt {prompt.sha256}",
        "cache miss",
    ]
    assert lines[4:] == [str(out.resolve() / rel) for rel in EXPECTED]
    assert main([*argv, *provider, "--out", str(tmp_path / "two")]) == 0
    assert "cache hit" in capsys.readouterr().out.splitlines()
    assert (tmp_path / "calls").read_text() == "1"


def test_the_command_reports_failed_tests_on_stderr_and_exits_1(app, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "draft-generator",
            "procs",
            "--reference",
            str(REFERENCE),
            "--project",
            str(app),
            "--provider",
            _provider("bad_provider.py", "golden"),
            "--out",
            str(out),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("seams draft-generator: ")
    assert "tests/test_procs.py::test_output_matches_golden" in captured.err
    assert not out.exists()


def test_the_command_without_a_provider_exits_1(app, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["draft-generator", "procs", "--reference", str(REFERENCE), "--project", str(app), "--out", str(out)])
    assert code == 1
    assert capsys.readouterr().err.startswith("seams draft-generator: no provider: set `[propose] provider`")
    assert not out.exists()


def test_the_command_refuses_a_non_empty_out_without_force(app, tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "README.md").write_text("mine\n", encoding="utf-8")
    argv = ["draft-generator", "procs", "--reference", str(REFERENCE), "--project", str(app), "--out", str(out)]
    provider = ["--provider", _provider("good_provider.py")]
    assert main([*argv, *provider]) == 1
    assert "pass --force" in capsys.readouterr().err
    assert main([*argv, *provider, "--force"]) == 0
    assert sorted(_files(out)) == sorted(["README.md", *EXPECTED])
