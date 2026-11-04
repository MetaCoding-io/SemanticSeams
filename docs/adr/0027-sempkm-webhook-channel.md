# ADR-0027: SemPKM Webhooks as a Channel — `object.changed` Starts a Subscribed Process

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M024/S04; backlog O6; research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 4 ("Webhooks as a channel"); extends
[ADR-0010](./0010-channel-started-processes.md) and builds on
[ADR-0025](./0025-sempkm-store.md) and [ADR-0013](./0013-error-shapes-and-boundaries.md)

## Context

[ADR-0010](./0010-channel-started-processes.md) lets a process start from a channel: its
BPMN message start event `seam:subscribesTo` a `comm:Channel`, and when another process
publishes on that channel the runtime calls `Runtime.start_subscribed` (worker rule 6a).
The channel is in-process: only a process of the same runtime can publish on it.

[ADR-0025](./0025-sempkm-store.md) keeps the domain data of a `deploy:SemPKM` store in
SemPKM, where people and other apps edit it too. Its section 12 left one thing out:
letting a change made in SemPKM start a process (O6). SemPKM sends webhooks, so the
missing piece is a channel that SemPKM publishes on.

What SemPKM actually sends decides most of this ADR. Its backend
(`app/services/webhooks.py`, `app/commands/router.py`, `app/security/ssrf.py`, read for
this ADR) works like this:

- **Configuration.** A webhook is a target URL, a list of event types and a list of
  filters, kept as RDF in `urn:sempkm:webhooks`. An owner creates it in SemPKM's admin
  pages (`POST /admin/webhooks`, session login only; there is no token API). The filters
  are stored but never applied: every event of a subscribed type is delivered.
- **Events.** `object.create`, `object.patch`, `body.set` and `body.diff` commands send
  `object.changed`; `edge.create` and `edge.patch` send `edge.changed`; validation sends
  `validation.completed`. One delivery is sent **per command**, so a request that commits
  two `object.create`s (an entity and its nested node, ADR-0025 section 4) sends two
  `object.changed` deliveries for the same event.
- **Payload.** A JSON `POST` with exactly four keys, shown in section 4. It names the
  event graph (`event_iri`), **not the object that changed** and not its class.
- **Delivery.** Fire-and-forget: one attempt with a 5 second timeout, no retry, and the
  answer's status is only logged. The delivery is awaited inside SemPKM's command request,
  after the commit and before the answer.
- **No signature.** The delivery carries no signature, no secret header and no
  configurable header. SemPKM has no per-webhook secret to sign with.
- **SSRF guard.** Before each delivery SemPKM resolves the target host and refuses
  loopback, private, link-local, reserved and multicast addresses.
- **The event graph.** The event's named graph holds `<event> a sempkm:Event` and one
  `sempkm:affectedIRI` per object the event changed (`sempkm:` is `urn:sempkm:`). SemPKM's
  SPARQL endpoint scopes every query to current state; reading another graph needs a
  `GRAPH` clause with `all_graphs`, which SemPKM allows only to a token whose user has
  the owner role. `POST /api/sparql` is rate-limited to 60 requests a minute.

The plan for this slice assumed a signed webhook checked against a secret from the
deploy facts. SemPKM signs nothing, so there is no signature to check. Section 6 says
what authenticates a delivery instead.

## Decision

### 1. A transport value: `comm:SemPKMWebhook`

`comm:SemPKMWebhook` is a new `comm:Transport` value: SemPKM `POST`s the channel's events
to the runtime. It sits beside `comm:SSE` and `comm:WebSocket`, which carry events the
other way, out to a client. A channel with `comm:transport comm:SemPKMWebhook` is
**inbound**: no process `seam:publishesTo` it; SemPKM is its only publisher.

S04/T02 adds the term to `ontology/comm.ttl` with its SHACL. No other term is added:
every other fact a webhook channel needs is already in the vocabulary.

