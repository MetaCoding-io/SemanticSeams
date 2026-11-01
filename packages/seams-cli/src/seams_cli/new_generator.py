"""``seams new-generator NAME --reference FILE [--out DIR]`` (M018/S04, backlog K5).

It turns a reference output, a file written by hand as the generator should
emit it, into a generator package whose golden test passes as written:

- ``pyproject.toml``: distribution ``seams-<name>``, registering
  ``<name> = "seams_<name>:generator"`` in the ``seams.generators`` group.
- ``seams_<name>/__init__.py``: the Generator. ``extract`` loads the model and
  returns the view model, a dict; ``render`` substitutes it into the template
  with the ``[[ ]]``/``[% %]`` delimiters of the built-ins; ``sources`` names
  no model element yet.
- ``seams_<name>/templates/<reference name>``: the reference, verbatim.
- ``tests/golden/<reference name>``: the reference with a ``[fixed]`` marker in
  a trailing comment on every non-blank line (``# ...`` for .py, .yaml and
  .yml, ``{# ... #}`` for .html).
- ``tests/test_<name>.py``: assert_matches_golden, assert_deterministic and
  check_output from seams_gen.testing, on the model named by ``SEAMS_MODEL``,
  else the chat-app example beside seams_gen.

Everything is checked before anything is written, and a refused input is a
NewGeneratorError: NAME is lowercase letters, digits and underscores starting
with a letter; the reference is a UTF-8 file with a suffix seams_gen.testing
has a comment syntax for, holding a non-blank line, parsing as its file type
(check_output), with no line that already carries a marker, holds a template
delimiter (``[[``, ``[%``, ``[#``) or would not come back unchanged from
strip_markers once marked (trailing whitespace, a ``\\r``); DIR does not exist
or is an empty directory. A line inside a multi-line string or block scalar is
marked like any other; whether the comment belongs there is the author's call.
The same arguments always give the same bytes.
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

from seams_gen.testing import MARKER, check_output, strip_markers

NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
VERSION = "0.1.0"
# The comment that carries the marker, per reference suffix (as in seams_gen.testing).
COMMENT = {".html": "  {# [fixed] #}", ".py": "  # [fixed]", ".yaml": "  # [fixed]", ".yml": "  # [fixed]"}
# The delimiters of the scaffolded template environment; a reference holding one
# would not render verbatim.
DELIMITERS = ("[[", "[%", "[#")


class NewGeneratorError(Exception):
    """The arguments of ``seams new-generator`` cannot make a generator; nothing was written."""


def default_out(name: str) -> Path:
    return Path(f"seams-{name}")


def scaffold(name: str, reference: Path) -> dict[str, str]:
    """{relative posix path: text} of the generator package for ``reference``."""
    if not NAME.match(name):
        raise NewGeneratorError(
            f"generator name {name!r} must be lowercase letters, digits and underscores, starting with a letter"
        )
    suffix = reference.suffix
    if suffix not in COMMENT:
        raise NewGeneratorError(f"{reference}: no golden comment syntax for {suffix!r} (known: {', '.join(COMMENT)})")
    if not reference.is_file():
        raise NewGeneratorError(f"{reference}: no such file")
    try:
        text = reference.read_bytes().decode("utf-8")
    except UnicodeDecodeError as err:
        raise NewGeneratorError(f"{reference}: not UTF-8 text: {err}") from None
    golden = _golden(text, reference)
    try:
        check_output(reference, text)
    except AssertionError as err:
        raise NewGeneratorError(f"the reference must parse as its file type: {err}") from None
    package = f"seams_{name}"
    fields = {"name": name, "package": package, "output": reference.name, "version": VERSION}
    return {
        "pyproject.toml": PYPROJECT.substitute(fields),
        f"{package}/__init__.py": PACKAGE.substitute(fields, output_literal=repr(reference.name)),
        f"{package}/templates/{reference.name}": text,
        f"tests/golden/{reference.name}": golden,
        f"tests/test_{name}.py": TEST.substitute(fields),
    }


def _golden(text: str, reference: Path) -> str:
    """``text`` with the ``[fixed]`` comment on every non-blank line, refusing a
    line strip_markers would not give back unchanged."""
    comment = COMMENT[reference.suffix]
    lines = text.split("\n")
    marked = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            marked.append(line)
            continue
        where = f"{reference}:{number}"
        if MARKER.search(line):
            raise NewGeneratorError(f"{where}: already carries a producibility marker: {line!r}")
        for delimiter in DELIMITERS:
            if delimiter in line:
                raise NewGeneratorError(f"{where}: holds the template delimiter {delimiter!r}: {line!r}")
        if line != line.rstrip():
            raise NewGeneratorError(f"{where}: ends in whitespace, which the golden's marker comment drops: {line!r}")
        with_marker = line + comment
        try:
            back = strip_markers(with_marker, reference.suffix)
        except ValueError as err:
            raise NewGeneratorError(f"{where}: cannot carry a trailing marker comment: {err}") from None
        if back != line:
            raise NewGeneratorError(f"{where}: does not survive a trailing marker comment: {line!r}")
        marked.append(with_marker)
    if len(marked) == sum(not line.strip() for line in lines):
        raise NewGeneratorError(f"{reference}: has no non-blank line")
    return "\n".join(marked)


def check_out(out: Path) -> None:
    if out.is_dir():
        if any(out.iterdir()):
            raise NewGeneratorError(f"{out}: directory is not empty")
    elif out.exists():
        raise NewGeneratorError(f"{out}: exists and is not a directory")


def write(out: Path, files: dict[str, str]) -> list[Path]:
    """Write ``files`` below ``out`` as UTF-8, newlines untranslated; the paths, sorted."""
    written = []
    for rel in sorted(files):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[rel], encoding="utf-8", newline="")
        written.append(path)
    return written


def new_generator(name: str, reference: Path, out: Path | None) -> list[Path]:
    """Check every argument, then write the package; the written paths."""
    files = scaffold(name, reference)
    out = default_out(name) if out is None else out
    check_out(out)
    return write(out, files)


PYPROJECT = Template("""\
# Scaffolded by `seams new-generator`. Install it beside the seams CLI, which
# brings seams_gen, and list `$name` under [[generators]] in a seams.toml.
[project]
name = "seams-$name"
version = "$version"
description = "The $name generator for Semantic Seams models."
requires-python = ">=3.12"
dependencies = ["semanticseams"]

