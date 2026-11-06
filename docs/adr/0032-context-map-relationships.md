# ADR-0032: Context-Map Relationships — an `arch:ContextRelationship` Joins One Upstream and One Downstream Context with One Type, at Most One per Pair, and a Cross-Context Access Is Translated Unless the Relationship Says Otherwise

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M029/S01; backlog B2; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
section 2.1 (context maps); decides what [ADR-0030](./0030-domains-and-bounded-contexts.md)
section 7 left to B2; builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md) and
[ADR-0021](./0021-vocabulary-versions.md)

## Context

ADR-0030 gave the graph bounded contexts that own models, and stopped short of any fact
between two contexts. Chapter 11 has two contexts, expense and finance, and they meet:

- **The approval process publishes on `payouts`** (`approved_end` `seam:publishesTo`
  `:payouts`), and the payout process, owned by finance, starts on it.
- **Finance reads the expense context's shape.** *Pay Expense*, *Choose Payout*, the
  `payout_method` decision and the console's `paid_expenses` block all `seam:reads`
  `ExpenseShape`, which the expense context owns. No expense element reads or writes a
  finance shape.

So the graph already shows which way the dependency runs, but not what the two teams
agreed about it. Three consumers need that agreement as a fact:

- **`seams diff`** (U8) classifies a shape change as breaking or compatible. It cannot
  say which other contexts a breaking change hits without knowing who depends on whom.
- **A gate** for "every cross-context access is translated unless declared conformist",
  ADR-0030 section 7's second rule.
- **The viewer and the bounded context canvas**, which draw a context's inbound and
  outbound lines.

DDD names the agreements (customer-supplier, conformist, anti-corruption layer, open
host service, published language, shared kernel, separate ways) and draws them as a
line between two contexts with an upstream and a downstream end.

## Decision

### 1. A relationship is an `arch:` node with three facts

`ontology/arch.ttl` gains, as `arch` 1.2 (a compatible widening under ADR-0021 section 7,
no migration file):

```turtle
arch:ContextRelationship a rdfs:Class .

arch:RelationshipType a rdfs:Class .
arch:CustomerSupplier    a arch:RelationshipType ; rdfs:label "customer-supplier" .
arch:Conformist          a arch:RelationshipType ; rdfs:label "conformist" .
arch:AntiCorruptionLayer a arch:RelationshipType ; rdfs:label "anti-corruption layer" .
arch:PublishedLanguage   a arch:RelationshipType ; rdfs:label "published language" .
arch:SharedKernel        a arch:RelationshipType ; rdfs:label "shared kernel" .

arch:upstream         rdfs:domain arch:ContextRelationship ; rdfs:range arch:BoundedContext .
arch:downstream       rdfs:domain arch:ContextRelationship ; rdfs:range arch:BoundedContext .
arch:relationshipType rdfs:domain arch:ContextRelationship ; rdfs:range arch:RelationshipType .
```

- **A node, not a property between contexts.** A relationship has three facts (two ends
  and a type), and a later one may want a label, a channel or a note; a bare
  `arch:upstreamOf` triple could carry none of them without reification.
- **It is architecture, in the architecture model graph.** Both ends are
  `arch:BoundedContext`s, so the relationship joins elements of one layer and lives with
  the contexts it joins (ADR-0001 rule 1). It is not an `arch:Element`: it is a line on
  the map, not a box, and the C4 projections do not draw it as a node.
- **The types are individuals**, as ADR-0030's classifications are, so queries compare
  IRIs and the viewer labels them from `rdfs:label`.

### 2. Upstream is the side whose change can break the other

`arch:upstream` is the context whose language the downstream depends on;
`arch:downstream` is the context that reads, writes or subscribes to what the upstream
owns. A change to an upstream shape can break the downstream; a change to a downstream
shape cannot break the upstream. This is the direction `seams diff` follows: a breaking
change to a shape owned by context U is reported against every context that is
`arch:downstream` of a relationship whose `arch:upstream` is U.

The direction is declared, not derived, because it is the teams' agreement; the gate
(section 4) is what checks the graph's accesses against it.

### 3. One type per relationship, one relationship per pair

- **Exactly one `arch:relationshipType`**, one of the five. DDD's patterns are partly
  per-end (an anti-corruption layer is built by the downstream, an open host service is
  offered by the upstream); here the relationship carries the one that decides how the
  downstream uses the upstream's language, which is what the gate and the diff read.
  Open host service is folded into published language: the graph has no fact that
  distinguishes the protocol from the language it speaks.
- **Separate ways is the absence of a relationship.** Two contexts with no relationship
  have agreed nothing, and any access between them is untranslated.
- **At most one relationship per unordered pair.** Two relationships over expense and
  finance, in either direction, would give the diff two directions and the gate two
  answers. A relationship's two ends are different contexts.

The shapes, in `ontology/shapes/seam-shapes.ttl`:

| Shape | Checks |
|---|---|
| `ContextRelationshipShape` | an `arch:ContextRelationship` has exactly one `arch:upstream` and exactly one `arch:downstream`, each an `arch:BoundedContext`, and they differ; exactly one `arch:relationshipType`, one of the five; no other relationship joins the same two contexts in either direction (`sh:sparql`) |
| `ContextRelationshipTermsShape` | only an `arch:ContextRelationship` has an `arch:upstream`, `arch:downstream` or `arch:relationshipType` |

Each message names the predicate. A dataset with contexts and no relationship conforms;
a dataset with no context has no relationship to check.

### 4. A translating operation, and the untranslated-call gate

An element is in the context that owns its `seam:inModel` model (ADR-0030 section 2). A
**cross-context access** is an element in context D that `seam:reads` or `seam:writes` a
shape whose model is owned by a different context U.

A **translating operation** for a shape S into context D is a `hydra:Operation` whose
model D owns, that `seam:acceptsShape` or `seam:returnsShape` S, and whose other side
(the shape it returns or accepts) is owned by D. It is the one place D's language meets
U's: the anti-corruption layer's translator, or the adapter over a published language.
The operation's own reference to S is the translation, not an untranslated access.

A cross-context access by element E is **untranslated** unless one of:

- **E is a translating operation** for S into D;
- **D conforms**: a relationship with `arch:upstream` U, `arch:downstream` D and type
  `arch:Conformist`. D has agreed to use U's language as it is, so reading U's shapes
  directly is the agreement;
- **the two share a kernel**: a relationship of type `arch:SharedKernel` between U and D,
  either way round. The kernel's shapes are owned by one side (ADR-0030 section 4) and
  used by both by agreement.

Every other cross-context access is a row of the gate
`docs/queries/gates/untranslated-cross-context-calls.rq`: the element, the shape, the
element's context and the shape's context. That includes an access against the declared
direction (an upstream element reading a downstream shape) and an access between two
contexts with no relationship. Customer-supplier, anti-corruption layer and published
language all still need a translating operation: the relationship says the downstream
keeps its own model, so a downstream process reading the upstream's shape directly is
what the agreement rules out.

Publishing and subscribing on a channel (`seam:publishesTo`, `seam:subscribesTo`) is not
an access: the channel is the published contract, and its subscriber reads the message
through its own process. The gate reads only `seam:reads` and `seam:writes`.

### 5. The worked example: expense upstream of finance, conformist

Chapter 11's facts fix the direction: finance reads `ExpenseShape` in four places and
expense touches no finance shape, so expense is upstream and finance downstream. Finance
has no operation that translates an expense into a payment-side shape; its processes read
`ExpenseShape` as the expense context defines it. That is conformist, and the chapter
declares it:

```trig
<urn:seams:graph:model:expense_architecture> {
    :expense_to_finance a arch:ContextRelationship ;
        arch:upstream :expense_context ;
        arch:downstream :finance_context ;
        arch:relationshipType arch:Conformist .
}
```

With it the gate has no rows on chapter 11, and a breaking change to `ExpenseShape` is
reported by `seams diff` against the finance context. Declaring customer-supplier instead
would make the gate list the four reads until finance adds a translating operation; that
is the refactoring a later chapter can show.

## Alternatives considered

- **A property between contexts (`arch:upstreamOf`) and a type per context.** Rejected:
  the type belongs to the pair, not to either context, and a property cannot carry a
  type without reification.
- **The relationship in the seams graph.** Rejected: both ends are architecture
  elements, so it is not a cross-layer fact (ADR-0001 rule 1).
- **Deriving the direction from the accesses.** Rejected: the direction is an agreement
  the gate checks the accesses against; derived, the gate could never fail on direction.
- **Several relationships per pair (one per type, or one per direction).** Rejected:
  `seams diff` and the gate need one answer per pair; a pair whose agreement differs by
  direction is two contexts that should be redrawn.
- **Separate ways and open host service as types.** Rejected: separate ways is no
  relationship, and open host service has no fact that tells it from published language.
- **A `ddd:` vocabulary.** Rejected for the reason ADR-0030 gives: contexts and the lines
  between them are method-neutral architecture facts.

## Consequences

- `arch` becomes `1.2`; every example declares it, and models that declare `1.1` load
  unchanged.
- `seams diff` gains a per-downstream-context view of breaking changes (M029/S01/T03),
  and the untranslated-call gate is added (M029/S01/T04).
- Chapter 11 declares `expense_to_finance` (M029/S01/T02).
- The bounded context canvas and the viewer can draw relationships as lines between
  contexts; neither is decided here.

## Open questions

- **Who owns a store.** ADR-0030's open question stays open: a store two contexts write
  is a deployment fact, and no relationship type covers it.
- **Channels on the relationship.** A relationship could name the channels it runs
  through (`payouts`). They are derivable today from the publishers' and subscribers'
  owners, so nothing is added until a consumer needs them stated.
