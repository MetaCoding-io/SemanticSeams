# ADR-0021: Vocabulary Versions — a Version IRI per Vocabulary, a Load Check, SPARQL Update Migrations and Warning-Level Deprecations

**Status:** Accepted

**Date:** 2026-11-03

**Source:** milestone M023/S01; backlog K6; research note
[A generator kit and a domain IDE](../research/2026-10-30-domain-ide-and-generator-kit.md)
section 3 (Boersma ch. 10); research note
[A data-centric model](../research/2026-10-31-data-centric-model-and-copilot.md)
section 3.1; builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md) and
[ADR-0017](./0017-write-path-and-editor.md); shares its classification with U8
(`seams diff`, M015/S01)

## Context

The vocabularies in `ontology/*.ttl` (`seam`, `arch`, `comm`, `deploy`, `ifml`, `proc`,
`state`, `verify`) each declare an `owl:Ontology` with a label and a comment, and no
version. A model does not say which vocabulary it was written for. Every change so far
has been widening (a new class, a new predicate), so every older model stayed valid.
M023's O2 is the first planned change that is not: states become category members
instead of copied `sh:in` lists, and the first rename or removal of a term will strand
every model that uses it, with no way to tell an out-of-date model from a wrong one.

The research note sets out what a language workbench does about this (Boersma ch. 10):
store the version with the content, check it on every load (same: proceed; newer than
the tool: refuse; older: migrate), write one small migration per version step, and
deprecate a term at warning level before removing it. It also notes that U8's shape
diff already sorts changes into the same two kinds, compatible and breaking.

ADR-0002 governs IRIs and already covers renames of *model* elements: a rename is
breaking unless the old IRI is kept as an `owl:sameAs` alias or every reference changes
in one commit. It says nothing about the vocabulary the model is written in. Two
constraints shape the answer: `packages/seams` is read-only and depends only on rdflib
and lxml, and the only code that writes model files is `seams_edit` (ADR-0017).

## Decision

### 1. A version IRI per vocabulary

Each `ontology/<name>.ttl` header gains two facts:

```turtle
<https://w3id.org/seams/seam> a owl:Ontology ;
    owl:versionIRI <https://w3id.org/seams/seam/1.0> ;
    owl:versionInfo "1.0" ;
    ...
```

- **The ontology IRI does not change.** Terms keep their `https://w3id.org/seams/<name>#`
  namespace across versions; only the version IRI moves. This is ADR-0002 rule 1 (stable
  IRIs) applied to the vocabulary: a version bump never renames a term by itself.
- **The version IRI is the ontology IRI, a slash, and `MAJOR.MINOR`.** Two numbers, no
  patch level: a vocabulary change either leaves models valid or it does not (section 6).
  A comment or label fix changes no version.
- **Versions are per vocabulary**, not one release number for the set: a breaking change
  to `ifml:` must not force a migration step on models that only use `arch:`.
- **The baseline is `1.0` for every vocabulary**: the vocabularies as they stand when
  S02 adds the version facts. `owl:versionInfo` repeats the number as a string for
  people and tools that read only the header.

### 2. A model declares the versions it targets with `owl:imports`

A model states, in the payload manifest graph ADR-0001 reserves
(`<urn:seams:graph:manifest>`), that it is an ontology importing the version IRI of each
vocabulary it uses:

```trig
<urn:seams:graph:manifest> {
    <urn:seams:graph:manifest> a owl:Ontology ;
        owl:imports <https://w3id.org/seams/seam/1.0> ,
                    <https://w3id.org/seams/arch/1.0> ,
                    <https://w3id.org/seams/proc/1.0> .
}
```

Why this form:

- **No new term.** `owl:imports` of a version IRI is the standard OWL way to say "this
  document was written against that version", and the research note's ontology example
  (`docs/research/examples/expense-gist.trig`) already imports gist that way. Principle 4
  prefers an existing term; a `seam:targetsVersion` predicate would add one for nothing.
- **In the model, not in `seams.toml`.** The viewer and the runtime load a model through
  `SEAMS_MODEL` with no project file, and the model is the source of truth. A version in
  the project file would be a fact about the model kept outside it.
- **In the manifest graph, not the seams graph or a model graph.** The declaration is
  about the files, not about any one `seam:Model` (one per notation) and not a
  cross-layer seam; the manifest graph is ADR-0001's place for facts about the model's
  files. Naming the graph's own IRI as the subject needs no newly minted IRI.

Rules for the declaration:

- A model with **no declaration for a vocabulary targets its `1.0`**. Every model written
  before S02 loads unchanged; S02 adds explicit declarations to the examples and the
  tutorial checkpoints.
