"""The IFML diagram's edits as patches (backlog I6, M019/S07, ADR-0017).

``build_ifml_patch`` turns one gesture on the IFML diagram into one
``seams_edit.Patch``: create a view container, component or event; connect an event
to a target with a navigation or data flow; move a container or component to
another container; delete an element with what it owns; remove a field from the
shape a form writes. The terms come from the IFML vocabulary (``seams.IFML``), the
names and IRIs from the op and the model: nothing here knows a domain.

``ds`` is the model as the writer reads it (``seams_edit.text_quads`` of each model
file, in a ``default_union`` Dataset), so a blank node of a removed ``[ ]`` carries
the writer's label. The module reads and writes nothing; the viewer applies the
patch through ``seams_edit.apply``.

A new element gets an IRI in its parent's namespace (the parent's IRI up to its last
``#`` or ``/``), with the name made an XML name as its local part, so a native id
and its IRI agree (ADR-0002 rules 2 and 4). Its quads, and the quad that links it to
its parent, go in the parent's graph (``editing.element_graph``); a new component
takes the next ``ifml:order`` of its container. An op the model
cannot take (an unknown or out-of-model element, a kind the parent cannot hold, an
IRI already in use) raises ``PatchError``; a form whose shapes do not have the
field raises ``ResolutionError``. Neither writes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdflib import RDF, RDFS, BNode, Dataset, Literal, URIRef
from rdflib.namespace import SH
from rdflib.term import Node
from seams import IFML, SEAM, ResolutionError

from seams_edit import Patch, PatchError, Quad
from viewer.editing import element_graph, ontology_graph

CONTAINER = IFML.ViewContainer
COMPONENTS = (IFML.List, IFML.Details, IFML.Form)
FLOWS = (IFML.NavigationFlow, IFML.DataFlow)
# The kinds ``create`` makes, by the local name the op gives.
CREATE_KINDS = {str(t).removeprefix(str(IFML)): t for t in (CONTAINER, *COMPONENTS, IFML.Event)}
CONNECT_KINDS = {str(t).removeprefix(str(IFML)): t for t in FLOWS}
# What ``delete`` takes with an element: what it contains, its events, its parameters.
OWNS = (IFML.contains, IFML.hasEvent, IFML.hasParameter)
OPS = ("create", "connect", "move", "delete", "remove_field")


@dataclass(frozen=True)
class IfmlEdit:
    """One diagram op as a patch: the op, the element it made or changed, the patch."""

    op: str
    element: str
    patch: Patch


def _types(ds: Dataset, iri: URIRef) -> set[Node]:
    return set(ds.objects(iri, RDF.type))


def _text(op: dict, key: str) -> str:
    value = op.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PatchError(op.get("op", "op"), key, f"the op needs a non-empty {key!r}")
    return value.strip()


def _element(ds: Dataset, model: URIRef, op: dict, key: str) -> URIRef:
    """The op's ``key`` IRI: the model itself or an element ``seam:inModel`` it."""
    iri = URIRef(_text(op, key))
    if iri != model and (iri, SEAM.inModel, model) not in ds:
        raise PatchError(iri, SEAM.inModel, f"not an element of {model}")
    return iri


def _is_container(ds: Dataset, iri: URIRef) -> bool:
    return CONTAINER in _types(ds, iri)


def _is_component(ds: Dataset, iri: URIRef) -> bool:
    return any(t in COMPONENTS for t in _types(ds, iri))


def _graph(ds: Dataset, iri: URIRef) -> Node:
    graph = element_graph(ds, str(iri))
    if graph is None:
        raise PatchError(iri, RDF.type, "no graph states this element")
    return graph


def mint_iri(parent: URIRef, name: str) -> URIRef:
    """The IRI of a new element named ``name`` in ``parent``'s namespace."""
    local = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not local:
        raise PatchError(parent, RDFS.label, f"the name {name!r} gives no IRI: it needs a letter or digit")
    if local[0].isdigit():
        local = f"_{local}"
    namespace = re.sub(r"[^#/]*$", "", str(parent))
    return URIRef(namespace + local)


def _unused(ds: Dataset, iri: URIRef) -> URIRef:
    if (iri, None, None) in ds or (None, None, iri) in ds:
        raise PatchError(iri, RDF.type, "the model already has an element with this IRI")
    return iri


def _orders(ds: Dataset, container: URIRef, but: Node | None = None) -> set[int]:
    """The ``ifml:order`` values the container's components hold, ``but`` aside."""
    return {
        int(o.toPython())
        for c in ds.objects(container, IFML.contains)
        if c != but
        for o in ds.objects(c, IFML.order)
        if isinstance(o, Literal) and isinstance(o.toPython(), int)
    }


def _next_order(ds: Dataset, container: URIRef, but: Node | None = None) -> Literal:
    """The order after the container's last component: the seam shapes want one, unique
    in its container, on every component of a page (seams_gen htmx lays them out by it)."""
    return Literal(max(_orders(ds, container, but), default=-1) + 1)


