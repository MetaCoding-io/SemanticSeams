# Backlog: viewer and generation

*Living document. Triaged 2026-10-19 from the three research notes of
2026-10-15 ([EventCatalog Levels](research/2026-10-15-eventcatalog-levels.md),
[reveal modes](research/2026-10-15-reveal-modes.md),
[IFML notation](research/2026-10-15-ifml-notation.md)) and the product brief's
milestones (M1 descent, M2 trust, M3 payoff). Twenty steps across the notes
collapse to twelve items once duplicates are merged.*

## How this was triaged

Three questions per item: does it move the tutorial persona closer to
`docker compose up` or to understanding the model on the way there; can it
ship on its own; and what does it force the vocabulary to decide. Priority
is P0 (do next), P1 (do after P0 lands), P2 (parked, with the reason).
Size is S (a day or two), M (a week), L (more, or needs a decision first).

The guiding call: **the UI work is bounded so it does not eat M3.** The brief
says the persona's payoff is generation, not browsing. The P0 set below is the
smallest set that makes the descent legible and gives every later renderer
one visual language; everything that is a second renderer, a second mode, or
editing waits.

## P0: one visual language, legible descent

| # | Item | Merges | Size | Depends on | Vocabulary impact |
|---|---|---|---|---|---|
| 1 | **Node card with seam dots and colour-by-layer tokens** in the existing templates. Type pill, label, description, one dot per outgoing seam coloured by target layer. | Levels 3, 8 · Reveal 1 | S | none | none; `rdfs:label`, `rdfs:comment`, `arch:technology`, `deploy:version` already exist |
| 2 | **C4 renderer on ELK with nested containment.** Replace vis-network; containment as nesting; deterministic positions; levels L1–L3 as class filters; rolled-up L1 edges from a canned query with an acceptance test. | Levels 1, 2, 7 · Reveal 2 | M | 1 | a viewer-side level config, not a seam predicate (design rule 2) |
| 3 | **IFML rendered as IFML, server-side SVG.** Containers as boxes, components with stereotypes and «DataBinding», events as border circles, flows, binding groups; Action hexagons from `seam:triggers`, fields from the written shape, activation notes from `seam:visibleWhen`; seam dots on all of them. | IFML 2, 3 | M | 1 | none to add; derivations only. Decide whether fields come only from SHACL (recommended) |
| 4 | **Level and lens state in the URL**, remembered per notation; level cards written as questions beside the Questions catalog, greyed out when empty. | Levels 5, 6 | S | 2 | none |
| 5 | **Legend with live counts and click-to-hide**, with edge contraction through hidden types. | Levels 4 | S | 2 | none |
| 6 | **Inspector as a right-hand panel.** Also fixes the wheel-over-canvas scroll trap. | walkthrough finding | S | 1 | none |

Ship order: 1, 6, 2, 4, 5, 3. Items 1 and 6 are template-only and can land in
one PR. Item 3 can start in parallel with 2 because it does not share the
layout engine.

## P1: the differentiators, once the base is consistent

| # | Item | Merges | Size | Depends on | Why not P0 |
|---|---|---|---|---|---|
| 7 | **Per-predicate reveal setting** (`open` / `nest` / `layer`) replacing the boolean `seam:navigational`; Relations panel; nest for `presents` and `executes` gives L4. | Reveal 3 · Levels 1 (L4) · open question 1 | M | 2, 3 | Changes an ADR-0005 annotation. Nest needs ELK compound layout, so it waits for 2 |
| 8 | **Tint bpmn-js and dmn-js and add overlay badges**, so process and decision views join the language and show their seams. | Reveal 5 | S | 1 | Cheap, but only reads as consistent once 1 and 2 define the language |
| 9 | **ShapeGraph renderer** using the same card; the data layer has no view at all today. | Reveal 6 | M | 1, 2 | Needed for the descent to bottom out somewhere other than an inspector; after 2 because it reuses the ELK renderer |
| 10 | **IFML on diagram-js with ELK ports for events**, geometry carried over from 3. | IFML 4 | M | 3 | Only worth it once pan, zoom and overlays are needed on the IFML view, and as the base for editing |

