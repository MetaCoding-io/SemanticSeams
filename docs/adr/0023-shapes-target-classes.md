# ADR-0023: Shapes Target Classes — `sh:targetClass`, `sh:name` as the Wire Name, Lifecycle States as Category Members and Flattened `sh:node` Fields

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M023/S04; backlog O2; research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 3 and its example [`expense-gist.trig`](../research/examples/expense-gist.trig);
builds on [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0007](./0007-execution-strategy.md), [ADR-0014](./0014-scenarios-and-derived-tests.md),
[ADR-0021](./0021-vocabulary-versions.md) and [ADR-0022](./0022-ontology-notation.md)

## Context

Since M023/S03 a model can declare its classes in a `seam:Ontology` graph, but its shapes
do not point at them. Each shape still describes its fields as if nothing else existed:

- **No shape says what it describes.** `:ExpenseShape` has `rdfs:label "Expense"` and no
  link to the `:Expense` class the ontology declares.
- **A field's name is its path's local name.** `Field.name` is `local_name(sh:path)`, and
  the runtime keys a payload the same way (`seams_runtime.contracts`). So a path cannot
  be an ontology property such as `gist:description` without the form field and the
  payload key becoming `description` by accident, or `isCategorizedBy` by force.
- **States are copied strings.** `:ExpenseShape`'s status field carries
  `sh:in ( "draft" "submitted" "approved" "rejected" "paid" )`, a copy of the
  `rdfs:label`s of `:expense_lifecycle`'s states. Rename a state and the list is stale;
  nothing checks that the two agree. `:ApprovalShape`'s decision and `:PaymentShape`'s
  status copy lists the same way.
- **Nested values cannot be entered.** The research note models money as a
  `gist:Magnitude` node (`sh:node :MoneyShape`) whose unit and aspect are fixed
  (`sh:hasValue`) and whose number is the only thing a person types. Today a form field
  is one path with one literal, so such a shape has no form.

Today's reading of `sh:name` is a fifth fact: `Field.label` is `sh:name`, else
`rdfs:label`, else the name. No committed model sets `sh:name` on a property shape; the
viewer's editor (`viewer/editing.py`) already reads it as the field's name.

Two constraints frame the answer. The generated forms, API and payloads of the expense
tutorial must not change (the backlog row says "none; plain SHACL" for the vocabulary
impact), and ADR-0021 calls O2 the first change that is not purely widening, so its
version impact must be stated.

## Decision

### 1. `sh:targetClass` says what a shape describes

A shape that describes instances of a class declares it with `sh:targetClass`:

```trig
:ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
    sh:targetClass :Expense ;
    ...
```

- **Optional.** A shape without one stays valid and behaves as today. Request, response
  and problem shapes (`:NotifyProblemShape`) usually have none.
- **At most one per shape**, and it must be an `owl:Class` declared in a `seam:Ontology`
  graph of the same model (ADR-0022). A class that only exists in an import (a gist class)
  is not a target: subclass it in the model's ontology and target the subclass. Both are
  seam-shape violations (section 6).
- **`Shape.target_class`** returns the `OntologyClass` or `None`. Nothing is generated
  from it in this ADR. It is what O3 (the JSON-LD context) and B3 (the lifecycle on the
  class) read, and what R1's "shapes with no target class" check reports.
- **Validation is unchanged.** The runtime validates a payload against one shape with
  an explicit focus node (`focus_nodes`, `use_shapes`), so a target never selects other
  nodes. The runtime's contract graph leaves `sh:targetClass` out.

### 2. `sh:name` is the field's wire name

- **The name.** `Field.name` is the property shape's `sh:name` when it has one, else the
  local name of its `sh:path`, as today. The name is the form control's `name`, the JSON
  property of the API schema, the payload key the runtime validates and stores, the key
  of a generated `TypedDict` stub and the `path` the runtime reports in a 422 result.
