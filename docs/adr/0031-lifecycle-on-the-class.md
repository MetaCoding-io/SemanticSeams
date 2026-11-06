# ADR-0031: Lifecycle on the Class — `seam:lifecycle` Names an `owl:Class`, a Shape's Lifecycle Is Derived Through `sh:targetClass`, and a Transition Is a Domain Event That May Publish on a Channel

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M028/S04; backlog B3; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
sections 2 and 3 ("lifecycle on the class or the shape"); decides the open question
**Lifecycle on the class** of [ADR-0022](./0022-ontology-notation.md); builds on
[ADR-0001](./0001-named-graph-partitioning.md), [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0021](./0021-vocabulary-versions.md) and [ADR-0030](./0030-domains-and-bounded-contexts.md)

## Context

`seam:lifecycle` joins a `sh:NodeShape` to the `state:StateMachine` that governs its
instances. It was put on the shape because, until ADR-0022, the shape was the only thing
in the graph that stood for a kind of thing. Since O2 every expense checkpoint declares
its classes (`:Expense a owl:Class`, `:Payment a owl:Class`) in its ontology model, and
each data shape points at one with `sh:targetClass`.

That leaves the lifecycle on the wrong node:

- **A lifecycle belongs to the thing, not to one view of it.** An expense moves from
  draft to submitted whichever shape reads or writes it. Two shapes of one class (a form
  shape and a stored shape) would each need the same `seam:lifecycle`, and nothing stops
  them naming two machines.
- **The DDD note's aggregate is a class.** Section 2 reads an aggregate root as "a shape
  with a `seam:lifecycle`" and section 3 says the lifecycle should move to the class once
  classes exist, with the shape's lifecycle derived through `sh:targetClass`. ADR-0022
  left the move open; ADR-0030 gave the class an owning context, so "whose lifecycle is
  this" now has an answer the shape cannot give.
- **A transition is already an event, with no way to say so.** The derived storm
  (B4, `seams storm`) draws every `state:Transition` a task `seam:fires` as an orange
  domain-event sticky (*Expense submitted*, *Payment scheduled*). It has an IRI
  (`:t_submit`, `:t_schedule`) and a `state:trigger`, but no seam can say that the event
  leaves the process on a channel. Only a `proc:MessageThrowEvent` or a
  `proc:ServiceTask` may `seam:publishesTo` (D046), so a model that wants "payment
  scheduled" on a channel must add a throw event and restate the transition's name in
  its label.

## Decision

### 1. `seam:lifecycle` names a class, and a shape is kept for compatibility

The subject of `seam:lifecycle` is an `owl:Class` (preferred) or a `sh:NodeShape` (kept,
so every existing model loads unchanged). The object stays a `state:StateMachine`.

```trig
<urn:seams:graph:seams> {
    :Expense seam:lifecycle :expense_lifecycle .
    :Payment seam:lifecycle :payment_lifecycle .
}
```

The fact stays in the seams graph (ADR-0001 rule 1): the class is in the ontology model
graph and the machine in its lifecycle model graph, so the edge between them is a
cross-layer fact, as it was between the shape and the machine. No new predicate is added;
`seam:lifecycle`'s comment becomes "owl:Class | sh:NodeShape -> state:StateMachine".

### 2. A shape's effective lifecycle is its own, else its class's

A `sh:NodeShape`'s effective lifecycle is the machine it names with `seam:lifecycle`, or,
when it names none, the machine named by the `owl:Class` it points at with
`sh:targetClass`. Every reader (the views in `packages/seams`, the generators, the
runtime, the viewer, `seams storm`, the review checks) takes the effective lifecycle,
so a model may move the fact from the shape to the class without changing any output.

- **More than one is a violation.** A shape whose direct lifecycle and class lifecycles
  together name more than one machine is refused by a shape that names the shape and
  `seam:lifecycle` and lists the machines. The same shape naming the same machine twice
  (directly and through its class) is one lifecycle, not two.
- **The views raise the same fact.** Reading a shape's lifecycle when the model has two
  candidates is `ResolutionError(<shape>, seam:lifecycle, <sorted machine IRIs>)`, so a
  model that skipped the shapes fails with the fact named.
- **A lifecycle's shapes are derived too.** The shapes a machine governs are the shapes
  that name it, plus every `sh:NodeShape` whose `sh:targetClass` names it, sorted by IRI.
- **The guards follow.** `seam:visibleWhen` and `verify:expectState`, which check that
  a state belongs to the lifecycle of a shape, accept a lifecycle reached through the
  shape's class (`?shape seam:lifecycle|sh:targetClass/seam:lifecycle ?machine`).

