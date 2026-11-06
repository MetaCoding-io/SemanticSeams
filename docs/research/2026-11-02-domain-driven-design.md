# Research note: domain-driven design, read against the graph

*Status: proposal, 2026-11-02. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Not yet scheduled" section, items B1 to B5). Follows the
[data-centric model note](2026-10-31-data-centric-model-and-copilot.md), whose open
question on where the ontology lives it answers, and the
[EventCatalog Levels note](2026-10-15-eventcatalog-levels.md), whose missing "Domain"
level it names. Written against `main` at `6ca0913`.*

*Revision, 2026-11-06: the first two open questions are answered by
[ADR-0030](../adr/0030-domains-and-bounded-contexts.md) (M028/S02, B1). A bounded context is
an `arch:` element, not a `seam:Model` grouping: it `seam:owns` exactly one `seam:Ontology`
and the model graphs in its language, and an `arch:Domain` with a core, supporting or
generic `arch:classification` contains it. One context per TriG file is a convention, not a
rule; chapter 11 (E6) loads two files into one dataset. A shared ontology has one owning
context, reached by `owl:imports`. The text below is unchanged.*

## The question

Domain-driven design (DDD) has no notation of its own, so there is nothing to seam
together the way BPMN, DMN, IFML and SHACL are. But it has thirty years of vocabulary
and practice for modelling a software domain: bounded contexts, context maps,
aggregates, domain events, ubiquitous language, event storming. What of that is
useful here, what does the graph already hold under other names, and what is missing?

## Short answer

- **The tactical patterns are already in the graph, unlabelled.** Every DDD building
  block maps onto an existing term or seam. The expense tutorial is a DDD model with
  two aggregates, two sagas and a policy, written without the words (section 1).
- **The strategic patterns are the layer the graph lacks above `arch:System`.**
  Nothing owns a language. There is no bounded context, no context map, no subdomain
  classification. These earn queries the existing seams cannot answer (section 2).
- **A bounded context is a named-graph scope with its own ontology.** That settles the
  data-centric note's open question: one ontology per bounded context, shared kernels
  as imports (section 2.1).
- **The aggregate is a class, not a shape.** The shapes are its command inputs and
  read models. So O1 and O2 come before any DDD profile (section 3).
- **Event storming is the DDD practice closest to a notation, and every sticky colour
  has a home in the graph.** Derive it as a view, like the sequence diagram. Do not
  author it (section 4).
- **DDD ships as the second `seam:Profile`,** after IDesign, as the outline planned:
  two or three method-neutral terms in `arch:`, and a shapes library over the model
  for the rest (section 5).

## 1. Tactical DDD: what the graph already holds

The test for each pattern: which model facts state it today, and what is lost by not
naming it. The column on the right uses chapter 9 of the expense tutorial
(`examples/expenses/chapter-09/expenses.trig`).

