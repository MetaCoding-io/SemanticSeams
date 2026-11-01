"""The model's one write path (ADR-0017, principle 10).

A patch is the quads an edit adds and removes. The TriG text writer applies it by
editing the source text at the triple level, so comments and layout survive and a
one-triple edit gives a one-line diff. ``apply`` routes a patch to the model files
that hold its graphs and writes them all or none; ``undo`` reverses it. No other code
writes model files.
"""

from .files import EditRecord, FileEdit, apply, undo
from .patch import Patch, PatchError, Quad
from .trig import apply_text, declared_graphs, text_quads

__all__ = [
    "EditRecord",
    "FileEdit",
    "Patch",
    "PatchError",
    "Quad",
    "apply",
    "apply_text",
    "declared_graphs",
    "text_quads",
    "undo",
]
