# Generated code for expense tutorial chapter 8

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

Regenerate from the repository root:

```
python -m seams_gen fastapi examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08/generated
python -m seams_gen htmx examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08/generated/templates
```

Compared with chapter 7, the route module gains two read routes for the
finance console (`list_payments`, `paid_expenses`) and the `payouts` SSE
stream of the channel the approval process publishes on. It gains no route
for `:payout_process`: that process's start event `seam:subscribesTo`
`:payouts`, so the runtime starts it when an approval instance publishes
there (ADR-0010). The templates gain the `/payouts` page and its two
partials. The host serves that page as it serves the landmark page, because
it has an `ifml:path` and holds no task form.

If a generator stops writing a file, delete the committed copy.
`tests/test_expense_payout.py` fails when a committed file differs from what
the generators produce, serves the generated app in process, and runs an
expense from submit through the payout.
