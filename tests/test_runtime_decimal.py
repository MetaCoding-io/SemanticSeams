"""An xsd:decimal field reaches a Python handler as a ``decimal.Decimal`` (A14).

The handler stub types such a field as ``Decimal``; ``handler_values`` makes
that true at run time. The worker and ``verify.handler_result`` pass a
handler the converted entity; HTTP and LLM bodies stay JSON. A Decimal a
handler returns validates as xsd:decimal and is stored as its plain lexical
form, so instance state stays JSON.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from expense_app import chapter_dir, serve, status, trace, until

from seams_runtime import ModelGraph
from seams_runtime.contracts import handler_values, validate
from seams_runtime.errors import ContractViolation
from seams_runtime.verify import Handler, handler_result, resolve_handler

CHAPTER = "chapter-09"
EX = "https://example.org/expenses/"
OP = EX + "notify_manager_op"
EXPENSE = {"description": "Train to Leeds", "date": "2026-10-01"}
ALICE = {"X-Forwarded-User": "alice", "X-Forwarded-Groups": "employee"}
NOTIFY = Handler(handler="notify.notify_manager", implementation=EX + "notify_manager_impl")


@pytest.fixture(scope="module")
def model() -> ModelGraph:
    return ModelGraph.load(chapter_dir(CHAPTER) / "expenses.trig")


def _copy(tmp_path: Path, body: str | None = None) -> ModelGraph:
    """Chapter 9's model files, its handlers/notify.py replaced by ``body`` when given."""
    app = tmp_path / "app"
    app.mkdir()
    source = chapter_dir(CHAPTER)
    for path in source.iterdir():
        if path.suffix in (".trig", ".bpmn", ".dmn"):
            shutil.copy(path, app / path.name)
    shutil.copytree(source / "handlers", app / "handlers", ignore=shutil.ignore_patterns("__pycache__"))
    if body is not None:
        (app / "handlers" / "notify.py").write_text(body, encoding="utf-8")
    return ModelGraph(app / "expenses.trig")


# ── handler_values ────────────────────────────────────────────────────────────


def test_a_decimal_field_becomes_a_decimal_and_other_fields_are_untouched(model):
    values = handler_values(model, ":ExpenseShape", {**EXPENSE, "amount": "42.50"})
    assert values == {**EXPENSE, "amount": Decimal("42.50")}
    assert type(values["amount"]) is Decimal
    assert type(values["description"]) is str and type(values["date"]) is str


@pytest.mark.parametrize(
    ("given", "expected"),
    [(42, Decimal(42)), (Decimal("1.5"), Decimal("1.5")), (["1.10", "2"], [Decimal("1.10"), Decimal(2)])],
)
def test_numbers_decimals_and_lists_of_a_decimal_field(model, given, expected):
    assert handler_values(model, ":ExpenseShape", {"amount": given})["amount"] == expected


def test_a_boolean_and_a_field_the_shape_lacks_are_passed_as_they_are(model):
    assert handler_values(model, ":ExpenseShape", {"amount": True, "other": "42.50"}) == {
        "amount": True,
        "other": "42.50",
    }


def test_the_input_mapping_is_not_changed(model):
    data = {"amount": "42.50"}
    handler_values(model, ":ExpenseShape", data)
    assert data == {"amount": "42.50"}


# ── a Decimal a handler returns ──────────────────────────────────────────────


@pytest.mark.parametrize(("given", "stored"), [(Decimal("42.50"), "42.50"), (Decimal("1E+2"), "100")])
def test_a_returned_decimal_validates_and_is_stored_as_json(model, given, stored):
    out = validate(model, ":ExpenseShape", {**EXPENSE, "amount": given})
    assert out["amount"] == stored
    json.dumps(out)  # instance state is JSON
    assert validate(model, ":ExpenseShape", out) == out  # and validates again as stored


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_a_non_finite_decimal_is_not_an_xsd_decimal(model, bad):
    with pytest.raises(ContractViolation) as caught:
        validate(model, ":ExpenseShape", {**EXPENSE, "amount": bad})
    assert [(e["path"], e["constraint"]) for e in caught.value.results] == [("amount", "DatatypeConstraintComponent")]


def test_a_decimal_for_a_string_field_fails_its_datatype(model):
    with pytest.raises(ContractViolation) as caught:
        validate(model, ":ExpenseShape", {**EXPENSE, "amount": "1", "description": Decimal("1")})
    assert ("description", "DatatypeConstraintComponent") in [
        (e["path"], e["constraint"]) for e in caught.value.results
    ]


# ── the chapter-9 handler gets a Decimal ─────────────────────────────────────


STRICT = """from decimal import Decimal


def notify_manager(entity: dict) -> dict:
    if type(entity["amount"]) is not Decimal:
        raise TypeError(f"amount is a {type(entity['amount']).__name__}")
    return {"recipient": "manager", "message": f"{entity['amount']}"}
"""


def test_verify_hands_the_handler_a_decimal(tmp_path):
    check = handler_result(_copy(tmp_path, STRICT), NOTIFY, OP, EX + "expense_train")
    assert check.ok, check.detail


def test_the_message_text_is_unchanged_by_a_decimal_amount(tmp_path):
    copy = _copy(tmp_path)
    target = resolve_handler(copy, NOTIFY)
    entity = handler_values(copy, ":ExpenseShape", {**EXPENSE, "amount": "250.00"})
    assert target(entity)["message"] == "Train to Leeds (250.00, 2026-10-01) is waiting for your approval."


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMS_HANDLERS", raising=False)
    with serve(CHAPTER, tmp_path, monkeypatch) as served:
        yield served


def test_the_worker_hands_the_handler_a_decimal(app, monkeypatch):
    c, runtime = app
    impl = runtime.implementations
    op = next(k for k in impl if str(k) == OP)
    kind, real = impl[op]
    seen = []

    def spy(entity):
        seen.append(entity["amount"])
        return real(entity)

    monkeypatch.setitem(impl, op, (kind, spy))
    r = c.post("/expenses/e1", data={**EXPENSE, "amount": "250.00"}, headers=ALICE)
    assert r.status_code == 200, r.text
    until(lambda: status(runtime, "e1") in ("waiting", "complete", "failed"))
    assert status(runtime, "e1") == "waiting", trace(runtime, "e1")
    assert seen == [Decimal("250.00")] and type(seen[0]) is Decimal
    [entity_id] = {r["task"]: r for r in trace(runtime, "e1")}["notify_manager"]["writes"]
    assert runtime.store.get_entity(entity_id)["data"]["message"] == (
        "Train to Leeds (250.00, 2026-10-01) is waiting for your approval."
    )
    [expense] = runtime.query(":ExpenseShape", expense="e1")
    assert expense["data"]["amount"] == "250.00"  # the stored expense stays JSON
