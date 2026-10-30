# 8. Growing up

At the end of this chapter paying an expense sets off a second process that nobody
starts by hand. When finance records a payment, the approval process ends by publishing
an event on a channel. A payout process subscribes to that channel, so the runtime starts
it, and it runs to its end with nobody taking part. It has its own DMN decision, which
chooses between adding the payment to the next batch and sending it now. It also has its
own lifecycle for the payment, and finance watches the result on a second screen model,
the finance console. Then you run the whole system with `docker compose up`, and the
complexity check that the tutorial was building towards passes.

The model ends with two models each of BPMN, DMN, IFML and statechart. That makes it the
second worked example this project needed, and the last section explains what it is for.

## The payouts channel

A channel is a `comm:Channel` in the seams graph, beside the operations. Its label names
the event:

```trig
    :payouts a comm:Channel ; rdfs:label "payout requested" ;
        comm:transport comm:SSE ;
        comm:eventName "payout" ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses/{expense}/payouts" ;
                    hydra:mapping [ a hydra:IriTemplateMapping ;
                                    hydra:variable "expense" ;
                                    hydra:property :id ] ] .
```

The API exposes the channel, so it needs a transport and a path. The generated app serves
it as a server-sent event stream, scoped to one expense, so a browser can watch that
expense's payouts. Add `:payouts` to the `seam:exposes` of `:expense_api`. While you are
there, add the payout process to its `seam:executes`. The process is described below.

```trig
    :expense_api seam:exposes :submit_expense_op , :list_expenses_op , :approve_expense_op ,
            :finance_approve_expense_op , :expense_details_op , :awaiting_approval_op ,
            :pay_expense_op , :list_payments_op , :paid_expenses_op , :payouts ;
        seam:executes :approval_process , :payout_process ;
        seam:deployedTo :app01 .
```

The two read operations and `seam:deployedTo` come later in this chapter.

## The approval publishes

In chapter 7 the paid path ended on a plain end event, `approved_end`. Make it a message
end event. In `approval.bpmn` it gains a message event definition:

```xml
<!-- A message end event: the graph says it seam:publishesTo :payouts (ADR-0010). -->
<bpmn:endEvent id="approved_end" name="Paid">
  <bpmn:incoming>flow_to_approved_end</bpmn:incoming>
  <bpmn:messageEventDefinition id="approved_end_msg" />
</bpmn:endEvent>
```

The process graph types it, and the seams graph says where it publishes:

```trig
    <https://example.org/expenses/approval_bpmn#approved_end> a proc:MessageThrowEvent ;
        rdfs:label "Paid" ;
        seam:inModel :approval_bpmn .
```

```trig
    <https://example.org/expenses/approval_bpmn#approved_end> seam:publishesTo :payouts .
```

The rejected end stays a plain end event, so a rejected expense publishes nothing.

## The payout process

The payout is a second BPMN model, in its own graph and its own file,
[`payout.bpmn`](../../../examples/expenses/chapter-08/payout.bpmn). It starts on a
message start event. It schedules the payment, asks a decision how to pay, and then
either adds the payment to a batch or sends it now:

```xml
<!-- A message start event: the graph says it seam:subscribesTo :payouts (ADR-0010). -->
<bpmn:startEvent id="payout_requested" name="Payout Requested">
  <bpmn:outgoing>flow_to_schedule</bpmn:outgoing>
  <bpmn:messageEventDefinition id="payout_requested_msg" />
</bpmn:startEvent>
```

```xml
<bpmn:exclusiveGateway id="method_gateway" name="Method?">
  <bpmn:incoming>flow_to_gateway</bpmn:incoming>
  <bpmn:outgoing>flow_batch</bpmn:outgoing>
  <bpmn:outgoing>flow_now</bpmn:outgoing>
</bpmn:exclusiveGateway>
```

