# Review Triage — Claude Code + Codex reviews, July 2026

Decisions on every substantive point from both reviews, re-weighted by the
persona decision (see product-brief.md: solo application builders first).
"CC" = Claude Code review, "CX" = Codex review. Items marked **[branch]** are
greenlit for immediate implementation on the existing review branch.

## Accepted — critical (block everything else)

| Item | Source | Decision |
|---|---|---|
| Flagship queries return zero rows; fragment IRIs are orphans | CC §1 | **[branch]** Mint `seam:inModel` (element → seam:Model), assert for every lifted element. It "earns all the queries." Fragment naming stays for renderer dispatch; membership becomes data. |
| No SHACL shapes despite shapes-over-the-model being the credibility mechanism | CC §6, CX arch §3 | **[branch]** Write `ontology/shapes/seam-shapes.ttl` covering CX's minimum list (every Model has exactly one notation; BPMN/DMN models have a renderPayload; decidedBy only BusinessRuleTask→Decision; etc.). Simultaneously strip `rdfs:domain/range` except where inference is genuinely wanted — RDFS ranges *infer*, not *reject* (CC's governedBy example: a WebACL resource would be inferred to be an odrl:Policy). Constraints live in shapes. |
| Prose acceptance test → executable CI | CC fix-list 2 | **[branch]** pytest: rdflib-parse all TTL, pySHACL-validate, assert expected rows for the canned queries. Would have caught every §6 drift bug. |

## Accepted — architectural decisions (write as ADRs before viewer code)

| Item | Source | Decision |
|---|---|---|
| Named-graph partitioning undefined; example is Turtle, can't express it | CC §3, CX arch §2 | ADR-0001. Adopt CX's partitioning: ontology graphs / one graph per model / **dedicated seams graph** (layers stay pure, seams stay auditable) / payload-manifest graph / shapes graph / as-deployed graph. Convert examples to TriG. |
| IRI identity & migration rules unspecified | CX arch §1 | ADR-0002. Stable model IRIs; `modelIRI#nativeElementId`; no blank nodes for durable nodes; ID rename = breaking migration unless alias recorded. |
| renderPayload resolution semantics TBD | CC §5, CX | ADR-0003. Payload IRIs resolve via the FastAPI payload endpoint against the manifest graph (path + checksum + media type), never against load context. |
| /view/{iri} response contract | CX arch §4 | ADR-0004. Adopt CX's JSON-LD sketch (label, types, focusedModel, notation, seam edges in/out, warnings, breadcrumbs, nativeElementId). |
| Navigation is not "one edge"; multi-hop (event→process→model) needs a rule | CC §4, CX arch §5 | ADR-0005. Annotation-based: navigational seam predicates marked in the ontology (`seam:navigational true`); shell resolves clicked node → preferred target via detailedBy, else navigational-edge (+detailedBy) hop; all other seams go to the inspector. Keeps the shell principled, not a switch statement. Adopt CX's interaction table (click-with-detail / click-without → inspector / breadcrumb / query-result-highlight). |
| Index↔payload drift lint | CC §5 | Accepted; required by tutorial step 4. Parse payload, assert every fragment IRI exists as an element ID; warn on seam-worthy XML elements with no IRI. Ship before any editing story. |

## Accepted — model & example fixes **[branch]**

Missing `arch:dependsOn` (db01 impact query currently rides `deploy:dependsOn`
by semantic accident — CC §2); add a "container executes process" seam edge
(CC §2, needed by "what breaks" queries); `seam:presents` domain
Container-vs-Component contradiction — resolve to Container (matches the
example; a Component variant can wait); DMN fragment-convention violation —
`:pricing_decision` → `:pricing_dmn#...`, same rule as BPMN; `hydra:method`
literal vs `comm:QUERY` resource type-clash — QUERY becomes the string
convention `"QUERY"`; state the `mediaKind + returnsShape` semantics
explicitly ("the shape of the data the fragment renders" — CC guessed our
intent correctly); give mediaKind values a class (rdfs:Resource typing is a
no-op); split or un-domain `deploy:requires` (policy vs node capability);
exercise the never-used edges `seam:visibleWhen` and `seam:subscribesTo` (CC
was right that both demos are valuable — and both occur naturally in the
chat-app model: status indicator visibleWhen streaming; a catch event on the
events channel); fix "every seam edge" and "~15 predicates" overclaims;
reconcile outline §8's stale namespaces (mark as historical sketch); settle
the name — **Seams** — and register w3id.org/seams.

## Accepted — product direction (re-weighted by persona)

| Item | Source | Decision |
|---|---|---|
| No persona / no first workflow | both, independently | Accepted as the top product gap → product-brief.md. Persona: application builders (solo first). |
| Killer feature has no user-facing form | CC prod §3, CX §2/§9 | Canned queries as buttons + `docs/queries/*.rq` catalog. Adopt CX's Explore/Ask/Explain/Validate framing for the viewer's information architecture. |
| Model-health / seam-confidence warnings | CX prod §4 | Accepted into M2 — "trust is the product" is exactly right for builders adopting an unfamiliar paradigm. |
| Friendly labels; standards names alienate | CX prod §5 | Accepted and promoted to a named principle (RDF invisibility, see brief). Mandatory given persona. |
| UX spec: ascent, multiplicity, dead ends, entry, context | CC prod §2 | Accepted → viewer spec alongside ADR-0005. Answers: breadcrumbs = traversal history (not inverse edges — multiple parents make inverse ambiguous); multiple detailedBy targets allowed, disambiguation popover; no-detail click = inspector; entry = root architecture model with search later; deep-linkable `/view/{iri}` URLs promised. Note the known htmx + JS-renderer lifecycle friction (bpmn-js init/destroy on swap); solve the pattern once, early in M1. |
| Demo larger than a toy | CX prod §6 | Superseded-and-satisfied by the tutorial decision: the chat app is the bounded-but-real example, and it naturally includes an external system, a secret, an async-ish flow, and a failure state. A second "messy" example (refunds, access requests) is post-M3. |

## Deferred (with reasoning)

**Authorization propagation model** (CX arch §7): the role-based query
phrasing is demoted in all docs until authorization is real (CC prod §4 —
`customer_policy` is an empty label and we won't pretend otherwise). We adopt
CX's propagation rule as a *comment* in seam.ttl (an action is allowed iff
every edge on the UI-event→…→shape path has no policy or a satisfied one) but
build nothing in v1. The chat app tutorial doesn't need roles.

**Endpoint canonicalization** (CX arch §8): keep direct
`seam:exposes → operation|channel` as sanctioned shorthand for v1; document
that `comm:Endpoint` becomes canonical when environments/versions/base-URLs
force the issue.

**Deployment fact provenance** (CX arch §6 — desired vs resolved vs
observed `seam:deployedTo`): the named-graph partitioning (ADR-0001) is the
answer; full drift machinery stays post-v1 as planned. `deploy:replicas`
semantics (instances vs nodes): instances; clarify in comment.

## Rejected

**None outright.** Both reviews were accurate; the only re-framings are the
persona-driven demotions above. Claude Code's suggested first move (membership
edge + executable test) is confirmed as the branch's starting point.
