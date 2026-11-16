"""Event-storm import (backlog X12, ADR-0046): ``seams_gen.storm_import`` reads a
big-picture storm into a skeleton model that ``seams_gen.storm`` derives back.

The fixture is the expense tutorial's approval_process storm (tests/golden/storm/
approval_process.md) cut down by hand to its big-picture stickies. The golden is the
TriG skeleton it imports to. Regenerate it deliberately with
``uv run python tests/test_storm_import.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import seams
from lxml import etree
from rdflib import Dataset
from seams import local_name

from seams_edit import Patch, PatchError, create
from seams_gen import GeneratorError
from seams_gen.storm import derive
from seams_gen.storm_import import bpmn_payload, parse, to_patch, write
from seams_gen.testing import ONTOLOGY_DIR, SHAPES_FILE, shape_violations

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "storm_import" / "approval.md"
GOLDEN = ROOT / "tests" / "golden" / "storm_import" / "approval_skeleton.trig"
ONTOLOGY_FILES = sorted(ONTOLOGY_DIR.glob("*.ttl"))
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


def _draft():
    return parse(FIXTURE.read_text(encoding="utf-8"))


def _import(where: Path) -> tuple[Path, tuple[str, ...]]:
    out = where / "approval_skeleton.trig"
    return out, write(_draft(), out)


def test_skeleton_matches_the_golden(tmp_path):
    out, _ = _import(tmp_path)
    assert out.read_bytes() == GOLDEN.read_bytes()


def test_payload_holds_the_bpmn_steps_in_step_order(tmp_path):
    out, _ = _import(tmp_path)
    payload = tmp_path / "approval_process.bpmn"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([out.name, payload.name])
    assert payload.read_text(encoding="utf-8") == bpmn_payload(_draft())
    (process,) = etree.parse(str(payload)).getroot()
    assert process.get("id") == "approval_process"
    assert [(n.tag.removeprefix(BPMN), n.get("id")) for n in process] == [
        ("serviceTask", "persist_expense"),
        ("businessRuleTask", "route_expense"),
        ("serviceTask", "notify_manager"),
        ("userTask", "approve_expense"),
        ("userTask", "finance_approve_expense"),
        ("serviceTask", "record_approval"),
        ("userTask", "pay_expense"),
        ("serviceTask", "record_rejection"),
    ]


def test_import_is_deterministic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one, gaps_one = _import(tmp_path / "a")
    two, gaps_two = _import(tmp_path / "b")
    assert one.read_bytes() == two.read_bytes()
    assert (one.parent / "approval_process.bpmn").read_bytes() == (two.parent / "approval_process.bpmn").read_bytes()
    assert gaps_one == gaps_two
    assert to_patch(_draft(), one) == to_patch(_draft(), one)


def test_seam_edges_are_only_in_the_seams_graph(tmp_path):
    out, _ = _import(tmp_path)
    ds = Dataset()
    ds.parse(str(out), format="trig")
    seam = "https://w3id.org/seams/seam#"
    for s, p, o, g in ds.quads((None, None, None, None)):
        if str(p).startswith(seam) and str(p) != seam + "inModel":
            assert str(g) == "urn:seams:graph:seams", (s, p, o, g)


def test_round_trip_derives_the_imported_storm(tmp_path):
    draft = _draft()
    out, gaps = _import(tmp_path)
    storm = derive(seams.load(out), "approval_process")

    assert storm.label == draft.label
    assert [s.name for s in storm.steps] == [s.label for s in draft.steps]
    assert [local_name(s.iri) for s in storm.steps] == [s.name for s in draft.steps]

    def stickies(kind: str) -> list[tuple[int, str]]:
        return [(s.index, e.name) for s in draft.steps for e in s.of(kind)]

    assert [(e.step, local_name(e.iri)) for e in storm.actors] == stickies("actor")
    assert [(e.step, local_name(e.iri)) for e in storm.commands] == stickies("command")
    assert [(e.step, local_name(e.iri)) for e in storm.aggregates] == stickies("aggregate")
    assert [(e.step, local_name(e.iri)) for e in storm.events] == stickies("domain event")
    assert [(e.step, local_name(e.iri)) for e in storm.decisions] == stickies("policy")
    assert [e.text for e in storm.commands][:1] == ["Submit Expense (`submit_expense`)"]
    assert storm.channels == () and storm.processes == () and storm.read_models == ()

    assert gaps[: len(storm.gaps)] == storm.gaps
    assert "submit_expense has no seam:submitsTo operation" in gaps
    assert "ApprovalShape has no read model: no ifml page or component seam:reads it" in gaps
    assert [g for g in gaps if g not in storm.gaps] == [
        "approval_process has no sequence flows: approval_process.bpmn lists its BPMN steps in step order, unjoined",
        "approval_process has no start event in approval_process.bpmn",
        "approval_process has no end event in approval_process.bpmn",
    ]


def test_shapes_flag_the_skeleton_without_raising(tmp_path):
    out, _ = _import(tmp_path)
    ds = Dataset(default_union=True)
    ds.parse(str(out), format="trig")
    violations = shape_violations(ds, SHAPES_FILE, ONTOLOGY_FILES)
    assert violations
    focus = {local_name(f) for f, _, _ in violations}
    assert focus & {"submit_expense", "approve_form", "approval_process"}, sorted(focus)


def test_write_refuses_an_existing_file_and_writes_nothing(tmp_path):
    out = tmp_path / "model.trig"
    out.write_text("# hand-written\n", encoding="utf-8")
    with pytest.raises(PatchError, match="already exists"):
        write(_draft(), out)
    assert out.read_text(encoding="utf-8") == "# hand-written\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.trig"]


def test_write_refuses_an_existing_payload_and_writes_nothing(tmp_path):
    payload = tmp_path / "approval_process.bpmn"
    payload.write_text("<x/>\n", encoding="utf-8")
    with pytest.raises(PatchError, match="already exists"):
        write(_draft(), tmp_path / "model.trig")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["approval_process.bpmn"]
    assert payload.read_text(encoding="utf-8") == "<x/>\n"


HEAD = "# Event storm: Expense Approval (`approval_process`)\n\n<!-- base: https://example.org/expenses/ -->\n\n## Timeline\n\n"
TRIGGER = "1. **Submit Expense** (`submit_expense`)\n   - actor: Employee (`employee`)\n   - command: Submit Expense (`submit_expense`)\n"

MALFORMED = [
    pytest.param(
        HEAD
        + TRIGGER.replace("submit_expense", "z_submit")
        + TRIGGER.replace("1.", "2.").replace("Employee", "E2").replace("employee", "e2"),
        10,
        "2. **Submit Expense** (`submit_expense`)",
        "IRI order",
        id="trigger-order",
    ),
    pytest.param("Event storm\n", 1, "Event storm", "expected the heading", id="heading"),
    pytest.param(
        "# Event storm: Expense Approval (`approval process`)\n",
        1,
        "# Event storm: Expense Approval (`approval process`)",
        "is not a BPMN id",
        id="process-name",
    ),
    pytest.param(
        "# Event storm: E (`p`)\n<!-- base: example.org/ -->\n",
        2,
        "<!-- base: example.org/ -->",
        "not an absolute IRI",
        id="base-relative",
    ),
    pytest.param(
        "# Event storm: E (`p`)\n<!-- base: https://example.org/x -->\n",
        2,
        "<!-- base: https://example.org/x -->",
        "ending in / or #",
        id="base-no-separator",
    ),
    pytest.param(
        "# Event storm: E (`p`)\n<!-- base: https://example.org/ -->\n## Steps\n",
        3,
        "## Steps",
        "## Timeline",
        id="no-timeline",
    ),
    pytest.param(
        HEAD + "   - actor: Employee (`employee`)\n",
        7,
        "- actor: Employee (`employee`)",
        "before the first step",
        id="entry-first",
    ),
    pytest.param(
        HEAD + TRIGGER + "3. **Persist** (`persist`)\n",
        10,
        "3. **Persist** (`persist`)",
        "out of sequence",
        id="numbering",
    ),
    pytest.param(
        HEAD + TRIGGER + "   - actr: Manager (`manager`)\n",
        10,
        "- actr: Manager (`manager`)",
        "unknown entry kind",
        id="kind",
    ),
    pytest.param(
        HEAD + TRIGGER + "   - actor: Manager\n", 10, "- actor: Manager", "expected - actor: <label>", id="no-name"
    ),
    pytest.param(
        HEAD
        + "1. **Submit Expense** (`submit_expense`)\n   - command: Submit Expense (`submit_expense`) → POST `op`\n",
        8,
        "→ POST `op`",
        "operation",
        id="operation-tail",
    ),
    pytest.param(HEAD + TRIGGER + "Some prose.\n", 10, "Some prose.", "expected a numbered step", id="prose"),
    pytest.param(HEAD + "1. **Persist** (`persist`)\n", 7, "1. **Persist** (`persist`)", "no entry", id="empty-step"),
    pytest.param(
        HEAD + "1. **Persist** (`persist`)\n   - aggregate: Expense (`ExpenseShape`)\n" + TRIGGER.replace("1.", "2."),
        9,
        "2. **Submit Expense** (`submit_expense`)",
        "comes before every BPMN step",
        id="trigger-after-bpmn",
    ),
    pytest.param(
        HEAD
        + "1. **Persist** (`persist`)\n   - actor: Employee (`employee`)\n   - aggregate: Expense (`ExpenseShape`)\n",
        8,
        "- actor: Employee (`employee`)",
        "an actor needs",
        id="actor-without-form",
    ),
    pytest.param(
        HEAD + TRIGGER + "   - aggregate: Expense (`ExpenseShape`)\n",
        10,
        "- aggregate: Expense (`ExpenseShape`)",
        "a trigger step",
        id="aggregate-on-trigger",
    ),
    pytest.param(
        HEAD + "1. **Approve** (`approve`)\n   - command: Approve (`approval`) on `form`\n",
        8,
        "- command: Approve (`approval`) on `form`",
        "the command's name must be the step's",
        id="command-name",
    ),
    pytest.param(
        HEAD + "1. **Route** (`route`)\n   - command: Route (`route`) on `form`\n   - policy: Rule (`rule`)\n",
        9,
        "- policy: Rule (`rule`)",
        "not both",
        id="command-and-policy",
    ),
    pytest.param(
        HEAD + TRIGGER + "2. **Persist** (`persist`)\n   - aggregate: Employee (`employee`)\n",
        11,
        "- aggregate: Employee (`employee`)",
        "is an actor already",
        id="name-two-kinds",
    ),
    pytest.param(
        HEAD
        + TRIGGER
        + "2. **Approve** (`approve`)\n   - actor: Staff (`employee`)\n   - command: Approve (`approve`) on `f`\n",
        11,
        "- actor: Staff (`employee`)",
        "labelled 'Employee' already",
        id="label-disagrees",
    ),
    pytest.param(
        HEAD + "1. **Persist** (`persist`)\n   - aggregate: Approval (`approval_process_data`)\n",
        8,
        "- aggregate: Approval (`approval_process_data`)",
        "the data model already",
        id="minted-name",
    ),
    pytest.param(
        HEAD.replace("## Timeline\n\n", ""),
        5,
        "",
        "end of file: expected ## Timeline",
        id="eof",
    ),
    pytest.param(HEAD + "## Gaps\n", 5, "## Timeline", "no step", id="no-steps"),
]


@pytest.mark.parametrize(("text", "line", "quoted", "detail"), MALFORMED)
def test_malformed_storm_names_the_line(text, line, quoted, detail):
    with pytest.raises(GeneratorError) as raised:
        parse(text)
    error = raised.value
    assert error.subject == f"line {line}"
    assert quoted in error.predicate
    assert detail in error.detail


def test_create_refuses_a_malformed_payload_and_writes_nothing(tmp_path):
    out = tmp_path / "model.trig"
    with pytest.raises(PatchError, match="not well-formed XML"):
        create(out, to_patch(_draft(), out), prefixes={}, payloads={tmp_path / "p.bpmn": "<open>"})
    assert list(tmp_path.iterdir()) == []


def test_create_refuses_a_patch_that_removes(tmp_path):
    out = tmp_path / "model.trig"
    quad = to_patch(_draft(), out).adds[0]
    with pytest.raises(PatchError, match="nothing to remove"):
        create(out, Patch(removes=[quad]), prefixes={})
    assert list(tmp_path.iterdir()) == []


def test_trailing_derived_sections_are_skipped():
    text = FIXTURE.read_text(encoding="utf-8")
    assert "## Gaps" in text
    head = text.split("## Gaps", 1)[0]
    assert parse(text) == parse(head)


def _regenerate() -> None:
    with tempfile.TemporaryDirectory() as where:
        out, _ = _import(Path(where))
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(out.read_bytes())
    print(f"wrote {GOLDEN.relative_to(ROOT)}")


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--regenerate"]):
        raise SystemExit("usage: python tests/test_storm_import.py")
    _regenerate()
