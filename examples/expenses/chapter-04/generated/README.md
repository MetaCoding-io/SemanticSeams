# Generated code for expense tutorial chapter 4

Every file here except this README is generated from
[`../expenses.trig`](../expenses.trig) by [`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes the operations and executes `:approval_process` |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the list partials the submit and list routes render |
| `templates/expense_details.html` | `htmx`: the details partial the approval and details routes render |
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-04
```

It runs the two generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).

The submit event now `seam:triggers :approval_process`, so `submit_expense`
validates the form and calls `runtime.start_process` with the `{expense}` path
variable as the correlation key; the process's service task stores the
expense. `approve_expense` is the completion route of the `approve_expense`
user task (ADR-0009): it calls `runtime.complete_task`, which validates the
form against `:ApprovalShape` and lets the process finish.

If a generator stops writing a file, delete the committed copy.
`tests/test_expense_process_app.py` fails when a committed file differs from
what the generators produce, and serves the generated app in process.
