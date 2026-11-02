"""`seams generate` reads a seams.toml project file and rewrites its outputs (M012/S01, D042).

In-process main() on a copy of examples/expenses/chapter-03 in tmp_path, so the
committed outputs are never touched.
"""

import json
import shutil
from pathlib import Path

import pytest
from seams_cli import ProjectError, load_project, resolve_model
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"
COMMITTED = CHAPTER / "generated"
OUTPUTS = [
    "expense_api.py",
    "templates/expense_list.html",
    "templates/expense_list_item.html",
    "templates/expenses_page.html",
]
# fastapi and htmx have a trace hook, so each output has its sidecar (ADR-0019).
EXPECTED = sorted(OUTPUTS + [f"{name}.trace.json" for name in OUTPUTS])

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


def _tree(app: Path) -> dict[str, bytes]:
    return {p.relative_to(app).as_posix(): p.read_bytes() for p in sorted(app.rglob("*")) if p.is_file()}


def test_traced_generators_write_a_sidecar_per_output_and_lock_its_terms(app):
    # ADR-0019: <output>.trace.json beside each output, an output of the same
    # generator in seams.lock; both lock entries' sources are the trace's terms.
    _project(app, 'model = "expenses.trig"\n' + GENERATORS)
    assert main(["generate", "--project", str(app)]) == 0
    lock = json.loads((app / "seams.lock").read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in lock["outputs"]}
    assert sorted(entries) == [f"generated/{name}" for name in EXPECTED]
    for name in OUTPUTS:
        trace = json.loads((app / "generated" / f"{name}.trace.json").read_text(encoding="utf-8"))
        generator = "fastapi" if name.endswith(".py") else "htmx"
        assert (trace["trace_version"], trace["generator"], trace["output"]) == (1, generator, Path(name).name)
        terms = sorted({term for line in trace["lines"] for term in line["terms"]})
        assert terms, name
        output, sidecar = entries[f"generated/{name}"], entries[f"generated/{name}.trace.json"]
        assert output["generator"] == sidecar["generator"] == generator
        assert output["sources"] == sidecar["sources"] == terms, name
    first = _tree(app)
    assert main(["generate", "--project", str(app)]) == 0
    assert _tree(app) == first


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
    assert "compose, dockerfile, fastapi, htmx" in capsys.readouterr().err


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


# ── registered generators (M018/S01, D056) ──────────────────────────────────

PLUGIN = """
from seams_gen.protocol import Generator
from seams_gen.trace import Trace

generator = Generator(
    name="example-gen",
    version="9.9.9",
    help="one example file",
    extract=lambda trig, out: trig.name,
    render=lambda name: {"example.txt": f"made from {name}\\n"},
    sources=lambda trig, out: {"example.txt": ("https://example.org/expenses/expense_api",)},
)
strict = Generator(
    name="strict-gen",
    version="1.2.3",
    help="needs every seam:Model to have one notation",
    extract=lambda trig, out: None,
    render=lambda view: {"strict.txt": "ok\\n"},
    sources=lambda trig, out: {"strict.txt": ()},
    preconditions=("https://w3id.org/seams/shapes#ModelShape",),
)
untraced = Generator(
    name="mistraced-gen",
    version="1.0.0",
    help="renders a file it has no trace for",
    extract=lambda trig, out: None,
    render=lambda view: {"traced.txt": "ok\\n"},
    sources=lambda trig, out: {"traced.txt": ()},
    trace=lambda view: {},
)
misnamed = Generator(
    name="misnamed-gen",
    version="1.0.0",
    help="traces its file under another name",
    extract=lambda trig, out: None,
    render=lambda view: {"traced.txt": "ok\\n"},
    sources=lambda trig, out: {"traced.txt": ()},
    trace=lambda view: {"traced.txt": Trace("other.txt", "misnamed-gen", ())},
)
"""
ENTRIES = {
    "example-gen": "seams_cli_test_plugin:generator",
    "strict-gen": "seams_cli_test_plugin:strict",
    "mistraced-gen": "seams_cli_test_plugin:untraced",
    "misnamed-gen": "seams_cli_test_plugin:misnamed",
}
EXAMPLE = '[[generators]]\nname = "example-gen"\nout = "generated/example"\n'
STRICT = '[[generators]]\nname = "strict-gen"\nout = "generated/strict"\n'
MODEL_SHAPE = "https://w3id.org/seams/shapes#ModelShape"
BROKEN = "https://example.org/expenses/broken_model"


