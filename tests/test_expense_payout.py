"""Expense tutorial chapter 8: the asynchronous payout process (M009/S07).

examples/expenses/chapter-08/ ends the approval process's paid path on a
message end event that seam:publishesTo :payouts. :payout_process has no UI
event: its message start event seam:subscribesTo :payouts, so the runtime
starts it (ADR-0010) with the expense's correlation key and a copy of the
approval instance's entities and statuses. It schedules the payment
(:t_schedule, recorded -> scheduled), asks payout.dmn's :payout_method for a
method ("batch" up to 500, else "now"), and the gateway sends the payment to
add_to_batch (:t_batch -> batched) or send_now (:t_send -> sent). Nobody takes
part, and no generated route starts it. A rejected expense ends on a plain
end event and starts nothing.

The finance console is a second IFML model. Its /payouts page holds no task
form, so the host serves it as a page (ModelGraph.secondary_pages), and it
lists the stored payments with their payment lifecycle state.
"""

from urllib.parse import quote

import pytest
from expense_app import (
    PAYOUT_PROCESS,
    assert_generated_current,
    chapter_dir,
    instances,
    serve,
    status,
    trace,
    until,
)

from viewer import app as viewer_app
from viewer import queries, validation

CHAPTER = "chapter-08"
EX = "https://example.org/expenses/"
APPROVAL = EX + "approval_process"
PAY_TASK = EX + "approval_bpmn#pay_expense"
EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
PAYMENT = {"reference": "PAY-0042", "paid_on": "2026-10-05"}


def person(name: str, *roles: str) -> dict[str, str]:
    return {"X-Forwarded-User": name, "X-Forwarded-Groups": ",".join(roles)}


ALICE = person("alice", "employee")
BOB = person("bob", "manager")
CAROL = person("carol", "finance")


@pytest.fixture
def app(tmp_path, monkeypatch):
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def _submit(c, runtime, key, amount):
    r = c.post(f"/expenses/{key}", data={**EXPENSE, "amount": amount}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, key) == "waiting")


def _approve(c, runtime, key, decision="approved"):
    """The manager decides (amounts up to 1000 route to the manager)."""
    r = c.post(f"/expenses/{key}/approval", data={"decision": decision}, headers=BOB)
    assert r.status_code == 200, r.text


def _pay(c, runtime, key):
    until(
        lambda: any(
            t["bpmn_id"] == "pay_expense" and t["correlation_key"] == key for t in runtime.store.list_user_tasks()
        )
    )
    r = c.post(f"/expenses/{key}/payment", data=PAYMENT, headers=CAROL)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, key) == "complete")


def _paid_out(c, runtime, key, amount):
    """Submit, approve and pay; return the finished payout instance's row."""
    _submit(c, runtime, key, amount)
    _approve(c, runtime, key)
    _pay(c, runtime, key)
    until(lambda: status(runtime, key, PAYOUT_PROCESS) in ("complete", "failed"))
    [row] = instances(runtime, key, PAYOUT_PROCESS)
    assert row["status"] == "complete", trace(runtime, key, PAYOUT_PROCESS)
    return row


def _payment(runtime, key) -> dict:
    [payment] = runtime.query(":PaymentShape", expense=key)
    return payment


# ── generated code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("generator", ["fastapi", "htmx"])
def test_committed_generated_code_is_current(generator, tmp_path):
    assert_generated_current(CHAPTER, tmp_path, generator)


def test_no_route_starts_the_payout_process():
    """The route module only starts the approval process: the payout process
    is channel-started (ADR-0010), so no handler names it."""
    module = (chapter_dir(CHAPTER) / "generated" / "expense_api.py").read_text()
    assert 'start_process(\n        ":approval_process"' in module
    assert module.count("start_process(") == 1
    assert "payout_process" not in module


def test_no_http_route_starts_the_payout_process(app):
    c, runtime = app
    paths = c.get("/openapi.json").json()["paths"]
    assert {"/payouts", "/payments", "/payouts/expenses", "/expenses/{expense}/payouts"} <= set(paths)
    assert {
        method
        for path in ("/payouts", "/payments", "/payouts/expenses", "/expenses/{expense}/payouts")
        for method in paths[path]
    } == {"get"}
    for path in ("/payouts", "/payments", "/payouts/expenses"):
        c.post(path, data={**EXPENSE, "amount": "250.00"}, headers=CAROL)
    assert runtime.store.list_instances() == []


