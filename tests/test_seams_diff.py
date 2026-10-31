"""`diff_models` classifies shape and operation-contract changes as compatible or breaking (M015/S01, D052).

Each test writes a small OLD and NEW TriG pair into tmp_path. Both share one
prefix block and differ only in the body of the shapes graph.
"""

import json
from pathlib import Path

import pytest
from seams_cli import ProjectError
from seams_cli.diff import Change, diff_models, to_json

EX = "https://example.org/m/"
PREFIXES = """\
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix :     <https://example.org/m/> .
"""

ITEM = """
:ItemShape a sh:NodeShape ;
    sh:property [ sh:path :name ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path :note ; sh:datatype xsd:string ; sh:maxCount 3 ] .
"""
OP = "\n:create_item seam:acceptsShape :ItemShape ; seam:returnsShape :ItemShape .\n"


def _trig(body: str) -> str:
    return PREFIXES + "<urn:seams:graph:shapes> {\n" + body + "\n}\n"


def _diff(tmp_path: Path, old: str, new: str) -> list[Change]:
    (tmp_path / "old.trig").write_text(_trig(old), encoding="utf-8")
    (tmp_path / "new.trig").write_text(_trig(new), encoding="utf-8")
    return diff_models(tmp_path / "old.trig", tmp_path / "new.trig")


def _only(changes: list[Change]) -> Change:
    assert len(changes) == 1, changes
    return changes[0]


def test_identical_models_give_no_changes(tmp_path):
    assert _diff(tmp_path, ITEM + OP, ITEM + OP) == []


def test_added_optional_property_is_compatible(tmp_path):
    new = ITEM.replace(" .\n", " ;\n    sh:property [ sh:path :tag ; sh:datatype xsd:string ] .\n")
    change = _only(_diff(tmp_path, ITEM, new))
    assert change == Change("compatible", "property-added", EX + "ItemShape", EX + "tag minCount 0", ("data",))


def test_added_required_property_is_breaking(tmp_path):
    new = ITEM.replace(" .\n", " ;\n    sh:property [ sh:path :tag ; sh:minCount 1 ] .\n")
    change = _only(_diff(tmp_path, ITEM, new))
    assert (change.verdict, change.kind, change.detail) == ("breaking", "property-added", EX + "tag minCount 1")


def test_removed_property_is_breaking(tmp_path):
    new = ITEM.replace(" ;\n    sh:property [ sh:path :note ; sh:datatype xsd:string ; sh:maxCount 3 ]", "")
    change = _only(_diff(tmp_path, ITEM, new))
    assert (change.verdict, change.kind, change.detail) == ("breaking", "property-removed", EX + "note")


def test_removed_shape_is_breaking_and_added_shape_compatible(tmp_path):
    other = "\n:OtherShape a sh:NodeShape .\n"
    changes = _diff(tmp_path, ITEM + other, ITEM.replace("ItemShape", "ThingShape"))
    assert [(c.verdict, c.kind, c.subject) for c in changes] == [
        ("breaking", "shape-removed", EX + "ItemShape"),
        ("breaking", "shape-removed", EX + "OtherShape"),
        ("compatible", "shape-added", EX + "ThingShape"),
    ]


def test_same_as_alias_is_a_rename_not_a_remove_and_add(tmp_path):
    new = ITEM.replace("ItemShape", "ThingShape") + "\n:ThingShape owl:sameAs :ItemShape .\n"
    new += OP.replace("ItemShape", "ThingShape")
    change = _only(_diff(tmp_path, ITEM + OP, new))
    assert change == Change(
        "compatible", "shape-renamed", EX + "ThingShape", f"{EX}ItemShape -> {EX}ThingShape", ("contract", "data")
    )


def test_rename_still_compares_properties(tmp_path):
    new = ITEM.replace("ItemShape", "ThingShape").replace("sh:maxCount 3", "sh:maxCount 2")
    new += "\n:ItemShape owl:sameAs :ThingShape .\n"
    changes = _diff(tmp_path, ITEM, new)
    assert [(c.verdict, c.kind, c.subject) for c in changes] == [
        ("breaking", "max-count-changed", EX + "ThingShape"),
        ("compatible", "shape-renamed", EX + "ThingShape"),
    ]


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        ("sh:datatype xsd:string ; sh:minCount 1", "sh:datatype xsd:integer ; sh:minCount 1", "datatype-changed"),
        ("sh:class :Person ; sh:minCount 1", "sh:class :Team ; sh:minCount 1", "class-changed"),
        ("sh:minCount 1", "sh:class :Person ; sh:minCount 1", "class-changed"),
    ],
)
def test_changed_or_added_datatype_and_class_are_breaking(tmp_path, old, new, kind):
    shape = ":S a sh:NodeShape ; sh:property [ sh:path :p ; {} ] ."
    change = _only(_diff(tmp_path, shape.format(old), shape.format(new)))
    assert (change.verdict, change.kind) == ("breaking", kind)


