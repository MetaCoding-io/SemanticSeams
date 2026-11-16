# ADR-0046: Event-Storm Import — a Big-Picture Storm in the `seams storm` Timeline Format Becomes a Skeleton Model and a BPMN Payload, Written by `seams_edit`, Flagged and Not Refused for What a Storm Does Not Say

**Status:** Accepted

**Date:** 2026-11-16

**Source:** milestone M033/S03; backlog X12 (event-storm import); research note
[Domain-driven design](../research/2026-11-02-domain-driven-design.md) section 4;
builds on [ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0007](./0007-execution-strategy.md),
[ADR-0017](./0017-write-path-and-editor.md) and
[ADR-0044](./0044-interchange-exports.md)

## Context

`seams storm` (backlog B4, `seams_gen.storm`) derives a process's event-storm timeline
from the graph. The DDD note names the inverse as the entry point for people who will
never write TriG: a workshop's storm board read into a skeleton model. Its acceptance
test is that deriving the storm from the imported model gives the storm back. Backlog
X12 adds that the skeleton is *flagged, not refused*: it loads, and the seam shapes and
the viewer's health panel report what it lacks.

Four things constrain the import:

- **The model is the source of truth.** The importer invents no fact the storm does not
  state. What a big-picture storm leaves out (the paths between steps, operations,
  routes, stores, lifecycles' initial states) stays absent, so the checks that already
  exist report it.
- **`seams_gen.storm.derive` reads BPMN.** A BPMN step is a `FlowNode` of
  `Process.nodes()`, which walks the process's BPMN payload. A model of TriG alone has
  no steps, so the skeleton needs a payload. With no sequence flows, `parse_bpmn` gives
  the nodes in document order, so the payload can carry the storm's order and nothing
  more.
- **One write path** (ADR-0017, principle 10). Only `seams_edit` writes model files,
  and it edits text that already exists. It has no way yet to create a model.
- **IRIs** (ADR-0002). A BPMN element's IRI is `<BPMN model IRI>#<bpmn id>`, and seam
  edges live only in the seams graph (ADR-0001).

## Decision

### 1. The input is a subset of the `seams storm` timeline

The importer reads UTF-8 Markdown, line by line. Blank lines are ignored anywhere.
Every other line must be one of these, in this order, or the import fails:

```markdown
# Event storm: Expense Approval (`approval_process`)

<!-- base: https://example.org/expenses/ -->

## Timeline

1. **Submit Expense** (`submit_expense`)
   - actor: Employee (`employee`)
   - command: Submit Expense (`submit_expense`)
2. **Approve Expense** (`approve_expense`)
   - actor: Manager (`manager`)
   - command: Approve Expense (`approve_expense`) on `approve_form`
   - aggregate: Approval (`ApprovalShape`)
```

- **The heading** `` # Event storm: <label> (`<name>`) `` names the process: its
  `rdfs:label` and its local name. The derived timeline's heading has no name, since
  it is followed by the process IRI. The import puts the name in the heading so the
  base comment can stay one IRI.
- **The base** `<!-- base: <IRI> -->` is the namespace every name is minted under.
  It must be an absolute IRI ending in `/` or `#`.
- **`## Timeline`**, then the numbered steps. Numbers start at 1 and go up by one.
  A step heading is `` <n>. **<label>** (`<name>`) ``.
- **Entries** under a step are `` - <kind>: <label> (`<name>`) ``, where kind is one of
  `actor`, `command`, `aggregate`, `domain event` and `policy`. The only suffix is a
  command's `` on `<form>` ``. Indentation is free.
- The file may end with the derived timeline's `## Read models` and `## Gaps`
  sections. They are skipped up to the end of the file, since they are what the
  derivation reports rather than what a workshop authors.

A name is a BPMN id and a local name, so it must match `[A-Za-z_][A-Za-z0-9_.-]*`.
Anything else is a parse error: an unknown kind, a line out of place, a missing name, a
number out of sequence. So is a command with an operation tail (`→ POST ...`), since
the skeleton has no operations (section 3). Each error is a `GeneratorError` that names
the line number and quotes the line. A storm that parses always imports.

### 2. Mapping each sticky to the vocabulary `seams_gen.storm` reads

A step is one of two things, set by its entries:

- **A trigger** is a step whose command has no `on` form. It becomes an `ifml:Event`
  `<base><name>` (`rdfs:label` the command's label) that `seam:triggers` the process.
  Its entries may only be actors and the one command. Trigger steps come before every
  BPMN step, as the derivation lists them, and the derivation sorts them by IRI.
- **A BPMN step** is every other step. It becomes a flow node of the payload with id
  `<name>`, lifted as `<BPMN model IRI>#<name>` with its `rdfs:label`:
  - with a command `` ... on `<form>` ``, a `bpmn:userTask` lifted as `proc:UserTask`, which
    `seam:completedOn` the `ifml:Form` `<base><form>`. The command's name must be the
    step's name, as the derivation writes it;
  - with a policy, a `bpmn:businessRuleTask` lifted as `proc:BusinessRuleTask`, which
    `seam:decidedBy` the `dec:Decision` `<base><name>` (a policy sticky is the
    "whenever" rule, a decision in this vocabulary). A step has at most one policy,
    and not both a command and a policy;
  - otherwise a `bpmn:serviceTask` lifted as `proc:ServiceTask`.

The other entries, on either kind of step where allowed:

| Sticky | Facts | `derive` reads it as |
|---|---|---|
| Actor `` L (`n`) `` | `<base>n a odrl:Party ; rdfs:label L`; one `odrl:Policy` `<base><step>_policy` per step with one `odrl:Permission` per actor (`odrl:assignee`, `odrl:action odrl:use`, `odrl:target` the step's element), and the step's element `seam:governedBy` it | the actor (policy) |
| Aggregate `` L (`n`) `` | `<base>n a sh:NodeShape ; rdfs:label L`; the step's element `seam:writes` it | the aggregate |
| Domain event `` L (`n`) `` | `<base>n a state:Transition ; rdfs:label L ; state:to <base>n_state`, the state `a state:State ; rdfs:label L`; the step's element `seam:fires` it | the domain event |
| Policy `` L (`n`) `` | `<base>n a dec:Decision ; rdfs:label L` | the decision |

An actor on a BPMN step requires a command: the derivation reads a user task's actors
and nothing else's. An aggregate, domain event or policy on a trigger is an error, since
the derivation reads them only on BPMN nodes. A step with no entry is an error, because
the derivation would not show it. A name met twice is one element. Its label and kind
must agree each time, so a party labelled two ways, or a name used for a step and a
shape, is an error naming the later line.

### 3. The skeleton and what it leaves out

The models, each a `seam:Model` with an `rdfs:label` of the process label and the
notation, in a graph `<urn:seams:graph:model:<local name>>`:

| Model IRI | `seam:notation` | Holds |
|---|---|---|
| `<base><process>_bpmn` | `seam:BPMN`, `seam:renderPayload <<process>.bpmn>` | the process and the lifted flow nodes |
| `<base><process>_ifml` | `seam:IFML` | the trigger events and the forms |
| `<base><process>_data` | `seam:ShapeGraph` | the aggregate shapes |
| `<base><process>_lifecycle` | `seam:Statechart` | the domain events' transitions and states |
| `<base><process>_dmn` | `seam:DMN` | the decisions |

A model is written only when it holds an element. Every element is `seam:inModel` its
model, in that model's graph. The process is `seam:detailedBy` its BPMN model, and every
other seam edge (`seam:triggers`, `seam:completedOn`, `seam:writes`, `seam:fires`,
`seam:decidedBy`, `seam:governedBy`, `seam:notation`, `seam:renderPayload`) is in
`<urn:seams:graph:seams>`, with the parties and policies, as the expense tutorial
writes them. The manifest graph `owl:imports` the version IRI of each vocabulary used,
read from `ontology/`, never written into the code.

The payload `<process>.bpmn` holds one `bpmn:process` with id `<process>` and the BPMN
steps' nodes in step order, named by their labels. The importer never writes these
facts:

- sequence flows, start and end events, gateways, lanes;
- operations (`seam:submitsTo`, `seam:invokes`), routes, pages, interaction models and
  the components that read an aggregate;
- stores, target classes, a lifecycle's state machine, its initial state and the
  states a transition leaves;
- decision tables and their DMN payload, containers that execute or present anything.

So the seam shapes and the viewer's health panel report the skeleton as nonconformant
(an event with no owning view, a form with no event that submits, and so on), and
`seams generate` refuses it, while `seams.load` loads it and `seams storm` derives it.

### 4. Gaps

The import reports what it left out, one line per fact, each once: first the gaps of
`seams_gen.storm.derive` on the written skeleton in its order, then the process's lack
of sequence flows, a start event and an end event. The CLI writes each to stderr as
`seams import-storm: gap <detail>` and exits 0. A parse error exits 2 naming the line.

### 5. Writing through `seams_edit`

The import is one `seams_edit.Patch` of quads, sorted, and the payload's text.
`seams_edit` gains a create path: it renders the patch with `apply_text` over a header
of `@prefix` lines (the vocabulary prefixes and `:` for the base), checks the result as
`apply_text` does, and writes the TriG file and the payload together through
`write_all`, or neither. It refuses a path that exists. The importer writes no file
itself, and writes nothing on an error.

Same storm, same bytes: quads, models and entries are sorted. Nothing in the output
holds a timestamp or a host path, and the payload is named relative to the TriG file.

## Consequences

- A workshop's storm becomes a model `seams storm` reads back, with its actors,
  commands, aggregates, domain events and decisions in step order, and the shapes list
  the work left before it generates.
- The format is the derived view's own text, so a `seams storm` timeline cut down to
  its sticky labels and names imports as it is. Operations, stores and lifecycles are
  added afterwards in the viewer's edit mode or the text editor, through the same write
  path.
- The storm stays a view, as the DDD note asks. The import is a one-time draft, not a
  second source: re-importing over an edited model is refused (the output exists), not
  merged.
- `seams_edit` can create a model file. The imports from OpenAPI, SQL and compose files
  (X10) can use the same path.
