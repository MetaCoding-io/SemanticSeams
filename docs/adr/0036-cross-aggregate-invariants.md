# ADR-0036: Cross-Aggregate Invariants — a Profile's `sh:Warning` `sh:sparql` Shapes Are Rules on Instance Data, Which the Runtime Lifts to RDF Through the Shape Contracts and Reports Without Refusing a Write

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M029/S05; backlog X6; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
section 2.4; amends [ADR-0033](./0033-ddd-profile.md) (sections 1 and 2); builds on
[ADR-0001](./0001-named-graph-partitioning.md), [ADR-0018](./0018-domain-profiles.md)
and [ADR-0035](./0035-aggregate-transaction-boundary.md)

## Context

ADR-0035 made an aggregate's members commit together, so an invariant inside one
aggregate holds on every write. The DDD note's section 2.4 names the other kind: a rule
across aggregates, such as "an expense is paid once". DDD says such a rule is eventually
consistent: the two writes are in different transactions, often in different contexts,
and refusing the second write would put both aggregates in one transaction after all.
What the project needs is to *see* a broken cross-aggregate rule, not to block it.

Three things are missing:

- **No rule is about instance data.** Every shape a profile holds (ADR-0033) validates
  the model. The runtime validates each payload against its own shape only, so no shape
  ever sees two entities together.
- **Instance data is not RDF.** The store holds entities as rows of JSON, keyed by the
  shape's `sh:name`s. `seams_runtime.contracts.to_rdf` already turns one payload into
  RDF through its shape's `sh:path`s, for validation, and nothing keeps that graph.
- **A payment does not name its expense.** In chapter 11 a payment's only link to the
  expense it pays is its process instance's correlation key, a column of the entity row
  and not a fact of `:PaymentShape`. A SHACL rule cannot join on it.

## Decision

### 1. A profile's `sh:Warning` shapes with a `sh:sparql` constraint are instance-data rules

An **instance-data rule** is a `sh:NodeShape` in an attached profile's shapes graph
(ADR-0018, ADR-0033) with `sh:severity sh:Warning` and at least one `sh:sparql`
constraint. No new term marks it (principle 4): the severity and the constraint kind
already say "a rule that may be broken, and that joins facts". It is written against
the model's own properties (the `sh:path`s of the shapes it joins), so its focus nodes
are entities, and the profile that holds it is the project's, as `profiles/ddd` is
chapter 11's (ADR-0033 section 3).

The rest of a profile is unchanged: `sh:Violation` shapes are model rules, labelled
`sh:Info` shapes are pills, and a `sh:Warning` shape with only core constraints is a
model rule reported as a `profile-warning`. `seams check` still validates the whole
profile against the model (ADR-0033 section 1). An instance-data rule finds no focus
node there, since the model holds no entity, and a `sh:Warning` result never fails the
check anyway.

### 2. The runtime lifts stored entities to RDF with `contracts.to_rdf`, per shape

The runtime builds one data graph for the rules from the store:

- **Every stored shape** of the model (a `sh:NodeShape` with `seam:storedIn`), in IRI
  order, is read with `store.query(shape)`, so every store kind, a `SplitStore`
  included, is read the same way.
- **Each entity** becomes triples through `contracts.to_rdf(model, shape, fields,
  focus=...)`, where `fields` are the entity's data keys that are fields of the shape's
  contract. Only the shape's `sh:path`s are used: no `rdf:type`, no store column (id,
  correlation key, status, timestamps) unless the shape has a `sh:path` for it, and no
  `seam:` term. Seam predicates live only in the seams graph (ADR-0001), and instance
  data is not a graph of the model.
- **The focus node** is `urn:seams:entity:` followed by the entity id, percent-encoded.
  It is never written anywhere; it exists so that a finding names the entity.
- **The graphs are unioned**, so a rule can join two shapes. The shapes graph is the
  profile's instance-data rules only, and pyshacl runs with inference off and no
  ontology merged, so the result is a function of the stored data and the profile.

