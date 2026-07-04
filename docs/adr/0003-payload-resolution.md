# ADR-0003: Payload Resolution

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CC §5, CX (review-triage.md)

## Context

Seams models reference native-notation files (BPMN XML, DMN XML, etc.) via payload IRIs. The viewer must resolve these IRIs to actual file content for rendering. Without an explicit resolution mechanism:

- The viewer would need ad-hoc logic to locate files on disk.
- Payload references could silently point to missing or stale files.
- There is no single source of truth for what file backs a given payload IRI.

The manifest graph (ADR-0001) already declares payload entries with path, checksum, and media type. This ADR defines how the FastAPI viewer uses that graph to resolve and serve payloads.

## Decision

### Resolution Mechanism

1. **Payload IRIs resolve via the manifest graph, never against load context.** The viewer's payload endpoint queries the `<urn:seams:graph:manifest>` named graph to map a payload IRI to its file path, media type, and checksum. It never attempts filesystem discovery or path inference.

2. **The manifest graph is the single source of truth.** Each payload entry declares:
   - `seam:filePath` — relative path from the model root to the native file
   - `seam:mediaType` — IANA media type (e.g., `application/bpmn+xml`, `application/dmn+xml`)
   - `seam:checksum` — integrity hash for drift detection

3. **The `renderPayload` property links model elements to their payload.** A model element that has a renderable native representation declares `seam:renderPayload <payloadIRI>`. The viewer uses this to locate the content to hand to the appropriate renderer (bpmn-js, dmn-js, etc.).

4. **The FastAPI payload endpoint** (`/payload/{iri}`) performs:
   1. Query manifest graph for the payload IRI → file path + media type
   2. Verify file exists at the resolved path
   3. Optionally verify checksum matches (fail-open with warning in dev, fail-closed in CI)
   4. Return file content with the declared media type

### Resolution Failures

5. **Missing manifest entry:** 404 with a structured error naming the unresolved IRI.
6. **File not found at declared path:** 404 with a diagnostic indicating manifest-vs-filesystem inconsistency (the drift lint, ADR-0006, prevents this in CI).
7. **Checksum mismatch:** Warning header in dev mode; hard failure in strict/CI mode.

### Scope Boundary

Payload resolution is read-only in v1. The viewer serves payloads for rendering; it does not accept uploads or mutations. Editing workflows are post-v1.

## Consequences

- **Positive:** Resolution is deterministic and auditable — the manifest graph is queryable, versionable, and lintable.
- **Positive:** The viewer needs no filesystem-scanning logic; all discovery goes through SPARQL against a single named graph.
- **Positive:** Checksum verification enables integrity checks without parsing the payload format.
- **Negative:** Every payload file must have a corresponding manifest entry. Forgetting to add one means the viewer cannot resolve it. The drift lint (ADR-0006) catches this.
- **Negative:** The manifest graph must be kept in sync with the filesystem. This is a maintenance burden offset by automated linting.
