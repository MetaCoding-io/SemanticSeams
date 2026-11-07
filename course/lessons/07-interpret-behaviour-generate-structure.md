# Lesson 7 · Interpret behaviour, generate structure

*BPMN and DMN run by an engine, IFML and the API generated, lifecycles and policies
enforced at one choke point. The project's answer to the first failure, for everything
that has an engine.*

## Outcomes

After this lesson you can:

- State ADR-0007's rule, interpret where an engine exists and generate where none does, and
  apply it layer by layer to the table you filled in during lesson 1.
- Explain the execution boundary: the engine never learns about seams, and one generic,
  graph-literate worker resolves each task's seams at the one point every call passes.
- Build the approval process, its decision table, the expense lifecycle and the roles and
  policies, and change a business rule with no code changing.

## The story

### Where an engine exists, interpret

Lesson 3 said the oldest generators worked because their input was complete and nobody
edited their output. [ADR-0007](../../docs/adr/0007-execution-strategy.md) applies that
test to each layer of the application, and its context section records why. The first plan
had been to generate everything, with the process order hard-wired into the scaffold, and
the decision names three problems with that. The diagram stops being the truth, because
the BPMN the viewer shows and the order the code executes are two copies of one fact. The
regeneration fights hand edits, because workflow logic in generated code invites exactly the
edits the next run overwrites. And it is more work, because a generator that emits correct
sequencing with error paths and message events is reimplementing a BPMN engine, and
SpiffWorkflow already is one, in Python, with DMN included.

So the rule is per layer. BPMN and DMN have engines and are interpreted: SpiffWorkflow
runs the native payload unchanged. SHACL has a validator and is interpreted, which lesson
6 covered. A lifecycle guard needs no engine, only a comparison of the transition a task
fires against the entity's current state, so the worker does it. Policies are evaluated at
the same point. The user interface, the API routes and the deployment have no interpreter
that reads a graph, so they are generated, under five rules that the rest of this module
keeps returning to. Generated code holds no business logic: no workflow order, no decision
rule, no validation, no state guard, and a generated handler with an `if` about the domain
is a bug in the generator. The graph is the runtime service registry: the running
application loads the same model the viewer shows, every generated artifact records the
model's content hash, and the runtime refuses to start against a different one. The native
XML stays free of vendor extensions. Generated files are disposable. And generation is
deterministic.

<Diagram name="interpret-generate" caption="The rule, per layer. Where an engine or a validator exists, the native model is interpreted and never regenerated; the interface and the deployment are generated as logic-free structure. One graph-literate worker spans the interpreted layers." />

### The execution boundary

The project outline had already decided where the engine ends: the BPMN engine never
learns about seams. It executes plain XML, and a single generic, graph-literate worker
sits at the one point every cross-component call passes through. For each service task the
worker resolves the task's fragment IRI in the graph, follows `seam:invokes` to the
operation and its contracts, dispatches, validates, enforces the governing policies, and
fires the transition. The BPMN tools you may know put this wiring in extension attributes:
which decision a rule task evaluates, which service a task calls. Here it is in the graph,
as `seam:decidedBy` and `seam:invokes`, and the XML carries only what the standard
defines.

Whether that could work was not assumed. The decision was accepted after a spike, kept in
the repository, that ran the chat app's real process and decision table in SpiffWorkflow
wired from the graph. The engine is told which DMN a business-rule task evaluates by a
parser hook that resolves `seam:decidedBy`, then `seam:inModel`, then `seam:renderPayload`,
and loads the DMN file the graph names; both payloads are parsed from disk untouched; a
test shows that pointing `seam:decidedBy` elsewhere in the graph changes the binding; and
a missing hop fails with an error naming the task and the predicate. The spike also found
what the vocabulary could not yet say, and each gap became a fact: the decision's id in the
DMN file, the binding of a decision input to a shape path, the output that feeds the
process variable, and the correlation key a process is addressed by. You will write all
four in the lab, as `dec:payloadElement`, `dec:input`, `dec:output` and
`proc:correlationKey`.

### A process started by a click, and one started by a message

Chapter 4 is where the model starts to run. The submit event on the expense form
`seam:triggers` the approval process, the API container `seam:executes` it, and the
process names the parameter it is correlated by. The generated submit route changes from
"validate and write" to "start an instance with this correlation key", and the chapter's
observation about the result is the one to carry: neither route branches on anything,
because the BPMN decides what happens next.