def _break_a_model(app: Path) -> None:
    """Add a seam:Model with no seam:notation, which seamsh:ModelShape reports."""
    with open(app / "expenses.trig", "a", encoding="utf-8") as fh:
        fh.write(f"\n<urn:seams:graph:model:broken_model> {{ <{BROKEN}> a seam:Model . }}\n")


def test_a_registered_third_party_generator_writes_its_files(app, generator_dist):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _project(app, 'model = "expenses.trig"\n' + GENERATORS + EXAMPLE)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == sorted([*EXPECTED, "example/example.txt"])
    assert (app / "generated/example/example.txt").read_text(encoding="utf-8") == "made from expenses.trig\n"


def test_a_satisfied_precondition_generates(app, generator_dist):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _project(app, 'model = "expenses.trig"\n' + STRICT)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == ["strict/strict.txt"]


def test_a_violated_precondition_exits_2_naming_generator_shape_and_focus(app, generator_dist, capsys):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _break_a_model(app)
    _project(app, 'model = "expenses.trig"\n' + GENERATORS + STRICT)
    assert main(["generate", "--project", str(app)]) == 2
    assert capsys.readouterr().err == (
        f"seams generate: {BROKEN}: {MODEL_SHAPE}: generator 'strict-gen' requires the model to conform to "
        "this shape: Every seam:Model has exactly one seam:notation, and it is a seam:Notation.\n"
    )
    assert not (app / "generated").exists()
    assert not (app / "seams.lock").exists()


def test_preconditions_of_other_shapes_are_ignored(app, generator_dist):
    # The broken model only violates ModelShape; generators without it still run.
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _break_a_model(app)
    _project(app, 'model = "expenses.trig"\n' + EXAMPLE)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == ["example/example.txt"]


def test_an_unknown_generator_is_a_project_error_listing_registered_ones(app, generator_dist):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _project(app, '[[generators]]\nname = "react"\nout = "x"\n')
    with pytest.raises(ProjectError, match=r"`generators\[0\]\.name` is 'react'; known generators: .*example-gen"):
        load_project(app)


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("mistraced-gen", "traces [] do not name the rendered files ['traced.txt']"),
        ("misnamed-gen", "the trace of traced.txt names output other.txt"),
    ],
)
def test_a_trace_that_does_not_match_the_render_exits_2_and_writes_nothing(app, generator_dist, capsys, name, detail):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _project(app, 'model = "expenses.trig"\n' + GENERATORS + f'[[generators]]\nname = "{name}"\nout = "generated/t"\n')
    assert main(["generate", "--project", str(app)]) == 2
    assert capsys.readouterr().err == f"seams generate: {name}: trace: {detail}\n"
    assert not (app / "generated").exists()
    assert not (app / "seams.lock").exists()


def test_a_generator_without_a_trace_hook_writes_no_sidecar(app, generator_dist):
    generator_dist("seams_cli_test_plugin", PLUGIN, ENTRIES)
    _project(app, 'model = "expenses.trig"\n' + EXAMPLE)
    assert main(["generate", "--project", str(app)]) == 0
    assert _generated(app) == ["example/example.txt"]
    (entry,) = json.loads((app / "seams.lock").read_text(encoding="utf-8"))["outputs"]
    assert entry["sources"] == ["https://example.org/expenses/expense_api"]