```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/expenses/> .

:vendor_changes a comm:Channel ; rdfs:label "vendor changed in SemPKM" ;
    comm:transport comm:SemPKMWebhook ;
    comm:eventName "object.changed" ;
    seam:acceptsShape :VendorShape ;
    comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/vendor-changes" ] .

:VendorShape a sh:NodeShape ; rdfs:label "Vendor" ;
    sh:targetClass :Vendor ;
    seam:storedIn :expense_pkm .

:expense_api seam:exposes :vendor_changes ;
    seam:executes :vendor_check_process .

<https://example.org/expenses/vendor_check_bpmn#vendor_changed>
    a proc:MessageCatchEvent ;
    seam:subscribesTo :vendor_changes .
```

### 2. The facts of a webhook channel

A channel whose `comm:transport` is `comm:SemPKMWebhook` has:

- **`comm:eventName`**: exactly one, the SemPKM event type it listens for. Only
  `"object.changed"` is supported (section 11 lists the others as open points). The
  receiver compares the delivery's `event_type` to this fact. It has no event type of
  its own.
- **`seam:acceptsShape`**: exactly one `sh:NodeShape`, the shape of the objects whose
  changes start processes. The shape must be `seam:storedIn` a `deploy:SemPKM` store and
  must have a `sh:targetClass`, as ADR-0025 requires of every SemPKM-stored shape. The
  class says which changed objects matter, and the shape says how to read them.
- **`comm:path`**: exactly one `hydra:IriTemplate` with no `hydra:mapping`. Its
  `hydra:template` is the receiving route, relative to the container. A delivery names
  no variable, so a template with variables cannot be filled.
- **one receiving container**: exactly one `arch:Container` `seam:exposes` the channel.
  That container must `seam:executes` every process subscribed to it, and it must reach
  the SemPKM store that holds the accepted shape through ADR-0025's two bindings
  (`deploy:connectsTo` for the URL, `deploy:authenticatesTo` for the service token).
- **at least one subscriber**: a channel-started process (ADR-0010) whose start event
  `seam:subscribesTo` the channel. A webhook channel with no subscriber is a fault, not
  a silent sink.

The SemPKM store is not named on the channel. It is the store the accepted shape is
`seam:storedIn`, so the shape is the single source of that fact.

### 3. The route: `POST` at the channel's `comm:path`

The FastAPI generator emits one `POST` route per webhook channel on the receiving
container, at the channel's `comm:path`. It computes everything in `extract` from the
facts of section 2, and the template only renders it. The route does what a generated
route does (P007): it hands the body to the runtime, with no branching of its own.

The route is not proxied by the htmx container. It is a machine-to-machine endpoint on
the API container. People never call it.

Registering the webhook in SemPKM is a deployment step, not a model fact: an owner adds
a webhook in SemPKM's admin pages with the target URL (the receiving container's public
base URL followed by the `comm:path`) and the event type of the `comm:eventName`. The
model cannot do this for them, because SemPKM has no token API for webhooks (section 11).

### 4. The payload, and how it maps to start state

SemPKM's delivery body is exactly this:

```json
{"event_type": "object.changed", "event_iri": "urn:sempkm:event:5f0c2d7e-8a51-4c3b-9d7e-1a2b3c4d5e6f", "command": "object.patch", "timestamp": "2026-11-04T09:30:00+00:00"}
```

The receiver uses `event_type` and `event_iri`, and only logs `command` and `timestamp`.
It handles a delivery in this order:

1. **Shape of the body.** A JSON object with string `event_type` and `event_iri` values,
   where `event_iri` starts with `urn:sempkm:event:`. Anything else is a 400.
2. **Event type.** An `event_type` other than the channel's `comm:eventName` is
   **ignored**: answered 202 with nothing started, and logged at info. SemPKM delivers
   every event type the webhook was registered for. A mismatch is a registration that
   asks for more than the channel listens to, not an error.
3. **Read the event back** (section 6). One SPARQL query, with the ADR-0025 service
   token, reads the `sempkm:affectedIRI`s of `<event_iri>` from its event graph, sorted.
   An event SemPKM does not have is **rejected**: 422, logged at warning.
4. **Read the objects** through `SemPKMStore.read(shape, iris)`. That is one query scoped
   to the accepted shape's `sh:targetClass` and paths, exactly as ADR-0025 section 6
   reads. An affected IRI that is not an object of that class (a nested node, an edge, an
   object of another class) drops out. If none remain, the delivery is **ignored**:
   answered 202 with nothing started, logged at info.
