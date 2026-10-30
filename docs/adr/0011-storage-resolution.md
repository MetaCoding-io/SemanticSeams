# ADR-0011: Storage Resolution — the Runtime Stores Data Where the Model Says

**Status:** Accepted

**Date:** 2026-10-30

**Source:** decision D039; milestone M011/S01; backlog U2 and U9; plan: [runtime storage plan](../research/2026-10-29-runtime-storage.md)

## Context

The chat app models a store. `:message_db` in `examples/chat-app/chat-app.trig` is an
`arch:Container` labelled "Message Store", with `arch:technology "PostgreSQL"`, a
`postgres` image, a volume and a healthcheck. The Chat API `arch:dependsOn` it and
carries a `DB_URL` binding whose value comes from a secret.

The runtime never connects to it:

- `seams_runtime/store.py` is hard-wired to SQLite. The file path comes from the
  `SEAMS_DB` environment variable, whatever the model says.
- `compose.override.yaml` says so out loud: `DB_URL` is unused.
- Nothing in the graph ties a binding to the store it reaches. `DB_URL` is a key-name
  convention, not a fact, and `"PostgreSQL"` is free text in `arch:technology`.
- Nothing in the graph says which store holds which data. The SHACL shapes the runtime
  writes have no link to any container.

So the model and the running system disagree about where data lives, and no query can
answer "which data is lost if this node goes away".

[ADR-0007](./0007-execution-strategy.md) stands: the runtime interprets the model and
resolves everything it needs at load time. This ADR adds storage to what it resolves.

## Decision

The runtime picks its store from three graph facts. It reads no key name and parses no
free text.

### The three facts

1. **`seam:storedIn`** — `sh:NodeShape` → `arch:Container`. The shape's instances live
   in that store. It is the only new seam predicate, and it earns a query:
   `impact-of-node.rq` can now say which data is lost if a node goes away (a shape
   `seam:storedIn` a container, the container `seam:deployedTo` the node).
2. **`deploy:storeKind`** — store `arch:Container` → a `deploy:StoreKind` IRI. It is a
   controlled vocabulary. The supported values are `deploy:PostgreSQL` and
   `deploy:SQLite` (an embedded file). `arch:technology` stays free text for people and
   is never read by the runtime.
3. **`deploy:connectsTo`** — on a `deploy:binding` blank node → the store
   `arch:Container` whose connection string the binding carries. It sits beside
   `deploy:serviceOf`, which names the service a URL binding reaches. The value still
   comes from `deploy:secretRef` / `deploy:secretName` (or `deploy:value` for a
   non-secret dev URL); secret values never enter the graph. The runtime reads the
   environment variable named by the binding's `deploy:key`. It never assumes `DB_URL`.

The chat app states them like this:

```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/chat/> .

:MessageShape a sh:NodeShape ; rdfs:label "Message" ;
    seam:storedIn :message_db .

:message_db a arch:Container ; rdfs:label "Message Store" ;
    arch:technology "PostgreSQL" ;
    deploy:storeKind deploy:PostgreSQL .

:chat_api a arch:Container ; rdfs:label "Chat API" ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "DB_URL" ;
                         deploy:secretRef <https://secrets.example.org/chat/prod/db-url> ;
                         deploy:secretName "chat-prod-db-url" ;
                         deploy:connectsTo :message_db ] ] .
```

### The process-state rule

Process instances, worker rows and the entities of a process live in the store that
the container which `seam:executes` the process connects to, through its
`deploy:connectsTo` binding.

In v1:

- each written shape (a shape some operation, form or task `seam:writes`) must be
  `seam:storedIn` that same store;
- an executing container connects to at most one store.

### Supported kinds and the default

| Kind | Connection | Notes |
|---|---|---|
| `deploy:SQLite` | none needed | embedded file; the path comes from `SEAMS_DB`, as today |
| `deploy:PostgreSQL` | a `deploy:connectsTo` binding on the executing container | JSON columns are `jsonb` |

A model that declares no store at all keeps embedded SQLite. Model health says so as an
informational result, not by silence.

### The error contract

Resolution happens at `Runtime.load`, before any request is served, through the seams
library. Each failure raises `seams.errors.ResolutionError(subject, predicate)`
(`packages/seams/src/seams/errors.py`), naming the subject and the predicate:

| Case | `subject` | `predicate` |
|---|---|---|
| a store with no `deploy:storeKind`, or more than one | the store | `deploy:storeKind` |
| a kind not in the supported set | the store | `deploy:storeKind` |
| a PostgreSQL store with no connecting binding on the executing container | the container | `deploy:connectsTo` |
| a written shape with no `seam:storedIn`, or one stored elsewhere | the shape | `seam:storedIn` |
| more than one store for one container | the container | `deploy:connectsTo` |

Observability: `/healthz` reports the store kind. Model health (S04) fails on a written
shape with no supported store, and warns on a store container that no shape is
`seam:storedIn`.

### Development override

Two ways run the runtime on another store than the model declares, for tests and local
runs without a database. Both resolve the facts first, so a broken model still fails at
load:

- `Runtime.load(..., store=...)` injects a backend, as the test suite does.
- `SEAMS_STORE_OVERRIDE=sqlite` keeps embedded SQLite at `SEAMS_DB` and logs a warning.
  Any other value fails at load.

Neither is silent: `/healthz` reports `{"kind", "declared", "container", "override"}`,
and `override` is true when the store in use is not the declared kind.

### Out of scope

- Replicas (backlog A10, the in-memory stream).
- Schema evolution of stored data (backlog U8).
- Migrating existing SQLite dev data. The guide documents a reset: delete the
  `SEAMS_DB` file and restart.

## Alternatives Considered

- **Read `DB_URL` by key name.** Rejected: it is a chat-app convention. Another model
  names its key differently, and the key says nothing about which store it reaches.
- **Parse `arch:technology`.** Rejected: it is free text for people ("PostgreSQL",
  "Postgres 16", "FastAPI, SSE streaming"). A controlled `deploy:StoreKind` value can be
  checked by SHACL.
- **A `seam:` predicate for the kind or the binding.** Rejected: both are deployment
  facts and belong in `deploy:`. Seams stay few; only `seam:storedIn` crosses layers
  (data to architecture).
- **A per-process store predicate.** Rejected: the executing-container rule already
  answers where a process's state lives, from facts the model states anyway.

## Consequences

- **S02** adds `seam:storedIn`, `deploy:storeKind`, `deploy:StoreKind` with its two
  values, and `deploy:connectsTo` to the ontologies with their SHACL, and states the
  facts in `examples/chat-app/chat-app.trig` and the expenses tutorial chapter 8.
- **S03** adds the store interface and its SQLite and PostgreSQL backends, resolved at
  `Runtime.load` under the error contract above. It also landed `/healthz` reporting
  the store kind and the compose wiring: the runtime reads the bound connection string
  (`DB_URL_FILE`, `DATABASE_URL_FILE`), and both compose stacks run on their declared
  PostgreSQL.
- **S04** added the model health checks (`ModelGraph.store_health()`, shown in the
  viewer's health panel: a written shape with no supported store fails, a store no
  shape is `seam:storedIn` warns, and a model with no store gets an embedded-SQLite
  note) and end-to-end assertions that both stacks write to the declared store and
  that `/healthz` reports it.
- `impact-of-node.rq` can list the data a node holds.
- Existing models with no store keep working on embedded SQLite.
