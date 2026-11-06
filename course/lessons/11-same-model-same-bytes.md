# Lesson 11 · Same model, same bytes

*Determinism, versioned generators and vocabularies, environments and generated compose
files, scenarios as tests, and data that outlives the application. The answer to the fourth
and sixth failures.*

::: info Module C draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module C pull request.
:::

## Outcomes

After this lesson you can:

- State what "same model, same bytes" requires of a generator and show it with one command
  and an empty diff.
- Explain how a vocabulary is versioned, how a model declares the versions it is written
  for, and what happens on load when they differ.
- Deploy the expense app with generated compose files for two environments, check its
  running containers against the model, and move its data into a second store with no code
  change.

## The story, in brief

Principle 6 is the shortest in the list and carries the most weight: same model, same
bytes. Every collection is sorted, no output carries a timestamp or an absolute path, and
the model is identified by its content hash, which every generated file records and the
runtime refuses to start against if it differs. That is what makes a golden test meaningful
and a diff readable, and it is why lesson 3's regeneration produced no change.
[ADR-0016](../../docs/adr/0016-generator-protocol.md) makes generators objects with a name,
a version, preconditions and the shapes a model must pass first, locked beside their
outputs, so that a third party's generator runs the same way and is held to the same rule.

[ADR-0021](../../docs/adr/0021-vocabulary-versions.md) applies versioning to the
vocabularies themselves, which is lesson 4's F4 test, "rename one element and ask what
else changed", applied to the language rather than the model. Each vocabulary has an
`owl:versionIRI`; a model `owl:imports` the versions it was written for; loading refuses a
newer one and migrates an older one in memory with SPARQL Update steps, and `seams migrate`
writes the migration into the files through the write path. `seams diff` and `seams plan`
classify a change between two models as compatible or breaking. [ADR-0015](../../docs/adr/0015-environments.md)
makes development and production facts in the model, with one generated compose file per
environment; `seams status` reads each running container's health endpoint and reports it
as current, behind or ahead of the model; `seams secrets` checks that every secret the
model names exists without reading one. [ADR-0014](../../docs/adr/0014-scenarios-and-derived-tests.md)
turns `verify:` scenarios into generated tests and `seams coverage` lists what no scenario
exercises. And [ADR-0025](../../docs/adr/0025-sempkm-store.md) and
[ADR-0026](../../docs/adr/0026-mental-model.md) are principle 9, data outlives applications:
a shape's entities can live in a SemPKM store, typed by the model's classes, with a
package generated from the same ontology and shapes so that the second tool understands
them.

## Read in the repo

- [ADR-0016](../../docs/adr/0016-generator-protocol.md) and
  [ADR-0021](../../docs/adr/0021-vocabulary-versions.md).
- [`examples/chat-app/seams.lock`](../../examples/chat-app/seams.lock). Everything the
  lock knows about one project's outputs.
- [Design and coding principles](../../docs/project/principles.md), principles 6, 7 and 9.

## Lab: chapters 8 and 10

- [Chapter 8, Growing up](../../docs/tutorials/expenses/08-growing-up.md): a payouts channel
  and a process started from it, a second decision and lifecycle, the finance console,
  deploy facts, PostgreSQL by `seam:storedIn`, two environments, `docker compose up`. Run
  the complexity check and read the derived diagrams, one per path.
- [Chapter 10, Expenses in SemPKM](../../docs/tutorials/expenses/10-sempkm.md): a SemPKM
  store, the expenses moved into it with no code change, the generated package installed,
  and a webhook channel starting a process.

Two twists:

1. After the stack is up, change one label in the model without regenerating and run
   `seams status`. Then regenerate and restart and run it again.
2. Run `seams diff` between your chapter 7 and chapter 8 files and read the classification.
   Then remove a required field from a shape and run it again.

## Scorecard

- **F4, closed for text, classification and migration.** The model is text in git, a
  change is classified by rule, the vocabulary is versioned and migrated. Merging two
  edits to one TriG file is still a text merge; no model-level merge tool exists.
- **F6, closed.** Deterministic bytes, versioned generators with preconditions, a lock, a
  trace, tests derived from scenarios, and a status check against the running system.
- **F1 and F3, reinforced.** The compose files are projections. Nothing in them is written
  by hand; what a laptop needs and production does not is a `:development` override in the
  model.

## Further reading

- The *Reproducible Builds* project, on why byte-identical output matters and what breaks
  it.
- Dave McComb, *The Data-Centric Revolution*, 2019, for principle 9's argument, and
  Semantic Arts' gist ontology, which the project pins and imports.
- Meinte Boersma, *Building User-Friendly DSLs*, 2025, chapter 10, on versions, migrations
  and deprecation, which the project's generator kit note reads closely.
