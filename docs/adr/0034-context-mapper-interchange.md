# ADR-0034: Context Mapper Interchange — `seams cml export` Writes the Context Map as CML, and `seams cml import` Adds the Relationships It Can Map and Flags the Rest

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M029/S03; backlog B5; research note
[Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md);
builds on [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0017](./0017-write-path-and-editor.md),
[ADR-0030](./0030-domains-and-bounded-contexts.md) and
[ADR-0032](./0032-context-map-relationships.md)

## Context

ADR-0030 and ADR-0032 put bounded contexts and the relationships between them in the
architecture model. Teams that do DDD often draw their context maps in
[Context Mapper](https://contextmapper.org/), whose Context Mapper DSL (CML) has a
`ContextMap` block of relationships between `BoundedContext`s, written with
upstream and downstream role brackets:

```text
ContextMap {
  contains LocationContext, CargoBookingContext
  LocationContext [U,OHS,PL]->[D,ACL] CargoBookingContext : CargoLocationRelationship
}
```

Backlog B5 asks for a way to move a context map between the two: export the graph's map
to CML so the Context Mapper tools (diagrams, refactorings) can read it, and import a
map drawn there so the graph does not have to be retyped.

The two vocabularies do not match one to one. CML has roles per end (the upstream offers
an open host service or a published language; the downstream conforms or builds an
anti-corruption layer) and a partnership; ADR-0032 keeps one type per relationship,
folds open host service into published language, and has no partnership. CML also holds
much more than a context map: aggregates, entities, services, teams, use cases. The
graph has its own facts for those, read from BPMN, DMN and SHACL, and a second source
would contradict principle 1.

## Decision

### 1. A context is a CML `BoundedContext` named by its IRI's local name

Each `arch:BoundedContext` in the model is exported as `BoundedContext <name>`, with no
body, where `<name>` is the local name of its IRI (`:expense_context` becomes
`expense_context`). ADR-0002 IRIs end in a local name that is already a valid CML
identifier. The label, the domain and the owned models are not exported: CML's
`BoundedContext` attributes (`domainVisionStatement`, `implements`, `type`) do not say
the same thing as `rdfs:label`, `arch:contains` or `seam:owns`, and a guessed mapping
would be a second meaning for one fact.

### 2. A relationship is a CML relationship with a fixed bracket form per type

Each `arch:ContextRelationship` is one line in the `ContextMap`, upstream on the left,
named by the relationship IRI's local name with CML's `: <name>` suffix:

| `arch:relationshipType` | CML |
|---|---|
| `arch:CustomerSupplier` | `<up> [U,S]->[D,C] <down> : <name>` |
| `arch:Conformist` | `<up> [U]->[D,CF] <down> : <name>` |
| `arch:AntiCorruptionLayer` | `<up> [U]->[D,ACL] <down> : <name>` |
| `arch:PublishedLanguage` | `<up> [U,PL]->[D] <down> : <name>` |
| `arch:SharedKernel` | `<up> [SK]<->[SK] <down> : <name>` |

Chapter 11 exports as:

```text
ContextMap {
  contains expense_context, finance_context
  expense_context [U]->[D,CF] finance_context : expense_to_finance
}

BoundedContext expense_context

BoundedContext finance_context
```

- **The output is sorted.** `contains` lists the contexts by IRI; relationships follow
  in IRI order; the `BoundedContext` declarations follow the map in IRI order. The same
  model exports the same bytes.
- **The map has no name, `type` or `state`.** All three are optional in CML, and the
  graph has no fact for them.
- **A shared kernel is symmetric in CML** but has an `arch:upstream` and an
  `arch:downstream` in the graph (ADR-0032 section 3). Export writes the upstream on the
  left; import reads the left side as upstream.

### 3. Import reads the context map and maps what the table covers

`seams cml import FILE` reads the relationship lines of every `ContextMap` in a CML file
and the names of its `BoundedContext`s. It accepts CML's arrow forms in either direction
(`A [U,..]->[D,..] B` and `B [D,..]<-[U,..] A`), the symmetric `<->` form, and an
optional `: <name>` suffix and `{ ... }` body. It decides the type from the roles,
downstream role first, because the downstream role is the one that says how the
downstream uses the upstream's language (ADR-0032 section 3):

1. `ACL` on the downstream end is `arch:AntiCorruptionLayer`;
2. `CF` on the downstream end is `arch:Conformist`;
3. `S` or `C` is `arch:CustomerSupplier`;
4. `PL` on the upstream end is `arch:PublishedLanguage` (with or without `OHS`, which
   ADR-0032 folds into it);
5. `SK` on both ends, or a bare `<->`, is `arch:SharedKernel`.

Each context name is resolved to the model's `arch:BoundedContext` whose IRI has that
local name. A relationship is written as the four facts ADR-0032 defines (`rdf:type`,
`arch:upstream`, `arch:downstream`, `arch:relationshipType`) in the architecture model
graph that declares the upstream context. Its IRI is minted from the model's base: the
CML name when the line has one, otherwise `<upstream>_to_<downstream>` from the two
local names. So exporting chapter 11 and importing the result into a copy without
`:expense_to_finance` gives back the same triples.

### 4. Import flags what it cannot map and never refuses it

Every construct with no mapping is skipped and reported on standard error as one line,
`seams cml import: flag <construct>: <reason>`; the import still writes the rest and
exits 0. The flagged constructs are:

- **A relationship whose only role is `OHS`**, or one with no role that decides a type
  (a bare `[U]->[D]`): the graph has no type for it.
- **A partnership** (`[P]<->[P]` or `Partnership`): ADR-0032 has no such type.
- **A role the type rule did not use** (the `PL` in `[U,PL]->[D,ACL]`): the relationship
  keeps one type, so the other role is reported rather than silently dropped.
- **An unknown context name**, one that matches no `arch:BoundedContext` local name in
  the model, or a name two contexts share.
- **A relationship over a pair the model already relates with another type or the other
  way round**: writing it would break ADR-0032's one relationship per pair.
- **Everything else in the file**: aggregates, entities, services, domains, teams, use
  cases, relationship bodies and `BoundedContext` attributes. The graph has its own
  sources for those.

A file that does not parse is different: the import names the line, writes nothing and
exits 1. Flags are for well-formed CML the graph cannot hold; a parse error is a file the
import cannot read.

### 5. Import only adds facts, through `seams_edit`

The import builds one `seams_edit` patch (ADR-0017) of the facts missing from the
architecture graph's file and applies it as `seams migrate` does, so the file keeps its
layout and comments. It never removes a fact: a relationship in the model that the CML
file does not mention stays, and a relationship that already holds the same facts adds
nothing, so importing into an unchanged model leaves the file's bytes as they were. It
prints `added <relationship>` for each relationship it writes.

## Alternatives considered

- **Exporting labels as `domainVisionStatement` and domains as `Domain` blocks.**
  Rejected: neither CML attribute means what the graph fact means, and the import would
  have to map them back or drop them, so the round trip would not hold.
- **Refusing a file with unmapped constructs.** Rejected: a real Context Mapper file
  holds aggregates and teams as a matter of course, and a refusal would make the import
  useless for exactly the files it is for. Flags keep every skipped item visible.
- **Import replaces the map.** Rejected: a CML file drawn from part of the system would
  delete the relationships it does not mention. Removal stays a deliberate edit.
- **Minting the IRI from the CML name only.** Rejected: the name is optional in CML, and
  a minted `<upstream>_to_<downstream>` is stable and readable when it is missing.
- **A CML parser library.** Rejected: Context Mapper's parser is Java (Xtext), and the
  part the import reads is a few line forms; a small parser that names the bad line is
  simpler than a JVM dependency.

## Consequences

- `seams cml export [PATH]` and `seams cml import FILE [PATH]` are added to the CLI
  (M029/S03/T02, T03), with `--project` and `--model` like `seams storm`.
- A CML file's aggregates and other tactical content are never read; the DDD profile
  (ADR-0033) is where the graph checks the tactical rules.
- A Context Mapper user can round-trip a map: export, edit relationships in Context
  Mapper, import the new ones. Removals and type changes made in Context Mapper are
  flagged, not applied.

## Open questions

- **Partnership.** If a later chapter needs it, it is a sixth `arch:RelationshipType`
  under ADR-0032, and this table gains `[P]<->[P]`.
- **Relationship attributes.** `implementationTechnology` and `exposedAggregates` could
  map to deployment facts and shapes; nothing reads them until a consumer needs them.
