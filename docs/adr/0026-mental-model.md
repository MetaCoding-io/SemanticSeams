# ADR-0026: The Mental Model — a SemPKM Package Written from the Ontology, the Target-Classed Shapes and the IFML Views, in SemPKM's Namespace

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M024/S03; backlog O5; research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 4; answers the format [ADR-0025](./0025-sempkm-store.md) section 12 left open,
and builds on [ADR-0016](./0016-generator-protocol.md),
[ADR-0019](./0019-generation-trace.md), [ADR-0022](./0022-ontology-notation.md),
[ADR-0023](./0023-shapes-target-classes.md) and [ADR-0024](./0024-json-ld-context.md)

## Context

Since M024/S02 the runtime writes the entities of a SemPKM-stored shape into SemPKM,
typed by the shape's `sh:targetClass` (ADR-0025). SemPKM stores them, but it knows nothing
about them: no form, no table, no type in its navigation. SemPKM learns about a kind of
data from a **Mental Model**, a directory it installs through `POST /api/models/install`
with the directory's path. Backlog O5 asks the model to write that directory.

SemPKM's own code is the contract (`backend/app/models/manifest.py`, `loader.py`,
`validator.py` and `services/models.py`, read at the version this ADR was written
against, with `models/basic-pkm` as its example):

- **`manifest.yaml`** is validated by a Pydantic schema. `modelId` matches
  `^[a-z][a-z0-9-]*$` (2 to 64 characters), `version` matches `^\d+\.\d+\.\d+$`, `name` is
  1 to 200 characters, `description` at most 2000 and optional, `namespace` must equal
  `urn:sempkm:model:<modelId>:`, `prefixes` defaults to none, and `entrypoints` names the
  `ontology`, `shapes` and `views` files (defaulting to `<kind>/<modelId>.jsonld`) and,
  optionally, `seed`, `rules`, `dashboards`, `workflows` and `docs`. `settings` and
  `icons` are optional lists.
- **The entrypoints are JSON-LD** with no remote `@context`: the loader refuses any
  `http(s)` context, because SemPKM's containers have no network to fetch it from.
- **Every subject IRI must be in the archive's namespace.** The validator rejects, as an
  error, any non-blank subject of the ontology, shapes, views or seed graph that does not
  start with `urn:sempkm:model:<modelId>:` or one of four fixed prefixes
  (`http://www.w3.org/`, `http://purl.org/dc/`, `https://schema.org/`,
  `http://xmlns.com/foaf/`). Objects are not checked.
- **Types come from the shapes.** SemPKM's type list, forms and default columns read
  every `sh:NodeShape` with a `sh:targetClass` in the shapes graph. The ontology graph only
  adds class labels and documentation; a class it lacks is still listed.
