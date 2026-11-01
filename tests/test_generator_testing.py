"""The generator test kit (M018/S03, backlog K4): seams_gen.testing compares an
output with its golden, checks a generator is deterministic and syntax-checks
an output by file type, with failures that name the file, the generator and
the line.
"""

import itertools
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import model_hash  # noqa: E402

from seams_gen import GeneratorError, builtin  # noqa: E402
from seams_gen.htmx import generate_page, generate_pages  # noqa: E402
from seams_gen.protocol import Generator  # noqa: E402
from seams_gen.testing import (  # noqa: E402
    SHAPES_FILE,
    assert_deterministic,
    assert_matches_golden,
    assert_shapes_catch,
    check_output,
    shape_violations,
)

TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
GOLDEN = ROOT / "docs" / "generation" / "golden"
HASH = "sha256:" + "0123456789abcdef" * 4
CHAT = Namespace("https://example.org/chat/")
IFML = Namespace("https://w3id.org/seams/ifml#")
CHAT_IFML = URIRef("urn:seams:graph:model:chat_ifml")


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


# --- shape_violations / assert_shapes_catch ---------------------------------


def _chat() -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(TRIG, format="trig")
    return ds


def _without_order() -> Dataset:
    """The chat app with a page component missing its ifml:order."""
    ds = _chat()
    ds.graph(CHAT_IFML).remove((CHAT.message_thread, IFML.order, None))
    return ds


def test_conforming_example_has_no_shape_violations():
    assert shape_violations(_chat(), SHAPES_FILE, sorted((ROOT / "ontology").glob("*.ttl"))) == []


def test_shape_violation_names_focus_path_and_message():
    found = shape_violations(_without_order(), SHAPES_FILE, sorted((ROOT / "ontology").glob("*.ttl")))
    assert [(f, p) for f, p, _m in found] == [(str(CHAT.message_thread), None)]
    assert all(message for _f, _p, message in found)


@pytest.mark.parametrize("model_path", [TRIG, None], ids=["model-path", "written"])
def test_shapes_catch_a_constrained_fault(model_path):
    assert_shapes_catch(
        generate_pages,
        _without_order(),
        subject=CHAT.message_thread,
        predicate=IFML.order,
        focus=CHAT.message_thread,
        model_path=model_path,
    )


def _raises(subject, predicate, detail=""):
    def extract(model):
        raise GeneratorError(subject, predicate, detail)

    return extract


def test_unconstrained_fault_reports_no_shape_violation():
    with pytest.raises(AssertionError) as caught:
        assert_shapes_catch(
            _raises(CHAT.chat_page, IFML.order),
            _chat(),
            subject=CHAT.chat_page,
            predicate=IFML.order,
            focus=CHAT.chat_page,
            model_path=TRIG,
        )
    assert str(caught.value) == f"no shape violation on {CHAT.chat_page}; shape results found:\n  (none)"


def test_violation_without_the_path_is_not_enough():
    with pytest.raises(AssertionError) as caught:
        assert_shapes_catch(
            generate_pages,
            _without_order(),
            subject=CHAT.message_thread,
            predicate=IFML.order,
            focus=CHAT.message_thread,
            path=IFML.order,
            model_path=TRIG,
        )
    message = str(caught.value)
    assert message.startswith(f"no shape violation on {CHAT.message_thread} {IFML.order}; shape results found:\n")
    assert f"\n  {CHAT.message_thread} -: A component of a page" in message


def test_extract_that_does_not_raise_is_reported():
    with pytest.raises(AssertionError) as caught:
        assert_shapes_catch(
            generate_pages,
            _chat(),
            subject=CHAT.message_thread,
            predicate=IFML.order,
            focus=CHAT.message_thread,
            model_path=TRIG,
        )
    assert str(caught.value) == f"generate_pages did not raise a GeneratorError on {CHAT.message_thread} {IFML.order}"


def test_raise_on_another_fact_is_reported():
    with pytest.raises(AssertionError, match=r"raised GeneratorError on .*chat_page .*, expected .*message_thread"):
        assert_shapes_catch(
            _raises(CHAT.chat_page, IFML.order),
            _without_order(),
            subject=CHAT.message_thread,
            predicate=IFML.order,
            focus=CHAT.message_thread,
            model_path=TRIG,
        )


def test_raise_without_the_match_is_reported():
    with pytest.raises(AssertionError, match=r"without 'two orders' in its detail"):
        assert_shapes_catch(
            _raises(CHAT.message_thread, IFML.order, "no order"),
            _without_order(),
            subject=CHAT.message_thread,
            predicate=IFML.order,
            focus=CHAT.message_thread,
            match="two orders",
            model_path=TRIG,
        )
