"""Expense tutorial chapter 7: roles, policies and the payment task (M009/S06).

examples/expenses/chapter-07/ makes :employee, :manager and :finance
odrl:Party roles. :employee_submit_policy governs the submit operation, and
each user task is governed by its own policy: approve_expense by the
manager's, finance_approve_expense and the new pay_expense by finance's. The
runtime's RoleEvaluator admits an identity whose id or X-Forwarded-Groups role
names the assignee. The people here (alice, bob, carol, dave) are names, not
role names, so only the role grants access.

An approved expense now waits on pay_expense. Finance completes it with a
PaymentShape, the task fires :t_pay, and the expense ends "paid". Failure
modes: no identity is a 401, a wrong role a 403 that changes nothing, and an
invalid payment a 422 that leaves the instance waiting.

The same checkpoint answers the access-review question in the viewer: the
only screen an employee can use that eventually writes a PaymentShape is the
Expenses page's Submit Expense, reaching pay_expense through the process it
starts.
"""

import pytest
from expense_app import chapter_dir, serve, status, trace, until

from viewer import app as viewer_app
from viewer import queries, validation

CHAPTER = "chapter-07"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
FINANCE_TASK = EX + "approval_bpmn#finance_approve_expense"
PAY_TASK = EX + "approval_bpmn#pay_expense"
EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
SMALL, MID, LARGE = "42.50", "200.00", "5000.00"
PAYMENT = {"reference": "PAY-0042", "paid_on": "2026-10-05"}
JSON = {"Accept": "application/json"}


def person(name: str, *roles: str) -> dict[str, str]:
    return {"X-Forwarded-User": name, "X-Forwarded-Groups": ",".join(roles)}


ALICE = person("alice", "employee")
BOB = person("bob", "manager")
CAROL = person("carol", "finance")
DAVE = person("dave", "employee")


@pytest.fixture
def app(tmp_path, monkeypatch):
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def _submit(c, runtime, key, amount, who=ALICE):
    r = c.post(f"/expenses/{key}", data={**EXPENSE, "amount": amount}, headers=who)
    assert r.status_code == 200, r.text
    return until(lambda: status(runtime, key) in ("waiting", "complete", "failed") and status(runtime, key))


def _inbox(c, who) -> list[tuple[str, str]]:
    """(correlation key, task IRI) of every task in ``who``'s inbox"""
    r = c.get("/tasks", headers={**who, **JSON})
    assert r.status_code == 200, r.text
    return [(row["correlation_key"], row["task"]) for row in r.json()["tasks"]]


def _open(runtime) -> dict[str, str]:
    """correlation key -> bpmn id of its open user task"""
    return {row["correlation_key"]: row["bpmn_id"] for row in runtime.store.list_user_tasks()}


def _stored_status(runtime, key) -> str:
    [expense] = runtime.query(":ExpenseShape", expense=key)
    return expense["status"]


def _denied(r, status_code, policy):
    assert r.status_code == status_code, r.text
    detail = r.json()["detail"]
    assert detail["type"] == "PolicyDenied", detail
    assert detail["policy"] == EX + policy, detail
    return detail


# ── submitting ───────────────────────────────────────────────────────────────


def test_an_employee_submits_and_a_manager_may_not(app):
    c, runtime = app
    assert _submit(c, runtime, "e1", MID) == "waiting"
    assert _stored_status(runtime, "e1") == "submitted"

    r = c.post("/expenses/e2", data={**EXPENSE, "amount": MID}, headers=BOB)
    detail = _denied(r, 403, "employee_submit_policy")
    assert "employee_submit_policy" in detail["reason"] and "'bob'" in detail["reason"]
    assert "roles: manager" in detail["reason"]
    # refused before the process started: nothing stored for e2
    assert runtime.store.list_instances(correlation_key="e2") == []
    assert runtime.query(":ExpenseShape", expense="e2") == []


def test_no_identity_is_401(app):
    c, runtime = app
    r = c.post("/expenses/e1", data={**EXPENSE, "amount": MID})
    _denied(r, 401, "employee_submit_policy")
    assert runtime.store.list_instances() == []
    r = c.get("/tasks", headers=JSON)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["type"] == "PolicyDenied"


def test_the_read_routes_are_ungoverned(app):
    c, runtime = app
    _submit(c, runtime, "e1", MID)
    for path in ("/expenses", "/expenses/e1", "/expenses/e1/awaiting-approval"):
        assert c.get(path).status_code == 200, path


# ── approving ────────────────────────────────────────────────────────────────


def test_only_the_manager_sees_and_completes_the_approval(app):
    c, runtime = app
    _submit(c, runtime, "e1", MID)
    assert _inbox(c, BOB) == [("e1", TASK)]
    assert _inbox(c, CAROL) == []
    assert _inbox(c, ALICE) == []

    r = c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=DAVE)
    detail = _denied(r, 403, "manager_approval_policy")
    assert detail["operation"] == TASK
    assert status(runtime, "e1") == "waiting" and _open(runtime) == {"e1": "approve_expense"}
    assert runtime.query(":ApprovalShape") == []
    assert _stored_status(runtime, "e1") == "submitted"

    r = c.post("/expenses/e1/approval", data={"decision": "approved"})
    _denied(r, 401, "manager_approval_policy")
    assert _open(runtime) == {"e1": "approve_expense"}


