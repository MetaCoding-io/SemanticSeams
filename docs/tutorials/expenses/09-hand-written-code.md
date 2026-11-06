# 9. Hand-written code

At the end of this chapter the manager is told about an expense before the approval task
opens for them. The message comes from a few lines of Python that you write yourself. The
model says where that code lives and what it takes and returns, and `seams generate`
never touches it. When the message cannot be sent, the code raises an error the model
declares, and the process takes the expense to finance instead of failing.

Every service task so far was work the runtime already knew how to do: storing an entity,
asking a decision, firing a transition, publishing on a channel. Some work is not like
that. Here it is composing a notification. Other examples are calling an internal
library, doing a calculation the decision tables cannot express, or formatting a
document. [ADR-0012](/adr/0012-operation-implementation) gives such work a declared home:
an operation says what implements it with `seam:implementedBy`, and one kind of
implementation is a Python function in the app's handlers package.

## Why not an LLM call

The chat app's one service task sends the conversation to an LLM. A notification could
work the same way, but nothing about it needs a model to guess. The recipient is fixed by
the route the decision chose, and the text is the expense's own fields. Plain code gives
the same message for the same expense every time. Tests can check it, and it costs
nothing to run. Use an LLM only for work that needs one. Everything else is a function.

## The Notify Manager task

In `approval.bpmn` the manager path used to go straight from the routing gateway to the
`approve_expense` user task. Put a service task in between:

```xml
<!-- Hand-written code (ADR-0012): the graph says this task seam:invokes
     :notify_manager_op, which a comm:PythonHandler implements. -->
<bpmn:serviceTask id="notify_manager" name="Notify Manager">
  <bpmn:incoming>flow_manager</bpmn:incoming>
  <bpmn:outgoing>flow_to_approve</bpmn:outgoing>
</bpmn:serviceTask>

<bpmn:userTask id="approve_expense" name="Approve Expense">
  <bpmn:incoming>flow_to_approve</bpmn:incoming>
  <bpmn:outgoing>flow_manager_decided</bpmn:outgoing>
</bpmn:userTask>
```

The `manager` flow now targets the new task, and a new flow leads on to the approval:

```xml
<bpmn:sequenceFlow id="flow_manager" name="manager" sourceRef="route_gateway" targetRef="notify_manager">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">route == "manager"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

```xml
<bpmn:sequenceFlow id="flow_to_approve" sourceRef="notify_manager" targetRef="approve_expense" />
```

The auto and finance paths do not pass through it, so only an expense the routing table
sends to the manager is announced. Declare the task in the process graph as chapter 6
declared its service tasks:

```trig
    # Hand-written code: the manager is told before the approval task opens.
    <https://example.org/expenses/approval_bpmn#notify_manager> a proc:ServiceTask ;
        rdfs:label "Notify Manager" ;
        seam:inModel :approval_bpmn .
```

## What the code returns

The handler returns a notification: who it is for and what it says. That is a shape like
any other, in the data graph beside `ExpenseShape`:

```trig
    # The message the notify handler composes for the manager: who it is
    # for and what it says. It is computed, never entered.
    :NotificationShape a sh:NodeShape ; rdfs:label "Notification" ;
        sh:property [ sh:path :recipient ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:order 0 ] ;
        sh:property [ sh:path :message ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:order 1 ] ;
        seam:inModel :expense_data .
```

Its rows live where the others do, so add it to the storage facts of chapter 8:

```trig
    :NotificationShape seam:storedIn :expense_db .
```

## The operation and its implementation

The code sits behind an operation, as the LLM call does in the chat app. The operation
takes the expense and returns a notification:

```trig
    :notify_manager_op a hydra:Operation ; rdfs:label "Notify Manager" ;
        seam:acceptsShape :ExpenseShape ;
        seam:returnsShape :NotificationShape ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses/{expense}/notification" ;
                    hydra:mapping [ a hydra:IriTemplateMapping ;
                                    hydra:variable "expense" ;
                                    hydra:property :id ] ] ;
        seam:implementedBy :notify_manager_impl ;
```

The `;` leaves room for one more fact, which [the error section](#when-the-notification-fails)
adds. `seam:implementedBy` names what serves it. The implementation node's type is its kind,
here `comm:PythonHandler`, and `comm:handler` is the dotted path of the function in the
handlers package:

```trig
    :notify_manager_impl a comm:PythonHandler ; rdfs:label "notify manager handler" ;
        comm:handler "notify.notify_manager" .
```

`"notify.notify_manager"` means the function `notify_manager` in `handlers/notify.py`,
beside `expenses.trig`. The API exposes the operation, because the API runs the approval
process and a Python handler runs in the process that calls it:

```trig
            :pay_expense_op , :list_payments_op , :paid_expenses_op , :payouts ,
            :notify_manager_op ;
```

No screen submits to `:notify_manager_op`. The task invokes it, so the generated route
module lists it as "not routed" and serves no HTTP route for it.

## The task invokes it

The last facts join the task to the operation and to the shape it stores, in the seams
graph:

```trig
    <https://example.org/expenses/approval_bpmn#notify_manager>
        seam:invokes :notify_manager_op ;
        seam:writes :NotificationShape .
