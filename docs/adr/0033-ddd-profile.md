# ADR-0033: The DDD Profile — `seams check` Validates an Attached Profile's Shapes, the DDD Rules Are SHACL in `profiles/ddd`, and a Type Pill Is a Labelled `sh:Info` Shape's Conforming Focus Nodes

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M029/S02; backlog B5; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
section 5; amends [ADR-0018](./0018-domain-profiles.md) ("Preview" and its
implementation notes); builds on [ADR-0030](./0030-domains-and-bounded-contexts.md),
[ADR-0031](./0031-lifecycle-on-the-class.md) and
[ADR-0032](./0032-context-map-relationships.md)

## Context

The DDD note ends with a design: the tactical taxonomy gets no classes, and "we follow
DDD" becomes a machine-checkable claim by attaching a shapes library with
`seam:conformsTo`. ADR-0030 and ADR-0032 have since given the graph the facts that
library needs: bounded contexts that `seam:own` models, and context relationships with an
upstream, a downstream and a type. ADR-0031 put the lifecycle on the class, which is
where the note says the aggregate root lives.

ADR-0018 built the profile mechanism for the editor, and decided three things this
profile cannot live with as they stand:

- **`seams check` ignores profiles.** A profile's shapes show only in the viewer's
  health panel. A claim that only the viewer checks is not checked in CI, which is
  where "we follow DDD" has to hold.
- **The resolver is the viewer's.** `resolve_profile` is in `viewer/profiles.py`, and
  the CLI may not import the viewer.
- **A profile adds no labels to elements.** It labels the classes it offers, but the
  note wants an aggregate, a command or a domain event shown as such in the viewer,
  as a derived pill, never as an `rdf:type` triple.

Two of the note's rules are already gate queries (`gates/ungoverned-writes.rq`,
`coverage/unfired-transitions.rq`), and ADR-0032 added a third
(`gates/untranslated-cross-context-calls.rq`). A profile that restates them is a second
source for the same fact, which principle 1's spirit (one fact, one place) argues
against.

## Decision

### 1. `seams check` validates the attached profile; `seams generate` still ignores it

This amends ADR-0018's "Preview" bullet, which said `seams generate` and `seams check`
ignore profiles. `seams generate` still does: a profile narrows what the editor previews
and what the model claims, never what the project builds. `seams check` now:

- **Resolves the profile** from the model directory with the same resolver the viewer
  uses (section 5), by ADR-0018's rules. A model with no `seam:conformsTo` reads no
  profile file and its output is unchanged, byte for byte.
- **Validates the model with the profile's shapes.** The graph is the one the `shacl`
  check already validates (the model unioned with `ontology/*.ttl`, inference off); the
  shapes graph is the profile's, the union of its `seam:profileShapes` files. The seam
  shapes are not merged in, because the `shacl` check already reports their results and
  a result must be reported once. (The viewer's health panel keeps ADR-0018's merge: it
  shows one list, so it reports each result once too.)
- **Prints the profile and its result count**, one line on standard output before the
  findings: `profile <IRI> <n> result(s)`, where `n` counts the results it reports
  below. The line is not a finding and does not change the exit code.
- **Reports each result as a finding.** A `sh:Violation` result is a `profile` finding,
  a problem that fails the check. A `sh:Warning` or a non-pill `sh:Info` result is a
  `profile-warning` finding, advisory like `shacl-warning`. The detail is the focus
  node, the result path and the message, as `shacl` findings are, sorted with every
  other finding. Results of pill shapes (section 4) are not reported.
- **Reports an unresolvable profile as the fact.** A `ResolutionError` from the resolver
  is a `profile` finding whose detail is the error's subject, predicate and detail, so
  `seams check` fails naming `seam:conformsTo` or `seam:profileShapes`. The viewer still
  carries on without the profile (ADR-0018); check fails because a claim it cannot load
  is a claim it cannot check.

### 2. The rules are SHACL in the profile's shapes files

The DDD profile is a shapes library and nothing else: no new term (principle 4), no
code that knows a DDD name. A rule core SHACL can state is core SHACL; a rule that needs
a join across models is a `sh:sparql` constraint whose `sh:select` binds `$this` and
whose `sh:message` names the fact. Each rule is one `sh:NodeShape` with `sh:severity
sh:Violation`. The rules, over the terms the graph already has:

