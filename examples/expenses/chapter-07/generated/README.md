# Generated code for expense tutorial chapter 7

Every file here except this README is generated from
[`../expenses.trig`](../expenses.trig) by [`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes the operations and executes `:approval_process` |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the list partials the submit and list routes render |
| `templates/expense_details.html` | `htmx`: the details partial the approval, finance approval, payment and details routes render |
| `templates/awaiting_approval.html` | `htmx`: the guarded partial the awaiting-approval route renders, wrapped in `{% if expense_state == "submitted" %}` |
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |
| `templates/finance_approve_form.html` | `htmx`: the task form partial the inbox renders for `finance_approve_expense` |
| `templates/payment_form.html` | `htmx`: the task form partial the inbox renders for `pay_expense` |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-07
```

It runs the two generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).

Compared with chapter 6, the route module gains the payment completion
handler, `pay_expense`, and the templates gain its task form. The policies
show up in two places. The submit route carries
`dependencies=[Depends(runtime.policy(":employee_submit_policy"))]`, because
`:submit_expense_op` is `seam:governedBy` that policy. Each completion route
already took its identity from `runtime.task_policy(...)`, which now checks
the task's own policy (manager, finance or finance payment). The read routes
have no dependency: they are ungoverned. Who holds a role is not generated:
the runtime reads it from the `X-Forwarded-Groups` header (or
`SEAMS_DEV_ROLES` locally) and matches it against the policy's
`odrl:assignee`.

`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
`tests/test_expense_process_app.py` fails when a committed file differs from
what the generators produce, and serves the generated app in process.
`tests/test_expense_roles.py` covers the roles, the payment and the
access-review query.