```xml
<bpmn:sequenceFlow id="flow_batch" name="batch" sourceRef="method_gateway" targetRef="add_to_batch">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">method == "batch"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
<bpmn:sequenceFlow id="flow_now" name="now" sourceRef="method_gateway" targetRef="send_now">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">method == "now"</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

Declare it in a new process graph. The start event is a `proc:MessageCatchEvent`:

```trig
<urn:seams:graph:model:payout_bpmn> {

    :payout_bpmn a seam:Model ; rdfs:label "Expense Payout (BPMN)" .

    # No person takes part: the process starts from the channel and runs to
    # its end. The gateway on "method" is in payout.bpmn only.
    :payout_process a proc:Process ; rdfs:label "Expense Payout" ;
        seam:inModel :payout_bpmn .

    <https://example.org/expenses/payout_bpmn#payout_requested> a proc:MessageCatchEvent ;
        rdfs:label "Payout Requested" ;
        seam:inModel :payout_bpmn .
```

The graph goes on with the four tasks, `schedule_payout` and `add_to_batch` and
`send_now` as `proc:ServiceTask` and `choose_payout` as `proc:BusinessRuleTask`. Give the
model its notation and payload in the seams graph, as chapter 4 did for the approval:

```trig
    :payout_bpmn seam:notation seam:BPMN ;
        seam:renderPayload <payout.bpmn> .
```

### Why it needs no button

Every process so far was started by a person: the Submit Expense event
`seam:triggers` the approval process. The payout process has no such event. Its start
event subscribes to the channel instead:

```trig
    :payout_process seam:detailedBy :payout_bpmn ;
        proc:correlationKey :expense .
    <https://example.org/expenses/payout_bpmn#payout_requested> seam:subscribesTo :payouts .
```

[ADR-0010](/adr/0010-channel-started-processes) calls such a process
**channel-started**. When a message throw event publishes on `:payouts`, the runtime
starts one instance of every process whose start event subscribes to it. The new
instance gets the publisher's correlation key, here the expense, and a copy of the
expense and the payment the approval instance holds, with their statuses. Nobody clicks
anything, so no screen and no route starts it, and the generator writes no route for it.
It also has no policy: a policy guards something a person does.

The approval instance does not wait for the payout. It ends, and the payout runs as its
own instance. A slow payout cannot hold up an approval.

## The payout decision

The second DMN table, [`payout.dmn`](../../../examples/expenses/chapter-08/payout.dmn),
reads the amount. Up to 500 goes into the batch, and anything else is sent now:

```xml
<rule id="rule_batch">
  <inputEntry id="rule_batch_amount"><text>&lt;= 500</text></inputEntry>
  <outputEntry id="rule_batch_out"><text>"batch"</text></outputEntry>
</rule>
<rule id="rule_now">
  <inputEntry id="rule_now_amount"><text>-</text></inputEntry>
  <outputEntry id="rule_now_out"><text>"now"</text></outputEntry>
</rule>
```

Its graph binds the table's input and output as chapter 5's did. The `Method` column is
copied into the process variable `method`, which the gateway reads:

```trig
    :payout_method a dec:Decision ; rdfs:label "Choose Payout Method" ;
        dec:payloadElement "payout_method" ;
        dec:input [ a dec:InputBinding ; dec:variable "amount" ; dec:fromPath :amount ] ;
        dec:output [ a dec:OutputBinding ; dec:variable "Method" ; dec:processVariable "method" ] ;
        seam:inModel :payout_dmn .
```

The business-rule task asks it:

```trig
    <https://example.org/expenses/payout_bpmn#choose_payout>
        seam:decidedBy :payout_method ;
        seam:reads :ExpenseShape .
    :payout_method seam:reads :ExpenseShape ;
        seam:detailedBy :payout_dmn .
```

## The payment lifecycle

A payment now has a lifecycle of its own. Finance records it, the payout schedules it,
and it ends either batched or sent:

```trig
    :payment_lifecycle a state:StateMachine , seam:Model ;
        rdfs:label "Payment Lifecycle" ;
        state:initial :s_recorded ;
        state:hasState :s_recorded , :s_scheduled , :s_batched , :s_sent ;
        state:final :s_batched , :s_sent ;
        state:hasTransition :t_schedule , :t_batch , :t_send .
```

```trig
    :t_schedule a state:Transition ; state:from :s_recorded  ; state:to :s_scheduled ; state:trigger "schedule" ; seam:inModel :payment_lifecycle .
    :t_batch    a state:Transition ; state:from :s_scheduled ; state:to :s_batched   ; state:trigger "batch"    ; seam:inModel :payment_lifecycle .
    :t_send     a state:Transition ; state:from :s_scheduled ; state:to :s_sent      ; state:trigger "send"     ; seam:inModel :payment_lifecycle .
```

`PaymentShape` gets a `status` the runtime sets, as `ExpenseShape` did in chapter 6, and
names its lifecycle:

```trig
        sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 2 ;
                      sh:in ( "recorded" "scheduled" "batched" "sent" ) ] ;
