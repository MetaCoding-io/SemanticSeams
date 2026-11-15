# ADR-0040: External Systems and Inbound Webhooks — `arch:external true` Marks an `arch:System` the Model Neither Builds Nor Runs; Its Containers and Operations Are External by Derivation, and an Inbound Webhook Is a Channel Whose Sender Is One of Its Containers

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M031/S02; backlog X4 (and O6, which it restates); research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.7
("External systems"); builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0011](./0011-storage-resolution.md),
[ADR-0012](./0012-operation-implementation.md),
[ADR-0015](./0015-environments.md),
[ADR-0021](./0021-vocabulary-versions.md),
[ADR-0025](./0025-sempkm-store.md),
[ADR-0027](./0027-sempkm-webhook-channel.md) and
[ADR-0032](./0032-context-map-relationships.md)

## Context

The UML note's section 3.7 found that the model has no way to say "someone else runs
this". Every `arch:Container` an `arch:System` contains is something the generators
build or deploy: the compose generator writes a service for it, the FastAPI and htmx
generators write code for the containers that execute or present a model, and
`impact-of-node.rq` walks through it. The note's suggestion was "probably `arch:System`
with operations marked external".

Two places in the examples already lean on a third party:

- **The LLM provider** in the chat app is modelled as a gateway container,
  `:llm_gateway`, that the model does run (an image of its own). The provider behind it
  is not in the graph at all. That is fine: the model runs the gateway, and the gateway's
  upstream is its own configuration.
- **SemPKM** in chapters 10 and 11 of the expense tutorial. `:expense_pkm` is a
  `deploy:SemPKM` store (ADR-0025) and `:expense_triplestore` is its triplestore. Both
  are contained by `:expense_system`, so the compose generator writes their services
  from their own images, ports and volumes. SemPKM is a separate product, though: it has
  its own project, its own releases and its own deployment, and its image cannot be
  pulled from the model's registry. Its webhook (ADR-0027, backlog O6) is the one inbound
  call from outside the model that the runtime receives.

What a third party offers falls into two kinds, and both need one convention:

- **Outbound calls:** the model's processes call an API someone else runs (a payment
  API, an email service, SemPKM's command and SPARQL endpoints).
- **Inbound webhooks:** someone else's system calls a route of the model's container
  when something happens on its side. ADR-0027 decided one such case in full, SemPKM's
  `object.changed`, and left the general shape open.

Principle 4 says vocabulary is earned. The model already says almost everything:
`arch:System` and `arch:Container` for the third party's parts, `seam:exposes` for its
operations, `deploy:connectsTo` and `deploy:authenticatesTo` (ADR-0011, ADR-0025) for how
the model's containers reach it, and a `comm:Channel` with an inbound transport for a
webhook. What is missing is one fact: that a system is not the model's to build or run.

## Decision

### 1. `arch:external true` marks a system the model neither builds nor runs

`arch:external` is a new property in `ontology/arch.ttl`:

- **Domain `arch:System`, range `xsd:boolean`.** It is stated at most once, and only as
  `true`. Leaving it out says the system is the model's own; `false` would be a second
  way to say the same thing, so the shapes refuse it (section 6).
- **It lives in the architecture model graph**, beside the system it describes. It is an
  `arch:` fact about an architecture element, not a seam between two models, so
  ADR-0001's rule for `seam:` predicates does not apply.
- **An external system is still an `arch:System`.** It has an IRI under ADR-0002, a
  label, `arch:technology` and `arch:description`, and it may `arch:contain` containers.
  The C4 views show it as a system at L1 and roll its containers up into it, as for any
  system; the viewer marks it as external.
- **`arch` moves from 1.2 to 1.3**, a compatible widening under ADR-0021 section 7: one
  added property and new shapes that fire only on models that use it. No migration file.

```trig
:sempkm a arch:System ; rdfs:label "SemPKM" ;
    arch:external true ;
    arch:technology "SemPKM" ;
    arch:contains :expense_pkm , :expense_triplestore ;
    seam:inModel :expense_architecture .

:expense_pkm a arch:Container ; rdfs:label "Expense Knowledge Store" ;
    arch:technology "SemPKM" ;
    deploy:storeKind deploy:SemPKM ;
    arch:dependsOn :expense_triplestore ;
    seam:inModel :expense_architecture .
```

### 2. Its containers and operations are external by derivation, never by a second marker

The marker is stated once, on the system. Everything else follows from it:

- **An external container** is an `arch:Container` that an external system
  `arch:contains`. It is contained by no other system (section 6). It keeps the facts the
  model's own containers need to reach it: its label, `arch:technology`,
  `deploy:storeKind` (the runtime reads a SemPKM store's kind, ADR-0025),
  `arch:dependsOn` inside its own system, and `seam:exposes`.
- **An external operation** is a `hydra:Operation` or `comm:Channel` that an external
  container `seam:exposes`: an endpoint of the third party's API. A process of the model
  calls it as ADR-0012 already allows, with `seam:implementedBy [ a comm:HTTPEndpoint ]`
  on the operation and a binding on the executing container that carries the base URL.
- **No marker on the operation.** Stating "external" on each operation as well as on its
  system would give one fact two sources that could disagree. The typed view (S02/T02)
  answers "is this operation external?" from the exposing container's system.

### 3. Generators emit no code, no image and no service for an external system

An external system is in the graph so that the model can name what it talks to. Nothing
of it is generated:

- **The compose generator** writes no service, volume, secret or healthcheck for an
  external container, and does not count an external system among "the model's one
  `arch:System`": that rule now reads as one system that is not external. ADR-0025
  section 10's pull-in of SemPKM containers that the system does not contain skips
  external containers too.
- **The FastAPI, htmx and Dockerfile generators** write no code and no image for an
  external container. An external container `seam:executes` and `seam:presents`
  nothing, so they would have nothing to write; the shapes say so explicitly.
- **Bindings to an external container carry their own URL.** A binding that
  `deploy:connectsTo` or `deploy:authenticatesTo` an external container keeps its
  `deploy:value`, `deploy:secretRef` or `deploy:secretFile`, as today. A
  `deploy:serviceOf` binding cannot name one: it derives the URL from a compose service
  name, and an external container has no service.
- **No `depends_on` on an external container.** A `deploy:dependsOn` from a container of
  the model to an external one would be a compose `depends_on` naming a service that
  does not exist.
- **What the model hands to the third party is still generated.** The SemPKM mental
  model package (ADR-0026) describes the model's own data; an owner installs it into
  SemPKM. It is an artifact of the model's shapes, not code of the external system, so
  it is generated as before.

Where a generator would otherwise write a dangling reference (a `depends_on` or a
`deploy:serviceOf` URL), it raises `GeneratorError` naming the same subject and predicate
as the shape in section 6, with a parity case (principle 5).

### 4. Impact queries stop at the boundary and report the system

`impact-of-node.rq` walks `arch:dependsOn`, `seam:consumes/^seam:exposes`,
`^seam:executes` and `seam:storedIn` from the containers deployed to a node. An external
system changes the walk in two ways:

- **It never starts a walk.** An external container is `seam:deployedTo` no node
  (section 6): the model does not say where the third party runs it.
- **It stops a walk and is reported as the system.** When the walk reaches an external
  container (a SemPKM store a shape is `seam:storedIn`, an operation an external
  container exposes), the result lists the external **system** once, not its
  containers, and the walk does not continue through it. What the third party depends
  on is not the model's to report, and listing its containers would count parts the
  model neither runs nor knows in full.

The same rule holds for any other query or measure that counts containers: it counts the
model's own containers only, and an external system as one system.

### 5. An inbound webhook is a channel the model exposes and an external container sends

The general convention, of which ADR-0027 is one case:

- **The channel is the model's.** A `comm:Channel` that a container of the model
  `seam:exposes`, at a `comm:path` on that container, with a `comm:transport` value that
  names the sender's delivery format. That transport is **inbound**: no process
  `seam:publishesTo` the channel.
- **The sender is an external container.** The transport's own ADR says which container
  sends the channel's deliveries, and that container is in an external system. The
  channel is bound to the external system through that container; no new predicate
  joins them.
- **The sender's format decides the rest.** Each sender has its own payload, event types
  and authenticity story (a signature, a shared secret, or none). So each inbound sender
  gets its own `comm:Transport` value and its own ADR, written against what the sender
  actually sends, as ADR-0027 was. There is no generic `comm:Webhook` transport.

ADR-0027 restated under this convention: `comm:SemPKMWebhook` is an inbound transport;
the receiving container `seam:exposes` the channel; the sender is the `deploy:SemPKM`
store that the channel's accepted shape is `seam:storedIn` (ADR-0027 section 2, still the
single source of that fact); and that store is a container of an external system, so in
chapters 10 and 11 `:expense_pkm` and `:expense_triplestore` move from `:expense_system`
into an external `:sempkm`. Nothing in ADR-0027's route, payload handling, idempotence,
authenticity or failure table changes.

### 6. Shape rules and errors

New shapes in `ontology/shapes/seam-shapes.ttl`, section "External systems (ADR-0040)".
Each violation is on the subject named, with the result path named, and `Runtime.load`
and `seams check` report the same facts as `ResolutionError(subject, predicate, detail)`:

| Shape | Target | Rule | Subject | Path |
|---|---|---|---|---|
| `seamsh:ExternalMarkerShape` | every subject of `arch:external` | the subject is an `arch:System`, the value is `true` and is stated once | the subject | `arch:external` |
| `seamsh:ExternalContainmentShape` | every container an external system `arch:contains` | no other `arch:System` contains it | the container | `arch:contains` |
| `seamsh:ExternalContainerShape` | every container an external system `arch:contains` | it carries no `deploy:artifact`, `deploy:override`, `deploy:port`, `deploy:volume`, `deploy:healthcheck`, `deploy:configuration`, `deploy:placement`, `deploy:proxies` or `deploy:dependsOn`, and is the subject of no `seam:executes`, `seam:presents`, `seam:schedules` or `seam:deployedTo` | the container | the offending predicate |
| `seamsh:ExternalReachShape` | every container of the model | it has no `deploy:dependsOn` to an external container, and none of its bindings is a `deploy:serviceOf` an external container | the container | `deploy:dependsOn` or `deploy:serviceOf` |

A model with no `arch:external` triple triggers none of them, which is why the shape
change is compatible under ADR-0021.

## Alternatives considered

- **A class, `arch:ExternalSystem`, a subclass of `arch:System`.** Rejected: nothing in
  the library infers types, so every reader of `arch:System` would have to look for two
  classes, and a node typed as both would say the same thing twice. A property on the
  class the readers already know is one fact in one place.
- **The marker on each operation as well as on the system**, as the research note
  sketched. Rejected: the system decides it, and a second copy on each operation could
  disagree with the first (section 2).
- **External systems with no containers**, the operations `seam:exposes`d by the system
  itself. Rejected: `seam:exposes` is a container fact, ADR-0025's store kind is a
  container fact, and widening both to systems would change two vocabularies to say what
  containment already says.
- **A new predicate from the channel to its sender** (say, `seam:sentBy`). Rejected for
  ADR-0027's channel, whose sender is already derived from the accepted shape's store; a
  second fact would be a second source. A later inbound transport whose sender cannot be
  derived may need one, decided in its own ADR.
- **A generic `comm:Webhook` transport.** Rejected: senders differ in payload and in how
  a delivery is authenticated, and a generic transport would leave both to code (section
  5).
- **Keeping SemPKM inside `:expense_system`.** Rejected: the model would keep claiming
  to build and run a product it does not own, with an image it cannot pull.

## Consequences

- `arch` is 1.3. The arch vocabulary page and the architecture concepts page describe
  `arch:external` (S02/T02, S02/T03).
- `packages/seams` gains a typed view of external systems, containers and operations
  (S02/T02), so the generators and the runtime read the fact one way.
- Chapters 10 and 11 model SemPKM as the external `:sempkm` system. Their compose files
  lose the SemPKM and triplestore services; the API's `deploy:dependsOn :expense_pkm` is
  dropped, and its `SEMPKM_URL` binding names the SemPKM deployment the operator runs.
  A developer runs SemPKM from SemPKM's own project, as chapter 10 already has to, since
  the image the model named cannot be pulled.
- The C4 L1 view of chapters 10 and 11 shows two systems, Expense Approval depending on
  SemPKM, instead of hiding SemPKM inside the expense system.
- `impact-of-node.rq` lists SemPKM as one impacted system where it listed its containers.

## Open questions

- **Outbound calls to an external operation at run time.** ADR-0012's
  `comm:HTTPEndpoint` takes its base URL from a `deploy:serviceOf` binding, which section
  3 refuses for an external container. Calling a third-party API from a service task
  needs the base URL from a `deploy:value` or secret binding instead, and an
  authentication rule; that is runtime work for a later slice.
- **How a context relates to an external system.** ADR-0032's relationships join two
  bounded contexts. A third party's API is usually a conformist or anti-corruption-layer
  relationship, but an external system owns no context. Whether an external system may
  stand on one side of an `arch:ContextRelationship` is left to B5's profile work.
- **A model that runs its own copy of a third-party product.** Such a container stays in
  the model's own system, built from its image, as the LLM gateway is. Whether its
  inbound webhooks (a self-hosted SemPKM's) follow section 5 with a sender that is not
  external is left until a model needs it.
- **Other inbound senders.** Each needs its own transport and ADR (section 5); none is
  planned.

## Revision notes

- 2026-11-15 (S02/T03 follow-up): section 4's second rule, "it stops a walk and is
  reported as the system", is replaced by a shape. Section 2 already keeps an external
  container's `arch:dependsOn` inside its own system and gives it no `seam:consumes`.
  Those are the only two edges that could lead a walk out of an external container to a
  container of the model, since it executes nothing and is not a shape.
  `seamsh:ExternalBoundaryShape` now refuses both, on the container, with the path
  `arch:dependsOn` or `seam:consumes`. So no dependency path from the model's elements to
  a node passes through an external container, and `impact-of-node.rq` walks as before
  ADR-0040, with no boundary clause. A SPARQL property path cannot exclude intermediate
  nodes, so a boundary clause in the query had to drop every element that a path
  through an external container also reached, even one that depended on the node
  directly. The shape makes the result exact. Its consequence for chapters 10 and 11 is
  that SemPKM is not listed among what `:db01` takes down: nothing of it runs there.
