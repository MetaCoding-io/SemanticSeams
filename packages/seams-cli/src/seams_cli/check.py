"""``seams check``: does a project still hold together? (M012/S03, D044)

Seven checks run, and an eighth when the project asks for it; every finding
is reported and nothing is written.

- ``shacl``: the model, unioned with ``ontology/*.ttl``, is validated against
  ``ontology/shapes/seam-shapes.ttl`` with inference off, as the viewer and
  tests/validate_chat_app.py do. One finding per sh:ValidationResult whose
  severity is not sh:Warning. A sh:Warning result (the shape of a deprecated
  vocabulary term, ADR-0021 section 6) is a ``shacl-warning`` finding instead,
  which is advisory: the detail is the same focus node, path and message.
- ``vocabulary-migrated``: one advisory finding per migration step
  ``seams.load`` applied to the model (``Model.migrations``, ADR-0021 section
  5): the vocabulary, the version the model targets and the tool's version.
- ``gate``: each SELECT query the project file lists under ``gates`` runs over
  the same union graph and must return no rows. One finding per row.
- outputs: every generator runs in memory and the result is compared with the
  disk and with seams.lock (D043). ``missing``: produced but absent on disk.
  ``stale``: on disk but different from the produced text. ``hand-edited``: a
  stale file whose sha256 is not the locked one either. ``orphan``: locked, no
  longer produced, still on disk. ``lock-out-of-date``: no seams.lock, or the
  lock generate would write differs from the one on disk. Generation here is
  lenient (D057): a generator fault does not stop the check, its outputs and
  orphans are compared as ``seams generate --lenient`` would leave them, and a
  fault the on-disk lock does not record makes the lock out of date.
- ``flagged``: the on-disk seams.lock records faults, so its outputs came from
  ``seams generate --lenient`` (D057). The detail is the lock path and the
  fault count. It is a problem, not advisory, which is how CI rejects a
  flagged lock.
- ``decision``: one finding per fault ``seams.decision_findings`` reports
  (backlog K2, M017/S02): a DMN input whose typeRef disagrees with the
  sh:datatype of its dec:fromPath, a gateway condition reading a variable
  nothing upstream sets, or overlapping rules and an uncovered input of a
  UNIQUE decision table (backlog X13). The detail is the subject IRI (the decision or the
  sequence flow), the fact (the property or the variable) and the message.
- ``review``: one finding per fault ``seams.review_findings`` reports
  (backlog R1, M017/S04): lifecycle state labels copied into sh:in, sh:class
  pointing at a sh:NodeShape, a shape without sh:targetClass, or a sh:path
  nothing declares a property. The detail is the subject IRI, the fact and
  the message. Review findings are advisory (ADVISORY_KINDS), like
  ``shacl-warning`` and ``vocabulary-migrated``: they are reported but do not
  make ``seams check`` fail.
- ``ontology-superclass``: one advisory finding per ``rdfs:subClassOf``
  target of a ``seam:Ontology`` class declared neither in the ontology nor in
  a resolved import (ADR-0022 section 5): rdflib does not reason, so it is a
  likely typo (``gist:Transation``), not a contradiction. The detail is the
  class IRI, ``rdfs:subClassOf``, the target IRI and the message. An import
  that does not resolve is a ``ResolutionError`` on load, so a ProjectError.
- ``coverage``: with ``coverage = ["paths"]`` in the project file, one finding
  per BPMN path no verify:Scenario runs (``seams.coverage``, D054): the
  process IRI, then the path's flow node IRIs.
- drafts: one pass over the ``drafts`` seams.lock records (``seams propose``,
  ADR-0020, M022/S05). ``draft-stale``: the task's context hash
  (``seams.context_for``, as ``build_prompt`` computes it) differs from the
  recorded one, or the task no longer resolves; the draft must be reviewed
  again. ``draft-hand-edited``: the file's sha256 differs from the recorded
  one, or the file is missing. The detail is the task IRI and the lock path,
  then for a missing file or an unresolved task the reason.

A model that cannot be loaded, a missing, unparsable or non-SELECT gate, and a
malformed seams.lock raise ProjectError.

The model is loaded, unioned and validated against the vocabularies, shapes and
migrations of ``ontology_dir`` (default: the repository's ``ontology/``); the
tests pass a fixture tree there (D060). Generation always uses the default.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, cast

import pyshacl
import rdflib
import seams
from rdflib import RDFS
from rdflib.plugins.sparql import prepareQuery
from rdflib.query import ResultRow

import seams_gen

from .coverage import path_gaps
from .generate import generate_project, next_lock
from .lockfile import audit, locate, lock_path, read_lock, relative, render_lock, sha256_file
from .project import Project, ProjectError

ONTOLOGY_DIR = Path(seams_gen.__file__).resolve().parents[1] / "ontology"
SHAPES_FILE = ONTOLOGY_DIR / "shapes" / "seam-shapes.ttl"
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")

# Finding kinds whose detail is an absolute file path.
FILE_KINDS = frozenset({"missing", "stale", "hand-edited", "orphan", "lock-out-of-date"})

# Finding kinds that flag the model for review but do not fail the check.
ADVISORY_KINDS = frozenset({"ontology-superclass", "review", "shacl-warning", "vocabulary-migrated"})


class Finding(NamedTuple):
    """One problem. ``detail`` is an absolute path for the FILE_KINDS, else free text."""

    kind: str
    detail: str


def load_model(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> seams.Model:
    """``seams.load`` against ``ontology_dir``; a model that cannot be loaded is a ProjectError."""
    try:
        return seams.load(model, ontology_dir=ontology_dir)
    except Exception as err:
        raise ProjectError(f"{model}: cannot load the model: {err}") from err


def model_graph(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> rdflib.Graph:
    """The model's quads (a TriG file or a directory of them), migrated as
    ``seams.load`` does, and ``<ontology_dir>/*.ttl`` in one graph."""
    ds = load_model(model, ontology_dir).ds
    union = rdflib.Graph()
    for path in sorted(ontology_dir.glob("*.ttl")):
        union.parse(path, format="turtle")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    return union


def check_shapes(graph: rdflib.Graph, shapes_file: Path = SHAPES_FILE) -> list[Finding]:
    """One ``shacl`` finding per result, or ``shacl-warning`` for a sh:Warning result."""
    _conforms, report, _text = pyshacl.validate(graph, shacl_graph=str(shapes_file), inference="none")
    results = cast(rdflib.Graph, report)
    findings = []
    for result in results.subjects(rdflib.RDF.type, SH.ValidationResult):
        kind = "shacl-warning" if results.value(result, SH.resultSeverity) == SH.Warning else "shacl"
        parts = (results.value(result, key) for key in (SH.focusNode, SH.resultPath, SH.resultMessage))
        findings.append(Finding(kind, " ".join(str(v) if v is not None else "-" for v in parts)))
    return findings


def check_migrations(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """One advisory finding per migration step applied on load: vocabulary, from, to."""
    return [
        Finding("vocabulary-migrated", f"{step.vocabulary} {step.source} {step.target}")
        for step in load_model(model, ontology_dir).migrations
    ]


def _gate_query(project: Project, gate: Path):
    if not gate.is_file():
        raise ProjectError(f"{project.path}: gate {gate} does not exist")
    try:
        query = prepareQuery(gate.read_text(encoding="utf-8"))
    except Exception as err:
        raise ProjectError(f"{gate}: invalid SPARQL: {err}") from err
    if query.algebra.name != "SelectQuery":
        raise ProjectError(f"{gate}: a gate must be a SELECT query, got {query.algebra.name}")
    return query


def check_gates(project: Project, graph: rdflib.Graph) -> list[Finding]:
    """One finding per row of every gate. Every gate is parsed before any runs."""
    queries = [(gate, _gate_query(project, gate)) for gate in project.gates]
    findings = []
    for gate, query in queries:
        name = relative(project, gate)
        for row in graph.query(query):
            values = " ".join(str(v) if v is not None else "-" for v in cast(ResultRow, row))
            findings.append(Finding("gate", f"{name} {values}"))
    return findings


def check_outputs(project: Project, model: Path) -> list[Finding]:
    """Compare the outputs produced now with the disk and with seams.lock. Writes nothing."""
    old = read_lock(project)
    generated = generate_project(project, model, lenient=True)
    files = {path: out.text for path, out in generated.files.items()}
    report = audit(project, old, files)
    faulted = {fault.generator for fault in generated.faults}
    generators = {entry.path: entry.generator for entry in old.outputs} if old else {}
    edited = {locate(project, rel) for rel in report.edited}
    findings = []
    for path, text in files.items():
        if not path.is_file():
            findings.append(Finding("missing", str(path)))
        elif path.read_bytes() != text.encode("utf-8"):
            findings.append(Finding("hand-edited" if path in edited else "stale", str(path)))
    for rel in report.orphans:
        if generators[rel] in faulted:
            continue
        path = locate(project, rel)
        if path.exists() or path.is_symlink():
            findings.append(Finding("orphan", str(path)))
    target = lock_path(project)
    if old is None or target.read_text(encoding="utf-8") != render_lock(
        next_lock(project, model, generated, old, report)
    ):
        findings.append(Finding("lock-out-of-date", str(target)))
    if old is not None and old.faults:
        findings.append(Finding("flagged", f"{target} {len(old.faults)} fault(s)"))
    return findings


def check_coverage(project: Project, model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """One finding per unexercised BPMN path, when the project lists ``paths`` under ``coverage``."""
    if "paths" not in project.coverage:
        return []
    return [Finding("coverage", " ".join(gap.iris)) for gap in path_gaps(load_model(model, ontology_dir))]


def check_decisions(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """One finding per static decision fault: the subject IRI, the fact, then the message."""
    return [
        Finding("decision", f"{f.subject} {f.fact} {f.message}")
        for f in seams.decision_findings(load_model(model, ontology_dir))
    ]


def check_review(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """One advisory finding per model review fault: the subject IRI, the fact, then the message."""
    return [
        Finding("review", f"{f.subject} {f.fact} {f.message}")
        for f in seams.review_findings(load_model(model, ontology_dir))
    ]


def check_ontology(model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """One advisory finding per undeclared superclass: the class, rdfs:subClassOf, the target, the message."""
    return [
        Finding(
            "ontology-superclass",
            f"{cls.iri} {RDFS.subClassOf} {sup.iri} declared neither in the ontology nor in a resolved import",
        )
        for ontology in load_model(model, ontology_dir).ontologies
        for cls in ontology.classes()
        for sup in cls.superclasses
        if sup.source is None
    ]


def check_drafts(project: Project, model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """``draft-stale`` and ``draft-hand-edited`` findings for the lock's ``seams propose`` drafts."""
    lock = read_lock(project)
    if lock is None or not lock.drafts:
        return []
    graph = seams.ModelGraph(model, load_model(model, ontology_dir).ds)
    findings = []
    for draft in lock.drafts:
        name = f"{draft.task} {draft.path}"
        try:
            context_hash = seams.context_for(graph, draft.task).context_hash
        except seams.ResolutionError as err:
            findings.append(Finding("draft-stale", f"{name} {err}"))
        else:
            if context_hash != draft.context_hash:
                findings.append(Finding("draft-stale", name))
        path = locate(project, draft.path)
        if not path.is_file():
            findings.append(Finding("draft-hand-edited", f"{name} missing"))
        elif sha256_file(path) != draft.sha256:
            findings.append(Finding("draft-hand-edited", name))
    return findings


def run_check(project: Project, model: Path, ontology_dir: Path = ONTOLOGY_DIR) -> list[Finding]:
    """Every finding of the checks, sorted by kind and detail."""
    graph = model_graph(model, ontology_dir)
    findings = check_gates(project, graph) + check_shapes(graph, ontology_dir / "shapes" / "seam-shapes.ttl")
    findings += check_migrations(model, ontology_dir) + check_outputs(project, model)
    findings += check_decisions(model, ontology_dir) + check_review(model, ontology_dir)
    findings += check_ontology(model, ontology_dir)
    findings += check_coverage(project, model, ontology_dir) + check_drafts(project, model, ontology_dir)
    return sorted(findings)


__all__ = [
    "ADVISORY_KINDS",
    "Finding",
    "check_coverage",
    "check_decisions",
    "check_drafts",
    "check_gates",
    "check_migrations",
    "check_ontology",
    "check_outputs",
    "check_review",
    "check_shapes",
    "load_model",
    "model_graph",
    "run_check",
]