```

```trig
    :PaymentShape seam:lifecycle :payment_lifecycle .
```

A payment is stored `recorded` when `pay_expense` writes it, because that is the
lifecycle's initial state. Each payout task fires one transition and writes the payment
back, so every edge of the new statechart leads back to a task:

```trig
    <https://example.org/expenses/payout_bpmn#schedule_payout>
        seam:reads :PaymentShape ;
        seam:writes :PaymentShape ;
        seam:fires :t_schedule .
```

```trig
    <https://example.org/expenses/payout_bpmn#add_to_batch>
        seam:writes :PaymentShape ;
        seam:fires :t_batch .
    <https://example.org/expenses/payout_bpmn#send_now>
        seam:writes :PaymentShape ;
        seam:fires :t_send .
```

The stored payment keeps its id, so the payout updates the payment finance recorded and
does not store a second one.

## The finance console

Finance needs to see the payments. That is a second IFML model with one page:

```trig
    :finance_console a seam:Model , ifml:InteractionModel ;
        rdfs:label "Finance Console" ;
        ifml:contains :payouts_page .

    # Finance's page. It holds no task form, so the generated app serves it
    # as a page at its ifml:path, as it serves the landmark page.
    :payouts_page a ifml:ViewContainer ; rdfs:label "Payouts" ;
        ifml:path "/payouts" ;
        ifml:title "Payouts"@en ;
        ifml:contains :payment_list , :paid_expenses ;
        seam:inModel :finance_console .
```

The page holds two read-only blocks, `:payment_list` and `:paid_expenses`. Each reads a
shape and is rendered by a GET operation, as the expense list was in chapter 3:

```trig
    :payment_list seam:reads :PaymentShape .
    :paid_expenses seam:reads :ExpenseShape .
```

```trig
    :list_payments_op a hydra:Operation ; rdfs:label "List Payments" ;
        hydra:method "GET" ;
        seam:returnsShape :PaymentShape ;
        seam:mediaKind seam:UIFragment ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/payments" ] .
```

```trig
    :list_payments_op seam:rendersComponent :payment_list .
    :paid_expenses_op seam:rendersComponent :paid_expenses .
```

`:paid_expenses_op` is the same at `/payouts/expenses`, returning `ExpenseShape`. The
portal presents both interaction models and consumes the two new operations:

```trig
    :employee_portal seam:presents :expense_ifml , :finance_console ;
        seam:consumes :submit_expense_op , :list_expenses_op , :approve_expense_op ,
            :finance_approve_expense_op , :expense_details_op , :awaiting_approval_op ,
            :pay_expense_op , :list_payments_op , :paid_expenses_op ;
        seam:deployedTo :web01 .
