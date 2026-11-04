"""Ontology imports: the ADR-0022 offline resolution of ``owl:imports``.

A ``seam:Ontology`` model is also an ``owl:Ontology``, and its ``owl:imports``
name the version IRIs of the ontologies it builds on (gist). Nothing is fetched:
the imports resolve against the files in ``<ontology_dir>/vendor/*.ttl``, each
indexed by the ``owl:Ontology`` IRI and the ``owl:versionIRI`` in its own header.
Per import, in sorted (ontology, import) order:

- the version IRI of a vendored file **resolves** to that file;
- the bare ontology IRI of a vendored file, or an IRI that starts with it, is a
  **version mismatch**;
- a SemanticSeams vocabulary version is **misplaced** (those belong in the
  manifest graph, ADR-0021);
- anything else is **unresolved**.

``import_statuses`` reports every import without raising; ``check_imports``
raises the first fault as ``ResolutionError(<ontology>, owl:imports, detail)``.
A vendored file is read into its own graph and never merged into the model's
Dataset, so the model hash, SHACL and the generators see only the model.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import NamedTuple

from rdflib import OWL, RDF, Dataset, Graph, URIRef
from rdflib.graph import ReadOnlyGraphAggregate

from .errors import ResolutionError
from .namespaces import SEAM, local_name
from .vocabularies import VOCABULARY_BASE

#: The directory, under an ontology directory, that holds vendored ontologies.
VENDOR_DIR = "vendor"


class VendoredOntology(NamedTuple):
    """A file in ``vendor/``: its ``owl:Ontology`` IRI, its ``owl:versionIRI``
    and its path."""

    ontology: URIRef
    version: URIRef
    path: Path


class ImportStatus(NamedTuple):
    """One ``owl:imports`` of a ``seam:Ontology`` model. ``vendored`` is the
    file it resolves to (None when it does not), ``detail`` the fault ("" when
    it resolves)."""

    ontology: URIRef
    imported: URIRef
    vendored: VendoredOntology | None
    detail: str

    @property
    def resolved(self) -> bool:
        return self.vendored is not None

    @property
    def error(self) -> ResolutionError | None:
        """``ResolutionError(ontology, owl:imports, detail)``, or None when it resolves."""
        return None if self.vendored is not None else ResolutionError(self.ontology, OWL.imports, self.detail)


def vendored_ontologies(ontology_dir: str | Path) -> tuple[VendoredOntology, ...]:
    """Each ``vendor/*.ttl`` under ``ontology_dir``, sorted by version IRI; none
    when there is no ``vendor/``. A file that does not declare exactly one
    ``owl:Ontology`` with exactly one ``owl:versionIRI`` raises
    ``ResolutionError(<file or ontology>, owl:versionIRI)``."""
    directory = (Path(ontology_dir) / VENDOR_DIR).resolve()
    files = tuple(sorted(directory.glob("*.ttl"), key=lambda p: p.name)) if directory.is_dir() else ()
    stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    return _vendored(str(directory), stamp)


@cache
def _vendored(directory: str, stamp: tuple[tuple[str, int, int], ...]) -> tuple[VendoredOntology, ...]:
    # ``stamp`` (name, mtime, size per file) is part of the key so an edited file is read again.
    found: list[VendoredOntology] = []
    for name, mtime, size in stamp:
        path = Path(directory) / name
        graph = _parse(str(path), mtime, size)
        ontologies = sorted({s for s in graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)}, key=str)
        if len(ontologies) != 1:
            subject = ontologies[0] if ontologies else URIRef(path.as_uri())
            raise ResolutionError(
                subject, RDF.type, f"expected one owl:Ontology in {VENDOR_DIR}/{name}, found {len(ontologies)}"
            )
        versions = sorted({v for v in graph.objects(ontologies[0], OWL.versionIRI) if isinstance(v, URIRef)}, key=str)
        if len(versions) != 1:
            listed = ", ".join(str(v) for v in versions) or "none"
            detail = f"expected one owl:versionIRI in {VENDOR_DIR}/{name}, found {listed}"
            raise ResolutionError(ontologies[0], OWL.versionIRI, detail)
        found.append(VendoredOntology(ontologies[0], versions[0], path))
    return tuple(sorted(found, key=lambda v: str(v.version)))


@cache
def _parse(path: str, _mtime: int, _size: int) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def vendored_graph(vendored: VendoredOntology) -> ReadOnlyGraphAggregate:
    """The triples of a vendored file, read-only (an edit raises)."""
    stat = vendored.path.stat()
    return ReadOnlyGraphAggregate([_parse(str(vendored.path), stat.st_mtime_ns, stat.st_size)])


def ontology_models(ds: Dataset) -> list[URIRef]:
    """The ``seam:Model``s whose ``seam:notation`` is ``seam:Ontology``, sorted."""
    return sorted({m for m in ds.subjects(SEAM.notation, SEAM.Ontology) if isinstance(m, URIRef)}, key=str)


def _status(ontology: URIRef, imported: URIRef, vendored: tuple[VendoredOntology, ...]) -> ImportStatus:
    text = str(imported)
    for v in vendored:
        if imported == v.version:
            return ImportStatus(ontology, imported, v, "")
    # The longest vendored ontology IRI the import starts with: its versions are the candidates.
    family = sorted((v for v in vendored if text.startswith(str(v.ontology))), key=lambda v: -len(str(v.ontology)))
    if family:
        candidates = [v for v in vendored if v.ontology == family[0].ontology]
        listed = ", ".join(local_name(v.version) for v in candidates)
        noun = "version is" if len(candidates) == 1 else "versions are"
        return ImportStatus(ontology, imported, None, f"imports {local_name(imported)}; the vendored {noun} {listed}")
    if text.startswith(VOCABULARY_BASE):
        detail = f"imports <{text}>; declare vocabulary versions in the manifest graph (ADR-0021)"
        return ImportStatus(ontology, imported, None, detail)
    return ImportStatus(ontology, imported, None, f"imports <{text}>, which no file in ontology/{VENDOR_DIR}/ declares")


def import_statuses(ds: Dataset, ontology_dir: str | Path | None) -> tuple[ImportStatus, ...]:
    """The status of every ``owl:imports`` of every ``seam:Ontology`` model in
    ``ds``, sorted by (ontology, import). Without ``ontology_dir`` nothing is
    vendored, so every import is unresolved."""
    vendored = vendored_ontologies(ontology_dir) if ontology_dir is not None else ()
    out: list[ImportStatus] = []
    for ontology in ontology_models(ds):
        imports = sorted({i for i in ds.objects(ontology, OWL.imports) if isinstance(i, URIRef)}, key=str)
        out.extend(_status(ontology, imported, vendored) for imported in imports)
    return tuple(out)


def check_imports(ds: Dataset, ontology_dir: str | Path) -> tuple[VendoredOntology, ...]:
    """Resolve every ontology import in ``ds`` against ``ontology_dir/vendor``.
    Returns the vendored ontologies imported, sorted by version IRI; the first
    fault, in (ontology, import) order, raises ``ResolutionError(<ontology>,
    owl:imports, detail)``."""
    resolved: dict[URIRef, VendoredOntology] = {}
    for status in import_statuses(ds, ontology_dir):
        if status.vendored is None:
            raise ResolutionError(status.ontology, OWL.imports, status.detail)
        resolved[status.vendored.version] = status.vendored
    return tuple(resolved[k] for k in sorted(resolved, key=str))
