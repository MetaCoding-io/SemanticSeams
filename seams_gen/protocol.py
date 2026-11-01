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

``check_preconditions(results, shapes)`` reads a pyshacl results graph of the
model validated against ``shapes`` (ontology/shapes) and raises
``GeneratorError`` on the first result of one of ``preconditions``; ``seams
generate`` calls it before ``generate`` (strict mode). The built-in generators
are the objects of ``seams_gen.builtin`` and declare no preconditions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rdflib import RDF, Graph, Namespace, URIRef

from . import GeneratorError

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

    def generate(self, trig: Path, out: Path) -> Files:
        """{relative file name: text}: ``render(extract(trig, out))``."""
        return self.render(self.extract(trig, out))

    def check_preconditions(self, results: Graph, shapes: Graph) -> None:
        """Raise ``GeneratorError`` when ``results``, the SHACL validation report
        of the model against ``shapes``, holds a result of one of
        ``preconditions``: a result whose ``sh:sourceShape`` is the node shape or
        one of its ``sh:property`` shapes (``shapes`` must be the graph that was
        validated with, so blank-node property shapes match). The error's subject
        is the focus node and its predicate the node shape IRI; the first result
        in (shape, focus node, message) order is reported, with a count of the rest."""
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
        )
        if not failures:
            return
        shape, focus, message = failures[0]
        more = f" (and {len(failures) - 1} more)" if len(failures) > 1 else ""
        raise GeneratorError(
            focus, shape, f"generator {self.name!r} requires the model to conform to this shape: {message}{more}"
        )


__all__ = ["SH", "Files", "Generator", "Sources"]
