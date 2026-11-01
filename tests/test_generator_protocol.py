"""The built-in generators as Generator objects (M018/S01, backlog K3).

Each object of ``seams_gen.builtin`` returns the same files as the
generator's ``seams_gen.__main__.GENERATORS`` function, for the chat app and
expenses chapter 8, or raises the same GeneratorError.
"""

import dataclasses
from pathlib import Path

import pytest

import seams_gen
from seams_gen import GeneratorError
from seams_gen.__main__ import GENERATORS
from seams_gen.builtin import BUILTINS
from seams_gen.protocol import Generator
from seams_gen.sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples/chat-app/chat-app.trig",
    "chapter-08": ROOT / "examples/expenses/chapter-08/expenses.trig",
}
BY_NAME = {g.name: g for g in BUILTINS}
CASES = [(name, model) for name in GENERATORS for model in MODELS]


def _outcome(generate, trig: Path) -> dict[str, str] | str:
    """The files, or the GeneratorError message."""
    try:
        return generate(trig, trig.parent)
    except GeneratorError as err:
        return f"GeneratorError: {err}"


def test_one_builtin_per_generator():
    assert [g.name for g in BUILTINS] == list(GENERATORS)


@pytest.mark.parametrize(("name", "model"), CASES, ids=[f"{n}:{m}" for n, m in CASES])
def test_generate_equals_the_old_function(name, model):
    old = _outcome(GENERATORS[name][1], MODELS[model])
    new = _outcome(BY_NAME[name].generate, MODELS[model])
    assert new == old


def test_every_builtin_generates_from_some_example():
    """The equality above is not only two equal errors."""
    for name in GENERATORS:
        assert any(isinstance(_outcome(BY_NAME[name].generate, m), dict) for m in MODELS.values()), name


@pytest.mark.parametrize("name", list(GENERATORS))
def test_fields_are_typed(name):
    g = BY_NAME[name]
    assert isinstance(g, Generator)
    assert g.name == name
    assert g.version == seams_gen.__version__
    assert g.help == GENERATORS[name][0]
    assert g.preconditions == ()
    assert g.sources is SOURCES[name]
    assert callable(g.extract) and callable(g.render)


def test_generator_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        BY_NAME["htmx"].name = "other"  # type: ignore[misc]


def test_fields_are_keyword_only():
    with pytest.raises(TypeError):
        Generator("x", "1", "help", lambda t, o: None, lambda v: {}, lambda t, o: {})  # type: ignore[misc]


def test_generate_is_render_of_extract():
    trig = MODELS["chat-app"]
    g = BY_NAME["htmx"]
    view = g.extract(trig, trig.parent)
    assert all(dataclasses.is_dataclass(p) for p in view)
    assert g.render(view) == g.generate(trig, trig.parent)


def test_ifmledit_names_unmapped_terms_on_stderr(capsys):
    trig = MODELS["chat-app"]
    BY_NAME["ifmledit"].generate(trig, trig.parent)
    assert capsys.readouterr().err.startswith("seams_gen ifmledit: not exported, no IFMLEdit counterpart: ")


def test_extract_error_is_the_generators_own():
    """Chapter 1 has no serving container: extract raises the generator's own GeneratorError."""
    trig = ROOT / "examples/expenses/chapter-01/expenses.trig"
    with pytest.raises(GeneratorError) as err:
        BY_NAME["fastapi"].extract(trig, trig.parent)
    assert f"GeneratorError: {err.value}" == _outcome(GENERATORS["fastapi"][1], trig)
