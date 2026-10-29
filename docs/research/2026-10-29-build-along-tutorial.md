# Research note: a build-along tutorial, and the second worked example it produces

*Status: proposal, 2026-10-29. Not yet scheduled. Linked from the
[backlog](../backlog.md) (item 11 and the "Examples and tutorials" section).*

## Two problems, one answer

**The docs never have the reader build anything.** The [tutorial](../tutorial.md) is
excellent at what it does: clone the repository, regenerate, `docker compose up`,
chat, change one title in the model and watch the app follow. But the model is handed
over finished. A reader learns that the pipeline works, not how to write a model.

**Layer mode is parked until a bigger model exists.** Backlog item 11 (M008/S03) waits
"until there is a second worked example large enough to need it", and the slice opens by
checking whether that is so. The chat app cannot pass that check, and the reason is
structural rather than a matter of adding features (next section).

The answer to both is a second tutorial in which the reader **builds an expense approval
app from an empty file**, one layer per chapter, ending with `docker compose up`. Its
last chapter is the second worked example.

## Why the chat app cannot make layer mode necessary

Measured with the queries in the next section, on `examples/chat-app/chat-app.trig` at
`main` on 2026-10-29:

| Measure | Chat app |
|---|---|
| Models | 6, exactly one per notation (C4, IFML, BPMN, DMN, statechart, shape graph) |
| Cross-layer seam edges | 58 |
| Most models any one element is reached from | 3 (`send_message_op`, `MessageShape`) |
| Seam predicates never used | `subscribesTo`, `conformsTo`, `realizes` |

With one model per layer, the descent shows everything in four clicks: there are no
sibling models for it to hide, and no element is reached from enough places that tracing
it by clicking becomes tedious. A stacked overview of six planes, each holding one small
model, adds little that the descent and the inspector do not already give. That matches
the reveal-modes note's finding that layer mode is "legible only as an overview".

Layer mode earns its place when three things are true:

1. **A layer holds several models,** so the descent hides the siblings you did not click
   into, and "which processes touch this?" means visiting each one.
2. **One element is reached from many models across several layers,** so tracing it by
   clicking means many round trips.
3. **Answers span models:** a canned question's rows come from several models at once.

## A complexity check, so M008/S03's first step is a measurement

Proposed: M008/S03 opens by running these three queries against the candidate example,
rather than deciding by eye. They run unchanged against any model (the numbers above come
from them).

```sparql
PREFIX seam: <https://w3id.org/seams/seam#>

# 1. Models per notation
SELECT ?notation (COUNT(DISTINCT ?model) AS ?models) WHERE {
  ?model a seam:Model ; seam:notation ?notation .
} GROUP BY ?notation ORDER BY DESC(?models)
```

```sparql
PREFIX seam: <https://w3id.org/seams/seam#>

# 2. The elements reached from the most distinct models
SELECT ?target (COUNT(DISTINCT ?model) AS ?models) WHERE {
  ?source ?p ?target ;
          seam:inModel ?model .
  FILTER(STRSTARTS(STR(?p), STR(seam:)))
  FILTER(?p NOT IN (seam:inModel, seam:notation, seam:renderPayload, seam:mediaKind, seam:detailedBy))
} GROUP BY ?target ORDER BY DESC(?models) LIMIT 5
```

```sparql
PREFIX seam: <https://w3id.org/seams/seam#>

# 3. Cross-layer seam edges
SELECT (COUNT(*) AS ?edges) WHERE {
  ?s ?p ?o .
  FILTER(STRSTARTS(STR(?p), STR(seam:)))
  FILTER(?p NOT IN (seam:inModel, seam:notation, seam:renderPayload))
}
```

Proposed thresholds, to be calibrated when the example exists:

| Condition | Threshold | Chat app |
|---|---|---|
| Notations with two or more models | at least 3 | 0 |
| Most models one element is reached from | at least 5 | 3 |
| Cross-layer seam edges | reported, not gated | 58 |

Edge count alone is a poor signal, which is why it is reported but does not gate: a
single large model can have many edges and still be fully visible by descent.

