# ADR-0035: The Aggregate Transaction Boundary — `seam:aggregateMember` Names the Shapes an Aggregate Commits Together, and the Runtime Writes Them in One Store Transaction

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M029/S04; backlog X7; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
section 2.4 ("Aggregates as explicit consistency boundaries"); builds on
[ADR-0001](./0001-named-graph-partitioning.md), [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0011](./0011-storage-resolution.md), [ADR-0021](./0021-vocabulary-versions.md),
[ADR-0025](./0025-sempkm-store.md), [ADR-0031](./0031-lifecycle-on-the-class.md) and
[ADR-0033](./0033-ddd-profile.md)

## Context

ADR-0033 made an aggregate a derived thing: the `owl:Class` that `seam:lifecycle` names
(or, kept for compatibility, a `sh:NodeShape` that names one), with one lifecycle, one
correlation key and one store. The DDD note's section 2.4 names what the graph still
does not state: **the transactional boundary**. A process carries several entities, and
nothing says which of them must change together.

The runtime has no transactions either:

- `Runtime.write` validates and stores one entity per call.
- The worker persists each of an element's `seam:writes` with its own
  `Store.put_entity` call, each in its own `asyncio.to_thread` call.
- `SQLiteStore` and `PostgresStore` open and commit a connection per operation, so that
  one store can be shared by coroutines and worker threads.
- `SplitStore` (ADR-0025) writes a SemPKM-stored entity over HTTP first and its
  relational index row afterwards.

If the second of two writes fails, the first one stays stored. That is the
partial aggregate DDD's rule "one transaction per aggregate" exists to prevent.

The membership cannot be derived. A class has many shapes (ADR-0031): the submit form's
input shape, an approver's input, a display shape. Some of them are persisted and some
are only views, so "every shape whose `sh:targetClass` is the aggregate" is the wrong
set. An aggregate's member entities can also belong to other classes: an expense's line
items are part of the expense aggregate but are not expenses. The membership is a fact
the modeller states, and principle 1 says it is stated once, in the model.

## Decision

### 1. `seam:aggregateMember` names an aggregate's member shapes

`seam:aggregateMember` is a new property in the `seam` vocabulary, from an aggregate to
one `sh:NodeShape` whose entities the aggregate commits together. The aggregate is
either an `owl:Class` or a `sh:NodeShape` with its own `seam:lifecycle`, the aggregate
of ADR-0033. The predicate lives in the seams graph, as every cross-model link does
(ADR-0001), and its subject and objects keep their own IRIs (ADR-0002):

```turtle
<urn:seams:graph:seams> {
    :Payment seam:lifecycle :payment_lifecycle ;
        seam:aggregateMember :PaymentShape .
}
```

- **The members are listed, never derived.** An aggregate's members are exactly the
  objects of its `seam:aggregateMember` triples. The aggregate's own shapes are members
  only when they are listed. An aggregate with no `seam:aggregateMember` declares no
  boundary, and every write to its shapes stays a single-entity write, as today.
