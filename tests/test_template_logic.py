"""Templates hold text, not logic (M017/S03, docs/project/principles.md): every
``[[ ]]`` and ``[% %]`` tag in seams_gen/templates/*.j2 is a prepared value or a
plain loop or branch over one. Filters, concatenation, comparisons, compound
conditions and calls belong in the generator's ``extract`` step.

``computing_expressions`` is the scanner; it takes template text so other checks
(the M017/S04 review checks) can reuse it on any template.
"""

import re
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "seams_gen" / "templates"

_PATH = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
_NAME = r"[A-Za-z_]\w*"
_TAG = re.compile(r"\[\[(?P<value>.*?)\]\]|\[%(?P<block>.*?)%\]|\[#.*?#\]", re.S)

# A value tag outputs an attribute path, optionally HTML-escaped.
_VALUE = re.compile(rf"{_PATH}(?:\|e)?")
# A block tag loops or branches on a bare path, closes a block, includes a
# template by name or aliases a path.
_BLOCKS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"for {_NAME}(?:, {_NAME})* in {_PATH}",
        rf"(?:if|elif) (?:not )?{_PATH}",
        r"else|endif|endfor",
        r'include "[\w.-]+\.j2"',
        rf"set {_NAME} = {_PATH}",
    )
)


class Finding(NamedTuple):
    template: str
    line: int
    expression: str

    def __str__(self) -> str:
        return f"{self.template}:{self.line}: {self.expression}"


def _allowed(value: str | None, block: str | None) -> bool:
    if value is not None:
        return _VALUE.fullmatch(value.strip()) is not None
    if block is not None:
        body = block.strip().strip("-+").strip()
        return any(pattern.fullmatch(body) for pattern in _BLOCKS)
    return True  # a comment


def computing_expressions(text: str, template: str = "<string>") -> list[Finding]:
    """Every tag in ``text`` that computes rather than emits a prepared value."""
    findings = []
    for match in _TAG.finditer(text):
        if not _allowed(match.group("value"), match.group("block")):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(template, line, " ".join(match.group(0).split())))
    return findings


def test_templates_exist() -> None:
    assert sorted(TEMPLATE_DIR.glob("*.j2"))


def test_templates_hold_no_computing_expressions() -> None:
    findings = [
        finding
        for path in sorted(TEMPLATE_DIR.glob("*.j2"))
        for finding in computing_expressions(path.read_text(encoding="utf-8"), path.name)
    ]
    assert not findings, "move these into extract:\n" + "\n".join(map(str, findings))


@pytest.mark.parametrize(
    "tag",
    [
        '[[ a|join(", ") ]]',
        '[[ "x" ~ a ]]',
        '[% if a == "b" %]',
        "[[ a|lower ]]",
        "[[ a.b() ]]",
        "[[ a[0] ]]",
        "[[ a if b else c ]]",
        "[% if a and b %]",
        "[% if a is not none %]",
        "[% for x in a|sort %]",
        "[% for x in a if x.b %]",
        "[% set s = a ~ b %]",
        "[% include a %]",
        "[% macro m(a) %]",
    ],
)
def test_scanner_flags_computing_expression(tag: str) -> None:
    text = f"line one\n  {tag}\n"
    assert computing_expressions(text, "sample.j2") == [Finding("sample.j2", 2, tag)]


@pytest.mark.parametrize(
    "tag",
    [
        "[[ a ]]",
        "[[ a.b.c|e ]]",
        "[% for a in b.c %]",
        "[% for k, v in b.items_list %]",
        "[% if a.b %]",
        "[% if not loop.first %]",
        "[% elif loop.last %]",
        "[% else %]",
        "[% endif %]",
        "[%- endfor -%]",
        '[% include "part.html.j2" %]',
        "[% set s = c.submit %]",
        "[# a comment ~ with |join #]",
    ],
)
def test_scanner_accepts_prepared_value(tag: str) -> None:
    assert computing_expressions(tag) == []


def test_finding_names_template_line_and_expression() -> None:
    text = "a\nb\n[[ x ]] [[ y|upper ]]\n"
    (finding,) = computing_expressions(text, "t.j2")
    assert str(finding) == "t.j2:3: [[ y|upper ]]"
