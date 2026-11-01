"""The IFMLEdit exporter: the model's IFML layer as IFMLEdit.org JSON (backlog 12, M008/S01).

``extract_ifmledit`` reads the IFML layer only through ``model.interfaces``
(D036) into a frozen ``IfmlEditDocument``, and ``render_ifmledit`` writes it
as the JSON the IFMLEdit.org editor loads (``client/js/ifml/fromjson`` in
github.com/B3rn475/IFMLEdit.org):

- ``elements``: every ifml:ViewContainer (``ifml.ViewContainer`` with
  ``name``, ``default``, ``landmark``, ``xor`` from rdfs:label,
  ifml:isDefault, ifml:isLandmark, ifml:isXOR), every ifml:List, ifml:Details
  and ifml:Form (``ifml.ViewComponent`` with stereotype ``list``,
  ``details`` or ``form``, and its ifml:hasParameter parameters' local names
  as ``fields``), every ifml:Event (``ifml.Event`` with its ``name``) and
  every ifml:NavigationFlow and ifml:DataFlow (with each ifml:binds
  ParameterBinding as a ``bindings`` entry: ifml:sourceParameter is the
  ``output``, ifml:targetParameter the ``input``).
- ``relations``: ``hierarchy`` (parent, child) for each ifml:contains
  between view elements and each ifml:hasEvent, ``source`` and ``target``
  (flow, element) for each flow's ifml:source and ifml:target.

Every id is the element's IRI local name; elements are sorted by id and
relations by their fields (principle 6). IFMLEdit's loader needs a position
and size for every view element and a position for every event, so
``metadata.graphics`` holds a fixed layout: top-level containers left to
right, each container's components (by ifml:order, then IRI) and nested
containers stacked inside it, events along their owner's bottom edge. A
top-level ``seams`` object names the generator and the model hash
(principle 7); IFMLEdit reads only ``elements`` and ``relations``.

The IFML terms IFMLEdit has no counterpart for are left out, not patched in
the vocabulary; ``UNMAPPED`` lists them with the reason, and the CLI prints
them to stderr. Generator-only faults (IFMLEdit's structure, not a shape):
a model with no ifml:InteractionModel, a component that is not exactly one
of ifml:List, ifml:Details and ifml:Form, a view element contained by
several containers, an event without exactly one exported owner, a flow
whose source or target is not exported, and two elements with one local name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rdflib import RDF, URIRef
from seams import IFML, Element, Model, local_name

from . import GeneratorError
from ._views import view_errors

FILE = "ifmledit.json"
GENERATOR = "seams_gen ifmledit"

#: The IFMLEdit stereotype of each concrete component class.
STEREOTYPES = {IFML.List: "list", IFML.Details: "details", IFML.Form: "form"}

#: The ifml: terms with no IFMLEdit counterpart, left out of the export, by IRI.
UNMAPPED: tuple[tuple[URIRef, str], ...] = (
    (IFML.Append, "IFMLEdit flows have no swap strategy"),
    (IFML.InteractionModel, "an IFMLEdit file is one model; its top-level containers stand alone"),
    (IFML.Prepend, "IFMLEdit flows have no swap strategy"),
    (IFML.Replace, "IFMLEdit flows have no swap strategy"),
    (IFML.SwapStrategy, "IFMLEdit flows have no swap strategy"),
    (IFML.boundTo, "IFMLEdit fields name no shape property"),
    (IFML.order, "IFMLEdit has no component order; it only orders the layout"),
    (IFML.path, "IFMLEdit containers have no URL path"),
    (IFML.swap, "IFMLEdit flows have no swap strategy"),
    (IFML.title, "IFMLEdit containers have no browser title"),
    (IFML.trigger, "IFMLEdit events have no trigger; every event is a user event"),
)

# The layout, in IFMLEdit canvas units.
MARGIN = 40  # around and between top-level elements
PAD = 20  # inside a container, left and right of its children and below them
HEADER = 40  # above a container's first child, for its name
GAP = 20  # between stacked children
COMPONENT_WIDTH, COMPONENT_HEIGHT = 160, 60
EVENT_INSET, EVENT_STEP = 10, 30  # from the owner's bottom-right corner; between events

CONTAINER, COMPONENT, EVENT = "ifml.ViewContainer", "ifml.ViewComponent", "ifml.Event"
FLOW_TYPES = {IFML.NavigationFlow: "ifml.NavigationFlow", IFML.DataFlow: "ifml.DataFlow"}


# ── the export model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IfmlElement:
    """One IFMLEdit element; ``attributes`` and ``metadata`` are JSON-ready."""

    id: str
    type: str
    iri: str
    attributes: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IfmlRelation:
    """``hierarchy`` (parent, child), ``source`` (flow, element) or ``target`` (flow, element)."""

    type: str
    first: str
    second: str


@dataclass(frozen=True)
class IfmlEditDocument:
    model_hash: str
    elements: tuple[IfmlElement, ...]  # by id
    relations: tuple[IfmlRelation, ...]  # by (type, first, second)


_RELATION_KEYS = {"hierarchy": ("parent", "child"), "source": ("flow", "source"), "target": ("flow", "target")}


# ── extract ─────────────────────────────────────────────────────────────────


def _ids(elements: list[Element]) -> dict[URIRef, str]:
    """{IRI: local name}; two elements with one local name raise."""
    ids: dict[URIRef, str] = {}
    seen: dict[str, URIRef] = {}
    for element in sorted(elements, key=lambda e: str(e.iri)):
        name = local_name(element.iri)
        if name in seen:
            raise GeneratorError(
                element.iri, RDF.type, f"its local name {name!r} is also {seen[name]}'s; IFMLEdit ids must be unique"
            )
        seen[name] = element.iri
        ids[element.iri] = name
    return ids


def _parent(element: Element, parents: list[Element], ids: dict[URIRef, str]) -> str | None:
    """The id of the one container that ifml:contains ``element``, or None at the top level."""
    if len(parents) > 1:
        found = ", ".join(str(p.iri) for p in parents)
        raise GeneratorError(element.iri, IFML.contains, f"IFMLEdit nests in one container, found {found}")
    return ids[parents[0].iri] if parents else None


def extract_ifmledit(model: Model) -> IfmlEditDocument:
    """The IFMLEdit document of every IFML element in ``model`` (module docstring)."""
    with view_errors():
        interfaces = model.interfaces
        if not interfaces.models():
            raise GeneratorError(model.subject, RDF.type, "expected an ifml:InteractionModel, found none")
        pages, components = interfaces.pages(), interfaces.components()
        events, flows = interfaces.events(), interfaces.flows()
        ids = _ids([*pages, *components, *events, *flows])
        views = {p.iri for p in pages} | {c.iri for c in components}

        elements: dict[str, tuple[str, URIRef, dict[str, Any]]] = {}  # id -> (type, iri, attributes)
        relations: set[IfmlRelation] = set()
        children: dict[str | None, list[tuple[tuple[int, int, str], str]]] = {}  # parent -> [(sort key, id)]
        owned: dict[str, list[str]] = {}  # view element id -> event ids

        for page in pages:
            pid = ids[page.iri]
            elements[pid] = (
                CONTAINER,
                page.iri,
                {
                    "name": model.label(page.iri),
                    "default": page.is_default,
                    "landmark": page.is_landmark,
                    "xor": page.is_xor,
                },
            )
            children.setdefault(pid, [])  # a container, even with nothing in it
            parent = _parent(page, list(page.parents), ids)
            children.setdefault(parent, []).append(((1, 0, str(page.iri)), pid))

        for component in components:
            cid = ids[component.iri]
            types = component.types
            if len(types) != 1:
                found = ", ".join(str(t) for t in types) or "none"
                raise GeneratorError(
                    component.iri,
                    RDF.type,
                    f"expected exactly one of ifml:List, ifml:Details, ifml:Form, found {found}",
                )
            fields = sorted(local_name(p.iri) for p in component.parameter_bindings)
            elements[cid] = (
                COMPONENT,
                component.iri,
                {"name": model.label(component.iri), "stereotype": STEREOTYPES[types[0]], "fields": fields},
            )
            parent = _parent(component, list(component.screens), ids)
            order = component.order
            key = (0, order if order is not None else 1 << 30, str(component.iri))
            children.setdefault(parent, []).append((key, cid))

        for event in events:
            eid = ids[event.iri]
            owners = [o for o in event.owners if o.iri in views]
            if len(owners) != 1:
                found = ", ".join(str(o.iri) for o in event.owners) or "none"
                raise GeneratorError(
                    event.iri,
                    IFML.hasEvent,
                    f"expected exactly one ifml:ViewContainer or component owner, found {found}",
                )
            elements[eid] = (EVENT, event.iri, {"name": model.label(event.iri)})
            owner = ids[owners[0].iri]
            owned.setdefault(owner, []).append(eid)
            relations.add(IfmlRelation("hierarchy", owner, eid))

        for flow in flows:
            fid = ids[flow.iri]
            kind = flow.kind
            assert kind is not None  # interfaces.flows() holds only typed flows
            bindings = [
                {"output": local_name(b.source), "input": local_name(b.target)}
                for b in flow.binds  # sorted by (source, target)
            ]
            elements[fid] = (FLOW_TYPES[kind], flow.iri, {"bindings": bindings})
            for predicate, end in ((IFML.source, flow.source), (IFML.target, flow.target)):
                if end.iri not in ids:
                    raise GeneratorError(flow.iri, predicate, f"{end.iri} is not an IFML element IFMLEdit can show")
                relations.add(IfmlRelation(local_name(predicate), fid, ids[end.iri]))

    for parent, items in children.items():
        items.sort()
        if parent is not None:
            relations.update(IfmlRelation("hierarchy", parent, child) for _, child in items)

    graphics = _layout({p: [c for _, c in items] for p, items in children.items()}, owned)
    out = tuple(
        IfmlElement(
            id=eid,
            type=etype,
            iri=str(iri),
            attributes=attributes,
            metadata={"graphics": graphics[eid]} if eid in graphics else {},
        )
        for eid, (etype, iri, attributes) in sorted(elements.items())
    )
    return IfmlEditDocument(
        model_hash=model.hash,
        elements=out,
        relations=tuple(sorted(relations, key=lambda r: (r.type, r.first, r.second))),
    )


def _layout(children: dict[str | None, list[str]], owned: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """{id: graphics} for every view element and event; ``children[None]`` are the top level."""
    graphics: dict[str, dict[str, Any]] = {}

    def place(eid: str, x: int, y: int) -> tuple[int, int]:
        if eid in children:  # a container
            top, width = y + HEADER, COMPONENT_WIDTH
            for child in children[eid]:
                w, h = place(child, x + PAD, top)
                top, width = top + h + GAP, max(width, w)
            size = (width + 2 * PAD, (top - GAP if children[eid] else top) - y + PAD)
        else:
            size = (COMPONENT_WIDTH, COMPONENT_HEIGHT)
        graphics[eid] = {"position": {"x": x, "y": y}, "size": {"width": size[0], "height": size[1]}}
        for i, event in enumerate(sorted(owned.get(eid, ()))):
            graphics[event] = {
                "position": {"x": x + size[0] - EVENT_INSET - EVENT_STEP * i, "y": y + size[1] - EVENT_INSET},
                "name": {"horizontal": "right", "vertical": "bottom"},
            }
        return size

    x = MARGIN
    for root in children.get(None, ()):
        w, _ = place(root, x, MARGIN)
        x += w + MARGIN
    return graphics


# ── render ──────────────────────────────────────────────────────────────────


def render_ifmledit(doc: IfmlEditDocument) -> str:
    """The IFMLEdit JSON text, keys sorted, two-space indented, ending in a newline."""
    data = {
        "seams": {"generator": GENERATOR, "model_hash": doc.model_hash},
        "elements": [
            {"id": e.id, "type": e.type, "attributes": e.attributes, "metadata": e.metadata} for e in doc.elements
        ],
        "relations": [
            {"type": r.type, **dict(zip(_RELATION_KEYS[r.type], (r.first, r.second), strict=True))}
            for r in doc.relations
        ],
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate(model: Model) -> dict[str, str]:
    """{``ifmledit.json``: the IFMLEdit JSON of ``model``'s IFML layer}."""
    return {FILE: render_ifmledit(extract_ifmledit(model))}


def ifmledit_sources(model: Model) -> dict[str, tuple[str, ...]]:
    """{``ifmledit.json``: the full IRIs of the elements it exports, sorted}."""
    return {FILE: tuple(sorted(e.iri for e in extract_ifmledit(model).elements))}


def unmapped_summary() -> str:
    """The stderr line naming the ifml: terms the export leaves out."""
    terms = ", ".join(f"ifml:{local_name(term)}" for term, _ in UNMAPPED)
    return f"seams_gen ifmledit: not exported, no IFMLEdit counterpart: {terms}"


__all__ = [
    "FILE",
    "UNMAPPED",
    "IfmlEditDocument",
    "IfmlElement",
    "IfmlRelation",
    "extract_ifmledit",
    "generate",
    "ifmledit_sources",
    "render_ifmledit",
    "unmapped_summary",
]
