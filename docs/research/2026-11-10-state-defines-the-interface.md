# Research note: the state defines the interface

*Status: research / design input, 2026-11-10. Not yet scheduled. Linked from the
[backlog](../backlog.md) ("Not yet scheduled" section, items H1 to H5). Follows the
[domain vocabulary as spec note](2026-11-03-domain-vocabulary-as-spec.md) (what a coding
agent is given, C6), the [LLM generator note](2026-10-31-llm-generator.md) (context
assembly, C3) and the [UML coverage note](2026-10-29-uml-coverage-and-gaps.md) (derived
tests and coverage). Written against `main` at `d219cbf`.*

## Source

A post by 工业聚 (@guyingjie129) on 2026-11-10
([link](https://x.com/guyingjie129/status/2119973431819309300)), in Chinese, quoting a
one-line post by duve (@jevonduve) of 2026-11-09: "write your agent harness as a
coalgebra on a polynomial functor". Paraphrased:

- This is a deeper description than the state-machine framing of agents that is popular
  at the moment. Different states allow different operations, so there is a map from a
  state to the operations it allows.
- For an agent harness, the tools, skills and MCP servers on offer should change with
  the state of the task rather than stay fixed. Where that change is not described, the
  model invents actions and makes invalid tool calls more often.
- The more domain knowledge and domain operations are encoded this way, the more
  efficient and correct an agent's work becomes.
- Three familiar cases of the same idea: HATEOAS, where a response carries links to the
  endpoints that are valid next; a GraphQL query branching over a union type; and a
  chain of method calls where each call's return type decides which methods exist next.

The post attaches three images and a 28-second video. They are kept out of the
repository, as the author's media, and this note describes the images. **The video was
not watched.** The post's text was read through a mirror API, since X serves it only to
signed-in clients.

1. *"Let the state define the interface."* A task policy Explore, Implement, Verify, each
   phase offering two tools (search and read; edit and run; test and inspect). The
   formula `P(X) = Σ X^Aᵢ` over interfaces `i`, with `α : S → P(S)`: a state yields its
   current interface `i` and a function from the operations `Aᵢ` that interface allows
   to the next state. A HATEOAS order response whose links (view, track, receipt)
   reflect that the order has shipped. Two instructions: expose the current
   capabilities to the model, and enforce the same rules in the harness.
2. *"Types shape the next step."* A GraphQL union `Draft | Review | Ready | Published`
   where each variant offers different fields, marked as observations rather than
   mutations. Below it a typed chain `edit`, `submit`, `approve`, `publish`, `url`, with
   `draft.submit().publish()` rejected because `Review` has no `publish()`.
3. A code listing: a coffee machine as one class per state (idle, grinding, brewing,
   ready, off), each holding only the transitions that state allows.

The post gives no measurement for its claim about error rates. This note takes the
structure and leaves the claim as the author's.

## The claim, in this project's terms

Stripped of the category theory, the claim has two parts. A state machine says which
state follows which. The post adds that each state also has an *interface*, the set of
operations a caller may choose from, and that this interface should be both shown to the
caller and enforced on it, from one description.

The graph holds three such descriptions, one per layer:

| Layer | State | Interface in that state | Next state |
|---|---|---|---|
| Lifecycle (`state:`) | an entity's `state:State` | the `state:Transition`s whose `state:from` is that state, and through `seam:fires` the tasks that fire them | `state:to` |
| Process (BPMN) | where the instance's tokens are | the open user tasks, each with the form it is `seam:completedOn` | the flow out of the completed task |
| Interaction (IFML) | the `ifml:ViewContainer` on screen | its `ifml:Event`s, each with the operation it `seam:submitsTo` | the `ifml:NavigationFlow` target |

IFML is the closest fit: a view container that offers events, each leading to a next
container, is the post's picture drawn for a person instead of a model. `seam:governedBy`
policies then narrow each interface by who is asking. So the state the post calls `S` is
here a product: the entity's lifecycle state, the process position and the identity.

## What already matches

- **The rules are data, and they are executed.** BPMN and DMN are interpreted from their
  native XML ([ADR-0007](../adr/0007-execution-strategy.md)), and the lifecycle is a
  statechart in the graph. The post's closing line, "encode domain knowledge as
  executable interaction rules", is principle 2.
- **The harness enforces them.** `seams_runtime.lifecycle.LifecycleGuard.check` runs
  before a task that `seam:fires` a transition and raises `LifecycleViolation` naming
  the transition, the current state and the state required. A refused task writes
  nothing. Tutorial [chapter 6](../tutorials/expenses/06-lifecycle.md) provokes one.
- **One interface is already exposed per state.** `runtime.user_tasks(identity)` and
  `GET /tasks` list only the user tasks that are open and that every policy on the task
  permits for that identity, each with its form. With `Accept: application/json` the
  same list comes back as data.
- **The screen can follow the state.** `seam:visibleWhen` puts a component behind a
  lifecycle state, and the htmx generator renders the guard.
- **The inverse question is a query.** `docs/queries/what-moves-state.rq` answers "which
  tasks may move an entity out of this state", and `ModelGraph.transitions_from` gives
  the transitions leaving a state.
- **Hand-written code is checked against the same rules.** The acceptance generator's
  `test_transition_*` tests run `transition_guard` for each task that fires a
  transition: accepted from `state:from`, refused from every other state.

## Where the project falls short

**1. The interface is never computed as one thing.** The pieces above live in three
places: lifecycle exits in the library, open tasks in the runtime's store, permissions
in the policy evaluator. Nothing answers "for this expense, for this identity, which
operations are legal now". Every caller that wants the menu has to assemble it, and none
does.

**2. Data responses do not carry their next steps.** The generated API's JSON responses
carry one `Link` header, naming the JSON-LD context
([ADR-0024](../adr/0024-json-ld-context.md)). They do not say which operations are valid
on the returned entity. The model uses Hydra to describe operations (method, path
template, error statuses), but not as hypermedia in the response, which is what Hydra is
for and what the post's HATEOAS example shows. A client other than the generated pages
learns that a call was illegal from the refusal.

**3. The screen's guard is written by hand, beside the lifecycle.** `seam:visibleWhen`
is authored per component. `seamsh:VisibleWhenGuardShape` checks that the state belongs
to the lifecycle of the shape the component reads, and nothing more. A form that leads
to a transition out of `submitted` can be left visible in every state, or guarded with
the wrong one, and the model still passes. That is the same fact stated twice
(principle 1), with no check that the two agree.

**4. An illegal sequence is found at run time.** The post's typed chain rejects
`draft.submit().publish()` before anything runs. Here the equivalent mistake, a process
path that reaches a task whose transition cannot fire from the state the path leaves the
entity in, passes the shapes and `seams check`, and fails when an instance takes that
path. `seams coverage` reports transitions nothing fires and paths no scenario runs, so
a scenario over the bad path would catch it, but only if someone wrote one. Principle 5
says shapes catch faults before generation; this fault is caught after deployment.

**5. State is a label in a field, not a type.** The lifecycle's state labels are the
values a payload's status field carries (`seams_runtime/lifecycle.py`). Handler stubs
are typed from shapes, and the docstring names the transition, but a handler's entity
has the same type in every state. The post's per-state types, where an operation absent
from a state does not exist, have no counterpart for owned code.

**6. Nothing offers an agent a tool surface.** `seams context`, `seams propose` and
`seams suggest` each build one prompt from model facts and take one answer. The gateway
makes no tool calls. No MCP server exists; the only mention of one in the repository is
a passing remark in the
[EventCatalog note](2026-10-15-eventcatalog-levels.md). So the post's main subject, a
tool list that changes with the task, has nothing here to apply to yet, although the
graph holds every fact such a list would be computed from.

## Suggestions

In dependency order. Each is a backlog row.

**H1. An affordances view.** One answer to "what may happen next". The model half
belongs in the `seams` library, read-only: for a shape and a lifecycle state, the
transitions leaving it, the tasks that fire them, the operations and forms that reach
those tasks, and the policies on each. The runtime half joins that with what only the
runtime knows: the entity's current status, the instance's open tasks and the identity.
`runtime.user_tasks` becomes one case of it. No vocabulary is needed; every edge exists.

**H2. Responses that carry their next steps.** A JSON response for an entity lists the
operations H1 allows on it now, for the caller's identity, in Hydra's own terms. This
needs an ADR first: whether the operations go in the body or in `Link` headers, how
that sits with the context link of ADR-0024, and whether a refusal should list them
too. The generated smoke tests can then check that an operation the response does not
offer is refused, which tests both halves of the post's "expose and enforce" against
each other.

**H3. Check the screen guards against the lifecycle, then derive them.** First a review
finding in `seams check`, beside R1's: a component whose event leads, through
`seam:submitsTo` and the process, to a task that fires a transition, and which is
visible in a state that is not that transition's `state:from`. Later the guard could be
derived and `seam:visibleWhen` kept for the cases that are not about a transition, such
as the tutorial's "awaiting approval" block. The check comes first because it removes
the drift without changing what authors write.

**H4. Walk the process against the lifecycle at check time.** For each BPMN path the
library already enumerates for coverage, track the lifecycle state the fired transitions
leave the entity in, and report a path that fires a transition from a state it cannot
be in. It is the model-time form of shortfall 4, in the same family as X13's static
checks of DMN tables. Its limits need stating in the finding: a channel-started process
receives an entity whose state the path does not determine, and a path through a
boundary event changes state by the error transition.

**H5. A tool surface for agents, derived from the model.** An MCP server over a running
application: one tool per operation, its input schema from `seam:acceptsShape`, its
description from the model's labels, and the list of tools offered for an entity taken
from H1, so it changes as the entity moves. Calls go through the runtime, so the guard
and the policies that refuse a person refuse an agent. This is the post's proposal
applied to a generated application, and the largest item. It wants an ADR first, on
what an agent's identity is in ODRL terms and on whether the server is generated per
application or is one generic server reading the model, as the worker is.

Shortfall 5 gets no row. Per-state types for handlers would be a change to the stub
generator and to how status is carried, and H4 removes most of the reason: if the model
is checked, a handler cannot be reached in the wrong state. Noted on H4.

## What not to take

- **The vocabulary of the post.** No class or predicate named for a functor or a
  coalgebra. The post describes a structure the graph already has in three notations;
  principle 4 says vocabulary is earned by a question or a generated line, and H1 to H5
  need none.
- **Types as the mechanism.** The post's examples put the rules in a type system so that
  a compiler rejects the wrong call. Here the rules are data, so that they can be
  queried, drawn and edited, and the checks are shapes and `seams check`. H4 is how the
  project gets the same early rejection without moving the rules into code.
- **Narrowing the tools of the agents that work on this repository.** The post is about
  agent harnesses in general. This note is about applications built from a model. How
  coding agents are constrained while changing the model or the generators is a
  different question, closer to R4 and the profiles of
  [ADR-0018](../adr/0018-domain-profiles.md).

## Open questions

1. **Is the state a product or a single thing?** Lifecycle state, process position and
   identity are three sources. H1 has to say what happens when they disagree: a
   transition the lifecycle allows but that no open task fires is not on the menu, and
   the note assumes the menu is the intersection.
2. **Observations and operations.** The post's second image separates queries, which
   only observe, from transitions. The model has no such mark on an operation; a `GET`
   is the nearest thing. Whether H2 lists reads as well as writes depends on it.
3. **Does a shorter tool list help?** The post asserts it. H5 could measure it, with the
   derived scenarios as the tasks and the full operation list as the control. Until
   then it is a reason to build H1 to H4, which stand without it, before H5.

## Sources

- 工业聚, post of 2026-11-10:
  https://x.com/guyingjie129/status/2119973431819309300 (three images and a video; the
  images are described above).
- duve, post of 2026-11-09, quoted by it: "write your agent harness as a coalgebra on a
  polynomial functor".
- This repository: `seams_runtime/lifecycle.py`, `seams_runtime/README.md` (the worker's
  rules, `user_tasks`, `GET /tasks`), `seams_gen/README.md` (the `seam:visibleWhen`
  guard, the acceptance tests), `seams_gen/fastapi.py` (the context `Link` header),
  `ontology/shapes/seam-shapes.ttl` (`seamsh:VisibleWhenGuardShape`),
  `docs/queries/what-moves-state.rq`, `packages/seams/src/seams/graph.py`
  (`transitions_from`), tutorial [chapter 6](../tutorials/expenses/06-lifecycle.md),
  [ADR-0007](../adr/0007-execution-strategy.md), [ADR-0024](../adr/0024-json-ld-context.md)
  and principles 1, 2, 4 and 5.
