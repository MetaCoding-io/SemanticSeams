# Generated code for expense tutorial chapter 9

Every file here except this README is generated from
[`../expenses.trig`](../expenses.trig) by [`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes the operations and the `:payouts` stream and executes `:approval_process` and `:payout_process` |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/payouts_page.html` | `htmx`: the finance console's `/payouts` page, a page with an `ifml:path` and no task form |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the list partials the submit and list routes render |
| `templates/expense_details.html` | `htmx`: the details partial the approval, finance approval, payment and details routes render |
| `templates/awaiting_approval.html` | `htmx`: the guarded partial the awaiting-approval route renders, wrapped in `{% if expense_state == "submitted" %}` |
| `templates/payment_list.html`, `templates/paid_expenses.html` | `htmx`: the finance console partials the `/payments` and `/payouts/expenses` routes render |
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |
| `templates/finance_approve_form.html` | `htmx`: the task form partial the inbox renders for `finance_approve_expense` |
| `templates/payment_form.html` | `htmx`: the task form partial the inbox renders for `pay_expense` |
| `tests/test_scenarios.py`, `tests/test_decisions.py`, `tests/test_shape_examples.py`, `tests/test_policies.py` | `tests`: pytest files for the `verify:` scenarios and examples and the allow/deny test for each ODRL permission and party (ADR-0014) |
| `smoke/test_smoke.py` | `smoke`: one test per `hydra:Operation`, calling it on its `comm:path` against `SEAMS_SMOKE_BASE_URL` and checking the answer against `seam:returnsShape`; skipped when the variable is unset |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-09
```

It runs the generators [`../seams.toml`](../seams.toml) names, writing each output
above and the chapter's `../compose.yaml`
(reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).

Compared with chapter 8, the route module gains no route. `:expense_api` now
also exposes `:notify_manager_op`, but no `ifml:Event` `seam:submitsTo` it:
only the `notify_manager` service task `seam:invokes` it, so the module
header lists it as not routed and the runtime calls its
`comm:PythonHandler` in-process (ADR-0012). That handler is owned code in
[`../handlers/`](../handlers/notify.py), not in this directory:
`python -m seams_gen.stubs` wrote it once, and `seams generate` never writes
there. The templates change only in their model hash.

`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
`tests/test_expense_handler.py` fails when a committed file differs from what
the generators produce, serves the generated app in process, and checks the
notify step ran the hand-written handler.
