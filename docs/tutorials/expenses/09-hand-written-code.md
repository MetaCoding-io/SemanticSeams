# 9. Hand-written code

At the end of this chapter the manager is told about an expense before the approval task
opens for them. The message comes from a few lines of Python that you write yourself. The
model says where that code lives and what it takes and returns, and `seams generate`
never touches it.

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
        seam:implementedBy :notify_manager_impl .
```

`seam:implementedBy` names what serves it. The implementation node's type is its kind,
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
auto path and notifies nobody. If the handler raises, the instance fails with a
`HandlerError` that names `:notify_manager_op` and the kind, and nothing is stored.

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
`handlers/` is byte for byte unchanged.

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
one function you wrote yourself. The model says where that function lives and what it
takes and returns, so it fits with everything that was generated.
