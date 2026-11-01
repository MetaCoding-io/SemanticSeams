"""The generator protocol (M018/S01, backlog K3).

A generator is a ``Generator`` object: a name, a version, a one-line help
text, the SHACL shapes the model must conform to before it runs
(``preconditions``, full shape IRIs) and three functions:

- ``extract(trig, out)``: read the model at ``trig`` into a frozen view model.
  ``out`` is the output directory, for generators whose output names paths
  relative to it (``compose``). Every check and every computation is here; a
  missing or ambiguous fact raises ``GeneratorError``.
- ``render(view)``: the view model as ``{relative file name: text}``.
- ``sources(trig, out)``: ``{relative file name: full IRIs}`` of the model
  elements each file comes from, with exactly the file names ``generate``
  returns. ``seams generate`` records them in seams.lock.

The built-in generators are the objects of ``seams_gen.builtin``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Files = dict[str, str]
Sources = dict[str, tuple[str, ...]]


@dataclass(frozen=True, kw_only=True)
class Generator[V]:
    name: str
    version: str
    help: str
    extract: Callable[[Path, Path], V]
    render: Callable[[V], Files]
    sources: Callable[[Path, Path], Sources]
    preconditions: tuple[str, ...] = ()  # sh:NodeShape IRIs

    def generate(self, trig: Path, out: Path) -> Files:
        """{relative file name: text}: ``render(extract(trig, out))``."""
        return self.render(self.extract(trig, out))


__all__ = ["Files", "Generator", "Sources"]
