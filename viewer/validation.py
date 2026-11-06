"""Reusable SHACL conformance check for the viewer's loaded model.

The viewer's Dataset (see viewer/app.py get_graph()) loads only the configured
model's TriG (SEAMS_MODEL, default examples/chat-app/chat-app.trig) — it
carries no ontology triples. The shapes
in ontology/shapes/seam-shapes.ttl rely on subclass closure from the ontology
files (sh:class checks), so validation here mirrors tests/validate_chat_app.py:
merge the ontology .ttl files with the dataset's quads into one union graph,
then run pyshacl against seam-shapes.ttl with inference off. A result of
severity sh:Warning (the shape of a deprecated vocabulary term, ADR-0021
section 6) is a warning, not a violation: it never changes ``conforms``.

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
``conforms``, not even when the check itself fails. The static decision checks
of backlog K2 and X13 (seams.decision_findings()) are warnings the same way:
DMN typeRefs against sh:datatype, gateway conditions reading unset variables,
and overlapping rules and uncovered inputs of UNIQUE decision tables. They read
the BPMN and DMN payloads, whose seam:renderPayload IRIs parsing the TriG has
already made file: IRIs; a decision whose payload is missing is skipped.

Both build a seams.ModelGraph over the Dataset with the ontology import check
off: an owl:imports that does not resolve is the health panel's own fact
(ADR-0022, viewer/ontologygraph.py), not a failure of these checks.

The lifted-IRI check of ADR-0002 rule 4 (get_lifted_iri_health()) is read-only
and separate from ``conforms``: for each BPMN or DMN model with a
seam:renderPayload, every IRI of the dataset starting with ``modelIRI#`` must
name an ``id`` in the payload XML, so an edit that drops or renames an id
without its quads shows up here.

A model attached to a domain profile (ADR-0018, viewer/profiles.py) is
validated against the seam shapes merged with the profile's shapes, with the
profile graph in the data so seamsh:ProfileShape checks it too. Each typed
element whose class is neither offered by the profile nor a subclass of an
offered class is one Warning naming the element, rdf:type and the class: flagged,
never refused, so it does not change ``conforms``.

The same pyshacl run derives the profile's type pills (ADR-0033 section 4,
get_profile_pills()): each focus node of a pill shape's standard targets that the
run reports no result of the shape for gets the shape's label. The pills' names
come from the profile's shapes file; this module holds none.

Results are cached per Dataset and profile identity: the model is loaded once per
process, so each dataset is validated at most once per profile.

The data-health view (ADR-0036, get_data_health()) is the one check here that
reads instance data: the attached profile's sh:Warning sh:sparql rules run, through
seams_runtime's public ``data_health``, on the entities of a SQLite store opened
read-only. The store changes under the viewer, so this result is never cached.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import rdflib
import seams
from lxml import etree
from rdflib import RDF, RDFS, Namespace, URIRef

from seams_runtime import ContractViolation, SQLiteStore, StoreError, data_health
from viewer.profiles import Profile

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"

SH = Namespace("http://www.w3.org/ns/shacl#")
SEAM = Namespace("https://w3id.org/seams/seam#")

# Notations whose model elements are lifted from a payload's XML ids (ADR-0002).
LIFTED_NOTATIONS = (SEAM.BPMN, SEAM.DMN)

# Conformance (keyed by id(ds) and id(profile)) and lifted-IRI (keyed by id(ds))
# caches; the viewer holds one Dataset per process. Python recycles id() values,
# so both are cleared together (MEM010).
_cache: dict[tuple[int, int | None], dict] = {}
_pill_cache: dict[tuple[int, int | None], dict[str, list[dict]]] = {}
_lifted_cache: dict[int, list[dict]] = {}


def _clear_cache() -> None:
    _cache.clear()
    _pill_cache.clear()
    _lifted_cache.clear()


def _short_name(term) -> str:
    """Local name of a URIRef (e.g. sh:Violation -> 'Violation')."""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


def _build_union(ds: rdflib.Dataset, profile: Profile | None = None) -> rdflib.Graph:
    union = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        union.parse(p, format="turtle")
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        union.add((s, p, o))
    if profile is not None:
        union += profile.graph
    return union


def _shapes(profile: Profile | None) -> rdflib.Graph:
    shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    if profile is not None:
        shapes += profile.shapes
    return shapes


def _out_of_profile(ds: rdflib.Dataset, union: rdflib.Graph, profile: Profile) -> list[dict]:
    """One Warning per typed model element whose class the profile does not offer,
    directly or through rdfs:subClassOf over the ontology, the model and the profile
    (``union``), sorted by element then class."""
    offered = set(profile.classes)
    if not offered:
        # A profile that offers no classes restricts nothing (ADR-0033 section 3).
        return []
    found = sorted(
        {
            (s, cls)
            for s, _p, cls, _ctx in ds.quads((None, RDF.type, None, None))
            if isinstance(s, URIRef) and isinstance(cls, URIRef)
            if offered.isdisjoint(union.transitive_objects(cls, RDFS.subClassOf))
        }
    )
    return [
        {
            "focusNode": str(s),
            "path": str(RDF.type),
            "message": f"{cls} is not a class the profile {profile.iri} offers",
            "severity": "Warning",
            "sourceShape": None,
        }
        for s, cls in found
    ]


def _targets(shapes: rdflib.Graph, shape: URIRef, data: rdflib.Graph) -> set[URIRef]:
    """The IRI focus nodes of ``shape``'s standard targets over ``data`` (sh:targetNode,
    sh:targetClass with rdfs:subClassOf, sh:targetSubjectsOf, sh:targetObjectsOf)."""
    nodes: set = set(shapes.objects(shape, SH.targetNode))
    for cls in shapes.objects(shape, SH.targetClass):
        for sub in data.transitive_subjects(RDFS.subClassOf, cls):
            nodes.update(data.subjects(RDF.type, sub))
    for predicate in shapes.objects(shape, SH.targetSubjectsOf):
        nodes.update(data.subjects(predicate, None))
    for predicate in shapes.objects(shape, SH.targetObjectsOf):
        nodes.update(data.objects(None, predicate))
    return {n for n in nodes if isinstance(n, URIRef)}


def _pills(data: rdflib.Graph, results: rdflib.Graph, profile: Profile) -> dict[str, list[dict]]:
    """Focus IRI -> its pills, each {"label", "shape"}, sorted by label then shape IRI
    and one per label (ADR-0033 section 4). A focus node conforms to a pill shape when
    ``results`` has no result whose source is the shape or one of its sh:property shapes."""
    failed: dict[URIRef, set] = {}
    for shape in profile.pills:
        sources = {shape, *profile.shapes.objects(shape, SH.property)}
        failed[shape] = {
            results.value(r, SH.focusNode)
            for r in results.subjects(RDF.type, SH.ValidationResult)
            if results.value(r, SH.sourceShape) in sources
        }
    found: dict[str, dict[str, str]] = {}
    for shape, label in sorted(profile.pills.items(), key=lambda item: (item[1], str(item[0]))):
        for node in _targets(profile.shapes, shape, data) - failed[shape]:
            found.setdefault(str(node), {}).setdefault(label, str(shape))
    return {node: [{"label": label, "shape": shape} for label, shape in pills.items()] for node, pills in found.items()}


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
        model = seams.ModelGraph(ROOT / "viewer.trig", dataset=ds, check_imports=False)
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
        findings = seams.review_findings(seams.ModelGraph(ROOT / "viewer.trig", dataset=ds, check_imports=False))
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


def _decision_findings(ds: rdflib.Dataset) -> list[dict]:
    """seams.decision_findings() over the same Dataset, one Warning each with
    the subject as focusNode and the fact as path. A failure of the check itself is one Warning too, so
    decision findings never change ``conforms``."""
    try:
        findings = seams.decision_findings(seams.ModelGraph(ROOT / "viewer.trig", dataset=ds, check_imports=False))
    except Exception as err:
        return [
            {
                "focusNode": None,
                "path": None,
                "message": f"decision check failed: {err}",
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


def get_model_conformance(ds: rdflib.Dataset, profile: Profile | None = None) -> dict:
    """Validate the dataset (plus ontology closure) against seam-shapes.ttl,
    then run the storage health, decision and model review checks. With a
    ``profile``, its shapes join the seam shapes and out-of-profile classes are
    warnings.

    Returns {"conforms": bool, "violationCount": int, "violations": list[dict],
    "warnings": list[dict], "notes": list[dict]}. Each entry carries focusNode,
    path, message, severity, and sourceShape (focusNode, path and sourceShape
    may be None). Store violations join ``violations`` and make the model not
    conform; warnings (SHACL sh:Warning results, then store, replica, decision,
    review and out-of-profile findings, in that order) and notes do not change ``conforms``.
    """
    key = (id(ds), None if profile is None else id(profile))
    if key in _cache:
        return _cache[key]

    union = _build_union(ds, profile)
    _conforms, results_graph, _text = pyshacl.validate(union, shacl_graph=_shapes(profile), inference="none")
    if not isinstance(results_graph, rdflib.Graph):
        raise TypeError(f"pyshacl returned a {type(results_graph).__name__} report, not a results graph")

    violations: list[dict] = []
    shape_warnings: list[dict] = []
    # A pill shape's results are its non-conforming targets, not findings (ADR-0033 section 4).
    pills = frozenset() if profile is None else profile.pill_sources()
    for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
        source_shape = results_graph.value(result, SH.sourceShape)
        if source_shape in pills:
            continue
        focus = results_graph.value(result, SH.focusNode)
        path = results_graph.value(result, SH.resultPath)
        message = results_graph.value(result, SH.resultMessage)
        severity = results_graph.value(result, SH.resultSeverity)
        (shape_warnings if severity == SH.Warning else violations).append(
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
    warnings = (
        shape_warnings
        + [f for f in store if f["severity"] == "Warning"]
        + _decision_findings(ds)
        + _review_findings(ds)
    )
    if profile is not None:
        warnings += _out_of_profile(ds, union, profile)
    _pill_cache[key] = {} if profile is None else _pills(union, results_graph, profile)
    notes = [f for f in store if f["severity"] == "Info"]

    summary = {
        "conforms": not violations,
        "violationCount": len(violations),
        "violations": violations,
        "warnings": warnings,
        "notes": notes,
    }
    _cache[key] = summary
    return summary


def get_profile_pills(ds: rdflib.Dataset, profile: Profile | None) -> dict[str, list[dict]]:
    """Focus IRI -> the profile's type pills on it (ADR-0033 section 4), from the run
    get_model_conformance() caches; empty with no profile or no pill shapes."""
    if profile is None or not profile.pills:
        return {}
    get_model_conformance(ds, profile)
    return _pill_cache[(id(ds), id(profile))]


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


def _data_health_state(state: str, store: Path | None, profile: Profile | None, error: str | None = None) -> dict:
    return {
        "state": state,
        "store": None if store is None else str(store),
        "profile": None if profile is None else str(profile.iri),
        "error": error,
        "findings": [],
        "count": 0,
    }


def get_data_health(
    model_path: Path,
    ds: rdflib.Dataset,
    profile: Profile | None,
    profile_error: dict | None,
    store_path: Path | None,
) -> dict:
    """The data-health view's facts (ADR-0036): the attached profile's
    instance-data rules run on the SQLite store at ``store_path``, opened
    read-only, so nothing is created or written.

    Returns {"state", "store", "profile", "error", "findings", "count"}.
    ``state`` is "no-store" without ``store_path``, "no-profile" when the model
    attaches none, "error" when the profile did not resolve, the store cannot be
    opened or a stored entity fails its shape contract (``error`` says which),
    else "ok". Each finding is {"shape", "focus", "message", "severity"}, in
    seams_runtime's sorted order.
    """
    if store_path is None:
        return _data_health_state("no-store", None, profile)
    if profile_error is not None:
        detail = f"{profile_error['subject']} {profile_error['predicate']}: {profile_error['detail']}"
        return _data_health_state("error", store_path, None, f"profile not resolved: {detail}")
    if profile is None:
        return _data_health_state("no-profile", store_path, None)
    try:
        store = SQLiteStore(store_path, read_only=True)
        model = seams.ModelGraph(model_path, dataset=ds, check_imports=False)
        findings = data_health(model, store, profile.shapes)
    except (StoreError, ContractViolation) as err:
        return _data_health_state("error", store_path, profile, str(err))
    rows = [{"shape": f.shape, "focus": f.focus, "message": f.message, "severity": f.severity} for f in findings]
    return {**_data_health_state("ok", store_path, profile), "findings": rows, "count": len(rows)}
