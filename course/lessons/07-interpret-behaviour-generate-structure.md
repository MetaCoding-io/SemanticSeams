# Lesson 7 · Interpret behaviour, generate structure

*BPMN and DMN run by an engine, IFML and the API generated, lifecycles and policies
enforced at one choke point. The project's answer to the first failure, for everything
that has an engine.*

::: info Module B draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module B pull request.
:::

## Outcomes

After this lesson you can:

- State ADR-0007's rule, interpret where an engine exists and generate where none does, and
  apply it layer by layer to the table you filled in during lesson 1.
- Explain the execution boundary: the engine never learns about seams, and one generic,
  graph-literate worker resolves each task's seams at the one point every call passes.
- Build the approval process, its decision table, the expense lifecycle and the roles and
  policies, and change a business rule with no code changing.

## The story, in brief

Lesson 3 said the oldest generators worked because nobody edited their output and the input
was complete. [ADR-0007](../../docs/adr/0007-execution-strategy.md) applies that test per
layer. BPMN and DMN have engines, so they are interpreted: SpiffWorkflow runs the native XML
unchanged, with no vendor extension, because the wiring a BPMN tool would put in extension
attributes, which decision a rule task evaluates, which operation a service task calls, is
in the graph as `seam:decidedBy` and `seam:invokes`. SHACL has a validator, so contracts
are interpreted. A lifecycle guard needs no engine, only a check of `seam:fires` against
the entity's state. Policies are checked at the same choke point. The UI, the API routes and
the deployment have no interpreter that reads a graph, so they are generated, and the rule
for what is generated is strict: it holds no business logic. No workflow order, no decision
rule, no validation, no state guard. A generated handler with an `if` about the domain is a
bug in the generator.

The project outline's "unusually clean" mapping from IFML to htmx is why the generated half
is thin: a container is a page, a component a partial, an event with its flow an `hx-post`
with a target. The spike that decided the ADR is in the repository, and so is the vocabulary
gap it found: at the time, the DMN decision was joined to the task by a naming convention,
not by a fact. It is a fact now.

## Read in the repo

- [ADR-0007](../../docs/adr/0007-execution-strategy.md), the per-layer table and the five
  rules.
- [`spikes/adr0007/spike.py`](../../spikes/adr0007/spike.py). The evidence: the chat process
  and its decision running in SpiffWorkflow, resolved from the graph.
- [ADR-0009](../../docs/adr/0009-human-tasks.md) and [ADR-0010](../../docs/adr/0010-channel-started-processes.md),
  for what a user task completes on, and how a channel starts a process.

## Lab: chapters 4 to 7

This is the course's longest lab, four chapters at a brisk pace. Each adds one interpreted
layer:

- [Chapter 4, The process](../../docs/tutorials/expenses/04-process.md): a BPMN process
  started from the form, an approval user task, a correlation key, the `/tasks` inbox.
- [Chapter 5, The rules](../../docs/tutorials/expenses/05-rules.md): a DMN table routing by
  amount, a gateway, a finance form. Do the "Change the rule, not the code" section
  twice, once as written and once lowering the threshold so your own expense routes
  differently. Nothing regenerates.
- [Chapter 6, The lifecycle](../../docs/tutorials/expenses/06-lifecycle.md): a statechart,
  which task fires which transition, a block shown only in one state. Provoke the refused
  transition.
- [Chapter 7, People and permissions](../../docs/tutorials/expenses/07-permissions.md):
  three roles, four policies, 401 against 403, the payment task, and the compliance
  question in the viewer.

If time is short, do chapters 4 and 5 in the session and 6 and 7 before lesson 8. Diff
against `examples/expenses/chapter-07/expenses.trig` when done.

## Scorecard

- **F1, closed for behaviour.** What is interpreted never needs regenerating, so the first
  half of the failure, behaviour in generated code, cannot happen. The second half, code
  that is neither interpretable nor generatable, is lesson 9.
- **F4, moved.** The BPMN and DMN files are vendor-extension-free and run in any engine
  that honours the standard. The wiring lives in the graph, in text, in git.
- **F3, reinforced.** The process diagram the viewer shows and the process the engine runs
  are one file.

## Further reading

- Object Management Group, *BPMN 2.0*, 2011, chapter 13, the execution semantics that make
  interpretation possible; *DMN 1.x*, chapter 8, hit policies.
- SpiffWorkflow and SpiffArena, the pure-Python engine the runtime uses.
- W3C, *ODRL Information Model 2.2*, 2018, the policy vocabulary behind `seam:governedBy`.
- The project outline, section 3, "Why these notations map cleanly to the stack".
