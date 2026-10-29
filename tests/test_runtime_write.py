"""Runtime.write (D026): an operation that triggers no process persists the
validated entity itself. A valid payload is stored with its initial lifecycle
status and returned in the row form query() returns; an invalid one raises
ContractViolation naming the path and stores nothing.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processless_model import EXPENSES, write_model  # noqa: E402
from seams_runtime import ContractViolation, ModelGraph, Runtime, Store  # noqa: E402
from seams_runtime.fragments import flatten  # noqa: E402

SHAPE = EXPENSES + "ExpenseShape"


@pytest.fixture
def runtime(tmp_path):
    model = ModelGraph.load(write_model(tmp_path))
    return Runtime(model, Store(tmp_path / "seams.sqlite"), templates_dir=tmp_path)


def test_valid_payload_is_persisted_and_queryable(runtime):
    stored = runtime.write(":ExpenseShape", {"description": "Train to Leeds"})
    assert stored["shape"] == SHAPE
    assert stored["data"] == {"description": "Train to Leeds", "status": "draft"}
    assert stored["status"] == "draft"
    assert stored["correlation_key"] is None and stored["instance_id"] is None
    assert runtime.query(":ExpenseShape") == [stored]
    assert flatten(stored) == {"description": "Train to Leeds", "status": "draft", "id": stored["id"]}


def test_each_write_is_a_new_entity(runtime):
    a = runtime.write(":ExpenseShape", {"description": "Taxi"})
    b = runtime.write(":ExpenseShape", {"description": "Taxi"})
    assert a["id"] != b["id"]
    assert [e["id"] for e in runtime.query(":ExpenseShape")] == [a["id"], b["id"]]


def test_payload_status_overrides_the_initial_state(runtime):
    stored = runtime.write(":ExpenseShape", {"description": "Hotel", "status": "submitted"})
    assert stored["status"] == stored["data"]["status"] == "submitted"


@pytest.mark.parametrize("payload, path", [
    ({}, "description"),
    ({"description": "x" * 201}, "description"),
    ({"description": "Lunch", "status": "paid"}, "status"),
], ids=["missing-required", "too-long", "status-not-in-list"])
def test_invalid_payload_raises_and_stores_nothing(runtime, payload, path):
    with pytest.raises(ContractViolation) as err:
        runtime.write(":ExpenseShape", payload)
    assert err.value.http_status == 422
    assert [r["path"] for r in err.value.results] == [path]
    assert runtime.query(":ExpenseShape") == []


def test_unknown_field_is_rejected(runtime):
    with pytest.raises(ContractViolation):
        runtime.write(":ExpenseShape", {"description": "Lunch", "amount_due": "12"})
    assert runtime.query(":ExpenseShape") == []
