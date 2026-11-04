# ADR-0025: SemPKM as a Store — a Third `deploy:StoreKind` for Domain Data, Beside SQLite and PostgreSQL, Never the Default

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M024/S01; backlog O4; research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 4 ("SemPKM as the default store"), especially 4.4 ("Open points with SemPKM");
extends [ADR-0011](./0011-storage-resolution.md) and builds on
[ADR-0009](./0009-human-tasks.md), [ADR-0022](./0022-ontology-notation.md) and
[ADR-0023](./0023-shapes-target-classes.md)

## Context

[ADR-0011](./0011-storage-resolution.md) lets the model say where data lives: a shape is
`seam:storedIn` a store `arch:Container`, the store has one `deploy:storeKind`, and the
executing container reaches it through a binding that `deploy:connectsTo` it. Two kinds
are supported, `deploy:SQLite` and `deploy:PostgreSQL`. Both are relational: the runtime
keeps each entity as a JSON row.

Since M023 the model's shapes target classes anchored in gist (ADR-0022, ADR-0023), and
the generated API can serve its payloads as JSON-LD (ADR-0024). The research note
proposes the next step: store the domain data as RDF, in SemPKM, so the data the
generated app writes can be browsed, edited and queried by people and other apps in one
graph. SemPKM is an event-sourced RDF4J triplestore behind a FastAPI backend, with one
write path (`POST /api/commands`), SPARQL reads scoped to current state, scoped API
tokens, and gist 14.0.0 bundled.

The research note leaves four points open (section 4.4), and proposes SemPKM as the
default for deployments (section 4.3):

- **Nested values.** `object.create` takes a map from predicate to value. How does a
  nested node, such as a gist magnitude, go through it?
- **IRIs.** SemPKM mints object IRIs; the runtime mints entity ids today
  (`Runtime.write`, a `uuid4`). One of them has to give way.
- **Identity.** One service token per application, or a user's token per request?
- **gist version.** SemPKM's bundled `gistCore14.0.0.ttl` carries a placeholder version
  IRI, while ADR-0022 has a model import a specific gist version IRI.

This ADR answers all five.

## Decision

### 1. A third kind: `deploy:SemPKM`

`deploy:SemPKM` is a new `deploy:StoreKind` value: a SemPKM instance, reached over HTTP.
It sits beside `deploy:SQLite` and `deploy:PostgreSQL`. S02 adds the term to
`ontology/deploy.ttl` with its SHACL; this ADR adds no term.

The three facts of ADR-0011 are unchanged:

- a shape is `seam:storedIn` the SemPKM store container;
- the store has `deploy:storeKind deploy:SemPKM`;
- the executing container has a binding that `deploy:connectsTo` the store. Its value is
  the SemPKM base URL, read from the environment variable named by the binding's
  `deploy:key`, as for PostgreSQL. It may be a plain `deploy:value`; a base URL is not a
  secret.

One fact is new, for the token (section 5): a second binding on the executing container
that **`deploy:authenticatesTo`** the store. Its value must come from a secret
(`deploy:secretRef` / `deploy:secretName`). S02 adds `deploy:authenticatesTo` with
`deploy:SemPKM`. The runtime reads no key name to tell the two bindings apart: the
predicate does.

```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix gist:   <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix :       <https://example.org/expenses/> .

:ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
    sh:targetClass :Expense ;
    seam:storedIn :expense_store .

:expense_store a arch:Container ; rdfs:label "Expense Store" ;
    arch:technology "SemPKM" ;
    deploy:storeKind deploy:SemPKM ;
    arch:dependsOn :expense_triplestore .

:expense_triplestore a arch:Container ; rdfs:label "Expense Triplestore" ;
    arch:technology "RDF4J" .

:expense_api a arch:Container ; rdfs:label "Expense API" ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "SEMPKM_URL" ;
                         deploy:value "http://expense-store:8000" ;
                         deploy:connectsTo :expense_store ] ,
                       [ deploy:key "SEMPKM_TOKEN" ;
                         deploy:secretRef <https://secrets.example.org/expenses/prod/sempkm-token> ;
                         deploy:secretName "expenses-prod-sempkm-token" ;
                         deploy:authenticatesTo :expense_store ] ] .
```

### 2. Domain data only; process state stays in the runtime's store

SemPKM holds the **entities of written shapes**: the domain data. Process instances,
worker rows, user tasks and the trace are execution state, not domain data. They stay in
a relational store: the `deploy:SQLite` or `deploy:PostgreSQL` store the executing
container connects to, or embedded SQLite at `SEAMS_DB` when it connects to none.

This amends ADR-0011's v1 process-state rule for SemPKM only:

- an executing container connects to at most one relational store and at most one
  SemPKM store;
- each written shape is `seam:storedIn` one of the two.

### 3. Writes: validate against the seam shapes, then `POST /api/commands`

