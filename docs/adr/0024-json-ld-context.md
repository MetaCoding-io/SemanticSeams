# ADR-0024: The JSON-LD Context — One Context per Target-Classed Shape, Fields as Terms, Categories as Scoped `@vocab` Terms, Served by the Generated API

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M023/S05; backlog O3; research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 3 ("API payloads as JSON-LD"); builds on
[ADR-0007](./0007-execution-strategy.md), [ADR-0016](./0016-generator-protocol.md),
[ADR-0019](./0019-generation-trace.md), [ADR-0022](./0022-ontology-notation.md) and
[ADR-0023](./0023-shapes-target-classes.md), and answers ADR-0023's open questions on
reference fields and the RDF form of a category value as far as a context can

## Context

Since M023/S04 a shape can say what it describes (`sh:targetClass`), a field has a wire
name apart from its path (`sh:name`), a category field's options are the labels of
member IRIs, and a `sh:node` with fixed values flattens into one field. The typed view
(`seams.views.shapes`: `Shape.target_class`, `Shape.fields()`, `Field.name`,
`Field.datatype`, `Field.members`, `Field.node`) computes all of it once.

The payloads the generated API accepts and returns are still plain JSON: `{"description":
"Taxi", "amount": "42.50", "date": "2026-11-04", "status": "submitted"}`. The research note
asks that they be RDF too, without changing what a client that ignores RDF sees. A
JSON-LD 1.1 context does that: a client that applies it reads the same JSON as triples,
and a client that does not is unaffected.

Five things need deciding before the generator is written:

- **How many contexts.** One per API, one per model or one per shape. Chapter 9 has three
  target-classed shapes, and two of them have a `status` field with the same path and
  different members (`:ExpenseShape`'s are the expense states, `:PaymentShape`'s the
  payment states), so one context cannot define `status` once for both.
- **What a field maps to.** The name is the term and the path its IRI; the datatype,
  category members, flattened fields and reference fields each need a rule.
- **What the target class is for**, given that the wire payload carries no `@type` and
  ADR-0023 keeps the wire unchanged.
- **Where it is served.** The generated API answers htmx fragments (HTML); its only JSON
  bodies are problem+json errors, whose shapes have no target class.
- **Determinism and provenance.** A JSON file has no comments, so it cannot carry the
  header principle 7 asks for.

## Decision

### 1. One context per shape that has a `sh:targetClass`

The `jsonld` generator (`seams_gen.jsonld`, on the generator protocol of ADR-0016) writes
one context document per `sh:NodeShape` of the model whose `Shape.target_class` is set,
named `<shape local name>.jsonld` (`ExpenseShape.jsonld`) in its output directory.

- **Per shape, not per API.** A shape is what a payload conforms to, and ADR-0023 keeps
  field names unique within a shape, so a shape's terms never collide. Across shapes they
  do: `status` is `:ExpenseShape`'s expense state and `:PaymentShape`'s payment state, and
  the label `approved` is both an expense state and an approval outcome. A per-API context
  would need JSON-LD type-scoped contexts, which apply only to a node that carries
  `@type`, and the wire payload does not.
- **Shapes without a target class get no context.** Request, response and problem shapes
  that describe a message rather than a thing (`:NotificationShape`,
  `:NotifyProblemShape`) stay plain JSON contracts, as ADR-0023 section 1 leaves them. The
  generator writes nothing for them and reports nothing; R1's model review is where a
  missing target class is suggested.
- **A model with no target-classed shape** gives an empty output, not an error, as a
  generator with nothing to generate does today.

### 2. The context document

```json
{
  "@context": {
    "@version": 1.1,
    "Expense": "https://example.org/expenses/Expense",
    "amount": {
      "@id": "https://example.org/expenses/amount",
      "@type": "http://www.w3.org/2001/XMLSchema#decimal"
    },
    "status": {
      "@context": {
        "approved": "https://example.org/expenses/s_approved",
        "draft": "https://example.org/expenses/s_draft",
        "paid": "https://example.org/expenses/s_paid",
        "rejected": "https://example.org/expenses/s_rejected",
        "submitted": "https://example.org/expenses/s_submitted"
      },
      "@id": "https://example.org/expenses/status",
      "@type": "@vocab"
    }
  }
}
```

