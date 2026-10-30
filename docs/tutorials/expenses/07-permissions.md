# 7. People and permissions

At the end of this chapter the app knows who may do what. Employees submit expenses,
managers approve ordinary ones, finance approves the large ones and pays every approved
expense. Someone without the right role gets a 403 that changes nothing, and someone with
no identity at all gets a 401. An approved expense is no longer finished: it waits for
finance to record a payment, and then it ends `paid`.

You declare three roles, write four policies and attach each one to the thing it governs.
Then you add a payment form and a `pay_expense` task to the process. Finally you ask the
viewer the compliance question the tutorial started with: which screens can each role use
that eventually write a payment?

## One more prefix

Policies are written in ODRL, the W3C policy vocabulary. Add its prefix after the others:

```trig
@prefix odrl:   <http://www.w3.org/ns/odrl/2/> .
```

## The roles

A role is an `odrl:Party`. Add the three to the seams graph:

```trig
    :employee a odrl:Party ; rdfs:label "Employee" .
    :manager a odrl:Party ; rdfs:label "Manager" .
    :finance a odrl:Party ; rdfs:label "Finance" .
```

The model does not say who holds a role. That is the job of whatever signs people in. In
production a fronting auth proxy sets `X-Forwarded-User` to the person and
`X-Forwarded-Groups` to their comma-separated roles. The runtime admits an identity when
its id or one of its roles is the local name of the policy's assignee, so `finance` in
`X-Forwarded-Groups` matches `:finance`.

## The policies

Each policy has one permission. Its `odrl:target` is what it governs, its `odrl:action` is
`odrl:use` and its `odrl:assignee` is the role that may use it. The first one governs the
submit operation:

```trig
    :employee_submit_policy a odrl:Policy ; rdfs:label "Employees may submit expenses" ;
        odrl:permission [ a odrl:Permission ;
                          odrl:target :submit_expense_op ;
                          odrl:action odrl:use ;
                          odrl:assignee :employee ] .
```

The other three govern user tasks. ADR-0009 lets a policy target a BPMN user task
directly, so the policy follows the task wherever its form is shown:

```trig
    :manager_approval_policy a odrl:Policy ; rdfs:label "Managers may approve expenses" ;
        odrl:permission [ a odrl:Permission ;
                          odrl:target <https://example.org/expenses/approval_bpmn#approve_expense> ;
                          odrl:action odrl:use ;
                          odrl:assignee :manager ] .
    :finance_approval_policy a odrl:Policy ; rdfs:label "Finance may approve large expenses" ;
        odrl:permission [ a odrl:Permission ;
                          odrl:target <https://example.org/expenses/approval_bpmn#finance_approve_expense> ;
                          odrl:action odrl:use ;
                          odrl:assignee :finance ] .
    :finance_payment_policy a odrl:Policy ; rdfs:label "Finance may pay expenses" ;
        odrl:permission [ a odrl:Permission ;
                          odrl:target <https://example.org/expenses/approval_bpmn#pay_expense> ;
                          odrl:action odrl:use ;
                          odrl:assignee :finance ] .
```

A target alone does not switch a policy on. `seam:governedBy` attaches it, and that is
the triple the runtime and the generators look for:

```trig
    :submit_expense_op seam:governedBy :employee_submit_policy .
    <https://example.org/expenses/approval_bpmn#approve_expense> seam:governedBy :manager_approval_policy .
    <https://example.org/expenses/approval_bpmn#finance_approve_expense> seam:governedBy :finance_approval_policy .
    <https://example.org/expenses/approval_bpmn#pay_expense> seam:governedBy :finance_payment_policy .
```

Why govern the tasks and not the lifecycle transitions? A transition is not something a
person calls. It happens when a task fires it, and chapter 6 already ties every transition
to exactly one task. Guarding the task covers the transition it fires. It also refuses
the person before anything runs: the runtime checks the policy when someone lists or
completes the task, so the wrong person never sees the task in their inbox, and their
completion is refused before the form data reaches the process. A policy on
`:t_approve` would only be checked once the process was already moving.

The read operations (the list, the details, the awaiting-approval block) have no policy.
Anyone the proxy lets through may read.

## Paying an expense

Finance needs somewhere to record a payment. Add a `PaymentShape` to the data graph, with
the payment reference and the day it was paid:

```trig
    :PaymentShape a sh:NodeShape ; rdfs:label "Payment" ;
        sh:property [ sh:path :reference ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:maxLength 100 ; sh:order 0 ] ;
        sh:property [ sh:path :paid_on ; sh:datatype xsd:date ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:order 1 ] ;
        seam:inModel :expense_data .
```

