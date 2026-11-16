# Structurizr DSL workspace of the model's C4 layer, written by the seams_gen structurizr generator (ADR-0044). Regenerate it with `seams generate`; do not edit it.
workspace {
    model {
        employee = person "Employee"
        finance = person "Finance"
        manager = person "Manager"
        expense_system = softwareSystem "Expense Approval" {
            employee_portal = container "Employee Portal" "" "htmx + server-rendered fragments"
            expense_api = container "Expense API" "" "FastAPI"
            expense_db = container "Expense Store" "" "PostgreSQL"
        }
        sempkm = softwareSystem "SemPKM" {
            tags "External"
            expense_pkm = container "Expense Knowledge Store" "" "SemPKM"
            expense_triplestore = container "Expense Triplestore" "" "RDF4J"
        }
        employee -> employee_portal "submit_expense"
        employee_portal -> expense_api "approve_expense_op, awaiting_approval_op, expense_details_op, finance_approve_expense_op, list_expenses_op, list_payments_op, paid_expenses_op, pay_expense_op, submit_expense_op"
        expense_api -> expense_db "depends on"
        expense_api -> expense_pkm "depends on"
        expense_pkm -> expense_triplestore "depends on"
        finance -> employee_portal "submit_finance_approval, submit_payment"
        manager -> employee_portal "submit_approval"
    }
    views {
        systemContext expense_system "expense_system-context" {
            include *
            autoLayout
        }
        container expense_system "expense_system-containers" {
            include *
            autoLayout
        }
        container sempkm "sempkm-containers" {
            include *
            autoLayout
        }
    }
}