| Rule | Focus nodes | Constraint |
|---|---|---|
| **Governed writes**: every UI event that can write a shape is governed by a policy | `sh:targetClass ifml:Event` | `sh:sparql`: the walk of `gates/ungoverned-writes.rq` from `$this` to a writer, with no `seam:governedBy` on the event or the operation it submits to |
| **Fired transitions**: every transition is fired by something | `sh:targetClass state:Transition` | `sh:sparql`: the body of `coverage/unfired-transitions.rq` with `?transition` bound to `$this` (see the note below the table) |
| **Translated access**: a cross-context `seam:reads` or `seam:writes` is translated unless the relationship is conformist or a shared kernel | `sh:targetSubjectsOf seam:reads`, `sh:targetSubjectsOf seam:writes` | `sh:sparql`: ADR-0032 section 4's rule, the body of `gates/untranslated-cross-context-calls.rq` with `?element` bound to `$this` |
| **One writing context**: a shape is written only from the context that owns it, so never from two | `sh:targetObjectsOf seam:writes` | `sh:sparql`: a writer of `$this` whose `seam:inModel` model is owned by a context that does not own `$this`'s model |
| **Aggregate boundary**: an aggregate has one lifecycle, one correlation key and one store | `sh:targetSubjectsOf seam:lifecycle` | `sh:sparql`, one constraint per fact, below |

*Implementation note (M029/S02/T03).* The fired-transitions rule was first written
as the core constraint `sh:property [ sh:path [ sh:inversePath seam:fires ] ; sh:minCount
1 ]`. It is a `sh:sparql` constraint instead, for two reasons: a core result on an
inverse path carries a blank-node `sh:resultPath`, which `seams check` would print as a
different identifier on every run; and the query joins `seam:inModel ?lifecycle`, so
the SPARQL form reports exactly the query's rows. Every DDD rule is therefore
`sh:sparql`.

An **aggregate** is what ADR-0031 and the note make it: the `owl:Class` that
`seam:lifecycle` names (or, kept for compatibility, a `sh:NodeShape` that names one
directly). Its **shapes** are itself when it is a shape, and every `sh:NodeShape` whose
`sh:targetClass` is it. The aggregate-boundary constraints are:

- **one lifecycle**: `$this` names exactly one `state:StateMachine` with
  `seam:lifecycle`. (ADR-0031 already refuses a shape with two effective lifecycles; this
  states it on the aggregate.)
- **one store**: its shapes are `seam:storedIn` exactly one store between them, so the
  aggregate is in one repository;
- **one correlation key**: the processes whose elements write one of its shapes (a
  writer `seam:inModel` a model the process is `seam:detailedBy`) state exactly one
  distinct `proc:correlationKey` between them, so every instance that changes the
  aggregate is keyed the same way.

A rule with no facts to read holds: a dataset with no `arch:BoundedContext` has no
cross-context access and no owner to disagree with, and a model with no lifecycle has no
aggregate. Every message names the focus node's fact: the predicate and the other IRIs
the constraint found (the writer and the two contexts, the stores, the keys), as every
seam shape does. `sh:sparql` prefixes are declared once in the shapes file with
`sh:declare` on the shapes graph's `owl:Ontology` and referenced by `sh:prefixes`.

The note's sixth rule, "every domain event a channel publishes has a published shape in
a versioned ontology", is left out: a transition that `seam:publishesTo` a channel
(ADR-0031 section 3) is new, and runtime emission is still a follow-up, so the rule has
no example to be checked against yet. It is added to the profile with its first one.

#### The gate queries stay, and a project checks a fact once

The three bundled rules restate three gate queries. Making the `.rq` file the only
source would need either a profile term that names gate files (a new term, and gate rows
carry no severity, message or focus node for the health panel), or SHACL-AF's SPARQL
targets, which tie the profile to one engine's extension. Neither is earned. So:

- **The `.rq` files are the catalog**: the question for a project that attaches no
  profile, and for the viewer's question buttons. They are unchanged.
- **The profile's constraint is the same query anchored on `$this`.** Its `sh:select`
  keeps the `.rq`'s walk and filters in the same order, and the shapes file names the
  `.rq` it restates in a comment.
- **A parity test pins the two together** (M029/S02/T03): on chapter 11 and on each
  negative fixture, the focus nodes a bundled rule reports are the values of the
  corresponding `.rq` variable (`?event`, `?transition`, `?element`). A change to one that
  is not made to the other fails CI, the way the bundled `seams` copies of the `.rq` files
  are pinned byte-identical today.
- **A project that attaches the profile drops the gates it bundles** from `gates` in its
  `seams.toml`, so one run reports one fact once. Chapter 11 does (T03); chapters 7 to 10
  keep their gates and attach no profile.

### 3. `profiles/ddd` lives beside chapter 11

