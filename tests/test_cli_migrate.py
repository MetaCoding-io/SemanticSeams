"""Tests for ``seams migrate`` (M023/S02, ADR-0021 section 5).

``seams.load`` migrates a model that targets an older vocabulary in memory only;
``seams migrate`` writes the same migration into the model's TriG files as one patch
through the seams_edit text writer (ADR-0017). Every shipped vocabulary is at 1.0, so
the migration runs against the fixture tree tests/fixtures/vocab-v2 (seam at 2.0, whose
1-to-2.ru renames seam:inModel to seam:partOfModel) over a copy of the expense
chapter-01 checkpoint.
"""

import functools
import shutil
from pathlib import Path

import seams
from rdflib import OWL
from seams import MANIFEST_GRAPH
from seams_cli import __main__ as cli
from seams_cli.__main__ import main
from seams_cli.migrate import migrate
from test_vocabulary_versions import undeclared

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vocab-v2"
CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01"
SEAM_V2 = "https://w3id.org/seams/seam/2.0"
ARCH_V1 = "https://w3id.org/seams/arch/1.2"
# The checkpoints declare the shipped seam, 1.5.
SEAM_V1_IMPORT = "<https://w3id.org/seams/seam/1.6>"


def chapter_01_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(CHAPTER_01, tmp_path / "chapter-01", ignore=shutil.ignore_patterns("__pycache__")))


def against(monkeypatch, vocab_dir: Path) -> None:
    monkeypatch.setattr(cli, "migrate", functools.partial(migrate, ontology_dir=vocab_dir))


def comments(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("#")]


def test_migrate_writes_the_migration_and_keeps_the_comments(tmp_path, monkeypatch, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    trig = project / "expenses.trig"
    before = trig.read_text(encoding="utf-8")
    against(monkeypatch, FIXTURE)
    assert main(["migrate", "--project", str(project)]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == ["migrated seam 1.6 2.0", str(trig)]
    assert err == ""
    after = trig.read_text(encoding="utf-8")
    assert comments(after) == comments(before)
    assert "seam:inModel" not in after
    assert after.count("seam:partOfModel") == before.count("seam:inModel")

    model = seams.load(trig, ontology_dir=FIXTURE)
    assert model.migrations == ()
    assert sorted(str(o) for o in model.ds.graph(MANIFEST_GRAPH).objects(None, OWL.imports)) == [ARCH_V1, SEAM_V2]


def test_the_written_model_is_the_model_load_migrates(tmp_path, monkeypatch) -> None:
    project = chapter_01_copy(tmp_path)
    in_memory = seams.load(project / "expenses.trig", ontology_dir=FIXTURE).ds
    migrate(project / "expenses.trig", FIXTURE)
    written = seams.load(project / "expenses.trig", ontology_dir=FIXTURE).ds
    for graph in sorted({g for *_t, g in in_memory.quads()} | {g for *_t, g in written.quads()}, key=str):
        assert set(in_memory.graph(graph)) == set(written.graph(graph)), graph


def test_a_second_run_writes_nothing(tmp_path, monkeypatch, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    against(monkeypatch, FIXTURE)
    assert main(["migrate", "--project", str(project)]) == 0
    migrated = (project / "expenses.trig").read_bytes()
    capsys.readouterr()
    assert main(["migrate", "--project", str(project)]) == 0
    assert capsys.readouterr() == ("", "seams migrate: nothing to migrate\n")
    assert (project / "expenses.trig").read_bytes() == migrated


def test_a_current_model_is_left_alone(tmp_path, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    before = (project / "expenses.trig").read_bytes()
    assert main(["migrate", "--project", str(project)]) == 0
    assert capsys.readouterr() == ("", "seams migrate: nothing to migrate\n")
    assert (project / "expenses.trig").read_bytes() == before


def test_a_newer_model_is_refused_and_nothing_is_written(tmp_path, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    trig = project / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(SEAM_V1_IMPORT) == 1
    trig.write_text(text.replace(SEAM_V1_IMPORT, f"<{SEAM_V2}>"), encoding="utf-8")
    before = trig.read_bytes()
    assert main(["migrate", "--project", str(project)]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("seams migrate: ")
    assert "targets seam 2.0; this tool supports seam up to 1.6" in err
    assert trig.read_bytes() == before


def test_a_missing_step_is_refused_and_nothing_is_written(tmp_path, monkeypatch, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    vocab = Path(shutil.copytree(FIXTURE, tmp_path / "vocab"))
    (vocab / "migrations" / "seam" / "1-to-2.ru").unlink()
    before = (project / "expenses.trig").read_bytes()
    against(monkeypatch, vocab)
    assert main(["migrate", "--project", str(project)]) == 2
    assert "no migration step seam 1-to-2" in capsys.readouterr().err
    assert (project / "expenses.trig").read_bytes() == before


def test_a_directory_model_without_a_manifest_block_is_refused_and_nothing_is_written(
    tmp_path, monkeypatch, capsys
) -> None:
    # The new declaration has no file to go to: no file declares the manifest graph
    # and the model has two, so the writer cannot route it (seams_edit.apply).
    model = tmp_path / "model"
    model.mkdir()
    (model / "a.trig").write_text(undeclared(CHAPTER_01 / "expenses.trig"), encoding="utf-8")
    (model / "b.trig").write_text("# second file\n<urn:example:other> { <urn:x> <urn:y> <urn:z> . }\n")
    before = {p.name: p.read_bytes() for p in model.glob("*.trig")}
    against(monkeypatch, FIXTURE)
    assert main(["migrate", "--project", str(CHAPTER_01), "--model", str(model)]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("seams migrate: ")
    assert {p.name: p.read_bytes() for p in model.glob("*.trig")} == before
