"""``seams diff`` on the expenses chapters (M015/S01): exit codes, text and JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from seams_cli.__main__ import main
from seams_cli.diff import diff_models

ROOT = Path(__file__).resolve().parent.parent
CH08 = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
CH09 = ROOT / "examples" / "expenses" / "chapter-09" / "expenses.trig"


def _curie(iri: str) -> str:
    """The expenses chapters bind their default prefix to example.org/expenses/."""
    return ":" + iri.removeprefix("https://example.org/expenses/")


PREFIXES = """\
@prefix :    <https://example.org/m/> .
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def test_chapter_8_to_9_is_compatible(capsys):
    assert main(["diff", str(CH08), str(CH09), "--json"]) == 0
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert set(report) == {"changes", "counts"}
    assert report["counts"] == {"breaking": 0, "compatible": len(report["changes"])}
    assert report["changes"], "chapter 9 adds the notification shapes and operations"
    for change in report["changes"]:
        assert set(change) == {"verdict", "kind", "subject", "detail", "scopes"}
        assert change["verdict"] == "compatible"
        assert change["kind"] in {"shape-added", "operation-added"}
        assert change["scopes"] == sorted(change["scopes"])
    assert out.err == ""


def test_chapter_9_to_8_is_breaking(capsys):
    assert main(["diff", str(CH09), str(CH08)]) == 1
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert [line.split()[1:3] for line in lines] == [[c.kind, _curie(c.subject)] for c in diff_models(CH09, CH08)], (
        "printed in diff_models order"
    )
    assert all(line.startswith("breaking ") for line in lines)
    assert any(line.startswith("breaking operation-removed :") for line in lines), lines
    assert out.err.strip() == f"seams diff: {len(lines)} breaking, 0 compatible"


def test_chapter_against_itself_prints_nothing(capsys):
    assert main(["diff", str(CH09), str(CH09.parent)]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_text_details_use_curies(tmp_path, capsys):
    old = tmp_path / "old.trig"
    new = tmp_path / "new.trig"
    old.write_text(PREFIXES + ":g { :S a sh:NodeShape ; sh:property [ sh:path :p ; sh:datatype xsd:string ] . }\n")
    new.write_text(PREFIXES + ":g { :S a sh:NodeShape ; sh:property [ sh:path :p ; sh:datatype xsd:integer ] . }\n")
    assert main(["diff", str(old), str(new)]) == 1
    out = capsys.readouterr()
    assert out.out == "breaking datatype-changed :S :p xsd:string -> xsd:integer\n"
    assert out.err.strip() == "seams diff: 1 breaking, 0 compatible"


def test_unloadable_model_exits_2(tmp_path, capsys):
    broken = tmp_path / "broken.trig"
    broken.write_text("this is not TriG {")
    assert main(["diff", str(broken), str(CH09)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("seams diff: ") and "cannot load the model" in err


def test_missing_model_exits_2(tmp_path, capsys):
    assert main(["diff", str(tmp_path / "absent.trig"), str(CH09)]) == 2
    assert "cannot load the model" in capsys.readouterr().err
