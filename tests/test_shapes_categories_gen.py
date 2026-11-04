"""Generators and the runtime read ADR-0023 shapes through ``Field`` and produce
what they produce for today's notation.

The model is ``test_shapes_categories.model()``: ``:ExpenseShape`` (ontology
paths with ``sh:name``, a flattened ``sh:node`` amount and an ``:ExpenseState``
category status) beside ``:OldExpenseShape`` (flat paths and a copied string
``sh:in``). Each extract step and each runtime check is run on both and must
agree: the htmx fields, inputs and bindings, the handler stub's ``TypedDict``,
the problem+json schema, the runtime contract's keys, its lowered graph, its
accepted payloads and its 422 results, and a JSON response check. Negative
cases name the fact: a parameter bound to no field, an empty category and an
ambiguous ``sh:node`` reached through the runtime."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import XSD, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from seams import ResolutionError  # noqa: E402
from test_shapes_categories import EX, GIST, LIFECYCLE_BODY, ONTOLOGY, SHAPES_BODY, model  # noqa: E402

from seams_gen.fastapi import _problem_schema  # noqa: E402
from seams_gen.htmx import _bound, _fields, _input, _task_input  # noqa: E402
from seams_gen.stubs import _stub_class  # noqa: E402
from seams_runtime.contracts import shape_contract, validate  # noqa: E402
from seams_runtime.errors import ContractViolation  # noqa: E402
from seams_runtime.model import ModelGraph  # noqa: E402
from seams_runtime.verify import response_conforms  # noqa: E402

NEW, OLD = "ExpenseShape", "OldExpenseShape"
GOOD = {"description": "Team lunch", "amount": "42.50", "status": "submitted"}


def load(tmp_path: Path, text: str | None = None) -> ModelGraph:
    path = tmp_path / "model.trig"
    path.write_text(model() if text is None else text, encoding="utf-8")
    return ModelGraph(path, ontology_dir=ONTOLOGY)


@pytest.fixture
def m(tmp_path: Path) -> ModelGraph:
    return load(tmp_path)


def shape(m: ModelGraph, name: str):
    return m.shape(EX[name])


def no_origin(value):
    """A dataclass with its trace origin (the shape's IRI) blanked."""
    return dataclasses.replace(value, iri="")


def results(m: ModelGraph, name: str, payload: dict) -> list[tuple]:
    """(path, constraint, value) of each result of a refused payload."""
    with pytest.raises(ContractViolation) as caught:
        validate(m, EX[name], payload)
    return [(r["path"], r["constraint"], r["value"]) for r in caught.value.results]


# ── htmx ──


def test_htmx_fields_are_the_same_for_both_notations(m: ModelGraph) -> None:
    new, old = _fields(shape(m, NEW)), _fields(shape(m, OLD))
    assert [no_origin(f) for f in new] == [no_origin(f) for f in old]
    assert [f.name for f in new] == ["description", "amount", "status"]
    assert new[2].kind == "enum"
    assert new[2].options == ("draft", "submitted", "approved", "rejected", "paid")


def test_htmx_inputs_render_the_same_for_both_notations(m: ModelGraph) -> None:
    for new, old in zip(_fields(shape(m, NEW)), _fields(shape(m, OLD)), strict=True):
        assert no_origin(_input("expense", new)) == no_origin(_input("expense", old))
        assert no_origin(_task_input("expense", new)) == no_origin(_task_input("expense", old))
    status = _task_input("expense", _fields(shape(m, NEW))[2])
    assert (status.element, status.name, status.options) == (
        "select",
        "status",
        ("draft", "submitted", "approved", "rejected", "paid"),
    )


def bindings(*paths: URIRef) -> list[SimpleNamespace]:
    return [SimpleNamespace(iri=EX[f"p{i}"], bound_to=path) for i, path in enumerate(paths)]


def test_a_parameter_bound_to_a_path_takes_the_field_name(m: ModelGraph) -> None:
    new = _bound(bindings(GIST.hasMagnitude, GIST.isCategorizedBy, GIST.description), shape(m, NEW))
    old = _bound(bindings(EX.amount, EX.status, EX.description), shape(m, OLD))
    assert new == old == ({"amount", "status", "description"}, None)


def test_a_parameter_bound_to_no_field_is_named_with_its_path(m: ModelGraph) -> None:
    # :amount is the old shape's path; in the new shape the field named
    # "amount" is on gist:hasMagnitude, so binding by name does not count.
    # The caller raises GeneratorError(parameter, ifml:boundTo) with these.
    assert _bound(bindings(GIST.description, EX.amount), shape(m, NEW)) == ({"description"}, ("amount", EX.p1))


# ── stubs and the problem schema ──


def test_the_handler_stub_has_the_same_keys_and_types(m: ModelGraph) -> None:
    new, old = _stub_class(m, shape(m, NEW)), _stub_class(m, shape(m, OLD))
    assert [(f.name, f.annotation) for f in new.fields] == [(f.name, f.annotation) for f in old.fields]
    assert [f.name for f in new.fields] == ["description", "amount", "status"]


def test_the_problem_schema_is_the_same(m: ModelGraph) -> None:
    assert _problem_schema(shape(m, NEW)) == _problem_schema(shape(m, OLD))


# ── the runtime contract ──


def test_the_contract_keys_fields_by_name(m: ModelGraph) -> None:
    new, old = shape_contract(m, EX[NEW]), shape_contract(m, EX[OLD])
    assert sorted(new.fields) == sorted(old.fields)
    assert {k: v[1] for k, v in new.fields.items()} == {k: v[1] for k, v in old.fields.items()}
    assert new.fields["amount"][0] == GIST.hasMagnitude
    assert new.fields["status"][0] == GIST.isCategorizedBy
    assert new.names == {GIST.description: "description", GIST.hasMagnitude: "amount", GIST.isCategorizedBy: "status"}


def test_the_contract_graph_is_lowered_to_the_wire(m: ModelGraph) -> None:
    g = shape_contract(m, EX[NEW]).graph
    assert (EX[NEW], SH.targetClass, None) not in g
    props = {g.value(p, SH.path): p for p in g.objects(EX[NEW], SH.property)}
    amount, status = props[GIST.hasMagnitude], props[GIST.isCategorizedBy]
    assert g.value(amount, SH.node) is None
    assert g.value(amount, SH.datatype) == XSD.decimal
    assert g.value(amount, SH.minInclusive) == Literal("0.01", datatype=XSD.decimal)
    # the outer property's counts stay, the free property's are not added twice
    assert sorted(int(v) for v in g.objects(amount, SH.maxCount)) == [1]
    assert g.value(status, SH["class"]) is None
    assert g.value(status, SH.datatype) == XSD.string
    listed = [str(v) for v in Collection(g, g.value(status, SH["in"]))]
    assert listed == ["draft", "submitted", "approved", "rejected", "paid"]
    # the cached model graph itself is not rewritten
    assert (EX[NEW], SH.targetClass, EX.Expense) in m.ds


def test_both_notations_accept_the_same_payload(m: ModelGraph) -> None:
    assert validate(m, EX[NEW], GOOD) == validate(m, EX[OLD], GOOD) == GOOD


@pytest.mark.parametrize(
    "payload",
    [
        {**GOOD, "status": "late"},
        {**GOOD, "amount": "abc"},
        {"description": "Team lunch"},
        {**GOOD, "colour": "red"},
        {**GOOD, "status": ["draft", "paid"]},
    ],
    ids=["unknown-state", "not-decimal", "missing", "unknown-field", "two-states"],
)
def test_both_notations_refuse_a_bad_payload_with_the_same_results(m: ModelGraph, payload: dict) -> None:
    assert results(m, NEW, payload) == results(m, OLD, payload)


def test_a_wrong_state_is_an_in_constraint_on_the_field_name(m: ModelGraph) -> None:
    assert results(m, NEW, {**GOOD, "status": "late"}) == [("status", "InConstraintComponent", "late")]


def test_a_flattened_field_keeps_the_free_propertys_value_constraints(m: ModelGraph) -> None:
    # :MoneyShape's gist:numericValue has sh:minInclusive 0.01 (the old shape has none)
    assert results(m, NEW, {**GOOD, "amount": "0"}) == [("amount", "MinInclusiveConstraintComponent", "0")]


def test_a_json_response_conforms_the_same_way(m: ModelGraph) -> None:
    for name in (NEW, OLD):
        assert response_conforms(m, str(EX[name]), GOOD)[0], name
        assert not response_conforms(m, str(EX[name]), {**GOOD, "status": "late"})[0], name
    assert not response_conforms(m, str(EX[NEW]), {**GOOD, "amount": "0"})[0]


def test_an_empty_category_fails_the_contract_naming_the_field(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY.replace(" , :ExpenseState", "")
    m = load(tmp_path, model(lifecycle=lifecycle))
    with pytest.raises(ResolutionError) as err:
        shape_contract(m, EX[NEW])
    assert (err.value.subject, err.value.predicate) == (str(EX[NEW]), str(SH["class"]))
    assert "status: category :ExpenseState has no members" in str(err.value)


def test_an_ambiguous_sh_node_fails_the_contract_naming_the_field(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:hasValue :USD", "sh:maxCount 1")
    m = load(tmp_path, model(shapes=shapes))
    with pytest.raises(ResolutionError) as err:
        shape_contract(m, EX[NEW])
    assert (err.value.subject, err.value.predicate) == (str(EX[NEW]), str(SH.node))
    assert "amount: :MoneyShape has 2 free properties" in str(err.value)