```

## Deploy facts

To run the system under Docker Compose, the architecture graph has to say what each
container runs. Add the deploy prefix:

```trig
@prefix deploy: <https://w3id.org/seams/deploy#> .
```

Then give each container an image, its ports and its start order. The portal publishes
port 8080 on the host and starts after the API:

```trig
    :employee_portal a arch:Container ; rdfs:label "Employee Portal" ;
        arch:technology "htmx + server-rendered fragments" ;
        arch:dependsOn :expense_api ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "ghcr.io/example/expense-portal" ;
                          deploy:version "latest" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ; deploy:publishedPort 8080 ] ;
        deploy:dependsOn :expense_api ;
        seam:inModel :expense_architecture .
```

The API gets an image and a port too, but publishes nothing, so it is only reachable
from inside the stack. It runs in the one environment, `:prod`:

```trig
        deploy:placement [ a deploy:PlacementPolicy ;
                           deploy:targetEnvironment :prod ] ;
```

The `seam:deployedTo` edges you saw above put the portal on `:web01` and the API on
`:app01`.

## Where the data lives

So far the model says nothing about where the expenses are kept. The runtime keeps them
in a SQLite file it chooses itself, and a reader of the model cannot tell. Three facts
from [ADR-0011](/adr/0011-storage-resolution) put the store in the model.

First, the store is a container like any other. `deploy:storeKind` says what kind of
store it is, one of `deploy:PostgreSQL` and `deploy:SQLite`. It runs the `postgres:16`
image, keeps its data on a named volume and reports ready through `pg_isready`:

```trig
    # Where the data lives: a PostgreSQL store with its own volume.
    :expense_db a arch:Container ; rdfs:label "Expense Store" ;
        arch:technology "PostgreSQL" ;
        deploy:storeKind deploy:PostgreSQL ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "postgres" ;
                          deploy:version "16" ] ;
        deploy:configuration [ a deploy:Configuration ;
                               deploy:binding [ deploy:key "POSTGRES_DB" ;
                                                deploy:value "expenses" ] ] ;
        deploy:volume [ a deploy:Volume ;
                        deploy:volumeName "expense_db_data" ;
                        deploy:mountPath "/var/lib/postgresql/data" ] ;
        deploy:healthcheck [ a deploy:Healthcheck ;
                             deploy:probe "pg_isready -U postgres" ;
                             deploy:interval "5s" ] ;
        seam:inModel :expense_architecture .
```

Add it to `:expense_system`'s `arch:contains`, and give it a node of its own in `:prod`:

```trig
    :prod a arch:Environment ; rdfs:label "Production" ;
        arch:contains :web01 , :app01 , :db01 ;
        seam:inModel :expense_architecture .
```

Second, the API reaches the store through a connection string. It is a secret, so the
binding names a secret rather than a value, and `deploy:connectsTo` says which store
the secret leads to:

```trig
        arch:dependsOn :expense_db ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "ghcr.io/example/expense-api" ;
                          deploy:version "0.8.0" ] ;
        # The connection string is a secret; deploy:connectsTo says which
        # store it reaches, so no key-name convention is needed (ADR-0011).
        deploy:configuration [ a deploy:Configuration ;
                               deploy:binding [ deploy:key "DATABASE_URL" ;
                                                deploy:secretRef <https://secrets.example.org/expenses/prod/database-url> ;
                                                deploy:secretName "expenses-prod-database-url" ;
                                                deploy:connectsTo :expense_db ] ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ] ;
        deploy:dependsOn :expense_db ;
```

The key is `DATABASE_URL`. The chat app calls its key `DB_URL`, and both are fine:
nothing reads the store from the key's name. `deploy:connectsTo` is what links the
binding to the store, so a model can keep whatever name its image already expects.
That is why this chapter picks a different name on purpose.

Third, each shape says where its rows live, in the seams graph next to the store's
`seam:deployedTo`:

```trig
    :expense_db seam:deployedTo :db01 .

    # Data to architecture (ADR-0011): where each shape's rows live.
    :ExpenseShape seam:storedIn :expense_db .
    :ApprovalShape seam:storedIn :expense_db .
    :PaymentShape seam:storedIn :expense_db .