## The app: expense approvals

Employees submit expenses, managers approve them, finance pays them out.

- **It is BPMN and DMN's home ground.** Forms, human approvals, decision tables and a
  clear entity lifecycle, all of them standard material for the two notations.
- **Everyone understands it.** No domain explanation is needed before chapter 1.
- **It needs no external service.** No LLM key, no vector store. The chat app needs a
  provider key or a stub; this runs entirely on a laptop.
- **Roles are intrinsic.** Employee, manager and finance make authorization a real layer
  rather than a single policy on one event.
- **It grows naturally** into several models per layer: an employee portal, a manager
  queue and a finance console; an approval process and a payout process; an approval
  decision and a policy-compliance decision; an expense lifecycle and a payout-batch
  lifecycle.

## Chapters

Each chapter adds one layer, ends with something the reader can see or run, and leaves a
model that conforms to the seam shapes.

| # | Chapter | The reader writes | The reader sees or runs | Exercises |
|---|---|---|---|---|
| 1 | An empty file and an architecture | One system, an employee portal container and an API container, in a model graph and the seams graph | The C4 view in the viewer, with the health badge green | Named graphs, `seam:inModel`, `seam:notation` |
| 2 | The data | An `Expense` shape in SHACL, then a deliberate mistake | The health badge turning red and naming the element, then green again | Shapes as the vocabulary, model health |
| 3 | The screens | An IFML page with a submit form and a list, an operation the form submits to | Generated htmx and routes, `docker compose up`, a form that rejects invalid input against the shape | IFML, `seam:submitsTo`, `seam:writes`, the generators |
| 4 | The process | A BPMN process: submit, approve, record, triggered from the form | The submission running through SpiffWorkflow; the BPMN view in the viewer | `seam:triggers`, `seam:invokes`, the runtime |
| 5 | The rules | A DMN table: auto-approve small amounts, route the rest to a manager or finance | Different paths for different amounts, with no code change | `seam:decidedBy`, interpreted DMN |
| 6 | The lifecycle | A statechart: draft, submitted, approved or rejected, paid | The approve button appearing only for submitted expenses; an illegal transition refused | `seam:lifecycle`, `seam:fires`, `seam:visibleWhen`, the lifecycle guard |
| 7 | People and permissions | Employee, manager and finance roles; policies on events, operations and transitions; a manager queue | Who can do what, enforced; the compliance question answered in the viewer | `seam:governedBy`, the policy hook, a new canned query (below) |
| 8 | Growing up | A payout process fed through a channel, a finance console, a worker container, a second environment | The whole system; the complexity check passing; layer mode earning its place | `seam:publishesTo`, `seam:subscribesTo` (first real use), several models per layer |

Chapter 7 is where the project's flagship question finally ships. The project outline's
second example question, "every UI event reachable by role X that eventually writes to
this shape", is not among the three canned queries today. Here it is the natural
question: *which screens can an employee use that eventually write a Payment?*

### The model at the end of chapter 8 (estimate)

| Notation | Models | Examples |
|---|---|---|
| C4 | 1 | Portal, manager queue, finance console, API, worker, database; staging and production |
| IFML | 3 | Employee portal, manager queue, finance console |
| BPMN | 2 | Submit and approve; payout batch |
| DMN | 2 | Approval routing; policy compliance |
| Statechart | 2 | Expense; payout batch |
| Shape graph | 1 | Expense, receipt, approval, payment, payout batch, employee |

That is four notations with two or more models, against a threshold of three, and the
`Expense` shape reached from roughly seven models: three interfaces, two processes and
two decisions. Both estimates are to be confirmed by the check once the model exists.

## What it forces us to build or decide

These are the parts that do not exist yet. Each is a candidate slice.

1. **A configurable model path.** The generators already take any TriG path
   (`python -m seams_gen <generator> <trig> --out <dir>`). The rest of the pipeline is
   tied to the chat app: `Runtime.load("/model/chat-app.trig")` in the runtime's
   documented entry point, `SEAMS_MODEL` and three bind mounts in `compose.yaml`, three
   `COPY examples/chat-app/...` lines in `docker/runtime.Dockerfile`, and `DATA_PATH` and
   `DATA_DIR` in `viewer/app.py`. This is the first enabling slice and is useful on its
   own.

