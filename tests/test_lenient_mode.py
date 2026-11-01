"""Lenient generation collects faults and flags seams.lock (M018/S02, D057).

Function-level: generate_project, apply, render_lock and read_lock on a copy of
examples/expenses/chapter-03 in tmp_path, with third-party generators from the
``generator_dist`` fixture. CLI-level: in-process ``seams generate --lenient``
and ``seams check`` on the same copy, with a precondition generator and a
raising generator registered through a monkeypatched ``discover``.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from rdflib import Graph
from seams_cli import Fault, Lock, LockError, load_project, read_lock, render_lock
from seams_cli.__main__ import main
from seams_cli.check import FILE_KINDS, SHAPES_FILE
from seams_cli.generate import apply, generate_project, shape_results

import seams_gen.registry
from seams_gen import GeneratorError
from seams_gen.protocol import Generator
from seams_gen.registry import discover

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-03"
MODEL_SHAPE = "https://w3id.org/seams/shapes#ModelShape"
BROKEN = "https://example.org/expenses/broken_model"
OTHER = "https://example.org/expenses/another_broken_model"
REQUIRES = "generator 'strict-gen' requires the model to conform to this shape: "
NOTATION = "Every seam:Model has exactly one seam:notation, and it is a seam:Notation."

PLUGIN = """
from seams_gen import GeneratorError
from seams_gen.protocol import Generator


def _fragile(trig, out):
    if "broken_model" in trig.read_text(encoding="utf-8"):
        raise GeneratorError("https://example.org/expenses/broken_model", "seam:notation", "no notation to render")
    return None


strict = Generator(
    name="strict-gen",
    version="1.2.3",
    help="needs every seam:Model to have one notation",
    extract=lambda trig, out: None,
    render=lambda view: {"strict.txt": "ok\\n"},
    sources=lambda trig, out: {"strict.txt": ()},
    preconditions=("https://w3id.org/seams/shapes#ModelShape",),
)
fragile = Generator(
    name="fragile-gen",
    version="0.0.1",
    help="raises on a broken model",
    extract=_fragile,
    render=lambda view: {"fragile.txt": "fine\\n"},
    sources=lambda trig, out: {"fragile.txt": ()},
)
"""
ENTRIES = {"strict-gen": "seams_lenient_test_plugin:strict", "fragile-gen": "seams_lenient_test_plugin:fragile"}
BUILTIN = '[[generators]]\nname = "fastapi"\nout = "generated"\n\n[[generators]]\nname = "htmx"\nout = "generated/templates"\n'
STRICT = '[[generators]]\nname = "strict-gen"\nout = "generated/strict"\n'
FRAGILE = '[[generators]]\nname = "fragile-gen"\nout = "generated/fragile"\n'

PRECONDITION_FAULT = Fault("strict-gen", MODEL_SHAPE, BROKEN, REQUIRES + NOTATION)
FRAGILE_FAULT = Fault("fragile-gen", "seam:notation", BROKEN, "no notation to render")


@pytest.fixture
def app(tmp_path: Path, generator_dist) -> Path:
    """chapter-03's model, without its generated outputs and lockfile, with the test generators registered."""
    generator_dist("seams_lenient_test_plugin", PLUGIN, ENTRIES)
    app = tmp_path / "app"
    shutil.copytree(CHAPTER, app, ignore=shutil.ignore_patterns("generated", "seams.lock"))
    return app


def _project(app: Path, generators: str):
    (app / "seams.toml").write_text('model = "expenses.trig"\n' + generators, encoding="utf-8")
    return load_project(app)


def _break(app: Path, *models: str) -> None:
    """Add seam:Models with no seam:notation, which seamsh:ModelShape reports."""
    with open(app / "expenses.trig", "a", encoding="utf-8") as fh:
        for iri in models:
            fh.write(f"\n<urn:seams:graph:model:{iri.rsplit('/', 1)[1]}> {{ <{iri}> a seam:Model . }}\n")


def _tree(app: Path) -> dict[str, bytes]:
    return {p.relative_to(app).as_posix(): p.read_bytes() for p in sorted(app.rglob("*")) if p.is_file()}


# ── precondition_faults ─────────────────────────────────────────────────────


def _results(app: Path):
    shapes = Graph().parse(SHAPES_FILE, format="turtle")
    return shape_results(app / "expenses.trig", shapes), shapes


def test_precondition_faults_are_sorted_and_check_raises_the_first(app):
    _break(app, OTHER, BROKEN)
    results, shapes = _results(app)
    gen = discover()["strict-gen"]
    faults = gen.precondition_faults(results, shapes)
    assert [(f.subject, f.predicate, f.detail) for f in faults] == [
        (OTHER, MODEL_SHAPE, REQUIRES + NOTATION),
        (BROKEN, MODEL_SHAPE, REQUIRES + NOTATION),
    ]
    with pytest.raises(GeneratorError) as err:
        gen.check_preconditions(results, shapes)
    assert str(err.value) == f"{OTHER}: {MODEL_SHAPE}: {REQUIRES}{NOTATION} (and 1 more)"


