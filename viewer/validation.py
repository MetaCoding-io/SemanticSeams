"""Reusable SHACL conformance check for the viewer's loaded model.

The viewer's Dataset (see viewer/app.py get_graph()) loads only the configured
model's TriG (SEAMS_MODEL, default examples/chat-app/chat-app.trig) — it
carries no ontology triples. The shapes
in ontology/shapes/seam-shapes.ttl rely on subclass closure from the ontology
files (sh:class checks), so validation here mirrors tests/validate_chat_app.py:
merge the ontology .ttl files with the dataset's quads into one union graph,
then run pyshacl against seam-shapes.ttl with inference off.

The same summary carries the storage health checks of ADR-0011
(seams.ModelGraph.store_health()): a store the runtime cannot resolve is a
violation, a declared store no shape is seam:storedIn is a warning, and a model
that declares no store gets a note that the runtime keeps embedded SQLite.
The replica cap of ADR-0015 (seams.ModelGraph.replica_health()) joins them: a
serving container declaring more than one deploy:replicas is a warning, since
the generator runs one until backlog A10. The model review checks of backlog
R1 (seams.review_findings()) add one warning each: lifecycle labels copied
into sh:in, sh:class pointing at a shape, shapes without sh:targetClass and
undeclared sh:path IRIs. They flag the model for review and never change
``conforms``, not even when the check itself fails.

The lifted-IRI check of ADR-0002 rule 4 (get_lifted_iri_health()) is read-only
and separate from ``conforms``: for each BPMN or DMN model with a
seam:renderPayload, every IRI of the dataset starting with ``modelIRI#`` must
name an ``id`` in the payload XML, so an edit that drops or renames an id
without its quads shows up here.

Results are cached per Dataset identity: the model is loaded once per process,
so each dataset is validated at most once.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import rdflib
import seams
from lxml import etree
from rdflib import Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"

SH = Namespace("http://www.w3.org/ns/shacl#")
SEAM = Namespace("https://w3id.org/seams/seam#")

# Notations whose model elements are lifted from a payload's XML ids (ADR-0002).
LIFTED_NOTATIONS = (SEAM.BPMN, SEAM.DMN)

# Conformance and lifted-IRI caches keyed by id(ds); the viewer holds one Dataset
# per process. Python recycles id() values, so both are cleared together (MEM010).
_cache: dict[int, dict] = {}
_lifted_cache: dict[int, list[dict]] = {}


def _clear_cache() -> None:
    _cache.clear()
    _lifted_cache.clear()


def _short_name(term) -> str:
    """Local name of a URIRef (e.g. sh:Violation -> 'Violation')."""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


def _build_union(ds: rdflib.Dataset) -> rdflib.Graph:
    union = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        union.parse(p, format="turtle")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    return union


def _finding(finding: seams.StoreFinding) -> dict:
    return {
        "focusNode": str(finding.subject) if finding.subject is not None else None,
        "path": str(finding.predicate) if finding.predicate is not None else None,
        "message": finding.message,
        "severity": finding.severity,
        "sourceShape": None,
    }


def _store_findings(ds: rdflib.Dataset) -> list[dict]:
    """store_health() over the same Dataset (no file is read when a dataset
    is passed). A failure of the check itself is reported as a violation
    rather than taking the page down."""
    try:
        model = seams.ModelGraph(ROOT / "viewer.trig", dataset=ds)
        findings = model.store_health() + model.replica_health()
    except Exception as err:
        return [
            {
                "focusNode": None,
                "path": None,
                "message": f"store health check failed: {err}",
                "severity": "Violation",
                "sourceShape": None,
            }
        ]
    return [_finding(f) for f in findings]


def _review_findings(ds: rdflib.Dataset) -> list[dict]:
    """seams.review_findings() over the same Dataset, one Warning each with the
    subject as focusNode and the fact as path. A failure of the check itself is
    one Warning too, so review findings never change ``conforms``."""
    try:
        findings = seams.review_findings(seams.ModelGraph(ROOT / "viewer.trig", dataset=ds))
    except Exception as err:
        return [
            {
                "focusNode": None,
                "path": None,
                "message": f"model review check failed: {err}",
                "severity": "Warning",
                "sourceShape": None,
            }
        ]
    return [
        {
            "focusNode": f.subject,
            "path": f.fact,
            "message": f.message,
            "severity": "Warning",
            "sourceShape": None,
        }
        for f in findings
    ]


def get_model_conformance(ds: rdflib.Dataset) -> dict:
    """Validate the dataset (plus ontology closure) against seam-shapes.ttl,
    then run the storage health and model review checks.

    Returns {"conforms": bool, "violationCount": int, "violations": list[dict],
    "warnings": list[dict], "notes": list[dict]}. Each entry carries focusNode,
    path, message, severity, and sourceShape (focusNode, path and sourceShape
    may be None). Store violations join ``violations`` and make the model not
    conform; warnings (store, replica and review findings, in that order) and
    notes do not change ``conforms``.
    """
    key = id(ds)
    if key in _cache:
        return _cache[key]

    union = _build_union(ds)
    conforms, results_graph, _text = pyshacl.validate(union, shacl_graph=str(SHAPES_FILE), inference="none")

    violations: list[dict] = []
    for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
        focus = results_graph.value(result, SH.focusNode)
        path = results_graph.value(result, SH.resultPath)
        message = results_graph.value(result, SH.resultMessage)
        severity = results_graph.value(result, SH.resultSeverity)
        source_shape = results_graph.value(result, SH.sourceShape)
        violations.append(
            {
                "focusNode": str(focus) if focus is not None else None,
                "path": str(path) if path is not None else None,
                "message": str(message) if message is not None else None,
                "severity": _short_name(severity) if severity is not None else None,
                "sourceShape": str(source_shape) if source_shape is not None else None,
            }
        )

    store = _store_findings(ds)
    violations += [f for f in store if f["severity"] == "Violation"]
    warnings = [f for f in store if f["severity"] == "Warning"] + _review_findings(ds)
    notes = [f for f in store if f["severity"] == "Info"]

    summary = {
        "conforms": bool(conforms) and not any(f["severity"] == "Violation" for f in store),
        "violationCount": len(violations),
        "violations": violations,
        "warnings": warnings,
        "notes": notes,
    }
    _cache[key] = summary
    return summary


def _payload_ids(path: Path) -> set[str]:
    """Every ``id`` attribute in the payload XML, entities unexpanded, no network."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.parse(str(path), parser).getroot()
    return {
        str(value)
        for el in root.iter()
        if isinstance(el.tag, str)
        for name, value in el.attrib.items()
        if etree.QName(name).localname == "id"
    }