2. **Human tasks.** The vocabulary has `proc:UserTask`, whose comment already expects it
   "to surface in generated UIs later". The runtime does not handle one: the worker
   selects ready tasks with `not t.task_spec.manual`, so a user task waits forever.
   Approvals need two things:
   - **Runtime:** list a person's ready user tasks and complete one, with identity and the
     policy hook applied.
   - **Vocabulary:** a way to say which screen a person uses to complete a task. Today
     `seam:triggers` runs from the interface to the process; nothing runs back. A new
     predicate must earn a query (design rule 2). Candidates: *which screens does a
     person need to finish this process?* and *which roles can complete this approval?*
     This is an ADR-sized decision, and it should be taken before chapter 4 is written.

3. **Role policies.** The runtime has a `PolicyEvaluator` protocol with a
   `PresenceEvaluator` default, as ADR-0007 scoped for v1. Chapter 7 needs an evaluator
   that checks the caller's role against the policy. That is a small evaluator behind the
   existing protocol, not general ODRL evaluation, which stays post-v1.

4. **An asynchronous second process.** Chapter 8 starts the payout process from an event
   on a channel. Check whether the runtime's channel support can start a process from a
   published event, or only stream to clients. A finance user pressing "Run payout" is
   the fallback that avoids a scheduler; a BPMN timer start event is the fuller version.

5. **Checkpoints that cannot rot.** The reader grows one file, but the repository should
   keep the model as it stands at the end of each chapter, for example
   `examples/expenses/chapter-NN.trig` with its payloads. CI parses each checkpoint,
   validates it against the shapes, and runs the generators on it; the final checkpoint
   also runs end to end like the chat-app tutorial. Without that, a vocabulary change
   silently breaks chapter 3 and nobody notices until a reader does.

## Where it lives in the docs

A **Tutorials** section with two tracks:

- **Quick start: run the chat app.** The existing tutorial: ten minutes, a finished model,
  the pipeline end to end.
- **Build an expense approval app.** The new tutorial, one page per chapter, each opening
  with what the reader will have at the end and closing with the checkpoint file to
  compare against.

The chat app stays the quick start and the viewer's default model.

## Alternative considered: grow the chat app

Extending the chat app into a team knowledge assistant would also reach the density
needed: accounts and sharing (roles, policies, a conversation lifecycle), document
retrieval (an ingestion process fed by a channel, a document lifecycle, a worker and a
vector store), and moderation (a moderation decision, a human review task, an admin
console). It keeps tutorial continuity and reuses the pipeline that already runs.

It loses on the goal that started this: the reader is still handed a finished model.
Retrieval also needs embeddings and a vector store, which makes the local stack heavier.
It remains a good later chapter for the quick-start track, and moderation in particular
would reuse the human-task work from point 2.

## Proposed slices (for scheduling)

Unscheduled; the order is the dependency order.

1. Configurable model path across the runtime, compose, the Dockerfile and the viewer.
2. The complexity check as a script with the thresholds above, run on any model.
3. Chapters 1 to 3, with their checkpoints in CI. No process yet, so no new runtime work.
4. Human tasks: the ADR on the vocabulary, then runtime support.
5. Chapters 4 to 6.
6. The role evaluator and chapter 7, with the new canned query.
7. Chapter 8 and the asynchronous process. Then M008/S03 runs the complexity check.

## Open questions

- Should the checkpoint files be cumulative copies, or should each chapter add a file to a
  directory that the viewer and runtime load together? Cumulative copies are simpler to
  diff against; a directory mirrors how the reader's file grows only if the reader also
  splits files.
- Does the new human-task predicate point at an IFML view container, a view component, or
  the whole interaction model?
- Is one shape-graph model enough at the end, or does the data layer also deserve a second
  model, for example a separate payments model owned by finance?
