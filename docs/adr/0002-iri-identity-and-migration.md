# ADR-0002: IRI Identity and Migration

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CX arch §1 (review-triage.md)

## Context

Every element in the Seams model — a C4 container, a BPMN task, a SHACL shape, an IFML view component — is an RDF resource identified by an IRI. The project had no explicit rules for how IRIs are minted, how they relate to native element IDs (e.g., BPMN XML `id` attributes), or what happens when an element is renamed.

Without identity rules:

- Fragment IRIs may collide across models.
- Renaming a BPMN element silently breaks all seam edges pointing at it.
- Blank nodes used for durable model elements make cross-graph queries unreliable (blank node identity is graph-scoped in RDF).
- There is no migration path when IDs change.

## Decision

### IRI Minting Rules

1. **Model IRIs are stable.** Each `seam:Model` has a stable base IRI that does not change when the model is edited. Pattern: `<https://w3id.org/seams/models/{projectId}/{modelId}>`.

2. **Element IRIs use `modelIRI#nativeElementId`.** For elements lifted from native notations (BPMN XML, DMN XML, IFML), the fragment identifier is the native element's `id` attribute. Examples:
   - BPMN task: `<https://w3id.org/seams/models/chat-app/send-message-bpmn#SendMessageTask>`
   - DMN decision: `<https://w3id.org/seams/models/chat-app/routing-dmn#RoutingDecision>`
   - Architecture element (no native format): `<https://w3id.org/seams/models/chat-app/architecture#api_server>`

3. **No blank nodes for durable model elements.** Every element that participates in a seam edge or is the target of a query must have an explicit IRI. Blank nodes are permitted only for structural RDF constructs (e.g., `rdf:List` members, SHACL property paths) that are never referenced externally.

4. **Fragment IRIs must match native element IDs exactly.** The `#fragment` in the IRI must be identical to the `id` attribute in the source notation file. This invariant enables the index-payload drift lint (ADR-0006).

### Migration Rules

5. **Renaming a native element ID is a breaking change** unless an alias is recorded. When an element's native ID changes:
   - The old IRI becomes a `owl:sameAs` alias pointing to the new IRI, OR
   - All references are updated atomically in the same commit.
   
   The choice depends on whether external consumers reference the old IRI. For internal-only models, atomic update is preferred (simpler). For published models, `owl:sameAs` preserves backwards compatibility.

6. **Model IRI changes are always breaking.** Changing a model's base IRI invalidates every element IRI derived from it. This should be extremely rare (project rename).

### Validation

The SHACL shapes (see shapes graph, ADR-0001) enforce:
- Every `seam:Model` instance has exactly one stable IRI.
- Every element with a seam edge has an explicit IRI (not a blank node).
- Fragment IRIs conform to the `modelIRI#nativeElementId` pattern where a native source exists.

## Consequences

- **Positive:** Cross-graph queries are reliable — element IRIs are globally unique and stable.
- **Positive:** The `modelIRI#nativeElementId` convention makes the mapping between RDF and native formats mechanical and verifiable.
- **Positive:** The blank node prohibition for durable elements eliminates a class of subtle query bugs (blank node identity is graph-local).
- **Negative:** Authors must maintain ID consistency between native files and TriG. The drift lint (ADR-0006) automates this check.
- **Negative:** The migration rules add process overhead for renames. This is intentional — renaming should be deliberate because it affects the entire seam graph.
- **Trade-off:** `owl:sameAs` aliases accumulate over time in published models. Periodic cleanup (removing aliases after all consumers migrate) is a manual process.