def test_manager_approves_then_finance_pays(app):
    c, runtime = app
    _submit(c, runtime, "e1", MID)
    r = c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=BOB)
    assert r.status_code == 200, r.text
    until(lambda: _open(runtime) == {"e1": "pay_expense"})
    assert status(runtime, "e1") == "waiting" and _stored_status(runtime, "e1") == "approved"
    assert _inbox(c, CAROL) == [("e1", PAY_TASK)]
    assert _inbox(c, BOB) == []

    html = c.get("/tasks", headers=CAROL).text
    assert '<form id="payment_form_e1"' in html and 'hx-post="/expenses/e1/payment"' in html

    # the manager may not pay
    _denied(c.post("/expenses/e1/payment", data=PAYMENT, headers=BOB), 403, "finance_payment_policy")
    assert runtime.query(":PaymentShape") == []

    r = c.post("/expenses/e1/payment", data=PAYMENT, headers=CAROL)
    assert r.status_code == 200, r.text
    assert '<section id="expense_details"' in r.text and 'data-expense="e1"' in r.text
    until(lambda: status(runtime, "e1") == "complete")

    assert _stored_status(runtime, "e1") == "paid"
    [payment] = runtime.query(":PaymentShape", expense="e1")
    assert payment["data"] == PAYMENT
    rows = {row["task"]: row for row in trace(runtime, "e1")}
    assert rows["approve_expense"]["by"] == "bob"
    assert rows["pay_expense"]["by"] == "carol"
    assert rows["pay_expense"]["fires"] == EX + "t_pay"
    assert rows["pay_expense"]["writes"] == [payment["id"]]
    assert _open(runtime) == {}


@pytest.mark.parametrize(
    "data, paths",
    [
        ({"paid_on": "2026-10-05"}, ["reference"]),
        ({"reference": "PAY-1", "paid_on": "yesterday"}, ["paid_on"]),
        ({"reference": "x" * 101, "paid_on": "2026-10-05"}, ["reference"]),
    ],
    ids=["missing-reference", "bad-date", "reference-too-long"],
)
def test_an_invalid_payment_is_422_and_changes_nothing(app, data, paths):
    c, runtime = app
    _submit(c, runtime, "e1", MID)
    c.post("/expenses/e1/approval", data={"decision": "approved"}, headers=BOB)
    until(lambda: _open(runtime) == {"e1": "pay_expense"})

    r = c.post("/expenses/e1/payment", data=data, headers=CAROL)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["type"] == "ContractViolation"
    assert sorted(x["path"] for x in detail["results"]) == paths
    assert runtime.query(":PaymentShape") == []
    assert status(runtime, "e1") == "waiting" and _open(runtime) == {"e1": "pay_expense"}
    assert _stored_status(runtime, "e1") == "approved"


def test_a_rejected_expense_is_never_paid(app):
    c, runtime = app
    _submit(c, runtime, "e1", MID)
    c.post("/expenses/e1/approval", data={"decision": "rejected"}, headers=BOB)
    until(lambda: status(runtime, "e1") == "complete")
    assert _stored_status(runtime, "e1") == "rejected"
    assert _inbox(c, CAROL) == []
    r = c.post("/expenses/e1/payment", data=PAYMENT, headers=CAROL)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["type"] == "TaskNotOpen"


# ── the other paths ──────────────────────────────────────────────────────────


def test_finance_approves_a_large_amount_and_the_manager_may_not(app):
    c, runtime = app
    assert _submit(c, runtime, "big", LARGE) == "waiting"
    assert _inbox(c, CAROL) == [("big", FINANCE_TASK)]
    assert _inbox(c, BOB) == []

    r = c.post("/expenses/big/finance-approval", data={"decision": "approved"}, headers=BOB)
    _denied(r, 403, "finance_approval_policy")
    assert _open(runtime) == {"big": "finance_approve_expense"}

    r = c.post("/expenses/big/finance-approval", data={"decision": "approved"}, headers=CAROL)
    assert r.status_code == 200, r.text
    until(lambda: _open(runtime) == {"big": "pay_expense"})
    assert _inbox(c, CAROL) == [("big", PAY_TASK)]


def test_a_small_amount_goes_straight_to_payment(app):
    c, runtime = app
    assert _submit(c, runtime, "small", SMALL) == "waiting"
    assert _open(runtime) == {"small": "pay_expense"}
    assert _stored_status(runtime, "small") == "approved"
    assert _inbox(c, CAROL) == [("small", PAY_TASK)]
    assert _inbox(c, BOB) == []
    c.post("/expenses/small/payment", data=PAYMENT, headers=CAROL)
    until(lambda: status(runtime, "small") == "complete")
    assert _stored_status(runtime, "small") == "paid"


# ── the access-review query ──────────────────────────────────────────────────


def test_the_viewer_answers_which_screens_write_a_payment(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    try:
        viewer_app.configure(chapter_dir(CHAPTER) / "expenses.trig")
        result = queries.execute_query(viewer_app.get_graph(), "screens-by-role-writing-shape", EX + "PaymentShape")
    finally:
        viewer_app.configure(original)
        validation._clear_cache()
    assert result["rows"] == [
        {
            "role": EX + "employee",
            "screen": EX + "expenses_page",
            "event": EX + "submit_expense",
            "writer": PAY_TASK,
        }
    ]
