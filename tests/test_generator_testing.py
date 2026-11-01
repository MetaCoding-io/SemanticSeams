"""The generator test kit (M018/S03, backlog K4): seams_gen.testing compares an
output with its golden, checks a generator is deterministic and syntax-checks
an output by file type, with failures that name the file, the generator and
the line.
"""

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import model_hash  # noqa: E402

from seams_gen import builtin  # noqa: E402
from seams_gen.htmx import generate_page  # noqa: E402
from seams_gen.protocol import Generator  # noqa: E402
from seams_gen.testing import assert_deterministic, assert_matches_golden, check_output  # noqa: E402

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
GOLDEN = ROOT / "docs" / "generation" / "golden"
HASH = "sha256:" + "0123456789abcdef" * 4


# --- assert_matches_golden -------------------------------------------------


def test_built_in_page_matches_its_golden():
    assert_matches_golden(generate_page(TRIG), GOLDEN / "chat_page.html", model_hash(TRIG))


def test_golden_match_fills_the_hash_placeholder(tmp_path):
    golden = tmp_path / "out.yaml"
    golden.write_text("# model-hash: sha256:<model-hash>  # [fixed]\na: 1  # [graph: :a]\n", encoding="utf-8")
    assert_matches_golden(f"# model-hash: {HASH}\na: 1\n", golden, HASH)


def test_golden_mismatch_names_the_file_and_line_with_a_diff(tmp_path):
    golden = tmp_path / "out.yaml"
    golden.write_text("a: 1  # [graph: :a]\nb: 2  # [graph: :b]\nc: 3  # [fixed]\n", encoding="utf-8")
    with pytest.raises(AssertionError) as caught:
        assert_matches_golden("a: 1\nb: 20\nc: 3\n", golden, HASH)
    message = str(caught.value)
    assert f"output differs from golden {golden} at line 2:" in message
    assert f"--- {golden}" in message
    assert "+++ generated" in message
    assert "-b: 2\n" in message
    assert "+b: 20\n" in message


def test_golden_mismatch_on_the_final_newline_is_reported(tmp_path):
    golden = tmp_path / "out.py"
    golden.write_text("x = 1  # [fixed]\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"at line 1:"):
        assert_matches_golden("x = 1", golden, HASH)


def test_golden_mismatch_on_extra_lines_names_the_first_extra(tmp_path):
    golden = tmp_path / "out.py"
    golden.write_text("x = 1  # [fixed]\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"at line 2:"):
        assert_matches_golden("x = 1\ny = 2\n", golden, HASH)


# --- assert_deterministic --------------------------------------------------


def _toy(render, name="toy"):
    return Generator(
        name=name,
        version="0.0.1",
        help="a test generator",
        extract=lambda trig, out: Path(trig).name,
        render=render,
        sources=lambda trig, out: {},
    )


def test_built_in_generator_is_deterministic():
    assert_deterministic(builtin.fastapi, TRIG)


def test_counter_based_output_is_caught():
    counter = itertools.count()
    gen = _toy(lambda view: {"a.txt": "same\n", "b.txt": f"{view}\nrun {next(counter)}\n"}, name="counting")
    with pytest.raises(AssertionError) as caught:
        assert_deterministic(gen, TRIG)
    assert str(caught.value) == "generator 'counting' is not deterministic: b.txt differs between two runs at line 2"


def test_varying_file_set_is_caught():
    counter = itertools.count()
    gen = _toy(lambda view: {f"run{next(counter)}.txt": "x\n"}, name="naming")
    with pytest.raises(AssertionError) as caught:
        assert_deterministic(gen, TRIG)
    assert str(caught.value) == "generator 'naming' is not deterministic: run0.txt is produced only by the first run"


def test_out_is_passed_to_generate():
    seen = []
    gen = Generator(
        name="seeing",
        version="0.0.1",
        help="records out",
        extract=lambda trig, out: seen.append(out),
        render=lambda view: {},
        sources=lambda trig, out: {},
    )
    assert_deterministic(gen, TRIG, Path("build"))
    assert seen == [Path("build"), Path("build")]


# --- check_output ----------------------------------------------------------


@pytest.mark.parametrize(
    "name, text",
    [
        ("app.py", "def f():\n    return 1\n"),
        ("compose.yaml", "a: 1\n---\nb: [1, 2]\n"),
        ("ci.yml", "on: push\n"),
        ("doc.json", '{"a": [1, 2]}\n'),
        ("page.html", "<p>{{ x }}</p>\n{% if y %}<b>y</b>{% endif %}\n"),
    ],
)
def test_well_formed_outputs_pass(name, text):
    check_output(Path("out") / name, text)


@pytest.mark.parametrize(
    "name, text, expected",
    [
        ("app.py", "x = 1\ndef f(:\n", r"^out/app\.py:2: not valid Python: "),
        ("compose.yaml", "a: 1\nb: [1, 2\n", r"^out/compose\.yaml:3: not valid YAML: "),
        ("ci.yml", "a: 1\n---\n  b: 1\n c: 2\n", r"^out/ci\.yml:4: not valid YAML: "),
        ("doc.json", '{\n  "a": 1,\n}\n', r"^out/doc\.json:3: not valid JSON: "),
        ("page.html", "<p>\n{{ x }}\n{{ x + }}\n", r"^out/page\.html:3: not a valid Jinja2 template: "),
    ],
)
def test_malformed_outputs_name_the_file_and_line(name, text, expected):
    with pytest.raises(AssertionError, match=expected):
        check_output(Path("out") / name, text)


def test_unknown_suffix_is_a_value_error():
    with pytest.raises(ValueError, match=r"out/notes\.txt: no output checker for '\.txt'"):
        check_output(Path("out") / "notes.txt", "hello\n")


def test_every_built_in_htmx_output_parses():
    for name, text in builtin.htmx.generate(TRIG, Path("generated")).items():
        check_output(name, text)
