# Research notes

Before a milestone is planned, the question behind it gets a research note in
[`docs/research/`](../research/). A note states the question, reads the sources and the
repository as they stood that day, and ends in proposed backlog items. The notes are
records: a later finding is added as a dated revision note at the top, never by rewriting,
so each one still says what was believed when it was written. They live in the repository
rather than on this site, so every link below opens the note on GitHub. The
[backlog](/backlog) tracks the items a note proposes, and an accepted
[decision record](/adr/) settles what a note left open.

## Every note, newest first

Status is as of 2026-11-07. Item IDs are the backlog's.

| Date | Note | The question | What came of it |
|---|---|---|---|
| 2026-11-10 | [The state defines the interface](../research/2026-11-10-state-defines-the-interface.md) | A post on agent harnesses says the operations on offer should follow the state, shown to the caller and enforced by one description. Does the graph hold that, and is it used? | It holds it and enforces it, but does not compute or show it. H1 to H5 proposed (added 2026-11-10): an affordances view, responses that carry their next steps, screen guards checked against the lifecycle, process paths walked against the lifecycle at check time, and a tool surface for agents derived from the model. |
| 2026-11-03 | [A product review from the modelling side, and ten UI ideas](../research/2026-11-03-product-review-and-ui-ideas.md) | What has the project built, measured as a modelling product, what does a builder still miss, and which interface ideas would close the gap? | The engine is ahead of the dashboard. V1 to V10 proposed and not yet scheduled: fundamentals, sentence editing, a questions cockpit, the storm board as capture, a thread strip, a role lens, a scenario player, diff on canvas, runtime heat and layers focus. The note's one bet is V4 and V2 before more generator or vocabulary work. |
| 2026-11-03 | [The domain vocabulary as the spec for coding agents](../research/2026-11-03-domain-vocabulary-as-spec.md) | Is the domain vocabulary the most important part of a spec for coding agents, and should it be an ontology? | Yes, and the project already holds it: the glossary an agent reads is a projection of the model, never its source. C6 (a glossary generator) and R4 (a spec-term check in `seams check`) proposed. |
| 2026-11-02 | [SysML v2, read against the graph](../research/2026-11-02-sysml-v2.md) | Does SysML v2 offer diagrams to author here, can it be generated from the model, and does it cover ground the project has not thought about? | No diagrams to author: its views are queries plus renderings, as ours are. W1 to W5 proposed: a `sysml` generator, a `req:` requirements vocabulary, requirement coverage, a snapshot vocabulary for the as-observed graph, and a model API shaped like the Systems Modeling API. |
| 2026-11-02 | [Domain-driven design, read against the graph](../research/2026-11-02-domain-driven-design.md) | What of DDD does the graph already hold under other names, and what is missing? | The tactical patterns were already there; the strategic layer was not. B1 to B5 done in M028 and M029: domains and bounded contexts ([ADR-0030](/adr/0030-domains-and-bounded-contexts)), lifecycle on the class ([ADR-0031](/adr/0031-lifecycle-on-the-class)), context maps ([ADR-0032](/adr/0032-context-map-relationships)), the DDD profile ([ADR-0033](/adr/0033-ddd-profile)), Context Mapper interchange ([ADR-0034](/adr/0034-context-mapper-interchange)), the derived event storm and tutorial [chapter 11](/tutorials/expenses/11-bounded-contexts). X6 and X7 done: aggregate boundaries ([ADR-0035](/adr/0035-aggregate-transaction-boundary)) and cross-aggregate invariants ([ADR-0036](/adr/0036-cross-aggregate-invariants)). X12, a storm import, proposed. |
| 2026-10-31 | [An LLM generator for the code templates cannot write](../research/2026-10-31-llm-generator.md) | Where does hand-written or drafted code live, what context does it get, and what keeps a drafted body honest? | C1 to C5 done in M022: `seams context`, typed handler stubs, generated acceptance tests, `seams propose` ([ADR-0020](/adr/0020-llm-drafts)) and drafts recorded in the lock. X11, pinned LLM models, done in M027. |
| 2026-10-31 | [Tracing generation, and running it backwards](../research/2026-10-31-generation-trace.md) | Can every generated line say which facts it came from, and can an edit to an output line become a model patch? | T1 to T5 done in M020 and M021: line-level trace sidecars ([ADR-0019](/adr/0019-generation-trace)), the viewer's generation view, and write-back of literals and form inputs. |
| 2026-10-31 | [A data-centric model, SemPKM as its store, and a model copilot](../research/2026-10-31-data-centric-model-and-copilot.md) | What does the project offer for data modelling, can SemPKM be the store, and what would a copilot propose? | O1 to O6 and R1 to R3 done in M023 to M025: vocabulary versions, the ontology layer on gist, shapes with target classes, JSON-LD contexts, SemPKM as a store with its Mental Model and webhooks ([ADR-0021](/adr/0021-vocabulary-versions) to [ADR-0027](/adr/0027-sempkm-webhook-channel)), model review checks, `seams suggest` ([ADR-0028](/adr/0028-copilot-suggestions)) and `seams draft-generator` ([ADR-0029](/adr/0029-llm-drafted-generators)). Tutorial [chapter 10](/tutorials/expenses/10-sempkm) is the worked example. |
| 2026-10-30 | [A generator kit and a domain IDE, read against two books](../research/2026-10-30-domain-ide-and-generator-kit.md) | Read against Boersma's *Building User-Friendly DSLs* and Parr's template rules: what does a builder need to write generators, and what does editing the model need? | K1 to K7 and I1 to I6 done in M017 to M019: shapes that catch every generator fault, static decision checks, logic-free templates, the generator protocol and lenient mode ([ADR-0016](/adr/0016-generator-protocol)), the public test kit, `seams new-generator`, and editing through one write path ([ADR-0017](/adr/0017-write-path-and-editor)) with domain profiles ([ADR-0018](/adr/0018-domain-profiles)). X13, static checks of `UNIQUE` tables, done in M027. |
| 2026-10-29 | [UML coverage, derived diagrams, and what a builder still lacks](../research/2026-10-29-uml-coverage-and-gaps.md) | Does the project need a UML layer, and what does a builder need after launch that the model does not hold? | No UML layer: every diagram is covered by a pillar or derivable. U1 to U8 done in M011 to M015: derived sequence diagrams, the declared delta stream, operation implementations ([ADR-0012](/adr/0012-operation-implementation)), error boundaries ([ADR-0013](/adr/0013-error-shapes-and-boundaries)), scenarios and derived tests ([ADR-0014](/adr/0014-scenarios-and-derived-tests)) and the shape diff. U10, timers, done in M030 ([ADR-0037](/adr/0037-timers-and-scheduling)). X1 to X5, X8 and X9 proposed and scheduled as M031 to M033. |
| 2026-10-29 | [`seams`, a read-only Python library over the model](../research/2026-10-29-seams-python-library.md) | Did the generation work produce a library a user could pick up to write their own generators? | Partly, so L1 to L6 done in M010: a uv workspace, the `seams` library on rdflib and lxml alone, typed views per layer, BPMN and DMN joins, every consumer ported with goldens unchanged, and the [API reference](/reference/seams-library) and [generator guide](/guide/write-your-own-generator). |
| 2026-10-29 | [The runtime stores data where the model says](../research/2026-10-29-runtime-storage.md) | The chat app declared a PostgreSQL store the runtime never used. How does the runtime read storage from the graph? | U9 done in M011 ([ADR-0011](/adr/0011-storage-resolution)): `seam:storedIn`, store kinds and bindings in `deploy:`, SQLite and PostgreSQL opened from the facts, and storage in model health. The note's "not covered" item, more than one replica, is A10, done in M030 ([ADR-0038](/adr/0038-shared-stream-channel)). |
| 2026-10-29 | [A build-along tutorial, and the second worked example it produces](../research/2026-10-29-build-along-tutorial.md) | The docs never had the reader build anything, and the chat app was too small to need layer mode. | E1 to E5 done in M009: the [expense tutorial](/tutorials/expenses/)'s chapters 1 to 8, the configurable model path, the complexity check, human tasks ([ADR-0009](/adr/0009-human-tasks)) and the role policy evaluator. Chapters 9 to 11 followed in M014, M024 and M028. |
| 2026-10-29 | [Managing and deploying generated artifacts](../research/2026-10-29-artifact-management.md) | Besides a library for generating, what does a builder need to manage generated files over time? | A1 to A9 done in M012, M015 and M016: `seams.toml`, `seams generate` and `seams check`, the lockfile, the CI action and pre-commit hook, `seams status`, environments ([ADR-0015](/adr/0015-environments)), change plans, published images, smoke tests and `seams secrets`. |
| 2026-10-15 | [One visual language, three ways to reveal a relation](../research/2026-10-15-reveal-modes.md) | The descent worked but every view looked like a different product. What is the one visual language, and how is a relation revealed? | Backlog items 1, 2 and 6 to 11, done in M006 to M008: the node card with seam dots, the ELK renderer ([ADR-0008](/adr/0008-node-link-renderer)), `seam:reveal` as open, nest or layer ([ADR-0005](/adr/0005-navigation-resolution)), tinted bpmn-js and dmn-js, the shape-graph renderer and [layer mode](/guide/the-viewer#layer-mode). |
| 2026-10-15 | [Render IFML as IFML, not as RDF](../research/2026-10-15-ifml-notation.md) | The IFML view was the C4 node-link code with other colours. What does the notation need, and what does the vocabulary already hold for it? | Items 3, 10 and 12 done: IFML in its own notation, server-side SVG (M006), then on diagram-js with ELK ports (M007), and the IFMLEdit JSON exporter as a conformance check (M008). |
| 2026-10-15 | [EventCatalog "Levels", and what SemanticSeams can take from it](../research/2026-10-15-eventcatalog-levels.md) | EventCatalog's visualiser switches an L1, L2 and L3 of one diagram. Which of its ideas fit a graph where levels are queries? | Items 2, 4 and 5 done in M006: L1 to L3 as class filters with a rolled-up query, level and lens state in the URL, and a legend with live counts. L4 is a preset of reveal choices, not a level. The "Domain" level it lacked became [ADR-0030](/adr/0030-domains-and-bounded-contexts). |

Not taken up: LionWeb interoperability (watch only, as the generator kit note suggests)
and levels for IFML (re-parked with a size threshold).

## The November notes

The five most recent notes read the project against bodies of practice rather than
proposing a feature, and only one of them has been built.

**Domain-driven design** found that the expense tutorial was already a DDD model written
without the words: two aggregates, two sagas and a policy. What the graph lacked was the
strategic layer above `arch:System`. That became the largest run of decisions in the
project, [ADR-0030](/adr/0030-domains-and-bounded-contexts) to
[ADR-0036](/adr/0036-cross-aggregate-invariants), and the tutorial's
[chapter 11](/tutorials/expenses/11-bounded-contexts), where payouts move into a finance
context with its own ontology, a conformist relationship to the expense context, and a
DDD profile whose rules `seams check` and the viewer report.

**SysML v2** has no diagrams in the UML sense, only view definitions that are queries plus
renderings. The note reads that as this project's "diagrams are views" stated by a
standards body, and recommends taking three kinds of fact rather than any notation:
requirements with satisfaction and verification links, concerns and stakeholders, and
variability. It also recommends exporting the whole model as one `.sysml` file, which
opens in SysON and Syside and diffs in a pull request.

**The domain vocabulary as spec** takes a thread on coding agents as its source: the
glossary an agent is given is the most important part of its spec, and it can be an
ontology graph. The project already has that graph. The note's rule is that the glossary
is a projection of the model, never its source, and that hand-written specs should be
checked against the model's terms.

**The product review** reads the project as a modelling product, from the seat of a
designer who comes from MBSE tooling. The digital thread is real, from one graph through
forms, routes, compose files, derived tests and sequence diagrams to the running
container, with a line-level trace behind each. The authoring experience is the weakest
part: the viewer does not yet meet the brief's own RDF-invisibility principle, and nobody
can start a model without writing TriG. Its ten UI ideas are backlog items V1 to V10, with
the storm board as capture and sentence editing as the bet.

**The state defines the interface** takes a post on agent harnesses as its source: the
operations a caller may choose from should follow the state, and one description should
both show them to the caller and enforce them. The graph holds that description three
times, as the lifecycle, the process and the IFML model, and the runtime enforces it. It
is never computed as one list, data responses do not carry it, and an illegal sequence is
found when an instance fails rather than at check time. H1 to H5 are the note's items,
ending in a tool surface for agents derived from the model.

## How a note is written

The [principles](/project/principles) page sets the rule: an exploration gets a research
note, a decision gets an ADR, and planned work gets a backlog row. A note opens with its
status, date, the commit it was written against and the notes it follows, so a reader can
tell what the author could see. Several notes carry mockups or screenshots under
[`docs/research/img/`](../research/img/) and
[`docs/research/mockups/`](../research/mockups/).