- **Views are `urn:sempkm:vocab:ViewSpec` nodes** read by the view service through
  `urn:sempkm:vocab:targetClass`, `rendererType`, `sparqlQuery`, `columns` (a
  comma-separated list of the query's variable names) and `sortDefault`. SemPKM adds the
  `FROM` clauses that scope a view's query to current state.
- A missing `README.md` is a **warning**, not an error, and does not stop the install.

The model already says most of what a Mental Model holds: the ontology model of
ADR-0022 (an `owl:Ontology` with a label and a version IRI), the shapes with target
classes of ADR-0023, and the IFML components that `seam:reads` a shape. Four things need
deciding:

- **Which facts fill the manifest**, and what happens when one is missing.
- **IRIs.** The model's terms are in the model's namespace (`https://example.org/expenses/`
  in the tutorial); SemPKM accepts no subject outside its own. The data the runtime writes
  is typed by the model's class IRIs, so they cannot be renamed.
- **Which views**, and how their queries are built.
- **gist.** ADR-0025 section 8 says the Mental Model states the gist version it targets.

## Decision

### 1. The package: one directory, four files

A new `mentalmodel` generator (`seams_gen.mentalmodel`, on the generator protocol of
ADR-0016) writes one Mental Model per project into its output directory:

```text
<out>/manifest.yaml
<out>/ontology/<modelId>.jsonld
<out>/shapes/<modelId>.jsonld
<out>/views/<modelId>.jsonld
```

The layout is SemPKM's default entrypoint layout, and the manifest names the three files
explicitly. No `seed`, `rules`, `dashboards`, `workflows` or `docs` file is written
(section 4). A project adds the generator in `seams.toml` (`[[generators]] name =
"mentalmodel"`); `seams generate` records the four files in `seams.lock` with their
trace sidecars (ADR-0019). A SemPKM deployment installs the directory with
`POST /api/models/install`.

### 2. The ontology model is the Mental Model

A Mental Model is written for **the model's one `seam:Model` with `seam:notation
seam:Ontology`** (ADR-0022): that `owl:Ontology` is what the package describes, and its
facts fill the manifest. A model with no ontology model, or with more than one, is a
fault (section 10): the generator does not guess which one a package is for.

### 3. IRIs: SemPKM's namespace for the package, the model's IRIs for the data

**The archive's own nodes are minted in `urn:sempkm:model:<modelId>:`; the model's domain
terms keep their IRIs and appear only as objects.**

- **Archive nodes** are the ontology node, the shapes (and the shapes they reach by
  `sh:node`) and the views. Each is `urn:sempkm:model:<modelId>:<local name>`, where the
  local name is that of the model term it comes from (`seams.namespaces.local_name`, the
  part after the last `#` or `/`): `:ExpenseShape` becomes
  `urn:sempkm:model:expense-ontology:ExpenseShape`. Each carries
  `prov:wasDerivedFrom` the model term, so the package says where every node came from.
  A `sh:node` that names a shape is rewritten to that shape's archive IRI.
- **Domain terms keep the model's IRIs**: target classes, property paths, `sh:class`
  classes, `sh:in` and category members. The runtime writes SemPKM objects typed by
  `sh:targetClass` with values on `sh:path` (ADR-0025 section 3), so the shapes and views
  must name those same IRIs. They appear only in object position (`sh:targetClass`,
  `sh:path`, `urn:sempkm:vocab:targetClass`), which SemPKM's validator does not check.
- **Why not rename the domain terms too.** A `urn:sempkm:model:` class would not match
  the type of a single object the runtime writes, and SemPKM applies no
  `owl:equivalentClass` entailment that could join them. Renaming the data's IRIs to
  satisfy one consumer would also break ADR-0002: a model IRI is the term's identity.
- **Why not ship the domain terms as subjects.** SemPKM refuses the install. The
  ontology file therefore cannot carry the model's `owl:Class` declarations (section 5),
  which is this ADR's main open question.

ADR-0002's rules are untouched: the archive IRIs are a rendering of model terms for one
consumer, derived from them one-to-one, and never read back into the model.

### 4. The manifest

| Key | Value | Model fact | Missing |
|---|---|---|---|
| `modelId` | the ontology's IRI local name, lowercased, `_` replaced by `-` (`expense_ontology` gives `expense-ontology`) | the ontology's IRI | always present; a result SemPKM's pattern rejects is a fault on the ontology, `rdf:type` |
| `version` | the literal, as written | the ontology's one `owl:versionInfo`, `MAJOR.MINOR.PATCH` | fault on the ontology, `owl:versionInfo` |
| `name` | the literal | the ontology's one `rdfs:label`, at most 200 characters | fault on the ontology, `rdfs:label` |
| `description` | the literal | the ontology's `rdfs:comment`, at most one, at most 2000 characters | omitted (SemPKM's default is empty) |
| `namespace` | `urn:sempkm:model:<modelId>:` | none: SemPKM fixes it from `modelId` | — |
| `entrypoints` | `ontology`, `shapes` and `views`, each `<kind>/<modelId>.jsonld` | none: the layout of section 1 | — |

- **The identity comes from the IRI, not the label.** The ontology's IRI is stable by
  ADR-0002; a label is free text that may change with no change in meaning. Lowercasing
  and replacing `_` is an encoding of that IRI into SemPKM's alphabet, not a new fact.
- **`version` is `owl:versionInfo`, not parsed out of `owl:versionIRI`.** A version IRI is
  an IRI; reading a number out of its last segment would be a guess about its form.
  `owl:versionInfo` is OWL's own annotation for the version string. SemPKM needs three
  numbers, so a value of another form is a fault. Chapter 10 states
  `owl:versionInfo "1.0.0"` beside its version IRI `…/expense_ontology/1.0`.