```

When the instance reaches the task, the runtime takes the stored expense, calls the
function with it, validates the returned dict against `:NotificationShape` and stores it.
The task fires no transition, so the expense stays `submitted` while the manager decides.

## Write the stub once

The model now names a function that does not exist yet. Let the stub generator write a
starting point:

```sh
python -m seams_gen.stubs examples/expenses/chapter-09/expenses.trig
```

It prints the files it creates: `handlers/__init__.py` and `handlers/notify.py`, each with
a `.trace.json` sidecar beside it. The module has a `TypedDict` for each shape the
operation accepts or returns, a signature that uses them, a docstring naming the
operation, the shapes, the service task that invokes it and the decision that routes to
it, and a body that raises:

```python
# Generated once by the seams handler stub generator from the expenses model.
# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).
# model-hash: sha256:a13fe61ea9f61e671cb3b5354897b972dc00f09a5840cb1da1df3546d7c9c970
# context-hash: sha256:622fb3abfd7cab3b12cc6bc41d4a34acb84b57e64cb166e961c5511aee9327de

from decimal import Decimal
from typing import NotRequired, TypedDict


class ExpenseShape(TypedDict):
    """:ExpenseShape (sh:NodeShape): one key per sh:property."""

    description: str
    amount: Decimal
    date: str
    status: NotRequired[str]
    id: NotRequired[str]


class NotificationShape(TypedDict):
    """:NotificationShape (sh:NodeShape): one key per sh:property."""

    recipient: str
    message: str


def notify_manager(entity: ExpenseShape) -> NotificationShape:
    """comm:handler "notify.notify_manager" of :notify_manager_impl (comm:PythonHandler).

    Implements :notify_manager_op (seam:implementedBy :notify_manager_impl).
    entity: the current :ExpenseShape entity (seam:acceptsShape).
    Returns: a :NotificationShape entity (seam:returnsShape).
    Invoked by :notify_manager (seam:invokes), a proc:ServiceTask of :approval_process.
    Decided by :approval_routing (seam:decidedBy): a gateway before the task routes on its output.
    """
    raise NotImplementedError("notify.notify_manager: write the handler for :notify_manager_op")
```

The class fields come from the shapes: `xsd:decimal` becomes `Decimal` (imported from
`decimal`, so an amount stays exact), `xsd:date` becomes
`str`, and a property with no `sh:minCount` is `NotRequired`. The notify task fires no
transition, so there is no `Fires` line. The `.trace.json` sidecar maps each line of the
stub to the model IRIs behind it, for the generation view.

The committed `handlers/notify.py` in the checkpoint was written by an earlier version of
the stub generator, before stubs had classes and model context, so its signature is
`(entity: dict) -> dict`. It is owned code, so it stays as it is.

Run the command again and it writes nothing. A file in the handlers package that exists
is never opened for writing.

## Write the handler

Replace the body with the real code. `entity` is the expense as a plain dict: its
`description`, `amount` and `date`, with no `id` and no `status`, because statuses belong
to the runtime. The `amount` arrives as a `Decimal`, as the stub types it, so it prints
as the submitted `250.00`. The result must match `NotificationShape`:

```python
# Who the notification is for: the approval process only runs this handler on
# the path the routing table sends to the manager.
RECIPIENT = "manager"


def notify_manager(entity: dict) -> dict:
    """comm:handler "notify.notify_manager" of :notify_manager_impl (comm:PythonHandler).

    Implements :notify_manager_op (seam:implementedBy :notify_manager_impl).
    entity: the current :ExpenseShape entity (seam:acceptsShape).
    Returns: a :NotificationShape entity (seam:returnsShape).

    Pure computation: the runtime validates the returned dict against
    :NotificationShape and the notify task stores it (seam:writes).
    """
    message = f"{entity['description']} ({entity['amount']}, {entity['date']}) is waiting for your approval."
    return {"recipient": RECIPIENT, "message": message}
```

The handler never sees the store, the bus or a secret. It gets an entity and returns one,
which makes it easy to test. Sending the message somewhere, by mail or chat, would be a
second operation with its own implementation, such as a `comm:HTTPEndpoint`. That is not
in this chapter.

## Why `seams generate` leaves it alone

[Principle 8](/project/principles#_8-generated-code-and-owned-code-never-mix) says
generated code and owned code never mix, and
[ADR-0012's regeneration rule](/adr/0012-operation-implementation#regeneration-rule)
applies it to the handlers package. The stub generator writes a module once, when it is
absent, and from then on the file is yours. It is not one of the generators in
`seams.toml`, so `seams generate` does not run it, and `seams.lock` does not record its
files. CI's committed-outputs check covers `generated/` and the compose files only.
`handlers/` is not excluded from ruff, so your code is linted and tested like any other.

The `model-hash` line in the module header records the model the stub was written from,
and the `context-hash` line the context of the task that invokes it (what
[`seams context`](/guide/authoring-a-model#what-a-task-depends-on-seams-context) prints).
Nothing checks them, so they can go stale without harm.

If you rename the function in the model, the runtime refuses to load and names
`:notify_manager_impl` and `comm:handler`. The stub generator reports the missing
function and leaves the module alone. Adding it is your edit.

## Generate the app

Regenerate the chapter:

```sh
seams generate --project examples/expenses/chapter-09
```

`expense_api.py` changes only in its model hash and its header, which lists
`:notify_manager_op` as not routed. Each compose file, `compose.development.yaml` and
`compose.production.yaml`, gains one line, a read-only bind mount
of the handlers package into the API container, because the API runs a process whose task
invokes a `comm:PythonHandler`:

```yaml
      - ./handlers:/model/handlers:ro
