# Expense approval tutorial checkpoints

This directory holds the model at the end of each chapter of the build-along
expense approval tutorial ([docs/tutorials/expenses/](../../docs/tutorials/expenses/index.md)).
If you get lost, copy the checkpoint for the chapter you are on and carry on
from there.

## Layout

Each chapter has its own directory with one file of the same name:

```
examples/expenses/
  chapter-01/expenses.trig   architecture: the system and its two containers (C4)
  chapter-02/expenses.trig   data: chapter 1 plus the ExpenseShape shape graph
  chapter-03/expenses.trig   screens: chapter 2 plus the IFML page, its two operations and their seams
  chapter-03/generated/      the route module and templates generated from chapter 3
  chapter-03/seed.json       an empty seed ({}) for the runtime image
  chapter-04/expenses.trig   process: chapter 3 plus the approval BPMN process, its approval user task,
                             the approvals page and the ApprovalShape
  chapter-04/approval.bpmn   the BPMN file the approval_bpmn model renders and the runtime executes
  chapter-04/generated/      the route module (submit starts the process, approve completes the task)
                             and templates generated from chapter 4
  chapter-04/seed.json       an empty seed ({})
  chapter-05/expenses.trig   rules: chapter 4 plus the approval_dmn decision model, the route_expense
                             business-rule task, the finance approval task and its form and operation
  chapter-05/approval.bpmn   chapter 4's process plus route_expense and a gateway with auto,
                             manager and finance paths
  chapter-05/approval.dmn    the routing table: up to 100 auto, up to 1000 manager, above that finance
  chapter-05/generated/      the route module (chapter 4's plus the finance completion route)
                             and templates generated from chapter 5
  chapter-05/seed.json       an empty seed ({})
  chapter-06/expenses.trig   lifecycle: chapter 5 plus the expense_lifecycle statechart, the
                             seam:fires edges, the record_approval and record_rejection tasks and the
                             awaiting_approval block guarded by seam:visibleWhen
  chapter-06/approval.bpmn   chapter 5's process plus a decision gateway after both approval tasks
                             and the record_approval and record_rejection service tasks
  chapter-06/approval.dmn    chapter 5's routing table, unchanged
  chapter-06/generated/      the route module (chapter 5's plus the awaiting-approval route)
                             and templates generated from chapter 6
  chapter-06/seed.json       an empty seed ({})
  chapter-07/expenses.trig   permissions: chapter 6 plus the employee, manager and finance parties,
                             the submit and three task policies, the PaymentShape and the finance
                             pay_expense task with its payment form and operation
  chapter-07/approval.bpmn   chapter 6's process plus the pay_expense user task after record_approval
  chapter-07/approval.dmn    chapter 6's routing table, unchanged
  chapter-07/generated/      the route module (chapter 6's plus the payment completion route, and the
                             employee policy on the submit route) and templates generated from chapter 7
  chapter-07/seed.json       an empty seed ({})
  chapter-08/expenses.trig   growing up: chapter 7 plus the payouts channel, the payout_bpmn process it
                             starts, the payout_dmn decision, the payment_lifecycle statechart and the
                             finance_console interaction model with its /payouts page
  chapter-08/approval.bpmn   chapter 7's process with the paid end event made a message end event
                             that publishes on payouts
  chapter-08/approval.dmn    chapter 7's routing table, unchanged
  chapter-08/payout.bpmn     the payout process: a message start event, schedule_payout, the
                             choose_payout business-rule task and a gateway to add_to_batch or send_now
  chapter-08/payout.dmn      the payout method table: up to 500 batch, above that now
  chapter-08/generated/      the route module (chapter 7's plus two finance console read routes and
                             the payouts SSE stream, but no route for the payout process) and
                             templates, including the /payouts page, generated from chapter 8
  chapter-08/seed.json       an empty seed ({})
  chapter-08/compose.yaml    the docker compose file generated from chapter 8's deploy facts
                             (do not edit; regenerate it)
  chapter-08/compose.override.yaml
                             the hand-written local override: builds the runtime image with
                             chapter 8's generated code, puts Caddy in front as the portal and
                             adds the /data volume
```

Every checkpoint is a cumulative copy of the one before it, so the diff between
two chapters is exactly what that chapter adds:

```
diff examples/expenses/chapter-01/expenses.trig examples/expenses/chapter-02/expenses.trig
```

To browse a checkpoint, point the viewer at it with `SEAMS_MODEL`:

```
SEAMS_MODEL=examples/expenses/chapter-02/expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

## Tested in CI

`tests/test_expense_checkpoints.py` checks every `chapter-*/expenses.trig` it
finds: the file parses, conforms to `ontology/shapes/seam-shapes.ttl`, keeps
seam predicates in the seams graph, keeps every named graph of the previous
chapter, and opens in the viewer at its C4 model with no SHACL violations. It
also replays chapter 2's deliberate mistake (deleting
`:expense_data seam:notation seam:ShapeGraph .`) and checks the validator names
`:expense_data`. A new chapter directory is picked up without editing the test.

`tests/test_expense_chapter3_app.py` checks that `chapter-03/generated/` equals
what the generators produce now, then serves it in process: the page has the
form, invalid input (an empty description, a negative amount, a malformed
date) is a 422 naming the failing paths and stores nothing, and a valid
expense is stored and listed.

`tests/test_expense_process_app.py` does the same for every process chapter
(chapter 4 onward, helpers in `tests/expense_app.py`): the committed generated
code is current, the BPMN model opens in the viewer, and the app runs the
approval process. A submitted expense starts an instance that waits on the
`approve_expense` user task, the task is in the `GET /tasks` inbox with its
generated form, and completing it finishes the instance with the approver in
the trace. An approval whose decision is not in the `sh:in` list is a 422
that leaves the instance waiting, and the inbox without an identity is a 401.

For chapter 5 the same file checks the routing: one served module sends
42.50, 250.00 and 5000.00 down the auto, manager and finance paths, with the
decision's `route` in the trace, and only the routed task can be completed. It
also copies the checkpoint, changes the manager threshold in `approval.dmn`
and regenerates: only the model-hash lines of the generated code differ, the
committed module refuses the edited model, and the regenerated app sends
250.00 to finance. A table without its catch-all rule, or an output no
gateway condition accepts, fails the instance with the error recorded.

For chapter 6 the same file checks the lifecycle: every path (auto, manager
or finance approving, manager or finance rejecting) leaves the stored expense
`approved` or `rejected`, with the history draft, submitted, decided.
`tests/test_expense_lifecycle.py` checks the guard. A transition the current
state does not allow is a `LifecycleViolation` naming it. In a copy of the
checkpoint whose `record_approval` fires `:t_pay`, an auto-approved expense
fails its instance with the transition recorded and stays `submitted`. The
`awaiting_approval` block renders only while the expense is submitted.

For chapter 7, `tests/test_expense_roles.py` serves the checkpoint with
identities whose roles come from `X-Forwarded-Groups`. Only an employee may
submit, only a manager may complete the manager approval, and only finance may
complete the finance approval or pay. A wrong role is a 403 naming the policy
that changes nothing, no identity is a 401, and an invalid payment is a 422
that leaves the instance waiting. An approved expense waits on `pay_expense`,
and paying stores a `PaymentShape` and leaves the expense `paid`. The same
file runs the viewer's `screens-by-role-writing-shape` query on `PaymentShape`
and gets one row: the employee's Submit Expense on the Expenses page.

For chapter 8, `tests/test_expense_payout.py` serves the checkpoint and runs
an expense through both processes. An employee submits 250.00, the manager
approves and finance pays. The approval instance completes, and its message end
event's trace row shows `published` on `:payouts` and the payout instance it
`started`. That instance runs with nobody taking part, under the same
correlation key: it schedules the payment, `payout.dmn` answers `batch` (or
`now` for 750.00), and the stored payment ends `batched` (or `sent`), having
been stored `recorded` when finance paid. A rejected expense, or one approved
but not yet paid, starts no payout, and no generated route starts the payout
process. `GET /payouts`, the finance console page, lists the payment, and the
viewer opens the new models. The same checkpoint is the passing example of
`python -m seams_gen.complexity` (4 notations with two models, `:ExpenseShape`
reached from 6 models, 111 seam edges), pinned by `tests/test_complexity.py`.

## Running chapter 8 under docker compose

Chapter 8's architecture graph has deploy facts: an image, ports and start
order for each container, and one environment (`:prod`, with a node for each
container). The compose generator writes them to `chapter-08/compose.yaml`:

```
python -m seams_gen compose examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08
```

The API container gets the TriG and its four payloads (`approval.bpmn`,
`approval.dmn`, `payout.bpmn`, `payout.dmn`) bind-mounted read-only at
`/model`, with the model hash the generated code was built from. The
generator places containers by `seam:deployedTo` and has no notion of a
second environment, so the checkpoint models no staging environment.

`chapter-08/compose.override.yaml` is written by hand. It builds
`docker/runtime.Dockerfile` with `SEAMS_APP_DIR=examples/expenses/chapter-08`
and `SEAMS_ROUTES_FILE=expense_api.py`, makes the portal a Caddy reverse proxy
to the API, adds healthchecks and a volume for `/data`, and names the project
`seams-expenses`. Compose only merges an override from the working directory,
so pass both files from the repository root:

```
docker compose -f examples/expenses/chapter-08/compose.yaml \
  -f examples/expenses/chapter-08/compose.override.yaml up -d --build --wait
```

There is no auth proxy and no static dev user, so the API's
`HeaderAuthenticator` reads `X-Forwarded-User` and `X-Forwarded-Groups`, which
Caddy passes through. Send them yourself (for example
`curl -H 'X-Forwarded-User: alice' -H 'X-Forwarded-Groups: employee' ...`); a
request without them is a 401. Keep the stack on localhost.

`tests/test_expense_compose.py` checks that the committed `compose.yaml`
equals what the generator writes now, and what the override builds.
`tests/test_expense_e2e.py` runs only with `SEAMS_E2E=1` (CI's `tutorial-e2e`
job): it brings the stack up, and over `http://localhost:8080` an employee
submits, the manager approves through the generated form route, finance pays,
and the test polls `/payouts` until the payout process has batched the
payment and the expense is paid. An invalid submit is a 422 and a submit with
no identity a 401. On failure it prints `docker compose logs`; teardown always
runs `down -v`.
