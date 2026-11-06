# Lesson 5 · One graph, many views

*Named graphs, IRIs as identity, native payloads kept native, and the seams. The first
lesson in which you write a model.*

::: info Module B draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module B pull request.
:::

## Outcomes

After this lesson you can:

- Explain the four decisions that make one RDF graph hold several notations without
  turning any of them into RDF: one named graph per model plus one for the seams, a
  native element's own id as its IRI fragment, native XML kept as a payload, and
  membership stated as a fact.
- Name the backbone of the seams, `seam:detailedBy` and `seam:notation`, and say how a
  click is resolved from them.
- Write a TriG file with a C4 architecture, a seams graph and a data shape, and see the
  viewer's health badge turn green, then red, then green.

## The story, in brief

Lesson 1 ended with a corollary: keep the notations that survived, keep their engines, and
join them. This lesson is how the joining is done without inventing a BPMN ontology or an
IFML-in-RDF. A model is a `seam:Model` with a `seam:notation`; for BPMN and DMN it carries
its native XML as a `seam:renderPayload` and only the elements that take part in a seam are
lifted, with the element's own id as the IRI fragment, so a stock bpmn-js viewer is a full
participant in the graph through its click event ([ADR-0002](../../docs/adr/0002-iri-identity-and-migration.md),
[ADR-0003](../../docs/adr/0003-payload-resolution.md)). Each model is one named graph, and
every seam lives in one more graph of its own, so a layer stays pure and the joins stay
auditable ([ADR-0001](../../docs/adr/0001-named-graph-partitioning.md)). Membership is a
fact, `seam:inModel`, not a naming convention: that was the first review's first finding.

The seams themselves are the predicates of [`ontology/seam.ttl`](../../ontology/seam.ttl), 37 at the time of writing,
under four design rules: few and generic beats many and precise; every seam predicate must
earn a query; reuse before minting; and the backbone stays notation-agnostic. Zooming in is
one query, follow `seam:detailedBy`, read `seam:notation`, mount the renderer
([ADR-0005](../../docs/adr/0005-navigation-resolution.md)). Everything the user sees is
labelled in product language, never in IRIs: the product brief's "RDF invisibility". The
Turtle you write in the lab is the one sanctioned exception, framed as what it is, writing
code.

## Read in the repo

- [Diagrams are views](../../docs/concepts/diagrams-are-views.md) and
  [The seams](../../docs/concepts/the-seams.md). The two concept pages this lesson is built
  on.
- [ADR-0001](../../docs/adr/0001-named-graph-partitioning.md) and
  [ADR-0002](../../docs/adr/0002-iri-identity-and-migration.md). Why one graph per model,
  and what a rename costs.
- The generated [seam predicates](https://metacoding-io.github.io/SemanticSeams/docs/reference/seam-predicates)
  reference, which cannot drift from `seam.ttl` because it is built from it.

## Lab: chapters 1 and 2

Work through [chapter 1, The architecture](../../docs/tutorials/expenses/01-architecture.md)
and [chapter 2, The data](../../docs/tutorials/expenses/02-data.md) of the expense tutorial
in your working file. Two twists:

1. After chapter 1, before the seams graph exists, start the viewer on your file and look at
   what it shows. Then add the seams graph and look again. The difference is what a seam is.
2. In chapter 2, when the deliberate mistake turns the badge red, read the message before
   fixing it. It names the element and the shape that rejected it. That is a SHACL result
   over the model, and lesson 6 is about it.

Diff your file against `examples/expenses/chapter-02/expenses.trig` when you are done.

## Scorecard

- **F3, closed.** The diagrams in the viewer are rendered from the graph. Your chapter 1
  architecture has no diagram file; the C4 view is a rendering of three triples.
- **F5, closed in part.** The seams graph you wrote is the join between layers, stated as
  facts. The questions it answers come in lesson 8.
- **F4, opened.** Your model is a text file in git. Lesson 11 is about what else that
  needs.

## Further reading

- W3C, *RDF 1.1 TriG*, 2014, for the named-graph syntax you wrote.
- Simon Brown, *The C4 Model for Visualising Software Architecture*, 2018 onward. The
  architecture notation and why it stops at the repository link.
- The project's [research note on reveal modes](../../docs/research/2026-10-15-reveal-modes.md):
  one visual language, three ways to reveal a relation.
