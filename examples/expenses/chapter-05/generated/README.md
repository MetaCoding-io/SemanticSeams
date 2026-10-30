# Generated code for expense tutorial chapter 5

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
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |
| `templates/finance_approve_form.html` | `htmx`: the task form partial the inbox renders for `finance_approve_expense` |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-05
```

It runs the two generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).

Compared with chapter 4, the route module gains one handler,
`finance_approve_expense`, the completion route of the finance user task. The
routing itself generates nothing: `runtime.start_process` runs
`route_expense`, which evaluates the DMN table in
[`../approval.dmn`](../approval.dmn), and the BPMN gateway picks the path from
its output. Changing a threshold in the table changes only the model-hash
lines here.

`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
`tests/test_expense_process_app.py` fails when a committed file differs from
what the generators produce, and serves the generated app in process.