def _lifted_finding(iri: str | None, model: str, message: str) -> dict:
    return {"iri": iri, "model": model, "message": message}


def get_lifted_iri_health(ds: rdflib.Dataset, base_dir: Path) -> list[dict]:
    """IRIs lifted from a BPMN or DMN payload whose fragment is no id of the XML.

    For each subject with seam:notation seam:BPMN or seam:DMN and a
    seam:renderPayload (resolved with seams.payload_path against ``base_dir``,
    the directory the viewer resolves payloads against), every subject or object
    IRI of ``ds`` that starts with ``modelIRI#`` must have its fragment as an
    ``id`` in the payload (ADR-0002 rule 4). Returns one {"iri", "model",
    "message"} per dangling IRI, sorted by model then IRI. A payload that is
    missing or not well-formed XML is one finding with ``iri`` None, so the check
    never takes the page down. Cached per dataset like get_model_conformance().
    """
    key = id(ds)
    if key in _lifted_cache:
        return _lifted_cache[key]

    iris = {
        term for s, _p, o, _ctx in ds.quads((None, None, None, None)) for term in (s, o) if isinstance(term, URIRef)
    }
    findings: list[dict] = []
    models = sorted({m for notation in LIFTED_NOTATIONS for m in ds.subjects(SEAM.notation, notation)}, key=str)
    for model in models:
        payload = ds.value(model, SEAM.renderPayload)
        if payload is None:
            continue
        path = seams.payload_path(payload, base_dir)
        try:
            ids = _payload_ids(path)
        except (OSError, etree.XMLSyntaxError) as err:
            findings.append(_lifted_finding(None, str(model), f"payload {path.name} cannot be read: {err}"))
            continue
        prefix = f"{model}#"
        for iri in sorted(str(i) for i in iris if str(i).startswith(prefix)):
            fragment = iri[len(prefix) :]
            if fragment not in ids:
                findings.append(_lifted_finding(iri, str(model), f'{path.name} has no element with id "{fragment}"'))

    _lifted_cache[key] = findings
    return findings
