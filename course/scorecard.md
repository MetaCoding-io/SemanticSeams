# The scorecard

The course is organised around six failures that model-based engineering, declarative
programming and code generation shared. [Lesson 4](lessons/04-why-it-kept-stalling.md)
builds the list from the three histories that precede it. Every lesson after that marks
one or more rows: which decision record or principle answers the failure, what artifact
in the repository shows it working, and what the backlog still lists as open.

The rule for the scorecard is the course's rule for itself. A row may be called closed
only when the lesson can point at a committed file, a decision record or a test. Where
the repository answers a failure in part, the row says so and names the backlog item.

| # | The failure | Where SemanticSeams answers it | Status today |
|---|---|---|---|
| **F1** | **Some code cannot be generated**, and generated code and hand-written code mix and rot together | Behaviour is interpreted, not generated ([ADR-0007](../docs/adr/0007-execution-strategy.md)). An operation says what implements it, the stub is written once and then owned ([ADR-0012](../docs/adr/0012-operation-implementation.md)). Errors are declared in the model ([ADR-0013](../docs/adr/0013-error-shapes-and-boundaries.md)). A language model drafts only behind the stub, and only tests derived from the model can accept the draft ([ADR-0020](../docs/adr/0020-llm-drafts.md)). Generated and owned code never mix (principle 8). | Closed. Tutorial [chapter 9](../docs/tutorials/expenses/09-hand-written-code.md) is the worked example. |
| **F2** | **Hand edits never get back into the model** or the generator; round-trip engineering never worked | One write path that edits the TriG text in place and keeps comments ([ADR-0017](../docs/adr/0017-write-path-and-editor.md)). A line-level trace from every output line to the facts behind it ([ADR-0019](../docs/adr/0019-generation-trace.md)). `seams check` names a hand-edited output. The viewer writes an edited output line back as a model patch when regeneration reproduces the edit, for literals and for form fields. A copilot proposes model patches that wait for a person ([ADR-0028](../docs/adr/0028-copilot-suggestions.md)). | Closed for literals and form fields. Structural write-back beyond form inputs is open (backlog V2, V4). |
| **F3** | **Diagrams are pictures, not models**; the view drifts from the thing it draws | One named graph per model plus one for the seams ([ADR-0001](../docs/adr/0001-named-graph-partitioning.md)). A BPMN element's own id is its IRI fragment ([ADR-0002](../docs/adr/0002-iri-identity-and-migration.md)). Diagrams are rendered from the graph ([ADR-0004](../docs/adr/0004-view-response-contract.md), [ADR-0005](../docs/adr/0005-navigation-resolution.md), [ADR-0008](../docs/adr/0008-node-link-renderer.md)). Sequence diagrams and event storms are derived, never authored. | Closed. |
| **F4** | **Models do not diff, merge or version**, and the tooling is captive to one vendor | The model is TriG text in git. `seams diff` and `seams plan` classify changes as compatible or breaking. Vocabularies carry versions, and a model is migrated by SPARQL Update steps ([ADR-0021](../docs/adr/0021-vocabulary-versions.md)). BPMN and DMN stay vendor-extension-free XML that any engine runs. The lock file records every output's generator version. | Closed for text diff, change classification and migration. There is no model-level merge tool; two edits to one TriG file merge as text. |
| **F5** | **Every tool draws one layer**; integration is glue, and no one can ask a question that crosses layers | The seams: the bridging predicates in [`ontology/seam.ttl`](../ontology/seam.ttl) (37 at the time of writing), each of which must earn a cross-layer query. A [query catalog](../docs/queries/README.md) whose rows continuous integration asserts. Domains and bounded contexts above the system ([ADR-0030](../docs/adr/0030-domains-and-bounded-contexts.md)), context-map relationships ([ADR-0032](../docs/adr/0032-context-map-relationships.md)) and the DDD profile ([ADR-0033](../docs/adr/0033-ddd-profile.md)), with tutorial [chapter 11](../docs/tutorials/expenses/11-bounded-contexts.md) as the worked example. | Closed for the questions in the catalog and the strategic layer above the system (M028 and M029 done). |
| **F6** | **Nobody trusts the generator**: it is nondeterministic, opaque and unverifiable, and language models make all three worse | Same model, same bytes (principle 6): sorted collections, no timestamps, the model identified by its content hash. Generators carry versions and preconditions, and a model that passes the shapes must generate ([ADR-0016](../docs/adr/0016-generator-protocol.md)). Every output has a trace ([ADR-0019](../docs/adr/0019-generation-trace.md)). Scenarios in the model become tests ([ADR-0014](../docs/adr/0014-scenarios-and-derived-tests.md)). A drafted generator is kept only when its golden test passes ([ADR-0029](../docs/adr/0029-llm-drafted-generators.md)). Continuous integration never calls a language model. | Closed. |

## How a row is marked

Each later lesson ends with a **Scorecard** section. It names the rows the lesson moved,
in this form:

> **F2, closed in part.** The viewer's write-back turns an edited `ifml:title` in a
> generated page into a one-triple patch (lab, step 4). Structural edits beyond adding or
> removing a form input are refused; backlog V2 proposes sentence editing for the rest.

The status column above is the course's summary of those sections. It is a snapshot. When
the [backlog](../docs/backlog.md) marks an item done, the row changes, and the lesson that
owns it changes with it.

## The two rows that are not failures

Two more things recur in the histories but are not on the scorecard, because they are not
failures of the approach: **the expressiveness cliff** (any declarative language ends
somewhere, and what lies beyond it must be written) and **the social cost of a new
notation** (people must learn to read it). The course treats the first as the reason F1
exists at all, and the second as a design constraint the project meets with its
"RDF invisibility" principle, which [lesson 5](lessons/05-one-graph-many-views.md)
introduces. They are discussed where they arise rather than scored.