| DDD building block | Where it lives today | In the expense tutorial |
|---|---|---|
| Aggregate root | A `sh:NodeShape` with a `seam:lifecycle`, an identifier property, a `proc:correlationKey` on the process that carries it, and a `seam:storedIn` store | `:ExpenseShape` and `:PaymentShape`: two aggregates |
| Value object | A shape with no identifier and no lifecycle, nested with `sh:node` | None yet; the money magnitude in the [gist example](examples/expense-gist.trig) is one |
| Invariant | SHACL constraints on the shape, enforced by `Runtime.write` before anything is stored | `sh:minInclusive 0.01` on `:amount` |
| Command | A `hydra:Operation` with `hydra:method "POST"` and a `seam:acceptsShape`, reached by an `ifml:Event` through `seam:submitsTo` | `:submit_expense_op`, `:approve_expense_op`, `:pay_expense_op` |
| Query, read model | A GET operation that `seam:rendersComponent` an `ifml:List` or `ifml:Details` | `:list_expenses_op`, `:awaiting_approval_op` |
| Domain event | A `comm:Channel` with a `seam:acceptsShape`, published by a message end event through `seam:publishesTo`. A `state:Transition` is a domain event too, one nothing outside the process can observe | `:payouts` ("payout requested"); `:t_submit`, `:t_approve`, `:t_pay` |
| Process manager, saga | A channel-started process ([ADR-0010](../adr/0010-channel-started-processes.md)): a message start event that `seam:subscribesTo` a channel | `:payout_process`, started by `:payouts` |
| Policy ("whenever X, then Y") | A `dec:Decision` feeding a BPMN gateway, or the process flow itself | `:approval_routing`, `:payout_method` |
| Domain service | A `comm:PythonHandler` or `comm:HTTPEndpoint` behind an operation ([ADR-0012](../adr/0012-operation-implementation.md)) | `notify.notify_manager` |
| Repository | Storage resolution: `seam:storedIn` a store whose `deploy:storeKind` the runtime supports ([ADR-0011](../adr/0011-storage-resolution.md)) | `:expense_db` |
| Actor, role | `odrl:Party`, and `arch:Person` at the architecture level | `:employee`, `:manager`, `:finance` |
| Specification by example | The `verify:` vocabulary: scenarios, decision examples, shape examples ([ADR-0014](../adr/0014-scenarios-and-derived-tests.md)) | `:auto_approved`, `:manager_approved`, `:finance_approved` |
| Ubiquitous language | `rdfs:label` on every element, and the planned ontology layer (O1) | The labels; no class yet says what an expense is |
| Ports and adapters | An operation with its shapes is the port; the three `seam:implementedBy` kinds are the adapters; the generic graph-literate worker is the application layer | `:notify_manager_op` and its handler |

Two observations follow.

**The ubiquitous-language rule is enforced harder here than in any DDD codebase.**
Principle 1 forbids domain literals in generated code and templates. Generated code
cannot name anything the model does not, so the language in the code is the language
in the model by construction. DDD achieves the same only by review.

**The anemic-model critique does not apply, though it looks as if it should.** DDD
puts behaviour in entity methods and treats a data holder with external services as an
anti-pattern. This project puts behaviour in statecharts, DMN and BPMN, and keeps the
data as shapes. The critique is about rules drifting away from the data they protect.
Here the rules are bound to the data by graph edges: `seam:lifecycle` hangs the
statechart on the shape, the SHACL constraints are the shape, and `seam:fires` names
which task may move it. The code is anemic by design. The model is not.

## 2. Strategic DDD: what is missing

### 2.1 Bounded contexts

A bounded context is the boundary inside which a term has one meaning. Nothing in the
graph owns a language. One TriG file holds one namespace, so one application is one
implicit context, and nothing can say that an expense means one thing to Finance and
another to HR, or that Finance's `:Payment` and the bank gateway's `:Payment` are
different things with the same name.

The RDF answer is already half built. A bounded context is a named-graph scope
([ADR-0001](../adr/0001-named-graph-partitioning.md)) plus its own ontology (O1) with
its own version IRI (K6). The data-centric note asked whether the ontology should be
one shared ontology across applications or one per model. DDD's answer is neither: one
per bounded context, with a shared kernel as an `owl:imports` of a small, versioned
ontology that both contexts agree to change together. gist is the upper ontology every
context imports; the shared kernel is the domain-level ontology two contexts share.

### 2.2 Context maps

The seams model the physical dependencies between containers: `seam:consumes`,
`seam:exposes`, channels. They do not say who owns the contract. A context map adds
the direction language flows across each dependency:

| Relationship | What it says | Graph facts that would state it |
|---|---|---|
| Upstream, downstream | Which side's changes force the other to change | The direction of `seam:consumes`, read per context |
| Customer, supplier | Downstream has a say in upstream's contract | A relationship fact between contexts; no seam needed |
| Conformist | Downstream uses upstream's language as is | Downstream's shapes are upstream's shapes, `sh:node` or `owl:imports` |
| Anti-corruption layer | Downstream translates at the boundary | An operation in the downstream context whose accepted shape is downstream's and whose implementation calls an upstream operation |
| Open host service, published language | Upstream publishes a stable contract with a version | An operation's shapes, in a versioned ontology (K6) |
| Shared kernel | Both share and co-own a small model | A shared ontology both import |
| Separate ways | No integration | No seam between the contexts |