```

Now the model answers "what breaks if `db01` goes away?" all the way down to the data.
The impact query, `docs/queries/impact-of-node.rq` on the [query reference](/reference/queries), returns the store, the API and the portal above it, both
processes the API runs, and the three shapes. In the viewer, each shape's inspector
shows a "stored in" edge to `:expense_db`.

The runtime does not use the declared store yet. It still keeps its rows in SQLite, and
a later release switches it to the store the model names.

## Generate the app

Run the generators on the chapter 8 checkpoint:

```sh
python -m seams_gen fastapi examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08/generated
python -m seams_gen htmx examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08/generated/templates
```

`expense_api.py` gains the two read routes, `list_payments` and `paid_expenses`, and the
`payouts` event stream. It gains no route for the payout process. The templates gain the
`/payouts` page, `payouts_page.html`, and its two partials. The host serves that page
the way it serves the landmark page, because it has an `ifml:path` and holds no task
form. The full list is in the
[generated README](../../../examples/expenses/chapter-08/generated/README.md).

The compose generator writes `compose.yaml` from the deploy facts:

```sh
python -m seams_gen compose examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08
```

## Run it in process

Start the host on the chapter 8 files, with identities from the headers as in chapter 7:

```sh
SEAMS_MODEL=examples/expenses/chapter-08/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-08/generated/templates \
SEAMS_DB=/tmp/expenses-08.sqlite \
python -m seams_runtime.host --routes examples/expenses/chapter-08/generated/expense_api.py --port 8001
```

Alice submits the hotel, Bob approves it and Carol pays it, the same three requests as
in chapter 7:

```sh
curl -X POST http://localhost:8001/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02 \
  -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: employee"
curl -X POST http://localhost:8001/expenses/hotel/approval -d decision=approved \
  -H "X-Forwarded-User: bob" -H "X-Forwarded-Groups: manager"
curl -X POST http://localhost:8001/expenses/hotel/payment -d reference=PAY-0042 -d paid_on=2026-10-05 \
  -H "X-Forwarded-User: carol" -H "X-Forwarded-Groups: finance"
```

If a task request returns 409 `TaskNotOpen`, the process has not reached that task yet,
so send it again. Carol's request is the last thing anyone does. The approval
instance ends on `approved_end` and publishes on `:payouts`, and the host log shows a
second workflow running and completing. Ask for the payments. Reads have no policy, so
this needs no identity:

```sh
curl http://localhost:8001/payments
```

```
<li class="payment">
  <span class="reference">PAY-0042</span>
  <span class="paid_on">2026-10-05</span>
  <span class="status">batched</span>
</li>
```

The hotel cost 250.00, so `payout.dmn` answered `batch`, and the payment went from
`recorded` through `scheduled` to `batched`. Pay a 750.00 expense the same way and it
ends `sent`. Reject one, or approve one and leave it unpaid, and no payout starts. The
finance console is at <http://localhost:8001/payouts>, with the payments above the
expenses they pay.

## Run it with docker compose

`compose.yaml` is generated, so it holds only what the model says. The repository keeps
a hand-written
[`compose.override.yaml`](../../../examples/expenses/chapter-08/compose.override.yaml)
beside it. The override builds the runtime image with the chapter 8 code, makes the
portal a Caddy reverse proxy in front of the API, adds a volume for the runtime's SQLite
file and names the project `seams-expenses`. The generated file also has an `expense_db`
service from the store's deploy facts. The override gives it a dev-only
`POSTGRES_PASSWORD`, and points the `database_url` secret at a committed placeholder,
`docker/local-secrets/expense_database_url`, because the generated secret is a swarm
secret that plain compose cannot create. The API does not read that secret yet. Pass
both files from the repository root:

```sh
docker compose -f examples/expenses/chapter-08/compose.yaml -f examples/expenses/chapter-08/compose.override.yaml up --build
```

The portal is now at <http://localhost:8080>. There is no static dev user in the stack,
so Caddy passes the `X-Forwarded-User` and `X-Forwarded-Groups` headers through to the
API. Run the three `curl` requests above against port 8080, and then
`curl http://localhost:8080/payouts` shows the payment `batched` and the expense
`paid`. A request with no identity headers is a 401. Keep the stack on localhost,
because anyone who can reach it can claim any role. Stop it with
`docker compose -f examples/expenses/chapter-08/compose.yaml -f examples/expenses/chapter-08/compose.override.yaml down -v`.