# ── the payout process ───────────────────────────────────────────────────────


def test_paying_an_expense_starts_the_payout_process(app):
    c, runtime = app
    row = _paid_out(c, runtime, "e1", "250.00")

    # the approval instance completed, published on :payouts and started the payout
    approval = {r["task"]: r for r in trace(runtime, "e1")}
    end = approval["approved_end"]
    assert end["published"] == {"channel": EX + "payouts", "event": "payout requested"}
    assert end["started"] == [{"process": PAYOUT_PROCESS, "instance": row["instance_id"]}]
    assert row["correlation_key"] == "e1"

    # the payout ran on its own: schedule, decide, batch
    rows = trace(runtime, "e1", PAYOUT_PROCESS)
    assert [r["task"] for r in rows] == [
        "payout_requested",
        "schedule_payout",
        "choose_payout",
        "method_gateway",
        "add_to_batch",
        "paid_out",
    ]
    by_task = {r["task"]: r for r in rows}
    assert not any("by" in r for r in rows)  # nobody completed a task
    assert by_task["choose_payout"]["decision"] == EX + "payout_method"
    assert by_task["choose_payout"]["outputs"] == {"method": "batch"}
    assert by_task["schedule_payout"]["status"] == "scheduled"
    assert by_task["add_to_batch"]["fires"] == EX + "t_batch"

    # the stored payment is the one finance recorded, in its final state
    payment = _payment(runtime, "e1")
    assert payment["status"] == "batched" and payment["data"]["status"] == "batched"
    assert payment["data"]["reference"] == "PAY-0042"
    assert payment["instance_id"] == row["instance_id"]
    assert by_task["add_to_batch"]["writes"] == [payment["id"]]
    [expense] = runtime.query(":ExpenseShape", expense="e1")
    assert expense["status"] == "paid"

    instance = runtime.instances[row["instance_id"]]
    assert instance.result["history"]["Payment"] == ["recorded", "scheduled", "batched"]


def test_a_larger_amount_is_sent_now(app):
    c, runtime = app
    _paid_out(c, runtime, "e2", "750.00")
    rows = {r["task"]: r for r in trace(runtime, "e2", PAYOUT_PROCESS)}
    assert rows["choose_payout"]["outputs"] == {"method": "now"}
    assert "send_now" in rows and "add_to_batch" not in rows
    assert rows["send_now"]["fires"] == EX + "t_send"
    assert _payment(runtime, "e2")["status"] == "sent"


def test_the_paid_payment_is_stored_recorded_before_the_payout(app):
    """Worker rule 4: pay_expense's PaymentShape has a lifecycle but no
    transition moved it, so it is stored in state:initial ("recorded"), and
    the payout's :t_schedule guard finds that state."""
    c, runtime = app
    _submit(c, runtime, "e3", "250.00")
    _approve(c, runtime, "e3")
    _pay(c, runtime, "e3")
    pay_row = {r["task"]: r for r in trace(runtime, "e3")}["pay_expense"]
    approval_instance = instances(runtime, "e3")[-1]["instance_id"]
    wf = runtime.engine.deserialize(runtime.store.load_state(approval_instance))
    assert wf.data["seams"]["status"][EX + "PaymentShape"] == "recorded"
    assert wf.data["seams"]["history"][EX + "PaymentShape"] == ["recorded"]
    assert len(pay_row["writes"]) == 1


def test_a_rejected_expense_starts_no_payout(app):
    c, runtime = app
    _submit(c, runtime, "r1", "250.00")
    _approve(c, runtime, "r1", "rejected")
    until(lambda: status(runtime, "r1") == "complete")
    rows = trace(runtime, "r1")
    assert [r["task"] for r in rows][-2:] == ["record_rejection", "rejected_end"]
    assert not any("published" in r or "started" in r for r in rows)
    assert instances(runtime, "r1", PAYOUT_PROCESS) == []
    assert runtime.query(":PaymentShape", expense="r1") == []
    assert {r["process"] for r in runtime.store.list_instances()} == {APPROVAL}


