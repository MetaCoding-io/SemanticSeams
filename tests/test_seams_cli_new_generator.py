"""`seams new-generator` scaffolds a generator from a reference output (M018/S04, backlog K5).

The scaffold's own golden test is run with a subprocess pytest, PYTHONPATH set
to the scaffold, as an author would run it before installing the package.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from seams_cli.__main__ import main

from seams_gen.testing import golden_target

REFERENCE = """\
# A reference output, written by hand.
service:
  name: "example"  # an existing comment
  url: "http://host/path#fragment"

  ports:
    - 8080
"""

EXPECTED = [
    "pyproject.toml",
    "seams_sample/__init__.py",
    "seams_sample/templates/sample.yaml",
    "tests/golden/sample.yaml",
    "tests/test_sample.py",
]


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _reference(tmp_path: Path, text: str = REFERENCE, name: str = "sample.yaml") -> Path:
    path = tmp_path / "ref" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _files(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def _scaffold(tmp_path: Path, capsys, name: str = "sample") -> Path:
    out = tmp_path / "out"
    assert main(["new-generator", name, "--reference", str(_reference(tmp_path)), "--out", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [str(out / rel) for rel in EXPECTED]
    return out


def test_scaffold_writes_the_package_and_prints_each_path(tmp_path, capsys):
    out = _scaffold(tmp_path, capsys)
    files = _files(out)
    assert sorted(files) == EXPECTED
    assert files["seams_sample/templates/sample.yaml"] == REFERENCE.encode()
    golden = files["tests/golden/sample.yaml"].decode().split("\n")
    for line, original in zip(golden, REFERENCE.split("\n"), strict=True):
        assert line == (original + "  # [fixed]" if original.strip() else original)


def test_scaffold_registers_the_generator_entry_point(tmp_path, capsys):
    out = _scaffold(tmp_path, capsys)
    project = tomllib.loads((out / "pyproject.toml").read_text())
    assert project["project"]["name"] == "seams-sample"
    assert "semanticseams" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["seams.generators"] == {"sample": "seams_sample:generator"}


def test_scaffolded_golden_test_passes_as_generated(tmp_path, capsys):
    out = _scaffold(tmp_path, capsys)
    env = {k: v for k, v in os.environ.items() if k != "SEAMS_MODEL"}
    env["PYTHONPATH"] = str(out)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_sample.py"],
        cwd=out,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout


def test_two_runs_are_byte_identical(tmp_path, capsys):
    reference = _reference(tmp_path)
    for out in ("one", "two"):
        assert main(["new-generator", "sample", "--reference", str(reference), "--out", str(tmp_path / out)]) == 0
    assert _files(tmp_path / "one") == _files(tmp_path / "two")


def test_out_defaults_to_seams_name_in_the_working_directory(tmp_path, capsys, monkeypatch):
    reference = _reference(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["new-generator", "sample", "--reference", str(reference)]) == 0
    assert capsys.readouterr().out.splitlines() == [f"seams-sample/{rel}" for rel in EXPECTED]


def test_an_existing_empty_out_directory_is_used(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    assert main(["new-generator", "sample", "--reference", str(_reference(tmp_path)), "--out", str(out)]) == 0
    assert sorted(_files(out)) == EXPECTED


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("page.html", "<!doctype html>\n<p>{{ message }}</p>  {# a comment #}\n"),
        ("module.py", 'TITLE = "a # b"  # a comment\n\n\ndef f():\n    return 1\n'),
        ("compose.yml", "services:\n  app: {}\n"),
    ],
)
def test_golden_strips_back_to_the_template_for_each_suffix(tmp_path, capsys, name, text):
    out = tmp_path / "out"
    reference = _reference(tmp_path, text, name)
    assert main(["new-generator", "kit", "--reference", str(reference), "--out", str(out)]) == 0
    template = (out / "seams_kit" / "templates" / name).read_text()
    assert template == text
    assert golden_target(out / "tests" / "golden" / name, "sha256:0") == text


@pytest.mark.parametrize(
    ("args", "text", "message"),
    [
        (["Bad-Name"], REFERENCE, "generator name 'Bad-Name' must be lowercase"),
        (["9lives"], REFERENCE, "generator name '9lives' must be lowercase"),
        (["sample"], "a: 1  # [fixed]\n", "already carries a producibility marker"),
        (["sample"], "a: 1  # [graph: :x]\n", "already carries a producibility marker"),
        (["sample"], "a: 1 \n", "ends in whitespace"),
        (["sample"], "a: 1\r\nb: 2\r\n", "ends in whitespace"),
        (["sample"], "a: [[ 1 ]]\n", "holds the template delimiter '[['"),
        (["sample"], "a: '[% x'\n", "holds the template delimiter '[%'"),
        (["sample"], "a: [1\n", "the reference must parse as its file type"),
        (["sample"], "\n  \n", "has no non-blank line"),
    ],
)
def test_refused_input_exits_2_and_writes_nothing(tmp_path, capsys, args, text, message):
    out = tmp_path / "out"
    reference = _reference(tmp_path, text)
    assert main(["new-generator", *args, "--reference", str(reference), "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("seams new-generator: ")
    assert message in captured.err
    assert not out.exists()


def test_unknown_suffix_exits_2(tmp_path, capsys):
    out = tmp_path / "out"
    reference = _reference(tmp_path, "text\n", "notes.txt")
    assert main(["new-generator", "sample", "--reference", str(reference), "--out", str(out)]) == 2
    assert "no golden comment syntax for '.txt'" in capsys.readouterr().err
    assert not out.exists()


def test_missing_reference_exits_2(tmp_path, capsys):
    out = tmp_path / "out"
    reference = tmp_path / "absent.yaml"
    assert main(["new-generator", "sample", "--reference", str(reference), "--out", str(out)]) == 2
    assert f"seams new-generator: {reference}: no such file" in capsys.readouterr().err
    assert not out.exists()


def test_non_utf8_reference_exits_2(tmp_path, capsys):
    out = tmp_path / "out"
    reference = tmp_path / "latin.yaml"
    reference.write_bytes(b"a: \xe9\n")
    assert main(["new-generator", "sample", "--reference", str(reference), "--out", str(out)]) == 2
    assert "not UTF-8 text" in capsys.readouterr().err
    assert not out.exists()


def test_non_empty_out_exits_2_and_leaves_it_untouched(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("mine\n")
    assert main(["new-generator", "sample", "--reference", str(_reference(tmp_path)), "--out", str(out)]) == 2
    assert f"seams new-generator: {out}: directory is not empty" in capsys.readouterr().err
    assert _files(out) == {"keep.txt": b"mine\n"}


def test_out_that_is_a_file_exits_2(tmp_path, capsys):
    out = tmp_path / "out"
    out.write_text("a file\n")
    assert main(["new-generator", "sample", "--reference", str(_reference(tmp_path)), "--out", str(out)]) == 2
    assert "exists and is not a directory" in capsys.readouterr().err
    assert out.read_text() == "a file\n"