The manager's approval is a user task, and [ADR-0009](../../docs/adr/0009-human-tasks.md)
gives it one seam, `seam:completedOn`, from the task to the form a person completes it on.
Everything else follows from facts already in the graph: the screen is the container that
holds the form, the completion operation is what the form's event submits to, the output
is the shape the form writes. The runtime keeps an inbox of open user tasks at `/tasks`,
and completing a task that is not open is a 409, because a task completes once.

The same mechanism starts a process without a click.
[ADR-0010](../../docs/adr/0010-channel-started-processes.md) reads a fact the vocabulary
already had: a message start event that `seam:subscribesTo` a channel starts its process
on each publish. Chapter 8 uses it to make the payout a second process that runs on its
own, so a slow payment never holds up an approval, and lesson 11's lab is where you build
it.

### Rules the business can read

Chapter 5 adds the decision table. Three rows: an amount up to 100 is approved
automatically, up to 1000 goes to a manager, anything else to finance, with a `FIRST`
hit policy so the engine's behaviour when rows overlap is a declared property of the
table. The BPMN gains a business-rule task, which `seam:decidedBy` the decision, and an
exclusive gateway whose outgoing flows test the route the table returned. The conditions
on those flows are the one piece of logic you write in the process file, and they are
expressions over a variable the table filled, nothing more.

Then the chapter does the experiment lesson 2 promised. Lower the manager threshold from
1000 to 200, regenerate, and diff: the only lines that change in the generated code are the
model-hash lines. Nothing in the module mentions amounts, thresholds or routes, because
none of them is in the module. The runtime refuses to run a module whose hash does not
match the mounted model, so a stale module cannot run against a new table by accident,
and a fresh instance of the hotel expense now waits on finance. Continuous integration runs
that experiment on every push. The chapter also shows what happens when the table has no
answer: an amount no row matches is a `ResolutionError` naming the decision, and an
output no gateway flow accepts fails the instance at the gateway. Either way the instance
is marked failed and leaves nothing half-open in the inbox.

### The lifecycle of a thing

BPMN models processes acting on things. The lifecycle of the thing itself, draft to
submitted to approved to paid, is a state machine, and chapter 6 writes one as a
statechart and attaches it to the shape with `seam:lifecycle`. Tasks then say which
transition they fire. Persisting the expense fires the submit transition, recording the
approval fires the approve transition, and the runtime checks each one against the
entity's current state before the task runs, so a refused move writes nothing. The chapter
makes you provoke the refusal by pointing a task at the wrong transition, and the message
you get names the transition, the shape, the current state and the state the transition
requires.

The statechart also solves a problem IFML has never had a clean answer to, which the
project outline singles out: conditional rendering. "Show this block only while the
expense awaits approval" is normally an `if` in a template. Here it is a graph edge,
`seam:visibleWhen` from the component to the state, and the generator writes the condition
from the edge. The chapter points out that the result is the only generated file with a
condition in it, and that the condition came from a fact, not from a template author.

### One choke point for policy

Chapter 7 adds the fifth pillar. Parties and policies are ODRL, which the project reuses
rather than minting. A policy permits a party to use a target, and the target is what the
seam attaches it to: the submit operation for employees, the approval tasks for managers
and finance. The chapter explains a choice worth noticing: policies guard tasks, not
transitions, because guarding the task covers the transition it fires, and a policy on the
transition would only be checked once the process was already moving.

The generated route gains one dependency that names the policy, and the chapter's line
about it is the rule of lesson 7 again: nothing in the generated code names a role. The
runtime evaluates the policy at the choke point. No identity is a 401; an identity the
policy does not admit is a 403 whose body names the policy and the roles presented; and
the inbox is filtered, so a manager sees the approvals and finance sees the payments. The
compliance question at the end of the chapter, which screens can each role use to write
this data, is the same facts asked from the other side, and the gate that follows it,
every write with no policy governing it, is how the model keeps itself honest from then
on.

### IFML to htmx, generated because nothing interprets it

The one layer in this module that is generated rather than interpreted is the interface,
and the reason is simply that no engine interprets IFML into a running UI the way
SpiffWorkflow interprets BPMN. The project outline calls the mapping "unusually clean": a
container is a page, a component a partial, an event with its flow an `hx-post` with a
target and a swap. IFML was designed before single-page applications around server-rendered
state transitions, and htmx is a return to the same machine, so the generated templates
are thin. They hold text and the one derived condition, and the extract step computed
everything else from the graph. Should an interpreter for IFML appear, the decision
record keeps it as a candidate; until then the templates are the inspectable, diffable
output the tutorial persona wanted.

That is the pattern of the module in one lesson. What has an engine runs from the model.
What does not is generated with no logic in it. The lab is the longest in the course: four
chapters, each adding one interpreted layer, and ending with a question the model answers
about itself.

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
