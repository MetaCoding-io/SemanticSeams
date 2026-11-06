# ADR-0018: Domain Profiles — A Profile Package Attached by `seam:conformsTo` Restricts What the Editor Offers

**Status:** Accepted

**Date:** 2026-11-02

**Amended by:** [ADR-0033](./0033-ddd-profile.md): `seams check` now resolves the
attached profile and fails on its shapes' `sh:Violation` results (`seams generate` still
ignores profiles), and `resolve_profile` moved to the `seams` library.

**Source:** milestone M019/S06; backlog I5; research note
[Projection and editing](../research/2026-10-30-domain-ide-and-generator-kit.md)
section 4, layer 4; builds on [ADR-0016](./0016-generator-protocol.md) and
[ADR-0017](./0017-write-path-and-editor.md)

## Context

`ontology/seam.ttl` reserves `seam:Profile` ("a component taxonomy plus a SHACL shapes
library validating the model graph itself") and `seam:conformsTo` (range
`seam:Profile`), but nothing uses them yet. The research note proposes extending a
profile to a package with four parts: extra vocabulary and shapes, the generators the
profile needs, the palette of classes the editor offers when adding an element (the
restricted construct menu of Boersma's fig. 1.6), and labels in the domain's own words.
That is what turns the viewer's edit mode (ADR-0017, I2 forms, I3 preview) into a
*domain* IDE: an expense team edits expense forms and approval tasks, not
`ifml:Form`s and `proc:UserTask`s.

Backlog I5 asks for this ADR before any code. It has to settle where a profile lives,
what new terms it needs, what a profile changes in the editor, health and preview, and
how a broken profile is reported. Principle 4 (vocabulary is earned) applies to every
term it adds; principle 5 (flag, never refuse) applies to what it does to the model.

## Decision

### The package: a directory under `profiles/` beside the model

A profile is a **directory `profiles/<name>/` in the model directory** (the directory of
the loaded TriG file, where `seams.toml` also sits). It holds:

- `profile.ttl` (required): a Turtle file declaring exactly one `seam:Profile`, with the
  terms below;
- optional shapes files, named by `seam:profileShapes` and resolved relative to the
  profile directory.

A model attaches to a profile with one triple in its seams graph:

```turtle
:expenses_model seam:conformsTo <https://example.org/profiles/expense> .
```

Resolution reads every `profiles/*/profile.ttl` under the model directory, in sorted
path order, and picks the one that states `<P> a seam:Profile` for the profile IRI `P`.
The IRI is the identity; the directory name is only where the file is. No new
"location" predicate is needed, so the model keeps naming the profile by IRI only
(ADR-0002) and stays free of file paths.

The profile is **not part of the model**: it is loaded into its own graph, not merged
into the dataset, so the model hash, the generators' input and `seams.lock` are
unchanged by attaching or editing a profile.

### The vocabulary

Four terms, all in the `seam:` namespace, each one needed by exactly one of the four
behaviours below:

| Term | Domain → range | Meaning |
|---|---|---|
| `seam:offersClass` | `seam:Profile` → `rdfs:Class` | a class the editor offers when adding an element; one triple per class |
| `seam:usesGenerator` | `seam:Profile` → `xsd:string` | the name of a generator the profile previews: a `seams.generators` entry-point name (ADR-0016), as written in `seams.toml` |
| `seam:profileShapes` | `seam:Profile` → `xsd:string` | a shapes file, a path relative to the profile directory, merged into health |
| (labels) | offered class → `rdf:langString` or `xsd:string` | `skos:prefLabel`, else `rdfs:label`, stated on the offered class in `profile.ttl` |

Labels reuse SKOS and RDFS rather than adding a term (principle 4). `skos:prefLabel`
wins over `rdfs:label` when both are present; a class with neither keeps the label the
editor shows without a profile. Labels come only from the profile graph, never from
code. `ontology/shapes/seam-shapes.ttl` gains a shape for `seam:Profile` that checks
these: `seam:offersClass` values are IRIs, `seam:usesGenerator` and
`seam:profileShapes` values are strings, and an offered class has at most one
`skos:prefLabel` and at most one `rdfs:label`.

Resolution returns a value holding the profile IRI, its offered classes sorted by IRI,
its generator names sorted, the labels by class, and one shapes graph parsed from its
`seam:profileShapes` files in sorted order (empty when there are none). Every value
comes from the profile graph.

### What a profile changes

- **Palette.** In edit mode, the classes the editor offers when adding an element are
  exactly the profile's `seam:offersClass` values, shown with the profile's labels, in
  IRI order. The palette is a list computed in Python and rendered by the template.
- **Out-of-profile classes are flagged, never refused.** A typed element in the model
  whose class is neither an offered class nor a subclass of one (by `rdfs:subClassOf`
  over the ontology, the model and the profile) appears in health as a fact naming the
  element, `rdf:type` and the class not offered by the profile. A hand edit or a form
  save that introduces such a class is still written (principle 5); the palette only
  restricts what the editor *suggests*.
- **Shapes.** The profile's shapes graph is merged with the seam shapes and the model's
  own shapes when health validates the model, so a profile shape's violations show in
  the health panel like any other. The validation cache is keyed on the merged shapes
  too, so attaching, changing or detaching a profile is never answered from a stale
  report.
- **Preview.** The live preview (I3) runs only the project's generators whose name is
  listed by `seam:usesGenerator`, still leniently and in memory. A listed name the
  project's `seams.toml` does not configure is not an error; the preview panel shows it
  as not configured. `seams generate` and `seams check` ignore profiles: a profile
  narrows what the editor previews, not what the project builds.
  *(Amended by ADR-0033: `seams check` validates the model with the profile's shapes and
  fails on a `sh:Violation`; `seams generate` still ignores profiles.)*

The viewer resolves the profile when it loads the model and again on every reload after
a save, and writes one log line naming the profile IRI, its class count and its
generator count.

### No profile means no change

A model with no `seam:conformsTo` behaves exactly as before this ADR: the palette offers
what it offered without a profile, health runs the same shapes, the preview runs every
configured generator, and no profile file is read. The read-only viewer is unaffected
either way; profiles only change edit mode and health.

### Errors are `ResolutionError` facts

A profile that cannot be resolved raises `ResolutionError(subject, predicate, detail)`
from the library's errors, and the viewer shows it in the health panel with the subject,
the predicate and the detail, then carries on as if no profile were attached. The cases:

| Case | Subject | Predicate | Detail |
|---|---|---|---|
| no `profiles/*/profile.ttl` declares the IRI | the model element stating `seam:conformsTo` | `seam:conformsTo` | the profile IRI and the directory searched |
| more than one `profile.ttl` declares it | the same | `seam:conformsTo` | the profile IRI and the files, sorted |
| the model states more than one distinct profile | the first subject, sorted | `seam:conformsTo` | the profile IRIs, sorted |
| `profile.ttl` does not parse | the same | `seam:conformsTo` | the file and the parser's message |
| a `seam:profileShapes` file is missing or does not parse | the profile IRI | `seam:profileShapes` | the path and the reason |

A violation of the profile's own shapes in `profile.ttl` (the `seam:Profile` shape) is
not a resolution error; it is a health fact like any other shape result.

## Alternatives Considered

- **A location predicate on the profile in the model** (`<P> seam:profileDirectory
  "profiles/expense"`). Rejected: it puts a file path in the model and adds a term that
  the directory convention makes unnecessary.
- **Naming the profile in `seams.toml`.** Rejected: `seam:conformsTo` is already the
  reserved, model-level way to state conformance, and the viewer must work on a model
  with no project file.
- **Merging the profile into the model dataset.** Rejected: it would change the model
  hash and the generators' input, so attaching a profile would make every committed
  output stale.
- **Refusing out-of-profile classes.** Rejected by principle 5: invalid models save and
  are flagged. A profile is guidance, not a gate.
- **Profiles also restricting `seams generate`.** Not chosen: `seams.toml` already says
  what the project builds. A profile that also gated builds would be a second source for
  the same fact.
- **A new label term.** Rejected: `skos:prefLabel` and `rdfs:label` already say it.

## Consequences

- `ontology/seam.ttl` gains `seam:offersClass`, `seam:usesGenerator` and
  `seam:profileShapes`, and `ontology/shapes/seam-shapes.ttl` a `seam:Profile` shape;
  the generated vocabulary reference pages are regenerated (M019/S06/T02).
- `viewer/profiles.py` resolves a profile; the viewer's palette, health and preview take
  it as input (T02, T03). The viewer guide gains a Domain profiles section, and the
  authoring guide a note on `seam:conformsTo`.
- Models without a profile, the CLI, the generators and every committed output are
  unchanged.

## Implementation Notes

- T02: profile terms and shapes, `viewer/profiles.py` (`resolve_profile(ds, model_dir)`
  returns the profile or `None`), a sample profile under
  `tests/fixtures/profiles/expense/`, and `tests/test_viewer_profiles.py`.
- T03: the palette, the health merge (with the validation cache cleared on reload), the
  preview subset and the docs.
