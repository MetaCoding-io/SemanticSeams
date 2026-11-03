# Research note: the domain vocabulary as the spec for coding agents

*Status: research / design input, 2026-11-03. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Not yet scheduled" section, items C6 and R4). Follows the
[LLM generator note](2026-10-31-llm-generator.md) (context assembly, C3), the
[data-centric model note](2026-10-31-data-centric-model-and-copilot.md) (the ontology
layer, O1, and the review checks, R1) and the
[domain-driven design note](2026-11-02-domain-driven-design.md) (ubiquitous language).
Written against `main` at `50cddfa`.*

## Source

A post by dearlordylord (@ohdearlordylord) on 2026-11-02
([link](https://x.com/ohdearlordylord/status/2117315803104039129)), the first of a
three-post thread. Paraphrased: the domain vocabulary is the most important part of a
"spec" for coding agents, and it can be turned into an ontology graph, which both
enriches the flat markdown file with typed relations and lets the vocabulary be checked
for logical discrepancies with an OWL reasoner or a SHACL schema.

The attached image is a WebVOWL rendering of an ontology of the author's own, about
seventy classes and properties (Engine, World state, Interpretation, Journal,
Multiverse, Classifier request, Assessment source, and so on) with subclass edges,
object properties and datatype properties. It is kept out of the repository, as the
author's media, and this note describes it.

**Posts 2 and 3 of the thread were not retrieved.** X serves them only to signed-in
clients, and the mirror APIs carry the first post alone. The author's blog
([dearlordylord.com](https://www.dearlordylord.com/)) had no write-up on the date of
this note. Two of its posts give the author's frame for "specs":

- *Formally Specifying Dungeons and Dragons rulebooks*: a Quint specification of the
  combat rules, used as a test oracle, with about a thousand assertions extracted from
  community rulings by an LLM and kept only when the spec passes them.
- *Vibe code isn't meant to be reviewed*: keep contracts, data shapes and tests in
  human-owned interface packages, let the agent fill implementation packages, and let
  dependencies point one way, from implementation to interface, so implementations can
  be deleted and regenerated without losing domain knowledge.

So "spec" means the material a coding agent is given: a markdown file with a glossary,
rules and contracts. The post's claim is that the glossary deserves a graph.

## What the post describes, in this project's terms

The post reaches the graph from the markdown side. This project reaches the markdown
from the graph side. The three points of contact:

**1. The model is the spec.** Here the vocabulary is not lifted out of a spec; the
spec is projected from the model. The LLM generator note's context assembly (C3)
builds an agent's context from the `seams` views, per kind of element, with model text
quoted as data, and the principles forbid domain literals in anything generated. The
post's "enrich the flat .md with typed relations" is the inverse projection: the
glossary section of a `CLAUDE.md` or spec file is a view over the ontology layer that
O1 plans, one entry per class and property. That projection does not exist yet. It is
a small generator, and for people who put coding agents on a generated application it
may be the most immediately useful output of O1.

**2. Checking the vocabulary.** The post reaches for OWL reasoning and SHACL to find
contradictions. This project validates the model with SHACL already, and R1 adds the
checks that are vocabulary-level discrepancies: shapes with no target class,
undeclared property paths, lifecycle labels copied into `sh:in` lists. What it does not
do is reason over a domain ontology, because no model declares one yet
(data-centric note, section 1: no class, no `sh:targetClass`, sixteen of sixteen paths
undeclared). Once O1 lands with classes anchored in gist, an OWL RL pass for
unsatisfiable classes and disjointness violations is a small addition to
`seams check`. SemPKM runs OWL 2 RL inference already (data-centric note, section
4.1), so when it is the store the reasoning comes with it.

**3. The interface-package pattern is ADR-0012 and principle 8.** Human-owned
contracts and tests, agent-filled implementations, dependencies one way. Here the
contract is an operation's accepted and returned shapes and the tests the `tests`
generator derives from the model; the implementation is a handler behind a generated
stub, accepted once and then owned. The project's version is stricter, because the
contract lives in the model rather than in TypeScript types, but it is the same shape
arrived at independently, and worth citing as such.

## What to take

**A glossary generator** (C6). One markdown file for coding agents, from the ontology
and the shapes: per class and property, its label, its definition, its gist anchor, the
shapes that target it, the lifecycle on it, and the processes, operations and screens
that read or write it, each with its IRI. Deterministic, sorted, traced like any other
output (ADR-0019), listed in `seams.toml` so `seams check` reports it stale. It sits
beside C3 in the "Code the templates cannot write" milestone: C3 assembles the context
for one draft, and C6 writes the standing vocabulary every draft shares. It makes the
post's claim true in the direction the project prefers: the markdown is generated from
the graph and never the source of it.

**A spec-term check** (R4). A review check, in R1's family, over any hand-written
markdown in the model directory (a `CLAUDE.md`, a spec, a README): each capitalised or
backticked term that matches no label or local name in the model is reported, and each
model class or shape no document mentions is listed. It is the post's discrepancy check
applied to prose, and it is the ubiquitous-language check the DDD note said the project
enforces for code but not for documents.

## What not to take

The post's starting point, a prose spec with a glossary lifted out of it, is the
second source of truth the project exists to end. Lifting a glossary out of markdown
and then maintaining both is drift by construction. The direction here stays: declare
the vocabulary once, in the model, and project the prose.

## Backlog items

| # | Item | Builds on |
|---|---|---|
| C6 | **Glossary generator**: the domain vocabulary as one markdown file for coding agents, from the ontology and shapes, with gist anchors and the elements that touch each term; traced and listed in `seams.toml` | O1, O2, ADR-0016, ADR-0019 |
| R4 | **Spec-term check**: terms in hand-written markdown in the model directory that the model does not declare, and model terms no document mentions, reported by `seams check` with R1's checks | R1 |

R4 can start before O1, on labels and local names. C6 needs the classes O1 adds to say
anything a shape does not already say.

## Open questions

- What posts 2 and 3 of the thread propose. If the author describes the lifting
  step or a tool, this note should get a revision note.
- Whether C6's file is the `CLAUDE.md` of a generated application or a file it
  includes. A generated `CLAUDE.md` would also carry the owned-code rule (ADR-0012)
  and the regeneration rule (principle 8), which are not vocabulary.
- Whether R4 should read the model's own comments too. The TriG files carry
  explanatory comments that name terms, and a term used in a comment but declared
  nowhere is the same discrepancy.

## Sources

- dearlordylord, post of 2026-11-02:
  https://x.com/ohdearlordylord/status/2117315803104039129 (media
  `https://pbs.twimg.com/media/HWIwxYYWUAAH72g.jpg`, a WebVOWL rendering).
- dearlordylord, *Formally Specifying Dungeons and Dragons rulebooks*:
  https://www.dearlordylord.com/blog/dnd-quint/
- dearlordylord, *Vibe code isn't meant to be reviewed*:
  https://www.dearlordylord.com/blog/vibe-code-how-to-stay-in-control/
- This repository: the [LLM generator note](2026-10-31-llm-generator.md) section 3.2,
  the [data-centric model note](2026-10-31-data-centric-model-and-copilot.md)
  sections 1, 4.1 and 5.1, [ADR-0012](../adr/0012-operation-implementation.md) and
  [principle 8](../project/principles.md#_8-generated-code-and-owned-code-never-mix).