5. **Validate** each object's data against the accepted shape. Unlike ADR-0010's copied
   entities, this data was written by people and other apps, and SemPKM validates only
   after commit. An object that does not conform is **skipped**: logged at warning with
   its failing paths, and listed as skipped in the answer. The other objects still start.
6. **Start** each subscribed process (sorted by IRI) once per remaining object (sorted by
   IRI), with `Runtime.start_subscribed` (ADR-0010):
   - **correlation key:** the object's IRI. SemPKM minted it, ADR-0025 section 7 makes it
     the entity's id, and it is the one value that names the object across both systems;
   - **start state:** `current` holds one entry, keyed by the accepted shape's IRI, whose
     `id` is the object's IRI and whose `data` is the validated data. `status` is empty,
     as for a UI-started process. The lifecycle starts from the shape's initial state;
   - **start record:** the instance's state records `{channel, event, object}`, so the
     start can be traced back to the SemPKM event.

The answer is 202 with a JSON body that lists `started` (`{process, instance}`) and
`skipped` (`{object, reason}`), each sorted. The starts are checkpointed before they run
(ADR-0010), so the answer comes after every instance is durable, not after it finishes.

### 5. Idempotence: one start per process, event and object

SemPKM sends one delivery per command, and a forged or replayed delivery (section 6) can
repeat a real event. A process is therefore started **at most once per (process, event,
object)**. Before it starts, the receiver looks for an instance whose start record has
the same three values. If one exists, the receiver starts nothing and lists that existing
instance in `started`. A later change to the same object is a new event, so it starts a
new instance with the same correlation key.

### 6. Authenticity: read the event back, trust no field

SemPKM signs nothing (Context), so no secret can tell a real delivery from a forged one.
The receiver therefore **treats the body as a hint, not as data**:

- the only field it acts on is `event_iri`, and only after the event has been read back
  from SemPKM with the runtime's own service token (step 3);
- the object, its class and its data all come from SemPKM through `SemPKMStore`, never
  from the body;
- a forged event IRI is rejected (422), and a replayed real one starts nothing new
  (section 5).

So a forger who can reach the route can at most make the runtime start the processes a
real SemPKM event would already have started, once. What a forger can still do is spend
the runtime's SPARQL budget (section 9).

No secret is added to the deploy facts, and none goes in the URL. A secret path segment
or query parameter would be the only place SemPKM could carry one. But SemPKM stores
target URLs in a graph and lists them in its admin pages, and the runtime's HTTP server
logs request paths, so the secret would leak in both places. The token the receiver
uses is ADR-0025's `deploy:authenticatesTo` binding. It is sent as a Bearer header and
appears in no log line, error or answer.

When SemPKM signs deliveries (section 11), a binding on the receiving container that
`deploy:authenticatesTo` the channel will carry the verification secret, and a delivery
with a bad signature will be a 401. That is a later ADR, written against SemPKM's
actual signature format.

### 7. The runtime's own writes do not start processes

Every `object.create` and `object.patch` the runtime sends (ADR-0025) makes SemPKM send
`object.changed`, and the delivery cannot say who made the change. SemPKM's `/api/auth/me`
accepts no token, so the runtime cannot learn its own SemPKM user to compare with the
event's `prov:wasAssociatedWith`. So the rule is a model fact checked at load:

- **the accepted shape of a webhook channel must not be `seam:writes` by any element of
  a process the receiving container `seam:executes`.**

A webhook channel listens to changes that people and other apps make in SemPKM: a vendor
added, a contract signed. A model that wants "the runtime changed an expense, start a
process" already has that with ADR-0010's in-process channels. Deliveries for the
runtime's own writes of other classes are still received, and they fall out at step 4.

The receiver also answers within SemPKM's 5 second budget. Because SemPKM awaits the
delivery inside its command request, a runtime write that blocked the runtime's event
loop while it waited for SemPKM would stop the receiver from answering its own
delivery. So the runtime's SemPKM calls must not block the loop that serves the route
(S04/T03).

### 8. Run-time failures