- **Optional keys are omitted unless the model states them, and no model fact states
  them today.** `prefixes`: a TriG file's prefix bindings are syntax, not facts, and no
  file of the package uses a prefix (section 9). `icons` and `settings` have no
  vocabulary in the model. `seed`, `rules`, `dashboards` and `workflows`: the model has
  no instance data, SHACL rules or dashboards for SemPKM; a seed would also need its
  subjects in SemPKM's namespace. `docs`: the model has no document to ship, so SemPKM
  warns `missing-docs` and installs. `manifest_version` is left to SemPKM's default.
  `entailment_defaults` is not part of SemPKM's schema at this version and is not
  written either.

The chapter 10 manifest:

```yaml
modelId: "expense-ontology"
version: "1.0.0"
name: "Expense Ontology"
namespace: "urn:sempkm:model:expense-ontology:"
entrypoints:
  ontology: "ontology/expense-ontology.jsonld"
  shapes: "shapes/expense-ontology.jsonld"
  views: "views/expense-ontology.jsonld"
```

Keys are written in that order, `description` after `name` when present, and every
value as a JSON string, which YAML reads as a double-quoted scalar: no value is ever
read as a number, a date or a boolean.

### 5. The ontology file: the ontology node, stating gist 14.0.0

`ontology/<modelId>.jsonld` holds one node, `urn:sempkm:model:<modelId>:<ontology local
name>`, typed `owl:Ontology`, with:

- `rdfs:label`, `owl:versionInfo` and, when stated, `rdfs:comment`, as in the manifest;
- `owl:imports` each version IRI the model's ontology imports, which states the gist
  version (section 7);
- `prov:wasDerivedFrom` the model ontology's `owl:versionIRI`.

The model's `owl:Class` declarations (labels, `skos:definition`s, gist superclasses) are
**not** written: their subjects are the model's IRIs, and SemPKM refuses them (section
3). SemPKM still lists every target class from the shapes; it shows a class's IRI where
it would show the class's label.

### 6. The shapes file: the target-classed shapes, as SHACL

`shapes/<modelId>.jsonld` holds every `sh:NodeShape` with a `sh:targetClass`
(ADR-0023), and every shape those reach by `sh:node`, transitively. For each:

- the shape node under its archive IRI (section 3), with `prov:wasDerivedFrom` the model
  shape;
- every triple of the model shape whose predicate is in the SHACL namespace, or is
  `rdfs:label` or `rdfs:comment`, and the same for the blank nodes those reach (property
  shapes and `sh:in` lists). `seam:` facts, which belong to the seams graph (ADR-0001),
  are not copied, and neither are other annotations.

These are the shapes the runtime validates against before it writes (ADR-0025 section
3), so SemPKM's forms ask for and check what the generated app asks for and checks. Every
target-classed shape is written, not only the SemPKM-stored ones: the package describes
the model's data, and which store holds a shape's entities is a deployment fact the
generator does not need.

### 7. gist 14.0.0

The ontology node `owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0>`
when the model's ontology does, which is how the package states the gist version it
targets (ADR-0025 section 8). SemPKM resolves no import; the triple is a statement for
people and tools reading the package. An ontology that imports any other gist version is
a fault (section 10), as it is at runtime load for a SemPKM store: SemPKM bundles gist
14.0.0, and the package must not claim another.

### 8. The views file: one table per IFML list or details view

`views/<modelId>.jsonld` holds one `urn:sempkm:vocab:ViewSpec` per `ifml:List` or
`ifml:Details` of the model's interaction models that `seam:reads` a shape. An IFML
component that reads no shape gets no view.

| Predicate | Value |
|---|---|
| `@id` | `urn:sempkm:model:<modelId>:<component local name>` |
| `rdfs:label` | the component's `rdfs:label` |
| `prov:wasDerivedFrom` | the component |
| `urn:sempkm:vocab:targetClass` | the shape's `sh:targetClass` |
| `urn:sempkm:vocab:rendererType` | `"table"` |
| `urn:sempkm:vocab:columns` | the shape's `Field.name`s in `Shape.fields()` order, joined by `,` |
| `urn:sempkm:vocab:sparqlQuery` | the query below |

