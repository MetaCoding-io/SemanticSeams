# ADR-0039: Data Classification — a Field Holds Personal Data When Its Property Shape States W3C DPV's `dpv:hasPersonalData` With a Category IRI; No Seam Term, No Vendored DPV

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M031/S01; backlog X3; research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.7;
builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0021](./0021-vocabulary-versions.md),
[ADR-0022](./0022-ontology-notation.md) and
[ADR-0023](./0023-shapes-target-classes.md)

## Context

The UML note's section 3.7 asks for "which screens show personal data to which roles"
as a query. The graph already holds every part of the answer but one: a screen
(`ifml:ViewContainer`) contains components that `seam:reads` a shape, and an
`odrl:Permission` names the role that may use a screen's operations. Nothing says which
fields of a shape hold personal data, so the question has no starting point.

Principle 4 says vocabulary is earned and an existing term beats a new one. The W3C
Data Privacy Vocabulary (DPV, a Community Group report) is the established vocabulary
for this:

- `dpv:hasPersonalData` (`https://w3id.org/dpv#hasPersonalData`) indicates association
  with personal data. Its range is `dpv:PersonalData`; DPV states no domain, so it may
  be said of any resource.
- The personal data extension `pd:` (`https://w3id.org/dpv/pd#`) names the categories:
  `pd:Name`, `pd:EmailAddress`, `pd:TelephoneNumber`, `pd:BankAccount` and some hundreds
  more, each a subclass of `dpv:PersonalData` and usable as an instance (DPV's own
  examples write `dpv:hasPersonalData pd:EmailAddress`).

## Decision

### 1. The annotation is `dpv:hasPersonalData <category>` on the field's property shape

A field holds personal data when its `sh:property` node states `dpv:hasPersonalData`
with the IRI of a personal data category:

```trig
:NotificationShape a sh:NodeShape ;
    sh:property [ sh:path :recipient ; sh:datatype xsd:string ; sh:maxCount 1 ;
                  dpv:hasPersonalData pd:Username ] .
```

- **The subject is the property shape**, not the node shape and not the RDF property.
  A shape is the unit a screen reads (`seam:reads`), and the same RDF property may be
  personal in one shape and not in another (an organisation's name against a person's).
- **The object is a category IRI.** A `pd:` concept is the expected value. A model may
  name its own category instead (an IRI in its ontology model, ADR-0022), for data DPV
  does not list; the shapes require an IRI, not a `pd:` one.
- **One or more per field.** A field that holds two kinds of personal data states both.
- **No seam term.** The annotation is a DPV fact about a shape, so it lives in the shape
  graph beside the field, not in the seams graph. ADR-0001 keeps `seam:` predicates in
  the seams graph; it says nothing against another vocabulary's facts in a model graph.
- **No version bump.** `seam` gains no term. The two shapes in section 2 are new shapes,
  which the vocabulary gate (ADR-0021 section 7) classes as compatible.

### 2. Two seam shapes check it

In `ontology/shapes/seam-shapes.ttl`, section "Data classification (ADR-0039)":

- **`seamsh:PersonalDataCategoryShape`** (every `sh:NodeShape`): a `dpv:hasPersonalData`
  value that is not an IRI is a violation on the shape, with result path
  `dpv:hasPersonalData`, naming the field (its `sh:name`, else its path) and the value.
  A string such as `"email address"` is the fault it catches: it reads as a category to
  a person and as nothing to a query.
- **`seamsh:PersonalDataPlacementShape`** (every subject of `dpv:hasPersonalData`): the
  subject must be an `sh:property` of a shape with an `sh:path`. An annotation on the
  node shape, or on a property shape without a path, would be silently left out of the
  screens query, so it is a violation naming the subject and `dpv:hasPersonalData`.

No generator reads the annotation, so neither shape has a parity case (principle 5
pairs shapes with generator faults; these guard a query).

### 3. DPV is not vendored

`ontology/vendor/` holds releases a model `owl:imports` (ADR-0022 section 4). A model
does not import DPV to use one of its properties, nothing type-checks the category
against `dpv:PersonalData`, and the screens query and the viewer show a category by its
IRI's local name (`EmailAddress`). Vendoring the `pd:` extension (several hundred
concepts) would add a large unchanged release for labels nobody reads yet. If a later
change needs DPV's labels or hierarchy, it vendors the release the README's way and
records it there.

### 4. The question is a bundled query and a viewer Question

`personal-data-screens-by-role.rq` (M031/S01/T03) lists, per role, the screens whose
components read a shape with an annotated field, with the field and its category. The
role comes from the same `odrl:assignee` rule as `screens-by-role-writing-shape.rq`: an
assignee of a permission in a policy that governs the screen's events or their
operations, and unbound when nothing governs them (open to any authenticated identity).
The query names no field.

## Alternatives considered

- **A `seam:personalData` term.** Rejected: DPV already says it, in a W3C vocabulary
  other tools read; a seam term would be the duplication principle 4 avoids.
- **`dpv:hasPersonalData` on the RDF property** (`:name dpv:hasPersonalData pd:Name` in
  the ontology). Rejected: it makes the property personal in every shape that uses it,
  and a shape graph without an ontology model could not say it.
- **A boolean, such as `dpv:isPersonalData true`.** Rejected: DPV has no such property,
  and a category answers more questions (which screens show email addresses) for the
  same one triple. Principle 9 prefers IRIs for categories.
- **`sh:class dpv:PersonalData` on the value.** Rejected for now: it needs DPV's class
  hierarchy loaded (section 3) and would refuse a model's own category.
- **Classifying in a profile (ADR-0018).** Rejected: the classification is a fact of the
  model, wanted by every application, not a domain-specific rule set.

## Consequences

- Seam shapes gain `PersonalDataCategoryShape` and `PersonalDataPlacementShape`; the
  shapes file declares the `dpv` prefix for its SPARQL. A model without the annotation
  is unaffected. Tests: `tests/test_data_classification.py`.
- The authoring guide documents the annotation ("Personal data").
- The expense tutorial chapters mark their personal fields (M031/S01/T02), which moves
  their model hashes and regenerates their outputs; generated code does not change.
  From chapter 9 the notification's `:recipient` is `pd:Username`. The vendor's
  `:name` is not marked: `:Vendor` is a `gist:Organization`, and a company's name is
  not personal data (section 1).
- The viewer's Questions gain the personal-data screens question (M031/S01/T03).

## Open questions

- **Retention and purpose.** DPV also has `dpv:hasPurpose`, `dpv:hasLegalBasis` and
  storage duration terms. A retention rule per store would build on this annotation;
  nothing needs it yet.
- **Special category data.** DPV marks some categories (health, ethnicity) as
  `dpv:SpecialCategoryPersonalData`. Telling them apart needs DPV's hierarchy, so it
  waits for section 3's vendoring.
