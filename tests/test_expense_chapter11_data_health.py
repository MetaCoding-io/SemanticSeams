"""Chapter 11's paid-once invariant (ADR-0036, M029/S05/T03).

An expense is paid once. The rule crosses two aggregates, the expense and the
payment, so the DDD profile states it as a sh:Warning sh:sparql shape on
instance data: paying an expense twice is stored, and Runtime.data_health
reports it, naming the expense. The payment names its expense through
:PaymentShape's "expense" field, which the runtime fills from the payout
instance's correlation key.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from expense_app import PAYOUT_PROCESS, instances, serve, until  # noqa: E402

from seams_runtime import ModelGraph  # noqa: E402
from seams_runtime.contracts import with_correlation_key  # noqa: E402

EXPENSE = {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"}
PAID_ONCE = "https://example.org/profiles/ddd#PaidOnce"
FINANCE = {"X-Forwarded-User": "finance"}
EMPLOYEE = {"X-Forwarded-User": "employee"}


def _payouts_done(runtime, key: str, count: int) -> bool:
    rows = instances(runtime, key, PAYOUT_PROCESS)
    return len(rows) == count and all(r["status"] == "complete" for r in rows)


def _pay(c, runtime, key: str, reference: str) -> None:
    r = c.post(f"/expenses/{key}/payment", data={"reference": reference, "paid_on": "2026-10-05"}, headers=FINANCE)
    assert r.status_code == 200, r.text


def _submit(c, runtime, key: str, payouts: int) -> None:
    """Submit expense ``key`` and wait for its ``payouts``-th payout to wait on finance."""
    r = c.post(f"/expenses/{key}", data=EXPENSE, headers=EMPLOYEE)
    assert r.status_code == 200, r.text
    until(lambda: len([r for r in instances(runtime, key, PAYOUT_PROCESS) if r["status"] == "waiting"]) == 1)
    assert len(instances(runtime, key, PAYOUT_PROCESS)) == payouts


def test_the_payment_names_the_expense_its_payout_is_keyed_by(tmp_path, monkeypatch):
    with serve("chapter-11", tmp_path, monkeypatch) as (c, runtime):
        _submit(c, runtime, "e1", 1)
        _pay(c, runtime, "e1", "PAY-1")
        until(lambda: _payouts_done(runtime, "e1", 1))
        [payment] = runtime.query(":PaymentShape", expense="e1")
        assert payment["data"]["expense"] == "e1" and payment["correlation_key"] == "e1"
        assert runtime.data_health() == []


def test_paying_an_expense_twice_is_stored_and_reported_once(tmp_path, monkeypatch, caplog):
    with serve("chapter-11", tmp_path, monkeypatch) as (c, runtime):
        _submit(c, runtime, "e1", 1)
        _pay(c, runtime, "e1", "PAY-1")
        until(lambda: _payouts_done(runtime, "e1", 1))
        # the same expense goes through approval and payout again
        _submit(c, runtime, "e1", 2)
        _pay(c, runtime, "e1", "PAY-2")
        until(lambda: _payouts_done(runtime, "e1", 2))
        # a second expense paid once breaks no rule
        _submit(c, runtime, "e2", 1)
        _pay(c, runtime, "e2", "PAY-3")
        until(lambda: _payouts_done(runtime, "e2", 1))

        # the warning refuses no write: both payments of e1 are stored
        payments = runtime.query(":PaymentShape", expense="e1")
        assert sorted(p["data"]["reference"] for p in payments) == ["PAY-1", "PAY-2"]
        assert {p["data"]["expense"] for p in payments} == {"e1"}

        with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
            [finding] = runtime.data_health()
        assert finding.shape == PAID_ONCE
        assert finding.focus == "e1"
        assert finding.severity == "Warning"
        assert finding.message == "expense e1 is paid by 2 payments, and an expense is paid once"
        assert "data health https://example.org/profiles/ddd 1 warning(s)" in caplog.messages


def test_the_key_fill_keeps_a_given_value_and_touches_no_other_shape():
    model = ModelGraph(ROOT / "examples" / "expenses" / "chapter-11")
    payment = {"reference": "PAY-1", "paid_on": "2026-10-05"}
    assert with_correlation_key(model, ":PaymentShape", payment, "e1") == {**payment, "expense": "e1"}
    # a payload that names its expense keeps it
    given = {**payment, "expense": "e9"}
    assert with_correlation_key(model, ":PaymentShape", given, "e1") is given
    # no key, or a shape with no key-named field, leaves the payload as it is
    assert with_correlation_key(model, ":PaymentShape", payment, None) is payment
    assert with_correlation_key(model, ":PaymentShape", payment, "") is payment
    assert with_correlation_key(model, ":ExpenseShape", EXPENSE, "e1") is EXPENSE