- **The form.** One `sh:name` per property shape, a plain string matching
  `^[A-Za-z_][A-Za-z0-9_]*$` (it becomes a Python identifier in stubs and an HTML `name`).
  Two property shapes of one shape with the same explicit `sh:name` are a seam-shape
  violation. A name that only collides through the fallback keeps today's error (the
  stubs generator's `GeneratorError` on duplicate names).
- **The label.** `Field.label` is the property shape's `rdfs:label`, else the name.
  `sh:name` is no longer read as a label. No committed model is affected (no property
  shape sets `sh:name`), and a label with spaces belongs in `rdfs:label`. The research
  example's `sh:name "paid on"` becomes `sh:name "paid_on"`.
- **The path is the data.** The path says which property the value is in RDF; the name
  says what the value is called on the wire. A migration that moves a path to an ontology
  property (`:description` to `gist:description`) and sets `sh:name "description"` changes
  no form, schema or payload.
- **IFML is unchanged.** An `ifml:Parameter` stays `ifml:boundTo` the field's `sh:path`
  (for a flattened field, the outer path, section 4).

### 3. Categories: options are members, the wire value is their label

A **category field** is a property shape whose allowed values are IRIs of a fixed set,
and whose options are those IRIs' labels. There are two ways to write one:

- **`sh:class C`**, where `C` is a **category class**: an `owl:Class` of the model's
  ontology that is `rdfs:subClassOf gist:Category`, directly or through the model's own
  classes (rdflib does not reason; the view walks only declared `rdfs:subClassOf`
  triples). Its **members** are the IRIs typed `C` (`rdf:type C`) in any model graph.
  Lifecycle states join a category by being typed with it in the lifecycle graph:

  ```trig
  :s_draft a state:State , :ExpenseState ; rdfs:label "draft" ; seam:inModel :expense_lifecycle .
  ```

- **`sh:in` of IRIs**: the members are the listed IRIs, in list order. No ontology is
  needed. A list may not mix IRIs and literals.

An `sh:class` whose class is not a category class (`gist:refersTo sh:class :Expense`) is a
reference to another entity. It is not a category, gets no options and is handled as
today; reference fields are not part of this ADR.

**Options.** `Field.options` holds the members' `rdfs:label`s, so a template that renders
options today renders the same `<option>` elements. Each member needs exactly one
`rdfs:label`. The order is deterministic:

| Members | Order |
|---|---|
| an `sh:in` list | list order |
| all states of one lifecycle (`state:hasState` or `state:initial` of the same `state:StateMachine`) | **lifecycle order**: breadth-first from `state:initial` over `state:from`/`state:to`, ties by IRI, unreachable states last by IRI |
| no member is a state | by IRI |

Lifecycle order is what the copied lists already say: `draft submitted approved rejected
paid` for the expense and `recorded scheduled batched sent` for the payment.

**The wire value stays the label.** A form posts `submitted`, the API accepts `submitted`,
the runtime stores and reports `submitted`, and a scenario's `verify:expectState` still
compares labels, exactly as with the string list. Mapping a label to its member IRI is
for the RDF form of a payload (O3, O4), not for this ADR. Since the label is the wire
value, two members with the same label are an error.

**Errors.** Each raises `ResolutionError(subject, predicate, detail)` from the typed view,
and the detail names the field:

| Fault | Subject | Predicate | Detail, for example |
|---|---|---|---|
| a category class with no members | the shape | `sh:class` | `status: category :ExpenseState has no members` |
| a member without exactly one `rdfs:label` | the member | `rdfs:label` | `member of :ExpenseState (status of :ExpenseShape) needs exactly one rdfs:label` |
| two members with one label | the shape | `sh:class` (or `sh:in`) | `status: members :s_a and :s_b are both labelled "draft"` |
| members drawn from two lifecycles, or states mixed with non-states | the shape | `sh:class` | `status: members of :ExpenseState belong to :a_lifecycle and :b_lifecycle; no single order` |
| an `sh:in` list mixing IRIs and literals | the shape | `sh:in` | `status: sh:in mixes IRIs and literals` |

### 4. `sh:node` with fixed values flattens into one field

