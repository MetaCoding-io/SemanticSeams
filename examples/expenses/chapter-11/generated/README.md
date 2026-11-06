# Generated code for expense tutorial chapter 11

Every file here except this README is generated from the model in
[`..`](..): [`../expenses.trig`](../expenses.trig) and
[`../finance.trig`](../finance.trig), loaded together as one dataset, by
[`seams_gen`](../../../../seams_gen/README.md).
Do not edit them: change the model and regenerate. Each file carries the model
hash it was generated from.

| File | Generator |
|---|---|
| `expense_api.py` | `fastapi`: the route module of `:expense_api`, the container that exposes both contexts' operations and the `:payouts` stream and executes `:approval_process`, `:payout_process` and `:vendor_review_process` |
| `expense_api.Dockerfile` | `dockerfile`: the runtime image with this route module and its templates; compose mounts the model |
| `templates/expenses_page.html` | `htmx`: the landmark page |
| `templates/payouts_page.html` | `htmx`: the finance console's `/payouts` page, a page with an `ifml:path` and no task form |
| `templates/expense_list.html`, `templates/expense_list_item.html` | `htmx`: the list partials the submit and list routes render |
| `templates/expense_details.html` | `htmx`: the details partial the approval, finance approval and details routes render |
| `templates/awaiting_approval.html` | `htmx`: the guarded partial the awaiting-approval route renders, wrapped in `{% if expense_state == "submitted" %}` |
| `templates/payment_list.html`, `templates/paid_expenses.html` | `htmx`: the finance console partials the `/payments` and `/payouts/expenses` routes render |
| `templates/payment_details.html` | `htmx`: the partial the payment route renders, on the finance console's payments-due screen |
| `templates/approve_form.html` | `htmx`: the task form partial the `GET /tasks` inbox renders for `approve_expense` |
| `templates/finance_approve_form.html` | `htmx`: the task form partial the inbox renders for `finance_approve_expense` |
| `templates/payment_form.html` | `htmx`: the task form partial the inbox renders for the payout process's `pay_expense` |
| `tests/test_scenarios.py`, `tests/test_decisions.py`, `tests/test_shape_examples.py`, `tests/test_policies.py` | `tests`: pytest files for the `verify:` scenarios and examples and the allow/deny test for each ODRL permission and party (ADR-0014) |
| `acceptance/test_notify.py` | `acceptance`: checks the hand-written notify handler against the model |
| `contexts/*.jsonld` | `jsonld`: the JSON-LD context of each shape with a `sh:targetClass` (ADR-0024); `expense_api.py` serves the same text at `GET /contexts/<shape>.jsonld` |
| `smoke/test_smoke.py` | `smoke`: one test per `hydra:Operation`, calling it on its `comm:path` against `SEAMS_SMOKE_BASE_URL` and checking the answer against `seam:returnsShape`; skipped when the variable is unset |

Regenerate from the repository root:

```
seams generate --project examples/expenses/chapter-11
```

It runs the generators [`../seams.toml`](../seams.toml) names, writing each output
above and the chapter's `../compose.development.yaml` and
`../compose.production.yaml`, one per environment the model declares
(reference: [docs/reference/seams-cli.md](../../../../docs/reference/seams-cli.md)).
The compose files mount each TriG file of the model under `/model`.

Compared with chapter 10, the payment route (`POST /expenses/{expense}/payment`)
now completes the payout process's `pay_expense` task and renders the payment,
not the expense; the approval routes no longer lead to a payment task. There is
no `mental-model/` directory: the `mentalmodel` generator writes a SemPKM Mental
Model for one `seam:Ontology` model, and this dataset has two, so chapter 11's
`seams.toml` does not list it.

`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
