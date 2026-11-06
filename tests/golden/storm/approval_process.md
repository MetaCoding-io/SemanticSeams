# Event storm: Expense Approval

<!-- derived from https://example.org/expenses/approval_process -->

## Timeline

1. **Submit Expense** (`submit_expense`)
   - actor: Employee (policy `employee_submit_policy`)
   - command: Submit Expense (`submit_expense`) → POST `submit_expense_op` [ExpenseShape]
2. **Persist Expense** (`persist_expense`)
   - aggregate: Expense (`ExpenseShape`), class `Expense`, stored in `expense_pkm`, lifecycle `expense_lifecycle`
   - domain event: submitted (`t_submit`: draft → submitted, Expense Lifecycle)
3. **Route Expense** (`route_expense`)
   - decision: Route Approval (`approval_routing`)
4. **Notify Manager** (`notify_manager`)
   - aggregate: Notification (`NotificationShape`), stored in `expense_db`
5. **Approve Expense** (`approve_expense`)
   - actor: Manager (policy `manager_approval_policy`)
   - command: Approve Expense (`approve_expense`) on `approve_form` → POST `approve_expense_op` [ApprovalShape]
   - aggregate: Approval (`ApprovalShape`), class `Approval`, stored in `expense_db`
6. **Finance Approve Expense** (`finance_approve_expense`)
   - actor: Finance (policy `finance_approval_policy`)
   - command: Finance Approve Expense (`finance_approve_expense`) on `finance_approve_form` → POST `finance_approve_expense_op` [ApprovalShape]
   - aggregate: Approval (`ApprovalShape`), class `Approval`, stored in `expense_db`
7. **Record Approval** (`record_approval`)
   - domain event: approved (`t_approve`: submitted → approved, Expense Lifecycle)
8. **Pay Expense** (`pay_expense`)
   - actor: Finance (policy `finance_payment_policy`)
   - command: Pay Expense (`pay_expense`) on `payment_form` → POST `pay_expense_op` [PaymentShape]
   - aggregate: Payment (`PaymentShape`), class `Payment`, stored in `expense_db`, lifecycle `payment_lifecycle`
   - domain event: paid (`t_pay`: approved → paid, Expense Lifecycle)
9. **Record Rejection** (`record_rejection`)
   - domain event: rejected (`t_reject`: submitted → rejected, Expense Lifecycle)
10. **Paid** (`approved_end`)
    - channel: payout requested (`payouts`)
    - process started: Expense Payout (`payout_process`) via `payouts`

## Read models

- Awaiting approval (`awaiting_approval`) reads `ExpenseShape`, served by GET `awaiting_approval_op`
- Expense (`expense_details`) reads `ExpenseShape`, served by GET `expense_details_op`
- My Expenses (`expense_list`) reads `ExpenseShape`, served by GET `list_expenses_op`
- Expenses (`paid_expenses`) reads `ExpenseShape`, served by GET `paid_expenses_op`
- Payments (`payment_list`) reads `PaymentShape`, served by GET `list_payments_op`

## Gaps

- ApprovalShape has no read model: no ifml page or component seam:reads it
- NotificationShape has no read model: no ifml page or component seam:reads it