def test_a_conforming_model_has_no_precondition_faults(app):
    results, shapes = _results(app)
    gen = discover()["strict-gen"]
    assert gen.precondition_faults(results, shapes) == []
    gen.check_preconditions(results, shapes)


# ── generate_project ────────────────────────────────────────────────────────


def test_strict_mode_raises_a_violated_precondition_unchanged(app):
    _break(app, BROKEN)
    project = _project(app, BUILTIN + STRICT)
    with pytest.raises(GeneratorError) as err:
        generate_project(project, project.model)
    assert str(err.value) == f"{BROKEN}: {MODEL_SHAPE}: {REQUIRES}{NOTATION}"


def test_strict_mode_raises_a_generators_own_error(app):
    _break(app, BROKEN)
    project = _project(app, BUILTIN + FRAGILE)
    with pytest.raises(GeneratorError, match="no notation to render"):
        generate_project(project, project.model)


def test_strict_mode_on_a_clean_model_has_no_faults(app):
    project = _project(app, BUILTIN + STRICT + FRAGILE)
    generated = generate_project(project, project.model)
    assert generated.faults == ()
    assert generated == generate_project(project, project.model, lenient=True)


def test_lenient_mode_collects_faults_and_still_runs_the_other_generators(app):
    _break(app, BROKEN)
    project = _project(app, BUILTIN + STRICT + FRAGILE)
    generated = generate_project(project, project.model, lenient=True)
    assert generated.faults == (FRAGILE_FAULT, PRECONDITION_FAULT)
    names = {path.relative_to(app).as_posix() for path in generated.files}
    # strict-gen runs despite its precondition fault; fragile-gen raised and contributes nothing.
    assert "generated/strict/strict.txt" in names and "generated/expense_api.py" in names
    assert not any(name.startswith("generated/fragile/") for name in names)


# ── apply and seams.lock ────────────────────────────────────────────────────


def test_two_lenient_runs_write_identical_bytes(app):
    _break(app, BROKEN)
    project = _project(app, BUILTIN + STRICT + FRAGILE)
    apply(project, project.model, generate_project(project, project.model, lenient=True))
    first = _tree(app)
    apply(project, project.model, generate_project(project, project.model, lenient=True))
    assert _tree(app) == first
    data = json.loads((app / "seams.lock").read_text(encoding="utf-8"))
    assert data["faults"] == [f._asdict() for f in (FRAGILE_FAULT, PRECONDITION_FAULT)]
    assert read_lock(project).faults == (FRAGILE_FAULT, PRECONDITION_FAULT)


def test_a_lock_without_faults_is_byte_identical_to_a_strict_one(app):
    project = _project(app, BUILTIN)
    apply(project, project.model, generate_project(project, project.model, lenient=True))
    assert (app / "seams.lock").read_bytes() == (CHAPTER / "seams.lock").read_bytes()
    assert "faults" not in json.loads((app / "seams.lock").read_text(encoding="utf-8"))
    assert read_lock(project).faults == ()


def test_an_orphan_of_a_faulted_generator_is_kept_and_stays_locked(app):
    project = _project(app, BUILTIN + FRAGILE)
    apply(project, project.model, generate_project(project, project.model))
    fragile = app / "generated" / "fragile" / "fragile.txt"
    entry = next(o for o in read_lock(project).outputs if o.generator == "fragile-gen")
    _break(app, BROKEN)
    applied = apply(project, project.model, generate_project(project, project.model, lenient=True))
    assert fragile.read_text(encoding="utf-8") == "fine\n"
    assert fragile not in applied.removed and fragile not in applied.kept
    lock = read_lock(project)
    assert entry in lock.outputs
    assert lock.faults == (FRAGILE_FAULT,)


def test_render_lock_sorts_faults():
    lock = Lock("m.trig", "h", (), (PRECONDITION_FAULT, FRAGILE_FAULT))
    data = json.loads(render_lock(lock))
    assert [f["generator"] for f in data["faults"]] == ["fragile-gen", "strict-gen"]
    assert sorted(data["faults"][0]) == ["focus", "generator", "message", "shape"]


@pytest.mark.parametrize(
    ("faults", "key"),
    [
        ({}, "`faults` must be a list"),
        (["x"], "`faults[0]` must be a dict"),
        ([{"generator": "g", "shape": "s", "focus": "f"}], "`faults[0].message` must be a str, got NoneType"),
        ([{"generator": 1, "shape": "s", "focus": "f", "message": "m"}], "`faults[0].generator` must be a str"),
    ],
)
def test_a_malformed_faults_entry_raises_lock_error(app, faults, key):
    project = _project(app, BUILTIN)
    apply(project, project.model, generate_project(project, project.model))
    path = app / "seams.lock"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["faults"] = faults
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LockError, match=re.escape(f"{path}: {key}")):
        read_lock(project)


