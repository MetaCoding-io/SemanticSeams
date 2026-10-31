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
port 8080 on the host and starts after the API. It has no code of its own: the API's
host serves the pages, including the event streams, so the portal runs the stock
`caddy` image, and `deploy:proxies` names the container it forwards every request to.
The compose generator turns that fact into Caddy's `reverse-proxy` command. Its
`deploy:healthcheck` probes the API's `/healthz` through the proxy:

```trig
    :employee_portal a arch:Container ; rdfs:label "Employee Portal" ;
        arch:technology "htmx + server-rendered fragments" ;
        arch:dependsOn :expense_api ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "caddy" ;
                          deploy:version "2-alpine" ] ;
        deploy:proxies :expense_api ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ; deploy:publishedPort 8080 ] ;
        deploy:dependsOn :expense_api ;
        deploy:healthcheck [ a deploy:Healthcheck ;
                             deploy:probe "wget -q -O /dev/null http://127.0.0.1:8000/healthz" ;
                             deploy:interval "5s" ] ;
```

The API gets an image and a port too, but publishes nothing, so it is only reachable
from inside the stack. Its placement names the `:production` environment:

```trig
        deploy:placement [ a deploy:PlacementPolicy ;
                           deploy:targetEnvironment :production ] ;
```

The `seam:deployedTo` edges you saw above put the portal on `:web01` and the API on
`:app01`.

## Where the data lives

So far the model says nothing about where the expenses are kept. The runtime keeps them
in a SQLite file it chooses itself, and a reader of the model cannot tell. Three facts
from [ADR-0011](/adr/0011-storage-resolution) put the store in the model.

First, the store is a container like any other. `deploy:storeKind` says what kind of
store it is, one of `deploy:PostgreSQL` and `deploy:SQLite`. It runs the `postgres:16`
image, keeps its data on a named volume and reports ready through `pg_isready`. The
`postgres` image refuses to start without a password, so the store's password is a
secret binding too:

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
                                                deploy:value "expenses" ] ;
                               deploy:binding [ deploy:key "POSTGRES_PASSWORD" ;
                                                deploy:secretRef <https://secrets.example.org/expenses/prod/postgres-password> ;
                                                deploy:secretName "expenses-prod-postgres-password" ] ] ;
        deploy:volume [ a deploy:Volume ;
                        deploy:volumeName "expense_db_data" ;
                        deploy:mountPath "/var/lib/postgresql/data" ] ;
        deploy:healthcheck [ a deploy:Healthcheck ;
                             deploy:probe "pg_isready -U postgres" ;
                             deploy:interval "5s" ] ;
```

Add it to `:expense_system`'s `arch:contains`, and give it a node of its own in
`:production`:

```trig
    :production a arch:Environment ; rdfs:label "Production" ;
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

The runtime uses the declared store. When the model loads it reads these three facts,
opens PostgreSQL at the URL in `DATABASE_URL` (or the file `DATABASE_URL_FILE` names),
and keeps the expenses, approvals, payments and process instances there. `GET /healthz`
reports `"kind": "postgresql"`. Drop one of the facts, say the `seam:storedIn` on
`:PaymentShape`, and the host refuses to start with a `ResolutionError` naming
`:PaymentShape` and `seam:storedIn`.

## Two environments

Everything so far describes production: images from a registry, secrets from a secret
store, containers placed on named nodes. A laptop has none of those. Rather than keep a
hand-written compose file for it, the model declares a second environment
([ADR-0015](/adr/0015-environments)). It contains no nodes, so nothing is placed:

```trig
    :development a arch:Environment ; rdfs:label "Development" ;
        seam:inModel :expense_architecture .
```

A container says what differs in one environment with a `deploy:override`. The override
names its `deploy:environment` and carries replacement facts with the same predicates.
In development the API builds its image from this checkout, and reads the connection
string from a committed file instead of a secret store. A replaced `deploy:artifact`
replaces the whole artifact; bindings merge by `deploy:key`, so the override restates
`DATABASE_URL` with a `deploy:secretFile`. It must still `deploy:connectsTo` the same
store, which SHACL checks:

```trig
        deploy:override [ a deploy:Override ;
            deploy:environment :development ;
            deploy:artifact [ a deploy:Artifact ;
                              deploy:reference "seams/expense-api" ;
                              deploy:version "local" ;
                              deploy:build [ a deploy:Build ;
                                             deploy:context "../../.." ;
                                             deploy:dockerfile "docker/runtime.Dockerfile" ] ] ;
            deploy:configuration [ a deploy:Configuration ;
                deploy:binding [ deploy:key "DATABASE_URL" ;
                                 deploy:secretFile "../../../docker/local-secrets/expense_database_url" ;
                                 deploy:connectsTo :expense_db ] ] ] ;
```

The store gets a fixed development password, the one that committed URL uses:

```trig
        deploy:override [ a deploy:Override ;
            deploy:environment :development ;
            deploy:configuration [ a deploy:Configuration ;
                deploy:binding [ deploy:key "POSTGRES_PASSWORD" ; deploy:value "seams-dev" ] ] ] ;
```

Paths in the model are relative to the model file. A container with no override for an
environment uses its shared facts there, so the portal is the same Caddy proxy in both.

## Generate the app

Run the generators the chapter 8 checkpoint's `seams.toml` names:

```sh
seams generate --project examples/expenses/chapter-08
```

