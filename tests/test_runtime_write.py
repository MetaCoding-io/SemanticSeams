"""Runtime.write (D026): an operation that triggers no process persists the
validated entity itself. A valid payload is stored with its initial lifecycle
status and returned in the row form query() returns; an invalid one raises
ContractViolation naming the path and stores nothing. A shape with a required
:id (the identifier convention) gets the new entity's id, which no form sends.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processless_model import EXPENSES, write_model  # noqa: E402

from seams_runtime import ContractViolation, ModelGraph, Runtime  # noqa: E402
from seams_runtime.fragments import flatten  # noqa: E402

SHAPE = EXPENSES + "ExpenseShape"


@pytest.fixture
def runtime(make_store, tmp_path):
    model = ModelGraph.load(write_model(tmp_path))
    return Runtime(model, make_store(), templates_dir=tmp_path)


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


@pytest.mark.parametrize(
    "payload, path",
    [
        ({}, "description"),
        ({"description": "x" * 201}, "description"),
        ({"description": "Lunch", "status": "paid"}, "status"),
    ],
    ids=["missing-required", "too-long", "status-not-in-list"],
)
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


ID_SHAPE_TRIG = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix :     <https://example.org/expenses/> .

<urn:seams:graph:model:expense_data> {
    :expense_data a seam:Model ; rdfs:label "Expense Data" .
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:property [ sh:path :id ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
        sh:property [ sh:path :description ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
        seam:inModel :expense_data .
}
"""


@pytest.fixture
def id_runtime(make_store, tmp_path):
    trig = tmp_path / "ids.trig"
    trig.write_text(ID_SHAPE_TRIG, encoding="utf-8")
    return Runtime(ModelGraph.load(trig), make_store(), templates_dir=tmp_path)


def test_required_id_is_assigned_by_the_runtime(id_runtime):
    stored = id_runtime.write(":ExpenseShape", {"description": "Taxi"})
    assert stored["data"] == {"description": "Taxi", "id": stored["id"]}
    assert flatten(stored)["id"] == stored["id"]


def test_sent_id_is_replaced_not_upserted(id_runtime):
    first = id_runtime.write(":ExpenseShape", {"description": "Taxi"})
    second = id_runtime.write(":ExpenseShape", {"description": "Hijack", "id": first["id"]})
    assert second["id"] != first["id"] and second["data"]["id"] == second["id"]
    assert [e["data"]["description"] for e in id_runtime.query(":ExpenseShape")] == ["Taxi", "Hijack"]


def test_assigned_id_does_not_mask_other_violations(id_runtime):
    with pytest.raises(ContractViolation) as err:
        id_runtime.write(":ExpenseShape", {})
    assert [r["path"] for r in err.value.results] == ["description"]
    assert id_runtime.query(":ExpenseShape") == []
