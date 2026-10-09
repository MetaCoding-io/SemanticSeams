# ADR-0001: Named-Graph Partitioning

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CC §3, CX arch §2 (review-triage.md)

## Context

The SemanticSeams model is a multi-layer RDF graph spanning architecture, UI, process, data, communication, deployment, and authorization concerns. Turtle (the initial serialization) cannot express named graphs, so there was no defined partitioning strategy — all triples lived in a single default graph.

Named graphs are essential for:

- **Provenance and scoping:** knowing which triples belong to which model, and which are bridging (seam) triples vs. layer-internal.
- **Renderer dispatch:** the viewer mounts a renderer scoped to a single model's named graph; without partitioning, the renderer sees the entire dataset.
- **Drift detection:** as-designed vs. as-deployed comparisons require separate named graphs for the same logical content at different lifecycle stages.
- **Payload resolution:** the manifest graph maps payload IRIs to their native files (BPMN XML, DMN XML, etc.); this must be a distinct, queryable graph.

## Decision

Adopt the following named-graph partitioning scheme. All examples are serialized as TriG (Turtle + named graphs).

### Graph Categories

| Graph | Purpose | Example IRI pattern |
|-------|---------|-------------------|
| **Ontology graphs** | One per vocabulary module (`seam:`, `arch:`, `ifml:`, `proc:`, `deploy:`, `state:`, `comm:`) | `<urn:seams:graph:ontology:seam>` |
| **Model graph** (one per model) | All triples describing elements within a single `seam:Model` — the unit of renderer scoping | `<urn:seams:graph:model:{modelId}>` |
| **Seams graph** (dedicated) | All cross-layer seam triples (`seam:triggers`, `seam:decidedBy`, `seam:detailedBy`, etc.) — kept separate so seams are independently auditable | `<urn:seams:graph:seams>` |
| **Payload manifest graph** | Maps payload IRIs to native files: path, checksum, media type | `<urn:seams:graph:manifest>` |
| **Shapes graph** | SHACL shapes for model validation | `<urn:seams:graph:shapes>` |
| **As-deployed graph** | Runtime/observed deployment state (fed by monitoring, not hand-authored) | `<urn:seams:graph:deployed>` |

### Principles

1. **Layers stay pure.** A model graph contains only layer-internal triples. Cross-layer relationships live exclusively in the seams graph.
2. **Seams stay auditable.** The dedicated seams graph means "show me all cross-layer connections" is a single-graph query, not a filter over the union.
3. **Ontology graphs are immutable per version.** They change only on vocabulary releases, not on model edits.
4. **Model graphs are the unit of authoring.** A TriG file may contain one or more model graphs plus the seams between them.

### Serialization

All example and tutorial models use TriG (`.trig` extension). The existing `checkout.ttl` smoke test remains as Turtle (single default graph) for ontology validation only.

## Consequences

- **Positive:** Renderer scoping becomes trivial (query one named graph). Drift detection is a SPARQL diff between two graphs. Seam auditing is cheap.
- **Positive:** TriG is a superset of Turtle; existing Turtle knowledge transfers directly.
- **Negative:** Tooling must handle TriG; some RDF tools have weaker TriG support than Turtle. Fuseki handles TriG natively, so the chosen stack is unaffected.
- **Negative:** Authors must decide which graph a triple belongs to. The rule is simple (seam predicates → seams graph; everything else → the element's model graph), but it is a new concern.
- **Migration:** Existing Turtle examples convert to TriG by wrapping in a named graph block. No data loss.
