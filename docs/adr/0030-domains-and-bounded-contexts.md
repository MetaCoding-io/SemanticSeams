# ADR-0030: Domains and Bounded Contexts — `arch:Domain` Classifies Systems, an `arch:BoundedContext` Owns One Ontology and Its Model Graphs, and a Shared Ontology Has One Owner

**Status:** Accepted

**Date:** 2026-11-06

**Source:** milestone M028/S02; backlog B1 (and E6, B2, B4, B5, X7, which wait on it);
research note [Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md)
sections 2.1, 2.3 and 5 and its first two open questions; amends
[ADR-0022](./0022-ontology-notation.md) section 3 ("shared by import later"); builds on
[ADR-0001](./0001-named-graph-partitioning.md), [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0008](./0008-node-link-renderer.md) and [ADR-0021](./0021-vocabulary-versions.md)

## Context

The graph has systems, containers and components (`arch:`), and since ADR-0022 one
`seam:Ontology` per model. It has nothing above `arch:System`: no domain to group
systems under, no classification that says where effort goes, and nothing that owns a
language. One TriG file holds one application and one namespace, so each example is one
implicit bounded context, and nothing can say that two models mean different things by
`:Payment`.

ADR-0022 decided where the ontology lives (one per model, imported by others later) and
left two things to B1: who owns an ontology that several contexts use, and how the
context boundary is drawn. The DDD note left two open questions on the same point:

- **Is a bounded context an `arch:` element or a `seam:Model` grouping?** It groups
  model graphs and owns an ontology, which is not what `arch:contains` nests today.
- **One context per TriG file?** A context map needs at least two contexts in one
  dataset, which may be two files loaded together or one file with two namespaces.

The derived event storm (B4, M028/S01, `seams storm`) is the evidence for where a
boundary falls in the expense tutorial. Run on `examples/expenses/chapter-10`:

- **The approval process hands over through one channel.** Its last step, *Paid*
  (`approved_end`), publishes to `payouts`, and the payout process's only trigger is
  *Payout Requested* on that channel, with no actor. The approval storm
  ([`tests/golden/storm/approval_process.md`](../../tests/golden/storm/approval_process.md))
  and the payout storm meet at that one sticky and nowhere else in their timelines.
- **One aggregate is written from both sides.** `PaymentShape` (class `Payment`,
  lifecycle `payment_lifecycle`) is written by *Pay Expense* in the approval process and
  by *Schedule Payout*, *Add to Batch* and *Send Now* in the payout process. Every
  payment domain event (scheduled, batched, sent) is fired on the payout side.
- **Both sides share one store.** Every aggregate is `stored in expense_db` (or
  `expense_pkm`), so the store does not draw the line.

So the finance context's language is `Payment` and its lifecycle, owned by the payout
process, the payout decision and the finance console; the expense context's is
`Expense`, `Approval` and the approval process; and the line between them is the
`payouts` channel, with one write (*Pay Expense*) on the wrong side of it. That is the
worked example below and the shape chapter 11 (E6) builds.

## Decision

### 1. A domain is an `arch:` element with one classification

`ontology/arch.ttl` gains a class, a property and three values:

```turtle
arch:Domain a rdfs:Class ; rdfs:subClassOf arch:Element ;
    rdfs:comment "A business area that groups systems and bounded contexts; classified core, supporting or generic." .

arch:DomainClassification a rdfs:Class .
arch:Core       a arch:DomainClassification ; rdfs:label "core" .
arch:Supporting a arch:DomainClassification ; rdfs:label "supporting" .
arch:Generic    a arch:DomainClassification ; rdfs:label "generic" .

arch:classification a rdf:Property ;
    rdfs:domain arch:Domain ; rdfs:range arch:DomainClassification .
```

A domain `arch:contains` the systems and the bounded contexts in it, with the existing
nesting property; nothing new nests. It carries exactly one `arch:classification`. The
classification is a fact about the domain, so the subdomain kinds of the DDD note
(section 2.3) are domains, and a context's classification is its domain's. It is not a
seam: a domain, its systems and its contexts are all architecture-layer elements, in the
architecture model graph (ADR-0001 rule 1).

