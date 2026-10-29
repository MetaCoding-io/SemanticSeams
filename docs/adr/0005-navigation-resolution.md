# ADR-0005: Navigation Resolution

**Status:** Accepted, amended 2026-10-29 (M007/S02)

**Date:** 2026-07-04

**Source:** CC §4, CX arch §5 (review-triage.md)

## Context

The SemanticSeams viewer shell must decide what happens when a user clicks on a seam edge or a related element. Navigation in a graph is not "follow one edge" — it may require multi-hop resolution (e.g., an event triggers a process, which is detailed by a model, which is the actual render target). Without a principled rule:

- The shell becomes a growing switch statement over predicate types.
- Click behavior is unpredictable to users.
- Adding new seam predicates requires shell code changes.

The goal is an annotation-based approach where the ontology itself declares which predicates are navigational, and the shell resolves clicks via a small, fixed algorithm rather than per-predicate logic.

## Decision

### Reveal-mode annotation

_Amended 2026-10-29 (M007/S02, decision D020). The original boolean `seam:navigational true` annotation was never added to the ontology; the viewer hard-coded the set instead. It is replaced by a three-valued reveal mode declared in `ontology/seam.ttl`, following the reveal-modes research (`docs/research/2026-10-15-reveal-modes.md` §2)._

1. **Every seam predicate declares a reveal mode in the ontology.** `seam:reveal` is an `owl:AnnotationProperty` on the predicate itself, never on individual edges. Its value is one `seam:RevealMode`:
   - `seam:Open`: the view is replaced by the target's model in its own notation, and a breadcrumb records the hop.
   - `seam:Nest`: the target's model is drawn inside the source's card. The C4 renderer shows this at level L4.
   - `seam:Layer`: the seam is drawn as a line between stacked layer planes. Until layer mode ships (M008/S03) a layer predicate is inspector-only.

   The administrative predicates `seam:inModel`, `seam:notation` and `seam:renderPayload` drive rendering and dispatch, not navigation, so they declare none. `seamsh:RevealShape` in `ontology/shapes/seam-shapes.ttl` checks that every other seam predicate has exactly one mode, and that it is one of the three.

2. **The defaults:**

   | Mode | Predicates |
   |---|---|
   | nest | `seam:presents`, `seam:executes` |
   | open | `seam:detailedBy`, `seam:triggers`, `seam:decidedBy`, `seam:lifecycle` |
   | layer | every other seam predicate (`exposes`, `consumes`, `deployedTo`, `visibleWhen`, `submitsTo`, `rendersComponent`, `invokes`, `publishesTo`, `subscribesTo`, `reads`, `writes`, `fires`, `acceptsShape`, `returnsShape`, `mediaKind`, `governedBy`, `conformsTo`, `realizes`) |

   **Navigation follows open and nest predicates; layer predicates stay inspector-only** until layer mode exists. A nest predicate navigates like an open one in every view that does not draw nesting. Compared with the original v1 set (`detailedBy`, `triggers`, `presents`, `decidedBy`), `seam:executes` and `seam:lifecycle` are now navigational: clicking a container that executes a process opens the process's BPMN, and clicking a shape with a lifecycle opens its statechart.

   The viewer reads the modes from `ontology/*.ttl` through a side lookup, as it does labels. Ontology triples never enter the model store. A `seam:reveal` triple in the model graph overrides the ontology default for that predicate, and a predicate with no mode at all counts as layer. Per-user overrides carried in the URL are deferred.

### Resolution Algorithm

When the user clicks an element linked by a navigational seam edge, the shell resolves the target as follows:

3. **Direct detail:** If the target has `seam:detailedBy` pointing to a renderable model, navigate to that model (descent). This is the primary navigation pattern — clicking a high-level element descends into its detail.

4. **Navigational edge + detail hop:** If the target does not itself have a `detailedBy` but is linked by a navigational predicate to an element that does, resolve one additional hop: `clicked → navigational-edge → target → detailedBy → render-target`. Maximum one extra hop. The navigational predicates other than `detailedBy` are tried in IRI order, so the result is deterministic when an element carries more than one.

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

8. **Making a predicate navigational, or not, is only an ontology change.** Set its `seam:reveal` to `seam:Open` or `seam:Nest` to navigate, or to `seam:Layer` to keep it inspector-only. A new seam predicate declares its mode and joins the `seamsh:RevealShape` target list. No shell code changes are needed, because the resolution algorithm is generic over the navigational set the viewer derives from the modes.

## Consequences

- **Positive:** The shell's navigation logic is a fixed algorithm (~10 lines), not a predicate-keyed switch statement. New seam types don't require viewer code changes.
- **Positive:** Click behavior is predictable: navigational edges descend, non-navigational edges inspect. Users build correct mental models quickly.
- **Positive:** The one-hop limit keeps navigation understandable — you never "teleport" across multiple layers without seeing intermediate steps.
- **Negative:** The `seam:reveal` annotation must be maintained as new predicates are added. SHACL flags a missing mode once the predicate is in the `seamsh:RevealShape` target list; the viewer treats an unannotated predicate as layer, so it is inspector-only (a safe default, but confusing if the user expects navigation).
- **Negative:** The one-hop resolution limit means some valid navigation paths require two clicks. This is intentional — multi-hop implicit navigation is disorienting.
- **Trade-off:** Disambiguation popovers add UI complexity for multi-detail elements. The alternative (picking the "first" target silently) is worse — it hides information and makes the graph feel non-deterministic.
