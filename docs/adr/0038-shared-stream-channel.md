# ADR-0038: Shared Stream Channel and Replicas — the Live-Update Bus Follows the Store Kind (PostgreSQL LISTEN/NOTIFY, In-Process for SQLite), Instances Resume from the Store on Any Replica, and the Generated Replica Cap Is Lifted

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M030/S03; backlog A10; research note
[runtime storage](../research/2026-10-29-runtime-storage.md) ("Not covered"); builds on
[ADR-0010](./0010-channel-started-processes.md),
[ADR-0015](./0015-environments.md) and
[ADR-0037](./0037-timers-and-scheduling.md)

## Context

The chat app's `:chat_api` declares `deploy:replicas 3`. ADR-0015 caps the generated
serving container at one replica, in every environment, because two pieces of state
live in the runtime's process:

- **The live-update stream.** `seams_runtime/channels.py`'s `ChannelBus` keeps each
  `(channel, scope)`'s subscriptions and a bounded backlog of SSE frames in memory. A
  frame published on one replica never reaches a client whose `GET` stream landed on
  another.
- **Process instances.** `Runtime.instances` holds every instance the runtime launched.
  `_waiting_instance` already falls back to the store checkpoint, but other lookups
  assume the instance was launched here, and `_task_locks` serialises a user-task
  completion only within one process.

U9 moved checkpoints, entities, user tasks and (ADR-0037) timer claims into a store that
replicas can share when it is PostgreSQL. The runtime-storage note said a shared database
is necessary for replicas but not sufficient: the stream needs a shared channel too.
ADR-0037 section 4 already makes timer firings run once across replicas.

## Decision

### 1. The channel transport follows the store kind

`Runtime.load` picks the bus from the kind of the relational store it uses
(`store.kind`), so no new deployment fact is needed:

| Store kind | Bus | Reach |
|---|---|---|
| `postgresql` | `PostgresChannelBus` | every runtime on the same database and schema |
| `sqlite` | `ChannelBus` (in-process, unchanged) | one process |

`PostgresChannelBus` has `ChannelBus`'s API (`publish`, `subscribe`, `close`,
`subscriber_count`), so route handlers and the worker do not change.

- **One channel name per runtime schema.** All frames of a runtime go through one
  `LISTEN`/`NOTIFY` channel, named from the store's schema (`seams_<schema>`, or
  `seams` without one), so two runtimes sharing a database in different schemas never
  see each other's frames.
- **The payload is `{channel, scope, frame}`** as JSON: the channel IRI, the scope and
  the rendered SSE frame. A `close` is the same message with no frame.
- **Every frame is also a row in `channel_frames`.** `publish` inserts
  `(id, channel, scope, frame, created)` into a new `channel_frames` table in the
  runtime schema and sends the `NOTIFY` in the same transaction, so a frame is either
  stored and announced or neither. PostgreSQL refuses a `NOTIFY` payload over 8000
  bytes, so when the JSON payload would exceed it, only `{id}` is notified and each
  listener reads the frame from the table by id.
- **One listener connection per runtime.** A background task holds a dedicated psycopg
  connection that `LISTEN`s and fans each message out to the local subscriptions of its
  `(channel, scope)`. The publishing replica receives its own notification like any
  other and delivers locally only through it, so every replica delivers each frame
  exactly once.

### 2. The backlog replays from `channel_frames`, bounded per `(channel, scope)`

A new subscriber is first sent the stored frames of its `(channel, scope)` in id order,
then live ones, as `ChannelBus` does from memory. `publish` keeps at most the bus's
`backlog` rows per `(channel, scope)` by deleting older ones in its transaction. A
subscriber starts listening before it reads the backlog and drops a live frame whose
id it has already replayed, so no frame is lost or doubled at the seam. A `close` deletes
the scope's rows, which keeps `ChannelBus`'s rule that a closed scope's next `publish`
reopens it.

### 3. `Runtime.instances` is a cache; every resume path reloads from the store

`Runtime.instances` keeps the instances this process is running, but no path may assume
an instance it needs is there. A user-task completion, a subscribed start's lookup, a
timer wake and `Runtime.resume` reload the checkpoint from the store when the instance
is absent or finished elsewhere, so a call can land on any replica.

`_task_locks` stays per process: it only stops two calls on one replica from racing.
Across replicas the store's `user_tasks` row is the claim. A completion takes that row
in a transaction (a conditional delete or update whose row count is checked), and the
replica that does not get it raises `TaskNotOpen`, as a second call on one replica does
today. The task runs once.

### 4. The compose replica cap is lifted, and an unshared store refuses replicas

The compose generator renders the model's `deploy:replicas` for the serving container in
every environment. `SERVING_REPLICAS`, the declared-count fields and the cap comment are
removed (superseding ADR-0015's "replica caveat").

A container whose replicas would not share state is refused: more than one replica on a
container whose runtime store is SQLite (not shared) raises `GeneratorError` naming the
container and `deploy:replicas`. The model, or an environment override of
`deploy:replicas` (ADR-0015), must then say one, or declare a PostgreSQL store.

### 5. The proxy reaches replicas through compose service DNS

The proxy keeps addressing the serving container by its compose service name
(`chat_api:8000`). Docker's embedded DNS returns every replica's address for that name,
so connections spread across replicas with no generated upstream list and no new
`deploy:` fact. An SSE stream stays on the replica it connected to; the shared bus makes
which one irrelevant.

### 6. Observability

The bus logs `channel listen <name>` when its listener starts, `channel reconnect <name>`
with the error each time it reconnects (with backoff, replaying nothing a client has not
asked for again), and `channel dropped <id>` when a notified id has no row, because the
backlog bound or a `close` removed it first. `/healthz` reports the bus as
`"channel": {"kind": "postgresql" | "in-process", ...}`.

## Alternatives considered

- **Redis or another broker.** Rejected: a new container and a new deploy fact for
  something the shared store can already carry.
- **Sticky sessions at the proxy.** Rejected: a message posted on one replica must still
  reach streams held by the others, so stickiness does not remove the shared channel.
- **A new `deploy:` fact choosing the channel.** Rejected for now: the only shared
  transport is the store's, so the store kind already decides it.
- **Always storing frames and notifying only ids.** Rejected: an extra read per frame per
  replica for the common small frame.
- **Cross-process task locks** (advisory locks). Rejected: the claimed row already
  ensures single execution, and a lock held across a worker run would tie up a
  connection.

## Consequences

- M030/S03 builds `PostgresChannelBus`, the `channel_frames` table, the store-backed
  resume paths and the user-task claim, lifts the compose cap and regenerates every
  committed compose file, and runs the chat app end to end with three replicas.
- SQLite models are unchanged: one process, the in-process bus. Declaring replicas on
  one is now an error rather than a silently capped count.
- A replica that loses its listener misses the frames published while it reconnects;
  a client that reconnects its stream gets them from the backlog.

## Open questions

- **Frames for a scope nobody streams** are kept up to the backlog bound until the scope
  is closed. A retention time may be needed if scopes are never closed.
