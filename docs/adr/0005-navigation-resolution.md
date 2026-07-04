# ADR-0005: Navigation Resolution

**Status:** Accepted

**Date:** 2026-07-04

**Source:** CC §4, CX arch §5 (review-triage.md)

## Context

The Seams viewer shell must decide what happens when a user clicks on a seam edge or a related element. Navigation in a graph is not "follow one edge" — it may require multi-hop resolution (e.g., an event triggers a process, which is detailed by a model, which is the actual render target). Without a principled rule:

- The shell becomes a growing switch statement over predicate types.
- Click behavior is unpredictable to users.
- Adding new seam predicates requires shell code changes.

The goal is an annotation-based approach where the ontology itself declares which predicates are navigational, and the shell resolves clicks via a small, fixed algorithm rather than per-predicate logic.

## Decision

### Navigational Annotation

1. **Seam predicates are annotated in the ontology.** Each seam predicate that should trigger navigation on click is marked with `seam:navigational true` in its property definition. This is a boolean annotation on the predicate itself, not on individual edges.

2. **The navigational set for v1:**
   - `seam:detailedBy` — always navigational (descent into detail)
   - `seam:triggers` — navigational (follow the triggered process)
   - `seam:presents` — navigational (view the presented UI)
   - `seam:decidedBy` — navigational (view the decision logic)
   - `seam:subscribesTo` — not navigational (informational, inspector-only)
   - `seam:visibleWhen` — not navigational (conditional, inspector-only)
   - `seam:governedBy` — not navigational (policy reference, inspector-only)

### Resolution Algorithm

When the user clicks an element linked by a navigational seam edge, the shell resolves the target as follows:

3. **Direct detail:** If the target has `seam:detailedBy` pointing to a renderable model, navigate to that model (descent). This is the primary navigation pattern — clicking a high-level element descends into its detail.

4. **Navigational edge + detail hop:** If the target does not itself have a `detailedBy` but is linked by a navigational predicate to an element that does, resolve one additional hop: `clicked → navigational-edge → target → detailedBy → render-target`. Maximum one extra hop.

5. **No detail available:** If neither direct detail nor a one-hop resolution yields a renderable target, open the inspector panel for the clicked element. The inspector shows all properties, seam edges, and metadata without attempting to render native notation.

### Interaction Table

| User Action | Condition | Result |
|---|---|---|
| Click element with `detailedBy` | Target has renderPayload | Navigate to detail model; render payload |
| Click element with navigational edge | Target resolves (≤1 hop) to a renderable model | Navigate to resolved target |
| Click element with no detail | — | Open inspector panel |
| Click non-navigational seam edge | — | Open inspector panel for linked element |
| Breadcrumb click | — | Navigate back to that ancestor |
| Query result highlight | Element in current model | Highlight in current renderer |
| Query result highlight | Element in different model | Navigate to that model, then highlight |

### Disambiguation

6. **Multiple `detailedBy` targets:** When an element has more than one `detailedBy` link (e.g., a container detailed by both a process model and a data model), the shell presents a disambiguation popover listing all targets with their labels and notations.

7. **Deep-linkable URLs:** Every navigation state is represented as `/view/{iri}`, making all states bookmarkable and shareable. The breadcrumb trail is reconstructed from the URL path or query parameter, not from hidden session state.

### Extensibility

8. **Adding new navigational predicates requires only an ontology annotation change** (`seam:navigational true` on the new predicate). No shell code changes are needed because the resolution algorithm is generic over the navigational set.

## Consequences

- **Positive:** The shell's navigation logic is a fixed algorithm (~10 lines), not a predicate-keyed switch statement. New seam types don't require viewer code changes.
- **Positive:** Click behavior is predictable: navigational edges descend, non-navigational edges inspect. Users build correct mental models quickly.
- **Positive:** The one-hop limit keeps navigation understandable — you never "teleport" across multiple layers without seeing intermediate steps.
- **Negative:** The `seam:navigational` annotation must be maintained as new predicates are added. Forgetting it means the predicate defaults to inspector-only (safe default, but potentially confusing if the user expects navigation).
- **Negative:** The one-hop resolution limit means some valid navigation paths require two clicks. This is intentional — multi-hop implicit navigation is disorienting.
- **Trade-off:** Disambiguation popovers add UI complexity for multi-detail elements. The alternative (picking the "first" target silently) is worse — it hides information and makes the graph feel non-deterministic.