The relationship type is one fact per pair of contexts. What it earns is the point:

- **Which contexts does this breaking change reach?** U8's shape diff classifies a
  change as compatible or breaking. Scoped by context, the same diff says which
  downstream contexts must change, and a conformist context is affected where a
  context behind an anti-corruption layer is not.
- **Which cross-context calls have no translation in front of them?** A gate query:
  an operation consumed across a context boundary whose accepted shape belongs to the
  other context. Each row is a conformist relationship the map does not declare.
- **Which contexts run against version N of a published language?** K6's version
  facts, read per context.

Context Mapper's CML is the one place DDD has a formal language, for exactly this
part: a textual DSL for bounded contexts, their relationships by type, and aggregates
inside them, with generators to PlantUML and to service contracts. It is the
Structurizr DSL of DDD. Its relationship types are the vocabulary above, and it would
be an import and export target in the same way the UML note treats Structurizr DSL and
LikeC4 for the C4 layer.

### 2.3 Subdomains and their classification

DDD classifies subdomains as core (where the business competes), supporting (needed
but not differentiating) and generic (bought or copied). The classification says
where to spend effort. The project already has a three-tier code story that lines up
with it:

| Subdomain kind | Where its code comes from here |
|---|---|
| Core | Owned code: `comm:PythonHandler` functions, LLM drafts reviewed and accepted (C4) |
| Supporting | Generated from the model, interpreted BPMN and DMN |
| Generic | An external system behind a `comm:HTTPEndpoint` |

Classifying a subdomain earns two review queries: a core-subdomain operation with no
handler and no `verify:Scenario` is a risk, and a generic subdomain with owned code is
a smell. Both are one query once the fact exists.

The EventCatalog Levels note found the same missing level from the other direction:
its L1 is "domains, systems and actors", and the graph has systems and actors but no
domain to group them under. Team Topologies' ownership line on the same card is the
same gap.

### 2.4 Aggregates as explicit consistency boundaries

Today an aggregate is implied by four facts on four elements: the shape, its
lifecycle, the process correlation key and the store. Two things are not stated:

- **The transactional boundary.** `Runtime.write` stores one entity per shape. A
  process carries several entities. Nothing says which of them must change together.
- **Cross-aggregate invariants.** An expense must not be paid twice; a batch of
  payments must not exceed a budget. SHACL validates one node, so these rules have no
  home. Once instance data is RDF (O4), a `sh:sparql` constraint can state a rule
  across instances, which DDD codebases hand-roll every time. The discipline to carry
  over with it: a cross-aggregate rule is eventually consistent, reconciled by a saga,
  so it should be `sh:Warning`, not a violation that blocks the write.

## 3. The aggregate is a class

The data-centric note's open question "lifecycle on the class or the shape" is the
aggregate question. A state belongs to the thing. The commands' input shapes and the
read models' display shapes are views of it, and one class has many shapes: the
submit form, the approver's input, the payment record. So:

- the aggregate root is the `rdfs:Class` the ontology layer (O1) introduces, anchored
  in gist where the fit is honest;
- `seam:lifecycle` moves from the shape to the class once classes exist, with the
  shape's lifecycle derived through `sh:targetClass`;
- a value object is a class with no lifecycle and no identity, reached only through
  `sh:node`;
- the states become categories (O2), so a domain event such as "expense approved" has
  an IRI, `:t_approve`, and a published form, a channel event, without copying labels.

This is why O1 and O2 come before a DDD profile. The profile has nothing to attach to
until the class exists.

## 4. Event storming as a derived view

