"""The vocabulary breaking-change gate (ADR-0021 section 7).

``diff_vocabularies(old, new)`` compares two vocabulary directories laid out like
``ontology/`` (``<name>.ttl`` files, ``shapes/*.ttl``, ``migrations/<name>/*.ru``) and
returns the changes of each vocabulary, by name, with the shared classification:

- terms in ``<name>.ttl`` by ``classification.classify_terms``, with the
  ``rdfs:subClassOf`` facts of every vocabulary in both directories;
- shapes in ``shapes/*.ttl`` by ``seams diff``'s rules (``diff.diff_graphs``). A shape
  change belongs to each vocabulary that defines a term the shape targets
  (``sh:targetClass``, ``sh:targetSubjectsOf``, ``sh:targetObjectsOf``,
  ``sh:targetNode``), or, for a shape without targets, a term it constrains (an
  ``sh:path`` of its properties); a shape that names no vocabulary term belongs to
  ``seam``, the vocabulary the shapes file is for.

``gate(old, new)`` returns one failure per vocabulary that breaks the version rules,
sorted, and an empty list when the change may ship:

- a breaking change without a higher major version;
- a major bump without the step's ``migrations/<name>/<from>-to-<to>.ru`` in NEW;
- a lower version than OLD, a removed vocabulary, or a vocabulary in NEW without an
  ``owl:versionIRI``.

A vocabulary in OLD without an ``owl:versionIRI`` is at ``1.0``, the ADR's baseline.
A file that does not parse, or that declares no SemanticSeams ``owl:Ontology``, raises
ProjectError. Nothing here writes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import rdflib
from rdflib.term import Node
from seams.vocabularies import DEFAULT_VERSION, VOCABULARY_BASE

from .classification import BREAKING, Change, classify_terms, sort_changes, terms
from .diff import diff_graphs
from .project import ProjectError

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
OWL = rdflib.OWL

#: The vocabulary a shape that names no vocabulary term belongs to.
SHAPES_VOCABULARY = "seam"

SHAPE_TARGETS = (SH.targetClass, SH.targetSubjectsOf, SH.targetObjectsOf, SH.targetNode)

_VERSION = re.compile(r"(\d+)\.(\d+)")

Version = tuple[int, int]


class Vocabulary(NamedTuple):
    """One ``<name>.ttl``: its graph and its version (None when it has no ``owl:versionIRI``)."""

    name: str
    graph: rdflib.Graph
    version: Version | None


def _parse(path: Path) -> rdflib.Graph:
    try:
        return rdflib.Graph().parse(path, format="turtle")
    except Exception as err:
        raise ProjectError(f"{path}: cannot parse: {err}") from err


def read_vocabularies(directory: Path) -> dict[str, Vocabulary]:
    """Each ``<name>.ttl`` in ``directory``, by vocabulary name."""
    found: dict[str, Vocabulary] = {}
    for path in sorted(Path(directory).glob("*.ttl")):
        graph = _parse(path)
        ontologies = sorted(
            str(s) for s in graph.subjects(rdflib.RDF.type, OWL.Ontology) if str(s).startswith(VOCABULARY_BASE)
        )
        if len(ontologies) != 1:
            raise ProjectError(f"{path}: expected one SemanticSeams owl:Ontology, found {ontologies or 'none'}")
        name = ontologies[0][len(VOCABULARY_BASE) :]
        iris = sorted(str(v) for v in graph.objects(rdflib.URIRef(ontologies[0]), OWL.versionIRI))
        version: Version | None = None
        if iris:
            match = _VERSION.fullmatch(iris[0].removeprefix(ontologies[0] + "/")) if len(iris) == 1 else None
            if match is None:
                raise ProjectError(f"{path}: expected one owl:versionIRI <{ontologies[0]}/MAJOR.MINOR>, found {iris}")
            version = (int(match[1]), int(match[2]))
        found[name] = Vocabulary(name, graph, version)
    return found


def _shapes(directory: Path) -> rdflib.Graph:
    graph = rdflib.Graph()
    for path in sorted((Path(directory) / "shapes").glob("*.ttl")):
        graph += _parse(path)
    return graph


def _named(shapes: rdflib.Graph, shape: rdflib.URIRef) -> set[Node]:
    """The terms a shape targets, or the paths it constrains when it has no target."""
    named = {t for predicate in SHAPE_TARGETS for t in shapes.objects(shape, predicate)}
    if not named:
        for prop in shapes.objects(shape, SH.property):
            named.update(shapes.objects(prop, SH.path))
    return named


def diff_vocabularies(old: Path, new: Path) -> dict[str, list[Change]]:
    """Every term and shape change from OLD to NEW, by vocabulary name, each list sorted.
    A vocabulary without changes is left out."""
    before, after = read_vocabularies(old), read_vocabularies(new)
    hierarchy = rdflib.Graph()
    for vocabulary in (*before.values(), *after.values()):
        hierarchy += vocabulary.graph
    empty = rdflib.Graph()
    result: dict[str, list[Change]] = {}
    for name in sorted(before.keys() | after.keys()):
        old_graph = before[name].graph if name in before else empty
        new_graph = after[name].graph if name in after else empty
        changes = classify_terms(old_graph, new_graph, hierarchy)
        if changes:
            result[name] = changes

    owner: dict[Node, str] = {}
    for vocabulary in (*before.values(), *after.values()):
        for term in terms(vocabulary.graph):
            owner.setdefault(term, vocabulary.name)
    old_shapes, new_shapes = _shapes(old), _shapes(new)
    for change in diff_graphs(old_shapes, new_shapes):
        shape = rdflib.URIRef(change.subject)
        names = {owner[t] for t in _named(old_shapes, shape) | _named(new_shapes, shape) if t in owner}
        for name in sorted(names or {SHAPES_VOCABULARY}):
            result.setdefault(name, []).append(change)
    return {name: sort_changes(changes) for name, changes in sorted(result.items())}


def _text(version: Version) -> str:
    return f"{version[0]}.{version[1]}"


def gate(old: Path, new: Path) -> list[str]:
    """The version-rule failures of the change from OLD to NEW, sorted; empty when it may ship."""
    before, after = read_vocabularies(old), read_vocabularies(new)
    changes = diff_vocabularies(old, new)
    failures: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        if name not in after:
            failures.append(f"{name}: the vocabulary is removed; a removed vocabulary strands every model using it")
            continue
        new_version = after[name].version
        if new_version is None:
            failures.append(f"{name}: no owl:versionIRI <{VOCABULARY_BASE}{name}/MAJOR.MINOR>")
            continue
        if name not in before:
            continue
        old_version = before[name].version or DEFAULT_VERSION
        if new_version < old_version:
            failures.append(f"{name}: version goes down, {_text(old_version)} -> {_text(new_version)}")
            continue
        breaking = [c for c in changes.get(name, []) if c.verdict == BREAKING]
        if breaking and new_version[0] <= old_version[0]:
            listed = "; ".join(f"{c.kind} {c.subject}" for c in breaking)
            failures.append(
                f"{name}: {len(breaking)} breaking change(s) without a major bump "
                f"({_text(old_version)} -> {_text(new_version)}): {listed}"
            )
        for major in range(old_version[0], new_version[0]):
            step = Path("migrations") / name / f"{major}-to-{major + 1}.ru"
            if not (Path(new) / step).is_file():
                failures.append(f"{name}: major bump {major} -> {major + 1} without the migration step {step}")
    return failures
