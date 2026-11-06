# ADR-0022: Ontology Notation — a `seam:Ontology` Model Graph per Model, gist Vendored and Pinned, Imports Resolved Offline

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M023/S03; backlog O1 (and B1, which asked for this decision);
research note [A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 3 and its open question "where the ontology lives"; builds on
[ADR-0001](./0001-named-graph-partitioning.md), [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0008](./0008-node-link-renderer.md) and [ADR-0021](./0021-vocabulary-versions.md)

## Context

A model's data side is SHACL shapes only. Nothing says what an `ExpenseShape` describes,
no example declares a class, and 16 of 16 property paths are bare IRIs. Principle 9
(data outlives applications) asks for the opposite: declare what things are, anchor the
classes in gist where the fit is honest, and let shapes target classes. The research note
proposes an ontology notation and shows, in
[`expense-gist.trig`](../research/examples/expense-gist.trig), the expense tutorial's
classes anchored in gist 14.0.0.

Four things need deciding before code:

- **Where the ontology lives.** The note's open question: one ontology shared across
  applications (the data-centric goal), or one per model, imported by others (easier to
  start). Backlog B1 defers its bounded-context owner to this ADR.
- **How gist is imported.** `owl:imports` names an IRI. The loader must not reach the
  network: the viewer, the runtime, the generators and CI all load offline, and the same
  model must give the same bytes (principle 6).
- **How versions are checked.** ADR-0021 versions SemanticSeams' own vocabularies and
  explicitly leaves imports of other ontologies (gist, a user's own) to O1.
- **How it is drawn.** The viewer already has a node-link card renderer for shape graphs
  (ADR-0008).

## Decision

### 1. `seam:Ontology` is a notation

`ontology/seam.ttl` gains one notation value beside `seam:ShapeGraph`:

```turtle
seam:Ontology a seam:Notation ; rdfs:label "OWL ontology (classes and properties)" .
```

That is the whole vocabulary impact: one value of an existing class, a compatible
widening under ADR-0021 section 7, so `seam` moves from `1.0` to `1.1` with no migration
file. Classes, properties and their relations are plain RDFS and OWL (`owl:Class`,
`rdfs:subClassOf`, `owl:DatatypeProperty`, `owl:ObjectProperty`, `rdfs:domain`,
`rdfs:range`), labelled with `rdfs:label` and defined with `skos:definition`
(principle 4: prefer an existing term). No seam predicate is added; the link from a shape
to a class is `sh:targetClass` (O2, M023/S04).

### 2. One ontology model graph per model, also an `owl:Ontology`

An ontology is a model graph like any other (ADR-0001): `<urn:seams:graph:model:{id}>`.
Its `seam:Model` is also the `owl:Ontology`, so the ontology's IRI is the model IRI and
ADR-0002 rule 1 (stable model IRIs) is the ontology's identity rule:

```trig
<urn:seams:graph:model:expense_ontology> {
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .

    :Expense a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Expense" ;
        skos:definition "Money an employee spent on the company's behalf and asks to have reimbursed." ;
        seam:inModel :expense_ontology .
}
```

- **Not ADR-0001's "ontology graphs".** Those are SemanticSeams' vocabulary modules
  (`<urn:seams:graph:ontology:seam>`), immutable per release. A user's ontology is
  authored with the model, so it is a model graph, edited through the one write path
  (ADR-0017) like the rest.
- **Exactly one `owl:versionIRI`.** ADR-0021's rule for vocabularies applied to the
  user's own: the ontology IRI never changes, the version IRI moves. The recommended form
  is the ontology IRI, a slash and `MAJOR.MINOR`; the shapes require one version IRI and
  do not parse it. Whether a load check and migrations apply to a user's ontology, as
  ADR-0021 asked, is deferred until a second model imports one (section 6): with one
  model per ontology there is nobody to migrate.
- **Every element is in the model.** Each `owl:Class`, property and category member in
  the graph carries `seam:inModel` and an `rdfs:label` (ADR-0002 rule 3: explicit IRIs,
  no blank nodes for classes). The seam shapes check both, as they do for other notations.
- **One per model, per bounded context.** A model (one directory or file, loaded as one
  `Dataset`) has one ontology: it is the vocabulary of one bounded context. The typed
  view returns a collection, sorted by IRI; a caller that needs the one calls `.only()`.

### 3. Per model now; shared by import later

The data-centric goal is one shared ontology that several applications import. It is not
where to start: no second application exists, and a shared ontology needs an owner, which
is B1's bounded context. So:

- **Now:** each model declares its own ontology graph. It imports gist and nothing else.
- **Later (B1):** an ontology owned by one context is imported by another by its version
  IRI, through the same resolution rule (section 4) with one more source of files: a
  project-declared directory of shared ontologies beside `ontology/vendor/`. The class
  view shows imported classes as read-only, as it does gist's. B1's ADR decides who owns
  a shared ontology and how its versions are released; this ADR guarantees only that
  moving an ontology out of a model and importing it back changes no IRI.

### 4. gist is vendored, pinned and resolved offline by import IRI

- **Vendored.** gistCore 14.0.0, the release SemPKM bundles and the research note's
  example uses, is committed as `ontology/vendor/gistCore14.0.0.ttl`: the release's
  `gistCore` Turtle file unchanged, licence header kept (CC BY 4.0, Semantic Arts).
  `ontology/vendor/README.md` records the source URL, the release tag and the file's
  SHA-256, and a test checks the checksum, so the file cannot drift by hand.
- **Pinned.** An import names a **version IRI**, never the bare ontology IRI: the model
  says which gist it was written against, as ADR-0021 has models say which vocabulary
  version they target. gist 14.1.0 and later are not vendored until a slice needs them;
  every gist term the expense example uses exists in both.
- **Resolved by IRI, offline.** The loader reads the header of each file in
  `ontology/vendor/` (under the same `ontology_dir` it already takes for ADR-0021) and
  indexes it by its `owl:Ontology` IRI and its `owl:versionIRI`, read from the file, not
  from a constant in code. Each `owl:imports` of a `seam:Ontology` graph then resolves:

  | The import names | Outcome |
  |---|---|
  | the `owl:versionIRI` of a vendored file | **resolved**: the import is that file |
  | the bare `owl:Ontology` IRI of a vendored file, or an IRI that starts with it but is not its version IRI (`…/gistCore14.1.0`) | **version mismatch**: `ResolutionError(<ontology>, owl:imports, "imports gistCore14.1.0; the vendored version is gistCore14.0.0")` |
  | the version IRI of a SemanticSeams vocabulary | **misplaced**: `ResolutionError(<ontology>, owl:imports, "…; declare vocabulary versions in the manifest graph (ADR-0021)")` |
  | anything else | **unresolved**: `ResolutionError(<ontology>, owl:imports, "imports <iri>, which no file in ontology/vendor/ declares")` |

  The subject is the ontology (the model IRI), the predicate `owl:imports`, and the
  detail names the import and what was expected. Imports are checked in sorted order and
  the first fault is raised, so the same model always gives the same error.
- **Imported triples stay out of the model's `Dataset`.** A resolved import is kept as a
  separate read-only graph the typed view can read (for an imported class's label and
  definition), never merged into the model's named graphs. So the model hash still hashes
  only the model's files (ADR-0007 rule 2; the import IRI pins the rest), the SHACL health
  check validates only the model, and no generator sees gist's 96 classes unasked.
- **`packages/seams` stays read-only and offline.** The vendored files are read as data
  with rdflib; nothing is downloaded, and nothing new is depended on.

### 5. Where import faults surface

- **`seams.load` checks imports by default**, as it checks vocabulary versions, so the
  CLI, the generators and the runtime refuse a model whose ontology does not resolve:
  `seams check` and `seams generate` report the `ResolutionError` as a model fault
  (exit 2) and write nothing.
- **The viewer keeps the fault as a health fact.** It loads with the import check off and
  runs the resolution itself, the way it already keeps a profile's `ResolutionError`
  (ADR-0018): the model still opens, the class view draws the model's own classes, and
  the health panel lists each import with its status (resolved to which vendored version,
  or the error's subject, predicate and detail).
- **Shape faults are ordinary violations.** A class without `rdfs:label` or
  `seam:inModel`, or an ontology without exactly one `owl:versionIRI`, fails the seam
  shapes and is reported where every violation is.
- **Health warnings, not faults.** A superclass that is neither declared in the
  ontology nor in a resolved import (a mistyped `gist:Transation`) is a warning in
  `seams check` and the health panel: rdflib does not reason, so it is a likely typo, not
  a contradiction.

### 6. The class view reuses the card renderer

The viewer draws a `seam:Ontology` graph with the ADR-0008 card renderer it uses for shape
graphs: one card per class, sorted by IRI, with its label, definition and properties
(those whose `rdfs:domain` is the class), and an edge to each superclass. A superclass
from an import is drawn as a read-only card in the import's own colour, labelled from the
vendored file. Nodes are sorted by (parent, id) and edges by (from, to, label), as for
shape graphs, so the layout is the same on every load. No new renderer and no new view
contract field: the projection is a pure Python module beside `viewer/shapegraph.py`,
tested in pytest, and the template only draws.

## Alternatives considered

- **One shared ontology now.** Rejected for now: no second application exists to share
  it, and a shared ontology needs an owner (B1). Section 3 keeps the move later free of
  renames.
- **The ontology in the shapes graph.** Rejected: the shapes are contracts (one per form,
  request or display), the ontology says what things are; one class has many shapes. Two
  notations, two graphs (principle 3).
- **Fetch imports over the network, with a cache.** Rejected: loading must work offline
  and be reproducible, and a cache is state outside the model.
- **Merge gist into the model's `Dataset`.** Rejected: it changes what the model hash,
  the SHACL health check and every generator see, for a read the class view alone needs.
- **A `seam:importsOntology` predicate, or the gist version in `seams.toml`.** Rejected:
  `owl:imports` of a version IRI is the standard form and the one ADR-0021 already uses
  (principle 4); the version is a fact about the model, so it lives in the model
  (principle 1).
- **A new renderer for class diagrams.** Rejected: the card renderer already draws
  labelled boxes with typed edges, and a second renderer would split the layout rules.

## Consequences

- `seam` becomes `1.1`; models that declare `seam/1.0` load unchanged (a lower minor).
- `ontology/vendor/` is new and holds third-party content under its own licence; the
  repository's licence notes must name it.
- The expense tutorial's chapter 9 gains an ontology graph (M023/S03), and O2 (M023/S04)
  can point shapes at its classes with `sh:targetClass` and make states category members.
- O3 (the JSON-LD context) and O5 (the SemPKM Mental Model) read classes from the typed
  ontology view instead of guessing them from shapes.
- R1's "shapes with no target class; undeclared paths" check gets something to suggest.
- Every caller that loads a model with an ontology needs `ontology/vendor/` present; the
  shipped-vocabularies location question in ADR-0021 now covers it too.

## Open questions

*Amended, 2026-11-06 (M028/S02, backlog B1): [ADR-0030](./0030-domains-and-bounded-contexts.md)
decides section 3's "later". An ontology is owned by exactly one `arch:BoundedContext`
(`seam:owns`); other contexts reach it by `owl:imports` of its version IRI, resolved first
against the ontology models in the same dataset, then `ontology/vendor/`. No ontology is
co-owned; a shared kernel is one owner's ontology. The text above is unchanged.*

- **gist upgrades.** Vendoring 14.1.0 beside 14.0.0 is compatible; a gist major that
  renames terms would need a migration in the user's ontology. Whether ADR-0021's
  migration layout applies to imports is open until it happens.
- **How much gist** (the note's second question): anchoring classes is decided here;
  using gist's properties (magnitudes, categories) in payloads is O2's and O3's call.
- **Lifecycle on the class** (B3): once classes exist, `seam:lifecycle` may move from
  shapes to classes. Not decided here.

  *Amended, 2026-11-06 (M028/S04, backlog B3): [ADR-0031](./0031-lifecycle-on-the-class.md)
  decides this. `seam:lifecycle` names an `owl:Class` (or, kept for compatibility, a
  `sh:NodeShape`); a shape's lifecycle is derived through `sh:targetClass`; a transition is
  a domain event that may `seam:publishesTo` a channel. The text above is unchanged.*