def _create(ds: Dataset, model: URIRef, op: dict) -> IfmlEdit:
    kind = _text(op, "kind")
    if kind not in CREATE_KINDS:
        raise PatchError(op["op"], "kind", f"create makes one of {', '.join(sorted(CREATE_KINDS))}, not {kind!r}")
    cls, name = CREATE_KINDS[kind], _text(op, "name")
    parent = _element(ds, model, op, "parent")
    if cls == IFML.Event:
        link = IFML.hasEvent
        if not (_is_container(ds, parent) or _is_component(ds, parent)):
            raise PatchError(parent, link, "an event belongs to a view container or a view component")
    else:
        link = IFML.contains
        holds = _is_container(ds, parent) or (cls == CONTAINER and parent == model)
        if not holds:
            what = "the interaction model or a view container" if cls == CONTAINER else "a view container"
            raise PatchError(parent, link, f"a {kind} goes in {what}")
    new = _unused(ds, mint_iri(parent, name))
    graph = _graph(ds, parent)
    adds: list[Quad] = [
        (new, RDF.type, cls, graph),
        (new, RDFS.label, Literal(name), graph),
        (new, SEAM.inModel, model, graph),
        (parent, link, new, graph),
    ]
    if cls in COMPONENTS:
        adds.append((new, IFML.order, _next_order(ds, parent), graph))
    return IfmlEdit("create", str(new), Patch(adds=adds))


def _connect(ds: Dataset, model: URIRef, op: dict) -> IfmlEdit:
    kind = _text(op, "kind")
    if kind not in CONNECT_KINDS:
        raise PatchError(op["op"], "kind", f"connect makes one of {', '.join(sorted(CONNECT_KINDS))}, not {kind!r}")
    cls = CONNECT_KINDS[kind]
    source, target = _element(ds, model, op, "source"), _element(ds, model, op, "target")
    if cls == IFML.NavigationFlow and IFML.Event not in _types(ds, source):
        raise PatchError(source, IFML.source, "a navigation flow leaves an event")
    if cls == IFML.DataFlow and not (IFML.Event in _types(ds, source) or _is_component(ds, source)):
        raise PatchError(source, IFML.source, "a data flow leaves an event or a view component")
    if not (_is_container(ds, target) or _is_component(ds, target)):
        raise PatchError(target, IFML.target, "a flow goes to a view container or a view component")
    name = op.get("name")
    if isinstance(name, str) and name.strip():
        new = mint_iri(source, name.strip())
    else:
        local = re.sub(r".*[#/]", "", str(source)), re.sub(r".*[#/]", "", str(target))
        new = mint_iri(source, f"{local[0]} to {local[1]}")
    new = _unused(ds, new)
    graph = _graph(ds, source)
    adds: list[Quad] = [
        (new, RDF.type, cls, graph),
        (new, IFML.source, source, graph),
        (new, IFML.target, target, graph),
        (new, SEAM.inModel, model, graph),
    ]
    if isinstance(name, str) and name.strip():
        adds.append((new, RDFS.label, Literal(name.strip()), graph))
    if op.get("swap") is not None:
        if cls != IFML.NavigationFlow:
            raise PatchError(new, IFML.swap, "only a navigation flow has a swap strategy")
        swap = IFML[_text(op, "swap")]
        if (swap, RDF.type, IFML.SwapStrategy) not in ontology_graph():
            strategies = sorted(
                str(s).removeprefix(str(IFML)) for s in ontology_graph().subjects(RDF.type, IFML.SwapStrategy)
            )
            raise PatchError(new, IFML.swap, f"the swap is one of {', '.join(strategies)}, not {op['swap']!r}")
        adds.append((new, IFML.swap, swap, graph))
    return IfmlEdit("connect", str(new), Patch(adds=adds))


def _descendants(ds: Dataset, iri: URIRef) -> set[Node]:
    return set(ds.transitive_objects(iri, IFML.contains))


def _move(ds: Dataset, model: URIRef, op: dict) -> IfmlEdit:
    element, parent = _element(ds, model, op, "element"), _element(ds, model, op, "parent")
    if not (_is_container(ds, element) or _is_component(ds, element)):
        raise PatchError(element, IFML.contains, "only a view container or a view component moves")
    if not (_is_container(ds, parent) or (parent == model and _is_container(ds, element))):
        raise PatchError(parent, IFML.contains, "a component moves into a view container")
    if parent in _descendants(ds, element):
        raise PatchError(parent, IFML.contains, f"{parent} is {element} or inside it")
    removes: list[Quad] = [
        (s, IFML.contains, element, g)
        for s, _p, _o, g in ds.quads((None, IFML.contains, element, None))
        if s == model or (s, SEAM.inModel, model) in ds
    ]
    if any(s == parent for s, _p, _o, _g in removes):
        raise PatchError(parent, IFML.contains, f"{element} is already in {parent}")
    adds: list[Quad] = [(parent, IFML.contains, element, _graph(ds, parent))]
    # An order another component of the new container holds is renumbered after them.
    taken = _orders(ds, parent, element)
    for _s, _p, order, g in ds.quads((element, IFML.order, None, None)):
        if isinstance(order, Literal) and order.toPython() in taken and g is not None:
            removes.append((element, IFML.order, order, g))
            adds.append((element, IFML.order, _next_order(ds, parent, element), g))
    return IfmlEdit("move", str(element), Patch(adds=adds, removes=removes))


