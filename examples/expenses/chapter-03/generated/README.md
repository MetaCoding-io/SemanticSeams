# Generated code for expense tutorial chapter 3

Every file here except this README is generated from
[`../expenses.trig`](../expenses.trig) by [`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes the operation the form submits to |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the fragment partials the routes render |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-03
```

It runs the two generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).

There is no process yet, so `submit_expense` calls `runtime.write`: it
validates the form against `:ExpenseShape` (422 naming the failing path) and
stores the expense with a runtime-assigned `:id` (D026).

If a generator stops writing a file, delete the committed copy.
`tests/test_expense_chapter3_app.py` fails when a committed file differs from
what the generators produce, and serves the generated app in process.
