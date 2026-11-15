"""The CI shard guard (tests/ci/check_shards.py) names every coverage defect."""

from tests.ci.check_shards import compare, parse_node_ids


def test_exact_cover_passes() -> None:
    assert compare(["a::x", "b::y", "c::z"], [["a::x"], ["c::z", "b::y"], [], []]) == []


def test_dropped_node_id_is_named() -> None:
    assert compare(["a::x", "b::y"], [["a::x"], []]) == ["missing from every shard: b::y"]


def test_duplicate_across_shards_is_named() -> None:
    assert compare(["a::x", "b::y"], [["a::x", "b::y"], ["b::y"]]) == ["collected by 2 shards: b::y"]


def test_extra_node_id_is_named() -> None:
    assert compare(["a::x"], [["a::x", "z::q"]]) == ["in a shard but not the serial collection: z::q"]


def test_empty_collection_fails() -> None:
    assert compare([], [[], []]) == ["serial collection is empty: no node IDs to compare"]


def test_parse_keeps_only_node_ids() -> None:
    out = "tests/test_a.py::test_x\ntests/test_a.py::test_y[1]\n\n12 tests collected in 0.5s\n"
    assert parse_node_ids(out) == ["tests/test_a.py::test_x", "tests/test_a.py::test_y[1]"]
