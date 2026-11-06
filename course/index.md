# From diagrams to running systems

*A course on model-based engineering and code generation: where the ideas came from,
why they kept stalling, and what SemanticSeams does about it.*

Every generation of software tooling has promised the same thing: describe the system
once, in a form people can read, and let machines produce the rest. CASE tools promised
it in the 1980s, UML and Model-Driven Architecture in the 1990s and 2000s, low-code
platforms in the 2010s, and large language models promise it today. Each time, the same
six problems came back. Some code could not be generated. Hand edits never found their way
back into the model. Diagrams turned out to be pictures, not models. Models did not diff,
merge or version. Every tool drew one layer. And nobody quite trusted the generator.

SemanticSeams is a small open-source project that takes those six problems as its
design brief. One RDF graph holds the architecture, the screens, the processes, the
decisions, the data shapes, the lifecycles, the policies and the deployment of an
application. Diagrams are views over that graph. Behaviour is interpreted by engines that
already exist; structure is generated, deterministically, with a trace from every output
line back to the facts behind it. Where code must be written by hand or drafted by a
language model, the model says where, and tests derived from the model say whether it
is right.

This course teaches both halves: the history, so that you can recognise the six problems
in any tool you meet, and the project, as one worked answer to them. It is honest about
what is finished and what is not. Every claim a lesson makes points at a committed file,
a decision record or a test, and a [scorecard](scorecard.md) tracks which problems are
closed, which are closed in part, and which are still open in the project's backlog.

## Who it is for

Working developers and architects. You know code, continuous integration and Docker.
You may never have used BPMN, SHACL or RDF, and the course assumes you have not. Each
notation is introduced the first time a lesson needs it, in the chapter of the
[expense approval tutorial](../docs/tutorials/expenses/index.md) that uses it, and no
lesson asks you to learn a standard for its own sake.

## How it is organised

Twelve lessons in four modules, each lesson 60 to 90 minutes: 20 to 30 minutes of
reading, a few files to open in the repository, and a 30 to 45 minute lab. The labs
reuse the project's own tutorials, so every command you run is one that continuous
integration runs too, and each chapter has a checkpoint model you can diff against your
own.

| Module | Lessons | What you take away |
|---|---|---|
| **A · Where the ideas came from** | 1 to 4 | The history of drawing software, of declarative programming and of code generation, told from a developer's seat, ending in the six failures and the scorecard. |
| **B · One graph, every diagram a view** | 5 to 8 | The graph, the seams, shapes as the contract, behaviour interpreted and structure generated, and the cross-layer questions. Labs build the expense app through chapter 7. |
| **C · The hard problems, addressed** | 9 to 11 | Code the templates cannot write, getting changes back into the model, and deployment and change safety. Labs finish the tutorial through chapter 10. |
| **D · The frontier** | 12 and the capstone | What the project has not done yet, where the backlog points, and a capstone of your own. |

### Module A: Where the ideas came from

1. [Drawing software](lessons/01-drawing-software.md). Flowcharts, structured analysis, UML, MDA, SysML and the OMG process stack. The notations that survived had an engine.
2. [Saying what, not how](lessons/02-saying-what-not-how.md). SQL, logic and rules, shapes and schemas, hypermedia and desired state. Declarative wins in a closed domain with a trusted evaluator, and falls off a cliff outside it.
3. [The program that writes the program](lessons/03-the-program-that-writes-the-program.md). CASE and round trip, MDA transformations, language workbenches, low-code, and language models as the newest generator with the oldest problem.
4. [Why it kept stalling](lessons/04-why-it-kept-stalling.md). The six failures, with evidence, and the scorecard the rest of the course is marked against.

### Module B: One graph, every diagram a view

5. [One graph, many views](lessons/05-one-graph-many-views.md). Named graphs, IRIs as identity, native payloads, and the seams. Lab: tutorial chapters 1 and 2.
6. [Shapes before generation](lessons/06-shapes-before-generation.md). SHACL on the data and on the model itself; a model that passes the shapes must generate. Lab: chapter 3.
7. [Interpret behaviour, generate structure](lessons/07-interpret-behaviour-generate-structure.md). BPMN and DMN run by an engine, IFML and the API generated, lifecycles and policies at one choke point. Lab: chapters 4 to 7.
8. [Questions no single tool can answer](lessons/08-questions-no-single-tool-can-answer.md). The query catalog, derived sequence diagrams and event storms. Lab: write a question and pin its rows.

### Module C: The hard problems, addressed

9. [Code the templates cannot write](lessons/09-code-the-templates-cannot-write.md). A stub written once, then owned; declared errors; a language model drafts behind the stub and tests decide. Lab: chapter 9.
10. [Getting changes back into the model](lessons/10-getting-changes-back-into-the-model.md). The generation trace, the lock, write-back from an output line, and a copilot that proposes model patches. Lab: break and then honour the round trip.
11. [Same model, same bytes](lessons/11-same-model-same-bytes.md). Determinism, versioned vocabularies and migrations, environments, scenarios as tests, data that outlives the application. Lab: chapters 8 and 10.

### Module D: The frontier

12. [What is still open](lessons/12-what-is-still-open.md). Domain profiles, bounded contexts, SysML v2 interchange, drafted generators, the model as a context layer for coding agents, and the backlog's honest list.

Then the [capstone](capstone.md): write and register a generator of your own, or model a
domain of your own to `docker compose up`, or both.

## What you need

A laptop with Python 3.12, [uv](https://docs.astral.sh/uv/) and git. Docker is needed
from lesson 11 (tutorial chapter 8) onward. No API key is needed: the one lesson that
drafts code with a language model has a hand-written path, and the chat app runs against
a built-in stub. [Before the first lesson](setup.md) walks through the install.

## How to read a lesson

Every lesson has the same six parts. **Outcomes** says what you will be able to do.
**The story** is the reading. **Read in the repo** names the two or three files that
carry the lesson's claim. **Lab** is the hands-on part, with the checkpoint to diff
against. **Scorecard** says which of the six rows moved and points at the evidence.
**Further reading** lists the primary sources, most of which the project's own
[research notes](../docs/research/) cite.

The course is written against the repository at a point in time, and the project moves.
Where a lesson says "today", it means the state recorded in the
[backlog](../docs/backlog.md); when the two disagree, the backlog is right and the lesson
needs a pull request.
