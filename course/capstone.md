# Capstone

Two capstones, self-paced, three to four hours each. Do one or both. Each ends with a
repository you can show, a `seams check` that passes, and a filled-in
[scorecard](scorecard.md) for your own work.

## Option A · Write a generator of your own

The six failures were about generators as much as models. This capstone has you write one
under the project's rules and see what the rules cost and buy.

1. Follow [Write your own generator](../docs/guide/write-your-own-generator.md) to the end:
   load the model, walk the views, join BPMN with DMN, write files deterministically, register
   the generator with `seams generate`, test it with the kit, preview a broken model with
   `--lenient`.
2. Then write a second generator from a reference output, with `seams new-generator NAME
   --reference FILE`, for an output you actually want from the expense model: a runbook, an
   access-review report, a glossary for a coding agent, a Structurizr or PlantUML view, an
   OpenAPI document. Write the output by hand first, as Boersma's method says, then teach
   the generator to produce it.
3. Optional: have a language model draft the same generator with `seams draft-generator`
   and compare its extract step and template with yours. The golden test decides whether
   the draft is kept; you decide whether it is better.

**Deliverable.** A package with a passing golden test, a determinism check, and a parity
inventory entry for every fault it can raise. **Scorecard.** F6 is yours to close: same
model, same bytes, a version in the lock, and a refusal that names the fact for every
precondition.

## Option B · Model a domain of your own

Take something you know: a small internal tool, a side project, a process at work. Model it
from an empty TriG file to `docker compose up`, following the order of the expense tutorial's
chapters and the conventions in [Authoring a model](../docs/guide/authoring-a-model.md).

1. Architecture, data, screens: the viewer shows it and the health badge is green.
2. Process, rules, lifecycle, permissions: it runs in process, a rule changes with no code
   changing, an illegal transition is refused, a write is governed.
3. A deployment: two environments, generated compose files, `seams status` current.
4. One hand-written handler behind a stub, with a declared error and a boundary event that
   catches it.
5. One question of your own in the catalog, with pinned rows.

**Deliverable.** The model, its generated outputs, its lock, a passing `seams check`, and a
derived sequence diagram for the main path with every `gap:` line either resolved or
explained. **Scorecard.** All six rows, for your model, with evidence.

## Showing your work

A capstone is a repository, not a document. If you want it read, open it with a README that
names the model file, the one command that generates everything, the one command that
checks it, and your scorecard. If you found a gap in the project while doing it, the
[backlog](../docs/backlog.md) says how items are proposed.
