"""`seams generate` records its outputs in seams.lock and cleans up after itself (M012/S02, D043).

In-process main() on a copy of examples/expenses/chapter-03 in tmp_path, without
its outputs and lockfile, so the committed files are never touched.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import seams
from seams_cli import Audit, LockError, ProjectError, audit, load_project, read_lock
from seams_cli.__main__ import main

import seams_gen

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"

FASTAPI = '[[generators]]\nname = "fastapi"\nout = "generated"\n'
HTMX = '[[generators]]\nname = "htmx"\nout = "generated/templates"\n'
BOTH = 'model = "expenses.trig"\n' + FASTAPI + HTMX
API = "generated/expense_api.py"
PAGE = "generated/templates/expenses_page.html"
TEMPLATES = [
    "generated/templates/expense_list.html",
    "generated/templates/expense_list_item.html",
    PAGE,
]


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    shutil.copytree(CHAPTER, app, ignore=shutil.ignore_patterns("generated", "seams.lock"))
    (app / "seams.toml").write_text(BOTH, encoding="utf-8")
    return app


def _generate(app: Path, capsys) -> tuple[list[str], list[str]]:
    assert main(["generate", "--project", str(app)]) == 0
    captured = capsys.readouterr()
    return captured.out.splitlines(), captured.err.splitlines()


def _lock(app: Path) -> dict:
    return json.loads((app / "seams.lock").read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_first_run_writes_a_lock_and_reports_nothing(app, capsys):
    out, err = _generate(app, capsys)
    assert err == []
    assert out[-1] == str(app.resolve() / "seams.lock")
    assert not any(line.startswith("removed ") for line in out)


def test_the_lock_is_deterministic(app, capsys):
    _generate(app, capsys)
    first = (app / "seams.lock").read_bytes()
    out, err = _generate(app, capsys)
    assert (app / "seams.lock").read_bytes() == first
    assert err == []
    assert first.endswith(b"}\n") and b"\r" not in first


def test_lock_fields(app, capsys):
    _generate(app, capsys)
    lock = _lock(app)
    digest = seams.model_hash(app / "expenses.trig")
    assert lock["lockfile_version"] == 1
    assert lock["model"] == "expenses.trig"
    assert lock["model_hash"] == digest
    paths = [o["path"] for o in lock["outputs"]]
    assert paths == [API, *TEMPLATES]
    subjects = {str(s) for s in seams.load(app / "expenses.trig").ds.subjects()}
    for entry in lock["outputs"]:
        assert set(entry) == {"generator", "generator_version", "model_hash", "path", "sha256", "sources"}
        assert entry["generator"] == ("fastapi" if entry["path"] == API else "htmx")
        assert entry["generator_version"] == seams_gen.__version__
        assert entry["model_hash"] == digest
        assert entry["sha256"] == _sha(app / entry["path"])
        assert entry["sources"] and entry["sources"] == sorted(set(entry["sources"]))
        assert set(entry["sources"]) <= subjects, entry["path"]
    assert "https://example.org/expenses/expense_api" in lock["outputs"][0]["sources"]


def test_removing_a_target_deletes_its_unchanged_files(app, capsys):
    _generate(app, capsys)
    (app / "seams.toml").write_text('model = "expenses.trig"\n' + FASTAPI, encoding="utf-8")
    out, err = _generate(app, capsys)
    assert err == []
    assert [line for line in out if line.startswith("removed ")] == [
        f"removed {app.resolve() / name}" for name in TEMPLATES
    ]
    assert not any((app / name).exists() for name in TEMPLATES)
    assert (app / API).is_file()
    assert [o["path"] for o in _lock(app)["outputs"]] == [API]


def test_an_edited_orphan_is_kept_and_reported(app, capsys):
    _generate(app, capsys)
    (app / PAGE).write_text("my own page\n", encoding="utf-8")
    (app / "seams.toml").write_text('model = "expenses.trig"\n' + FASTAPI, encoding="utf-8")
    out, err = _generate(app, capsys)
    assert err == [f"seams generate: kept hand-edited orphan {app.resolve() / PAGE}"]
    assert (app / PAGE).read_text(encoding="utf-8") == "my own page\n"
    assert f"removed {app.resolve() / PAGE}" not in out
    assert len([line for line in out if line.startswith("removed ")]) == 2


def test_a_symlink_orphan_is_not_deleted(app, capsys, tmp_path):
    _generate(app, capsys)
    real = tmp_path / "real.html"
    shutil.copy(app / PAGE, real)  # same bytes, so only the symlink rule keeps it
    (app / PAGE).unlink()
    (app / PAGE).symlink_to(real)
    (app / "seams.toml").write_text('model = "expenses.trig"\n' + FASTAPI, encoding="utf-8")
    out, err = _generate(app, capsys)
    assert err == [f"seams generate: kept hand-edited orphan {app.resolve() / PAGE}"]
    assert (app / PAGE).is_symlink() and real.is_file()


def test_a_lock_entry_whose_hash_does_not_match_never_deletes(app, capsys, tmp_path):
    """A crafted lock naming a file outside the outputs deletes nothing unless it knows the exact bytes."""
    _generate(app, capsys)
    victim = tmp_path / "precious.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    lock = _lock(app)
    lock["outputs"].append({**lock["outputs"][0], "path": "../precious.txt", "sha256": "0" * 64})
    (app / "seams.lock").write_text(json.dumps(lock), encoding="utf-8")
    out, err = _generate(app, capsys)
    assert victim.read_text(encoding="utf-8") == "keep me\n"
    assert err == [f"seams generate: kept hand-edited orphan {victim}"]
    assert not any(line.startswith("removed ") for line in out)


def test_a_hand_edited_output_is_overwritten_and_reported(app, capsys):
    _generate(app, capsys)
    original = (app / API).read_bytes()
    (app / API).write_text("# edited\n", encoding="utf-8")
    out, err = _generate(app, capsys)
    assert err == [f"seams generate: overwrote hand-edited {app.resolve() / API}"]
    assert (app / API).read_bytes() == original


def test_a_deleted_output_is_restored_and_reported(app, capsys):
    _generate(app, capsys)
    original = (app / PAGE).read_bytes()
    (app / PAGE).unlink()
    out, err = _generate(app, capsys)
    assert err == [f"seams generate: restored deleted {app.resolve() / PAGE}"]
    assert (app / PAGE).read_bytes() == original


@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda lock: "{not json", "invalid JSON"),
        (lambda lock: "[]", "(top level)"),
        (lambda lock: json.dumps({**lock, "lockfile_version": 2}), "`lockfile_version`"),
        (lambda lock: json.dumps({**lock, "model": 3}), "`model`"),
        (lambda lock: json.dumps({**lock, "outputs": {}}), "`outputs`"),
        (lambda lock: json.dumps({**lock, "outputs": [1]}), "`outputs[0]`"),
        (
            lambda lock: json.dumps({**lock, "outputs": [{**lock["outputs"][0], "path": None}]}),
            "`outputs[0].path`",
        ),
        (
            lambda lock: json.dumps({**lock, "outputs": [{**lock["outputs"][0], "sha256": "xyz"}]}),
            "`outputs[0].sha256`",
        ),
        (
            lambda lock: json.dumps({**lock, "outputs": [{**lock["outputs"][0], "sources": [1]}]}),
            "`outputs[0].sources[0]`",
        ),
    ],
    ids=["json", "top-level", "version", "model", "outputs", "entry", "path", "sha256", "sources"],
)
def test_a_malformed_lock_exits_2_and_touches_nothing(app, capsys, mutate, key):
    _generate(app, capsys)
    (app / API).write_text("# edited\n", encoding="utf-8")
    (app / "seams.toml").write_text('model = "expenses.trig"\n' + FASTAPI, encoding="utf-8")
    (app / "seams.lock").write_text(mutate(_lock(app)), encoding="utf-8")
    before = {p: p.read_bytes() for p in app.rglob("*") if p.is_file()}
    assert main(["generate", "--project", str(app)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("seams generate: ")
    assert str(app.resolve() / "seams.lock") in err and key in err
    assert {p: p.read_bytes() for p in app.rglob("*") if p.is_file()} == before


def test_read_lock_is_none_without_a_lockfile(app):
    assert read_lock(load_project(app)) is None


def test_audit_lists_missing_edited_and_orphans(app, capsys):
    _generate(app, capsys)
    project = load_project(app)
    lock = read_lock(project)
    files = {(app / p).resolve(): (app / p).read_text(encoding="utf-8") for p in [API, *TEMPLATES]}
    assert audit(project, lock, files) == Audit()
    assert audit(project, None, files).orphans == ()

    (app / API).write_text("# edited\n", encoding="utf-8")
    (app / TEMPLATES[0]).unlink()
    del files[(app / PAGE).resolve()]
    result = audit(project, lock, files)
    assert result.edited == (API,)
    assert result.missing == (TEMPLATES[0],)
    assert result.orphans == (PAGE,)

    # On disk equal to the new text is not an edit, even when the lock differs.
    files[(app / API).resolve()] = "# edited\n"
    assert audit(project, lock, files).edited == ()


def test_a_failing_generator_keeps_the_old_lock(app, capsys):
    _generate(app, capsys)
    before = (app / "seams.lock").read_bytes()
    # compose fails on chapter-03 (no deploy:artifact); nothing may change.
    (app / "seams.toml").write_text(
        'model = "expenses.trig"\n' + FASTAPI + '[[generators]]\nname = "compose"\nout = "."\n', encoding="utf-8"
    )
    assert main(["generate", "--project", str(app)]) == 2
    assert (app / "seams.lock").read_bytes() == before
    assert all((app / name).is_file() for name in TEMPLATES)


def test_lock_error_is_a_project_error():
    assert issubclass(LockError, ProjectError)
