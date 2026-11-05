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

and, optionally, ``trace(view)``: ``{relative file name: Trace}`` with
exactly the file names ``render`` returns, the line-level generation trace
of each file (ADR-0019, ``seams_gen.trace``). ``None`` (the default) means
the generator writes no trace sidecars.

and, optionally, ``inputs(trig, out)``: the absolute paths of the files
outside the model and its payloads that ``extract`` reads (ADR-0016,
"Inputs beyond the model"; the ``dockerfile`` generator's uv workspace
files). A tool that regenerates in a scratch copy (the viewer's write-back,
``seams suggest``) copies them to the same place relative to the model. It
never raises: a file it cannot find is left out, and ``extract`` raises on
it. ``None`` (the default) means the generator reads nothing beyond the
model.

``precondition_faults(results, shapes)`` reads a pyshacl results graph of the
model validated against ``shapes`` (ontology/shapes) and returns a sorted
``GeneratorError`` per result of one of ``preconditions``;
``check_preconditions`` raises the first. ``seams generate`` calls
``check_preconditions`` before ``generate`` (strict mode), or collects
``precondition_faults`` and runs the generator anyway (lenient mode, D057).
The built-in generators are the objects of ``seams_gen.builtin`` and declare
no preconditions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rdflib import RDF, Graph, Namespace, URIRef

from . import GeneratorError
from .trace import Trace

SH = Namespace("http://www.w3.org/ns/shacl#")

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
    trace: Callable[[V], dict[str, Trace]] | None = None  # ADR-0019
    inputs: Callable[[Path, Path], tuple[Path, ...]] | None = None  # ADR-0016, inputs beyond the model

    def generate(self, trig: Path, out: Path) -> Files:
        """{relative file name: text}: ``render(extract(trig, out))``."""
        return self.render(self.extract(trig, out))

    def precondition_faults(self, results: Graph, shapes: Graph) -> list[GeneratorError]:
        """One ``GeneratorError`` per result in ``results``, the SHACL validation
        report of the model against ``shapes``, of one of ``preconditions``: a
        result whose ``sh:sourceShape`` is the node shape or one of its
        ``sh:property`` shapes (``shapes`` must be the graph that was validated
        with, so blank-node property shapes match). A ``sh:Warning`` result is
        never a fault (ADR-0021 section 6). Each error's subject is the
        focus node and its predicate the node shape IRI; they are sorted by
        (shape, focus node, message)."""
        owner = {}
        for iri in self.preconditions:
            node = URIRef(iri)
            owner[node] = iri
            for prop in shapes.objects(node, SH.property):
                owner[prop] = iri
        failures = sorted(
            (owner[shape], str(results.value(r, SH.focusNode)), str(results.value(r, SH.resultMessage) or ""))
            for r in results.subjects(RDF.type, SH.ValidationResult)
            if (shape := results.value(r, SH.sourceShape)) in owner
            if results.value(r, SH.resultSeverity) != SH.Warning
        )
        return [
            GeneratorError(
                focus, shape, f"generator {self.name!r} requires the model to conform to this shape: {message}"
            )
            for shape, focus, message in failures
        ]

    def check_preconditions(self, results: Graph, shapes: Graph) -> None:
        """Raise the first of ``precondition_faults(results, shapes)``, with a
        count of the rest (strict mode)."""
        faults = self.precondition_faults(results, shapes)
        if not faults:
            return
        shape, focus, detail = faults[0].predicate, faults[0].subject, faults[0].detail
        more = f" (and {len(faults) - 1} more)" if len(faults) > 1 else ""
        raise GeneratorError(focus, shape, f"{detail}{more}")


__all__ = ["SH", "Files", "Generator", "Sources"]