A property shape `[ sh:path P ; sh:node S ]` is a **flattened field** when the node shape
`S` has exactly one **free** property and every other property is **fixed**:

- a fixed property has exactly one `sh:hasValue` and nothing else but `sh:path`
  (and optionally `rdfs:label`);
- the free property has no `sh:hasValue`, no `sh:node`, and `sh:maxCount 1`;
- `S` may carry one `sh:class` on itself: the type of the nested node.

```trig
sh:property [ sh:path gist:hasMagnitude ; sh:node :MoneyShape ;
              sh:minCount 1 ; sh:maxCount 1 ; sh:order 1 ; sh:name "amount" ] .

:MoneyShape a sh:NodeShape ; sh:class gist:Magnitude ;
    sh:property [ sh:path gist:numericValue ; sh:datatype xsd:decimal ;
                  sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01 ] ;
    sh:property [ sh:path gist:hasUnitOfMeasure ; sh:hasValue :USD ] ;
    sh:property [ sh:path gist:hasAspect ; sh:hasValue gistd:_Aspect_monetary_value ] .
```

The field is the outer property with the free property's value constraints: its `iri`
(path) is `P`, its name, label, counts and order come from the outer property, and its
datatype, `sh:in` or category options, `sh:maxLength`, `sh:minInclusive` and the like
come from the free property. The view also exposes the nested shape, the free path and
the fixed `(path, value)` pairs, sorted by path, so O3 can write the nested node. On the
wire the field is one value (`"amount": "42.50"`), exactly as a flat `:amount` path is.

Flattening is one level: a free property with its own `sh:node` is not flattened. A
`sh:node` whose shape does not fit the rule raises
`ResolutionError(shape, sh:node, "amount: :MoneyShape has 2 free properties (gist:numericValue, gist:unit); a flattened field needs exactly one")`,
naming the outer shape, `sh:node`, the field and the nested shape's paths. A property
with both `sh:node` and `sh:datatype` is the same error.

A shape example (ADR-0014) may write a flattened value as the nested node; the view's
`example_values` reads it through the node to the free path, and reads a category value
given as a member IRI as the member's label, so derived tests keep their values.

### 5. One reading, in the typed view; generators and the runtime read `Field`

All of sections 2 to 4 is computed once, in `seams.views.shapes` (`Field` and `Shape`,
public names, pyright-strict). The generators read `Field.name`, `Field.label` and
`Field.options` in `extract` and keep their templates free of logic, as today.

The runtime's contract (`seams_runtime.contracts`) keys its fields by `Field.name` instead
of the path's local name, and **lowers** the shape when it builds its standalone contract
graph: a category property becomes `sh:datatype xsd:string` with `sh:in` of the members'
labels in option order, and a flattened property becomes a plain property on the outer
path with the free property's value constraints. pySHACL then validates the same wire
payload against the same constraints as before, so a 422 body for an unchanged model, and
for a migrated one, is identical: the same constraint component (`InConstraintComponent`
for a wrong state), the same value and the same `path` (now the field name). The status
the runtime writes is still the current state's `rdfs:label` under the key `status`.

### 6. Seam shapes, and `seam` moves to `1.2`

`ontology/shapes/seam-shapes.ttl` checks the shape-level faults so they surface in
`seams check`, the viewer's health panel and generation preconditions before any view
raises:

- at most one `sh:targetClass` per shape, an `owl:Class` of a `seam:Ontology` graph;
- `sh:name` at most once per property shape, matching the pattern, unique within a shape;
- a category class has at least one member, and each member has exactly one `rdfs:label`;
- a flattened `sh:node` has exactly one free property (section 4).

They are **new shapes**, not new properties of existing seam shapes: under ADR-0021
section 7 an added shape is compatible and an added property on an existing shape is
breaking. Their `sh:message`s name the shape, the field and the predicate, as the
`ResolutionError`s do; the view keeps its errors for callers that load without checking.