# ── seams generate --lenient and seams check (CLI) ─────────────────────────


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def _cli(*argv: str) -> int:
    return main(list(argv))


def _summary(n: int) -> str:
    return f"seams generate: {n} fault(s); output is flagged\n"


def _line(fault: Fault) -> str:
    return f"seams generate: fault {fault.generator}: {fault.focus}: {fault.shape}: {fault.message}\n"


def _check_lines(app: Path, capsys) -> list[str]:
    assert _cli("check", "--project", str(app)) == 1
    out, err = capsys.readouterr()
    assert err.startswith("seams check: ") and "problem(s)" in err
    return out.splitlines()


def test_cli_lenient_precondition_fault_writes_flagged_output(app, capsys):
    _break(app, BROKEN)
    _project(app, BUILTIN + STRICT)
    assert _cli("generate", "--project", str(app), "--lenient") == 0
    out, err = capsys.readouterr()
    assert err == _line(PRECONDITION_FAULT) + _summary(1)
    assert out.splitlines()[-1] == str(app / "seams.lock")
    assert (app / "generated/strict/strict.txt").read_text(encoding="utf-8") == "ok\n"
    assert (app / "generated/expense_api.py").is_file()
    project = load_project(app)
    assert read_lock(project).faults == (PRECONDITION_FAULT,)

    lines = _check_lines(app, capsys)
    assert f"flagged {app / 'seams.lock'} 1 fault(s)" in lines
    # The lock matches what lenient generation writes: no output or lock finding.
    assert not {line.split(" ", 1)[0] for line in lines} & FILE_KINDS

    before = _tree(app)
    assert _cli("generate", "--project", str(app)) == 2
    assert capsys.readouterr().err == f"seams generate: {BROKEN}: {MODEL_SHAPE}: {REQUIRES}{NOTATION}\n"
    assert _tree(app) == before


def _raise_on_broken(trig: Path, out: Path):
    if "broken_model" in trig.read_text(encoding="utf-8"):
        raise GeneratorError(BROKEN, "seam:notation", "cannot render a model without a notation")
    return None


RAISER = Generator(
    name="raiser",
    version="2.0.0",
    help="raises on a broken model",
    extract=_raise_on_broken,
    render=lambda view: {"raiser.txt": "rendered\n"},
    sources=lambda trig, out: {"raiser.txt": ()},
)
RAISER_FAULT = Fault("raiser", "seam:notation", BROKEN, "cannot render a model without a notation")


@pytest.fixture
def raiser(monkeypatch):
    registry = {**discover(), "raiser": RAISER}
    monkeypatch.setattr(seams_gen.registry, "discover", lambda: registry)


def test_cli_lenient_generator_error_keeps_its_locked_output(app, raiser, capsys):
    _project(app, BUILTIN + '[[generators]]\nname = "raiser"\nout = "generated/raiser"\n')
    assert _cli("generate", "--project", str(app)) == 0
    capsys.readouterr()
    output = app / "generated/raiser/raiser.txt"
    entry = next(o for o in read_lock(load_project(app)).outputs if o.generator == "raiser")

    _break(app, BROKEN)
    assert _cli("generate", "--project", str(app), "--lenient") == 0
    out, err = capsys.readouterr()
    assert err == _line(RAISER_FAULT) + _summary(1)
    assert "removed" not in out
    assert output.read_text(encoding="utf-8") == "rendered\n"
    lock = read_lock(load_project(app))
    assert lock.faults == (RAISER_FAULT,)
    assert entry in lock.outputs

    lines = _check_lines(app, capsys)
    assert f"flagged {app / 'seams.lock'} 1 fault(s)" in lines
    # The carried output is neither an orphan nor a reason for lock-out-of-date.
    assert not {line.split(" ", 1)[0] for line in lines} & FILE_KINDS

    before = _tree(app)
    assert _cli("generate", "--project", str(app)) == 2
    assert (
        capsys.readouterr().err
        == f"seams generate: {BROKEN}: seam:notation: cannot render a model without a notation\n"
    )
    assert _tree(app) == before


def test_check_reports_a_fault_the_lock_does_not_record_as_lock_out_of_date(app, raiser, capsys):
    _project(app, BUILTIN + '[[generators]]\nname = "raiser"\nout = "generated/raiser"\n')
    assert _cli("generate", "--project", str(app)) == 0
    _break(app, BROKEN)
    capsys.readouterr()
    lines = _check_lines(app, capsys)
    assert f"lock-out-of-date {app / 'seams.lock'}" in lines
    assert not any(line.startswith("flagged ") for line in lines)


def test_a_clean_lenient_run_prints_no_faults_and_checks_clean(app, capsys):
    _project(app, BUILTIN)
    assert _cli("generate", "--project", str(app), "--lenient") == 0
    assert capsys.readouterr().err == ""
    assert _cli("check", "--project", str(app)) == 0
