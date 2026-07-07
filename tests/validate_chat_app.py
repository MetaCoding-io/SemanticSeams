"""Validate chat-app.trig against SHACL shapes and named-graph isolation constraints.

Mirrors the acceptance checks in test_acceptance.py but targeted at the chat-app
model. Run standalone (python3 tests/validate_chat_app.py) or via pytest.
"""

from pathlib import Path
import sys

import pyshacl
import rdflib
from rdflib import Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
CHAT_APP_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"

SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
ALLOWED_IN_MODEL_GRAPHS = {SEAM.inModel}

EXPECTED_GRAPHS = {
    URIRef("urn:seams:graph:model:chat_architecture"),
    URIRef("urn:seams:graph:model:chat_ifml"),
    URIRef("urn:seams:graph:model:chat_bpmn"),
    URIRef("urn:seams:graph:model:chat_data_shapes"),
    URIRef("urn:seams:graph:model:message_lifecycle"),
    URIRef("urn:seams:graph:seams"),
}


def load_chat_app_dataset() -> rdflib.Dataset:
    ds = rdflib.Dataset()
    for p in ONTOLOGY_FILES:
        ds.default_graph.parse(p, format="turtle")
    ds.parse(CHAT_APP_TRIG, format="trig")
    return ds


def union_graph(ds: rdflib.Dataset) -> rdflib.Graph:
    g = rdflib.Graph()
    for s, p, o, _ctx in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    return g


def check_parse_and_graph_count() -> tuple[rdflib.Dataset, list[str]]:
    errors = []
    ds = load_chat_app_dataset()
    graph_ids = {
        g.identifier
        for g in ds.graphs()
        if str(g.identifier) != "urn:x-rdflib:default"
    }
    if graph_ids != EXPECTED_GRAPHS:
        missing = EXPECTED_GRAPHS - graph_ids
        extra = graph_ids - EXPECTED_GRAPHS
        msg = f"Graph mismatch. Expected 6, got {len(graph_ids)}."
        if missing:
            msg += f" Missing: {sorted(str(g) for g in missing)}."
        if extra:
            msg += f" Extra: {sorted(str(g) for g in extra)}."
        errors.append(msg)
    return ds, errors


def check_shacl(model: rdflib.Graph) -> list[str]:
    conforms, _, report = pyshacl.validate(
        model, shacl_graph=str(SHAPES_FILE), inference="none"
    )
    if not conforms:
        return [f"SHACL validation failed:\n{report}"]
    return []


def check_isolation(ds: rdflib.Dataset) -> list[str]:
    leaked = []
    for s, p, o, ctx in ds.quads((None, None, None, None)):
        graph_id = ctx.identifier if hasattr(ctx, "identifier") else ctx
        if str(p).startswith(str(SEAM)) and p not in ALLOWED_IN_MODEL_GRAPHS:
            if graph_id != SEAMS_GRAPH:
                leaked.append((graph_id, s, p, o))
    if leaked:
        lines = "\n".join(f"  {g}: {s} {p} {o}" for g, s, p, o in leaked)
        return [f"Seam predicates leaked into model graphs:\n{lines}"]
    return []


def main() -> int:
    errors: list[str] = []

    print("1. Parsing chat-app.trig and checking graph count...", flush=True)
    ds, parse_errors = check_parse_and_graph_count()
    errors.extend(parse_errors)
    if not parse_errors:
        print("   PASS: 6 named graphs found")

    model = union_graph(ds)

    print("2. SHACL validation against seam-shapes.ttl...", flush=True)
    shacl_errors = check_shacl(model)
    errors.extend(shacl_errors)
    if not shacl_errors:
        print("   PASS: model conforms to shapes")

    print("3. Named-graph isolation check (ADR-0001)...", flush=True)
    iso_errors = check_isolation(ds)
    errors.extend(iso_errors)
    if not iso_errors:
        print("   PASS: seam predicates isolated to seams graph")

    if errors:
        print(f"\nFAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\nAll chat-app validations passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