The query selects `?s` and one variable per column, scoped to the class and one
`OPTIONAL` per field, in column order:

```sparql
SELECT ?s ?description ?amount ?date ?status ?id
WHERE { ?s a <https://example.org/expenses/Expense> .
  OPTIONAL { ?s <https://example.org/expenses/description> ?description }
  ...
  OPTIONAL { ?s <https://example.org/expenses/id> ?id } }
```

(written on one line in the file). A flattened `sh:node` field (`Field.node`, ADR-0023
section 4) follows the edge one level, as the store's reads do (ADR-0025 section 6):
`OPTIONAL { ?s <path> [ <free path> ?name ] }`, with a blank node in the pattern so no
helper variable can collide with a column. A category field's column holds the member
IRI the store keeps.

- **Table only.** A list or details view shows the fields of entities of one class, which
  is a table. SemPKM's `card` and `graph` renderers need a title and subtitle field and an
  edge set that no model fact names.
- **No `sortDefault`.** The model states an order of fields (`sh:order`), not an order of
  rows. SemPKM's default applies.
- **Every field is a column**, including one named `id`; the generator singles out no
  field by name. A column the store does not hold is empty.

An example node (`:expense_list`, shortened to two columns):

```json
{
  "@graph": [
    {
      "@id": "urn:sempkm:model:expense-ontology:expense_list",
      "@type": "urn:sempkm:vocab:ViewSpec",
      "http://www.w3.org/2000/01/rdf-schema#label": "My Expenses",
      "http://www.w3.org/ns/prov#wasDerivedFrom": {
        "@id": "https://example.org/expenses/expense_list"
      },
      "urn:sempkm:vocab:columns": "description,amount",
      "urn:sempkm:vocab:rendererType": "table",
      "urn:sempkm:vocab:sparqlQuery": "SELECT ?s ?description ?amount WHERE { ?s a <https://example.org/expenses/Expense> . OPTIONAL { ?s <https://example.org/expenses/description> ?description } OPTIONAL { ?s <https://example.org/expenses/amount> ?amount } }",
      "urn:sempkm:vocab:targetClass": {
        "@id": "https://example.org/expenses/Expense"
      }
    }
  ]
}
```

### 9. Same model, same bytes

- **JSON-LD without a context.** Each JSON-LD file is a top-level object with one
  `@graph`, full IRIs as keys and `@type`s, `{"@id": …}` for IRI objects, typed literals
  as `{"@value": …, "@type": …}` (plain strings for `xsd:string`), blank nodes nested
  where they are used, and RDF lists as `{"@list": […]}` in list order. No `@context` means
  no remote context for SemPKM's loader to refuse, and no prefix choice that could change
  the bytes.
- **Sorted.** `@graph` nodes are sorted by `@id`; the property shapes of a shape by
  `Shape.fields()` order; other multi-valued properties by value. A file is
  `json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)` plus a trailing
  newline. The manifest's keys are in the fixed order of section 4.
- **No header, no model hash, no timestamp.** As for ADR-0024's contexts, the trace
  sidecar and `seams.lock` say which model produced the files. A file's bytes change only
  when the facts it is made from change.

### 10. Faults

Every fault names the fact, as `GeneratorError(subject, predicate, detail)`, and nothing
is written. None is stated by the seam shapes: the facts a Mental Model needs are
required only when a project asks for one, so each is generator-only (principle 5).

| Fault | Subject | Predicate |
|---|---|---|
| no `seam:Model` has `seam:notation seam:Ontology` | `seam:Ontology` | `seam:notation` |
| more than one ontology model | the second, by IRI | `seam:notation` |
| the `modelId` from the ontology's IRI does not match `^[a-z][a-z0-9-]*$`, or is not 2 to 64 characters | the ontology | `rdf:type` |
| no `owl:versionInfo`, more than one, or one that is not `MAJOR.MINOR.PATCH` | the ontology | `owl:versionInfo` |
| no `rdfs:label`, more than one, or longer than 200 characters | the ontology | `rdfs:label` |
| more than one `rdfs:comment`, or longer than 2000 characters | the ontology | `rdfs:comment` |
| an `owl:imports` of a gist version other than 14.0.0 | the ontology | `owl:imports` |
| two archive nodes with one local name (one archive IRI) | the second, by IRI | `rdf:type` |
| an IFML list or details view that reads more than one shape | the component | `seam:reads` |
| an IFML list or details view that reads a shape with no `sh:targetClass` | the shape | `sh:targetClass` |
| a `Field.name` of a viewed shape that is not a SPARQL variable name (`^[A-Za-z_][A-Za-z0-9_]*$`) | the shape | `sh:name` |

