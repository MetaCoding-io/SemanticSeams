# 4. The process

At the end of this chapter submitting an expense starts a BPMN process instead of
storing the expense directly. The process stores the expense, then waits for a person to
approve it. You see the process drawn in the viewer, submit an expense, find the waiting
approval in the task inbox at `/tasks`, approve it there, and watch the instance finish.

There are no roles yet: anyone who is signed in may approve. Chapter 7 restricts the
task to managers. The routing by amount comes in chapter 5 and the expense lifecycle in
chapter 6.

## One more prefix

The process layer has its own vocabulary. Add it after `comm:`:

```trig
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/expenses/> .
```

## The process

The process itself is a BPMN file next to the model, `approval.bpmn`. It has a start
event, a service task that stores the expense, a user task where someone approves it,
and an end event. Save this beside your `expenses.trig`:

```xml
<bpmn:process id="approval_process" name="Expense Approval" isExecutable="true">
  <bpmn:startEvent id="start" name="Expense Submitted">
    <bpmn:outgoing>flow_to_persist</bpmn:outgoing>
  </bpmn:startEvent>

  <bpmn:serviceTask id="persist_expense" name="Persist Expense">
    <bpmn:incoming>flow_to_persist</bpmn:incoming>
    <bpmn:outgoing>flow_to_approve</bpmn:outgoing>
  </bpmn:serviceTask>

  <bpmn:userTask id="approve_expense" name="Approve Expense">
    <bpmn:incoming>flow_to_approve</bpmn:incoming>
    <bpmn:outgoing>flow_to_end</bpmn:outgoing>
  </bpmn:userTask>

  <bpmn:endEvent id="end" name="Decided">
    <bpmn:incoming>flow_to_end</bpmn:incoming>
  </bpmn:endEvent>

  <bpmn:sequenceFlow id="flow_to_persist" sourceRef="start" targetRef="persist_expense" />
  <bpmn:sequenceFlow id="flow_to_approve" sourceRef="persist_expense" targetRef="approve_expense" />
  <bpmn:sequenceFlow id="flow_to_end" sourceRef="approve_expense" targetRef="end" />
</bpmn:process>
```