Run-time failures are not resolution errors. Each is answered with problem+json
(ADR-0013) naming the channel, and each is logged with the channel, the event type, the
event IRI and, when there is one, the object IRI. The service token appears in none of
them.

| Case | Answer | Log |
|---|---|---|
| the body is not a JSON object, or lacks a string `event_type` or `event_iri`, or `event_iri` is not a SemPKM event IRI | 400 | warning |
| `event_type` is not the channel's `comm:eventName` | 202, nothing started | info |
| SemPKM has no such event (forged, or from another SemPKM) | 422 | warning, "unverified event" |
| no affected object is of the accepted shape's class | 202, nothing started | info |
| an affected object fails the accepted shape | 202, listed in `skipped` | warning, with the failing paths |
| the process, event and object already started an instance | 202, the existing instance | info |
| SemPKM unreachable, timing out, 429 or 5xx | 503, naming the store container | error |
| SemPKM answering 401 or 403 (a wrong token, a missing `sparql:read` scope, or a token whose user is not an owner, which reading an event graph needs) | 503, naming the store container | error, naming the scope and the owner role |
| SemPKM answering with no SPARQL results | 502, naming the store container | error |
| a subscriber that cannot start (ADR-0010's failure isolation) | 202, listed in `started` with `instance: null` and the error | exception |

SemPKM only logs the status it gets back and never retries, so a 503 is not redelivered.
A change missed while the runtime or SemPKM was down is not replayed. Section 11
records this as an open point.

### 9. Load

Each delivery costs the runtime two `POST /api/sparql` queries (step 3 and step 4).
SemPKM limits that endpoint to 60 requests a minute per client, and the runtime's own
reads (ADR-0025 section 6) share the limit. Since SemPKM sends a delivery for every
`object.changed`, including the runtime's own writes of other classes (section 7), the
limit is reached first, at around 30 deliveries a minute. Past it SemPKM answers 429,
which is a 503 here (section 8) and a missed start. The receiver does not queue or retry:
SemPKM's limits are deployment facts the model does not hold. A busier deployment needs
SemPKM to filter by class or name the objects in the payload (section 11), which would
remove both queries.

### 10. Resolution errors

Resolution happens at `Runtime.load`, before any request is served, as in ADR-0011 and
ADR-0025. The facts of sections 2 and 7 raise `seams.errors.ResolutionError(subject,
predicate, detail)`. The FastAPI generator checks the same facts and raises
`GeneratorError` naming the same subject and predicate, so a model that fails here
generates nothing.

| Case | `subject` | `predicate` |
|---|---|---|
| a webhook channel with no `comm:eventName`, more than one, or one other than `"object.changed"` | the channel | `comm:eventName` |
| a webhook channel with no `seam:acceptsShape`, or more than one | the channel | `seam:acceptsShape` |
| the accepted shape is not `seam:storedIn` a `deploy:SemPKM` store | the shape | `seam:storedIn` |
| the accepted shape has no `sh:targetClass` | the shape | `sh:targetClass` |
| a webhook channel with no `comm:path`, more than one, or a template with a `hydra:mapping` | the channel | `comm:path` |
| two webhook channels of one container with the same `comm:path` template | the container | `comm:path` |
| a webhook channel that no container `seam:exposes`, or more than one does | the channel | `seam:exposes` |
| a webhook channel with no channel-started process subscribed to it | the channel | `seam:subscribesTo` |
| a process subscribed to a webhook channel that the receiving container does not `seam:executes` | the container | `seam:executes` |
| a message throw event or task that `seam:publishesTo` a webhook channel | the channel | `seam:publishesTo` |
| the receiving container has no binding that `deploy:connectsTo` the accepted shape's store | the container | `deploy:connectsTo` |
| the receiving container has no token binding for that store, or more than one, or one whose value is not a secret | the container | `deploy:authenticatesTo` |
| the accepted shape is `seam:writes` by an element of a process the receiving container executes | the shape | `seam:writes` |
| a webhook channel with more than one `comm:transport` | the channel | `comm:transport` |

ADR-0010's resolver `subscribed_processes(channel)` answers the subscribers. S04/T02 adds
the resolvers for the facts above beside it in `ModelGraph`, with sorted results.

### 11. Open points

These are facts the model cannot express, or that SemPKM does not offer yet. None is
hard-coded around.

- **Delivery inside a compose network.** SemPKM's SSRF guard refuses private addresses,
  and every compose service address is private. So SemPKM cannot deliver to a receiving
  container on the same compose network until it allows a configured list of internal
  targets. Until then the receiver is exercised by posting SemPKM's payload directly,
  which is what the tests do, or from a SemPKM whose route to the runtime is public.
- **Signatures.** SemPKM signs nothing. When it does, a later ADR adds the verification
  binding of section 6.
- **The object in the payload.** If the payload named the affected objects and their
  classes, steps 3 and 4 would shrink to one class-scoped read. The owner-role need and
  the rate limit of section 9 would also go away.
- **Filters.** SemPKM stores per-webhook class filters but does not apply them. Applied,
  they would stop the runtime's own writes of other classes from being delivered.
- **Registration.** SemPKM creates webhooks only from an owner's browser session. With a
  token API, the runtime or a deploy step could register the channel's route from the
  model.
- **Other event types.** `edge.changed` (which object, along which predicate?) and
  `validation.completed` need their own start-state mapping, so they are faults for now.
- **Missed events.** Deliveries are not retried. Catching up from SemPKM's event log after
  an outage needs a cursor the runtime does not keep.
- **Who made the change.** The event's `prov:wasAssociatedWith` names a SemPKM user, and
  the runtime has no model fact that maps it to an ODRL party. Started instances record
  no actor.

## Alternatives Considered

- **(a) Read the event back with the service token, trust no field. Chosen.** It works
  with what SemPKM sends today, adds no secret, and makes forged deliveries harmless
  (section 6).
- **(b) Check an HMAC signature with a secret from the deploy facts.** Rejected for now:
  SemPKM sends no signature and has no secret to sign with. A check against a signature
  that never arrives would reject every real delivery. It is the planned successor
  (section 11).
- **(c) A secret in the target URL** (a path segment or query parameter). Rejected: SemPKM
  stores and lists target URLs, and request paths are logged, so the secret would leak
  (section 6).
- **(d) Trust the payload.** Rejected: it names no object, and nothing in it can be
  verified.
- **(e) Start a process for the runtime's own writes too, and stop loops at run time.**
  Rejected: a delivery cannot say who made the change, and the runtime cannot learn its
  own SemPKM user with its token. The load-time rule of section 7 needs neither.
- **(f) Answer 202 at once and read the event in the background.** Rejected: SemPKM only
  logs the answer, so this saves nothing on its side. It would hide store failures from
  the answer and from tests, and it would need a queue the runtime does not have.
- **(g) Name the SemPKM store on the channel with a new predicate.** Rejected: the
  accepted shape's `seam:storedIn` already says it, and two facts could disagree.
- **(h) Poll SemPKM for changes.** Rejected: it needs a cursor and a schedule the model
  does not state, and webhooks exist.

## Consequences

- **S04/T02** adds `comm:SemPKMWebhook` to `ontology/comm.ttl` with its SHACL, and the
  resolvers of section 10 to `ModelGraph` beside `subscribed_processes`.
- **S04/T03** adds the receiver to `seams_runtime` (sections 4 to 8), the event read to
  `SemPKMStore`, and the route to the FastAPI generator (section 3). It also takes the
  runtime's SemPKM calls off the event loop (section 7). Its tests post SemPKM's payload
  to a receiver whose SemPKM is an `httpx.MockTransport`. The plan's "bad signature"
  case becomes the unverified event of section 8, because there is no signature.
- **S04/T04** gives tutorial chapter 10 a webhook channel whose accepted shape is a
  class people create in SemPKM and the runtime does not write (section 7), and a
  process that subscribes to it.
- `seam:subscribesTo` now has a publisher outside the runtime. ADR-0010's machinery
  (`start_subscribed`, `Engine.deliver_start`, checkpoint before run) is reused
  unchanged.
- Models with no webhook channel are unchanged.
- **Limit:** a change made in SemPKM while the runtime is down never starts its process
  (section 11).
