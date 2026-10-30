"""The golden-target rule (D016): a golden artifact without its markers.

The goldens in docs/generation/golden/ are expected generator outputs whose
every non-blank line ends in a producibility marker inside a trailing comment
(see docs/generation/golden/README.md). A generator emits the same text with
the markers stripped: on each line the single marker is removed from its
trailing comment, a comment left empty is dropped together with the
whitespace before it, and the line is right-stripped. Blank lines and the
trailing newline are kept, and lines without a marker are left as they are.
"""

import re
from pathlib import Path

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
    ``model_hash`` (``sha256:<hex>``, as returned by seams_runtime.model_hash).
    """
    path = Path(path)
    if not model_hash.startswith("sha256:"):
        model_hash = "sha256:" + model_hash
    text = strip_markers(path.read_text(encoding="utf-8"), path.suffix)
    return text.replace(PLACEHOLDER_HASH, model_hash)