[project.optional-dependencies]
test = ["pytest"]

[project.entry-points."seams.generators"]
$name = "$package:generator"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["$package"]
""")

PACKAGE = Template('''\
"""The $name generator, scaffolded by `seams new-generator`.

extract reads the model into the view model; render substitutes the view model
into templates/$output and holds no logic. Every name, join, condition and
format is computed in extract, so the template only outputs prepared values
([[ field ]]) and loops over them ([% for item in items %]).
"""

from pathlib import Path

import jinja2
import seams
from seams_gen.protocol import Generator

TEMPLATES = Path(__file__).resolve().parent / "templates"
OUTPUT = $output_literal


def extract(trig: Path, out: Path) -> dict:
    """The view model: every value the template outputs, read from the model at ``trig``."""
    model = seams.load(trig)
    return {"model_hash": model.hash}


def render(view: dict) -> dict[str, str]:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
    )
    return {OUTPUT: env.get_template(OUTPUT).render(view)}


def sources(trig: Path, out: Path) -> dict[str, tuple[str, ...]]:
    """The full IRIs of the model elements each file comes from."""
    return {OUTPUT: ()}


generator = Generator(
    name="$name",
    version="$version",
    help="writes $output from the model",
    extract=extract,
    render=render,
    sources=sources,
)
''')

TEST = Template('''\
"""Tests of the $name generator on the seams_gen.testing kit.

The model is SEAMS_MODEL when it is set, else examples/chat-app/chat-app.trig
of the Semantic Seams checkout seams_gen comes from. golden/$output is the
expected output with a marker on every non-blank line: [fixed] for text the
template holds, [graph: ...] for text read from the model.
"""

import os
from pathlib import Path

import seams
import seams_gen
from seams_gen.testing import assert_deterministic, assert_matches_golden, check_output

from $package import OUTPUT, generator

GOLDEN = Path(__file__).resolve().parent / "golden" / OUTPUT
EXAMPLE = Path(seams_gen.__file__).resolve().parents[1] / "examples" / "chat-app" / "chat-app.trig"
MODEL = Path(os.environ.get("SEAMS_MODEL") or EXAMPLE)


def test_output_matches_golden(tmp_path):
    files = generator.generate(MODEL, tmp_path)
    assert sorted(files) == [OUTPUT]
    assert_matches_golden(files[OUTPUT], GOLDEN, seams.load(MODEL).hash)


def test_output_is_deterministic(tmp_path):
    assert_deterministic(generator, MODEL, tmp_path)


def test_output_parses(tmp_path):
    for name, text in generator.generate(MODEL, tmp_path).items():
        check_output(name, text)


def test_sources_name_the_generated_files(tmp_path):
    assert set(generator.sources(MODEL, tmp_path)) == set(generator.generate(MODEL, tmp_path))
''')


__all__ = ["NewGeneratorError", "default_out", "new_generator", "scaffold"]