`Runtime.write` keeps its order. The payload is validated against the model's shape
first, so a bad payload still gets a 422 with the failing paths. SemPKM validates in the
background, after commit, so it cannot give that answer.

The runtime then sends the commands for the entity in one `POST /api/commands` request:

- `object.create` with the shape's `sh:targetClass` as the RDF type, and a map from each
  field's `sh:path` to its value, typed by `sh:datatype`. A category field sends its
  member IRI, the mapping ADR-0024's context states;
- for each nested value, the commands of section 4.

A SemPKM-stored shape must therefore have a `sh:targetClass` (ADR-0023). The runtime
writes no predicate the shape does not name.

### 4. Nested values are objects joined by an edge

A nested node, such as a gist magnitude (`gist:hasMagnitude [ a gist:Magnitude ;
gist:numericValue ... ; gist:hasUnitOfMeasure ... ]`), is **created as its own object
and joined to its parent by an edge**: one `object.create` for the nested node, typed by
its `sh:node` shape's `sh:targetClass`, and one `edge.create` from the parent along the
field's `sh:path`. Both go in the same request as the parent's `object.create`, so they
commit in one SemPKM event.

Blank nodes inline are rejected:

- `object.create` takes a map from predicate to value; a blank node has no place in it.
- SemPKM's later commands (`object.patch`, `edge.patch`) and its event diffs, undo and
  federation address objects by IRI. A blank node cannot be patched, undone or shared
  on its own.
- An object can be browsed and edited in SemPKM's workspace like any other, which is the
  point of storing the data there.

The flattened field of ADR-0023 is unaffected on the wire: the form still sends one
value, and the runtime still adds the fixed `sh:hasValue`s. The store only sees the
nested node as an object. Reads (section 6) reassemble it by following the edge.

If S02 finds that SemPKM does not commit the commands of one request together, it stops
and amends this ADR rather than writing parent and child in separate events.

### 5. Identity: one service token per application

The runtime calls SemPKM with **one service token per application**, from the
`deploy:authenticatesTo` binding, scoped to `objects:write` and `sparql:read`. It sends
no user's token.

This is the ADR-0009 split kept as it is. Who may complete a task, or call an operation,
is decided in the runtime by the `PolicyEvaluator`, against the task or operation's
`seam:governedBy` policies, before anything is written. SemPKM is told what to store,
not asked who may store it. The identity that completed a user task is still recorded in
the runtime's trace row (`"by"`), where it is today.

A user's token per request is rejected for now:

- authorization would split between ODRL in the model and SemPKM's token scopes, and the
  two could disagree;
- a process step with no person behind it (a service task, a channel-started process,
  ADR-0010) has no user token to send;
- the runtime would hold user credentials for a second system.

A later ADR can add per-user tokens, so that SemPKM's event graphs name the person, when
the runtime has a model fact for it.

### 6. Reads: SPARQL scoped to current state and the shape's class

Reads are `POST /api/sparql` queries over SemPKM's current state, with the service
token. Each query is scoped:

- to the shape's `sh:targetClass` (`?s a <class>`), so a read never returns objects the
  model does not describe, even though other apps write to the same graph;
- to the shape's `sh:path`s, following the edges of section 4 one level to rebuild
  nested values.

The queries are built from the typed view (`seams.views.shapes`) with sorted variables,
so the same model sends the same query text.

### 7. IRIs: the runtime gives way

**SemPKM mints the IRI. The runtime keeps the IRI `object.create` returns as the
entity's id**, in place of the `uuid4` it mints for the relational stores. A shape that
has an `id` field gets the IRI as its value.

- SemPKM is the one write path for its graph, and other apps write there too. One
  authority for object identity avoids two schemes in one graph.
- A runtime-minted IRI could not be kept stable through SemPKM's own edits and
  federation without SemPKM accepting it, which its `object.create` does not.
- The runtime's ids are runtime data, not model terms: ADR-0002's rules for model IRIs
  and "same model, same bytes" are untouched.

The IRI is not deterministic, which is acceptable for the same reason a `uuid4` is:
generated files never contain it.

### 8. gist version: resolved by the runtime, checked against what SemPKM bundles

SemPKM is not asked to resolve `owl:imports`. Imports are resolved offline at load,
against `ontology/vendor/`, exactly as ADR-0022 says. SemPKM's placeholder version IRI
is never read.

The data a store holds uses gist class and property IRIs, which carry no version. The
version only matters for agreement between the model and the gist SemPKM bundles, which
is gist 14.0.0, the version this project vendors. So:

- a model that names a `deploy:SemPKM` store and imports gistCore 14.0.0
  (`https://w3id.org/semanticarts/ontology/gistCore14.0.0`) is supported;
- a model that names a `deploy:SemPKM` store and imports any other gist version fails at
  load (section 10). When SemPKM bundles another release, it is vendored and added to
  the supported pair in the same change.

The Mental Model generator (O5) states the gist version the model targets in what it
emits; it does not rely on SemPKM's version IRI either.