## Measure it

The tutorial started from a question: is there a model large enough to need more than
the descent the viewer already offers? `python -m seams_gen.complexity` answers it with
three measurements:

```sh
python -m seams_gen.complexity examples/expenses/chapter-08/expenses.trig
```

```
models per notation:
  BPMN: 2
  DMN: 2
  IFML: 2
  Statechart: 2
  C4: 1
  ShapeGraph: 1
most reached (distinct models):
  ExpenseShape: 6
  PaymentShape: 4
  payouts: 3
  submit_expense_op: 3
  ApprovalShape: 2
seam edges: 115 (reported, not gated)
PASS
```

It passes when at least 3 notations have two or more models, and some element is reached
from at least 5 distinct models. This model has 4 such notations. `ExpenseShape` is
reached from 6 models: both screen models, both processes and both decisions. The seam-edge count, 115, is reported but not gated. Four of those edges are the storage facts above. The chat app scores 0 and
3 and fails, because it has one model per notation. The command exits 0 on a pass, so
CI can gate on it, and `tests/test_complexity.py` pins these numbers.

## Open it in the viewer

Start the viewer on the finished model:

```sh
SEAMS_MODEL=examples/expenses/chapter-08/expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

The descent still works, but it now has choices to make. The portal presents two screen
models, the API runs two processes, and `ExpenseShape` is reached from six models. Follow
the hotel's path from the Submit Expense event to the batched payment and you cross the
approval process, the channel, the payout process, its decision and the payment
lifecycle. Each one is a separate view. Questions like this are what layer mode, item 11
in the [backlog](/backlog) and slice M008/S03, is for. That slice opens by running the
complexity check above on this model.

## Known limitations

- **The bus is in process.** The approval instance and the payout instance run in the
  same runtime, so the payout cannot move to a separate worker container yet.
  [ADR-0010](/adr/0010-channel-started-processes) defers a cross-container broker.
- **One environment.** The compose generator places containers by `seam:deployedTo` and
  has no notion of a second environment, so the model has `:prod` and no staging.
- **No timer starts.** A process can start from a UI event or a channel, but not on a
  schedule. A nightly payout batch would need one. There are no intermediate message
  catch events either.

CI checks every step of this chapter. `tests/test_expense_payout.py` runs both processes
in process on both payout paths, `tests/test_expense_compose.py` checks that the
committed `compose.yaml` is current, `tests/test_expense_e2e.py` runs the docker compose
stack in CI's `tutorial-e2e` job, and `tests/test_complexity.py` pins the measurement.

## Checkpoint

Your files should now match
[`examples/expenses/chapter-08/expenses.trig`](../../../examples/expenses/chapter-08/expenses.trig),
[`approval.bpmn`](../../../examples/expenses/chapter-08/approval.bpmn),
[`payout.bpmn`](../../../examples/expenses/chapter-08/payout.bpmn) and
[`payout.dmn`](../../../examples/expenses/chapter-08/payout.dmn) (`approval.dmn` is
unchanged), and the generated code
[`examples/expenses/chapter-08/generated/`](../../../examples/expenses/chapter-08/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-07/expenses.trig examples/expenses/chapter-08/expenses.trig
```

That is the whole tutorial. You started from an empty file and now have an architecture,
two screen models, two processes, two decisions, two lifecycles, roles and a deployment.
Every one of them is in one TriG file, and every line of generated code follows from it.
