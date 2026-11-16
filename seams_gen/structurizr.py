"""The Structurizr DSL export (M033/S01, backlog X9, ADR-0044).

``render_structurizr(view)`` prints the ``C4Model`` of ``seams_gen.c4`` as
one Structurizr DSL workspace, ``workspace.dsl``:

- a header comment, then one ``# gap:`` comment line per gap of the model;
- ``model``: each person, then each system (``tags "External"`` when it is
  arch:external, ADR-0040) with its containers (the arch:technology as the
  container's technology, an empty description), then each relationship,
  all by IRI;
- ``views``: a ``systemContext`` view of each of the model's own systems and
  a ``container`` view of every system with containers, keyed
  ``<system>-context`` and ``<system>-containers``, each ``include *`` with
  ``autoLayout``.

Identifiers are the ``C4Model``'s, so the DSL's flat identifier scope holds
(a clash is ``extract_c4``'s ``GeneratorError``). Names are the elements'
rdfs:labels, quoted. The workspace has no name: the model's subject is a
file path, and an export carries no paths. There is no model hash or
timestamp; seams.lock records where the file came from.
"""

from __future__ import annotations

from .c4 import C4Model, Container, System
from .protocol import Files

FILE = "workspace.dsl"
INDENT = "    "
HEADER = (
    "# Structurizr DSL workspace of the model's C4 layer, written by the seams_gen structurizr generator "
    "(ADR-0044). Regenerate it with `seams generate`; do not edit it."
)


def _q(text: str) -> str:
    """``text`` as a DSL string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _container(c: Container) -> str:
    parts = [f"{c.identifier} = container {_q(c.name)}"]
    if c.technology is not None:
        parts.append(f'"" {_q(c.technology)}')
    return " ".join(parts)


def _system(s: System, depth: int) -> list[str]:
    pad = INDENT * depth
    head = f"{pad}{s.identifier} = softwareSystem {_q(s.name)}"
    body = ([f"{pad}{INDENT}tags {_q('External')}"] if s.external else []) + [
        f"{pad}{INDENT}{_container(c)}" for c in s.containers
    ]
    return [f"{head} {{", *body, f"{pad}}}"] if body else [head]


def _view(kind: str, s: System, key: str) -> list[str]:
    pad = INDENT * 2
    return [
        f"{pad}{kind} {s.identifier} {_q(f'{s.identifier}-{key}')} {{",
        f"{pad}{INDENT}include *",
        f"{pad}{INDENT}autoLayout",
        f"{pad}}}",
    ]


def workspace(view: C4Model) -> str:
    """The workspace text, with a trailing newline."""
    lines = [HEADER, *(f"# gap: {g}" for g in view.gaps), "workspace {", f"{INDENT}model {{"]
    pad = INDENT * 2
    lines += [f"{pad}{p.identifier} = person {_q(p.name)}" for p in view.people]
    for s in view.systems:
        lines += _system(s, 2)
    lines += [f"{pad}{r.source_id} -> {r.destination_id} {_q(r.label)}" for r in view.relationships]
    lines += [f"{INDENT}}}", f"{INDENT}views {{"]
    for s in view.systems:
        if not s.external:
            lines += _view("systemContext", s, "context")
    for s in view.systems:
        if s.containers:
            lines += _view("container", s, "containers")
    lines += [f"{INDENT}}}", "}"]
    return "\n".join(lines) + "\n"


def render_structurizr(view: C4Model) -> Files:
    """{``workspace.dsl``: the workspace}."""
    return {FILE: workspace(view)}


__all__ = ["FILE", "render_structurizr", "workspace"]