```

## Run it in process

Start the host on the chapter 9 files as in chapter 8. The runtime finds `handlers/`
beside the model file; `SEAMS_HANDLERS` points it somewhere else.

```sh
SEAMS_MODEL=examples/expenses/chapter-09/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-09/generated/templates \
SEAMS_STORE_OVERRIDE=sqlite \
SEAMS_DB=/tmp/expenses-09.sqlite \
python -m seams_runtime.host --routes examples/expenses/chapter-09/generated/expense_api.py --port 8001
```

Alice submits the hotel. It costs 250.00, so the routing table sends it to the manager:

```sh
curl -X POST http://localhost:8001/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02 \
  -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: employee"
```

Before Bob's approval task opens, the instance runs `notify_manager`. Its trace row has
`"implementation": "PythonHandler"` and `"handler": "notify.notify_manager"`, and the
stored notification says:

```
{"recipient": "manager", "message": "Hotel (250.00, 2026-10-02) is waiting for your approval."}
```

Bob's approval and Carol's payment then go as in chapter 8. A 50.00 expense takes the
auto path and notifies nobody. If the handler raises anything other than an error the
operation declares, the instance fails with a `HandlerError` that names
`:notify_manager_op` and the kind, and nothing is stored. The next section declares one.

## When the notification fails

The manager is told by text message, and a text message holds 160 characters. An expense
with a long description makes a message that does not fit. Failing the whole instance for
that would lose the expense. [ADR-0013](/adr/0013-error-shapes-and-boundaries) lets the
operation say how it fails, and lets the process catch that failure and take another
path.

### The operation declares its error

An operation names each error it can raise as a `hydra:Status`, through Hydra's own
`hydra:possibleStatus`. Add it to `:notify_manager_op`:

```trig
        seam:implementedBy :notify_manager_impl ;
        hydra:possibleStatus :notify_failed .
```

The status has its HTTP code, an error code the code raises and the BPMN matches, and the
shape of the error body:

```trig
    :notify_failed a hydra:Status ; rdfs:label "Notification failed" ;
        hydra:statusCode 502 ;
        comm:errorCode "notify-failed" ;
        seam:returnsShape :NotifyProblemShape .