`expense_api.py` gains the two read routes, `list_payments` and `paid_expenses`, and the
`payouts` event stream. It gains no route for the payout process. The templates gain the
`/payouts` page, `payouts_page.html`, and its two partials. The host serves that page
the way it serves the landmark page, because it has an `ifml:path` and holds no task
form. The full list is in the
[generated README](../../../examples/expenses/chapter-08/generated/README.md).

The same command also writes one compose file per environment from the deploy facts,
`compose.development.yaml` and `compose.production.yaml`, because chapter 8's
[`seams.toml`](../../../examples/expenses/chapter-08/seams.toml) names a third
generator, `compose`, with `out = "."`. Each file's header names its environment and
the model hash.

## Run it in process

Start the host on the chapter 8 files, with identities from the headers as in chapter 7.
The model now asks for PostgreSQL, which a quick run on a laptop does not have, so
`SEAMS_STORE_OVERRIDE=sqlite` keeps the rows in the `SEAMS_DB` file instead. The host
logs a warning and `/healthz` reports `"override": true`. To use a local PostgreSQL
instead, drop both lines and set `DATABASE_URL` to its URL.

```sh
SEAMS_MODEL=examples/expenses/chapter-08/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-08/generated/templates \
SEAMS_STORE_OVERRIDE=sqlite \
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

[`compose.development.yaml`](../../../examples/expenses/chapter-08/compose.development.yaml)
is the development environment, generated, with nothing written by hand. It builds the
runtime image with the chapter 8 code (the generator adds the `SEAMS_APP_DIR` and
`SEAMS_ROUTES_FILE` build args), runs the portal as a Caddy reverse proxy in front of
the API, and names the project `expense_system` after the `arch:System`, so it never
shares volumes with the chat app. Every container with a healthcheck makes the
containers that depend on it wait until it is healthy, so the API starts once the
database accepts connections. The `database_url` secret is the committed dev URL,
`docker/local-secrets/expense_database_url` (set `DATABASE_URL_FILE` on the host to use
another file). The API reads that secret through `DATABASE_URL_FILE` inside the
container and keeps its data in `expense_db`, so no SQLite volume is needed. Run it from
the repository root:

```sh
docker compose -f examples/expenses/chapter-08/compose.development.yaml up --build
```

The portal is now at <http://localhost:8080>. There is no static dev user in the stack,
so Caddy passes the `X-Forwarded-User` and `X-Forwarded-Groups` headers through to the
API. Run the three `curl` requests above against port 8080, and then
`curl http://localhost:8080/payouts` shows the payment `batched` and the expense
`paid`. A request with no identity headers is a 401. Keep the stack on localhost,
because anyone who can reach it can claim any role.

To see where the data landed, ask `expense_db` for the shape of every entity stored under
the `hotel` correlation key:

```sh
docker compose -f examples/expenses/chapter-08/compose.development.yaml exec -T expense_db psql -U postgres -d expenses -tAc "SELECT shape FROM entities WHERE correlation_key = 'hotel'"
```

It lists `https://example.org/expenses/ExpenseShape` along with the approval and
payment rows, and `curl http://localhost:8080/healthz` reports the store as
`"kind": "postgresql"`, `"declared": "PostgreSQL"` and `"override": false`.
`tests/test_expense_e2e.py` runs both checks against chapter 9's stack, which is this one
with a hand-written handler added. Optionally,
`seams status --project examples/expenses/chapter-08 --env development` reads the same
`/healthz` through the `development` environment in `seams.toml` and prints
`expense_api current` when the running API is on this chapter's model
([seams status](/reference/seams-cli#seams-status)). Stop the stack with
`docker compose -f examples/expenses/chapter-08/compose.development.yaml down -v`.

`compose.production.yaml` is the same system as production runs it: the registry
images, external swarm secrets for the connection string and the store's password, and
placement constraints for `web01`, `app01` and `db01`.

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

### One diagram per path

The approval process has exclusive gateways, so `seams sequence :submit_expense` derives
one sequence diagram per path rather than one diagram with `alt` blocks: five here. The
viewer's Sequences section on the Submit Expense event lists all five, each with its
gaps. Two of them, the automatic approval and the manager's approval:

<<< @/generation/sequences/expenses/submit_expense--auto.mmd{mermaid}

<<< @/generation/sequences/expenses/submit_expense--manager--approved.mmd{mermaid}

The rest are in [`docs/generation/sequences/expenses`](../../generation/sequences/expenses).

## Known limitations

- **The bus is in process.** The approval instance and the payout instance run in the
  same runtime, so the payout cannot move to a separate worker container yet.
  [ADR-0010](/adr/0010-channel-started-processes) defers a cross-container broker.
- **The production images do not exist.** `ghcr.io/example/expense-api` is a
  placeholder, so only the development file runs here. Publishing images tagged with the
  model hash is planned.
- **No timer starts.** A process can start from a UI event or a channel, but not on a
  schedule. A nightly payout batch would need one. There are no intermediate message
  catch events either.

CI checks every step of this chapter. `tests/test_expense_payout.py` runs both processes
in process on both payout paths, `tests/test_expense_compose.py` checks that the
committed compose files are current and that the development file needs no override, `tests/test_expense_e2e.py` runs the same docker compose
stack, with chapter 9's handler, in CI's `tutorial-e2e` job, and `tests/test_complexity.py` pins the measurement.

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

You started from an empty file and now have an architecture, two screen models, two
processes, two decisions, two lifecycles, roles and a deployment. Every one of them is in
one TriG file, and every line of generated code follows from it. The last chapter,
[Hand-written code](./09-hand-written-code), adds the one thing that does not: a
function you write yourself, behind a service task.
