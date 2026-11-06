"""``seams storm <name> [--project] [--model] [--out FILE]`` (M028/S01, backlog
B4): prints the chapter-10 approval_process golden for the process and for the
event that triggers it, reports gaps on stderr with exit 0, and exits 2 naming
an unknown argument."""

from __future__ import annotations

from pathlib import Path

from seams_cli.__main__ import main as seams_main

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_10 = ROOT / "examples" / "expenses" / "chapter-10"
GOLDEN = ROOT / "tests" / "golden" / "storm" / "approval_process.md"


def _gap_lines() -> list[str]:
    text = GOLDEN.read_text(encoding="utf-8")
    gaps = text.split("## Gaps\n\n", 1)[1].splitlines()
    return [f"seams storm: gap approval_process: {g.removeprefix('- ')}" for g in gaps if g.startswith("- ")]


def test_storm_prints_the_golden(capsys):
    assert seams_main(["storm", "approval_process", "--project", str(CHAPTER_10)]) == 0
    out, err = capsys.readouterr()
    assert out == GOLDEN.read_text(encoding="utf-8")
    assert err.splitlines() == _gap_lines()
    assert err.splitlines()  # chapter 10 has gaps, so the stderr format is exercised


def test_storm_of_the_triggering_event_is_the_process_storm(capsys):
    assert seams_main(["storm", "submit_expense", "--project", str(CHAPTER_10)]) == 0
    assert capsys.readouterr().out == GOLDEN.read_text(encoding="utf-8")


def test_storm_model_override_and_out_file(tmp_path, capsys):
    out_file = tmp_path / "storm.md"
    code = seams_main(
        [
            "storm",
            ":submit_expense",
            "--project",
            str(CHAPTER_10),
            "--model",
            str(CHAPTER_10 / "expenses.trig"),
            "--out",
            str(out_file),
        ]
    )
    assert code == 0
    assert out_file.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")
    assert capsys.readouterr().out.splitlines() == [str(out_file.resolve())]


def test_storm_unknown_name_exits_2_and_names_it(tmp_path, capsys):
    out_file = tmp_path / "storm.md"
    code = seams_main(["storm", "no_such_process", "--project", str(CHAPTER_10), "--out", str(out_file)])
    assert code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("seams storm: ")
    assert "no_such_process" in err
    assert not out_file.exists()


def test_storm_unloadable_model_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.trig"
    bad.write_text("this is not trig", encoding="utf-8")
    assert seams_main(["storm", "approval_process", "--project", str(CHAPTER_10), "--model", str(bad)]) == 2
    assert "cannot load the model" in capsys.readouterr().err