Event storming is the DDD workshop that produces the most structure with the least
formality: a timeline of sticky notes in fixed colours. Every colour has a home in the
graph.

| Sticky | Meaning | Graph element |
|---|---|---|
| Orange | Domain event | A `state:Transition`, or a `comm:Channel` publish |
| Blue | Command | A POST `hydra:Operation` |
| Yellow, small | Actor | An `odrl:Party` |
| Yellow, large | Aggregate | A shape with a `seam:lifecycle` (a class, after section 3) |
| Purple | Policy, "whenever" | A `dec:Decision`, or a channel-started process |
| Green | Read model | An `ifml:List` or `ifml:Details` with its GET operation |
| Pink | External system | An `arch:System` reached through a `comm:HTTPEndpoint` |
| Red | Hot spot | A backlog row or ADR question |

The walk for one process is: the actor who may fire the triggering event
(`seam:governedBy`), the command it submits to, the aggregate the command writes, the
transitions the process's tasks fire, the decisions on the way, the channels the end
events publish to, the processes those channels start, and the read models that show
the result. Rendered as a timeline, that is a big-picture storm board per process.

The UML note's lesson applies unchanged. Deriving a view is a cheap audit of the model:
every sticky the deriver cannot place is a missing fact or runtime behaviour that
bypasses the graph. And the storm must not become an authored notation, because every
authored storm would restate facts the graph holds and would drift. `seams sequence`
is the pattern: a function from a process to Mermaid, a golden test on the expense
tutorial, a section in the viewer later.

The inverse, importing a storm into a skeleton model, is an editing feature (I-series)
or a copilot suggestion (R2), and it is where a workshop's output becomes the entry
point for people who will never write TriG. It needs the derived view first, because
the import's acceptance test is that deriving the view from the imported model gives
the storm back.

Two related practices need nothing new:

- **Domain storytelling** draws actors and work objects along a numbered story. The
  derived sequence diagram (U1, done) with ODRL parties as actors is that picture.
- **Example mapping** collects rules and examples per story. `verify:` scenarios,
  decision examples and shape examples are the examples; the DMN rows are the rules.

The DDD Crew's **bounded context canvas** is worth naming as a second derived view.
Its fields are name, purpose, strategic classification, inbound messages by
collaborator (commands, queries, events), outbound messages, business decisions and
ubiquitous language. Every field is a query over a context's named graphs once
sections 2.1 and 2.3 exist. It is the natural L1 card for a context.

## 5. Design: two terms in `arch:`, the rest in a profile

The outline reserved `seam:Profile` and `seam:conformsTo` for methodologies, named
IDesign as the first, and said a DDD profile could ship the same way. The split
between what goes in the shared vocabulary and what goes in the profile:

**Method-neutral facts belong in `arch:`.** A domain that groups systems, with a
classification, is a fact EventCatalog, C4 and Team Topologies all need. The bounded
context as a language boundary is a fact the ontology layer needs regardless of DDD.
Vocabulary is earned, so the backlog rows below name the query each term earns, and
the ADR for O1 is where the context boundary is decided, since it is the same decision
as where the ontology lives.

**The tactical taxonomy does not get classes.** `ddd:Aggregate`, `ddd:ValueObject`
and `ddd:DomainEvent` as `rdf:type` values would restate facts the graph already
derives (section 1). A profile shape can target "a shape with a `seam:lifecycle`"
directly. If a label is wanted in the viewer, it is a derived type pill, not a triple.

**The DDD profile is a shapes library** over the model, bundled and attached by
`seam:conformsTo`, with these rules as a starting set:

- every aggregate has exactly one correlation key, one lifecycle and one store;
- no shape is written from two bounded contexts (ownership);
- every cross-context consume passes through a translating operation, unless the
  context map declares the relationship conformist;