(`:ExpenseShape`, shortened to two of its five fields.) The rules, per field of
`Shape.fields()`:

| Field | Term definition |
|---|---|
| a datatype field (`Field.datatype` set, no members, no node) | `"<name>": {"@id": <path>, "@type": <sh:datatype>}`, every datatype including `xsd:string` |
| a field with neither datatype, members nor node | `"<name>": {"@id": <path>}` |
| a category field (`Field.members` set: a `gist:Category` class or an `sh:in` of IRIs) | `"<name>": {"@id": <path>, "@type": "@vocab", "@context": {<label>: <member IRI>, …}}` |
| a flattened `sh:node` field (`Field.node` set) | `"<name>": null` (section 4) |
| a reference field (`sh:class` of a class that is not a category) | `"<name>": null` (section 4) |

- **The term is `Field.name`, the IRI is `Field.path`** (ADR-0023 section 2). That is why
  `paid_on` reads as `:paidOn` and a migrated `description` as `gist:description`.
- **`@type` is the shape's `sh:datatype`.** A wire value stays a JSON string where it is
  one today (`"amount": "42.50"`), so the literal keeps its lexical form
  (`"42.50"^^xsd:decimal`); a JSON number would be converted by JSON-LD's number rules,
  which is a reason not to change the wire. `xsd:string` is written like any other
  datatype: one rule, and RDF 1.1 makes the typed and plain literal the same term.
- **The target class is a term**, its local name mapped to its IRI (`"Expense"`). The wire
  payload has no `@type` member and does not gain one (ADR-0023 keeps the wire), so the
  context cannot type the node by itself: a context adds no triple that the JSON does not
  hold. The term is there for a client or store that writes the RDF form of a payload
  (O4) and adds `"@type": "Expense"`, and the context route (section 5) is per shape, so
  the context a payload names says which class it describes.
- **Full IRIs, no prefixes, no `@vocab` at the top.** The file needs nothing else to be
  read, and no prefix choice can change its bytes. A top-level `@vocab` would turn every
  unknown JSON member into a triple in some namespace, which is the opposite of the
  shapes' contract.
- **`@version: 1.1`** is always written: property-scoped contexts are JSON-LD 1.1, and one
  rule is simpler than detecting them.

### 3. Categories: the wire value stays the label, the context maps it to the member

ADR-0023 keeps a category field's wire value as the member's `rdfs:label` and leaves its
RDF form to O3 or O4. The context does it: the term is coerced with `"@type": "@vocab"`,
so a string value is expanded as a term, and the term's **property-scoped context** maps
each member's label to its IRI. `"status": "submitted"` reads as
`<expense> :status :s_submitted`.

- **Scoped per field**, because labels repeat across categories: `approved` is
  `:s_approved` under `:ExpenseShape`'s `status` and `:outcome_approved` under
  `:ApprovalShape`'s `decision`. A scoped context applies only to the value of its term.
- **The labels and members are `Field.options` and `Field.members`**, the same pairs the
  form's `<option>`s come from, so the two cannot disagree (the file sorts them by label,
  section 6). Two members with one label
  are already a `ResolutionError` from the view (ADR-0023 section 3).
- **A label must be a usable term**: not empty, not starting with `@`, and containing no
  `:` (JSON-LD reads a term with a colon as a compact IRI and rejects one mapped to an
  unrelated IRI). A label that is not raises
  `GeneratorError(<member>, rdfs:label, "status of :ExpenseShape: label \"a:b\" of :s_x is not a JSON-LD term (…)")`.
  A label is free text for every other generator, so this is a generator-only fault
  (principle 5), listed with its reason in `tests/test_shape_generator_parity.py`.
- **An `sh:in` of literals** is not a category: its term is a datatype term, and the
  values stay literals.