```

The body is [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details
(`application/problem+json`). Its shape uses the `comm:` member properties, so the field
names are the JSON member names. Put it in the data graph beside `NotificationShape`:

```trig
    :NotifyProblemShape a sh:NodeShape ; rdfs:label "Notify problem" ;
        sh:property [ sh:path comm:title ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
        sh:property [ sh:path comm:status ; sh:datatype xsd:integer ; sh:minCount 1 ; sh:maxCount 1 ] ;
        sh:property [ sh:path comm:detail ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
        seam:inModel :expense_data .
```

You never state `title` or `status` in code. The runtime fills them from the status's
`rdfs:label` and `hydra:statusCode`, so each is stated once.

### The handler raises it

The handler raises `OperationError` with the error code and a `detail` member:

```python
from seams_runtime import OperationError

# Who the notification is for: the approval process only runs this handler on
# the path the routing table sends to the manager.
RECIPIENT = "manager"
# The manager is told by text message, which holds at most this many characters.
MAX_MESSAGE = 160


def notify_manager(entity: dict) -> dict:
    message = f"{entity['description']} ({entity['amount']}, {entity['date']}) is waiting for your approval."
    if len(message) > MAX_MESSAGE:
        raise OperationError(
            "notify-failed", f"the message is {len(message)} characters; a text message holds {MAX_MESSAGE}"
        )
    return {"recipient": RECIPIENT, "message": message}
```

A code the operation does not declare, or any other exception, still fails the instance.

### The process catches it

In BPMN the construct is an error boundary event: a catch event on the edge of a task,
with its own outgoing flow. Declare the error once at the top of `approval.bpmn`, with
the same code:

```xml
<bpmn:error id="notify_failed_error" name="Notification failed" errorCode="notify-failed" />
```

Attach the boundary to `notify_manager`, and send its flow to finance's approval task:

```xml
<bpmn:boundaryEvent id="notify_failed_boundary" name="Notification failed" attachedToRef="notify_manager">
  <bpmn:outgoing>flow_escalate</bpmn:outgoing>
  <bpmn:errorEventDefinition id="notify_failed_def" errorRef="notify_failed_error" />
</bpmn:boundaryEvent>
```

```xml
<bpmn:sequenceFlow id="flow_escalate" name="escalate" sourceRef="notify_failed_boundary" targetRef="finance_approve_expense" />
```

`finance_approve_expense` gains `flow_escalate` as a second incoming flow. The boundary
catches an operation's error, so it takes part in a seam and gets an IRI, as every
seam-bearing BPMN element does. Lift it into the process graph:

```trig
    <https://example.org/expenses/approval_bpmn#notify_failed_boundary> a proc:ErrorBoundaryEvent ;
        rdfs:label "Notification failed" ;
        seam:inModel :approval_bpmn .
```

and say which error it catches, in the seams graph:

```trig
    <https://example.org/expenses/approval_bpmn#notify_failed_boundary>
        seam:catches :notify_failed .
```

The task it is attached to and the code stay in the XML. When the runtime loads, it
checks the two agree: a boundary on `notify_manager` that catches a status of
`:notify_manager_op`, with a `bpmn:error` whose `errorCode` is that status's
`comm:errorCode`. If you mistype the code in either file, the runtime refuses to load and
names the boundary and `seam:catches`.

### Run the error path

Regenerate the chapter. Only the model hashes change, because no route serves
`:notify_manager_op`. Then submit an expense whose description is too long for a text
message:

```sh
curl -X POST http://localhost:8001/expenses/conf -d amount=250.00 -d date=2026-10-03 \
  -d "description=Conference in Leeds: three nights at the venue hotel, the conference dinner, return rail tickets and two taxis" \
  -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: employee"
```

The message is 161 characters, so the handler raises `notify-failed`. The runtime builds
the problem body and validates it against `NotifyProblemShape`:

```
{"title": "Notification failed", "status": 502, "detail": "the message is 161 characters; a text message holds 160"}
```

It then routes the instance down the boundary. The body becomes the instance's current
`NotifyProblemShape` entity, so a task on the error path could read it. Nothing is
stored for the notification and the expense stays `submitted`. The `notify_manager` trace
row records what happened:

```
"error": {"code": "notify-failed", "status": "https://example.org/expenses/notify_failed", "operation": "https://example.org/expenses/notify_manager_op"},
"boundary": "https://example.org/expenses/approval_bpmn#notify_failed_boundary"
```

The next row is the boundary's own, with `"caught": "notify-failed"`. The OpenTelemetry
span for the task carries the same facts as `seams.error.code`, `seams.error.status` and
`seams.boundary`. Bob has no approval task for this expense. Carol finds it on the finance
approval form, and once she approves it, it goes on to payment as any other expense does.

In the viewer, open Expense Approval (BPMN). The boundary sits on the edge of Notify
Manager with one seam badge, "catches → Notification failed". Click the badge to open the
status, which shows the boundary that catches it and the shape its body returns.

## Run it with docker compose

The stack is chapter 8's development environment, with the handlers package mounted into
the API:

```sh
docker compose -f examples/expenses/chapter-09/compose.development.yaml up --build
```

Submit the hotel against port 8080, then ask the store what landed under its key:

```sh
docker compose -f examples/expenses/chapter-09/compose.development.yaml exec -T expense_db psql -U postgres -d expenses -tAc "SELECT shape FROM entities WHERE correlation_key = 'hotel'"
```

The list now includes `https://example.org/expenses/NotificationShape` beside the
expense. `tests/test_expense_e2e.py` runs this stack in CI's `tutorial-e2e` job and
waits for that row. Stop the stack with
`docker compose -f examples/expenses/chapter-09/compose.development.yaml down -v`.

CI checks the rest of this chapter in `tests/test_expense_handler.py`. It runs the notify
step in process and checks its trace row and stored notification. It checks that the
other routes notify nobody and that a failing handler fails the instance. It also runs
`seams generate` and the stub generator on a copy of the checkpoint and checks that
`handlers/` is byte for byte unchanged. `tests/test_expenses_error_path.py` checks the
error path: the 160-character limit, the boundary resolved at load and the load faults
for a mismatched code, the routed trace rows and spans, the problem body, finance's
approval after the escalation, and the boundary's badge in the viewer.

## Remind the manager

An expense can wait on Bob for days. BPMN can say "if this task is still open after two
days, do something" with a timer boundary event: a catch event on the edge of the task,
like the error boundary, whose definition holds a time instead of an error
([ADR-0037](/adr/0037-timers-and-scheduling)). Attach one to `approve_expense`, and give
it a short path of its own:

```xml
<bpmn:boundaryEvent id="overdue_reminder" name="Approval overdue" attachedToRef="approve_expense" cancelActivity="false">
  <bpmn:outgoing>flow_to_remind</bpmn:outgoing>
  <bpmn:timerEventDefinition id="overdue_reminder_def">
    <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT48H"</bpmn:timeDuration>
  </bpmn:timerEventDefinition>
</bpmn:boundaryEvent>
<bpmn:endEvent id="reminder_end" name="Reminded">
  <bpmn:incoming>flow_to_remind</bpmn:incoming>
</bpmn:endEvent>
<bpmn:sequenceFlow id="flow_to_remind" sourceRef="overdue_reminder" targetRef="reminder_end" />
```

`cancelActivity="false"` makes it non-interrupting: when it fires, the instance runs the
reminder path and Approve Expense stays open, so Bob can still decide. The duration is one
quoted ISO 8601 literal, `"PT48H"`, which the runtime can read without running the
process. A variable, a cron string, a date-time without an offset or a cycle without a
start date is refused when the runtime loads, naming the event and the expression's
element, and `seams check` reports the same as a `timer` finding.

The graph says what the element is, and the XML says when it fires. Lift it into the
process graph as a `proc:TimerCatchEvent`, the class `proc` 1.1 adds, which is why the
manifest graph above imports `proc/1.1`:

```trig
    <https://example.org/expenses/approval_bpmn#overdue_reminder> a proc:TimerCatchEvent ;
        rdfs:label "Approval overdue" ;
        seam:inModel :approval_bpmn .
```

When the runtime loads, it checks that the two agree: a boundary attached to a user task,
with exactly one timer definition holding exactly one expression. It also checks that
the store keeps a timer table, which SQLite and PostgreSQL do. When an instance reaches
Approve Expense, the worker writes the reminder's due time (48 hours from then, in UTC)
to the `timers` table in the same transaction as the checkpoint. Every second the API's
scheduler leases the rows that are due, fires each one in the instance, and deletes the
row while it still holds the lease. Two replicas sharing the store fire a reminder once.
Each firing logs `timer fire <event> due <due> instance <id>` and runs in the
`seams.timer.claim` and `seams.timer.fire` spans.

The new path shows in `seams sequence :submit_expense` like any other. The note says the
task stays open:

<<< @/generation/sequences/expenses-chapter-09/submit_expense--manager--overdue_reminder.mmd{mermaid}

Nobody waits 48 hours to see it. The runtime's clock can run ahead of the system clock
by an ISO 8601 duration in `SEAMS_CLOCK_OFFSET`, a development setting the generated
compose never writes. With the stack up and an expense waiting on Bob, recreate the API
with the clock 49 hours ahead, through an override file of your own:

```yaml
services:
  expense_api:
    environment:
      SEAMS_CLOCK_OFFSET: PT49H
```

```sh
docker compose -f examples/expenses/chapter-09/compose.development.yaml -f compose.clock.yaml up -d --wait --no-deps expense_api
```

Within a second of starting, the API logs the reminder's `timer fire` line, the expense's
`timers` row is gone, and Bob's approval task is still in `user_tasks`.
`tests/test_expense_e2e.py` does exactly this against the stack. `tests/test_timer_runtime.py`
runs the same reminder in process on a stepped clock, with two runtimes sharing one store.

## Say what it should do

The model now says what the app *is*. It can also say what the app should *do*
([ADR-0014](/adr/0014-scenarios-and-derived-tests)). Add the `verify:` prefix:

```trig
@prefix verify: <https://w3id.org/seams/verify#> .
```

Import its version in the manifest graph too:

```trig
<urn:seams:graph:manifest> {

    # One owl:imports per vocabulary the model uses (ADR-0021).
    <urn:seams:graph:manifest> a owl:Ontology ;
        owl:imports <https://w3id.org/seams/arch/1.2> ,
                    <https://w3id.org/seams/comm/1.0> ,
                    <https://w3id.org/seams/deploy/1.0> ,
                    <https://w3id.org/seams/ifml/1.0> ,
                    <https://w3id.org/seams/proc/1.1> ,
                    <https://w3id.org/seams/seam/1.6> ,
                    <https://w3id.org/seams/state/1.0> ,
                    <https://w3id.org/seams/verify/1.1> .
}
```

Then, at the end of the seams graph, state one run of the approval process for each
route. An employee submits, the named parties complete the user tasks in order, and
the expense ends in the state you expect. The manager's run looks like this:

```trig
    :manager_approved a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                     [ verify:field :amount ; verify:value 200.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#approve_expense> ;
                        verify:actor :manager ;
                        verify:given [ verify:field :decision ; verify:value "approved" ] ] ) ;
        verify:expectState :s_approved .
```

`:auto_approved` has no steps and expects `:s_approved`. `:finance_approved` has two
steps, finance approving and then paying, and also expects the `approved_end` event.
`:manager_rejected` and `:finance_rejected` each have one step in which the manager or
finance sends `"rejected"`, and expect `:s_rejected` and the `rejected_end` event.
Each rule of both decision tables gets an example at its limit, and `:ExpenseShape`
gets an expense it accepts and one it refuses:

```trig
    :routes_up_to_100_automatically a verify:DecisionExample ;
        verify:decision :approval_routing ;
        verify:given [ verify:field :amount ; verify:value 100.00 ] ;
        verify:expectOutput [ dec:variable "Route" ; verify:value "auto" ] .
```

```trig
    :ExpenseShape verify:validExample :expense_train ;
        verify:invalidExample :expense_negative_amount .
    :expense_train :description "Train to Leeds" ; :amount 42.50 ; :date "2026-10-01"^^xsd:date .
    :expense_negative_amount :description "Refund" ; :amount -5.00 ; :date "2026-10-01"^^xsd:date .
```

The shapes check these too: a decision example must give every input its decision
reads, and a scenario must expect something. The `tests` generator turns each one into
a test whose name carries its local name, so a moved threshold fails the test named for `routes_up_to_100_automatically`.
It also writes `test_policies.py` from the ODRL policies you already have: each
permission's assignee may act and every other party is refused. Add it to `seams.toml`
(`name = "tests"`, `out = "generated/tests"`), run `seams generate`, then
`pytest generated/tests`.
[Scenarios and examples](/guide/authoring-a-model#scenarios-and-examples) in
the authoring guide lists the terms.

### What the scenarios leave out

Ask the model what no scenario covers:

```sh
seams coverage examples/expenses/chapter-09
```

Every transition is fired and every permission gets a deny test. The reject paths are
covered by two scenarios like the manager's run above, with `"rejected"` as the
decision:

```trig
    :manager_rejected a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                     [ verify:field :amount ; verify:value 200.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#approve_expense> ;
                        verify:actor :manager ;
                        verify:given [ verify:field :decision ; verify:value "rejected" ] ] ) ;
        verify:expectState :s_rejected ;
        verify:expectEndEvent <https://example.org/expenses/approval_bpmn#rejected_end> .
```

A scenario may only expect an end event that the model lifts into the process graph, so
`rejected_end` is lifted with a label and `seam:inModel`, as `approved_end` already is.

Five paths are still left. The command lists each by IRI and exits 1. In the viewer,
open the Expense Approval process and ask **Which paths does no scenario run?** under
Questions to see the same paths for that process. Two are the escalations through the
notify-failed boundary event. A scenario makes Notify Manager's operation fail with a
`verify:failure`. It names the operation and the error, and the runtime raises that
error whenever the run invokes the operation, whatever the handler would do:

```trig
    :notify_failed_rejected a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                     [ verify:field :amount ; verify:value 200.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:failure [ verify:operation :notify_manager_op ; verify:status :notify_failed ] ;
        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#finance_approve_expense> ;
                        verify:actor :finance ;
                        verify:given [ verify:field :decision ; verify:value "rejected" ] ] ) ;
        verify:expectState :s_rejected ;
        verify:expectEndEvent <https://example.org/expenses/approval_bpmn#rejected_end> .
```

`:notify_failed_approved` is the same run with `"approved"`, followed by the payment.
The other two are the payout paths. `payout_process` starts on a message, not a form,
but a run that pays an expense publishes on `:payouts` and starts it. A scenario's run
takes in that process too, so it can expect the state a payout leaves the payment in:

```trig
    :paid_now a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Conference in Lisbon" ] ,
                     [ verify:field :amount ; verify:value 5000.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#finance_approve_expense> ;
                        verify:actor :finance ;
                        verify:given [ verify:field :decision ; verify:value "approved" ] ]
                      [ verify:task <https://example.org/expenses/approval_bpmn#pay_expense> ;
                        verify:actor :finance ;
                        verify:given [ verify:field :reference ; verify:value "PAY-0045" ] ,
                                     [ verify:field :paidOn ; verify:value "2026-10-05"^^xsd:date ] ] ) ;
        verify:expectState :s_sent .
```

`:paid_in_batch` pays 200.00 after the manager approves and expects `:s_batched`. Both
terms came with the 1.1 version of the `verify` vocabulary, so the manifest graph now
imports `verify/1.1` ([ADR-0014](/adr/0014-scenarios-and-derived-tests), as amended).

The fifth is the reminder's. A scenario needs no new term for it, because a run lets
the timers its instance waits on fire once its steps are done, as if their due times had
come. A run with no step on Approve Expense therefore takes the reminder path. It expects
the reminder's end, which is lifted with a label, as `rejected_end` is:

```trig
    :manager_reminded a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                     [ verify:field :amount ; verify:value 200.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:expectState :s_submitted ;
        verify:expectEndEvent <https://example.org/expenses/approval_bpmn#reminder_end> .
```

```trig
    <https://example.org/expenses/approval_bpmn#reminder_end> rdfs:label "Reminded" ;
        seam:inModel :approval_bpmn .
```

The expense is still `submitted` after the reminder, and its approval task is still
open. A scenario that completes Approve Expense never fires the reminder, since
completing the task cancels its timer.
Now `seams coverage` lists nothing and exits 0, so chapter 9's `seams.toml` turns the
paths gate on, and `seams check` fails if a later change leaves a path unrun (see
[seams coverage](/reference/seams-cli#seams-coverage)):

```toml
coverage = ["paths"]
```

### Smoke tests against the running stack

The tests above run the model in process. The `smoke` generator checks the deployed
app instead. It writes `test_smoke.py`, with one test per `hydra:Operation`. Each test calls
the operation on its `comm:path` and checks the answer against the
`seam:returnsShape` of the status it got. Add it to `seams.toml` (`name = "smoke"`,
`out = "generated/smoke"`), run `seams generate`, start the docker compose stack above,
then call it as the employee:

```sh
SEAMS_SMOKE_BASE_URL=http://localhost:8080 SEAMS_SMOKE_USER=alice SEAMS_SMOKE_GROUPS=employee pytest -rs examples/expenses/chapter-09/generated/smoke
```

The three list pages answer. The six operations on `/expenses/{expense}` are skipped,
because `:expense_train` has no `:id` to fill the path. Once an example fills it, an
operation whose policy refuses the identity is skipped too, and the reason names that
policy, for example `:manager_approval_policy`. Without
`SEAMS_SMOKE_BASE_URL` every test is skipped. `tests/test_expense_e2e.py` runs these tests
against the stack in CI's `tutorial-e2e` job.

### Acceptance tests for your handler

The tests above check the process; nothing yet checks the handler you wrote against the
model. The `acceptance` generator does. For every module of the handlers package it writes
`generated/acceptance/test_<module>.py`, here `test_notify.py`, from the same facts the
stub was written from. Each test asks one question of `notify_manager`:

- **Types.** It takes one entity, and its annotations are `dict` or TypedDicts with the
  keys and required-ness of `:ExpenseShape` and `:NotificationShape`.
- **Shape conformance.** Called with `:expense_train`, it returns a notification that
  conforms to `:NotificationShape`, or raises the declared `:notify_failed` error.
- **Decision branches.** For each decision example of `:approval_routing`, the process run
  in process reaches Notify manager exactly when the routing sends the expense to the
  manager.
- **Legal transitions.** A task that fires a lifecycle transition is also checked to run
  only in the transition's from-state. Notify manager fires none, so its decision tests
  check that its run moves no state instead.

Add it to `seams.toml` (`name = "acceptance"`, `out = "generated/acceptance"`), run
`seams generate`, then:

```sh
pytest examples/expenses/chapter-09/generated/acceptance
```

The tests import your handler from the project's handlers package, so they test the code
you own, not the stub. A failing test names the model fact it checks, for example the
shape the result breaks. Like the other generated files, `test_notify.py` is regenerated
on every `seams generate` and must not be edited.

### Draft it with an LLM (optional)

You can ask an LLM for the body instead of writing it. `seams propose` builds a prompt
from the task's context, the stub and these tests, sends it to a command you name, and
keeps the draft only if the tests pass:

```sh
seams propose send_now --project examples/expenses/chapter-09 --provider "my-llm" --force
```

The provider is any command that reads the prompt on stdin and prints the draft;
the model's labels reach it only as quoted data, and binding values never. A draft
that fails a test is not written, and each failing test is named. One that passes is
written to `handlers/notify.py` and is yours from then on, like code you typed, so
read it before you commit it. `seams propose` also records the draft in `seams.lock`,
so `seams check` tells you when the model facts it was written from change
(`draft-stale`) or when the file no longer matches it (`draft-hand-edited`). See the [CLI reference](../../reference/seams-cli.md#seams-propose).

## Say what the data is

The shapes say what each form and list carries: `ExpenseShape` is the submit form's
contract, `ApprovalShape` the approver's. Neither says what an expense *is*. An
ontology model does ([ADR-0022](../../adr/0022-ontology-notation.md)): a model graph of
OWL classes, each a kind of something in [gist](https://github.com/semanticarts/gist),
the small upper ontology SemanticSeams ships pinned in `ontology/vendor/`. Add two
prefixes beside the others:

```turtle
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix gist:   <https://w3id.org/semanticarts/ns/ontology/gist/> .
```

and, after the data model graph, a model graph whose `seam:Model` is also the
`owl:Ontology`. It has one version IRI, which moves when the classes change, and imports
gist by gist's version IRI:

```trig
<urn:seams:graph:model:expense_ontology> {

    :expense_ontology a seam:Model , owl:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .

    # Money an employee spent for the company. gist: a transfer of funds.
    :Expense a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Expense" ;
        skos:definition "Money an employee spent on the company's behalf and asks to have reimbursed." ;
        seam:inModel :expense_ontology .

    # The company's transfer that reimburses an expense. Also a transaction.
    :Payment a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Payment" ;
        skos:definition "Money the company transfers to reimburse an expense." ;
        seam:inModel :expense_ontology .

    # A manager's or finance's decision on an expense. gist: an event that
    # establishes a result by evaluating.
    :Approval a owl:Class ;
        rdfs:subClassOf gist:Determination ;
        rdfs:label "Approval" ;
        skos:definition "An evaluation that establishes whether an expense is reimbursed." ;
        seam:inModel :expense_ontology .

    # States and outcomes are categories, not strings.
    :ExpenseState a owl:Class ;
        rdfs:subClassOf gist:Category ;
        rdfs:label "Expense state" ;
        skos:definition "A stage an expense is in: draft, submitted, approved, rejected or paid." ;
        seam:inModel :expense_ontology .

    :ApprovalOutcome a owl:Class ;
        rdfs:subClassOf gist:Category ;
        rdfs:label "Approval outcome" ;
        skos:definition "What an approval decides: approved or rejected." ;
        seam:inModel :expense_ontology .

    # The outcomes themselves. An expense's states are :ExpenseState
    # members too; they are typed where they are declared, in
    # :expense_lifecycle.
    :outcome_approved a :ApprovalOutcome ; rdfs:label "approved" ; seam:inModel :expense_ontology .
    :outcome_rejected a :ApprovalOutcome ; rdfs:label "rejected" ; seam:inModel :expense_ontology .
}
```

Each class has a label, a definition and one gist superclass: `Expense` and `Payment`
are `gist:Transaction`s, `Approval` a `gist:Determination`, and `ExpenseState` and
`ApprovalOutcome` are `gist:Category`s. A category's members are plain IRIs with one
label each: the two approval outcomes here, and the expense's states below. In the seams graph, give the model its notation:

```turtle
    :expense_ontology seam:notation seam:Ontology .
```

`seams check --project examples/expenses/chapter-09` resolves the import offline
against `ontology/vendor/`. Change it to `gistCore14.1.0` and the model is refused,
naming the fact:

```
cannot resolve https://example.org/expenses/expense_ontology: missing http://www.w3.org/2002/07/owl#imports (imports gistCore14.1.0; the vendored version is gistCore14.0.0)
```

A superclass that is in neither the ontology nor gist, such as a mistyped
`gist:Transation`, is a warning instead. Open `:expense_ontology` in the viewer to see
the class view: a card per class with its definition, an edge to its gist superclass,
and gist's classes as grey read-only cards; the health panel lists the import as
vendored. gist is never added to the model.

## Point the shapes at the classes

The shapes still copy facts the model already has: `ExpenseShape`'s `status` lists the
five state labels as strings, `ApprovalShape`'s `decision` lists two more, and nothing
says that `ExpenseShape` describes an `Expense`. Rewrite them in the notation of
[ADR-0023](../../adr/0023-shapes-target-classes.md). Each shape names its class with
`sh:targetClass`, and each field names itself with `sh:name`, the name forms and payloads
use. A field whose options are a category's members says `sh:class` instead of copying
their labels:

```trig
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
        sh:property [ sh:path :description ; sh:name "description" ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
        sh:property [ sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01 ; sh:order 1 ] ;
        sh:property [ sh:path :date ; sh:name "date" ; sh:datatype xsd:date ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 2 ] ;
        # Set by the runtime, never entered: the expense's current state in
        # :expense_lifecycle. The options are the :ExpenseState members (the
        # lifecycle's states) in lifecycle order; the wire value is the
        # member's rdfs:label, so the payload still carries "draft" (ADR-0023).
        sh:property [ sh:path :status ; sh:name "status" ; sh:class :ExpenseState ;
                      sh:maxCount 1 ; sh:order 3 ] ;
        seam:inModel :expense_data .

    # What the approver enters: a decision from the list, and an optional comment.
    # The decision is an :ApprovalOutcome member, sent as its label.
    :ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ;
        sh:targetClass :Approval ;
        sh:property [ sh:path :decision ; sh:name "decision" ; sh:class :ApprovalOutcome ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
```

The expense's states become the category's members where the lifecycle declares them:

```trig
    :s_draft     a state:State , :ExpenseState ; rdfs:label "draft"     ; seam:inModel :expense_lifecycle .
    :s_submitted a state:State , :ExpenseState ; rdfs:label "submitted" ; seam:inModel :expense_lifecycle .
    :s_approved  a state:State , :ExpenseState ; rdfs:label "approved"  ; seam:inModel :expense_lifecycle .
    :s_rejected  a state:State , :ExpenseState ; rdfs:label "rejected"  ; seam:inModel :expense_lifecycle .
    :s_paid      a state:State , :ExpenseState ; rdfs:label "paid"      ; seam:inModel :expense_lifecycle .
```

The payment has no state category, so its `status` lists the payment lifecycle's state
IRIs with `sh:in` instead of their labels. Its date shows what `sh:name` is for: the RDF
property can be `:paidOn` while the form field and the payload member stay `paid_on`.
The screen parameter and the scenario that name the property move to `:paidOn` with it.

```trig
    :PaymentShape a sh:NodeShape ; rdfs:label "Payment" ;
        sh:targetClass :Payment ;
        sh:property [ sh:path :reference ; sh:name "reference" ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:maxLength 100 ; sh:order 0 ] ;
        sh:property [ sh:path :paidOn ; sh:name "paid_on" ; sh:datatype xsd:date ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 1 ] ;
        # Set by the runtime, never entered: the payment's current state in
        # :payment_lifecycle. The payment has no state category yet, so the
        # options are an sh:in of the state IRIs, sent as their labels.
        sh:property [ sh:path :status ; sh:name "status" ; sh:maxCount 1 ; sh:order 2 ;
                      sh:in ( :s_recorded :s_scheduled :s_batched :s_sent ) ] ;
        seam:inModel :expense_data .
```

Options come in lifecycle order, from the initial state, and the value a form sends is
still the member's label. Older tools would misread this notation, so the model now
imports the seam vocabulary at 1.2 or later (1.5 today); the manifest above already shows it:

```turtle
                    <https://w3id.org/seams/seam/1.6> ,
```

Run `seams generate --project examples/expenses/chapter-09` again. Every generated form,
route, stub and test is the same as before, apart from the model hash. The status
select still offers `draft` to `paid`, the approver still picks `approved` or `rejected`,
and a payload with `"decision": "maybe"` is refused with the same 422. Rename a state
now and its option is renamed with it. Add one and it joins the options in lifecycle order.

### Put the lifecycles on the classes

Since chapter 6 the expense's lifecycle has hung off `:ExpenseShape`, and since chapter 8
the payment's off `:PaymentShape`. Now that the classes exist, the lifecycle can belong
to the thing rather than to one shape of it
([ADR-0031](../../adr/0031-lifecycle-on-the-class.md)). In the seams graph:

```trig
    :Expense seam:lifecycle :expense_lifecycle .
    :Payment seam:lifecycle :payment_lifecycle .
```

`:ExpenseShape` targets `:Expense`, so its lifecycle now comes through
`sh:targetClass`: the `awaiting_approval` guard, the first state on submit and the
status options are unchanged, and so is every generated file apart from the model hash.
A shape that reached two different lifecycles, one of its own and one through its class,
would be refused by `seams check`.

## Serve the payloads as JSON-LD

Now that each shape names its class, the API can say what its payloads mean as RDF
without changing them ([ADR-0024](../../adr/0024-json-ld-context.md)). Add the `jsonld`
generator to `seams.toml`:

```toml
[[generators]]
name = "jsonld"
out = "generated/contexts"
```

Run `seams generate --project examples/expenses/chapter-09` again. It writes one
JSON-LD context per target-classed shape, `ExpenseShape.jsonld`, `ApprovalShape.jsonld`
and `PaymentShape.jsonld`, in `generated/contexts/`. Each field's name maps to its
property, typed by its datatype, and the category fields map each label to its member:

```json
    "status": {
      "@context": {
        "approved": "https://example.org/expenses/s_approved",
        "draft": "https://example.org/expenses/s_draft",
        ...
      },
      "@id": "https://example.org/expenses/status",
      "@type": "@vocab"
    }
```

So `"status": "submitted"` reads as `:status :s_submitted`, and `PaymentShape`'s
`paid_on` reads as `:paidOn`. The route module serves the same text at
`GET /contexts/ExpenseShape.jsonld` and its two siblings, and every route that returns an
expense or a payment adds a header naming its context:

```
Link: </contexts/ExpenseShape.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"
```

A client that ignores JSON-LD sees nothing new. `NotificationShape` and the problem
shape describe messages, not things, so they have no target class and no context.

## Checkpoint

Your files should now match
[`examples/expenses/chapter-09/expenses.trig`](../../../examples/expenses/chapter-09/expenses.trig),
[`approval.bpmn`](../../../examples/expenses/chapter-09/approval.bpmn) and the owned
handler [`handlers/notify.py`](../../../examples/expenses/chapter-09/handlers/notify.py).
The other payload files are unchanged from chapter 8. The generated code is in
[`examples/expenses/chapter-09/generated/`](../../../examples/expenses/chapter-09/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-08/expenses.trig examples/expenses/chapter-09/expenses.trig
```

You started from an empty file and now have an architecture,
two screen models, two processes, two decisions, two lifecycles, roles, a deployment and
one function you wrote yourself, with a declared error the process catches, and an ontology that says what the data is. The model says where that function lives and what it
takes and returns, so it fits with everything that was generated.

[Chapter 10](./10-sempkm) moves the expenses into SemPKM, a semantic knowledge store.