No vocabulary term is added: everything above is SHACL, RDFS and gist. The seam
vocabulary's shapes widen compatibly and the tool reads notation older tools misread (an
older tool would take `sh:name` for a label and draw a category field with no options),
so **`seam` moves from `1.1` to `1.2`** (ADR-0021 section 7, a minor bump, no migration
file). A model that uses `sh:name`, categories or flattened fields declares
`seam/1.2` in its manifest graph, and an older tool then refuses it by the ADR-0021 load
check instead of rendering it wrong. Models that declare `seam/1.0` or `seam/1.1` load
unchanged.

### 7. "The generated output is unchanged" means the rendered files

The expense tutorial's chapter 9 migrates to this notation (M023/S04) and its generated
forms, API and payloads must not change. Every generated module embeds the model's
`MODEL_HASH` (ADR-0007), and every `*.trace.json` sidecar and `seams.lock` records which
model terms and which hash an output came from (ADR-0019), so those must change with any
edit of the model. "Unchanged" therefore means: every rendered file under `generated/`
is byte-identical except its `MODEL_HASH` line; trace sidecars and the lock are
regenerated and committed as usual. The check is
`git diff --exit-code -I '^MODEL_HASH = ' -- examples/expenses/chapter-09/generated ':!*.trace.json'`.

## Alternatives considered

- **A `seam:fieldName` predicate.** Rejected: `sh:name` exists, SHACL tools display it,
  and principle 4 prefers an existing term. The cost is reading `sh:name` as a name, not a
  label; `rdfs:label` carries the label.
- **Wire values as member IRIs or CURIEs.** Rejected for now: it changes every form,
  payload, store row and scenario, which this slice must not. A label is already the
  value the runtime stores; IRIs on the wire are O3's JSON-LD question.
- **Any `sh:class` with members is a category.** Rejected: an entity class with no
  instances in the model (`:Expense`) would read as an empty category, and a reference
  field would grow options. `gist:Category` is the honest marker in a gist-anchored
  ontology; `sh:in` of IRIs covers models without gist.
- **Options sorted by label or IRI for lifecycle states.** Rejected: neither reproduces
  the authored order (`draft submitted approved rejected paid`), and lifecycle order is
  derivable from the model with no new fact.
- **Recursive flattening.** Rejected until a model needs it: one level covers a magnitude
  with a unit, and deeper nesting is a sub-form, not a field.
- **No version bump.** Rejected: the seam shapes change and a model written this way is
  misread by a `1.1` tool. A minor bump makes the load check refuse instead.

## Consequences

- Shapes can use ontology properties as paths and still give forms and payloads stable
  names; chapter 9's shapes follow the research example and target `:Expense`,
  `:Approval` and `:Payment`.
- The copied `sh:in` lists of states go: a renamed state renames its option, and a state
  that is added joins the field's options in lifecycle order.
- The runtime's contract module reads the typed shape view and keys by field name; for
  every committed model the keys are unchanged.
- `seam` becomes `1.2`; S02's tests that pin the shipped version move with it, and
  chapter 9 declares `seam/1.2`.
- The slice plan's T04 check `git diff --exit-code examples/expenses/chapter-09/generated`
  cannot pass after any model edit, because of `MODEL_HASH` and the trace sidecars; it
  uses the section 7 check instead.
- O3, O4 and O5 read `Shape.target_class`, category members and flattened fields' fixed
  values from one view instead of re-reading SHACL.

## Open questions

- **Finding the status field.** The runtime finds a shape's lifecycle field by the wire
  name `status`. With categories, the field whose members are the shape's
  `seam:lifecycle` states could be found from the model instead. Left for B3, which moves
  the lifecycle to the class.
- **Reference fields.** An `sh:class` to an entity class (`gist:refersTo sh:class
  :Expense`) is a link to another entity, today carried by the correlation parameter.
  How it is entered and sent is for O3 and U9.
- **The RDF form of a category value.** When payloads are stored as RDF (O4), the label
  maps to the member IRI; whether the map is done by the runtime or by the JSON-LD
  context (O3) is decided there.
