"""``seams plan`` (M015/S02): the Markdown change plan, its layers, and git REF:PATH models."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from seams_cli.__main__ import main
from seams_cli.diff import diff_loaded, load_model
from seams_cli.plan import LAYERS, layer_changes, render, resolve
from seams_cli.project import ProjectError

ROOT = Path(__file__).resolve().parent.parent
CH08 = ROOT / "examples" / "expenses" / "chapter-08"
CH09 = ROOT / "examples" / "expenses" / "chapter-09"


def _plan(old: Path, new: Path) -> str:
    a, b = load_model(old), load_model(new)
    return render(a, b, diff_loaded(a, b))


def test_chapter_8_to_9_plan_headings_and_elements():
    text = _plan(CH08, CH09)
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings == [
        "# Change plan",
        "## Breaking changes",
        "## Compatible changes",
        "## Elements by layer",
        "### Operations",
        "### Shapes",
        "### Processes",
    ]
    assert "## Breaking changes\n\nNone\n" in text
    assert "- shape-added :NotificationShape\n" in text
    assert "### Shapes\n\nAdded:\n\n- :NotificationShape\n- :NotifyProblemShape\n" in text
    assert "- :approval_bpmn#notify_manager\n" in text
    assert "Removed:" not in text
    assert text == _plan(CH08, CH09), "deterministic"


def test_layer_changes_cover_every_layer_in_order():
    changes = layer_changes(load_model(CH09), load_model(CH08))
    assert tuple(changes) == LAYERS
    assert changes["shapes"].removed == (
        "https://example.org/expenses/NotificationShape",
        "https://example.org/expenses/NotifyProblemShape",
    )
    assert changes["shapes"].added == ()
    assert not changes["decisions"].added and not changes["decisions"].removed


def test_identical_models_have_no_layer_sections(capsys):
    assert main(["plan", str(CH09), str(CH09 / "expenses.trig")]) == 0
    out = capsys.readouterr()
    assert "###" not in out.out
    assert out.out.endswith("## Elements by layer\n\nNone\n")
    assert out.err == ""


def test_backwards_plan_is_breaking_and_writes_output(tmp_path, capsys):
    target = tmp_path / "plan.md"
    assert main(["plan", str(CH09), str(CH08), "--output", str(target)]) == 1
    out = capsys.readouterr()
    assert out.out.strip() == str(target)
    summary, *refused = out.err.strip().splitlines()
    assert summary == "seams plan: 4 breaking, 0 compatible"
    # ADR-0041: the stored NotificationShape cannot be removed mechanically, so it is refused after the summary.
    assert refused == [
        "seams plan: refused :NotificationShape - (shape-removed): the shape is removed: its rows have no "
        "shape to conform to, and deleting them is not mechanical"
    ]
    text = target.read_text()
    assert "- shape-removed :NotificationShape\n" in text
    assert "### Shapes\n\nRemoved:\n\n- :NotificationShape\n" in text
    assert "## Stored-data migrations\n\nRefused:\n\n- refused :NotificationShape - (shape-removed): " in text


PREFIXES = """\
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/m/> .
"""
STORES = ":db a arch:Container ; deploy:storeKind deploy:SQLite .\n:pkm a arch:Container ; deploy:storeKind deploy:SemPKM .\n"
NAME = "sh:property [ sh:path :name ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ]"
NOTE = "sh:property [ sh:path :note ; sh:datatype xsd:string ; sh:maxCount 1 ]"
COUNT = "sh:property [ sh:path :count ; sh:datatype xsd:integer ; sh:minCount 1{} ]"


def _stored(*props: str, store: str = ":db") -> str:
    body = " ;\n    ".join((":ItemShape a sh:NodeShape", f"seam:storedIn {store}", *props))
    return PREFIXES + "<urn:seams:graph:shapes> {\n" + body + " .\n" + STORES + "}\n"


def _write(tmp_path: Path, old: str, new: str) -> tuple[Path, Path]:
    (tmp_path / "old.trig").write_text(old, encoding="utf-8")
    (tmp_path / "new.trig").write_text(new, encoding="utf-8")
    return tmp_path / "old.trig", tmp_path / "new.trig"


def test_stored_changes_get_a_sql_block_per_kind_and_shape(tmp_path, capsys):
    old, new = _write(tmp_path, _stored(NAME, NOTE), _stored(NAME, COUNT.format(" ; sh:defaultValue 0")))
    assert main(["plan", str(old), str(new)]) == 1
    out = capsys.readouterr()
    assert out.err == "seams plan: 2 breaking, 0 compatible\n", "no refusal line"
    text = out.out
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings[:5] == [
        "# Change plan",
        "## Breaking changes",
        "## Compatible changes",
        "## Stored-data migrations",
        "### postgresql :ItemShape",
    ]
    assert "### sqlite :ItemShape" in headings
    shape = "'https://example.org/m/ItemShape'"
    assert (
        "### sqlite :ItemShape\n\n```sql\n"
        f"UPDATE entities SET data = json_set(data, '$.\"count\"', json('0')) WHERE shape = {shape} "
        "AND json_type(data, '$.\"count\"') IS NULL;\n"
        f"UPDATE entities SET data = json_remove(data, '$.\"note\"') WHERE shape = {shape};\n```\n"
    ) in text
    assert f"UPDATE entities SET data = data - 'note' WHERE shape = {shape};" in text
    assert "Refused:" not in text
    assert text.index("## Stored-data migrations") < text.index("## Elements by layer")
    assert main(["plan", str(old), str(new)]) == 1
    assert capsys.readouterr().out == text, "deterministic"


def test_refusals_name_shape_and_path_in_the_plan_and_on_stderr(tmp_path, capsys):
    old, new = _write(tmp_path, _stored(NAME), _stored(NAME, COUNT.format("")))
    assert main(["plan", str(old), str(new)]) == 1
    out = capsys.readouterr()
    line = "refused :ItemShape :count (property-added): no sh:defaultValue to fill the rows that lack it"
    assert out.err.splitlines() == ["seams plan: 1 breaking, 0 compatible", f"seams plan: {line}"]
    assert f"## Stored-data migrations\n\nRefused:\n\n- {line}\n" in out.out
    assert "```sql" not in out.out


def test_sempkm_store_is_refused_with_no_sql(tmp_path, capsys):
    old, new = _write(tmp_path, _stored(NAME, NOTE, store=":pkm"), _stored(NAME, store=":pkm"))
    assert main(["plan", str(old), str(new)]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[1:] == [
        "seams plan: refused :ItemShape :note (property-removed): stored in the SemPKM store :pkm; "
        "SemPKM data is not rewritten by SQL"
    ]


def test_unstored_shape_has_no_migration_section(tmp_path, capsys):
    old, new = _write(
        tmp_path,
        _stored(NAME, NOTE).replace("seam:storedIn :db ;", ""),
        _stored(NAME).replace("seam:storedIn :db ;", ""),
    )
    assert main(["plan", str(old), str(new)]) == 1
    out = capsys.readouterr()
    assert "## Stored-data migrations" not in out.out
    assert out.err == "seams plan: 1 breaking, 0 compatible\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository whose HEAD holds chapter 8 at model/ and whose working tree holds chapter 9."""
    repo = tmp_path / "repo"
    model = repo / "model"
    shutil.copytree(CH08, model, ignore=shutil.ignore_patterns("generated", "handlers"))
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "chapter 8")
    shutil.copy(CH09 / "expenses.trig", model / "expenses.trig")
    monkeypatch.chdir(repo)
    return repo


def test_resolve_extracts_a_git_ref(repo, tmp_path):
    path = resolve("HEAD:model/expenses.trig", tmp_path / "work")
    assert path == tmp_path / "work" / "model" / "expenses.trig"
    assert path.read_bytes() == (CH08 / "expenses.trig").read_bytes()
    assert resolve("model", tmp_path / "unused") == Path("model")


def test_plan_between_head_and_the_working_tree(repo, capsys):
    assert main(["plan", "HEAD:model", "model"]) == 0
    out = capsys.readouterr()
    assert out.out == _plan(CH08, CH09)
    assert out.err == ""


def test_bad_ref_exits_2(repo, capsys):
    assert main(["plan", "no-such-ref:model", "model"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("seams plan: no-such-ref: ")


def test_path_missing_at_ref_exits_2(repo, capsys):
    assert main(["plan", "HEAD:missing", "model"]) == 2
    assert capsys.readouterr().err.startswith("seams plan: HEAD: ")


def test_resolve_outside_a_repository_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(ProjectError, match="^HEAD: "):
        resolve("HEAD:model", tmp_path / "work")
