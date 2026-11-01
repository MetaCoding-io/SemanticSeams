"""The generator test kit (M018/S03, backlog K4): what a generator's tests import.

- ``golden_target(path, model_hash)`` and ``assert_matches_golden(text, path,
  model_hash)``: the golden-target rule (D016). The goldens are expected
  generator outputs whose every non-blank line ends in a producibility marker
  inside a trailing comment (see docs/generation/golden/README.md). A generator
  emits the same text with the markers stripped: on each line the single marker
  is removed from its trailing comment, a comment left empty is dropped together
  with the whitespace before it, and the line is right-stripped. Blank lines and
  the trailing newline are kept, and lines without a marker are left as they
  are. Every ``sha256:<model-hash>`` placeholder becomes the model's hash.
- ``assert_deterministic(generator, model_path)``: two runs give the same files.
- ``check_output(path, text)``: the text parses as its file type.
"""

import ast
import difflib
import json
import re
from pathlib import Path

import jinja2
import yaml

# Same pattern as MARKER in tests/test_golden_outputs.py.
MARKER = re.compile(r"\[(graph: [^\]]+|fixed|gap: GAP-\d{2})\]")
# The marker plus the whitespace before it, as removed from the comment body.
_MARKER_WITH_SPACE = re.compile(r"\s*" + MARKER.pattern)
# A `#` that opens a Python/YAML comment: at line start or after whitespace,
# so `:chat_bpmn#frag` inside a comment does not count as an opener.
_HASH_OPENER = re.compile(r"(?:^|(?<=\s))#")
PLACEHOLDER_HASH = "sha256:<model-hash>"

_SYNTAX = {".html": ("{#", "#}"), ".py": ("#", ""), ".yaml": ("#", ""), ".yml": ("#", "")}


def _strip_line(line: str, opener: str, closer: str) -> str:
    found = list(MARKER.finditer(line))
    if not found:
        return line
    marker = found[-1]
    head = line[: marker.start()]
    if opener == "#":
        starts = [m.start() for m in _HASH_OPENER.finditer(head)]
        start = starts[-1] if starts else -1
    else:
        start = head.rfind(opener)
    if start < 0:
        raise ValueError(f"marker outside a trailing {opener} comment: {line!r}")
    end = line.rfind(closer) if closer else len(line)
    if end < marker.end():
        raise ValueError(f"marker outside a trailing {opener} comment: {line!r}")
    before, comment = line[:start], line[start:end]
    body = _MARKER_WITH_SPACE.sub("", comment[len(opener) :], count=1)
    if not body.strip():
        return before.rstrip()
    return (before + opener + body + line[end:]).rstrip()


def strip_markers(text: str, suffix: str) -> str:
    """Remove the producibility marker from every line of a golden text.

    ``suffix`` picks the comment syntax: ``{# ... #}`` for ``.html``, ``# ...``
    for ``.py`` and ``.yaml``.
    """
    try:
        opener, closer = _SYNTAX[suffix]
    except KeyError:
        raise ValueError(f"no comment syntax for {suffix!r}") from None
    lines = text.split("\n")
    return "\n".join(_strip_line(line, opener, closer) for line in lines)


def golden_target(path, model_hash: str) -> str:
    """The exact text a generator must emit for the golden at ``path``.

    Markers are stripped and every ``sha256:<model-hash>`` placeholder becomes
    ``model_hash`` (``sha256:<hex>``, as returned by seams.model_hash).
    """
    path = Path(path)
    if not model_hash.startswith("sha256:"):
        model_hash = "sha256:" + model_hash
    text = strip_markers(path.read_text(encoding="utf-8"), path.suffix)
    return text.replace(PLACEHOLDER_HASH, model_hash)


def _first_difference(a: list[str], b: list[str]) -> int:
    """The 1-based number of the first line where ``a`` and ``b`` differ."""
    for number, (left, right) in enumerate(zip(a, b, strict=False), start=1):
        if left != right:
            return number
    return min(len(a), len(b)) + 1