def _tree(ds: Dataset, quads: set[Quad]) -> set[Quad]:
    """``quads`` with every quad of the blank nodes they hold, so a ``[ ]`` or ``( )``
    goes whole; a quad about a blank node takes the statement that holds the node."""
    todo, done = list(quads), set[Quad]()
    while todo:
        quad = todo.pop()
        if quad in done:
            continue
        done.add(quad)
        s, _p, o, _g = quad
        if isinstance(s, BNode):
            todo.extend(q for q in ds.quads((None, None, s, None)) if q[3] is not None)
        if isinstance(o, BNode):
            todo.extend(q for q in ds.quads((o, None, None, None)) if q[3] is not None)
    return done


def _delete(ds: Dataset, model: URIRef, op: dict) -> IfmlEdit:
    element = _element(ds, model, op, "element")
    if element == model:
        raise PatchError(element, SEAM.inModel, "the interaction model itself is not deleted from its diagram")
    # What the element owns, transitively, then every flow that starts or ends there.
    gone: set[Node] = {element}
    todo: list[Node] = [element]
    while todo:
        x = todo.pop()
        for p in OWNS:
            for o in ds.objects(x, p):
                if isinstance(o, URIRef) and o not in gone:
                    gone.add(o)
                    todo.append(o)
    for end in (IFML.source, IFML.target):
        for x in list(gone):
            gone.update(f for f in ds.subjects(end, x) if any(t in FLOWS for t in _types(ds, f)))
    stated: set[Quad] = set()
    for x in gone:
        stated.update(q for q in ds.quads((x, None, None, None)) if q[3] is not None)
        stated.update(q for q in ds.quads((None, None, x, None)) if q[3] is not None)
    return IfmlEdit("delete", str(element), Patch(removes=_tree(ds, stated)))


def _remove_field(ds: Dataset, model: URIRef, op: dict) -> IfmlEdit:
    form = _element(ds, model, op, "element")
    if IFML.Form not in _types(ds, form):
        raise PatchError(form, RDF.type, "fields are removed from a form")
    path = URIRef(_text(op, "path"))
    shapes = sorted(ds.objects(form, SEAM.writes), key=str)
    found = sorted(
        {
            (shape, prop, g)
            for shape in shapes
            for _s, _p, prop, g in ds.quads((shape, SH.property, None, None))
            if g is not None and (prop, SH.path, path) in ds
        },
        key=str,
    )
    if not found:
        raise ResolutionError(form, SH.path, f"no shape the form seam:writes has a property with sh:path <{path}>")
    if len(found) > 1:
        raise ResolutionError(form, SH.path, f"{len(found)} property shapes of the form's shapes have <{path}>")
    shape, prop, graph = found[0]
    return IfmlEdit("remove_field", str(form), Patch(removes=_tree(ds, {(shape, SH.property, prop, graph)})))


BUILDERS = {"create": _create, "connect": _connect, "move": _move, "delete": _delete, "remove_field": _remove_field}


def build_ifml_patch(ds: Dataset, model_iri: str, op: dict) -> IfmlEdit:
    """The patch for one diagram ``op`` on the IFML model ``model_iri``.

    ``op["op"]`` is one of ``OPS``:

    - ``create``: ``kind`` (ViewContainer, List, Details, Form, Event), ``name``,
      ``parent`` (the model or a container for a container; a container for a
      component; a container or component for an event, by ``ifml:hasEvent``);
    - ``connect``: ``kind`` (NavigationFlow, DataFlow), ``source``, ``target``, an
      optional ``name`` (the IRI is ``source_to_target`` without one) and, for a
      navigation flow, an optional ``swap`` (an ``ifml:SwapStrategy`` local name);
    - ``move``: ``element`` and its new ``parent``: the ``ifml:contains`` quad
      changes, and a component's ``ifml:order`` when the new container already
      has it;
    - ``delete``: ``element``, with what it contains, its events and parameters,
      every flow from or to any of them, and every quad naming them;
    - ``remove_field``: ``element`` (a form) and ``path``: the property shape with
      that ``sh:path`` leaves the shape the form ``seam:writes``.
    """
    model = URIRef(model_iri)
    if IFML.InteractionModel not in _types(ds, model):
        raise PatchError(model, RDF.type, "not an IFML interaction model")
    name = op.get("op")
    if name not in BUILDERS:
        raise PatchError(model, "op", f"the op is one of {', '.join(OPS)}, not {name!r}")
    return BUILDERS[name](ds, model, op)