- **The seam shapes check the fact**, in `ontology/shapes/seam-shapes.ttl`. The subject
  has a `seam:lifecycle`, so it is an aggregate. Each object is a `sh:NodeShape`. A
  shape is a member of at most one aggregate. The last rule is a `sh:sparql` constraint
  focused on the shape, so the result has no blank-node path (the reason given in
  ADR-0033's implementation note). Every message names `seam:aggregateMember` and the
  IRIs involved.
- **The library has a typed view.** `packages/seams` has a public view of the
  aggregates: each one's IRI and its members, sorted by IRI. The runtime and the
  profile read the fact through it and through the graph only, and no code names an
  aggregate. It stays rdflib-only and pyright-strict.
- **Vocabulary version.** Adding the term is a compatible change (ADR-0021 section 6),
  so it is `seam` 1.5 with no migration. A model that targets 1.4 loads as it is.

### 2. The DDD profile requires the members to be in one store

ADR-0033's aggregate-boundary rule gets a fourth constraint in
`profiles/ddd/ddd-shapes.ttl`, on the same focus nodes (`sh:targetSubjectsOf
seam:lifecycle`):

- **one transaction store**: the members of `$this` are `seam:storedIn` exactly one
  store between them. Its `sh:message` names `seam:aggregateMember`, the aggregate and
  the stores found.

The profile is where a project claims "aggregates commit atomically" in CI. The runtime
cannot rely on the profile, though, because `seams generate` and `Runtime.load` ignore
profiles (ADR-0033 section 1). So the runtime refuses what it cannot keep (section 5).

### 3. `Store.transaction()` is one all-or-nothing unit of entity writes

The `Store` protocol in `seams_runtime/store.py` gains a context manager:

```python
with store.transaction():
    store.put_entity(...)
    store.put_entity(...)
```

- **Inside the block**, every call on that store from the calling thread uses one
  connection. The writes commit when the block exits normally, and all of them roll
  back when it raises. The exception propagates unchanged. A `transaction()` inside
  another `transaction()` joins the outer one. Outside a block, every operation keeps
  its own connection, as today.
- **`SQLiteStore`** opens one connection and starts the transaction with `BEGIN
  IMMEDIATE`. That takes the write lock up front, so two concurrent aggregate commits
  wait on each other (bounded by the store's `timeout`) instead of failing halfway.
- **`PostgresStore`** uses one connection whose `with` block is the transaction, the
  same form its operations use today.
- **`SplitStore`** delegates `transaction()` to its relational store. Section 5 means no
  aggregate with more than one member reaches the SemPKM backend, so a split
  transaction never has to span the relational store and SemPKM.
- **`SemPKMStore`** is an entity backend, not a `Store`, and has no `transaction()`.

### 4. The runtime commits an aggregate's writes in one transaction

- **`Runtime.write_aggregate(aggregate, payloads)`** takes the aggregate's CURIE or IRI
  and a mapping from member shape to payload, and returns the stored rows keyed by
  shape IRI. It applies `Runtime.write`'s rules to each payload: the `:id` convention
  and the lifecycle's initial status. The steps are:
  1. Resolve. A shape that is not a member of the aggregate, or an empty mapping, raises
     `ResolutionError(shape or aggregate, seam:aggregateMember, detail)`.
  2. Validate every payload before anything is written. A `ContractViolation` (422)
     raises as it would from `Runtime.write`, and nothing is stored.
  3. Write the entities in member-IRI order inside one `store.transaction()`.

  A store failure during step 3 rolls the whole transaction back. It raises
  `AggregateRolledBack`, a `RuntimeModelError` that names the aggregate, the shape
  whose write failed and the cause. Its HTTP status is the cause's if it has one,
  otherwise 500, and the cause is chained (`raise ... from`).
- **The worker** applies the same boundary to the writes of one process element. When an
  element's `seam:writes` include two or more members of one aggregate, it persists
  those members in one `store.transaction()` inside a single `asyncio.to_thread` call,
  so the transaction stays on one thread. Its other writes are persisted one by one, as
  today. A rollback fails the element the way any store error does: the instance keeps
  its last checkpoint and its trace row names the error. This is the case the slice
  demo covers: a process writing two entities of one aggregate commits both or
  neither.
- **Scope.** The boundary covers the entity writes of one call or one element. Status
  updates after a transition (`_set_status`) rewrite the entities of one shape and are
  unchanged. Checkpoints (`save_state`) stay separate writes. A checkpoint that misses
  a committed write is already handled by re-persisting: `put_entity` is an upsert by
  id.

### 5. `Runtime.load` refuses an aggregate the store cannot commit atomically

While the store plan resolves, before any store is opened (ADR-0012's order),
`Runtime.load` raises `ResolutionError(aggregate, seam:aggregateMember, detail)` in two
cases:

- **Members in a SemPKM store.** The aggregate has more than one member and at least one
  of them is `seam:storedIn` a `deploy:SemPKM` store. The detail says that SemPKM
  cannot commit more than one entity of an aggregate atomically (ADR-0035). SemPKM
  commits one `POST /api/commands` request as one event, but an update is a separate
  request (ADR-0025's `update` reads before it patches), and the relational index row
  is written after SemPKM accepts the data. There is no two-phase commit across the
  two, and pretending there is one would keep a partial aggregate on the first
  failure. An aggregate with exactly one SemPKM-stored member is accepted, because its
  write is the single-entity write ADR-0025 already makes.
- **Members in two stores.** The members are `seam:storedIn` more than one store. This
  restates the profile's rule (section 2) for models that attach no profile. The
  runtime cannot keep it either way.

The check runs whatever store is injected or forced (`SEAMS_STORE=sqlite`), as the store
plan's own checks do. A model fault is a model fault on every backend.

### 6. Observability

- **One span per aggregate commit**, named `seams.aggregate.commit`, with the attributes
  `seams.aggregate.iri`, `seams.aggregate.members` (the written shapes, sorted) and the
  store's `kind`. Inside the worker, the span is a child of the element span and also
  carries the instance attributes. A rollback records the exception and ends the span
  with status ERROR, described by `AggregateRolledBack`. With tracing off it is the
  existing no-op.
- **One log line per commit**: INFO naming the aggregate, the members and the entity
  ids. A rollback logs ERROR naming the aggregate, the failing shape and the cause,
  never a payload value.

## Alternatives considered

- **Deriving the members from `sh:targetClass`.** Rejected: a class has view and input
  shapes that are never stored, and member entities can belong to other classes (the
  context above).
- **Putting the fact only in the DDD profile**, as a profile shape that lists members.
  Rejected: the runtime needs the members to commit, and `Runtime.load` ignores
  profiles. A profile holds rules about facts, not the facts. The profile checks the
  fact (section 2) and does not hold it.
- **An `arch:Aggregate` or `ddd:Aggregate` class.** Rejected, as ADR-0033 rejected it.
  The aggregate is already derived from `seam:lifecycle`, and a stated type could
  disagree with the facts it summarises.
- **The inverse, `seam:memberOf` on the shape.** Rejected: the boundary is the
  aggregate's fact. Reading it from one subject keeps it reviewable in one place, and
  "at most one aggregate per shape" is a constraint either way.
- **Saga or compensation for SemPKM members**, undoing the created objects when a later
  write fails. Rejected for now: an undo is a second write that can itself fail, and
  SemPKM's event log would keep the failed create. Refusing the model is honest, and
  the open question below keeps the option.
- **Transactions on every write.** Rejected: one entity is already atomic, and a
  transaction around unrelated writes would serialise SQLite writers for no
  invariant.

## Consequences

- `seam` 1.5 adds `seam:aggregateMember`, with its seam shapes and the library's typed
  aggregate view (M029/S04/T02).
- The DDD profile gains the one-transaction-store constraint, with a negative fixture
  whose expected `sh:message` is exact (T02).
- **Chapter 11 declares its aggregates' members as the model has them.**
  `:Payment seam:aggregateMember :PaymentShape` and `:Expense seam:aggregateMember
  :ExpenseShape` are one member each. The expense and its approval are not one
  aggregate there: `:ExpenseShape` is in `:expense_pkm` and `:ApprovalShape` is in
  `:expense_db`, so the profile would flag the pair and `Runtime.load` would refuse it.
  They are two aggregates that refer to each other by id, which is the DDD reading.
  Chapter 11's seams graph changes, so its model hash and generated outputs are
  regenerated (T02). The two-entity commit and its rollback are shown with inline
  fixtures (T03).
- `Store.transaction()`, `Runtime.write_aggregate`, the worker's aggregate commit,
  `AggregateRolledBack` and the load-time refusal arrive with tests on SQLite and
  PostgreSQL (T03). A model that declares no `seam:aggregateMember` behaves as it does
  today, byte for byte.
- Backlog X7 is done when T03 lands.

## Open questions

- **Cross-aggregate invariants.** Section 2.4's second point ("an expense must not be
  paid twice") needs instance data as RDF (O4). It would be a `sh:sparql` rule with
  `sh:Warning` severity, reconciled by a saga, and is not a transaction.
- **SemPKM aggregates.** If SemPKM gains a request that creates and updates several
  objects in one event, section 5's first refusal could become a single SemPKM commit
  for aggregates whose members are all SemPKM-stored.
