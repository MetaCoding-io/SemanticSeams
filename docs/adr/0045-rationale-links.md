# ADR-0045: Rationale Links — an `arch:DecisionRecord` in the Architecture Model Names the Elements a Decision Decides with `dcterms:references`, So the Inspector Can Say Why an Element Exists

**Status:** Accepted

**Date:** 2026-11-16

**Source:** milestone M033/S02; backlog X8 (rationale links); research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.7;
builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0021](./0021-vocabulary-versions.md) and
[ADR-0043](./0043-latency-budgets.md)

## Context

The viewer's inspector says what an element is, what it joins and what is generated
from it, but not why it exists. The answer is usually an ADR in `docs/adr/`, and today
nothing in the model connects the two: a reader has to know which ADR to open. Backlog
X8 asks for decisions to name the elements they decide, so the inspector can list them.

The facts are small: a decision has an identifier (`ADR-0012`), a title, a document,
and the elements it decides. Dublin Core already has the terms (`dcterms:identifier`,
`dcterms:references`), as RDFS has `rdfs:label` and `rdfs:seeAlso`. Principle 4 asks
for the smallest addition that answers the question.

The name must not be confused with `dec:Decision` in `ontology/proc.ttl`, which is a
DMN decision the runtime evaluates. A decision record is documentation about the model,
and nothing executes it.

## Decision

### 1. `arch:DecisionRecord`, the one new term

`arch` 1.4 adds one class, `arch:DecisionRecord`, and no predicate. A record is an IRI
with:

| Predicate | Count | Value |
|---|---|---|
| `rdfs:label` | exactly one | a literal: the decision's title |
| `dcterms:identifier` | exactly one | an `xsd:string` such as `"ADR-0012"`, unique among the records |
| `rdfs:seeAlso` | at most one | the IRI of the decision's document |
| `dcterms:references` | one or more | the IRI of each model element the decision decides |

```trig
<urn:seams:graph:model:expense_architecture> {
    :adr_0012 a arch:DecisionRecord ;
        rdfs:label "Store expenses in SQLite" ;
        dcterms:identifier "ADR-0012" ;
        rdfs:seeAlso <https://example.org/docs/adr/0012-sqlite-store.md> ;
        dcterms:references :expense_db , :submit_expense .
}
```

The class is not an `arch:Element`: a record explains the architecture and is not part
of it, so the C4 views, the exports (ADR-0044) and the generators, which read
`arch:Element`s, never see it. A referenced element may be any IRI the model names: a
container, an operation, a shape, a screen, or a BPMN or DMN element's IRI
(ADR-0002). A model that uses the class declares `arch/1.4` in its manifest graph
(ADR-0021); the addition is compatible, so a model on `arch/1.3` loads unchanged.

### 2. Where records live

Records are written in the architecture (C4) model's graph,
`<urn:seams:graph:model:{architecture model}>`. One decision often decides elements of
several layers, so no single layer's graph is its home; the architecture model is the
one every model has and the one that describes the system as a whole. Records are never
written in the seams graph, the manifest graph, or a payload.

**It is not a seam predicate.** A seam is a join between two layers that generators and
navigation follow, and each seam predicate declares a `seam:reveal` mode (ADR-0001,
ADR-0005). `dcterms:references` joins no two layers of the application: it says that a
document is about an element. Nothing generates from it and the viewer does not navigate
along it, so it stays out of the seams graph and out of the `seam:` vocabulary, as
ADR-0043 kept `nfr:budgetOf` out.

### 3. The shapes

`seamsh:DecisionRecordShape` checks the table of section 1, each finding naming the
record and the predicate; a second record with the same `dcterms:identifier` is a
violation on both. `seamsh:DecisionRecordIriShape` refuses a blank-node record, which
the viewer could neither name nor link. The referenced IRIs are not checked against the
graph, for ADR-0043's reason: a BPMN flow node that no seam names has no triples of its
own. Which graph holds a record is not checked either: `seams check` validates the
merged graphs.

### 4. What reads it

The viewer's inspector lists, for the focused element, the records that
`dcterms:references` it, sorted by identifier, each linked to its `rdfs:seeAlso`
document (S02/T02). Generators and the runtime ignore records; adding one changes the
model hash, as any model triple does, and no generated line besides the hash lines.

## Alternatives considered

- **A seam predicate** (`seam:decidedBy`, `seam:rationale`). Rejected: it joins no two
  layers (section 2), and `seam:decidedBy` already means a DMN decision.
- **A link from the element to the ADR** (`rdfs:seeAlso` on the element). Rejected: one
  decision decides several elements, so the facts about the decision would be repeated
  on each, and the element would carry a document IRI with no identifier or title.
- **Parsing `docs/adr/*.md` for element IRIs.** Rejected: the model is the source of
  truth (principle 1), and the viewer and generators read nothing but the model
  (principle 6).
- **Reusing `dec:Decision`.** Rejected: that class is a DMN decision the runtime
  evaluates, and the target of `seam:decidedBy` from a business-rule task.
- **A full decision vocabulary** (status, date, supersedes, alternatives). Left out:
  the inspector needs identifier, title and document. Status and supersession can be
  added later as compatible widenings when a question needs them.

## Consequences

- `ontology/arch.ttl` moves to 1.4 with `arch:DecisionRecord`; `ontology/shapes/seam-shapes.ttl`
  gains `seamsh:DecisionRecordShape` and `seamsh:DecisionRecordIriShape`, and declares
  the `dcterms` prefix for its SPARQL constraints.
- An ADR that decides model elements gets a record in the architecture graph, and the
  inspector shows it beside each element it references.
- A reference to an IRI the model does not otherwise name is not flagged; the record
  still lists it, and the inspector simply never focuses it.
