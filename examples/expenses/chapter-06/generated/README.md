# Generated code for expense tutorial chapter 6

Every file here except this README is generated from
[`../expenses.trig`](../expenses.trig) by [`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes the operations and executes `:approval_process` |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the list partials the submit and list routes render |
| `templates/expense_details.html` | `htmx`: the details partial the approval, finance approval and details routes render |
| `templates/awaiting_approval.html` | `htmx`: the guarded partial the awaiting-approval route renders, wrapped in `{% if expense_state == "submitted" %}` |
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |
| `templates/finance_approve_form.html` | `htmx`: the task form partial the inbox renders for `finance_approve_expense` |

Regenerate from the repository root:

```
python -m seams_gen fastapi examples/expenses/chapter-06/expenses.trig --out examples/expenses/chapter-06/generated
python -m seams_gen htmx examples/expenses/chapter-06/expenses.trig --out examples/expenses/chapter-06/generated/templates
```

Compared with chapter 5, the route module gains one handler,
`awaiting_approval`, and the templates gain its guarded partial. The partials
that list expenses also show the new `status` field. The lifecycle
itself generates nothing: the runtime checks each `seam:fires` transition
before the task runs and stores the new state after it, so the statechart in
`../expenses.trig` and the gateways in [`../approval.bpmn`](../approval.bpmn)
decide which state an expense reaches.

If a generator stops writing a file, delete the committed copy.
`tests/test_expense_process_app.py` fails when a committed file differs from
what the generators produce, and serves the generated app in process.
`tests/test_expense_lifecycle.py` covers the refused transition and the guard.