def test_dropped_datatype_is_compatible(tmp_path):
    shape = ":S a sh:NodeShape ; sh:property [ sh:path :p ; {} ] ."
    change = _only(_diff(tmp_path, shape.format("sh:datatype xsd:string"), shape.format("sh:minCount 0")))
    assert (change.verdict, change.kind, change.detail) == ("compatible", "datatype-changed", f"{EX}p {XSD}string -> -")


XSD = "http://www.w3.org/2001/XMLSchema#"


@pytest.mark.parametrize(
    ("old", "new", "kind", "verdict"),
    [
        ("sh:minCount 0", "sh:minCount 1", "min-count-changed", "breaking"),
        ("sh:minCount 2", "sh:minCount 1", "min-count-changed", "compatible"),
        ("sh:maxCount 3", "sh:maxCount 1", "max-count-changed", "breaking"),
        ("sh:maxCount 1", "sh:maxCount 3", "max-count-changed", "compatible"),
        ("sh:maxCount 1", "sh:minCount 0", "max-count-changed", "compatible"),
        ("sh:minCount 0", "sh:maxCount 1", "max-count-changed", "breaking"),
    ],
)
def test_tighter_cardinality_is_breaking_and_looser_compatible(tmp_path, old, new, kind, verdict):
    shape = ":S a sh:NodeShape ; sh:property [ sh:path :p ; {} ] ."
    change = _only(_diff(tmp_path, shape.format(old), shape.format(new)))
    assert (change.verdict, change.kind) == (verdict, kind)


def test_shape_change_is_in_contract_scope_when_an_operation_uses_it(tmp_path):
    tighter = ITEM.replace("sh:maxCount 3", "sh:maxCount 2")
    assert _only(_diff(tmp_path, ITEM, tighter)).scopes == ("data",)
    assert _only(_diff(tmp_path, ITEM + OP, tighter + OP)).scopes == ("contract", "data")
    # An operation in only one of the two models is enough.
    changes = _diff(tmp_path, ITEM + OP, tighter)
    assert [(c.kind, c.scopes) for c in changes] == [
        ("max-count-changed", ("contract", "data")),
        ("operation-removed", ("contract",)),
    ]


def test_added_operation_is_compatible_and_removed_breaking(tmp_path):
    added = _only(_diff(tmp_path, ITEM, ITEM + OP))
    assert added == Change("compatible", "operation-added", EX + "create_item", "-", ("contract",))
    removed = _only(_diff(tmp_path, ITEM + OP, ITEM))
    assert (removed.verdict, removed.kind, removed.subject) == ("breaking", "operation-removed", EX + "create_item")


def test_changed_accepts_or_returns_target_is_breaking(tmp_path):
    shapes = ITEM + "\n:OtherShape a sh:NodeShape .\n"
    new = OP.replace("seam:acceptsShape :ItemShape", "seam:acceptsShape :OtherShape")
    change = _only(_diff(tmp_path, shapes + OP, shapes + new))
    assert change == Change(
        "breaking", "accepts-changed", EX + "create_item", f"{EX}ItemShape -> {EX}OtherShape", ("contract",)
    )
    dropped = OP.replace("; seam:returnsShape :ItemShape", "")
    change = _only(_diff(tmp_path, shapes + OP, shapes + dropped))
    assert (change.kind, change.detail) == ("returns-changed", f"{EX}ItemShape -> -")


def test_unloadable_model_raises_project_error(tmp_path):
    (tmp_path / "old.trig").write_text(_trig(ITEM), encoding="utf-8")
    (tmp_path / "bad.trig").write_text("this is not trig {", encoding="utf-8")
    with pytest.raises(ProjectError, match="cannot load the model"):
        diff_models(tmp_path / "old.trig", tmp_path / "bad.trig")
    with pytest.raises(ProjectError, match="cannot load the model"):
        diff_models(tmp_path / "missing.trig", tmp_path / "old.trig")


def test_to_json_is_sorted_and_counts_verdicts(tmp_path):
    new = ITEM.replace("sh:maxCount 3", "sh:maxCount 2") + "\n:ZShape a sh:NodeShape .\n" + OP
    changes = _diff(tmp_path, ITEM, new)
    result = to_json(reversed(changes))
    assert result == to_json(changes)
    assert result["counts"] == {"breaking": 1, "compatible": 2}
    assert [c["kind"] for c in result["changes"]] == ["max-count-changed", "shape-added", "operation-added"]
    assert result["changes"][0]["scopes"] == ["contract", "data"]
    json.dumps(result)
