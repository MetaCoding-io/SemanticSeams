"""The fragment-name rule (GAP-19, D017), shared by the htmx and FastAPI generators.

A ``seam:UIFragment`` operation names the partial it renders through its one
``seam:rendersComponent`` target C. When some ``ifml:Event`` that
``seam:submitsTo`` the operation has an ``ifml:NavigationFlow`` to C whose
``ifml:swap`` is ``ifml:Append`` or ``ifml:Prepend``, the response is one new
item of C and the partial is ``<C local name>_item.html``; otherwise it is the
whole component, ``<C local name>.html``. The htmx generator emits exactly the
partials this rule names and the route generator calls them by the same rule,
so a route can never name a partial that was not generated.
"""

from __future__ import annotations

from rdflib import RDF
from seams import IFML, SEAM, ModelGraph, local_name

from . import GeneratorError
from .facts import Facts

ITEM_SWAPS = (IFML.Append, IFML.Prepend)

COMPONENT = "component"
ITEM = "item"


def fragment_for(facts_or_model, operation) -> tuple[str, object, str]:
    """(file name, component IRI, kind) of the partial ``operation`` renders.

    kind is ``"component"`` (the component's block body) or ``"item"`` (one
    ``<li>`` of an ``ifml:Details`` item list). No or several
    ``seam:rendersComponent`` targets raise ``GeneratorError(operation,
    seam:rendersComponent)``; an item partial of anything but an
    ``ifml:Details`` raises on the component's ``rdf:type``.
    """
    f = facts_or_model if isinstance(facts_or_model, Facts) else Facts(_model(facts_or_model))
    component = f.one(operation, SEAM.rendersComponent)
    item = any(
        (flow, RDF.type, IFML.NavigationFlow) in f.ds
        and (flow, IFML.target, component) in f.ds
        and any((flow, IFML.swap, swap) in f.ds for swap in ITEM_SWAPS)
        for event in f.subjects(SEAM.submitsTo, operation)
        if (event, RDF.type, IFML.Event) in f.ds
        for flow in f.subjects(IFML.source, event)
    )
    if item and (component, RDF.type, IFML.Details) not in f.ds:
        raise GeneratorError(
            component, RDF.type, f"{operation} appends an item to it, which needs an ifml:Details item list"
        )
    if item:
        return f"{local_name(component)}_item.html", component, ITEM
    return f"{local_name(component)}.html", component, COMPONENT


def _model(model) -> ModelGraph:
    if not isinstance(model, ModelGraph):
        raise TypeError(f"fragment_for needs a ModelGraph or Facts, got {type(model).__name__}")
    return model