The approvals page gets a form for it. Add `:payment_form` to the page's `ifml:contains`:

```trig
            :awaiting_approval , :payment_form ;
```

```trig
    :payment_form a ifml:Form ; rdfs:label "Record Payment" ;
        ifml:order 4 ;
        ifml:hasEvent :submit_payment ;
        ifml:hasParameter :reference_input , :paid_on_input ;
        seam:inModel :expense_ifml .
    :reference_input a ifml:Parameter ; rdfs:label "reference" ;
        ifml:boundTo :reference ;
        seam:inModel :expense_ifml .
    :paid_on_input a ifml:Parameter ; rdfs:label "paid_on" ;
        ifml:boundTo :paid_on ;
        seam:inModel :expense_ifml .

    :submit_payment a ifml:Event ; rdfs:label "Submit Payment" ;
        ifml:trigger "submit" ;
        seam:inModel :expense_ifml .
```

The form writes the shape, and its event submits to a new operation, `:pay_expense_op`.
Add it to the `seam:exposes` of `:expense_api` and the `seam:consumes` of
`:employee_portal`, as you did for the awaiting-approval operation in chapter 6:

```trig
    :payment_form seam:writes :PaymentShape .
    :submit_payment seam:submitsTo :pay_expense_op .
```

```trig
    :pay_expense_op a hydra:Operation ; rdfs:label "Pay Expense" ;
        hydra:method "POST" ;
        seam:acceptsShape :PaymentShape ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:requestMediaType "application/x-www-form-urlencoded" ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses/{expense}/payment" ;
```

```trig
    :pay_expense_op seam:rendersComponent :expense_details .
```

In the process, `record_approval` no longer ends the process. It leads to a new user task,
`pay_expense`, and that task leads to the end event, now named "Paid":

```xml
<bpmn:serviceTask id="record_approval" name="Record Approval">
  <bpmn:incoming>flow_auto</bpmn:incoming>
  <bpmn:incoming>flow_approved</bpmn:incoming>
  <bpmn:outgoing>flow_to_pay</bpmn:outgoing>
</bpmn:serviceTask>

<bpmn:userTask id="pay_expense" name="Pay Expense">
  <bpmn:incoming>flow_to_pay</bpmn:incoming>
  <bpmn:outgoing>flow_to_approved_end</bpmn:outgoing>
</bpmn:userTask>
```

```xml
<bpmn:sequenceFlow id="flow_to_pay" sourceRef="record_approval" targetRef="pay_expense" />
<bpmn:sequenceFlow id="flow_to_approved_end" sourceRef="pay_expense" targetRef="approved_end" />
```

The full file is
[`examples/expenses/chapter-07/approval.bpmn`](../../../examples/expenses/chapter-07/approval.bpmn),
with a diagram shape for the new task. The end event keeps its id, `approved_end`, so
nothing else that names it changes.

Declare the task in the process graph:

```trig
    <https://example.org/expenses/approval_bpmn#pay_expense> a proc:UserTask ;
        rdfs:label "Pay Expense" ;
        seam:inModel :approval_bpmn .
```

Then say what it does in the seams graph. Finance sees the expense, completes the task on
`:payment_form`, the task stores the payment, and it fires `:t_pay`, the transition
chapter 6 left unused:

```trig
    <https://example.org/expenses/approval_bpmn#pay_expense>
        seam:reads :ExpenseShape ;
        seam:completedOn :payment_form ;
        seam:writes :PaymentShape ;
        seam:fires :t_pay .
```

Remove the comment above `:t_pay` in the lifecycle graph that said nothing fires it yet.
Something does now: every edge of the statechart leads back to a task.

## Generate the app

Run the generators the chapter 7 checkpoint's `seams.toml` names:

```sh
seams generate --project examples/expenses/chapter-07
```

`expense_api.py` gains the payment handler, `pay_expense`, and the templates gain its
form, `payment_form.html`. The policies show up in two places. The submit route now
carries a dependency, because `:submit_expense_op` is governed:

```
dependencies=[Depends(runtime.policy(":employee_submit_policy"))],
```

Each completion route already took its identity from `runtime.task_policy(...)`. That
dependency now finds a policy on the task and checks it. Nothing in the generated code
names a role. Who holds a role is decided at request time, from the headers.

## Run it

Start the host on the chapter 7 files. Leave `SEAMS_DEV_USER` unset this time, so every
identity comes from the headers, as it would behind a proxy:

