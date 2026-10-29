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