### 9. SemPKM is not the default

**Embedded SQLite stays the default**, as ADR-0011 says: a model that declares no store
runs on SQLite at `SEAMS_DB`. SemPKM is used only when a store says `deploy:storeKind
deploy:SemPKM`.

The research note's proposal to make SemPKM the default for deployments (section 4.3) is
not taken. A default is what the runtime uses when the model says nothing; choosing a
four-service stack, a network dependency and a token for a model that never asked for
them would be the runtime inventing facts. A deployment that wants SemPKM says so in
one triple.

### 10. Compose adds SemPKM's services because the model names them

When a store has `deploy:storeKind deploy:SemPKM`, the compose generator emits SemPKM's
services from the model's containers: the store container (SemPKM's API) and the
containers it `arch:dependsOn` (the triplestore, the frontend), each with the image,
ports, volumes and healthchecks the model gives it. The bindings of section 1 become
environment entries and secrets, as for PostgreSQL. The generator hard-codes no SemPKM
image, port or service name: a missing fact is a precondition failure, not a guess.

### 11. The error contract

Resolution stays at `Runtime.load`, before any request is served. ADR-0011's
`seams.errors.ResolutionError(subject, predicate)` gains these cases:

| Case | `subject` | `predicate` |
|---|---|---|
| a SemPKM store with no connecting binding on the executing container | the container | `deploy:connectsTo` |
| a SemPKM store with no token binding, more than one, or one whose value is not a secret | the container | `deploy:authenticatesTo` |
| more than one SemPKM store, or more than one relational store, for one container | the container | `deploy:connectsTo` |
| a shape `seam:storedIn` a SemPKM store with no `sh:targetClass` | the shape | `sh:targetClass` |
| a nested field of a SemPKM-stored shape whose `sh:node` shape has no `sh:targetClass` | the nested shape | `sh:targetClass` |
| a model naming a SemPKM store that imports a gist version other than 14.0.0 | the ontology | `owl:imports` |

At run time, SemPKM failures are not resolution errors:

- SemPKM unreachable, timing out, or answering 5xx on a write: the write returns 503
  with a problem+json body naming the store container. The process does not advance and
  the runtime's store is unchanged, so the request can be retried.
- SemPKM answering 401 or 403: the token is wrong or lacks a scope. The write returns
  503 and the log names the store and the missing scope; the user's request is not
  blamed.
- A malformed answer (no IRI from `object.create`): 502, nothing kept.

`/healthz` reports `{"kind": "SemPKM", "container", "reachable"}` for a SemPKM store, and
the relational store as today. ADR-0011's development override applies:
`SEAMS_STORE_OVERRIDE=sqlite` keeps the SemPKM-stored shapes in embedded SQLite, with a
warning, after the facts above resolve.

### 12. Out of scope

- SemPKM webhooks as a channel (O6, M024/S04).
- The Mental Model generator's format (O5, M024/S03), beyond section 8.
- Updates and deletes. The runtime writes new entities today; `object.patch` and
  `edge.patch` follow when the runtime updates entities.
- Federation between SemPKM instances.

## Alternatives Considered

- **SemPKM as the default for deployments** (research note 4.3). Rejected: section 9.
- **A new store interface for RDF stores.** Rejected: SemPKM is one more backend behind
  ADR-0011's interface; only its write and read bodies differ.
- **Process state in SemPKM too.** Rejected: execution state is not domain data, it
  changes on every step, and other apps have no use for it. Keeping it relational keeps
  ADR-0009's task rows and P005's workflow state as they are.
- **Nested values as inline blank nodes.** Rejected: section 4.
- **The runtime mints IRIs and SemPKM accepts them.** Rejected: `object.create` returns
  the IRI it mints, and one graph should have one minting authority (section 7).
- **A user's token per request.** Rejected for now: section 5.
- **The token in the connection URL** (`https://token@host`). Rejected: it puts a secret
  in a value that is otherwise not secret, and logs and `/healthz` would have to scrub
  it. A separate secret binding keeps it out.
- **Telling the bindings apart by `deploy:key`.** Rejected: ADR-0011 rules out key-name
  conventions; `deploy:authenticatesTo` is a fact.
- **Asking SemPKM to resolve gist imports.** Rejected: its version IRI is a placeholder,
  and ADR-0022 resolves imports offline.

## Consequences

- **S02** adds `deploy:SemPKM` and `deploy:authenticatesTo` to `ontology/deploy.ttl` with
  their SHACL, a SemPKM backend behind the store interface resolved under section 11,
  and the compose wiring of section 10.
- **S03** adds the Mental Model generator (O5), stating the gist version as section 8
  says.
- **S04** turns SemPKM's webhooks into a channel (O6).
- Models with no store, or with a SQLite or PostgreSQL store, are unchanged.
- The domain data of a SemPKM-stored shape can be browsed and queried in SemPKM by
  people and other apps, while the runtime keeps owning process state and authorization.
