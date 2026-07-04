# ADR-0004: View Response Contract

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CX arch §4 (review-triage.md)

## Context

The `/view/{iri}` endpoint is the primary API surface for the Seams viewer shell. It returns everything the frontend needs to render a focused element: its label, type, related seam edges, navigation aids, and native-notation metadata. Without a defined response contract:

- Frontend and backend evolve independently with silent breakage.
- There is no specification for what a renderer can rely on.
- Navigation, breadcrumbs, and seam-edge display are ad-hoc per element type.

## Decision

### Response Format

The `/view/{iri}` endpoint returns a JSON-LD response with the following structure:

```json
{
  "@context": "https://w3id.org/seams/context.jsonld",
  "@id": "<resolved IRI>",
  "label": "Human-readable element label",
  "types": ["seam:BPMNModel", "seam:Model"],
  "focusedModel": "<model IRI this element belongs to>",
  "notation": "bpmn",
  "nativeElementId": "SendMessageTask",
  "renderPayload": "<payload IRI if renderable>",
  "seamEdges": {
    "outgoing": [
      {
        "predicate": "seam:triggers",
        "target": "<target IRI>",
        "targetLabel": "Target Label",
        "navigational": true
      }
    ],
    "incoming": [
      {
        "predicate": "seam:decidedBy",
        "source": "<source IRI>",
        "sourceLabel": "Source Label",
        "navigational": true
      }
    ]
  },
  "breadcrumbs": [
    {"iri": "<ancestor IRI>", "label": "Ancestor Label"}
  ],
  "warnings": [
    {"code": "missing-payload", "message": "No renderPayload declared"}
  ]
}
```

### Field Semantics

1. **`label`** — The `rdfs:label` or `skos:prefLabel` of the element. The viewer always shows friendly labels (RDF invisibility principle).

2. **`types`** — All `rdf:type` values, most-specific first. Used by the shell to select the appropriate renderer component.

3. **`focusedModel`** — The `seam:Model` whose named graph contains this element. Scopes the renderer query context.

4. **`notation`** — Short string identifying the native notation family (`bpmn`, `dmn`, `ifml`, `c4`, `none`). Drives renderer selection.

5. **`nativeElementId`** — The fragment portion of the element's IRI (the native `id` attribute from the source file, per ADR-0002). Enables renderer highlight/focus.

6. **`renderPayload`** — Payload IRI for the element's renderable content (resolved via ADR-0003). Absent if the element has no native visual representation.

7. **`seamEdges`** — All seam predicates connecting this element to other elements, split into outgoing and incoming. Each edge includes whether it is `navigational` (ADR-0005) to guide click behavior.

8. **`breadcrumbs`** — Traversal path from the entry point to the current element. Represents the user's navigation history, not a strict hierarchy (multiple parents are possible in a graph).

9. **`warnings`** — Model-health diagnostics relevant to this element (e.g., missing payload, orphaned seam edge, failed shape validation). Supports the "trust is the product" principle.

### Stability Contract

- Fields present in this ADR are stable for v1. Removal is a breaking change requiring a new ADR.
- New fields may be added without a breaking change (additive evolution).
- The `@context` JSON-LD context document maps short names to full IRIs; it is versioned alongside the ontology.

## Consequences

- **Positive:** Frontend renderers have a predictable, typed contract. No guessing about response shape.
- **Positive:** JSON-LD gives the response semantic meaning while remaining valid JSON for non-RDF consumers.
- **Positive:** Including `navigational` on edges means the shell can implement click behavior without additional queries.
- **Negative:** The response assembles data from multiple sources (model graph, seams graph, manifest graph, shapes graph for warnings). The endpoint must perform multiple SPARQL queries or use a pre-assembled view.
- **Negative:** Breadcrumbs require session state (traversal history). The backend must either accept breadcrumb context from the client or maintain server-side session state.
- **Trade-off:** JSON-LD adds conceptual weight for frontend developers unfamiliar with it. The `@context` file absorbs the complexity; in practice, consumers treat it as typed JSON.
