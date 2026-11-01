"""The generator registry: the ``seams.generators`` entry-point group (M018/S01, D056).

``discover()`` loads every entry point of the group and returns
``{name: Generator}`` sorted by name. The built-in generators are found the
same way as a third-party one: their entry points are declared in
packages/seams-cli/pyproject.toml, because seams_gen is a virtual member and
installs no metadata of its own (D033). A third-party distribution declares

    [project.entry-points."seams.generators"]
    my-gen = "my_package.module:generator"

where ``generator`` is a ``seams_gen.protocol.Generator`` whose ``name`` is
``my-gen``. An entry point that does not load, does not load a Generator,
names a different generator or repeats a name raises ``RegistryError``,
which names the entry point and its distribution.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

from . import GeneratorError
from .protocol import Generator

GROUP = "seams.generators"


class RegistryError(GeneratorError):
    """An entry point of the ``seams.generators`` group cannot be registered.

    The message names the entry point (``name = value``), its distribution
    and what is wrong.
    """

    def __init__(self, entry_point: EntryPoint, detail: str):
        self.entry_point = f"{entry_point.name} = {entry_point.value}"
        self.distribution = _distribution(entry_point)
        self.subject = self.entry_point
        self.predicate = GROUP
        self.detail = detail
        Exception.__init__(
            self, f"{GROUP} entry point {self.entry_point} of distribution {self.distribution}: {detail}"
        )


def _distribution(ep: EntryPoint) -> str:
    dist = ep.dist
    return "(unknown)" if dist is None else f"{dist.name} {dist.version}"


def discover() -> dict[str, Generator]:
    """{name: Generator} of every ``seams.generators`` entry point, sorted by name."""
    found: dict[str, tuple[EntryPoint, Generator]] = {}
    for ep in sorted(entry_points(group=GROUP), key=lambda e: (e.name, e.value)):
        try:
            obj = ep.load()
        except Exception as err:  # any import or attribute failure of a plugin
            raise RegistryError(ep, f"does not load: {type(err).__name__}: {err}") from err
        if not isinstance(obj, Generator):
            raise RegistryError(ep, f"loads an object of type {type(obj).__name__}, not a seams_gen.protocol.Generator")
        if obj.name != ep.name:
            raise RegistryError(ep, f"loads the generator named {obj.name!r}, not {ep.name!r}")
        if ep.name in found:
            other = found[ep.name][0]
            raise RegistryError(
                ep, f"repeats the generator name {ep.name!r} of {other.name} = {other.value} of {_distribution(other)}"
            )
        found[ep.name] = (ep, obj)
    return {name: gen for name, (_, gen) in sorted(found.items())}


__all__ = ["GROUP", "RegistryError", "discover"]