- In a directory model, several files may declare; the **declarations must agree**. Two
  different version IRIs of one vocabulary are a `ResolutionError` naming
  `<urn:seams:graph:manifest>`, `owl:imports` and both versions.
- A version IRI of a SemanticSeams vocabulary that the tool has never published (for
  example `seam/1.7` when only `1.0` to `1.3` exist) is a `ResolutionError` naming it.
  Imports of other ontologies (gist, a user's own ontology for O1) are not checked by
  this ADR; O1's model-health checks cover them.

### 3. The load check

`seams.load` compares, per vocabulary, the version the model targets with the version the
tool ships, so the viewer, the runtime, the generators, the CLI and the editor all refuse
or migrate the same way:

| Model targets | Outcome |
|---|---|
| the same major, a minor at most the tool's | **same**: load as is. A lower minor only lacks additions, which are compatible by definition (section 6). |
| a newer version (a higher major, or the same major and a higher minor) | **newer**: `ResolutionError(<urn:seams:graph:manifest>, owl:imports, "targets seam 2.1; this tool supports seam up to 2.0")`. Nothing is loaded and nothing is written. |
| an older major | **older**: run the migrations from the model's major to the tool's, in order (section 4), then load the result. |

The check reads the tool's versions from the `owl:versionIRI` of the shipped vocabulary
files, not from a constant in code, so the version lives in exactly one place.

### 4. Migrations: one SPARQL Update file per major step

- **Location and name.** `ontology/migrations/<vocabulary>/<from>-to-<to>.ru`, one file
  per major step: `ontology/migrations/seam/1-to-2.ru`. A minor step has no migration,
  because it is compatible. A step from 1 to 3 runs `1-to-2.ru` then `2-to-3.ru`; a
  missing step file is a `ResolutionError` naming the vocabulary and the step.
- **Order.** Vocabularies in sorted name order; within one, steps in ascending order.
  Each file is SPARQL 1.1 Update (`DELETE`/`INSERT`/`WHERE`) run with rdflib over the
  loaded `Dataset`.
- **Partitioning is kept.** A migration matches `GRAPH ?g { ... }` and writes back into
  the same `?g`, so a triple never moves between the named graphs of ADR-0001. It
  touches only model data, never the ontology or shapes graphs.
- **Deterministic.** A migration may not call `NOW()`, `RAND()`, `UUID()`, `STRUUID()`
  or `BNODE()`, and may not mint IRIs from anything but the matched data. The same model
  and the same migrations give the same quads, so principle 6 (same model, same bytes)
  holds for everything generated from a migrated model.
- **The declaration moves with the data.** After the last step of a vocabulary, the
  loader replaces that vocabulary's `owl:imports` in the manifest graph with the tool's
  version IRI. The migration files do not edit the declaration themselves.
- **Renames build on ADR-0002.** A renamed term is a `DELETE { GRAPH ?g { ?s old:p ?o } }
  INSERT { GRAPH ?g { ?s new:p ?o } }` step. The old term stays in the vocabulary as
  deprecated (section 5) for at least one minor release before the major that removes
  it; an `owl:sameAs` alias between vocabulary terms is not used, because rdflib does
  not reason and every query would have to match both.

### 5. Where migration runs: in memory in `seams`, persisted only through `seams_edit`

- **`seams` migrates the loaded copy.** The load check and the migrations run on the
  in-memory `Dataset` the loader builds. `packages/seams` still writes nothing and
  depends on nothing new: rdflib already runs SPARQL Update, and the `.ru` files are
  read as data. The `Model` records the steps it applied (vocabulary, from, to), sorted,
  so callers can report them.
- **Older models keep working.** Every caller sees the migrated graph, so an older model
  can be browsed, checked and generated from without anyone editing it first.
  `seams check` reports each applied step as a warning (`vocabulary-migrated`), never
  as a problem, so CI tells the author the model is behind without failing.
- **`seams migrate` persists.** The command loads the model twice, as written and as
  migrated, takes the quad difference per named graph, and applies it as one patch
  through the ADR-0017 text writer. Comments and layout survive, the diff is the
  migration's triples only, and undo works as for any patch. No other code writes the
  migrated model.
- **The model hash is unchanged in meaning.** It still hashes the source content
  (ADR-0007 rule 2). A model migrated in memory has the hash of its files; once
  `seams migrate` writes them, the hash changes like any edit.

### 6. Deprecation: `owl:deprecated` on the term, an `sh:Warning` shape on its uses

- **On the term**, in its vocabulary file: `owl:deprecated true`, `dct:isReplacedBy` the
  term to use instead when there is one, and an `rdfs:comment` sentence saying why and
  in which major it goes. Deprecating a term is a minor bump: nothing becomes invalid.
- **On its uses**, in `ontology/shapes/seam-shapes.ttl`: one shape per deprecated term,
  with `sh:severity sh:Warning`. A deprecated predicate is targeted with
  `sh:targetSubjectsOf`, a deprecated class with `sh:targetClass`. Its `sh:message` says
  what is deprecated, since which version, when it goes and what to write instead. This
  is the project's first `sh:Warning`: until now every seam shape is a violation.
- **Warnings never fail.** `seams check`, `seams generate`'s precondition check and the
  viewer's health panel report `sh:Warning` results as warnings: they are listed and do
  not change `conforms`, the exit code or the generation outcome. The viewer already
  shows warning-level findings (profile and review findings) the same way.
- **Removal is a major step.** The major that removes the term ships the migration that
  rewrites its uses, and the shape's severity becomes `sh:Violation`, so a model that
  declares the new version and still uses the old term fails the shapes.
- A test (S02) checks that every `owl:deprecated` term has exactly one warning shape and
  every warning shape targets a deprecated term.

### 7. Version bumps use U8's classification

A vocabulary change is classified with the same two verdicts as `seams diff`:
**compatible** (widening; a minor bump, no migration) and **breaking** (a minor bump is
not enough; a major bump and a migration file). One classification, shared:

- The vocabulary's shapes (`seam-shapes.ttl`) are compared with U8's existing shape
  rules: a new required property, a tighter count or a changed datatype or class is
  breaking; a looser or dropped constraint is compatible.
- Terms in `ontology/*.ttl` add rules with the same `Change` record and verdicts: an
  added class or property, an `owl:deprecated` flag or a looser domain or range is
  compatible; a removed term, a renamed term or a narrower domain or range is breaking.
- The verdict constants and the `Change` record move from `seams_cli.diff` to a public
  module both comparisons import; the rules for domain shapes do not change.
- A gate (S02) fails when an `ontology/` change is classified breaking and the
  vocabulary's major did not move, or the step's migration file is missing.

## Alternatives considered

- **A `seam:targetsVersion` predicate on each `seam:Model`.** Rejected: a new term where
  OWL has one, and a model has one `seam:Model` per notation, so the version would be
  repeated and could disagree within one file.
- **The version in `seams.toml`.** Rejected: models load without a project file, and the
  model is the source of truth (principle 1).
- **One version for all vocabularies.** Rejected: every breaking change would force a
  migration step on every model, including models that do not use the changed
  vocabulary.
- **Migrations in Python.** Rejected: SPARQL Update is declarative, reviewable as a
  diff, runs on rdflib with no new dependency, and keeps migrations data rather than
  code in the read-only library.
- **Rewriting older models on load.** Rejected: `seams` must not write (package
  boundaries), and an author should see and commit a migration as one reviewable patch.
- **A generic SPARQL-based shape that flags any use of any `owl:deprecated` term.**
  Rejected for now: it needs the vocabulary graphs merged into the data graph under
  validation, which the health check deliberately does not do, and one shape per term
  gives each warning its own message.

## Consequences

- Every vocabulary file gains two header triples; nothing else in the vocabularies
  changes in S02. Every existing model keeps loading because a missing declaration means
  `1.0`.
- The manifest graph becomes used for the first time. The authoring guide and the
  chapter that introduces it document the `owl:imports` declaration.
- Breaking vocabulary changes become possible without stranding models, which unblocks
  O2's change to states as categories and any later rename.
- A newer model loaded by an older tool fails fast with an error naming the version,
  rather than failing later on an unknown term.
- The first `sh:Warning` shapes mean every place that reads SHACL results must
  distinguish severities; S02 makes `seams check`, generation preconditions and the
  viewer do so.
- The vocabulary's breaking-change check and `seams diff` share one classification;
  improving a rule improves both.

## Open questions

- **How `seams` finds the shipped vocabularies.** Today `seams check` reaches
  `ontology/` through the repository layout. The load check must work in every caller,
  so S02 either ships `ontology/` (vocabularies, shapes and migrations) as package data
  of `seams`, or passes its location in; package data is preferred, with `ontology/`
  still the single source.
- **Migrating native payloads.** A vocabulary change that affects how BPMN or DMN
  elements are lifted cannot be expressed as SPARQL Update over the graph. None is
  planned; such a change would need its own ADR.
- **Versions of the user's own ontology.** O1 gives a user's ontology an
  `owl:versionIRI` too. Whether the same load check and migration layout apply to it,
  under the project rather than under `ontology/`, is for O1's ADR.
- **When a warning shape becomes a violation without a major.** This ADR ties the
  severity change to the removing major. A project may want a stricter mode that treats
  deprecation warnings as problems in CI; that is a `seams check` option, not decided
  here.
