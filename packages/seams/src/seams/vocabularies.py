"""Vocabulary versions: the ADR-0021 load check and in-memory migrations.

Each vocabulary in ``ontology/<name>.ttl`` carries ``owl:versionIRI
<https://w3id.org/seams/<name>/MAJOR.MINOR>``. A model declares the versions it
was written for as ``owl:imports`` of those version IRIs in the manifest graph
``<urn:seams:graph:manifest>``; a vocabulary it does not declare targets
``1.0``. ``check_versions`` compares each target with the shipped version:

- **same** (same major, minor at most the tool's): nothing happens;
- **newer** (higher major, or same major and higher minor): ``ResolutionError``;
- **older** (lower major): the SPARQL Update files
  ``migrations/<name>/<from>-to-<to>.ru`` run over the loaded Dataset, in sorted
  vocabulary order and ascending step order, and the vocabulary's declaration is
  replaced with the shipped version IRI.

Migrations change only the in-memory Dataset; nothing here writes a file.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

from rdflib import OWL, RDF, Dataset, Graph, URIRef

from .errors import ResolutionError

#: Every SemanticSeams vocabulary IRI starts with this.
VOCABULARY_BASE = "https://w3id.org/seams/"

#: The payload manifest graph (ADR-0001) that holds the version declarations.
MANIFEST_GRAPH = URIRef("urn:seams:graph:manifest")

#: A model without a declaration for a vocabulary targets this version.
DEFAULT_VERSION = (1, 0)

_VERSION = re.compile(r"(\d+)\.(\d+)")
# SPARQL function names are case-insensitive.
_FORBIDDEN = re.compile(r"\b(NOW|RAND|UUID|STRUUID|BNODE)\s*\(", re.IGNORECASE)

Version = tuple[int, int]


class MigrationStep(NamedTuple):
    """One applied migration step: ``vocabulary`` moved from version
    ``source`` to version ``target`` (``"MAJOR.MINOR"`` strings)."""

    vocabulary: str
    source: str
    target: str


def version_text(version: Version) -> str:
    """``(2, 1)`` as ``"2.1"``."""
    return f"{version[0]}.{version[1]}"


def version_iri(vocabulary: str, version: Version) -> URIRef:
    """``https://w3id.org/seams/<vocabulary>/MAJOR.MINOR``."""
    return URIRef(f"{VOCABULARY_BASE}{vocabulary}/{version_text(version)}")


def shipped_versions(ontology_dir: str | Path) -> dict[str, Version]:
    """The version of each vocabulary in ``ontology_dir/*.ttl``, by name, read
    from its ``owl:versionIRI``. A vocabulary without a well-formed version IRI
    raises ``ResolutionError(<ontology>, owl:versionIRI)``."""
    directory = Path(ontology_dir).resolve()
    files = tuple(sorted(directory.glob("*.ttl"), key=lambda p: p.name))
    stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    return dict(_shipped(str(directory), stamp))


@cache
def _shipped(directory: str, stamp: tuple[tuple[str, int, int], ...]) -> tuple[tuple[str, Version], ...]:
    # ``stamp`` (name, mtime, size per file) is part of the key so an edited
    # vocabulary is read again.
    versions: dict[str, Version] = {}
    for name, _mtime, _size in stamp:
        graph = Graph()
        graph.parse(Path(directory) / name, format="turtle")
        for ontology in sorted(graph.subjects(RDF.type, OWL.Ontology), key=str):
            text = str(ontology)
            if not text.startswith(VOCABULARY_BASE):
                continue
            vocabulary = text[len(VOCABULARY_BASE) :]
            found = sorted({str(v) for v in graph.objects(ontology, OWL.versionIRI)})
            match = _VERSION.fullmatch(found[0][len(text) + 1 :]) if len(found) == 1 else None
            if match is None or not found[0].startswith(text + "/"):
                detail = f"expected one owl:versionIRI <{text}/MAJOR.MINOR> in {name}, found {found or 'none'}"
                raise ResolutionError(ontology, OWL.versionIRI, detail)
            versions[vocabulary] = (int(match[1]), int(match[2]))
    return tuple(sorted(versions.items()))