The profile is `examples/expenses/chapter-11/profiles/ddd/`, by ADR-0018's convention
(a `profiles/<name>/` directory beside the loaded model): `profile.ttl` declares the
`seam:Profile` with `seam:profileShapes "ddd-shapes.ttl"`, and `ddd-shapes.ttl` holds
the rules and the pill shapes. Its IRI is `<https://example.org/profiles/ddd>`, and
chapter 11's seams graph states `<urn:seams:graph:manifest> seam:conformsTo
<https://example.org/profiles/ddd>`: the subject is the manifest's `owl:Ontology`, the
one node that stands for the whole dataset rather than one of its models. The profile offers no classes and lists no
generators, so the editor's palette and preview behave as they do with no profile: a
profile with no `seam:offersClass` restricts nothing (ADR-0018's "no profile means no
change" holds for each part the profile leaves out).

It is an example, not a library the tool ships: a profile is the model directory's, and
the tool reads no profile from anywhere else. A second project that wants it copies the
directory; a shared profile directory is a question for when two projects need one.
The profile is outside the model (ADR-0018): the `seam:conformsTo` triple changes the
model hash once, and editing the profile's files changes no hash.

### 4. A type pill is a labelled `sh:Info` shape's conforming focus nodes

A **pill shape** is a `sh:NodeShape` in the profile's shapes graph with `sh:severity
sh:Info` and a `skos:prefLabel` or `rdfs:label` (`skos:prefLabel` wins, as in ADR-0018).
Its pill is shown on every node that is a **focus node of the shape and conforms to it**:

- the focus nodes are the shape's standard targets (`sh:targetNode`, `sh:targetClass`
  with `rdfs:subClassOf` over the data graph, `sh:targetSubjectsOf`,
  `sh:targetObjectsOf`);
- a focus node conforms when validating the shape reports no result for it. The
  constraints narrow the targets: "a `sh:NodeShape` with an effective lifecycle" is
  `sh:targetClass sh:NodeShape` with a `sh:sparql` constraint that reports a shape with
  none.

So the DDD profile labels an aggregate (a shape or class with an effective lifecycle),
a command (an operation with a `seam:acceptsShape` that a `seam:submitsTo` reaches), and
a domain event (a `state:Transition`, and a `comm:Channel` with a `seam:acceptsShape`)
from its own shapes file, with its own labels. No `rdf:type` triple is added to the model,
and no code holds a pill name: the viewer computes the pills in Python from the shapes
graph, sorts them by label then IRI, and the template renders the list.

Pill shapes' results are informational by construction (the non-conforming targets), so
neither `seams check` nor the health panel reports them. A shape with `sh:Info` and no
label is an ordinary informational rule and is reported as a `profile-warning`.

### 5. `resolve_profile` moves to `packages/seams`

`resolve_profile(ds, model_dir)` and `Profile` move from `viewer/profiles.py` to
`packages/seams/src/seams/profiles.py` and are exported from `seams`. The resolver reads
files and parses Turtle with rdflib only, so it keeps the library's rules: rdflib and lxml
only, read-only, pyright-strict. It does not validate; the CLI and the viewer each run
pyshacl with the shapes graph it returns. `viewer/profiles.py` becomes a re-export so the
viewer's callers and tests are unchanged.

## Alternatives considered

- **`seams check` merging the profile's shapes with the seam shapes.** Rejected: every
  seam-shape result would be reported twice, once as `shacl` and once as `profile`.
- **Profiles failing `seams generate`.** Rejected, as ADR-0018 rejected it: generation
  is what `seams.toml` says, and a profile is a claim about the model, not a build input.
- **`ddd:Aggregate`, `ddd:Command`, `ddd:DomainEvent` classes, or a pill term.** Rejected
  by the note (section 5) and principle 4: each restates facts the graph derives, and a
  stated type can disagree with the facts it summarises. A label on a shape already says
  what a pill is called.
- **A `seam:profileGate` term naming `.rq` files the profile runs.** Rejected: a new term
  for a second mechanism, whose rows have no severity, message or focus node for health.
- **SHACL-AF SPARQL targets** (`sh:target [ a sh:SPARQLTarget ]`) to reuse the `.rq`
  text as a target. Rejected: an extension beyond SHACL core and SHACL-SPARQL, and the
  `.rq` text still needs rewriting to bind `$this`.
- **Deleting the gate queries.** Rejected: projects with no profile, chapters 7 to 10 and
  the viewer's questions use them.
- **Pill shapes marked by a new predicate, or by `sh:deactivated true`.** Rejected: a new
  term is not needed when `sh:Info` plus a label already says "this is a description,
  not a rule", and a deactivated shape has no conforming focus nodes to compute.

## Consequences

- `seams check` gains the `profile` and `profile-warning` finding kinds and, for a model
  with a profile, one `profile <IRI> <n> result(s)` line (M029/S02/T02). Models with no
  profile, `seams generate` and every committed output are unchanged.
- `seams.resolve_profile` and `seams.Profile` are public names of the library;
  `viewer/profiles.py` re-exports them (T02).
- Chapter 11 attaches `profiles/ddd`, its seams graph gains one triple (so its model hash
  and generated outputs are regenerated), and its `seams.toml` drops the two gates the
  profile bundles (T03).
- The viewer shows derived DDD pills and the profile's violations in health (T04).
- Context Mapper import and export, the rest of B5, is M029/S03.

## Open questions

- **A shared profile directory.** A profile lives in one model directory. When two
  projects attach the same profile, it may need a project-declared search path, as
  ADR-0022 left for shared ontologies.
- **The published-event rule.** Section 2's sixth rule waits for a channel-published
  transition in an example.
