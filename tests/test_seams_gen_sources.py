"""seams_gen.sources lists, per generated file, the model elements it comes from (M012/S02, D043).

Every example project with generators is checked: the source file names equal
the generator's file names, every tuple is non-empty, sorted and unique, and
every IRI is a subject of the loaded model.
"""

from pathlib import Path

import pytest
from seams import load
from seams_cli import load_project, resolve_model

from seams_gen import GeneratorError
from seams_gen.__main__ import GENERATORS
from seams_gen.sources import SOURCES, output_sources

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = sorted(
    p.parent.relative_to(ROOT) for p in (ROOT / "examples").rglob("seams.toml") if load_project(p.parent).generators
)
TARGETS = [(rel, t.name) for rel in PROJECTS for t in load_project(ROOT / rel).generators]


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def test_every_generator_has_sources():
    assert SOURCES.keys() == GENERATORS.keys()


def test_projects_found():
    assert Path("examples/chat-app") in PROJECTS
    assert {Path(f"examples/expenses/chapter-0{n}") for n in range(3, 9)} <= set(PROJECTS)


@pytest.mark.parametrize(("rel", "name"), TARGETS, ids=[f"{rel}:{name}" for rel, name in TARGETS])
def test_sources_match_generated_files(rel, name):
    project = load_project(ROOT / rel)
    model = resolve_model(project)
    (target,) = [t for t in project.generators if t.name == name]
    sources = output_sources(name, model, target.out)
    assert sources.keys() == GENERATORS[name][1](model, target.out).keys()
    subjects = {str(s) for s in load(model).ds.subjects()}
    for file, iris in sources.items():
        assert iris, file
        assert list(iris) == sorted(set(iris)), file
        assert all(isinstance(i, str) and ("://" in i or i.startswith("urn:")) for i in iris), file
        assert set(iris) <= subjects, (file, set(iris) - subjects)


def test_chat_app_sources():
    project = load_project(ROOT / "examples/chat-app")
    model = resolve_model(project)
    m = load(model)
    sources = {t.name: output_sources(t.name, model, t.out) for t in project.generators}
    page = sources["htmx"]["chat_page.html"]
    assert str(m.curie(":chat_page")) in page
    # a fragment partial lists its component and the operations that render it
    thread = sources["htmx"]["message_thread.html"]
    assert str(m.curie(":message_thread")) in thread
    compose = sources["compose"]["compose.yaml"]
    assert len(compose) == len(m.architecture.systems()[0].containers) + 1


def test_task_form_sources_name_task_and_shape():
    project = load_project(ROOT / "examples/expenses/chapter-08")
    model = resolve_model(project)
    (htmx,) = [t for t in project.generators if t.name == "htmx"]
    sources = output_sources("htmx", model, htmx.out)
    ns = "https://example.org/expenses/"
    # the form, the user task completed on it, the shape it writes, the shape the task reads
    assert sources["approve_form.html"] == (
        f"{ns}ApprovalShape",
        f"{ns}ExpenseShape",
        f"{ns}approval_bpmn#approve_expense",
        f"{ns}approve_form",
    )
    # a partial several operations render lists them all
    assert sources["expense_details.html"] == (
        f"{ns}approve_expense_op",
        f"{ns}expense_details",
        f"{ns}expense_details_op",
        f"{ns}finance_approve_expense_op",
        f"{ns}pay_expense_op",
    )


def test_unknown_generator_raises_key_error():
    with pytest.raises(KeyError):
        output_sources("nope", ROOT / "examples/chat-app/chat-app.trig", ROOT)


def test_missing_fact_raises_generator_error(tmp_path):
    """A model with no arch:System fails compose sources as compose itself fails."""
    trig = tmp_path / "empty.trig"
    trig.write_text("@prefix : <http://example.org/m#> .\n:m a :Thing .\n", encoding="utf-8")
    for name in ("compose", "fastapi", "htmx"):
        with pytest.raises(GeneratorError):
            output_sources(name, trig, tmp_path)
