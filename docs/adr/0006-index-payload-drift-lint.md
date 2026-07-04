# ADR-0006: Index-Payload Drift Lint

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CC §5 (review-triage.md)

## Context

The Seams model maintains a dual representation: RDF index graphs describe elements and their relationships, while native payload files (BPMN XML, DMN XML, etc.) carry the renderable notation content. Two invariants bind these representations together:

1. **Fragment IRI ↔ element ID correspondence** (ADR-0002, rule 4): every `modelIRI#nativeElementId` fragment in the RDF index must have a matching `id` attribute in the corresponding payload file, and vice versa for seam-worthy elements.
2. **Manifest ↔ filesystem correspondence** (ADR-0003): every payload IRI in the manifest graph must resolve to a file that actually exists at the declared `seam:filePath`.

Without automated enforcement these invariants drift silently:

- A BPMN element is renamed in the XML but the TriG fragment IRI is not updated → seam edges dangle, queries return zero rows.
- A payload file is moved or deleted but the manifest entry is not updated → the viewer 404s at runtime.
- A new XML element is added that should participate in seams but no IRI is minted → the element is invisible to the seam graph.

The review triage flagged this as a required lint: "Parse payload, assert every fragment IRI exists as an element ID; warn on seam-worthy XML elements with no IRI. Ship before any editing story."

## Decision

### Lint Rule: `index-payload-drift`

Implement a CI lint that validates consistency between RDF index graphs and native payload files. The lint runs in two phases.

#### Phase 1 — Manifest Integrity

For every entry in the `<urn:seams:graph:manifest>` named graph:

1. **File exists:** The file at `seam:filePath` must exist on disk relative to the model root.
2. **Media type is declared:** `seam:mediaType` must be present and non-empty.
3. **Checksum matches (strict mode):** When `seam:checksum` is declared, recompute the hash and assert equality. In dev mode this is a warning; in CI it is a hard failure.

#### Phase 2 — Fragment IRI ↔ Element ID Consistency

For every model graph that references a payload via `seam:renderPayload`:

4. **Forward check (RDF → payload):** Every fragment IRI in the model graph whose base matches the payload's parent model IRI must have a corresponding element ID in the parsed payload file. A fragment with no matching element ID is an error: the IRI is dangling.

5. **Reverse check (payload → RDF):** Every "seam-worthy" element ID in the payload file should have a corresponding fragment IRI in the model graph. An element ID with no matching fragment is a warning (not all native elements need RDF representation, but significant ones should have it).

   Seam-worthy elements are notation-specific:
   - **BPMN:** `bpmn:task`, `bpmn:serviceTask`, `bpmn:userTask`, `bpmn:process`, `bpmn:collaboration`, `bpmn:participant`, `bpmn:messageFlow`, `bpmn:startEvent`, `bpmn:endEvent`, `bpmn:gateway` (and subtypes)
   - **DMN:** `dmn:decision`, `dmn:inputData`, `dmn:knowledgeSource`, `dmn:decisionService`
   - **IFML:** view containers, view components, actions (element names per the IFML XSD)

   The seam-worthy element list is configurable per media type so new notations can be added without modifying the lint core.

#### Severity Levels

| Check | Dev | CI |
|-------|-----|-----|
| Missing file at `seam:filePath` | Error | Error |
| Missing `seam:mediaType` | Warning | Error |
| Checksum mismatch | Warning | Error |
| Dangling fragment IRI (RDF → payload) | Error | Error |
| Missing fragment IRI for seam-worthy element (payload → RDF) | Warning | Warning |

#### Integration

6. **CI gate:** The lint runs as a pytest check alongside SHACL validation. It must pass before merge.
7. **Pre-commit (optional):** A lightweight version can run as a pre-commit hook, checking only changed files.
8. **Output format:** Errors are reported as structured diagnostics: `{file, iri_or_element_id, check, severity, message}`. The CI runner renders these as GitHub annotations when available.

### Scope Boundary

The lint validates structural consistency only. It does not:
- Parse payload semantics (e.g., whether a BPMN process is well-formed)
- Validate seam edge targets (that is SHACL's job)
- Enforce naming conventions beyond the `modelIRI#nativeElementId` pattern (ADR-0002)

## Consequences

- **Positive:** Drift between RDF index and native payloads is caught at commit time, not at runtime when the viewer 404s or queries return empty.
- **Positive:** The reverse check (payload → RDF) surfaces elements that should participate in seams but were missed during authoring — a guardrail against incomplete models.
- **Positive:** Configurable seam-worthy element lists mean the lint extends to new notations without core changes.
- **Negative:** The lint must parse multiple payload formats (BPMN XML, DMN XML, IFML). Each parser is thin (extract element IDs only), but each new notation requires a parser entry.
- **Negative:** False-positive warnings on the reverse check are possible when payload elements intentionally have no RDF representation. Authors suppress these with an explicit exclusion annotation or by adding the element to a `.driftignore` list scoped to the model.
- **Trade-off:** Running the lint in CI adds build time proportional to the number of payload files. For the tutorial-scale models this is negligible; for large models, the pre-commit hook (changed files only) mitigates the cost.