## P2: parked, with the reason

| # | Item | Merges | Reason |
|---|---|---|---|
| 11 | **Layer mode** (stacked planes, hover tracing). | Reveal 4 | Legible only as an overview; the mock proved the idea, the product needs 2 and 7 first. Revisit when there is a second worked example large enough to need it |
| 12 | **IFMLEdit JSON exporter** as a conformance check. | IFML 5 | Valuable but orthogonal to the persona; do it when the vocabulary's correspondence claims are challenged, or as a weekend item |
| 13 | **Editing** (diagram-js modeling module, embed modelers read-write). | IFML 6 · project outline roadmap | Explicit v1 non-goal in the product brief |
| 14 | **Levels for IFML** (container › component › event). | Levels open question 2 | Generalise from C4 only when the IFML view needs it; proper notation (3) removes most of the need |

Resolved open questions from the Levels note: L4 is a preset of reveal
choices, not a separate level (item 7); rollup queries live in
`docs/queries/` with acceptance tests (item 2).

## Generation: what is planned, what is not

**Planned already.** The product brief puts generation on the critical path
and defines milestone M3 as three generators for the chat-app tutorial:
htmx templates from the interaction model, a FastAPI scaffold whose handlers
validate against the declared shapes and dispatch through the generic
graph-literate worker, and a docker-compose file from `deploy:`. The brief
scopes them to what the tutorial needs, with the process flow hard-wired and
BPMN interpretation deferred past v1. The outline separately decided the
execution boundary (the engine never learns about seams; one worker resolves
`seam:invokes` and enforces `seam:governedBy`) and left "interpret or
generate" open.

**Not planned.** The hybrid is a decision, not a plan: interpret where a real
engine exists (BPMN and DMN through SpiffWorkflow, SHACL validation through
pySHACL at request time), generate only where none exists (templates, route
scaffold, compose). It changes M3 in one place: the process is run by an
engine from the start instead of being hard-wired, which is the smaller
amount of work and keeps the generated scaffold free of workflow logic. It
also makes the worker from the execution-boundary decision a v1 deliverable
rather than a stub.

**What to do about it.** Two items, neither large:

| # | Item | Size | Output |
|---|---|---|---|
| G1 | **ADR-0007, execution strategy.** Record the hybrid: interpret BPMN/DMN with SpiffWorkflow, validate with pySHACL, generate templates, routes and compose. Amend M3 accordingly. | S | Drafted, status Proposed: [ADR-0007](adr/0007-execution-strategy.md). Its open items are a spike before M3 starts. |
| G2 | **Golden-output dry run.** Hand-write the three target artifacts for the chat app (the htmx page, the FastAPI module, the compose file), then walk the model and mark every line the graph can and cannot produce. The cannot list becomes the vocabulary additions (operation paths, event-to-operation binding, form fields or their SHACL derivation, SSE and channel transport, artifacts for the other three containers, ports) and the generators get a test to pass before they exist. | M | `docs/generation/golden/` plus a gap table |

G2 is a documentation exercise that can run in parallel with P0 and should,
because its gap list will change the vocabulary before the renderers harden
around it. The generators themselves come after G2 and are M3.

## Suggested sequence

*Revised 2026-10-28: the generators now come straight after P0, ahead of P1.
The earlier order put P1 first, which contradicted the guiding call above that
UI work must not eat M3.*

1. P0 items 1 and 6 (one PR).
2. P0 item 2 and G2 in parallel.
3. P0 items 4, 5, 3.
4. M3, opening with the ADR-0007 spike (its open items). ADR-0007 moves to
   Accepted only if the spike holds; then the vocabulary additions from G2's
   gap list, the worker, and the three generators against the golden outputs.
5. P1 items 8, 7, 9, 10 and the P2 list, re-triaged once M3 lands and as the
   second worked example demands.