The values are individuals, not a `seam:` enumeration or a string, so a query compares
IRIs and the viewer labels them from `rdfs:label`. They are the three DDD names; no
method beyond DDD needs a fourth, and a profile that does can add its own value.

### 2. A bounded context is an `arch:` element that owns its models

```turtle
arch:BoundedContext a rdfs:Class ; rdfs:subClassOf arch:Element ;
    rdfs:comment "The boundary inside which a term has one meaning: owns one seam:Ontology and the model graphs that use its language." .
```

and, in `ontology/seam.ttl`:

```turtle
seam:owns a rdf:Property ;
    rdfs:domain arch:BoundedContext ; rdfs:range seam:Model ;
    rdfs:comment "A bounded context owns a model: the model is written in the context's language and changed by its team." .
```

- **An `arch:` element, not a `seam:Model` subclass.** A context is a thing in the
  architecture (it sits in a domain, a team owns it, the C4 projection draws it), and a
  `seam:Model` is a graph of one notation. Making the context a model would put a
  grouping of graphs in the place of a graph, and every consumer that walks models by
  notation (the hash, the health check, the generators, the layers view) would need a
  rule for a model that is not one. As an element it needs no such rule.
- **Ownership is `seam:owns`, not `arch:contains`.** `arch:contains` nests elements in
  elements; ownership joins an architecture element to models of any notation, so it is a
  cross-layer fact and lives in the seams graph (ADR-0001 rule 1), beside the
  `seam:notation` facts. Keeping the two apart means a C4 nesting query never meets a
  BPMN model, and "which models does this context own" is one predicate in one graph.