def declared_versions(ds: Dataset, shipped: dict[str, Version]) -> dict[str, Version]:
    """The version of each SemanticSeams vocabulary the model declares with
    ``owl:imports`` in the manifest graph, by name. Imports of other
    ontologies are ignored. Two different versions of one vocabulary, or a
    version this tool never published, raise
    ``ResolutionError(<urn:seams:graph:manifest>, owl:imports)``."""
    found: dict[str, set[Version]] = {}
    for iri in sorted(set(ds.graph(MANIFEST_GRAPH).objects(None, OWL.imports)), key=str):
        text = str(iri)
        if not text.startswith(VOCABULARY_BASE):
            continue
        vocabulary, _sep, number = text[len(VOCABULARY_BASE) :].partition("/")
        match = _VERSION.fullmatch(number)
        tool = shipped.get(vocabulary)
        version = (int(match[1]), int(match[2])) if match is not None else (0, 0)
        # A newer version is reported by check_versions; anything else the tool
        # cannot place (an unknown vocabulary, no MAJOR.MINOR, major 0) is unpublished.
        if tool is None or version[0] < 1:
            raise ResolutionError(
                MANIFEST_GRAPH, OWL.imports, f"{text} is not a published SemanticSeams vocabulary version"
            )
        found.setdefault(vocabulary, set()).add(version)
    declared: dict[str, Version] = {}
    for vocabulary, versions in sorted(found.items()):
        if len(versions) > 1:
            listed = ", ".join(f"<{version_iri(vocabulary, v)}>" for v in sorted(versions))
            raise ResolutionError(MANIFEST_GRAPH, OWL.imports, f"declarations disagree on {vocabulary}: {listed}")
        declared[vocabulary] = next(iter(versions))
    return declared


def _step_files(ontology_dir: Path, vocabulary: str, source: Version, target: Version) -> list[Path]:
    steps: list[Path] = []
    for major in range(source[0], target[0]):
        path = ontology_dir / "migrations" / vocabulary / f"{major}-to-{major + 1}.ru"
        if not path.is_file():
            detail = f"no migration step {vocabulary} {major}-to-{major + 1} (migrations/{vocabulary}/{path.name})"
            raise ResolutionError(MANIFEST_GRAPH, OWL.imports, detail)
        forbidden = _FORBIDDEN.search(path.read_text(encoding="utf-8"))
        if forbidden is not None:
            detail = f"migration migrations/{vocabulary}/{path.name} calls {forbidden[1].upper()}(), which is not deterministic"
            raise ResolutionError(MANIFEST_GRAPH, OWL.imports, detail)
        steps.append(path)
    return steps


def _redeclare(ds: Dataset, vocabulary: str, version: Version) -> None:
    manifest = ds.graph(MANIFEST_GRAPH)
    prefix = f"{VOCABULARY_BASE}{vocabulary}/"
    old = [(s, o) for s, o in manifest.subject_objects(OWL.imports) if str(o).startswith(prefix)]
    subjects = {s for s, _o in old} or {MANIFEST_GRAPH}
    for s, o in old:
        manifest.remove((s, OWL.imports, o))
    if not old:
        manifest.add((MANIFEST_GRAPH, RDF.type, OWL.Ontology))
    for s in subjects:
        manifest.add((s, OWL.imports, version_iri(vocabulary, version)))


def check_versions(ds: Dataset, ontology_dir: str | Path) -> tuple[MigrationStep, ...]:
    """Run the ADR-0021 load check on ``ds`` against the vocabularies in
    ``ontology_dir`` and migrate it in place. Returns the steps applied,
    sorted (vocabulary, then ascending version). A model newer than the tool,
    or a missing or non-deterministic migration step, raises
    ``ResolutionError`` before ``ds`` is changed."""
    directory = Path(ontology_dir).resolve()
    shipped = shipped_versions(directory)
    declared = declared_versions(ds, shipped)
    plan: list[tuple[str, Version, Version, list[Path]]] = []
    for vocabulary, tool in sorted(shipped.items()):
        target = declared.get(vocabulary, DEFAULT_VERSION)
        if target[0] > tool[0] or (target[0] == tool[0] and target[1] > tool[1]):
            detail = f"targets {vocabulary} {version_text(target)}; this tool supports {vocabulary} up to {version_text(tool)}"
            raise ResolutionError(MANIFEST_GRAPH, OWL.imports, detail)
        if target[0] < tool[0]:
            plan.append((vocabulary, target, tool, _step_files(directory, vocabulary, target, tool)))
    applied: list[MigrationStep] = []
    for vocabulary, target, tool, steps in plan:
        for major, path in enumerate(steps, start=target[0]):
            ds.update(path.read_text(encoding="utf-8"))
            source = target if major == target[0] else (major, 0)
            reached = tool if major + 1 == tool[0] else (major + 1, 0)
            applied.append(MigrationStep(vocabulary, version_text(source), version_text(reached)))
        _redeclare(ds, vocabulary, tool)
    return tuple(applied)