### 4. What a context cannot say correctly maps to `null`

A context can rename, type and coerce a value; it cannot add a node or a triple that the
JSON does not hold. Two kinds of field need that, and both get a term mapped to `null`,
which JSON-LD defines as "this member is not RDF": a processor drops it instead of
guessing.

- **Flattened `sh:node` fields** (ADR-0023 section 4). `"amount": "42.50"` stands for a
  `gist:Magnitude` node with the free path's value and the fixed unit and aspect. Mapping
  the term to the outer path would state `<expense> gist:hasMagnitude "42.50"`, a literal
  where the shape requires a node; mapping it to the free path would put the number on
  the expense. Both are triples the shapes reject. The view exposes the nested shape, the
  free path and the fixed values (`Field.node`), so O4, which writes RDF, builds the node.
- **Reference fields**, an `sh:class` of a class that is not a category
  (`gist:refersTo sh:class :Expense`). The wire value is another entity's `id` string,
  not an IRI, and entities have no IRIs until O4 gives them one; `"@type": "@id"` would
  resolve the string against the document's base and invent one. ADR-0023's open
  question on how a reference is entered and sent stays with U9 and O4.

The rule: **a context never states a triple the shape would reject.** It may state fewer
than the shape requires (a payload read through it misses its amount); the RDF form that
is complete is O4's.

### 5. Served by the generated API, embedded in the route module

The fastapi generator (`seams_gen.fastapi`) gives each serving container, per
target-classed shape that one of its routed operations `seam:acceptsShape` or
`seam:returnsShape`:

- **A route `GET /contexts/<shape local name>.jsonld`** answering the context document
  with media type `application/ld+json`. The body is byte-identical to the file the
  `jsonld` generator writes: the fastapi generator's `extract` calls the `jsonld`
  generator's own extract and render, and embeds the text in the route module as a
  string constant. Embedding keeps the runtime image as it is (the generated Dockerfile
  copies the route module and the templates, and no file path is resolved at run time),
  and the handler stays a one-line return (P007: no branching). One route per context,
  sorted by path, not a `{name}` parameter, so an unknown name is FastAPI's 404 and no
  handler looks anything up.
- **A `Link` header** on the 2xx responses of each routed operation whose
  `seam:returnsShape` has a target class:
  `Link: </contexts/ExpenseShape.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"`.
  The path is relative to the API's root, as every generated route is. JSON-LD 1.1
  (section 6.1, "Interpreting JSON as JSON-LD") applies this header to `application/json`
  responses; today every such route answers an htmx fragment, which a JSON-LD processor
  ignores, so the header there names the context of the entity the route returns and
  takes effect unchanged when a route answers JSON. Problem+json and 422 responses are a
  different shape and carry no `Link`. One header per response: an operation returns one
  shape.