That is the process part. The full file,
[`examples/expenses/chapter-04/approval.bpmn`](../../../examples/expenses/chapter-04/approval.bpmn),
wraps it in `bpmn:definitions` and adds the diagram interchange (`bpmndi:`) section with
a position for every shape, so the viewer can draw it. Any BPMN editor, such as the
[bpmn.io demo](https://demo.bpmn.io), writes both parts for you.

The model gets a graph for the process too. It names the process and its two tasks, so
the seams can point at them. Each task's IRI is its BPMN element id under the model's
namespace, `approval_bpmn#`:

```trig
<urn:seams:graph:model:approval_bpmn> {

    :approval_bpmn a seam:Model ; rdfs:label "Expense Approval (BPMN)" .

    # The process and its two tasks. Their IRIs are the BPMN element ids in
    # approval.bpmn, under the model's namespace.
    :approval_process a proc:Process ; rdfs:label "Expense Approval" ;
        seam:inModel :approval_bpmn .

    <https://example.org/expenses/approval_bpmn#persist_expense> a proc:ServiceTask ;
        rdfs:label "Persist Expense" ;
        seam:inModel :approval_bpmn .

    <https://example.org/expenses/approval_bpmn#approve_expense> a proc:UserTask ;
        rdfs:label "Approve Expense" ;
        seam:inModel :approval_bpmn .
}
```

In the seams graph, give it its notation and point the viewer at the file with
`seam:renderPayload`:

```trig
    :approval_bpmn seam:notation seam:BPMN ;
        seam:renderPayload <approval.bpmn> .
```

## What the approver enters

The approval is data like the expense, so it gets a shape in the data graph: a decision
that must be one of two values, and an optional comment.

```trig
    # What the approver enters: a decision from the list, and an optional comment.
    :ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ;
        sh:property [ sh:path :decision ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:in ( "approved" "rejected" ) ; sh:order 0 ] ;
        sh:property [ sh:path :comment ; sh:datatype xsd:string ; sh:maxCount 1 ;
                      sh:maxLength 500 ; sh:order 1 ] ;
        seam:inModel :expense_data .
```

`sh:in` becomes a drop-down in the generated form, and anything else is refused with a
422.

## The correlation key

A process instance needs a name, so that when the approval arrives the runtime knows
which waiting instance it belongs to. That name is the correlation key. Here it is the
expense, as a new parameter of the form:

```trig
        ifml:hasParameter :expense , :description_input , :amount_input , :date_input ;
        seam:inModel :expense_ifml .

    # The correlation key: its label is the {expense} variable of the submit
    # and approval paths, and it names the process instance.
    :expense a ifml:Parameter ; rdfs:label "expense" ;
        seam:inModel :expense_ifml .
```

The key travels in the URL. The submit operation's path gains an `{expense}` variable,
mapped to the expense's `:id`:

```trig
    :submit_expense_op a hydra:Operation ; rdfs:label "Submit Expense" ;
        hydra:method "POST" ;
        seam:acceptsShape :ExpenseShape ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:requestMediaType "application/x-www-form-urlencoded" ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses/{expense}" ;
                    hydra:mapping [ a hydra:IriTemplateMapping ;
                                    hydra:variable "expense" ;
                                    hydra:property :id ] ] .
```

Because the path now carries the identifier, the form body no longer has to. Chapter 3's
`:id` property was required; make it optional by deleting its `sh:minCount 1`:

```trig
        sh:property [ sh:path :id ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
```

These three edits are the only chapter 3 triples this chapter changes.

## The approvals screen

The user task needs a form for the approver. ADR-0009's rule is that the task is
completed on the form you name with `seam:completedOn`, and the screen is whichever page
contains that form. Add the page to the interaction graph, and add `:approvals_page` to
the `ifml:contains` of `:expense_ifml`:

```trig
    # The approver's page. The approval task is completed here, because the
    # page ifml:contains :approve_form (ADR-0009).
    :approvals_page a ifml:ViewContainer ; rdfs:label "Approvals" ;
        ifml:path "/approvals" ;
        ifml:title "Approvals"@en ;
        ifml:contains :expense_details , :approve_form ;
        seam:inModel :expense_ifml .

    # One expense, named by the correlation key.
    :expense_details a ifml:Details ; rdfs:label "Expense" ;
        ifml:order 0 ;
        ifml:hasParameter :approved_expense ;
        seam:inModel :expense_ifml .
    :approved_expense a ifml:Parameter ; rdfs:label "expense" ;
        seam:inModel :expense_ifml .

    :approve_form a ifml:Form ; rdfs:label "Approve Expense" ;
        ifml:order 1 ;
        ifml:hasEvent :submit_approval ;
        ifml:hasParameter :decision_input , :comment_input ;
        seam:inModel :expense_ifml .
```

The form's parameters are bound to `:decision` and `:comment`, its event is
`:submit_approval`, and a navigation flow replaces the details with the decided expense.
The checkpoint has those triples in full.

The page also needs two operations: `:approve_expense_op`, a POST to
`/expenses/{expense}/approval` that accepts an `:ApprovalShape`, and
`:expense_details_op`, a GET of `/expenses/{expense}`. They follow the same pattern as
the submit operation; add both to the `seam:exposes` of `:expense_api` and the
`seam:consumes` of `:employee_portal`.

## The seams

Now the links that make it run. Submitting the expense form starts the process, the API
container executes it, and each instance is keyed by `:expense`:

```trig
    # UI to process: submitting the form starts the approval process, which
    # the API container runs. Each instance is keyed by :expense.
    :submit_expense seam:triggers :approval_process .
    :approval_process seam:detailedBy :approval_bpmn ;
        proc:correlationKey :expense .
```

```trig
    :expense_api seam:exposes :submit_expense_op , :list_expenses_op , :approve_expense_op , :expense_details_op ;
        seam:executes :approval_process .
```

The service task calls the submit operation and stores what it accepted. The user task
shows the expense, waits for someone to submit `:approve_form`, and stores the approval:

```trig
    # Process to API and data: the service task calls the submit operation
    # and stores the expense.
    <https://example.org/expenses/approval_bpmn#persist_expense>
        seam:invokes :submit_expense_op ;
        seam:writes :ExpenseShape .

    # The human task (ADR-0009): it shows the expense, waits for someone to
    # submit :approve_form, and stores what they entered as an ApprovalShape.
    <https://example.org/expenses/approval_bpmn#approve_expense>
        seam:reads :ExpenseShape ;
        seam:completedOn :approve_form ;
        seam:writes :ApprovalShape .
```

The approval form's event submits to the completion operation. It has no
`seam:triggers`, because the process is already running and waiting for it:

```trig
    :expense_details seam:reads :ExpenseShape .
    :approve_form seam:writes :ApprovalShape .
    :submit_approval seam:submitsTo :approve_expense_op .
```

Restart the viewer on your file. The badge is green, and the architecture view now has a
way into the process: **Expense API** has a `seam:executes` seam to Expense Approval.
Follow it and the viewer opens the process, which `seam:detailedBy` the BPMN model, drawn
from `approval.bpmn`.

## Generate the app

Run the generators the chapter 4 checkpoint's `seams.toml` names:

```sh
seams generate --project examples/expenses/chapter-04
```

Compare `submit_expense` in `expense_api.py` with chapter 3's. It no longer calls
`runtime.write`. It validates the form against `:ExpenseShape` and calls
`runtime.start_process(":approval_process", ..., correlation_key=expense)`; the service
task does the storing. There is a new route, `approve_expense`, the completion route of
the user task. It calls `runtime.complete_task`, which checks there is an open task for
that expense, validates the form against `:ApprovalShape` and lets the process continue.
Neither route branches on anything: the BPMN decides what happens next.

The `htmx` generator also writes `approve_form.html`, the form the task inbox renders for
each open approval, with a drop-down for the decision from `sh:in`.

## Run it

Start the host as in chapter 3, on the chapter 4 files. The inbox needs to know who you
are. Behind a proxy that comes from the `X-Forwarded-User` header; for a local run,
`SEAMS_DEV_USER` makes every request come from one person:

```sh
SEAMS_MODEL=examples/expenses/chapter-04/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-04/generated/templates \
SEAMS_DB=/tmp/expenses-04.sqlite \
SEAMS_DEV_USER=alice \
python -m seams_runtime.host --routes examples/expenses/chapter-04/generated/expense_api.py --port 8001
```

Submit an expense with its key in the path. Nothing on the page supplies the key of an
expense that does not exist yet, so the generated form makes one up: on every submit the
browser puts a fresh random key in place of `{expense}`. To get a key you can read, use
curl for this step:

```sh
curl -X POST http://localhost:8001/expenses/e1 -d "description=Train to Leeds" -d amount=42.50 -d date=2026-10-01
```

The answer is the new list item, as in chapter 3, but this time a process instance named
`e1` has started. Its service task stored the expense, so it is in the list at
<http://localhost:8001>, and the instance is now waiting on the user task.

Open <http://localhost:8001/tasks>. This is the task inbox: every open task you may
complete, each with its form. There is one, **Approve Expense**, showing the expense's
description, amount and date, and a decision drop-down. Choose **approved**, add a
comment if you like, and submit. The card is replaced with the decided expense, the
process runs on to its end event, and reloading `/tasks` shows **No open tasks.**

The same approval with a decision that is not in the list is refused, and the task stays
open:

```sh
curl -i -X POST http://localhost:8001/expenses/e1/approval -d decision=maybe
```

On a fresh expense the answer is `422` with a `ContractViolation` naming `decision`. On
`e1`, which you have approved already, it is `409 TaskNotOpen`: a task completes once.

Without `SEAMS_DEV_USER` or the header, `/tasks` answers `401`. Who may approve is a
policy, and that is chapter 7.

## Checkpoint

Your files should now match
[`examples/expenses/chapter-04/expenses.trig`](../../../examples/expenses/chapter-04/expenses.trig)
and
[`examples/expenses/chapter-04/approval.bpmn`](../../../examples/expenses/chapter-04/approval.bpmn),
and the generated code
[`examples/expenses/chapter-04/generated/`](../../../examples/expenses/chapter-04/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-03/expenses.trig examples/expenses/chapter-04/expenses.trig
```

Next, [chapter 5](./05-rules) lets a decision table choose who approves, by amount.