A stored entity that `to_rdf` refuses raises its `ContractViolation`: the runtime
refuses a model with a different hash (P006), so such an entity is a store fault to be
named, not skipped. The lift reads; it writes nothing.

### 3. A payment names its expense through a property on `:PaymentShape`

The link a rule joins on is a model fact. `:PaymentShape` gains a property whose
`sh:name` is the correlation key label of the process that writes it (`"expense"`, the
`rdfs:label` of the `proc:correlationKey` parameter of `:payout_process`), a string with
`sh:maxCount 1`, under its own model property path, with a comment in `finance.trig`.

When a write's payload omits a field whose `sh:name` is a correlation key label, the
runtime fills it from the instance's correlation key before it validates. The runtime
finds the field by matching the shape's `sh:name`s against
`model.correlation_key_labels()`, so the code names no field, and the entity's
`correlation_key` column is still set as before. A payload that gives the field keeps
its value.

The paid-once rule is then an instance-data rule whose focus nodes are the objects of
that path (`sh:targetObjectsOf`), one per expense, and whose `sh:sparql` reports an
expense with two or more payments, with a message naming the expense. One expense paid
twice is one finding.

### 4. Warnings are reported and never refuse a write

`Runtime.data_health()` resolves the attached profile with `seams.resolve_profile`,
lifts the store and validates it, and returns the findings, each `(shape, focus,
message, severity)`, sorted. It:

- returns `[]` when the model attaches no profile, and raises the resolver's
  `ResolutionError` (naming `seam:conformsTo` or `seam:profileShapes`) when the profile
  cannot be loaded;
- logs one line, `data health <profile> N warning(s)`, and emits one
  `seams.data_health` span carrying the result count;
- is never called from a write: `Runtime.write`, `Runtime.write_aggregate` and the
  worker store the entity whether or not it breaks a rule. The report is read when
  someone asks for it, by the runtime's caller or by the viewer's data-health view.

A `sh:Violation` on instance data is out of scope. Within an aggregate the shape
contract and ADR-0035's transaction already refuse a bad write; across aggregates a
refusal is the coupling the note warns against. A profile shape of severity
`sh:Violation` is a model rule, and the data-health report does not run it.

## Alternatives considered

- **Refusing a write that breaks a cross-aggregate rule.** Rejected: it validates the
  whole store on every write and makes two aggregates one consistency boundary, which
  ADR-0035 says they are not.
- **A `seam:instanceRule` term, or a separate instance-rules file.** Rejected: a new term
  for what the severity and the constraint kind already say, and a second place for a
  profile's rules.
- **Lifting with `rdf:type` from `sh:targetClass`, or with `seam:` provenance triples.**
  Rejected: an `rdf:type` the payload did not state is inference the contract does not
  make, and a `seam:` term on instance data breaks ADR-0001. A rule targets the objects
  or subjects of the model's own paths instead.
- **Joining on the correlation key column.** Rejected: it is a store column, not a fact
  of the shape, so a rule would depend on the store's schema.
- **A new key term linking a shape's property to the correlation key.** Rejected: the
  `sh:name` already matches the key's label, which is how seeds and `Runtime.query`
  already map a correlation key (`seams_runtime/host.py`, `Runtime.query`).

## Consequences

- `seams_runtime/invariants.py` and `Runtime.data_health()` are added (M029/S05/T02);
  no write path calls them.
- Chapter 11's `:PaymentShape` gains the expense property and the DDD profile gains the
  paid-once rule; the model hash and the generated outputs are regenerated, and
  `seams check` still exits 0 (T03).
- The viewer gets a data-health view that reads a configured store (T04).
- No vocabulary changes, so `seam` stays at 1.5 and no migration is needed.

## Open questions

- **Cost on a large store.** The report lifts every stored entity. A store with many
  entities may need the rules' paths to narrow which shapes are lifted, or an
  incremental report; nothing needs it yet.
- **Rules over the lifecycle.** A rule on a status reads it only where the shape has a
  `sh:path` for it, as `:PaymentShape`'s `:status` does.
