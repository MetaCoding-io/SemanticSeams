"""The model's one write path (ADR-0017, principle 10).

A patch is the quads an edit adds and removes. The TriG text writer applies it by
editing the source text at the triple level, so comments and layout survive and a
one-triple edit gives a one-line diff. ``apply`` routes a patch to the model files
that hold its graphs and writes them all or none; ``undo`` reverses it. The XML payload
writer saves a BPMN or DMN file (``save_payload``) and renames an element id with every
quad that names its lifted IRI (``rename_id``, ADR-0002); ``combine`` makes successive
edits one undoable record. No other code writes model files.
"""

from .files import EditRecord, FileEdit, apply, combine, undo
from .patch import Patch, PatchError, Quad
from .trig import apply_text, declared_graphs, text_quads
from .xml import rename_id, save_payload

__all__ = [
    "EditRecord",
    "FileEdit",
    "Patch",
    "PatchError",
    "Quad",
    "apply",
    "apply_text",
    "combine",
    "declared_graphs",
    "rename_id",
    "save_payload",
    "text_quads",
    "undo",
]
