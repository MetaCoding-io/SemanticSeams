# ADR-0044: Interchange Exports — the C4 Layer as Structurizr DSL and LikeC4, the Derived Sequence and Storm Views as PlantUML, Each a Built-in Generator That Writes Its Gaps as Comments

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M033/S01; backlog X9 (interchange exports); research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.7;
builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0016](./0016-generator-protocol.md),
[ADR-0030](./0030-domains-and-bounded-contexts.md) and
[ADR-0040](./0040-external-systems-and-webhooks.md)

## Context

The model already holds a C4 layer (`arch:System`, `arch:Container`, `arch:dependsOn`,
the `seam:exposes` / `seam:consumes` edges) and the viewer and `seams_gen` derive
sequence diagrams and an event-storm timeline from it, as Mermaid and Markdown. Teams
that already draw architecture in Structurizr or LikeC4, or keep PlantUML in their
docs, cannot use those views without copying them by hand, and a copy drifts from the
model. Backlog X9 asks for exports in those formats. Context Mapper is already exported
by `seams cml export` (ADR-0034) and stays there.

What must not change: the model is the source of truth (an export invents nothing),
the same model gives the same bytes, and the derivations of the sequence and storm
views live in one place (`seams_gen.sequence`, `seams_gen.storm`).

## Decision

### 1. Three formats, three built-in generators

Each export is a built-in generator (ADR-0016), registered in the `seams.generators`
entry-point group, `seams_gen.builtin.BUILTINS` and `seams_gen.sources.SOURCES`, and
listed in a project file like any other:

| Generator | Writes | From |
|---|---|---|
| `structurizr` | `workspace.dsl`, a Structurizr DSL workspace | the C4 model of section 2 |
| `likec4` | `model.c4`, a LikeC4 model | the same C4 model |
| `plantuml` | `sequence/<diagram file stem>.puml` and `storm/<process local name>.puml` | `seams_gen.sequence.derive` and `seams_gen.storm.derive`, unchanged |

The two C4 exports share one extract, `seams_gen.c4.extract_c4`, so they draw the same
elements and arrows. The PlantUML export only adds a render step to the existing
derivations. Nothing parses the exports with the external tools; they are text checked
by goldens.

### 2. The C4 model

`extract_c4(model)` reads the C4 layer through the seams views into a frozen
`C4Model`, every collection sorted by IRI:

- **Systems** are every `arch:System`, with an external flag when it states
  `arch:external true` (ADR-0040), each with the `arch:Container`s it `arch:contains`
  and their `arch:technology`.
- **People** are the `odrl:assignee`s of the policies `seam:governedBy` an `ifml:Event`
  that a container presents, the operation that event `seam:submitsTo`, or a user task
  `seam:completedOn` the event's form. A container presents an event when it
  `seam:presents` the interaction model holding the event's owner (the sequence
  view's rule). These are the actors of the sequence and storm views. A model with
  none has no person.

### 3. Relationships

One relationship per (source, destination) pair:

- a person to the container presenting the events its policies govern, labelled with
  those events' local names;
- a container to each container that `seam:exposes` what it `seam:consumes`, labelled
  with those operations' and channels' local names;
- a container to each container it `arch:dependsOn`, labelled `depends on` when it
  consumes nothing from it.

Labels are sorted and joined with `, `. System-to-system arrows are not stated; both
tools derive them from the container arrows.

### 4. Identifiers

An element's identifier is its IRI's local name, with every character outside
`[A-Za-z0-9_]` replaced by `_` and `_` before a leading digit, which both C4 formats
accept. Structurizr DSL uses one flat identifier scope; LikeC4 scopes names by their
parent, so its relationships name a container `<system>.<container>`. The extract keeps
the stricter, flat rule for both, so the two exports name every element alike: two
elements with one identifier are a
`GeneratorError` on the second element's IRI and `rdf:type`. The seam shapes cannot
state it: two IRIs in different namespaces may share a local name in a valid model.

### 5. Output layout

Each export writes into its generator's `out` directory. The examples list them under
`generated/exports/<generator name>`. An export has no header model hash, timestamp or
path, and the workspace and model are unnamed (the model's subject is a file IRI);
`seams.lock` records where each file came from.

### 6. Gaps are comments

A fact an export expects and cannot find is a gap, written as a comment line at the top
of the file (`# gap: …` in Structurizr DSL, `// gap: …` in LikeC4, `' gap: …` in
PlantUML), never an invented element. The C4 gaps are an event no container presents,
an event no assignee's policy governs, a container with no `arch:technology`, a
container in no system or in several (it is left out), a system with no containers and
a consumed endpoint no container exposes. The PlantUML export carries the sequence and
storm derivations' own gaps. The gap lines audit what the model lacks.

## Consequences

- Structurizr, LikeC4 and PlantUML users read the model's views in their own tools,
  regenerated with `seams generate` instead of copied.
- A new C4 fact (a person's description, a relationship technology) is added once to
  `seams_gen.c4` and both C4 exports print it.
- The exports are one-way. Importing from these formats is backlog X10.
- Each identifier collision is reported, not renamed, so an export never silently
  merges two elements.
