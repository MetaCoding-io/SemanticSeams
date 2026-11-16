"""The LikeC4 export (M033/S01, backlog X9, ADR-0044).

``render_likec4(view)`` prints the ``C4Model`` of ``seams_gen.c4`` as one
LikeC4 model, ``model.c4``:

- a header comment, then one ``// gap:`` comment line per gap of the model;
- ``specification``: the ``person``, ``system`` and ``container`` element
  kinds and the ``external`` tag;
- ``model``: each person, then each system (``#external`` when it is
  arch:external, ADR-0040) nesting its containers (each with its
  arch:technology as ``technology``), then each relationship, all by IRI. A
  container is referred to by its fully qualified name,
  ``<system>.<container>``, since LikeC4 scopes names by their parent;
- ``views``: ``view index`` of the whole model, then a ``view <system>_view
  of <system>`` of each system, each ``include *``.

Identifiers are the ``C4Model``'s (a clash is ``extract_c4``'s
``GeneratorError``). Titles are the elements' rdfs:labels, quoted. The model
carries no name, model hash, timestamp or path; seams.lock records where the
file came from.
"""

from __future__ import annotations

from .c4 import C4Model, Container, System
from .protocol import Files

FILE = "model.c4"
INDENT = "  "
HEADER = (
    "// LikeC4 model of the model's C4 layer, written by the seams_gen likec4 generator (ADR-0044). "
    "Regenerate it with `seams generate`; do not edit it."
)
SPECIFICATION = ("element person", "element system", "element container", "tag external")


def _q(text: str) -> str:
    """``text`` as a LikeC4 string literal."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _container(c: Container, depth: int) -> list[str]:
    pad = INDENT * depth
    head = f"{pad}{c.identifier} = container {_q(c.name)}"
    if c.technology is None:
        return [head]
    return [f"{head} {{", f"{pad}{INDENT}technology {_q(c.technology)}", f"{pad}}}"]


def _system(s: System, depth: int) -> list[str]:
    pad = INDENT * depth
    head = f"{pad}{s.identifier} = system {_q(s.name)}"
    body = [f"{pad}{INDENT}#external"] if s.external else []
    for c in s.containers:
        body += _container(c, depth + 1)
    return [f"{head} {{", *body, f"{pad}}}"] if body else [head]


def _names(view: C4Model) -> dict[str, str]:
    """IRI -> fully qualified LikeC4 name of every element."""
    names = {p.iri: p.identifier for p in view.people}
    for s in view.systems:
        names[s.iri] = s.identifier
        names.update({c.iri: f"{s.identifier}.{c.identifier}" for c in s.containers})
    return names


def model_text(view: C4Model) -> str:
    """The model text, with a trailing newline."""
    lines = [HEADER, *(f"// gap: {g}" for g in view.gaps), "specification {"]
    lines += [f"{INDENT}{s}" for s in SPECIFICATION]
    lines += ["}", "model {"]
    lines += [f"{INDENT}{p.identifier} = person {_q(p.name)}" for p in view.people]
    for s in view.systems:
        lines += _system(s, 1)
    names = _names(view)
    lines += [f"{INDENT}{names[r.source]} -> {names[r.destination]} {_q(r.label)}" for r in view.relationships]
    lines += ["}", "views {", f"{INDENT}view index {{", f"{INDENT * 2}include *", f"{INDENT}}}"]
    for s in view.systems:
        lines += [f"{INDENT}view {s.identifier}_view of {s.identifier} {{", f"{INDENT * 2}include *", f"{INDENT}}}"]
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_likec4(view: C4Model) -> Files:
    """{``model.c4``: the model}."""
    return {FILE: model_text(view)}


__all__ = ["FILE", "render_likec4", "model_text"]