```sh
SEAMS_MODEL=examples/expenses/chapter-07/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-07/generated/templates \
SEAMS_DB=/tmp/expenses-07.sqlite \
python -m seams_runtime.host --routes examples/expenses/chapter-07/generated/expense_api.py --port 8001
```

Alice, an employee, submits the hotel:

```sh
curl -X POST http://localhost:8001/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02 \
  -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: employee"
```

Bob, a manager, tries to submit one too:

```sh
curl -i -X POST http://localhost:8001/expenses/dinner -d "description=Dinner" -d amount=80.00 -d date=2026-10-02 \
  -H "X-Forwarded-User: bob" -H "X-Forwarded-Groups: manager"
```

He gets a 403. The body is a `PolicyDenied` naming `:employee_submit_policy`, and its
reason names bob and his roles. The refusal came before the process started, so there is
no dinner expense and no instance for it. Drop both headers and you get a 401 instead.

Bob's inbox shows the hotel's approval task. Alice's and finance's do not, because the
task's policy is checked when the inbox is listed:

```sh
curl http://localhost:8001/tasks -H "Accept: application/json" \
  -H "X-Forwarded-User: bob" -H "X-Forwarded-Groups: manager"
```

Bob approves it:

```sh
curl -X POST http://localhost:8001/expenses/hotel/approval -d decision=approved \
  -H "X-Forwarded-User: bob" -H "X-Forwarded-Groups: manager"
```

The hotel is now `approved`, and the instance waits on `pay_expense`. Carol, in finance,
sees it in her inbox and pays it:

```sh
curl -X POST http://localhost:8001/expenses/hotel/payment -d reference=PAY-0042 -d paid_on=2026-10-05 \
  -H "X-Forwarded-User: carol" -H "X-Forwarded-Groups: finance"
```

The response is the hotel's details. `curl http://localhost:8001/expenses/hotel` shows the
status `paid`. Bob trying the same payment gets a 403 naming `:finance_payment_policy`,
and a payment with no reference or a date like `yesterday` is a 422 that leaves the task
waiting. A small amount, say 42.50, is approved automatically and goes straight to
Carol's inbox. A large one, over the finance threshold, waits on
`/expenses/{expense}/finance-approval`, which only finance may complete.

To click through it in a browser, which sends no proxy headers, give the host a static
identity with its roles instead:

```sh
SEAMS_MODEL=examples/expenses/chapter-07/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-07/generated/templates \
SEAMS_DB=/tmp/expenses-07.sqlite \
SEAMS_DEV_USER=alice SEAMS_DEV_ROLES=employee,manager,finance \
python -m seams_runtime.host --routes examples/expenses/chapter-07/generated/expense_api.py --port 8001
```

Every request is then alice with the roles in `SEAMS_DEV_ROLES` (comma-separated), and the
headers are ignored. Restart with fewer roles to see what each role's `/tasks` looks
like. `SEAMS_DEV_ROLES` does nothing without `SEAMS_DEV_USER`, so a host started without
either still refuses a request with no headers.

## Ask the compliance question

The policies are in the model, so the viewer can answer questions about them. Start it on
the checkpoint:

```sh
SEAMS_MODEL=examples/expenses/chapter-07/expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

Open **Payment** (`PaymentShape`) and press **Which screens can each role use to write
this shape?** under Questions. The answer is one row:

| Role | Screen | Event | Writer |
|---|---|---|---|
| Employee | Expenses Page | Submit Expense | Pay Expense |

An employee's Submit Expense, on the Expenses page, starts the approval process, and that
process eventually reaches `pay_expense`, which writes the payment. Finance's payment form
does not appear, because it completes a task rather than starting the process. The query
follows what a screen sets in motion, which is the question an access review asks. It is
`docs/queries/screens-by-role-writing-shape.rq`, listed on the
[query reference](/reference/queries).

CI checks every step of this chapter: the roles, the refusals, the payment and the
viewer's answer (`tests/test_expense_roles.py`), and the generated app on every path
(`tests/test_expense_process_app.py`).

## Checkpoint

Your files should now match
[`examples/expenses/chapter-07/expenses.trig`](../../../examples/expenses/chapter-07/expenses.trig)
and
[`examples/expenses/chapter-07/approval.bpmn`](../../../examples/expenses/chapter-07/approval.bpmn)
(`approval.dmn` is unchanged), and the generated code
[`examples/expenses/chapter-07/generated/`](../../../examples/expenses/chapter-07/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-06/expenses.trig examples/expenses/chapter-07/expenses.trig
```

[Chapter 8, Growing up](./08-growing-up), makes payout asynchronous. A payout process
starts on its own when an expense is paid, finance gets a console, and the whole system
runs with `docker compose up`.
