"""The built-in generators as Generator objects (M018/S01, backlog K3).

Each object of ``seams_gen.builtin`` returns the same files as the
generator's old ``generate`` function (``LEGACY``, the functions
``seams_gen.__main__.GENERATORS`` held before it became a view of the
registry), for the chat app and expenses chapter 8, or raises the same
GeneratorError.
"""

import dataclasses
import sys
from pathlib import Path

import pytest
from seams import load

import seams_gen
from seams_gen import GeneratorError
from seams_gen.__main__ import GENERATORS
from seams_gen.acceptance import generate_acceptance
from seams_gen.builtin import BUILTINS
from seams_gen.compose import generate_compose_environments
from seams_gen.dockerfile import generate_dockerfiles
from seams_gen.fastapi import route_module
from seams_gen.htmx import generate_pages
from seams_gen.ifmledit import generate as generate_ifmledit
from seams_gen.ifmledit import unmapped_summary
from seams_gen.jsonld import extract_jsonld, render_jsonld
from seams_gen.protocol import Generator
from seams_gen.smoke import generate_smoke
from seams_gen.sources import SOURCES
from seams_gen.tests import generate_tests

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "chat-app": ROOT / "examples/chat-app/chat-app.trig",
    "chapter-08": ROOT / "examples/expenses/chapter-08/expenses.trig",
}
BY_NAME = {g.name: g for g in BUILTINS}


def _legacy_ifmledit(trig: Path, out: Path) -> dict[str, str]:
    files = generate_ifmledit(load(trig))
    print(unmapped_summary(), file=sys.stderr)
    return files


# generator name -> its generate(trig, out) before the protocol (M018/S01); jsonld,
# newer than the protocol, is its module's own render(extract(model))
LEGACY = {
    "htmx": lambda trig, out: generate_pages(load(trig)),
    "fastapi": lambda trig, out: dict([route_module(trig)]),
    "compose": lambda trig, out: generate_compose_environments(trig, base_dir=out),
    "tests": lambda trig, out: generate_tests(trig),
    "smoke": lambda trig, out: generate_smoke(trig),
    "dockerfile": lambda trig, out: generate_dockerfiles(trig),
    "ifmledit": _legacy_ifmledit,
    "acceptance": lambda trig, out: generate_acceptance(trig),
    "jsonld": lambda trig, out: render_jsonld(extract_jsonld(load(trig))),
}
CASES = [(name, model) for name in LEGACY for model in MODELS]


def _outcome(generate, trig: Path) -> dict[str, str] | str:
    """The files, or the GeneratorError message."""
    try:
        return generate(trig, trig.parent)
    except GeneratorError as err:
        return f"GeneratorError: {err}"


def test_one_builtin_per_generator():
    assert sorted(g.name for g in BUILTINS) == sorted(LEGACY) == list(GENERATORS)


@pytest.mark.parametrize("name", list(LEGACY))
def test_generators_is_the_registered_builtin(name):
    help_text, generate = GENERATORS[name]
    assert (help_text, generate) == (BY_NAME[name].help, BY_NAME[name].generate)


@pytest.mark.parametrize(("name", "model"), CASES, ids=[f"{n}:{m}" for n, m in CASES])
def test_generate_equals_the_old_function(name, model):
    old = _outcome(LEGACY[name], MODELS[model])
    new = _outcome(BY_NAME[name].generate, MODELS[model])
    assert new == old


def test_every_builtin_generates_from_some_example():
    """The equality above is not only two equal errors."""
    for name in LEGACY:
        assert any(isinstance(_outcome(BY_NAME[name].generate, m), dict) for m in MODELS.values()), name


@pytest.mark.parametrize("name", list(LEGACY))
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
    assert f"GeneratorError: {err.value}" == _outcome(LEGACY["fastapi"], trig)
