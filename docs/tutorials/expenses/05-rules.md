# 5. The rules

At the end of this chapter the process decides who approves an expense by its amount.
Expenses of up to 100 are approved automatically, with no person involved. Expenses above
100 and up to 1000 go to a manager, as every expense did in chapter 4. Anything above 1000
goes to finance. The rule lives in a DMN decision table, so you change a threshold by
editing the table: the generated code does not change, apart from the model hash it
records.

You write the table, bind it to the model, add a gateway to the process with one path per
outcome, and give finance its own approval form. Then you submit three amounts and watch
them take three paths through the same generated app.

## One more prefix

Decisions have their own vocabulary. Add it after `proc:`:

```trig
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix dec:    <https://w3id.org/seams/dec#> .
```

## The decision table

The table is a DMN file next to the model, `approval.dmn`. It has one input, the amount,
and one output column, `Route`. The hit policy is `FIRST`: the rules are tried in order and
the first that matches wins, so the second rule only sees amounts above 100 and the last
rule, `-` (any value), catches the rest.

```xml
<decisionTable id="routing_table" hitPolicy="FIRST">
  <input id="input_amount" label="Amount">
    <inputExpression id="input_amount_expr" typeRef="number">
      <text>amount</text>
    </inputExpression>
  </input>
  <output id="output_route" label="Route" typeRef="string" />

  <rule id="rule_auto">
    <inputEntry id="rule_auto_amount"><text>&lt;= 100</text></inputEntry>
    <outputEntry id="rule_auto_out"><text>"auto"</text></outputEntry>
  </rule>
  <rule id="rule_manager">
    <inputEntry id="rule_manager_amount"><text>&lt;= 1000</text></inputEntry>
    <outputEntry id="rule_manager_out"><text>"manager"</text></outputEntry>
  </rule>
  <rule id="rule_finance">
    <inputEntry id="rule_finance_amount"><text>-</text></inputEntry>
    <outputEntry id="rule_finance_out"><text>"finance"</text></outputEntry>
  </rule>
</decisionTable>
```