A `ResolutionError` from the typed view is passed on as the generator's fault, as other
generators do (`seams_gen._views.view_errors`). Through `seams generate` and `seams.lock`
these surface as any generator's faults do; a project that does not list `mentalmodel`
never sees them.

### 11. No vocabulary change

Everything above reads OWL, RDFS, SHACL, PROV, IFML and seam facts that exist. No term is
added and no seam shape changes. Chapter 10 gains one fact, `owl:versionInfo`, from
OWL.

## Alternatives considered

- **Domain terms renamed into `urn:sempkm:model:`.** Rejected: the runtime's objects are
  typed by the model's classes, SemPKM would show none of them, and a model IRI is the
  term's identity (section 3).
- **`owl:equivalentClass` from SemPKM-namespace classes to the model's.** Rejected:
  SemPKM applies no equivalence entailment, so the views and forms would still miss the
  objects, and the archive would declare a second class for every class.
- **Ship the model's `owl:Class` declarations anyway.** Rejected: SemPKM refuses the
  install (`iri-namespace` errors). Section 5 writes what it accepts and the open question
  below asks for the rest.
- **`modelId` and `name` from one fact (a slug of the label).** Rejected: a label is free
  text, and a typo fixed in it would change the package's identity, which SemPKM uses to
  find the installed model.
- **`version` read from the end of `owl:versionIRI`.** Rejected: section 4.
- **A new `seam:` term for the package id or version.** Rejected: `owl:versionInfo` exists
  for the version, and the ontology's IRI already is an identity.
- **Views per shape rather than per IFML component.** Rejected: the IFML model is where
  the model says which collections people look at, and what they are called; a shape no
  view reads has its form in SemPKM but no named table, and SemPKM's generic browser
  still lists it.
- **Card and graph views.** Rejected for now: section 8.
- **Copy the ADR-0024 context files into the package.** Rejected: SemPKM does not read
  them, and its loader needs every graph inline; a payload's context is the generated
  API's concern.
- **YAML through a YAML serializer with default settings.** Not chosen as the rule: the
  bytes would depend on the serializer's quoting and key order. Section 4 fixes both,
  whichever way the generator writes the text.

## Consequences

- **T02** adds `seams_gen.mentalmodel`, registered with the other built-ins and in
  `seams_gen.sources`, with each raise of section 10 as a generator-only entry in the
  parity inventory.
- **T03** gives chapter 10 `owl:versionInfo "1.0.0"`, adds the generator to its
  `seams.toml`, commits `generated/mental-model/`, and installs it into the chapter's
  SemPKM in the end-to-end tests.
- SemPKM's workspace lists expenses, approvals and payments with the model's forms, and
  shows the IFML views as tables. Its classes show IRIs instead of labels until the open
  question below is answered.
- SemPKM's background SHACL validation sees a category value (an `:ExpenseState` member)
  with no `rdf:type`, because the members are not in SemPKM, so its `sh:class`
  check can fail there; SemPKM validates after commit, so this does not block writes. See the open questions.
- A model with no ontology model cannot have a Mental Model; the chat app has none and
  does not list the generator.

## Open questions

- **Domain subjects in SemPKM.** Shipping the model's `owl:Class` declarations, and its
  category members as seed data, needs SemPKM to accept subjects in namespaces the
  manifest declares (for example under `prefixes`), which is a SemPKM change. When it
  can, section 5 writes the ontology model's graph and a seed of the members, and the
  category `sh:class` checks above can pass.
- **Icons, settings and documentation.** The model has no vocabulary for a type's icon
  and colour, for user settings or for a package README. Each needs a model fact first;
  the generator does not invent them.
- **Card and graph renderers.** A view could name its title field or its edges in IFML.
  Until it does, only tables are written.
