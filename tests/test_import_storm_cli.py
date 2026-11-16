"""``seams import-storm FILE --out PATH [--base IRI]`` (M033/S03, backlog X12, ADR-0046):
writes the skeleton golden and its payload, reports each gap on stderr with exit 0,
exits 2 naming the line of an unreadable storm or an existing output and writing
nothing; the skeleton is refused by ``seams generate`` and flagged by the viewer's
health panel."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import seams
from seams_cli.__main__ import main as seams_main

from seams_gen.storm_import import gaps, parse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import validation  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "storm_import" / "approval.md"
GOLDEN = ROOT / "tests" / "golden" / "storm_import" / "approval_skeleton.trig"


@pytest.fixture(autouse=True)
def clear_conformance_cache():
    """The viewer caches conformance by id(ds); a recycled id must not serve a stale result."""
    validation._clear_cache()
    yield


def _import(out: Path, *extra: str) -> int:
    return seams_main(["import-storm", str(FIXTURE), "--out", str(out), *extra])


def test_import_writes_the_golden_and_the_payload(tmp_path, capsys):
    out = tmp_path / "approval_skeleton.trig"
    assert _import(out) == 0
    assert out.read_bytes() == GOLDEN.read_bytes()
    payload = tmp_path / "approval_process.bpmn"
    assert payload.is_file()
    assert capsys.readouterr().out.splitlines() == [str(payload), str(out)]


def test_gaps_go_to_stderr_one_line_each(tmp_path, capsys):
    out = tmp_path / "approval_skeleton.trig"
    assert _import(out) == 0
    err = capsys.readouterr().err.splitlines()
    expected = gaps(parse(FIXTURE.read_text(encoding="utf-8")), out)
    assert err == [f"seams import-storm: gap {gap}" for gap in expected]
    assert any("no sequence flows" in line for line in err)
    assert any("seam:submitsTo operation" in line for line in err)


def test_base_option_mints_under_the_given_iri(tmp_path, capsys):
    out = tmp_path / "model.trig"
    assert _import(out, "--base", "https://example.org/other/") == 0
    text = out.read_text(encoding="utf-8")
    assert "@prefix : <https://example.org/other/> ." in text
    assert "https://example.org/expenses/" not in text
    capsys.readouterr()


def test_bad_base_option_exits_2_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "model.trig"
    assert _import(out, "--base", "not-an-iri") == 2
    assert "not-an-iri" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_unreadable_line_exits_2_naming_the_line(tmp_path, capsys):
    storm = tmp_path / "storm.md"
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "   - aggregate: Expense (`ExpenseShape`)", "   - sticky: Expense (`ExpenseShape`)"
    )
    storm.write_text(text, encoding="utf-8")
    number = text.splitlines().index("   - sticky: Expense (`ExpenseShape`)") + 1
    out = tmp_path / "out" / "model.trig"
    out.parent.mkdir()
    assert seams_main(["import-storm", str(storm), "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"seams import-storm: line {number}: ")
    assert "unknown entry kind 'sticky'" in captured.err
    assert list(out.parent.iterdir()) == []


def test_existing_out_exits_2_and_is_kept(tmp_path, capsys):
    out = tmp_path / "model.trig"
    out.write_text("kept\n", encoding="utf-8")
    assert _import(out) == 2
    assert "already exists" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "kept\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.trig"]


def test_missing_storm_file_exits_1(tmp_path, capsys):
    out = tmp_path / "model.trig"
    assert seams_main(["import-storm", str(tmp_path / "absent.md"), "--out", str(out)]) == 1
    assert capsys.readouterr().err.startswith("seams import-storm: ")
    assert not out.exists()


def test_generate_refuses_the_skeleton_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "model.trig"
    assert _import(out) == 0
    (tmp_path / "seams.toml").write_text(
        'model = "model.trig"\n\n[[generators]]\nname = "fastapi"\nout = "generated"\n\n'
        '[[generators]]\nname = "htmx"\nout = "generated/templates"\n',
        encoding="utf-8",
    )
    capsys.readouterr()
    before = sorted(p.name for p in tmp_path.iterdir())
    assert seams_main(["generate", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("seams generate: ")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_viewer_health_reports_the_skeleton_nonconformant(tmp_path, capsys):
    out = tmp_path / "model.trig"
    assert _import(out) == 0
    capsys.readouterr()
    health = validation.get_model_conformance(seams.load(out, check_imports=False).ds)
    assert health["conforms"] is False
    assert health["violationCount"] > 0