def assert_matches_golden(text: str, golden_path, model_hash: str) -> None:
    """Assert ``text`` is ``golden_target(golden_path, model_hash)`` byte for byte.

    The AssertionError names the golden file and the first differing line, then
    gives a unified diff from the golden target to ``text``.
    """
    golden_path = Path(golden_path)
    expected = golden_target(golden_path, model_hash)
    if text == expected:
        return
    want, got = expected.splitlines(keepends=True), text.splitlines(keepends=True)
    if want == got:  # only the end of the text differs, e.g. a missing final newline
        want, got = [repr(expected[-1:])], [repr(text[-1:])]
        line = len(expected.splitlines()) or 1
    else:
        line = _first_difference(want, got)
    diff = "".join(difflib.unified_diff(want, got, fromfile=str(golden_path), tofile="generated"))
    raise AssertionError(f"output differs from golden {golden_path} at line {line}:\n{diff}")


def assert_deterministic(generator, model_path, out=Path("generated")) -> None:
    """Assert two runs of ``generator.generate(model_path, out)`` return the same
    ``{relative file name: text}``.

    Each run loads the model from ``model_path`` afresh. The AssertionError names
    the generator and the first output path (in sorted order) that is missing
    from one run or whose text differs.
    """
    model_path, out = Path(model_path), Path(out)
    first = generator.generate(model_path, out)
    second = generator.generate(model_path, out)
    for name in sorted(first.keys() | second.keys()):
        if name not in first or name not in second:
            run = "second" if name in second else "first"
            raise AssertionError(
                f"generator {generator.name!r} is not deterministic: {name} is produced only by the {run} run"
            )
        if first[name] != second[name]:
            line = _first_difference(first[name].splitlines(), second[name].splitlines())
            raise AssertionError(
                f"generator {generator.name!r} is not deterministic: {name} differs between two runs at line {line}"
            )


def _parse_python(text: str, name: str) -> None:
    try:
        ast.parse(text, filename=name)
    except SyntaxError as err:
        raise AssertionError(f"{name}:{err.lineno}: not valid Python: {err.msg}") from None


def _parse_yaml(text: str, name: str) -> None:
    try:
        for _document in yaml.safe_load_all(text):
            pass
    except yaml.MarkedYAMLError as err:
        mark = err.problem_mark or err.context_mark
        line = mark.line + 1 if mark else "?"
        raise AssertionError(f"{name}:{line}: not valid YAML: {err.problem or err.context}") from None
    except yaml.YAMLError as err:
        raise AssertionError(f"{name}: not valid YAML: {err}") from None


def _parse_json(text: str, name: str) -> None:
    try:
        json.loads(text)
    except json.JSONDecodeError as err:
        raise AssertionError(f"{name}:{err.lineno}: not valid JSON: {err.msg}") from None


def _parse_jinja(text: str, name: str) -> None:
    try:
        jinja2.Environment().parse(text, filename=name)
    except jinja2.TemplateSyntaxError as err:
        raise AssertionError(f"{name}:{err.lineno}: not a valid Jinja2 template: {err.message}") from None


_CHECKERS = {
    ".py": _parse_python,
    ".yaml": _parse_yaml,
    ".yml": _parse_yaml,
    ".json": _parse_json,
    ".html": _parse_jinja,
}


def check_output(path, text: str) -> None:
    """Assert ``text``, a generated file at ``path``, parses as its file type.

    The suffix picks the parser: ``.py`` ast.parse, ``.yaml``/``.yml``
    yaml.safe_load_all, ``.json`` json.loads, ``.html`` a Jinja2 parse. The
    AssertionError is ``<path>:<line>: <parse error>``. An unknown suffix is a
    ValueError.
    """
    path = Path(path)
    try:
        checker = _CHECKERS[path.suffix]
    except KeyError:
        raise ValueError(f"{path}: no output checker for {path.suffix!r} (known: {', '.join(_CHECKERS)})") from None
    checker(text, str(path))


__all__ = [
    "MARKER",
    "PLACEHOLDER_HASH",
    "assert_deterministic",
    "assert_matches_golden",
    "check_output",
    "golden_target",
    "strip_markers",
]
