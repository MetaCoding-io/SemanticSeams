# 6. The lifecycle

At the end of this chapter an expense has a lifecycle. It starts as a draft, becomes
submitted when the process stores it, and ends approved or rejected. Paid comes in
chapter 7, when finance records a payment by hand, and chapter 8 makes payout
asynchronous. The process can only move an expense along a transition the lifecycle allows,
and the runtime refuses any other move before the task runs, so a refused move writes
nothing. The approvals page also gains a block that is visible only while an expense is
waiting for a decision.

You write a statechart, attach it to `ExpenseShape`, say which process task fires which
transition, and make the process record the person's decision. Then you guard a component
with the state it should appear in, and break the process on purpose to watch the runtime
refuse a transition.

## One more prefix

Statecharts have their own vocabulary. Add it after `proc:`:

```trig
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix state:  <https://w3id.org/seams/state#> .
```

## The statechart

The lifecycle is a model of its own, so it gets its own graph. It names the states, the
initial state and the transitions. Each transition goes from one state to another:

```trig
<urn:seams:graph:model:expense_lifecycle> {

    # Every expense starts as a draft. The runtime compares states by their
    # rdfs:label, so the labels are the values :status and the
    # seam:visibleWhen guard use.
    :expense_lifecycle a state:StateMachine , seam:Model ;
        rdfs:label "Expense Lifecycle" ;
        state:initial :s_draft ;
        state:hasState :s_draft , :s_submitted , :s_approved , :s_rejected , :s_paid ;
        state:final :s_rejected , :s_paid ;
        state:hasTransition :t_submit , :t_approve , :t_reject , :t_pay .

    :s_draft     a state:State ; rdfs:label "draft"     ; seam:inModel :expense_lifecycle .
    :s_submitted a state:State ; rdfs:label "submitted" ; seam:inModel :expense_lifecycle .
    :s_approved  a state:State ; rdfs:label "approved"  ; seam:inModel :expense_lifecycle .
    :s_rejected  a state:State ; rdfs:label "rejected"  ; seam:inModel :expense_lifecycle .
    :s_paid      a state:State ; rdfs:label "paid"      ; seam:inModel :expense_lifecycle .

    :t_submit  a state:Transition ; state:from :s_draft     ; state:to :s_submitted ; state:trigger "submit"  ; seam:inModel :expense_lifecycle .
    :t_approve a state:Transition ; state:from :s_submitted ; state:to :s_approved  ; state:trigger "approve" ; seam:inModel :expense_lifecycle .
    :t_reject  a state:Transition ; state:from :s_submitted ; state:to :s_rejected  ; state:trigger "reject"  ; seam:inModel :expense_lifecycle .
    # No task fires :t_pay yet: chapter 8 pays approved expenses.
    :t_pay     a state:Transition ; state:from :s_approved  ; state:to :s_paid      ; state:trigger "pay"     ; seam:inModel :expense_lifecycle .
}
```

The labels matter. The runtime stores an expense's state as the label of that state, and
the guard you write later compares labels. Write them in lower case, as above.

In the seams graph, give the model its notation and attach it to the shape:

```trig
    :expense_lifecycle seam:notation seam:Statechart .
```

```trig
    :ExpenseShape seam:lifecycle :expense_lifecycle .
```

The expense now has a state, so the shape can say where it is kept. Add a `:status`
property whose allowed values are the state labels. Forms do not ask for it, because the
runtime sets it:

```trig
        # Set by the runtime, never entered: the rdfs:label of the expense's
        # current state in :expense_lifecycle.
        sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 3 ;
                      sh:in ( "draft" "submitted" "approved" "rejected" "paid" ) ] ;
```

Restart the viewer on your file and open **Expense Lifecycle** from the shape's
`seam:lifecycle` seam. The statechart view draws the five states and the four transitions
between them.

## Which task fires which transition

A transition happens when a process task fires it. `persist_expense` stores the expense,
so it also moves the expense from draft to submitted:

```trig
    <https://example.org/expenses/approval_bpmn#persist_expense>
        seam:invokes :submit_expense_op ;
        seam:writes :ExpenseShape ;
        seam:fires :t_submit .
```

Approving or rejecting needs a task too. In chapter 5 both approval tasks went straight to
the end, and the person's decision went nowhere. Now each approval task goes to a gateway
on `decision`. The runtime merges the completed form into the task data, so the `decision`
the person picked is a process variable the gateway can read:

```xml
<bpmn:exclusiveGateway id="decision_gateway" name="Decision?">
  <bpmn:incoming>flow_manager_decided</bpmn:incoming>
  <bpmn:incoming>flow_finance_decided</bpmn:incoming>
  <bpmn:outgoing>flow_approved</bpmn:outgoing>
  <bpmn:outgoing>flow_rejected</bpmn:outgoing>
</bpmn:exclusiveGateway>
```

```xml
<bpmn:sequenceFlow id="flow_approved" name="approved" sourceRef="decision_gateway" targetRef="record_approval">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">decision == "approved"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
<bpmn:sequenceFlow id="flow_rejected" name="rejected" sourceRef="decision_gateway" targetRef="record_rejection">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">decision == "rejected"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

The two flows end in two new service tasks, `record_approval` and `record_rejection`.
Chapter 5's `auto` flow ended the process; now it goes to `record_approval` too, because an
expense approved automatically is still approved:

```xml
<bpmn:sequenceFlow id="flow_auto" name="auto" sourceRef="route_gateway" targetRef="record_approval">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">route == "auto"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

The full file is
[`examples/expenses/chapter-06/approval.bpmn`](../../../examples/expenses/chapter-06/approval.bpmn).
It ends in two end events, `approved_end` and `rejected_end`, and the diagram has a shape
for each new element.

The new tasks only change the expense's state. They call no operation and write no new
entity: when a task fires a transition, the runtime stores the new state on every expense
the instance has written.

```trig
    # They do nothing but move the expense to its decided state.
    <https://example.org/expenses/approval_bpmn#record_approval> a proc:ServiceTask ;
        rdfs:label "Record Approval" ;
        seam:inModel :approval_bpmn .

    <https://example.org/expenses/approval_bpmn#record_rejection> a proc:ServiceTask ;
        rdfs:label "Record Rejection" ;
        seam:inModel :approval_bpmn .
```

```trig
    # Process to lifecycle: the tasks that move the expense. The runtime
    # checks each transition against the expense's current state before the
    # task runs, and stores the new state after it.
    <https://example.org/expenses/approval_bpmn#record_approval> seam:fires :t_approve .
    <https://example.org/expenses/approval_bpmn#record_rejection> seam:fires :t_reject .
```

In the viewer, open `record_approval` and follow its `seam:fires` seam to `:t_approve` in
the statechart. Each edge of the statechart now leads back to the task that fires it,
except `:t_pay`, which nothing fires yet: chapter 7 adds a manual payment task that
fires it, and chapter 8 makes payout asynchronous.

## A block that shows only while the expense waits

`seam:visibleWhen` makes a component conditional on a state. Add a new details component to
the approvals page, labelled "Awaiting approval":

```trig
        ifml:contains :expense_details , :approve_form , :finance_approve_form ,
            :awaiting_approval ;
```

```trig
    # The same expense, shown only while it waits for a decision: its
    # seam:visibleWhen guard is in the seams graph.
    :awaiting_approval a ifml:Details ; rdfs:label "Awaiting approval" ;
        ifml:order 3 ;
        ifml:hasParameter :awaiting_expense ;
        seam:inModel :expense_ifml .
    :awaiting_expense a ifml:Parameter ; rdfs:label "expense" ;
        seam:inModel :expense_ifml .
```

The guard goes in the seams graph. The component must read a shape that has a lifecycle,
and the guard state must be a state of that lifecycle. Otherwise the generator stops with
an error naming the component:

```trig
    # Data to lifecycle, and the guard: the block reads the expense and
    # renders only while its lifecycle state is "submitted".
    :ExpenseShape seam:lifecycle :expense_lifecycle .
    :awaiting_approval seam:reads :ExpenseShape ;
        seam:visibleWhen :s_submitted .
```

A new operation renders it. Add `:awaiting_approval_op` to the `seam:exposes` of
`:expense_api` and the `seam:consumes` of `:employee_portal`:

```trig
    :awaiting_approval_op seam:rendersComponent :awaiting_approval .
```

```trig
    :awaiting_approval_op a hydra:Operation ; rdfs:label "Awaiting Approval" ;
        hydra:method "GET" ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses/{expense}/awaiting-approval" ;
                    hydra:mapping [ a hydra:IriTemplateMapping ;
                                    hydra:variable "expense" ;
                                    hydra:property :id ] ] .
```

Why a new component, and not a guard on `:expense_details`? The approval routes render
`:expense_details` as their response, and the runtime finishes the process in the
background after the task is completed. A guard there would hide the response whenever the
process won the race. A separate block keeps the approval response unconditional.

