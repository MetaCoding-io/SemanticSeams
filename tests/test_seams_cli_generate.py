"""`seams generate` reads a seams.toml project file and rewrites its outputs (M012/S01, D042).

In-process main() on a copy of examples/expenses/chapter-03 in tmp_path, so the
committed outputs are never touched.
"""

import shutil
from pathlib import Path

import pytest
from seams_cli import ProjectError, load_project, resolve_model
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"
COMMITTED = CHAPTER / "generated"
EXPECTED = [
    "expense_api.py",
    "templates/expense_list.html",
    "templates/expense_list_item.html",
    "templates/expenses_page.html",
]

GENERATORS = """
[[generators]]
name = "fastapi"
out = "generated"

[[generators]]
name = "htmx"
out = "generated/templates"
"""


@pytest.fixture
def app(tmp_path: Path) -> Path:
    """chapter-03's model and seed, without its generated outputs and lockfile."""
    app = tmp_path / "app"
    shutil.copytree(CHAPTER, app, ignore=shutil.ignore_patterns("generated", "seams.lock"))
    return app


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _project(app: Path, text: str) -> Path:
    path = app / "seams.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _generated(app: Path) -> list[str]:
    out = app / "generated"
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) if out.exists() else []


def test_generate_rewrites_the_committed_outputs_byte_for_byte(app, capsys):
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == EXPECTED
    for name in EXPECTED:
        assert (app / "generated" / name).read_bytes() == (COMMITTED / name).read_bytes(), name
    printed = capsys.readouterr().out.splitlines()
    assert printed == sorted(printed)
    assert [Path(line).name for line in printed] == [Path(name).name for name in EXPECTED] + ["seams.lock"]


def test_printed_paths_are_relative_to_the_cwd(app, capsys, monkeypatch):
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    monkeypatch.chdir(app)
    assert main(["generate"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(Path("generated") / name) for name in EXPECTED] + ["seams.lock"]


def test_project_accepts_the_file_or_its_directory(app):
    path = _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    assert load_project(path) == load_project(app)
    assert main(["generate", "--project", str(path)]) == 0
    assert _generated(app) == EXPECTED


def test_paths_resolve_against_the_project_file_not_the_cwd(app, tmp_path, monkeypatch):
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    monkeypatch.chdir(tmp_path)
    project = load_project(Path("app"))
    assert project.model == app.resolve() / "expenses.trig"
    assert [(t.name, t.out) for t in project.generators] == [
        ("fastapi", app.resolve() / "generated"),
        ("htmx", app.resolve() / "generated" / "templates"),
    ]


def test_environment_names_are_read(app):
    _project(app, 'model = "expenses.trig"\n[environments.dev]\n[environments.prod]\nhost = "x"\n')
    assert load_project(app).environments == ("dev", "prod")


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("model = 3\n", "`model`"),
        ("generators = 3\n", "`generators`"),
        ("generators = [1, 2]\n", "`generators`"),
        ('[[generators]]\nout = "generated"\n', "`name`"),
        ('[[generators]]\nname = "fastapi"\n', "`out`"),
        ('[[generators]]\nname = "react"\nout = "x"\n', "`generators[0].name`"),
        ("environments = 3\n", "`environments`"),
        ("[environments]\ndev = 1\n", "`environments`"),
        ("model = [unclosed\n", "invalid TOML"),
    ],
    ids=[
        "model",
        "generators-scalar",
        "generators-not-tables",
        "no-name",
        "no-out",
        "unknown",
        "env-scalar",
        "env-not-tables",
        "toml",
    ],
)
def test_a_malformed_project_exits_2_naming_the_file_and_key(app, capsys, text, key):
    _project(app, text)
    assert main(["generate", "--project", str(app)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("seams generate: ")
    assert str(app / "seams.toml") in err
    assert key in err
    assert not (app / "generated").exists()


def test_an_unknown_generator_lists_the_known_ones(app, capsys):
    _project(app, '[[generators]]\nname = "react"\nout = "x"\n')
    assert main(["generate", "--project", str(app)]) == 2
    assert "compose, fastapi, htmx" in capsys.readouterr().err


def test_a_missing_project_file_exits_2(tmp_path, capsys):
    assert main(["generate", "--project", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "seams.toml" in err and "no such project file" in err


def test_model_flag_beats_the_project_model(app, tmp_path):
    other = tmp_path / "other.trig"
    shutil.copy(app / "expenses.trig", other)
    (app / "expenses.trig").unlink()
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    assert resolve_model(load_project(app), other) == other
    assert main(["generate", "--project", str(app), "--model", str(other)]) == 0
    assert _generated(app) == EXPECTED


def test_project_model_beats_seams_model(app, monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", str(ROOT / "examples" / "expenses" / "chapter-01" / "expenses.trig"))
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    assert resolve_model(load_project(app)) == app.resolve() / "expenses.trig"
    assert main(["generate", "--project", str(app)]) == 0
    assert (app / "generated" / "expense_api.py").read_bytes() == (COMMITTED / "expense_api.py").read_bytes()


def test_seams_model_is_used_when_the_project_names_none(app, monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", str(app / "expenses.trig"))
    _project(app, GENERATORS)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == EXPECTED


def test_an_empty_seams_model_does_not_count(app, monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", "")
    _project(app, GENERATORS)
    with pytest.raises(ProjectError, match="no model"):
        resolve_model(load_project(app))


def test_no_model_at_all_exits_2(app, capsys):
    _project(app, GENERATORS)
    assert main(["generate", "--project", str(app)]) == 2
    err = capsys.readouterr().err
    assert "no model" in err and "SEAMS_MODEL" in err and str(app / "seams.toml") in err
    assert not (app / "generated").exists()


def test_a_failing_generator_writes_nothing(app, capsys):
    # fastapi and htmx succeed on chapter-03; compose then fails (it declares no
    # arch:Environment, ADR-0015), and the outputs of the first two must not be
    # written either.
    _project(app, 'model = "expenses.trig"\n' + GENERATORS + '\n[[generators]]\nname = "compose"\nout = "."\n')
    assert main(["generate", "--project", str(app)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("seams generate: ") and "arch:Environment" in err
    assert not (app / "generated").exists()
    assert not list(app.glob("compose*.yaml"))


def test_an_unwritable_output_exits_1(app, capsys):
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    (app / "generated").write_text("a file where a directory is needed", encoding="utf-8")
    assert main(["generate", "--project", str(app)]) == 1
    assert capsys.readouterr().err.startswith("seams generate: ")
