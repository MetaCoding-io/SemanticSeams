"""``seams check``: does a project still hold together? (M012/S03, D044)

Five checks run, and a sixth when the project asks for it; every finding
is reported and nothing is written.

- ``shacl``: the model, unioned with ``ontology/*.ttl``, is validated against
  ``ontology/shapes/seam-shapes.ttl`` with inference off, as the viewer and
  tests/validate_chat_app.py do. One finding per sh:ValidationResult.
- ``gate``: each SELECT query the project file lists under ``gates`` runs over
  the same union graph and must return no rows. One finding per row.
- outputs: every generator runs in memory and the result is compared with the
  disk and with seams.lock (D043). ``missing``: produced but absent on disk.
  ``stale``: on disk but different from the produced text. ``hand-edited``: a
  stale file whose sha256 is not the locked one either. ``orphan``: locked, no
  longer produced, still on disk. ``lock-out-of-date``: no seams.lock, or the
  lock generate would write differs from the one on disk.
- ``decision``: one finding per fault ``seams.decision_findings`` reports
  (backlog K2, M017/S02): a DMN input whose typeRef disagrees with the
  sh:datatype of its dec:fromPath, or a gateway condition reading a variable
  nothing upstream sets. The detail is the subject IRI (the decision or the
  sequence flow), the fact (the property or the variable) and the message.
- ``review``: one finding per fault ``seams.review_findings`` reports
  (backlog R1, M017/S04): lifecycle state labels copied into sh:in, sh:class
  pointing at a sh:NodeShape, a shape without sh:targetClass, or a sh:path
  nothing declares a property. The detail is the subject IRI, the fact and
  the message. Review findings are advisory (ADVISORY_KINDS): they are
  reported but do not make ``seams check`` fail.
- ``coverage``: with ``coverage = ["paths"]`` in the project file, one finding
  per BPMN path no verify:Scenario runs (``seams.coverage``, D054): the
  process IRI, then the path's flow node IRIs.

A model that cannot be loaded, a missing, unparsable or non-SELECT gate, and a
malformed seams.lock raise ProjectError.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pyshacl
import rdflib
import seams
from rdflib.plugins.sparql import prepareQuery

import seams_gen

from .coverage import path_gaps
from .generate import generate_project
from .lockfile import audit, build_lock, locate, lock_path, read_lock, relative, render_lock
from .project import Project, ProjectError

ONTOLOGY_DIR = Path(seams_gen.__file__).resolve().parents[1] / "ontology"
SHAPES_FILE = ONTOLOGY_DIR / "shapes" / "seam-shapes.ttl"
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")

# Finding kinds whose detail is an absolute file path.
FILE_KINDS = frozenset({"missing", "stale", "hand-edited", "orphan", "lock-out-of-date"})

# Finding kinds that flag the model for review but do not fail the check.
ADVISORY_KINDS = frozenset({"review"})


class Finding(NamedTuple):
    """One problem. ``detail`` is an absolute path for the FILE_KINDS, else free text."""

    kind: str
    detail: str


def model_graph(model: Path) -> rdflib.Graph:
    """The model's quads (a TriG file or a directory of them) and ``ontology/*.ttl`` in one graph."""
    try:
        ds = seams.load(model).ds
    except Exception as err:
        raise ProjectError(f"{model}: cannot load the model: {err}") from err
    union = rdflib.Graph()
    for path in sorted(ONTOLOGY_DIR.glob("*.ttl")):
        union.parse(path, format="turtle")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    return union


def check_shapes(graph: rdflib.Graph) -> list[Finding]:
    _conforms, results, _text = pyshacl.validate(graph, shacl_graph=str(SHAPES_FILE), inference="none")
    findings = []
    for result in results.subjects(rdflib.RDF.type, SH.ValidationResult):
        parts = (results.value(result, key) for key in (SH.focusNode, SH.resultPath, SH.resultMessage))
        findings.append(Finding("shacl", " ".join(str(v) if v is not None else "-" for v in parts)))
    return findings


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
            values = " ".join(str(v) if v is not None else "-" for v in row)
            findings.append(Finding("gate", f"{name} {values}"))
    return findings


def check_outputs(project: Project, model: Path) -> list[Finding]:
    """Compare the outputs produced now with the disk and with seams.lock. Writes nothing."""
    old = read_lock(project)
    outputs = generate_project(project, model)
    files = {path: out.text for path, out in outputs.items()}
    report = audit(project, old, files)
    edited = {locate(project, rel) for rel in report.edited}
    findings = []
    for path, text in files.items():
        if not path.is_file():
            findings.append(Finding("missing", str(path)))
        elif path.read_bytes() != text.encode("utf-8"):
            findings.append(Finding("hand-edited" if path in edited else "stale", str(path)))
    for rel in report.orphans:
        path = locate(project, rel)
        if path.exists() or path.is_symlink():
            findings.append(Finding("orphan", str(path)))
    target = lock_path(project)
    if old is None or target.read_text(encoding="utf-8") != render_lock(build_lock(project, model, outputs)):
        findings.append(Finding("lock-out-of-date", str(target)))
    return findings


def check_coverage(project: Project, model: Path) -> list[Finding]:
    """One finding per unexercised BPMN path, when the project lists ``paths`` under ``coverage``."""
    if "paths" not in project.coverage:
        return []
    return [Finding("coverage", " ".join(gap.iris)) for gap in path_gaps(seams.load(model))]


def check_decisions(model: Path) -> list[Finding]:
    """One finding per static decision fault: the subject IRI, the fact, then the message."""
    return [
        Finding("decision", f"{f.subject} {f.fact} {f.message}") for f in seams.decision_findings(seams.load(model))
    ]


def check_review(model: Path) -> list[Finding]:
    """One advisory finding per model review fault: the subject IRI, the fact, then the message."""
    return [Finding("review", f"{f.subject} {f.fact} {f.message}") for f in seams.review_findings(seams.load(model))]


def run_check(project: Project, model: Path) -> list[Finding]:
    """Every finding of the checks, sorted by kind and detail."""
    graph = model_graph(model)
    findings = check_gates(project, graph) + check_shapes(graph) + check_outputs(project, model)
    findings += check_decisions(model) + check_review(model) + check_coverage(project, model)
    return sorted(findings)


__all__ = [
    "ADVISORY_KINDS",
    "Finding",
    "check_coverage",
    "check_decisions",
    "check_gates",
    "check_outputs",
    "check_review",
    "check_shapes",
    "model_graph",
    "run_check",
]
