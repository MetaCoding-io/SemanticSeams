# Reading list

The primary sources behind the lessons, grouped by module, with one line on why each is
here. Most of the project's own research notes cite these too; where a note reads a source
closely, it is named beside it. Nothing on this list is required to follow the course.

## Module A · Where the ideas came from

**On drawing software (lesson 1)**

- Harel, "Statecharts: A Visual Formalism for Complex Systems", 1987. The notation that
  survived because it could be executed.
- Fowler, "UmlMode", 2003. Sketch, blueprint, programming language.
- Bell, "Death by UML Fever", *ACM Queue*, 2004. What happened when people tried harder.
- Petre, "UML in Practice", *ICSE*, 2013. Interviews with the people who did not use it.
- Hutchinson, Whittle, Rouncefield and Kristoffersen, "Empirical Assessment of MDE in
  Industry", *ICSE*, 2011; Whittle, Hutchinson and Rouncefield, "The State of Practice in
  Model-Driven Engineering", *IEEE Software*, 2014. Where model-driven engineering worked and
  where it did not.
- Brambilla, Cabot and Wimmer, *Model-Driven Software Engineering in Practice*, second
  edition, 2017. The textbook.
- OMG, *BPMN 2.0* (2011), *DMN* (2015), *IFML* (2015), *SysML v2* (2025). The standards with
  engines, and the one that made views queries. Read with the project's
  [SysML v2 note](../docs/research/2026-11-02-sysml-v2.md) and
  [UML coverage note](../docs/research/2026-10-29-uml-coverage-and-gaps.md).

**On saying what, not how (lesson 2)**

- Kowalski, "Algorithm = Logic + Control", *Communications of the ACM*, 1979.
- Codd, "A Relational Model of Data for Large Shared Data Banks", 1970.
- Forgy, "Rete", *Artificial Intelligence*, 1982.
- Fielding, *Architectural Styles and the Design of Network-based Software Architectures*,
  2000, chapter 5. Hypermedia as the engine of application state.
- Peyton Jones, Blackwell and Burnett, "A User-Centred Approach to Functions in Excel",
  *ICFP*, 2003. The most used functional language.
- Allemang, Hendler and Gandon, *Semantic Web for the Working Ontologist*, third edition,
  2020. The open world for people who build things.
- W3C, *SHACL* (2017), *SPARQL 1.1* (2013), *RDF 1.1 TriG* (2014).
- Gross, Stepinski and Akşimşek, *Hypermedia Systems*, 2023.

**On generators and DSLs (lesson 3)**

- Vlissides, "Generation Gap", 1996, in *Pattern Hatching*, 1998.
- Czarnecki and Eisenecker, *Generative Programming*, 2000.
- Stahl and Völter, *Model-Driven Software Development*, 2006. "Never modify generated
  code."
- Fowler, "Language Workbenches: The Killer-App for Domain Specific Languages?", 2005.
- Kelly and Tolvanen, *Domain-Specific Modeling: Enabling Full Code Generation*, 2008.
- Parr, *Language Implementation Patterns*, 2010, chapters 11 and 12. Logic-free templates.
  Read with the project's [generator kit note](../docs/research/2026-10-30-domain-ide-and-generator-kit.md).
- Boersma, *Building User-Friendly DSLs*, 2025. Structure, notation, meaning, constraints;
  write the reference output first. The same note reads it chapter by chapter.
- Ceri, Fraternali and Bongio, "Web Modeling Language (WebML)", 2000. IFML's parent.

**On the failures (lesson 4)**

- Selic, "The Pragmatics of Model-Driven Development", *IEEE Software*, 2003.
- The project's own [review triage](../orig_convo/review-triage.md) and
  [product brief](../orig_convo/product-brief.md), July 2026.

## Module B · One graph, every diagram a view

- Brown, *The C4 Model for Visualising Software Architecture*. The architecture notation.
- W3C, *SHACL 1.2 User Interface* (draft) and Knublauch's DASH vocabulary. Shapes that drive
  forms.
- IETF, *RFC 9457: Problem Details for HTTP APIs*, 2023.
- OMG, *BPMN 2.0*, chapter 13, execution semantics; *DMN*, chapter 8, hit policies.
- W3C, *ODRL Information Model 2.2*, 2018.
- Brandolini, *Introducing EventStorming*. The workshop the derived storm reproduces; read
  with the project's [DDD note](../docs/research/2026-11-02-domain-driven-design.md).
- The project's [EventCatalog levels](../docs/research/2026-10-15-eventcatalog-levels.md),
  [IFML notation](../docs/research/2026-10-15-ifml-notation.md) and
  [reveal modes](../docs/research/2026-10-15-reveal-modes.md) notes.

## Module C · The hard problems, addressed

- Stevens, "Bidirectional model transformations in QVT: semantic issues and open
  questions", *Software and Systems Modeling*, 2010. Why the general problem is hard, and
  why the project chose tiers. Read with the
  [generation trace note](../docs/research/2026-10-31-generation-trace.md).
- The *Reproducible Builds* project. Why byte-identical output matters.
- McComb, *The Data-Centric Revolution*, 2019, and Semantic Arts' gist ontology. Data
  outlives applications; read with the
  [data-centric model note](../docs/research/2026-10-31-data-centric-model-and-copilot.md).
- The project's [LLM generator note](../docs/research/2026-10-31-llm-generator.md),
  [artifact management note](../docs/research/2026-10-29-artifact-management.md) and
  [domain vocabulary as spec note](../docs/research/2026-11-03-domain-vocabulary-as-spec.md).

## Module D · The frontier

- Löwy, *Righting Software*, 2019. The IDesign method the first profile encodes.
- Evans, *Domain-Driven Design*, 2003, part IV. Bounded contexts and context maps.
- OMG, *SysML v2*, 2025, view definitions and the Systems Modeling API.
- The project's [product review note](../docs/research/2026-11-03-product-review-and-ui-ideas.md)
  and [backlog](../docs/backlog.md).

## The project's own record

Read in this order if you want the whole story as the project told it: the
[project outline](../docs/project-outline.md), the [product brief](../orig_convo/product-brief.md),
the [review triage](../orig_convo/review-triage.md), the
[decision records](../docs/adr/index.md) from 0001 upward, the
[principles](../docs/project/principles.md), and the [research notes](../docs/research/) by
date. The notes are records: a later finding is added as a revision note, never by
rewriting, so each one still says what was believed when it was written.