- **Computed in `extract`, printed by the template.** The route view model carries the
  context path and the header value; the template holds no logic (principle "templates
  hold text").
- A context route whose path equals another route's or an `ifml:path` raises
  `GeneratorError(<shape>, sh:targetClass, "…/contexts/ExpenseShape.jsonld is also the path of :op")`.

The `jsonld` generator's own file is the published artifact: the one a SemPKM Mental
Model (O5), a client generator or the docs point at. A project adds it in `seams.toml`
(`[[generators]] name = "jsonld"`, chapter 9 writes it under `generated/contexts`), and
`seams generate` records it in `seams.lock` with its trace sidecar (ADR-0019), whose
sources are the shape, its target class, the fields' paths and the category members.

### 6. Same model, same bytes; provenance in the trace, not the file

- **Sorted.** The file is `json.dumps(document, indent=2, sort_keys=True,
  ensure_ascii=False)` plus a trailing newline: terms sorted by name, scoped label terms
  by label. Nothing depends on graph or dictionary order.
- **No header, no model hash.** JSON has no comments, and a `MODEL_HASH`-like member would
  be a term. The trace sidecar and `seams.lock` say where the file came from and which
  model hash produced it (ADR-0019). So a context's bytes change only when its shape, its
  fields, its class or its members change, not on every model edit; the route module
  that embeds it keeps its usual header and hash.

### 7. Faults

Every fault names the fact, as `GeneratorError(subject, predicate, detail)`, and nothing
is written:

| Fault | Subject | Predicate | Shapes |
|---|---|---|---|
| two fields of one shape with one name (an explicit `sh:name` twice, or two paths with one local name and no `sh:name`) | the shape | `sh:name` | the explicit case is ADR-0023's seam shape (the parity case); the fallback case is the same raise site |
| the target class's local name is also a field name | the shape | `sh:targetClass` | generator-only: only a context puts both in one namespace |
| two target-classed shapes with one local name (one file name) | the second shape | `sh:targetClass` | generator-only: IRIs are unique, local names need not be |
| a category label that is not a JSON-LD term (section 3) | the member | `rdfs:label` | generator-only |
| a context path that is also a route path (section 5, fastapi generator) | the shape | `sh:targetClass` | generator-only |

A `ResolutionError` from the typed view (a target class no ontology declares, a broken
category or `sh:node`, ADR-0023 sections 1, 3 and 4) is passed on as the generator's
fault, as other generators do (`seams_gen._views.view_errors`).

### 8. No vocabulary change

Everything above reads SHACL, RDFS, gist and JSON-LD. No term is added, no seam shape
changes and `seam` stays `1.2`.

## Alternatives considered

- **One context per API.** Rejected: `status` and `approved` mean different things in two
  shapes of one API (section 1). Type-scoped contexts would separate them only for nodes
  with `@type`, which the wire payload does not carry.
- **One context per model.** Rejected for the same reason, and it would describe shapes
  an API never serves.
- **Add `"@type"` to every payload.** Rejected: it changes the wire, every form, the store
  rows and the scenarios, which ADR-0023 keeps fixed. The target class term is there for
  the writer of the RDF form.
- **Category values as IRIs or CURIEs on the wire.** Rejected again (ADR-0023): the label
  stays the wire value and the scoped context maps it.
- **A top-level `@vocab` for the model's namespace.** Rejected: unknown members would
  become triples, and a migrated path in another namespace (`gist:description`) would
  still need a term.
- **Flattened and reference fields mapped to the outer path.** Rejected: the triples
  would be ones the shapes reject (section 4). `null` says plainly that the context does
  not cover them.
- **Serve the `jsonld` generator's file from disk.** Rejected: the route module would
  resolve a path at run time and the Dockerfile generator would copy one more directory;
  embedding the same bytes, computed by the same code, needs neither.
- **A `Link` header only on `application/json` responses.** Rejected for now: no
  generated route answers JSON with a target-classed shape, so the header would never be
  sent. On the fragment routes it is harmless and names the context of what they return.

## Consequences

- Chapter 9 gains three contexts (`ExpenseShape`, `ApprovalShape`, `PaymentShape`), three
  routes and a `Link` header on the routes that return an expense or a payment. Its
  forms, payloads, store rows and scenarios do not change.
- A client that applies the context reads a payload as triples typed by the shape, with
  category values as member IRIs; a client that does not sees the same JSON as before.
- The route module changes whenever a context does, because it embeds it; the chat app's
  route module changes only if one of its shapes targets a class (none does today).
- Each new `GeneratorError` raise in `seams_gen.jsonld` and `seams_gen.fastapi` needs a
  parity case or a `GENERATOR_ONLY` entry (principle 5).
- O4 inherits the RDF form of flattened and reference fields and the `@type` of a stored
  payload; O5 can ship the context files as they are.

## Open questions

- **JSON answers.** The generated routes answer htmx fragments. Whether an operation can
  also answer `application/json` (by content negotiation, or a `comm:responseMediaType`
  on the operation) is a separate change; the `Link` header already says which context
  that answer would use.
- **Node identity.** The `id` field is a plain property (`:id`), and a payload read
  through the context is a blank node. Mapping `id` to `@id` needs an IRI scheme for
  entities, which is O4's.
