# Event storm: Expense Approval (`approval_process`)

<!-- base: https://example.org/expenses/ -->

## Timeline

1. **Submit Expense** (`submit_expense`)
   - actor: Employee (`employee`)
   - command: Submit Expense (`submit_expense`)
2. **Persist Expense** (`persist_expense`)
   - aggregate: Expense (`ExpenseShape`)
   - domain event: submitted (`t_submit`)
3. **Route Expense** (`route_expense`)
   - policy: Route Approval (`approval_routing`)
4. **Notify Manager** (`notify_manager`)
   - aggregate: Notification (`NotificationShape`)
5. **Approve Expense** (`approve_expense`)
   - actor: Manager (`manager`)
   - command: Approve Expense (`approve_expense`) on `approve_form`
   - aggregate: Approval (`ApprovalShape`)
6. **Finance Approve Expense** (`finance_approve_expense`)
   - actor: Finance (`finance`)
   - command: Finance Approve Expense (`finance_approve_expense`) on `finance_approve_form`
   - aggregate: Approval (`ApprovalShape`)
7. **Record Approval** (`record_approval`)
   - domain event: approved (`t_approve`)
8. **Pay Expense** (`pay_expense`)
   - actor: Finance (`finance`)
   - command: Pay Expense (`pay_expense`) on `payment_form`
   - aggregate: Payment (`PaymentShape`)
   - domain event: paid (`t_pay`)
9. **Record Rejection** (`record_rejection`)
   - domain event: rejected (`t_reject`)

## Gaps

- The derived sections below the timeline are skipped.
