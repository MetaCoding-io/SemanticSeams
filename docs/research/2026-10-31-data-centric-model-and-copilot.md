# Research note: a data-centric model, SemPKM as its store, and a model copilot

*Status: proposal, 2026-10-31. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Generator kit and domain IDE" section, items O1 to O6 and
R1 to R3). Follows the [LLM generator note](2026-10-31-llm-generator.md), whose
closing open question it takes up. Written against `main` at `752020a`. SemPKM facts
are from its repository at `afbfc64`.*

## The questions

1. What do we offer for data modeling? Can users define their application's data
   model in RDF, RDFS or OWL, or only as SHACL shapes? Could we allow the former?
2. Data-centric architecture, as Semantic Arts defines it, keeps data in a shared,
   self-describing graph that outlives the applications built on it. How close are we,
   and could [SemPKM](https://sempkm.metacoding.io/), a sister project, be the default
   store that supports SPARQL?
3. Could a meta system generate generators, or act as a copilot that reviews the
   model, the generators and the LLM stubs, and suggests ways to move more into the
   model?

## Short answer

- **Today the data model is SHACL shapes only, and the data is JSON in SQLite.**
  Shapes do their job as interface contracts. But nothing declares what the things
  are, and instance data never becomes RDF. We are model-centric, not data-centric.
- **An ontology layer fits without new seams.** Add an ontology notation, anchor
  domain classes in [gist](https://www.semanticarts.com/gist/), and let shapes point at
  classes with `sh:targetClass`. A worked example of the expense tutorial validates
  cleanly with pySHACL.
- **SemPKM is a strong default store.** It is event-sourced RDF on RDF4J, with a single
  write API and scoped SPARQL reads. Its domain packages are OWL ontologies plus SHACL
  shapes, built on gist. A generated app and SemPKM could then share one graph, which
  is the data-centric goal.
- **A copilot can start without an LLM.** Three deterministic checks already find real
  issues in both examples. An LLM adds judgment calls and, one level up, can draft new
  generators. Its output is accepted only when a golden test passes.

## 1. Data modeling today

| Aspect | Today |
|---|---|
| Notation | One `seam:ShapeGraph` model per app, holding SHACL node shapes. 2 shapes in the chat app, 3 in the expense tutorial's chapter 8 |
| What shapes drive | Form fields, request validation, list and detail displays, and lifecycles (`seam:lifecycle` hangs a statechart on a shape) |
| Classes | None. No example declares an `rdfs:Class` or `owl:Class`, and no shape has `sh:targetClass` |
| Properties | Bare IRIs in the app's namespace (`:amount`, `:description`). Across both examples, 16 of 16 property paths have no declaration: no label, domain or range |
| Relationships | One, in the chat app: `sh:class :MessageShape`, which points at a shape where a class belongs |
| Instance data | JSON in SQLite. `seams_runtime/store.py` keeps one `entities` row per payload, keyed by shape IRI. U9 adds PostgreSQL `jsonb` on the same path |
| RDFS or OWL in a model | Possible to write, since a TriG model graph is RDF, but nothing reads it: there is no ontology notation, and the viewer, generators and runtime ignore it |

Shapes are good at what they do: one contract per form, request or display. The gap is
that the contract is all there is. Nothing says that the thing an `ExpenseShape`
describes is an expense, what an expense is, or how it relates to a payment, beyond
what the shapes and the process imply. And the data is stored where only this
application can read it.

## 2. Data-centric, in Semantic Arts' terms

Semantic Arts argues that data, and a single simple model of it, should be the
long-lived asset. Applications are built on that data rather than each owning its own
schema and silo. The model is expressed in RDF and OWL, kept small, and anchored in
gist, their minimalist upper ontology. gist's current release is 14.1.0, licensed
CC BY 4.0; its core declares 96 classes and 116 properties
([repository](https://github.com/semanticarts/gist)).

Measured against that, SemanticSeams already does several things right:

- **The model is RDF.** Every diagram is a named graph with stable IRIs (ADR-0001,
  ADR-0002).
- **The behaviour lives in the model.** BPMN and DMN are interpreted rather than
  compiled into code (ADR-0007).

What is missing is the data side:

- a shared ontology of the domain;
- instance data stored as RDF against that ontology, so any application, query or
  person can read it.

## 3. Proposal A: an ontology layer

### 3.1 Shape of it

- **An ontology notation.** `seam:Ontology` is a model graph holding `owl:Ontology`,
  classes and properties, importing gist. The viewer draws it with the card renderer it
  already uses for shape graphs, showing classes, their gist superclasses and their
  properties.
- **Shapes target classes.** `:ExpenseShape sh:targetClass :Expense`. One class can
  have many shapes: the display shape, the approver's input, the payment record.
  `sh:targetClass` is plain SHACL, so no new seam predicate is needed.
- **Properties are declared once.** A gist property is used where one fits. A domain
  property is declared where none does.
- **States and enumerations are categories, not strings.** A lifecycle's own state IRIs
  become members of a class such as `:ExpenseState ⊑ gist:Category`, and the shape says
  `sh:class :ExpenseState`. Adding a state to the lifecycle then allows it everywhere,
  with no copied list to update.
- **Versions.** The ontology carries an `owl:versionIRI`, which is K6's vocabulary
  versioning applied to the user's own model.

### 3.2 The expense tutorial, anchored in gist

[`examples/expense-gist.trig`](examples/expense-gist.trig) rewrites chapter 8's data
model this way. It imports gist 14.0.0, the version SemPKM bundles; every gist term it
uses also exists in 14.1.0.

| Class | gist superclass | Why |
|---|---|---|
| `:Expense` | `gist:Transaction` | gist: a transfer of goods, services or funds. An expense is money spent |
| `:Payment` | `gist:Transaction` | The company's transfer that reimburses it |
| `:Approval` | `gist:Determination` | gist: an event that establishes a result by evaluating |
| `:ExpenseState`, `:ApprovalOutcome` | `gist:Category` | States and outcomes as IRIs, not strings |

Money becomes a gist magnitude with a unit and an aspect, instead of a bare decimal:

```turtle
<https://example.org/expenses/data/e42> a :Expense ;
    gist:description "Train to the Utrecht client workshop" ;
    gist:hasMagnitude [ a gist:Magnitude ;
        gist:numericValue 42.50 ;
        gist:hasUnitOfMeasure :USD ;
        gist:hasAspect gistd:_Aspect_monetary_value ] ;
    :incurredOn "2026-10-28"^^xsd:date ;
    gist:isCategorizedBy :s_submitted .
```

Two choices in the example are deliberate:

- **gistCore has no currency individuals**, so the model declares `:USD` as a
  `gist:UnitOfMeasure` with `gist:exponentOfUSDollar 1`.
- **gist's dates are `xsd:dateTime`**, and an expense is dated to the day, so
  `:incurredOn` stays a domain property. Not everything has to be gist.

`ExpenseShape` keeps its four fields and `sh:order`. `sh:name` keeps the form field
names (description, amount, date, status) stable even though the paths changed.

**Validated.** Run with pySHACL against gistCore and RDFS inference, the sample data
conforms. Four broken variants each fail on the constraint you would expect:

| Variant | Conforms | Constraint that fires |
|---|---|---|
| As written | yes | none |
| Status as the string `"submitted"` | no | `sh:class :ExpenseState` |
| Status set to `:approved` (an approval outcome) | no | `sh:class :ExpenseState` |
| Amount with no unit | no | `sh:hasValue :USD`, through `sh:node :MoneyShape` |
| Amount of −5.00 | no | `sh:minInclusive 0.01`, through `sh:node :MoneyShape` |

### 3.3 What changes for the generators

- **Forms over nested shapes.** The amount is now a magnitude node, not a decimal. The
  htmx generator has to flatten a `sh:node` whose other values are fixed by
  `sh:hasValue` into one field, and name it with `sh:name`. The rule fits in `extract`:
  a nested node with one free datatype property and the rest fixed by `sh:hasValue`
  becomes one input.
- **API payloads as JSON-LD.** A new generator emits a JSON-LD context from the
  ontology and the shapes, so the payloads the routes accept and return are RDF too.
  Clients that ignore `@context` see the same JSON as today.
- **Existing models keep working.** A shape with no target class stays a plain
  contract, and R1's checks suggest declaring one.

## 4. Proposal B: SemPKM as the default store

### 4.1 What SemPKM is

These facts come from its repository (`CODEBASE.md`, `docker-compose.yml` and the
backend modules):

- **The store.** An RDF4J 5.0.1 triplestore behind a FastAPI backend. It is
  event-sourced: every write commits an immutable event named graph and materialises
  current state into `urn:sempkm:current`, in one RDF4J transaction. Event diffs and
  undo are supported.
- **One write path.** `POST /api/commands`, with commands `object.create`,
  `object.patch`, `edge.create`, `edge.patch`, `body.set` and `body.diff`. An
  `object.create` takes an RDF type and a map from predicate to value, and returns the
  new IRI and its event graph.
- **SPARQL reads.** `GET` and `POST /api/sparql`, scoped to current state.
- **Auth.** API tokens with scopes `sparql:read`, `sparql:write`, `objects:read` and
  `objects:write`; IndieAuth OAuth2 for applications.
- **Mental Models.** Installable domain packages: `manifest.yaml`, an OWL ontology,
  SHACL shapes, view specs and seed data, in JSON-LD, each installed into its own named
  graphs. gist 14.0.0 is bundled, and the bundled models subclass gist. The CRM model's
  classes, for example, extend `gist:Person`, `gist:Organization`, `gist:Event` and
  `gist:Agreement`.
- **More services.**
  - OWL 2 RL inference;
  - a background SHACL validation queue;
  - webhooks emitting `object.changed` and `edge.changed`;
  - federation between instances using signed RDF Patch;
  - full-text search;
  - an AI copilot working with any OpenAI-compatible endpoint.

The overlap with this proposal is close. SemPKM already stores an OWL ontology with
SHACL shapes, anchored in gist, as RDF, behind SPARQL.

### 4.2 How SemanticSeams would use it

- **A storage backend behind U9's interface.** U9 already plans storage backends
  chosen from model facts, so SemPKM is one more backend.
  - A write validates against the shape first, as `runtime.write` does today, so a bad
    payload still gets a 422 with the failing paths. SemPKM validates in the
    background, after commit, so it cannot provide that answer.
  - The runtime then sends `object.create` with the class and the properties, and
    keeps the returned IRI.
  - Reads are SPARQL queries over current state, with a token scoped to `sparql:read`.
- **A generator that emits a Mental Model.** The ontology and shapes become a
  `manifest.yaml` plus `ontology/` and `shapes/` JSON-LD, with views derived from the
  IFML lists and details. Installed in SemPKM, the expense data the generated app writes
  can be browsed, edited and queried in SemPKM's workspace, by people and other apps.
  That is the data-centric outcome: one graph, several applications.
- **Webhooks as a channel.** SemPKM's `object.changed` events can start BPMN processes
  through `seam:subscribesTo`, the same way the expense tutorial's payout process starts
  from a channel today (ADR-0010).
- **Change history.** SemPKM's event graphs give every entity an audit trail. Its
  commands correspond to T4's quad patches and to I1's edits. Its RDF Patch federation
  is a model for sharing data between instances.
- **The compose generator adds it.** When the model names SemPKM as a store, the
  compose generator adds SemPKM's services (triplestore, API, frontend) with the right
  bindings. Process state and user tasks stay in the runtime's own store; they are
  execution state, not domain data.

### 4.3 Default for what

- **Deployments: SemPKM is the default.** It is a four-service stack (RDF4J, the API,
  nginx and Jaeger), so it suits deployed applications.
- **Quick start: embedded SQLite stays.** The chat app's one-command start and the
  tutorial's early chapters should keep using it until RDF storage is proven end to
  end.

U9's ADR is where this choice belongs, alongside SQLite and PostgreSQL.

### 4.4 Open points with SemPKM

- **Nested values.** `object.create` takes a map from predicate to value. It is not
  yet clear how a nested blank node such as a magnitude goes through it, or whether a
  magnitude should be an object with an edge.
- **IRIs.** SemPKM mints object IRIs. The runtime fills a shape's `:id` today. One of
  them has to give way, probably the runtime.
- **Identity.** One service token per application, or a user's token per request? The
  latter fits ADR-0009's per-person tasks better.
- **gist version.** SemPKM's bundled `gistCore14.0.0.ttl` carries a placeholder version
  IRI. An ontology that imports a specific version needs SemPKM to resolve it.

## 5. Proposal C: a model copilot, and generators that write generators

### 5.1 Deterministic checks first

A throwaway script ran three checks over both examples. Every finding is real:

| Check | Finding |
|---|---|
| A `sh:in` list repeats a lifecycle's state labels | Three times, each an exact match: `MessageShape` status (chat), `ExpenseShape` status and `PaymentShape` status (expenses). The list can drift from the lifecycle. Fix: section 3.1's categories |
| `sh:class` points at a shape | `sh:class :MessageShape` in the chat app. Fix: a `:Message` class |
| Shapes with no target class; undeclared paths | 5 of 5 shapes, and 16 of 16 paths. Fix: section 3's ontology |

More checks of the same kind come from the other notes:

- template expressions that compute (T2's 43);
- generator faults with no matching shape (K1);
- literals in LLM drafts that repeat model facts. The mockup's illustrative Send Now
  body sets `status="sent"`, which is `:t_send`'s target state.

None of these needs an LLM, and each comes with a fix that can be checked by
validating and regenerating.

### 5.2 Where an LLM helps

Some suggestions need judgment:

- "This branch in a draft is a decision rule; move it into the DMN table."
- "These three shapes describe the same thing; declare one class."
- "This class is a kind of `gist:Agreement`." An LLM can read gist's definitions and
  propose an anchor, for a person to confirm.

Each suggestion arrives as a model patch. It is accepted only after the model
validates, regeneration reproduces the expected output, and a person agrees. That is
the same loop as T5 and C4.

### 5.3 Generators that write generators

One level up, an LLM drafts a new deterministic generator from a reference output: a
template and its `extract` step. This is the kit note's reference-first method (K5) with
an LLM doing step 2. The golden test decides acceptance, so the output is a reusable
generator rather than one file.

A target as concrete as the SemPKM Mental Model in section 4.2 is a good first case:
the reference output is a hand-written package for the expense ontology.

## Backlog items

| # | Item | Builds on |
|---|---|---|
| O1 | **Ontology notation**: `seam:Ontology` model graphs, gist imports, a class view in the viewer, and model-health checks for imports and versions | K6 for versions |
| O2 | **Shapes target classes; states as categories**: `sh:targetClass`, `sh:name` for field names, lifecycle state IRIs as category members replacing copied `sh:in` lists, and form flattening for `sh:node` with fixed values | O1 |
| O3 | **JSON-LD context generator** for API payloads | O1, O2 |
| O4 | **SemPKM storage backend** behind U9's interface: validate, then `POST /api/commands`; read through scoped SPARQL; the compose generator adds SemPKM when the model names it. Decided in U9's ADR, alongside SQLite and PostgreSQL | U9, O2 |
| O5 | **Mental Model generator**: `manifest.yaml`, ontology, shapes, and views from IFML, as a package SemPKM installs | O1, O2, K3 |
| O6 | **SemPKM webhooks as a channel**, so `object.changed` can start a BPMN process | O4, ADR-0010 |
| R1 | **Model review checks**: the three checks above, plus T2's computing expressions and literals in drafts that repeat model facts; reported by `seams check` and in the viewer's health badge | none |
| R2 | **Copilot suggestions**: LLM-proposed model patches (move logic into DMN, merge shapes into a class, gist anchors), each accepted after validation, regeneration and review | R1, T5, C4 |
| R3 | **Generators that write generators**: an LLM drafts a template and `extract` step from a reference output, accepted when the golden test passes | K5, C4 |

R1 can start now. Its first three checks are a short script against existing models,
and it would have found the three repeated status lists. O1 and O2 are the foundation
for the rest of the data work. O4 and O5 are where SemPKM comes in, and they are
independent of each other: the Mental Model generator is useful even while the runtime
still writes to SQLite.

## Open questions

- **Where the ontology lives.** Is it one shared ontology across applications, as
  data-centric architecture prefers, with each SemanticSeams model importing it? Or one
  per model, imported by others? The first is the goal; the second is easier to start.
- **How much gist.** Anchoring every class in gist is cheap. Using gist's properties
  everywhere (magnitudes, categories) changes payload shapes. Should the forms and APIs
  hide that through `sh:name` and JSON-LD, or show it?
- **Lifecycle on the class or the shape.** A state belongs to the thing, not to a form.
  Should `seam:lifecycle` move from shapes to classes once classes exist?
- **One copilot or two.** SemPKM already ships an AI copilot against
  OpenAI-compatible endpoints. Should the model copilot reuse that connection setup, or
  stay a SemanticSeams tool?
