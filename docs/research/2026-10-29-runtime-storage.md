# Plan: the runtime stores data where the model says

*Status: plan, 2026-10-29. Tracked as backlog item U9. Agreed direction: keep the
execution strategy of [ADR-0007](../adr/0007-execution-strategy.md), and fix the runtime
rather than the model. Written against `main` at `dd56985`.*

## The mismatch

The chat-app model declares a **Message Store**: a PostgreSQL container with a volume, a
healthcheck, and a `DB_URL` secret given to the Chat API. The compose generator turns
that into a running Postgres container. The runtime never connects to it. Its store
(`seams_runtime/store.py`) is hard-wired to a SQLite file inside the Chat API container,
and `compose.override.yaml` says so: "DB_URL is unused". All messages and all process
state live in that file.

So the model is wrong about where the data is, and every answer built on it inherits the
error: the impact query, backups planned from the model, and the diagrams.

## What makes the fix general

Reading `DB_URL` and connecting to it would fix the chat app and nothing else. The key
name is a chat-app convention, and "PostgreSQL" is free text in `arch:technology`. For the
fix to hold for any model, the runtime must choose its store from graph facts, the way it
already resolves tasks, operations, shapes and policies. Three facts are missing:

1. **Which store holds a shape.** A seam from a shape to the container that persists it.
   This is backlog item U2, and it also earns the query "which data is lost if this node
   goes away".
2. **What kind of store it is.** A controlled value on the store container, not free
   text, so the runtime can refuse a kind it does not support.
3. **Which binding connects to it.** The configuration binding that carries the
   connection string, marked by a fact that points at the store container, not found by
   its key name. The secret value stays out of the graph, as now.

One rule needs deciding alongside them: **where process state lives.** The simplest rule
is the store of the container that executes the process, so a model that declares one
store gets everything in it.

A model that declares no store keeps today's behaviour, an embedded SQLite file, and the
model-health check says so instead of staying silent.

## Steps

1. **ADR: storage resolution.** Record the three facts and the process-state rule above,
   the supported store kinds (embedded SQLite and PostgreSQL to start), and the
   error contract.
2. **Vocabulary.** Add the facts to `seam:` and `deploy:` with SHACL shapes, and state
   them in the chat-app model. This lands U2.
3. **Runtime backends.** Put a small store interface in front of the two tables the store
   has today, with a SQLite backend (the current code) and a PostgreSQL backend (JSON
   columns as `jsonb`). `Runtime.load` picks the backend from the graph. A missing or
   unsupported fact fails at load with an error that names the subject and the
   predicate, like `GeneratorError` does. `/healthz` reports the store kind.
4. **Deployment.** The runtime image gains a PostgreSQL driver. The generated compose
   already passes the connection secret; the local override keeps its dev URL, drops the
   "unused" comment, and waits for the database to be healthy.
5. **Model health.** Two checks: every shape a process writes resolves to exactly one
   store of a supported kind; and a store container that no shape lives in raises a
   warning. The second check would have caught this mismatch.
6. **Tests.** Run the runtime tests against both backends, with PostgreSQL as a CI service
   container. The tutorial end-to-end test asserts that a sent message lands in Postgres.

## How we know it is general

The chat app is the only example today, so it cannot prove generality on its own. The
expense-approval build-along tutorial (M009) is the second model. Its data chapter should
declare a store with the new facts and need no runtime change to use it.

## Not covered

- **Replicas.** The model asks for three Chat API replicas, and the local override forces
  one because process instances and the live-update stream are held in memory. A shared
  database is necessary for more than one replica, but not sufficient: the stream would
  also need a shared channel. That is a separate item.
- **Schema evolution** of stored data stays with U8.
- **Migrating existing SQLite data.** It exists only in local development volumes, so the
  plan is to document a reset rather than build a migration.