def test_an_unpaid_expense_starts_no_payout(app):
    """Approval alone does not publish: the message end event comes after
    pay_expense, so the expense waits for finance with no payout."""
    c, runtime = app
    _submit(c, runtime, "w1", "250.00")
    _approve(c, runtime, "w1")
    until(lambda: [t["bpmn_id"] for t in runtime.store.list_user_tasks()] == ["pay_expense"])
    assert status(runtime, "w1") == "waiting"
    assert instances(runtime, "w1", PAYOUT_PROCESS) == []


# ── the finance console ──────────────────────────────────────────────────────


def test_the_finance_console_lists_the_payment(app):
    c, runtime = app
    r = c.get("/payouts")
    assert r.status_code == 200, r.text
    assert r.text.lstrip().startswith("<!doctype html>")
    assert '<main id="payouts_page" data-seam=":payouts_page">' in r.text
    assert '<li class="payment">' not in r.text

    _paid_out(c, runtime, "e1", "250.00")
    r = c.get("/payouts")
    assert r.status_code == 200, r.text
    assert '<span class="reference">PAY-0042</span>' in r.text
    assert '<span class="status">batched</span>' in r.text
    assert '<span class="description">Train to Leeds</span>' in r.text
    assert '<span class="status">paid</span>' in r.text

    fragment = c.get("/payments")
    assert fragment.status_code == 200, fragment.text
    assert '<section id="payment_list"' in fragment.text and "PAY-0042" in fragment.text
    assert '<section id="paid_expenses"' in c.get("/payouts/expenses").text
    # the landmark page is unchanged
    assert '<main id="expenses_page"' in c.get("/").text


def test_secondary_pages_skip_task_form_screens():
    """ModelGraph.secondary_pages: a pathed page with no task form. The
    approvals page holds the task forms (the inbox reaches it, ADR-0009), so
    chapter 7 has none and its host serves no /approvals page."""
    from seams_runtime import ModelGraph

    assert ModelGraph.load(chapter_dir("chapter-07") / "expenses.trig").secondary_pages() == []
    assert list(map(str, ModelGraph.load(chapter_dir(CHAPTER) / "expenses.trig").secondary_pages())) == [
        EX + "payouts_page"
    ]


def test_the_approvals_screen_is_not_a_page(app):
    c, _runtime = app
    assert c.get("/approvals").status_code == 404


# ── the viewer ───────────────────────────────────────────────────────────────


@pytest.fixture
def viewer(monkeypatch):
    monkeypatch.delenv(viewer_app.MODEL_ENV, raising=False)
    monkeypatch.delenv(viewer_app.ROOT_ENV, raising=False)
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    viewer_app.configure(chapter_dir(CHAPTER) / "expenses.trig")
    try:
        yield viewer_app
    finally:
        viewer_app.configure(original)
        validation._clear_cache()


@pytest.mark.parametrize(
    "model, payload",
    [
        ("payout_bpmn", "payout.bpmn"),
        ("payout_dmn", "payout.dmn"),
        ("payment_lifecycle", None),
        ("finance_console", None),
    ],
)
def test_the_viewer_opens_the_new_models(viewer, model, payload):
    from fastapi.testclient import TestClient

    client = TestClient(viewer.app)
    r = client.get(f"/view/{quote(EX + model, safe='')}")
    assert r.status_code == 200, r.text
    if payload is not None:
        assert payload in r.text


def test_screens_by_role_writing_a_payment_reach_the_payout(viewer):
    result = queries.execute_query(viewer.get_graph(), "screens-by-role-writing-shape", EX + "PaymentShape")
    writers = {row["writer"] for row in result["rows"]}
    assert PAY_TASK in writers
    # the async hop: submit -> approval -> approved_end publishes -> payout subscribes
    assert {EX + "payout_bpmn#schedule_payout", EX + "payout_bpmn#add_to_batch", EX + "payout_bpmn#send_now"} <= writers
    assert {(row["role"], row["screen"], row["event"]) for row in result["rows"]} == {
        (EX + "employee", EX + "expenses_page", EX + "submit_expense")
    }
