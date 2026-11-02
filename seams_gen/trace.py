"""Line-level generation traces (ADR-0019, M020/S01, backlog T1).

A ``Trace`` names, for each non-blank line of one generated file, the
template lines that emitted it (``templates``, outermost include first) and
the full model IRIs behind it (``terms``). ``render_trace_json`` writes it as
the ``<output>.trace.json`` sidecar.

A trace comes from a second render of the same view model with a
``TracingEnvironment``, which has the generator environment's options plus:

- an extension whose ``filter_stream`` adds sentinels to the token stream:
  a line sentinel before each newline (or at the end) of every piece of
  template text, naming its template file and line, and a span around every
  ``[[ expression ]]`` and every ``include`` tag, naming the line of the tag
  (an included template's lines are inside the span of the include).
  Block-only lines and comments emit no text, so they get none.
- ``getattr``/``getitem`` that tag a plain ``str`` read off a view object
  carrying an ``iri`` (or one reached from such an object) with that IRI, and
  a ``finalize`` that emits a term sentinel before each tagged value.

``trace_template`` renders, strips the sentinels and requires the result to
equal the normal render; a mismatch, or a sentinel character already in the
normal output, raises ``GeneratorError`` naming the template and line. A line
no term sentinel lands on takes the terms of its innermost include that has
any, else the ``fallback`` terms: the IRIs of the enclosing view object
passed to the template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import jinja2
from jinja2.ext import Extension
from jinja2.lexer import (
    TOKEN_BLOCK_BEGIN,
    TOKEN_BLOCK_END,
    TOKEN_DATA,
    TOKEN_VARIABLE_BEGIN,
    TOKEN_VARIABLE_END,
    Token,
    TokenStream,
)

from . import GeneratorError

TRACE_VERSION = 1

# Private-use code points: a sentinel is OPEN kind payload CLOSE, where kind
# is L (a template line), S (an expression span opens), I (an include span
# opens), E (the innermost span ends) or T (a model term). Payloads hold no
# newline, so sentinels never move a line.
OPEN = ""
CLOSE = ""
_SENTINEL = re.compile(f"{OPEN}([LSIET])([^{CLOSE}]*){CLOSE}")
_PRIMITIVE = (str, bytes, int, float, bool, type(None))


@dataclass(frozen=True)
class TraceLine:
    line: int  # 1-based line of the output
    templates: tuple[str, ...]  # "<template file>:<line>", outermost include first
    terms: tuple[str, ...]  # full model IRIs, sorted and de-duplicated


@dataclass(frozen=True)
class Trace:
    output: str  # the file name ``render`` returns it under
    generator: str  # the generator's entry-point name
    lines: tuple[TraceLine, ...]  # the non-blank output lines, in order

    @property
    def terms(self) -> tuple[str, ...]:
        """The sorted union of the lines' terms."""
        return tuple(sorted({t for line in self.lines for t in line.terms}))

    def union(self, other: Trace) -> Trace:
        """This trace with ``other``'s templates and terms added line by line
        (one file that two view objects render identically)."""
        theirs = {line.line: line for line in other.lines}
        lines = []
        for mine in self.lines:
            line = theirs.get(mine.line, mine)
            templates = tuple(dict.fromkeys(mine.templates + line.templates))
            lines.append(TraceLine(mine.line, templates, tuple(sorted(set(mine.terms) | set(line.terms)))))
        return Trace(self.output, self.generator, tuple(lines))