- every command is governed by a policy (today's `gates/ungoverned-writes.rq`);
- every transition is fired by something (today's `coverage/unfired-transitions.rq`);
- every domain event a channel publishes has a published shape in a versioned
  ontology.

Several of these are gates already. The profile bundles and names them, which is what
a profile is for: "we follow DDD" becomes a machine-checkable claim, the same way the
outline promised for IDesign.

**Context Mapper import and export** would come with the profile, as the
interchange path for the strategic layer.

## Backlog items

| # | Item | Builds on |
|---|---|---|
| B1 | **Domains and bounded contexts in `arch:`**: a domain that `arch:contains` systems, with a core, supporting or generic classification; a bounded context as the owner of an ontology and the named graphs that use it, decided in O1's ADR alongside where the ontology lives | O1, K6 |
| B2 | **Context map facts and queries**: one relationship type per pair of contexts; the breaking-change-per-downstream-context query over U8's diff; a gate for cross-context calls with no translating operation | B1, U8 |
| B3 | **Lifecycle on the class, states as events**: `seam:lifecycle` targets the class once O2 lands; a transition is a domain event with an IRI, publishable on a channel without a copied label | O1, O2 |
| B4 | **Derived event-storm view**: `seams storm <process>`, a timeline per process from the graph, with a golden test on the expense tutorial, then a viewer section; the bounded context canvas as a second derived view | B1 for the canvas; none for the storm |
| B5 | **DDD profile**: the shapes library in section 5, attached by `seam:conformsTo`, as the second profile after IDesign; Context Mapper import and export | I5, B1, B2 |

B4's storm view needs nothing new and can start now, as U1 did. B1 is the vocabulary
decision the rest wait on, and it belongs in the same ADR as O1.

## Open questions

- **Is a bounded context an `arch:` element or a `seam:Model` grouping?** It groups
  model graphs and owns an ontology, which is not what `arch:contains` nests today. If
  it is a kind of `seam:Model`, the viewer's C4 L1 would need a projection rule for it.
- **One context per TriG file?** The examples hold one application each. A context
  map needs at least two contexts in one dataset, which may be two files loaded
  together, or one file with two namespaces. ADR-0001's "a TriG file may contain one
  or more model graphs" allows both.
- **Where cross-aggregate warnings surface.** A `sh:Warning` on instance data has no
  reader yet: the runtime's write path rejects on violation and ignores the rest, and
  the viewer validates the model, not the data.
- **How much of the storm to import.** A big-picture storm carries no field names,
  no paths and no routes, so the imported skeleton cannot pass the shapes. The
  principle that an invalid model is flagged, never refused, makes that acceptable,
  but the editor has to make the gap visible as a to-do list.

## Sources

- Eric Evans, *Domain-Driven Design* (Addison-Wesley, 2003). Part II for entities,
  value objects, services, aggregates and repositories (chapters 5 and 6); Part IV for
  bounded contexts, context maps and their relationship types (chapter 14) and for
  core and generic subdomains (chapter 15). Paraphrased.
- Vaughn Vernon, *Implementing Domain-Driven Design* (Addison-Wesley, 2013). Chapters
  2 and 3 for subdomains, bounded contexts and context maps; chapter 8 for domain
  events; chapter 10 for aggregate design rules. Paraphrased.
- Alberto Brandolini, *Introducing EventStorming* (Leanpub). The sticky-note colours
  and the big-picture to process-level progression. Paraphrased.
- Vlad Khononov, *Learning Domain-Driven Design* (O'Reilly, 2021). The subdomain
  classification and its link to build-or-buy. Paraphrased.
- Stefan Hofer and Henning Schwentner, *Domain Storytelling* (Addison-Wesley, 2021).
  Paraphrased.
- Context Mapper, the DSL and tools for DDD strategic design:
  https://contextmapper.org/
- DDD Crew, the bounded context canvas:
  https://github.com/ddd-crew/bounded-context-canvas
- This repository: the [project outline](../project-outline.md) section 4 on profiles,
  the [principles](../project/principles.md), and the ADRs cited inline.
