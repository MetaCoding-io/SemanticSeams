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

It prints the two files it creates, `handlers/__init__.py` and `handlers/notify.py`. The
module has the signature, a docstring naming the operation and the two shapes, and a body
that raises:

```python
def notify_manager(entity: dict) -> dict:
    """comm:handler "notify.notify_manager" of :notify_manager_impl (comm:PythonHandler).

    Implements :notify_manager_op (seam:implementedBy :notify_manager_impl).
    entity: the current :ExpenseShape entity (seam:acceptsShape).
    Returns: a :NotificationShape entity (seam:returnsShape).
    """
    raise NotImplementedError("notify.notify_manager: write the handler for :notify_manager_op")
```

Run the command again and it writes nothing. A file in the handlers package that exists
is never opened for writing.

## Write the handler

Replace the body with the real code. `entity` is the expense as a plain dict: its
`description`, `amount` and `date`, with no `id` and no `status`, because statuses belong
to the runtime. The result must match `NotificationShape`:

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
files. CI's committed-outputs check covers `generated/` and `compose.yaml` only.
`handlers/` is not excluded from ruff, so your code is linted and tested like any other.

The `model-hash` line in the module header records the model the stub was written from.
Nothing checks it, so it can go stale without harm.

If you rename the function in the model, the runtime refuses to load and names
`:notify_manager_impl` and `comm:handler`. The stub generator reports the missing
function and leaves the module alone. Adding it is your edit.

## Generate the app

Regenerate the chapter:

```sh
seams generate --project examples/expenses/chapter-09
```

`expense_api.py` changes only in its model hash and its header, which lists
`:notify_manager_op` as not routed. `compose.yaml` gains one line, a read-only bind mount
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

The stack is chapter 8's, with the handlers package mounted into the API:

```sh
docker compose -f examples/expenses/chapter-09/compose.yaml -f examples/expenses/chapter-09/compose.override.yaml up --build
```

Submit the hotel against port 8080, then ask the store what landed under its key:

```sh
docker compose -f examples/expenses/chapter-09/compose.yaml -f examples/expenses/chapter-09/compose.override.yaml exec -T expense_db psql -U postgres -d expenses -tAc "SELECT shape FROM entities WHERE correlation_key = 'hotel'"
```

The list now includes `https://example.org/expenses/NotificationShape` beside the
expense. `tests/test_expense_e2e.py` runs this stack in CI's `tutorial-e2e` job and
waits for that row. Stop the stack with
`docker compose -f examples/expenses/chapter-09/compose.yaml -f examples/expenses/chapter-09/compose.override.yaml down -v`.

CI checks the rest of this chapter in `tests/test_expense_handler.py`. It runs the notify
step in process and checks its trace row and stored notification. It checks that the
other routes notify nobody and that a failing handler fails the instance. It also runs
`seams generate` and the stub generator on a copy of the checkpoint and checks that
`handlers/` is byte for byte unchanged. `tests/test_expenses_error_path.py` checks the
error path: the 160-character limit, the boundary resolved at load and the load faults
for a mismatched code, the routed trace rows and spans, the problem body, finance's
approval after the escalation, and the boundary's badge in the viewer.

## Say what it should do

The model now says what the app *is*. It can also say what the app should *do*
([ADR-0014](/adr/0014-scenarios-and-derived-tests)). Add the `verify:` prefix:

```trig
@prefix verify: <https://w3id.org/seams/verify#> .
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
[Scenarios and examples](/guide/authoring-a-model#scenarios-and-examples) in
the authoring guide lists the terms.

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

That is the whole tutorial. You started from an empty file and now have an architecture,
two screen models, two processes, two decisions, two lifecycles, roles, a deployment and
one function you wrote yourself, with a declared error the process catches. The model says where that function lives and what it
takes and returns, so it fits with everything that was generated.