def render_trace_json(trace: Trace) -> str:
    """The sidecar text: sorted-key JSON, two-space indented, ending in a newline."""
    data = {
        "generator": trace.generator,
        "lines": [{"line": ln.line, "templates": list(ln.templates), "terms": list(ln.terms)} for ln in trace.lines],
        "output": trace.output,
        "trace_version": TRACE_VERSION,
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sentinel(kind: str, payload: str = "") -> str:
    return f"{OPEN}{kind}{payload}{CLOSE}"


class _Origin(str):
    """A ``str`` read off a view object carrying ``iri``."""

    iri: str

    def __new__(cls, text: str, iri: str) -> _Origin:
        value = super().__new__(cls, text)
        value.iri = iri
        return value


def _own_iri(obj: object) -> str | None:
    iri = getattr(obj, "iri", None)
    return iri if isinstance(iri, str) and iri else None


def _finalize(value: Any) -> Any:
    iri = value.iri if isinstance(value, _Origin) else _own_iri(value)
    return f"{_sentinel('T', iri)}{value}" if iri else value


def _mark_text(name: str, lineno: int, text: str) -> str:
    """``text``, starting on template line ``lineno``, with a line sentinel
    ending each of its pieces (before the newline, if it has one)."""
    out = []
    for offset, piece in enumerate(re.findall(r"[^\n]*\n|[^\n]+", text)):
        body = piece[:-1] if piece.endswith("\n") else piece
        out.append(f"{body}{_sentinel('L', f'{name}:{lineno + offset}')}{piece[len(body) :]}")
    return "".join(out)


class _SentinelExtension(Extension):
    def filter_stream(self, stream: TokenStream) -> Iterator[Token]:
        name = stream.name or "<template>"
        in_include = False
        for token in stream:
            if token.type == TOKEN_DATA:
                yield Token(token.lineno, TOKEN_DATA, _mark_text(name, token.lineno, token.value))
            elif token.type == TOKEN_VARIABLE_BEGIN:
                yield Token(token.lineno, TOKEN_DATA, _sentinel("S", f"{name}:{token.lineno}"))
                yield token
            elif token.type == TOKEN_VARIABLE_END:
                yield token
                yield Token(token.lineno, TOKEN_DATA, _sentinel("E"))
            elif token.type == TOKEN_BLOCK_BEGIN and stream.current.test("name:include"):
                in_include = True
                yield Token(token.lineno, TOKEN_DATA, _sentinel("I", f"{name}:{token.lineno}"))
                yield token
            elif token.type == TOKEN_BLOCK_END and in_include:
                in_include = False
                yield token
                yield Token(token.lineno, TOKEN_DATA, _sentinel("E"))
            else:
                yield token


class TracingEnvironment(jinja2.Environment):
    """A Jinja2 environment that renders with trace sentinels; construct it
    with the generator environment's options."""

    def __init__(self, **options: Any) -> None:
        super().__init__(finalize=_finalize, extensions=[_SentinelExtension], **options)
        self._reached: dict[int, tuple[object, str]] = {}  # id -> (object, IRI it was reached from)

    def _iri(self, obj: object) -> str | None:
        own = _own_iri(obj)
        if own is not None:
            return own
        reached = self._reached.get(id(obj))
        return reached[1] if reached is not None and reached[0] is obj else None

    def _tag(self, obj: object, value: Any) -> Any:
        iri = self._iri(obj)
        if iri is None or isinstance(value, jinja2.Undefined):
            return value
        if type(value) is str:
            return _Origin(value, iri)
        for item in value if isinstance(value, tuple | list) else (value,):
            if not isinstance(item, _PRIMITIVE) and _own_iri(item) is None:
                self._reached.setdefault(id(item), (item, iri))
        return value

    def getattr(self, obj: Any, attribute: str) -> Any:
        return self._tag(obj, super().getattr(obj, attribute))

    def getitem(self, obj: Any, argument: Any) -> Any:
        return self._tag(obj, super().getitem(obj, argument))


@dataclass
class _Line:
    text: str
    templates: tuple[str, ...]
    terms: tuple[str, ...]
    regions: tuple[int, ...]  # the include spans the line is in, innermost first


def _parse(traced: str, template: str) -> tuple[list[_Line], list[set[str]]]:
    """Each line of the traced render with its sentinels removed, the
    template origins and the terms that land on it; and, per include span,
    the terms that land anywhere inside it."""
    lines: list[_Line] = []
    stack: list[tuple[str, int | None]] = []  # (origin, include span index)
    regions: list[set[str]] = []
    text: list[str] = []
    origins: dict[str, None] = {}
    inside: dict[int, None] = {}
    terms: set[str] = set()

    def touch() -> None:
        for origin, region in stack:
            origins.setdefault(origin)
            if region is not None:
                inside.setdefault(region)

    def end_line() -> None:
        lines.append(_Line("".join(text), tuple(origins), tuple(sorted(terms)), tuple(reversed(inside))))
        text.clear()
        origins.clear()
        inside.clear()
        terms.clear()

    def visible(chunk: str) -> None:
        for i, piece in enumerate(chunk.split("\n")):
            if i:
                end_line()
            if piece:
                touch()
                text.append(piece)

    pos = 0
    for m in _SENTINEL.finditer(traced):
        visible(traced[pos : m.start()])
        pos = m.end()
        kind, payload = m.group(1), m.group(2)
        if kind == "S":
            stack.append((payload, None))
        elif kind == "I":
            stack.append((payload, len(regions)))
            regions.append(set())
        elif kind == "E":
            if not stack:
                raise GeneratorError(template, "trace", "a trace span ends that never began")
            stack.pop()
        else:
            touch()
            if kind == "L":
                origins.setdefault(payload)
            else:
                terms.add(payload)
                for _, region in stack:
                    if region is not None:
                        regions[region].add(payload)
    visible(traced[pos:])
    if text or origins:
        end_line()
    return lines, regions


def trace_template(
    env: TracingEnvironment,
    template: str,
    context: Mapping[str, Any],
    *,
    output: str,
    generator: str,
    expected: str,
    fallback: Iterable[str] = (),
) -> Trace:
    """The trace of ``output``, the normal render ``expected`` of
    ``template`` with ``context``. A line no term sentinel lands on takes the
    terms of the innermost include it is in that has any (the included
    template's view object), else ``fallback``."""
    for number, line in enumerate(expected.split("\n"), start=1):
        if OPEN in line or CLOSE in line:
            raise GeneratorError(
                template, "trace", f"line {number} of {output} already holds a trace sentinel character"
            )
    traced = env.get_template(template).render(context)
    stripped = _SENTINEL.sub("", traced)
    parsed, regions = _parse(traced, template)
    if stripped != expected:
        want = expected.split("\n")
        got = stripped.split("\n")
        number = next((i for i, (a, b) in enumerate(zip(want, got, strict=False)) if a != b), min(len(want), len(got)))
        origin = parsed[number].templates[-1] if number < len(parsed) and parsed[number].templates else template
        raise GeneratorError(
            origin, "trace", f"the traced render of {output} differs from the normal render at line {number + 1}"
        )
    default = tuple(sorted(set(fallback)))
    lines = []
    for number, line in enumerate(parsed, start=1):
        if not line.text.strip():
            continue
        if not line.templates:
            raise GeneratorError(template, "trace", f"line {number} of {output} has no template origin")
        enclosing = next((tuple(sorted(regions[r])) for r in line.regions if regions[r]), default)
        lines.append(TraceLine(number, line.templates, line.terms or enclosing))
    return Trace(output, generator, tuple(lines))


__all__ = ["TRACE_VERSION", "Trace", "TraceLine", "TracingEnvironment", "render_trace_json", "trace_template"]