The table sits inside a `decision` with the id `approval_routing`. The full file,
[`examples/expenses/chapter-05/approval.dmn`](../../../examples/expenses/chapter-05/approval.dmn),
adds the `inputData` the decision requires and a DMNDI section with a position for each
shape, so the viewer can draw the decision requirements diagram. Any DMN editor, such as
the [bpmn.io DMN demo](https://demo.bpmn.io/dmn), writes both.

`typeRef="number"` on the input expression matters. A form sends every value as text, so
the runtime receives the amount as the string `"250.00"`. It converts the input to a number
because the table says the input is a number, and only then compares it with `<= 100`.

## The decision model

The table is a model of its own, so it gets its own graph. The graph names the decision
and binds it to the file: `dec:payloadElement` is the DMN decision id, the `dec:input`
fills the table's `amount` variable from the expense's `:amount`, and the `dec:output`
copies the `Route` column into a process variable called `route`:

```trig
<urn:seams:graph:model:approval_dmn> {

    :approval_dmn a seam:Model , dec:DecisionModel ;
        rdfs:label "Approval Routing (DMN)" .

    # The decision and how the runtime binds it to approval.dmn: the DMN
    # decision id, the table's input variable "amount" filled from the
    # expense's :amount, and the output column "Route" copied into the
    # process variable "route" that the gateway reads.
    :approval_routing a dec:Decision ; rdfs:label "Route Approval" ;
        dec:payloadElement "approval_routing" ;
        dec:input [ a dec:InputBinding ; dec:variable "amount" ; dec:fromPath :amount ] ;
        dec:output [ a dec:OutputBinding ; dec:variable "Route" ; dec:processVariable "route" ] ;
        seam:inModel :approval_dmn .
}
```

In the seams graph, give it its notation and its file, as you did for the BPMN model:

```trig
    :approval_dmn seam:notation seam:DMN ;
        seam:renderPayload <approval.dmn> .
```

## The gateway

The process gains two elements after `persist_expense`: a business-rule task,
`route_expense`, that evaluates the table, and an exclusive gateway with one outgoing flow
per route. Each flow has a condition on the `route` variable:

```xml
<bpmn:businessRuleTask id="route_expense" name="Route Expense">
  <bpmn:incoming>flow_to_route</bpmn:incoming>
  <bpmn:outgoing>flow_to_gateway</bpmn:outgoing>
</bpmn:businessRuleTask>

<bpmn:exclusiveGateway id="route_gateway" name="Route?">
  <bpmn:incoming>flow_to_gateway</bpmn:incoming>
  <bpmn:outgoing>flow_auto</bpmn:outgoing>
  <bpmn:outgoing>flow_manager</bpmn:outgoing>
  <bpmn:outgoing>flow_finance</bpmn:outgoing>
</bpmn:exclusiveGateway>
```

```xml
<bpmn:sequenceFlow id="flow_auto" name="auto" sourceRef="route_gateway" targetRef="auto_approved">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">route == "auto"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
<bpmn:sequenceFlow id="flow_manager" name="manager" sourceRef="route_gateway" targetRef="approve_expense">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">route == "manager"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
<bpmn:sequenceFlow id="flow_finance" name="finance" sourceRef="route_gateway" targetRef="finance_approve_expense">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">route == "finance"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

The `auto` flow goes straight to an end event, `auto_approved`. The `manager` flow goes to
chapter 4's `approve_expense` task. The `finance` flow goes to a new user task,
`finance_approve_expense`. The conditions are Python expressions, which is what
SpiffWorkflow evaluates. The full file is
[`examples/expenses/chapter-05/approval.bpmn`](../../../examples/expenses/chapter-05/approval.bpmn);
`persist_expense` now flows to `route_expense`, and the diagram has a shape for each new
element.

The process graph names the two new tasks. The gateway gets no triples: nothing links to
it, and its conditions read a process variable, not the model.

```trig
    <https://example.org/expenses/approval_bpmn#route_expense> a proc:BusinessRuleTask ;
        rdfs:label "Route Expense" ;
        seam:inModel :approval_bpmn .
```

```trig
    <https://example.org/expenses/approval_bpmn#finance_approve_expense> a proc:UserTask ;
        rdfs:label "Finance Approve Expense" ;
        seam:inModel :approval_bpmn .
```

The seam that makes the task a decision is `seam:decidedBy`. The task reads the expense,
so the runtime knows which entity fills the table's inputs:

```trig
    # Process to decision: the business-rule task evaluates :approval_routing
    # on the stored expense. The decision reads the same shape.
    <https://example.org/expenses/approval_bpmn#route_expense>
        seam:decidedBy :approval_routing ;
        seam:reads :ExpenseShape .
    :approval_routing seam:reads :ExpenseShape ;
        seam:detailedBy :approval_dmn .
```

## Finance's form

A form completes at most one user task (ADR-0009), so the finance task cannot reuse
`:approve_form`. Give it its own form, with its own parameters bound to the same
`:decision` and `:comment`, and put it on the approvals page:

```trig
        ifml:contains :expense_details , :approve_form , :finance_approve_form ;
```

```trig
    # Finance's form for large expenses. A form completes at most one user
    # task (ADR-0009), so the finance task gets its own form and parameters.
    :finance_approve_form a ifml:Form ; rdfs:label "Finance Approve Expense" ;
        ifml:order 2 ;
        ifml:hasEvent :submit_finance_approval ;
        ifml:hasParameter :finance_decision_input , :finance_comment_input ;
        seam:inModel :expense_ifml .
```

The checkpoint has the parameters, the event and its navigation flow in full. The form
writes an `:ApprovalShape`, like the manager's, and its event submits to a new operation,
`:finance_approve_expense_op`, a POST to `/expenses/{expense}/finance-approval`. Add it to
the `seam:exposes` of `:expense_api` and the `seam:consumes` of `:employee_portal`, and
let it render `:expense_details` as the manager's operation does. The task itself follows
chapter 4's pattern:

```trig
    # The finance task, for the amounts the table routes to "finance".
    <https://example.org/expenses/approval_bpmn#finance_approve_expense>
        seam:reads :ExpenseShape ;
        seam:completedOn :finance_approve_form ;
        seam:writes :ApprovalShape .
```

Restart the viewer on your file. The badge is green, and the process view now draws the
gateway. **Route Approval** has a `seam:detailedBy` seam to the DMN model, so following it
opens the decision drawn from `approval.dmn`.

## Generate the app

Run the generators on the chapter 5 checkpoint:

```sh
python -m seams_gen fastapi examples/expenses/chapter-05/expenses.trig --out examples/expenses/chapter-05/generated
python -m seams_gen htmx examples/expenses/chapter-05/expenses.trig --out examples/expenses/chapter-05/generated/templates
```

Compare `expense_api.py` with chapter 4's. The only new handler is
`finance_approve_expense`, the completion route of the finance task. Nothing in the module
mentions amounts, thresholds or routes: `submit_expense` still validates and calls
`runtime.start_process`, and the runtime evaluates the table and follows the gateway. The
`htmx` generator adds `finance_approve_form.html`, the finance task's form for the inbox.

## Run it

Start the host on the chapter 5 files:

```sh
SEAMS_MODEL=examples/expenses/chapter-05/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-05/generated/templates \
SEAMS_DB=/tmp/expenses-05.sqlite \
SEAMS_DEV_USER=alice \
python -m seams_runtime.host --routes examples/expenses/chapter-05/generated/expense_api.py --port 8001
```

Submit three expenses, one per path:

```sh
curl -X POST http://localhost:8001/expenses/taxi -d "description=Taxi" -d amount=42.50 -d date=2026-10-01
curl -X POST http://localhost:8001/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02
curl -X POST http://localhost:8001/expenses/laptop -d "description=Laptop" -d amount=5000.00 -d date=2026-10-03
```

All three are stored and listed at <http://localhost:8001>. The host log shows each
instance running `route_expense` and `route_gateway`. The taxi's instance then runs to
`auto_approved` and finishes. The hotel's waits on `approve_expense`, and the laptop's on
`finance_approve_expense`.

Open <http://localhost:8001/tasks>. There are two cards, not three: **Approve Expense** for
the hotel and **Finance Approve Expense** for the laptop. Nobody has to approve the taxi.
Each card posts to its own route, so the manager's route cannot complete the finance task:

```sh
curl -i -X POST http://localhost:8001/expenses/laptop/approval -d decision=approved
```

The answer is `409 TaskNotOpen`: the laptop's instance never waits on `approve_expense`.
Now approve both cards in the browser, and both instances finish.

If you have the `sqlite3` command, you can see where each instance ended:

```sh
sqlite3 /tmp/expenses-05.sqlite "select correlation_key, status from workflow_state"
```

## Change the rule, not the code

Now the point of the chapter. Finance wants to see everything above 200. Edit the manager
rule in your `approval.dmn`:

```diff
-        <inputEntry id="rule_manager_amount"><text>&lt;= 1000</text></inputEntry>
+        <inputEntry id="rule_manager_amount"><text>&lt;= 200</text></inputEntry>
```

Run the two generator commands again and look at what changed:

```sh
git diff --stat examples/expenses/chapter-05/generated
git diff examples/expenses/chapter-05/generated
```

Every generated file changes only on its model-hash lines: the `model-hash` comment at
the top of each file, and in `expense_api.py` also the `MODEL_HASH` constant. The hash covers the TriG file and every file
it names with `seam:renderPayload`, so the generated code records which table it was made
for. No handler, template or route moved. The runtime refuses to run a module whose hash
does not match the mounted model, so a stale module cannot silently run against a new
table.

Restart the host with a fresh `SEAMS_DB` and submit the hotel again. This time it waits on
`finance_approve_expense`. The same amount takes another path, and the only thing you
edited is the table.

Put the threshold back to 1000 and regenerate when you are done, so your files match the
checkpoint. CI runs this experiment on a copy of the checkpoint
(`tests/test_expense_process_app.py`).

## When the table has no answer

The last rule, `-`, makes sure the table always produces a route. Without it, an amount
above 1000 matches no rule, the decision produces no `Route`, and the instance fails with
a `ResolutionError` naming the decision `approval_routing`. A route that no gateway
condition accepts, for example a rule that outputs `"board"`, fails the instance at the
gateway too. In both cases the instance is marked `failed` with the error recorded, and it
leaves no task open in the inbox.

## Checkpoint

Your files should now match
[`examples/expenses/chapter-05/expenses.trig`](../../../examples/expenses/chapter-05/expenses.trig),
[`examples/expenses/chapter-05/approval.bpmn`](../../../examples/expenses/chapter-05/approval.bpmn)
and
[`examples/expenses/chapter-05/approval.dmn`](../../../examples/expenses/chapter-05/approval.dmn),
and the generated code
[`examples/expenses/chapter-05/generated/`](../../../examples/expenses/chapter-05/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-04/expenses.trig examples/expenses/chapter-05/expenses.trig
```

Next, [chapter 6](./06-lifecycle) gives an expense a lifecycle, so the process can only
move it along legal transitions.
