"""The seams.generators entry-point registry (M018/S01, D056).

The built-in generators are discovered through their entry points in
packages/seams-cli/pyproject.toml. A third-party distribution is simulated by a
``<name>-1.0.dist-info`` directory (METADATA and entry_points.txt) and its
module in ``tmp_path``, put on sys.path: nothing is installed.
"""

import sys
from pathlib import Path

import pytest

from seams_gen import GeneratorError
from seams_gen.__main__ import GENERATORS
from seams_gen.builtin import BUILTINS
from seams_gen.registry import GROUP, RegistryError, discover
from seams_gen.sources import output_sources

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"

PLUGIN = """
from seams_gen.protocol import Generator

generator = Generator(
    name="example-gen",
    version="9.9.9",
    help="one example file",
    extract=lambda trig, out: trig.name,
    render=lambda name: {"example.txt": f"made from {name}\\n"},
    sources=lambda trig, out: {"example.txt": ("urn:example:model",)},
)
renamed = Generator(
    name="other-name",
    version="9.9.9",
    help="a generator under the wrong entry-point name",
    extract=lambda trig, out: None,
    render=lambda view: {},
    sources=lambda trig, out: {},
)
htmx = Generator(
    name="htmx",
    version="9.9.9",
    help="a second htmx",
    extract=lambda trig, out: None,
    render=lambda view: {},
    sources=lambda trig, out: {},
)
not_a_generator = 42
"""


@pytest.fixture
def dist(tmp_path, monkeypatch):
    """dist(entry_points) puts a distribution ``example-gen 1.0`` on sys.path
    whose ``seams.generators`` group is ``{name: value}`` and whose module
    ``example_gen_plugin`` holds the PLUGIN objects."""

    def make(entries: dict[str, str]) -> Path:
        (tmp_path / "example_gen_plugin.py").write_text(PLUGIN, encoding="utf-8")
        info = tmp_path / "example_gen-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example-gen\nVersion: 1.0\n", encoding="utf-8")
        lines = "".join(f"{name} = {value}\n" for name, value in entries.items())
        (info / "entry_points.txt").write_text(f"[{GROUP}]\n{lines}", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, "example_gen_plugin", raising=False)
        return tmp_path

    return make


def _error() -> str:
    with pytest.raises(RegistryError) as err:
        discover()
    assert isinstance(err.value, GeneratorError)
    return str(err.value)


def test_builtins_are_discovered():
    found = discover()
    assert list(found) == sorted(g.name for g in BUILTINS)
    assert all(found[g.name] is g for g in BUILTINS)


def test_generators_is_a_view_of_the_registry():
    assert GENERATORS == {name: (g.help, g.generate) for name, g in discover().items()}


def test_third_party_generator_is_discovered(dist):
    dist({"example-gen": "example_gen_plugin:generator"})
    found = discover()
    assert list(found) == sorted([*(g.name for g in BUILTINS), "example-gen"])
    gen = found["example-gen"]
    assert (gen.name, gen.version) == ("example-gen", "9.9.9")
    assert gen.generate(CHAT, CHAT.parent) == {"example.txt": "made from chat-app.trig\n"}
    assert output_sources("example-gen", CHAT, CHAT.parent) == {"example.txt": ("urn:example:model",)}


def test_load_failure_names_entry_point_and_distribution(dist):
    dist({"broken": "no_such_module_for_seams:generator"})
    assert _error() == (
        "seams.generators entry point broken = no_such_module_for_seams:generator of distribution "
        "example-gen 1.0: does not load: ModuleNotFoundError: No module named 'no_such_module_for_seams'"
    )


def test_missing_attribute_is_a_load_failure(dist):
    dist({"missing": "example_gen_plugin:no_such_object"})
    assert _error() == (
        "seams.generators entry point missing = example_gen_plugin:no_such_object of distribution "
        "example-gen 1.0: does not load: AttributeError: module 'example_gen_plugin' has no attribute "
        "'no_such_object'"
    )


def test_not_a_generator(dist):
    dist({"number": "example_gen_plugin:not_a_generator"})
    assert _error() == (
        "seams.generators entry point number = example_gen_plugin:not_a_generator of distribution "
        "example-gen 1.0: loads an object of type int, not a seams_gen.protocol.Generator"
    )


def test_entry_point_name_differs_from_generator_name(dist):
    dist({"wrong-name": "example_gen_plugin:renamed"})
    assert _error() == (
        "seams.generators entry point wrong-name = example_gen_plugin:renamed of distribution "
        "example-gen 1.0: loads the generator named 'other-name', not 'wrong-name'"
    )


def test_duplicate_name(dist):
    dist({"htmx": "example_gen_plugin:htmx"})
    # entry points are read in (name, value) order, so the built-in comes second
    assert _error() == (
        "seams.generators entry point htmx = seams_gen.builtin:htmx of distribution semanticseams-cli 0.1.0: "
        "repeats the generator name 'htmx' of htmx = example_gen_plugin:htmx of example-gen 1.0"
    )


def test_error_carries_entry_point_and_distribution(dist):
    dist({"number": "example_gen_plugin:not_a_generator"})
    with pytest.raises(RegistryError) as err:
        discover()
    assert err.value.entry_point == "number = example_gen_plugin:not_a_generator"
    assert err.value.distribution == "example-gen 1.0"
