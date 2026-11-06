# Lesson 12 · What is still open

*Domain profiles, bounded contexts, SysML v2 interchange, drafted generators, the model as
a context layer for coding agents, and the backlog's honest list. The scorecard, filled
in.*

::: info Module D draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module D pull request, and it is the lesson most
likely to change as the backlog moves.
:::

## Outcomes

After this lesson you can:

- Read the project's backlog and research notes well enough to say which open items bear on
  which scorecard row, and which are new ground the six failures do not cover.
- Explain what a domain profile is, what a bounded context adds above a system, and what
  the project takes from SysML v2 and from domain-driven design without lifting either
  into RDF.
- Repeat lesson 4's written exercise for SemanticSeams itself, with evidence for every row.

## The story, in brief

The project's own research notes are the best account of where it is going, and they are
written as records: each states a question, a short answer, and a revision note when a
decision answers part of it. Five threads matter here.

**Profiles.** [ADR-0018](../../docs/adr/0018-domain-profiles.md) makes a method a package of
vocabulary and shapes attached by `seam:conformsTo`, which narrows the editor's palette and
adds health checks without ever refusing a model. The outline planned Löwy's IDesign as the
first method profile, with its interaction rules as shapes over the architecture, and the
DDD note proposes domain-driven design as the second. The mechanism is shipped and tested;
the method profiles themselves are backlog items.

**Bounded contexts.** The DDD note found the tactical patterns already in the graph without
their names, and the strategic layer missing. [ADR-0030](../../docs/adr/0030-domains-and-bounded-contexts.md)
adds `arch:Domain` and `arch:BoundedContext`, each context owning one ontology and the model
graphs written in its language. Context maps, the DDD profile and a tutorial chapter with a
second context are milestone M029.

**SysML v2.** The note's conclusion: export it, take requirements, concerns and
variability, do not lift KerML into RDF. Items W1 to W5 are proposed and unscheduled.

**Drafted generators.** [ADR-0029](../../docs/adr/0029-llm-drafted-generators.md) extends
lesson 9's rule to generators themselves: a language model drafts the extract step and the
template from a reference output, and the package is kept only when its golden test passes.
The product review note goes further and names the project's strongest pitch: not a
competitor to low-code, but "the governed context layer for agentic coding", with a
glossary generated from the model for coding agents (C6) and hand-written specs checked
against the model's terms (R4).

**The honest list.** Observed behaviour as its own named graph, service-level objectives,
data classification, timers and scheduled work, more than one replica, imports of existing
models, a model-level merge. None is a reason the six failures reopen; each is a kind of
fact the graph does not yet hold.

## Read in the repo

- [`docs/backlog.md`](../../docs/backlog.md), the milestones table and the "Not yet
  scheduled" section.
- [Product review and UI ideas](../../docs/research/2026-11-03-product-review-and-ui-ideas.md),
  written from a model-based systems engineering persona.
- [Domain-driven design, read against the graph](../../docs/research/2026-11-02-domain-driven-design.md)
  and [SysML v2, read against the graph](../../docs/research/2026-11-02-sysml-v2.md), the
  short answers.

## Lab: the exercise, again

Repeat [lesson 4's written exercise](04-why-it-kept-stalling.md#lab-a-written-exercise) for
SemanticSeams. For each of the six rows: does the failure apply, what does the project do
about it, and what did that choice cost? Point every claim at a file, a decision record or a
test you touched in a lab. Where the [scorecard](../scorecard.md) says "closed in part",
find the backlog item and say whether you agree with its priority.

Then write one paragraph on what the project should do next, and why. If you want it
considered, the backlog's triage rule is stated at its top; open a pull request against
`docs/backlog.md` in its format.

## Scorecard

Filled in. The [scorecard page](../scorecard.md) is the course's summary; your exercise is
your own. Where they disagree, one of them is wrong, and the repository decides which.

## Further reading

- Juval Löwy, *Righting Software*, 2019, for the IDesign method the first profile encodes.
- Eric Evans, *Domain-Driven Design*, 2003, part IV, strategic design, for bounded contexts
  and context maps.
- Object Management Group, *SysML v2*, 2025, part 1, section on view definitions.
- The project's [EventCatalog levels](../../docs/research/2026-10-15-eventcatalog-levels.md)
  and [reveal modes](../../docs/research/2026-10-15-reveal-modes.md) notes, for how the
  viewer will show more without showing everything.
