"""``seams diff`` names the downstream contexts a change reaches (M029/S01/T03, ADR-0032 section 2).

Each test diffs scratch copies of expenses chapter 11, where expense is upstream of
finance (``:expense_to_finance``, conformist). A breaking change to a shape the expense
context owns reaches finance; a change to a shape finance owns reaches no context, and
a model with no relationship reports no contexts at all.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from seams_cli.__main__ import main
from seams_cli.diff import BREAKING, COMPATIBLE, Change, diff_models, downstream, to_json

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"
EX = "https://example.org/expenses/"
FINANCE = EX + "finance_context"

AMOUNT = 'sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal ;'
RELATIONSHIP = """    :expense_to_finance a arch:ContextRelationship ;
        arch:upstream :expense_context ;
        arch:downstream :finance_context ;
        arch:relationshipType arch:Conformist .
"""
EXPENSE_DATA = '    :expense_data a seam:Model ; rdfs:label "Expense Data" .\n'
FINANCE_CONSOLE = "    :finance_console a seam:Model , ifml:InteractionModel ;\n"
# Shapes with no seam:inModel: each is in the model its graph declares.
AUDIT = """
    :AuditShape a sh:NodeShape ;
        sh:property [ sh:path :auditor ; sh:datatype xsd:string ; sh:maxCount 1 ] .
"""
# finance.trig binds no sh: or xsd: prefix.
LEDGER = """
    :LedgerShape a <http://www.w3.org/ns/shacl#NodeShape> ;
        <http://www.w3.org/ns/shacl#property> [ <http://www.w3.org/ns/shacl#path> :entry ;
            <http://www.w3.org/ns/shacl#maxCount> 1 ] .
"""


def _copy(tmp_path: Path, name: str) -> Path:
    copy = tmp_path / name
    shutil.copytree(CHAPTER, copy, ignore=shutil.ignore_patterns("generated", "__pycache__"))
    return copy


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_a_breaking_expense_shape_change_reaches_finance(tmp_path):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(new / "expenses.trig", AMOUNT, AMOUNT.replace("xsd:decimal", "xsd:integer"))
    changes = diff_models(old, new)
    assert changes == [
        Change(
            BREAKING,
            "datatype-changed",
            EX + "ExpenseShape",
            f"{EX}amount http://www.w3.org/2001/XMLSchema#decimal -> http://www.w3.org/2001/XMLSchema#integer",
            ("contract", "data"),
            (FINANCE,),
        )
    ]
    assert downstream(changes) == {FINANCE: changes}


def test_the_text_output_has_a_section_per_downstream_context(tmp_path, capsys):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(new / "expenses.trig", AMOUNT, AMOUNT.replace("xsd:decimal", "xsd:integer"))
    assert main(["diff", str(old), str(new)]) == 1
    out = capsys.readouterr()
    line = "breaking datatype-changed :ExpenseShape :amount xsd:decimal -> xsd:integer"
    assert out.out.splitlines() == [line, "downstream :finance_context", "  " + line]
    assert out.err.strip() == "seams diff: 1 breaking, 0 compatible"


def test_the_json_output_lists_each_changes_contexts(tmp_path, capsys):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(new / "expenses.trig", AMOUNT, AMOUNT.replace("xsd:decimal", "xsd:integer"))
    assert main(["diff", str(old), str(new), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [c["contexts"] for c in report["changes"]] == [[FINANCE]]
    assert report == to_json(diff_models(old, new))


def test_a_removed_shape_reaches_the_downstream_of_its_old_graphs_model(tmp_path):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(old / "expenses.trig", EXPENSE_DATA, EXPENSE_DATA + AUDIT)
    changes = diff_models(old, new)
    assert changes == [Change(BREAKING, "shape-removed", EX + "AuditShape", "-", ("data",), (FINANCE,))]


def test_a_compatible_change_names_its_contexts_but_has_no_section(tmp_path, capsys):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(new / "expenses.trig", EXPENSE_DATA, EXPENSE_DATA + AUDIT)
    changes = diff_models(old, new)
    assert changes == [Change(COMPATIBLE, "shape-added", EX + "AuditShape", "-", ("data",), (FINANCE,))]
    assert downstream(changes) == {}
    assert main(["diff", str(old), str(new)]) == 0
    assert capsys.readouterr().out.splitlines() == ["compatible shape-added :AuditShape -"]


def test_a_downstream_shape_change_reaches_no_context(tmp_path, capsys):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    _edit(old / "finance.trig", FINANCE_CONSOLE, LEDGER + FINANCE_CONSOLE)
    _edit(new / "finance.trig", FINANCE_CONSOLE, LEDGER.replace("shacl#maxCount", "shacl#minCount") + FINANCE_CONSOLE)
    changes = diff_models(old, new)
    assert [(c.verdict, c.kind, c.subject, c.contexts) for c in changes] == [
        (COMPATIBLE, "max-count-changed", EX + "LedgerShape", ()),
        (BREAKING, "min-count-changed", EX + "LedgerShape", ()),
    ]
    assert main(["diff", str(old), str(new)]) == 1
    assert not any(line.startswith("downstream") for line in capsys.readouterr().out.splitlines())


def test_without_a_relationship_no_change_has_contexts(tmp_path, capsys):
    old, new = _copy(tmp_path, "old"), _copy(tmp_path, "new")
    for copy in (old, new):
        _edit(copy / "expenses.trig", RELATIONSHIP, "")
    _edit(new / "expenses.trig", AMOUNT, AMOUNT.replace("xsd:decimal", "xsd:integer"))
    changes = diff_models(old, new)
    assert [(c.kind, c.contexts) for c in changes] == [("datatype-changed", ())]
    assert main(["diff", str(old), str(new)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "breaking datatype-changed :ExpenseShape :amount xsd:decimal -> xsd:integer"
    ]


def test_downstream_groups_only_breaking_changes_by_sorted_context():
    a, b = "https://example.org/a", "https://example.org/b"
    late = Change(BREAKING, "shape-removed", EX + "Z", "-", ("data",), (a, b))
    early = Change(BREAKING, "shape-removed", EX + "A", "-", ("data",), (b,))
    loose = Change(COMPATIBLE, "shape-added", EX + "B", "-", ("data",), (a,))
    plain = Change(BREAKING, "shape-removed", EX + "C", "-", ("data",))
    grouped = downstream([late, loose, plain, early])
    assert list(grouped) == [a, b]
    assert grouped == {a: [late], b: [early, late]}