## Generate the app

Run the generators the chapter 6 checkpoint's `seams.toml` names:

```sh
seams generate --project examples/expenses/chapter-06
```

`expense_api.py` gains one handler, `awaiting_approval`, which queries the expense and
renders its partial. Nothing in the module mentions states or transitions. The new
template, `awaiting_approval.html`, is the only generated file with a condition in it:

```
{% if expense_state == "submitted" %}
<section id="awaiting_approval" aria-label="Awaiting approval"
         data-expense="{{ expense }}">
  ...
</section>
{% endif %}
```

The variable name comes from the shape: `ExpenseShape` lowercased without `Shape`, plus
`_state`. The runtime binds it to the status of the expense it renders, or to the initial
state, `draft`, when there is none. The other partials that list expenses also gain a
`status` field, because `ExpenseShape` now has one.

## Run it

Start the host on the chapter 6 files:

```sh
SEAMS_MODEL=examples/expenses/chapter-06/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-06/generated/templates \
SEAMS_DB=/tmp/expenses-06.sqlite \
SEAMS_DEV_USER=alice \
python -m seams_runtime.host --routes examples/expenses/chapter-06/generated/expense_api.py --port 8001
```

Submit the same three expenses as in chapter 5:

```sh
curl -X POST http://localhost:8001/expenses/taxi -d "description=Taxi" -d amount=42.50 -d date=2026-10-01
curl -X POST http://localhost:8001/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02
curl -X POST http://localhost:8001/expenses/laptop -d "description=Laptop" -d amount=5000.00 -d date=2026-10-03
```

The list at <http://localhost:8001> now shows each expense's status. The taxi went
through `record_approval` and is `approved`. The hotel and the laptop wait for a person
and are `submitted`. Ask for the hotel's awaiting-approval block:

```sh
curl http://localhost:8001/expenses/hotel/awaiting-approval
```

It returns the hotel in a `<section id="awaiting_approval">`. Ask for the taxi's and you get
nothing back but whitespace, because the taxi is not submitted.

Open <http://localhost:8001/tasks>, approve the hotel and reject the laptop. Ask for the
hotel's block again: it has gone. `curl http://localhost:8001/expenses/hotel` still shows
the hotel, with the status `approved`, and the laptop's shows `rejected`.

## Provoke a refused transition

The guard is the point of the lifecycle, so break the process on purpose. Make
`record_approval` fire `:t_pay` instead of `:t_approve`, as if someone wired up payment too
early:

```diff
-    <https://example.org/expenses/approval_bpmn#record_approval> seam:fires :t_approve .
+    <https://example.org/expenses/approval_bpmn#record_approval> seam:fires :t_pay .
```

The model hash changes, so run the two generator commands again (the host refuses the old
module otherwise). Restart the host with a fresh `SEAMS_DB` and submit the taxi. Its
instance fails, and the host log names the transition:

```
instance … failed: transition https://example.org/expenses/t_pay not allowed for https://example.org/expenses/ExpenseShape: current state 'submitted', transition requires 'approved'
```

The runtime checked `:t_pay` against the taxi's state before `record_approval` ran, and
`:t_pay` leaves only from `approved`. Nothing was written: `curl
http://localhost:8001/expenses/taxi` still shows the taxi as `submitted`, never `paid` or
`approved`. The error is stored with the failed instance as a `LifecycleViolation`, with
the transition, the current state and the state the transition requires. Approving the
hotel fails the same way, while rejecting it still works, because `record_rejection` fires
`:t_reject`.

Put `:t_approve` back and regenerate, so your files match the checkpoint. CI runs this
experiment on a copy of the checkpoint (`tests/test_expense_lifecycle.py`), and checks
that every path leaves the expense in its decided state
(`tests/test_expense_process_app.py`).

## Checkpoint

Your files should now match
[`examples/expenses/chapter-06/expenses.trig`](../../../examples/expenses/chapter-06/expenses.trig)
and
[`examples/expenses/chapter-06/approval.bpmn`](../../../examples/expenses/chapter-06/approval.bpmn)
(`approval.dmn` is unchanged), and the generated code
[`examples/expenses/chapter-06/generated/`](../../../examples/expenses/chapter-06/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-05/expenses.trig examples/expenses/chapter-06/expenses.trig
```

[Chapter 7](./07-permissions) adds people and permissions: employee, manager and finance
roles, policies that decide who may submit and who may complete which task, and a manual
payment that finally fires `:t_pay`.