### 3. A transition is a domain event and may publish on a channel

A `state:Transition` is a domain event: the fact that an instance of the class moved from
one state to another. It is identified by its IRI, as every element is (ADR-0002), and
may `seam:publishesTo` a `comm:Channel`:

```trig
<urn:seams:graph:seams> {
    :t_schedule seam:publishesTo :payouts .
}
```

- **The event's name is the transition, never a copied label.** A consumer names the
  event by the transition's IRI or by its `state:trigger`; no `rdfs:label` restating
  the transition is added to a throw event or a channel. Renaming the trigger renames the
  event everywhere it is drawn or sent.
- **The shapes widen once.** The `seam:publishesTo` subject shape accepts a
  `state:Transition` beside `proc:MessageThrowEvent` and `proc:ServiceTask`; the object is
  still a `comm:Channel`. D046's rule for processes is unchanged.
- **The storm draws it.** The storm already draws a fired transition as a domain event;
  a transition that publishes is that event leaving on a channel, the same sticky with the
  channel beside it.

### 4. Runtime emission is a follow-up

This ADR decides the facts and their shapes, not delivery. Publishing a message on the
channel when a task fires a publishing transition is a `seams_runtime` change with its
own questions (the payload, ordering against the task's own throw events, a transition
fired by a decision rather than a task) and is left to a later slice. Until then a
transition's `seam:publishesTo` is a modelled fact: checked, drawn and queryable, not
sent.

### 5. `seam` goes to 1.4 as a compatible widening

`ontology/seam.ttl` moves from `1.3` to `1.4`. Widening a subject and adding shapes that
accept every model that conformed before is a compatible change under
[ADR-0021](./0021-vocabulary-versions.md) section 7, so there are no migration files and
a model declaring `seam` `1.3` or older loads unchanged. The new shapes are:

| Shape | Checks |
|---|---|
| `LifecycleShape` | the subject of `seam:lifecycle` is an `owl:Class` or a `sh:NodeShape`, and its object is a `state:StateMachine` |
| `EffectiveLifecycleShape` | a `sh:NodeShape` has at most one effective lifecycle, counting its own and that of each `sh:targetClass` |
| `PublishesToShape` | the subject of `seam:publishesTo` is a `proc:MessageThrowEvent`, a `proc:ServiceTask` or a `state:Transition` |

Chapter 9 of the expense tutorial moves its two lifecycles onto `:Expense` and `:Payment`
and its generated outputs stay byte-identical (apart from the model hash), which is the
proof that the derivation is complete. The other chapters and the chat app keep the
shape form as the proof that it still works.

## Alternatives considered

- **Move the lifecycle and drop the shape form.** Rejected: every checkpoint and the
  chat app would need a migration for a change that adds nothing to them, and the chat
  app's shapes have no classes yet. The shape form costs one `sh:or` branch.
- **A new predicate for the class (`seam:classLifecycle`).** Rejected: it would be the
  same fact under two names, and every reader would need to read both. One predicate with
  a wider subject keeps one question ("what governs this?") one triple pattern.
- **Inherit through `rdfs:subClassOf`.** Not now: no model has a class hierarchy with a
  lifecycle, and a subclass that changes its parent's machine is a design question
  (refine or replace) with no example to decide it. A shape's class lifecycle is read
  from its `sh:targetClass` only.
- **A `seam:DomainEvent` class, or a throw event per transition.** Rejected: the
  transition already has an IRI, endpoints and a trigger, so a second node would restate
  it and could disagree with it. Publishing from a throw event remains for completion
  events of a process (D046).
- **Name the event by the channel's `comm:eventName`.** Rejected for a transition: one
  channel may carry several transitions' events, so the channel cannot name them; the
  channel's `comm:eventName` still names how it reaches a client.

## Consequences

- `seam` becomes `1.4`; models on older versions load unchanged.
- Every reader of a shape's lifecycle goes through the derived view, so the generators,
  the runtime and the viewer see the same machine whichever node carries the fact.
- The DDD profile (B5) can state "one lifecycle per aggregate" on the class, and X7's
  aggregate boundary gets the class it hangs on.
- The storm and the context map (B2) can show a domain event crossing a context boundary
  on a channel without a throw event added for it.
- Delivering those events at run time is a follow-up (section 4).

## Open questions

- **Runtime emission.** What the message carries (the instance's key, the from and to
  states, the trigger) and when it is sent relative to the task's own effects.
- **Lifecycles across a class hierarchy.** Whether a subclass inherits, refines or
  replaces its parent's lifecycle, once a model has one.