- **Exactly one ontology.** A context owns exactly one model whose `seam:notation` is
  `seam:Ontology`: that ontology is its language (ADR-0022 section 2's "one per model,
  per bounded context", now stated on the context).
- **Each model has at most one owner.** A model is owned by at most one context. Once a
  dataset declares any context, every model except an architecture model (`seam:C4`) is
  owned by exactly one. A dataset with no context is one implicit context, so every
  existing example loads and checks unchanged.
- **The architecture model is not owned.** The domains and contexts are declared in it,
  so it describes the boundaries rather than sitting inside one.
- **Which containers run a context is derived.** A container that `seam:executes` or
  `seam:presents` a model a context owns runs that context. No context-to-container fact
  is added.
- **A context's elements are its models' elements.** An element is in a context when
  its `seam:inModel` model is owned by the context. No `seam:inContext` is added.

### 3. One context per TriG file is a convention, not a rule

A context's models may be in one file or several, and one file may hold several
contexts' models: ADR-0001 already lets a file hold any number of model graphs, and the
loader already merges a directory's files into one `Dataset`. Ownership is a fact, never
read from the file layout, so moving a model graph between files changes nothing the
model says.

The convention is one file per context, named for it, because it matches how a team
works and keeps each context's diff to its own file. Chapter 11 (E6) follows it with two
files in one checkpoint directory, `expenses.trig` and `finance.trig`, loaded together.
A context does not get a namespace of its own: IRIs follow ADR-0002 as they do today,
so ownership never shows in an IRI.

### 4. A shared ontology has exactly one owning context

This amends [ADR-0022](./0022-ontology-notation.md) section 3, which left "who owns a
shared ontology" to B1:

- **One owner.** A shared ontology is an ordinary `seam:Ontology` model owned by exactly
  one context, by section 2's rule. That context changes it and moves its
  `owl:versionIRI`; no ontology is co-owned.
- **Others reach it by `owl:imports`.** A context that uses another's classes imports
  that ontology by its version IRI from its own ontology, resolved by ADR-0022 section 4
  with one more source: an ontology model in the same dataset, matched by its
  `owl:versionIRI`, before the files in `ontology/vendor/`. An import of a version the
  dataset does not hold is the same `ResolutionError(<ontology>, owl:imports, ...)`.
- **Imported classes are read-only to the importer.** The class view draws them as it
  draws gist's (ADR-0022 section 6), and the importer's shapes may target them with
  `sh:targetClass`. Writing them is a context-map question (section 7).
- **A shared kernel is a small ontology with one owner.** DDD's shared kernel, which two
  contexts agree to change together, is modelled as a third context's ontology both
  import, or as one side's; which relationship that is goes to B2's context map. No
  ontology is owned by two contexts.
- **Releases follow the owner's version IRI.** A version change is the owner's, by
  ADR-0021's classification. Whether ADR-0021's load check and migrations apply to a
  user's ontology, which ADR-0022 deferred until a second model imports one, stays open
  (see Open questions); chapter 11 is the first such import.

ADR-0022's guarantee holds: an element's IRI is not derived from the context that owns
it, so moving `Payment` from `expense_ontology` to `finance_ontology` changes its
`seam:inModel` and the `seam:owns` facts, not its IRI.

#### The worked example: expense and finance

Chapter 11's architecture graph declares the domains and contexts; the seams graph says
what each context owns:

```trig
<urn:seams:graph:model:expense_architecture> {
    :expense_management a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_system , :expense_context .
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" .
}

<urn:seams:graph:seams> {
    :expense_context seam:owns :expense_ontology , :expense_data , :expense_ifml ,
        :approval_bpmn , :approval_dmn , :expense_lifecycle .
    :finance_context seam:owns :finance_ontology , :payout_bpmn , :payout_dmn ,
        :finance_console , :payment_lifecycle .
}
```

`finance_ontology` declares `Payment`; `expense_ontology` imports
`finance_ontology`'s version IRI. The storm's one cross-boundary write, *Pay Expense*
writing `PaymentShape` from the approval process, is what chapter 11 resolves: the
payment task moves to the payout process, so `Payment` is written only from the context
that owns it, and the `payouts` channel is the only line between the two storms. The
classifications are the example's, chosen to give the section 6 query a row: the
tutorial's business competes on paying people quickly, and approving expenses is
supporting work.

### 5. The C4 L1 projection draws domains and contexts

The viewer's L1 (system context) level adds `arch:Domain` and `arch:BoundedContext` to
its visible classes. A domain is drawn as a compound node around the systems and
contexts it `arch:contains`, labelled with its classification; a context is drawn as a
node inside its domain, with an edge to each system that runs it: a system that
`arch:contains` a container which, by section 2, runs the context. The edges come
from the `c4-l1-rollup` projection query, as L1's edges already do (ADR-0008), and nodes
and edges are sorted as every node-link layout is, so the picture is the same on every
load. A model with no domain draws L1 as today.

The bounded context canvas (B4's second view) is the L1 card for a context: name,
classification, owned models, inbound and outbound messages. It is a derived view over
these facts, built after the vocabulary, not decided here.

### 6. Shapes and the first query

S03 adds the vocabulary above (`arch` `1.0` to `1.1`, `seam` `1.2` to `1.3`, both
compatible widenings under ADR-0021 section 7, no migration files) and these shapes to
`ontology/shapes/seam-shapes.ttl`:

| Shape | Checks |
|---|---|
| `DomainShape` | an `arch:Domain` has one `rdfs:label` and exactly one `arch:classification`, one of `arch:Core`, `arch:Supporting`, `arch:Generic` |
| `BoundedContextShape` | an `arch:BoundedContext` has one `rdfs:label`, is `arch:contains`ed by exactly one `arch:Domain`, and `seam:owns` exactly one model whose `seam:notation` is `seam:Ontology` |
| `ModelOwnerShape` | a `seam:Model` is `seam:owns`ed by at most one context, and, when the dataset declares any `arch:BoundedContext`, every model whose notation is not `seam:C4` is owned by exactly one |
| `OwnsTargetShape` | the object of `seam:owns` is a `seam:Model` |

Each violation names the element and the predicate, like every seam shape.

The query the classification earns is **core operations with no handler and no
scenario**, `docs/queries/coverage/core-operations-untested.rq`: every `hydra:Operation`
whose model is owned by a context in an `arch:Core` domain, that is not
`seam:implementedBy` a `comm:PythonHandler` and is not reached by any `verify:Scenario`
(through the process it starts or the user task it completes). Each row is a risk:
the code the business competes on, either generated or untested. On chapter 11
each row is a finance operation still to cover. The
generic-domain smell (owned code in a generic domain) is the second query of the same
kind, added with B5's profile.

### 7. Context maps are out of scope

The relationship between two contexts (upstream and downstream, customer and supplier,
conformist, anti-corruption layer, published language, shared kernel, separate ways)
is B2. This ADR adds no fact between contexts. The three rules that need one, "no shape
written from two contexts", "every cross-context consume is translated unless declared
conformist" and the aggregate boundary of X7, wait for B2 and B5. Until then, a write
across contexts (the storm's *Pay Expense*) is visible in `seams storm` and in the
section 6 shapes' ownership facts, not refused.

## Alternatives considered

- **A bounded context as a `seam:Model` subclass, or a model of notation
  `seam:Context`.** Rejected: a context groups models and owns an ontology, which is not
  a graph of one notation; every model walker would need an exception, and the C4
  projection would need a rule to draw a model (the DDD note's first open question).
- **Ownership by `arch:contains`.** Rejected: it would mix nesting of elements with
  ownership of models of every notation, put a cross-layer fact in the architecture
  graph (ADR-0001 rule 1), and make every C4 nesting query filter out models.
- **A `seam:inContext` on every element.** Rejected: an element's model already says
  where it is (`seam:inModel`), so per-element facts would restate one fact per model
  hundreds of times and could disagree with it.
- **One context per TriG file as a rule, or a context per namespace.** Rejected: the
  loader merges files and ADR-0001 lets a file hold any graphs, so a file rule would
  read meaning from the layout (principle 1), and a namespace rule would make moving a
  model between contexts an IRI change.
- **A co-owned shared kernel.** Rejected: an ontology two contexts both change has no
  one to move its version IRI, which is the fact ADR-0021 and ADR-0022 version on. A
  shared kernel is one owner's ontology plus an agreement, and the agreement is B2's.
- **The classification on the context, or as a string.** Rejected: DDD classifies the
  subdomain, and EventCatalog's L1 and Team Topologies both group by domain; a string
  cannot be compared by IRI or labelled by the viewer.
- **A `ddd:` vocabulary for domains and contexts.** Rejected: domain and context are
  method-neutral facts C4, EventCatalog and the ontology layer need (DDD note section
  5). The tactical taxonomy (aggregates, value objects) stays out of every vocabulary,
  as the note recommends; the DDD profile (B5) is a shapes library.

## Consequences

- `arch` becomes `1.1` and `seam` `1.3`; models that declare the older versions load
  unchanged. Every existing example declares no context, so it is one implicit context
  and passes the new shapes as it is.
- ADR-0022 section 3's "later" is now decided: an ontology owned by one context is
  imported by another by its version IRI, resolved first against the dataset's own
  ontology models.
- Chapter 11 (E6) has a fixed target: two files, two domains, two contexts, `Payment` in
  the finance ontology and the payment task moved to the payout process.
- B2's context map and B5's ownership rules get the context to hang facts and shapes
  on; X7's aggregate boundary gets the context it must not cross.
- The viewer's L1 gains two node kinds; the layers view and the class view need no
  change, since contexts are elements and imported classes are already drawn read-only.
- `seams storm` gains nothing now. Once contexts exist, a step that writes an aggregate
  whose class another context's ontology declares is a natural storm gap; that is B5's
  call.

## Open questions

- **Versions and migrations for a user's ontology.** ADR-0022 deferred ADR-0021's load
  check and migrations for a user's ontology until a second model imports one.
  Chapter 11 is the first; whether importing a lower minor of `finance_ontology` loads
  unchanged, and where its migrations live, is decided when chapter 11 needs a change to
  it, not before.
- **Who owns a store.** The storm showed both contexts writing to `expense_db`. A
  store shared by two contexts is a deployment fact, not a language one; whether B5
  flags it, or the context map declares it, is B2's question.
- **Cross-file imports outside a dataset.** Section 4 resolves an import against
  ontology models in the same dataset. A context in another repository, loaded
  separately, would need ADR-0022's "project-declared directory of shared ontologies";
  nothing needs it yet.
