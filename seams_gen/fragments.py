"""The fragment-name rule (GAP-19, D017), shared by the htmx and FastAPI generators.

A ``seam:UIFragment`` operation names the partial it renders through its one
``seam:rendersComponent`` target C. When some ``ifml:Event`` that
``seam:submitsTo`` the operation has an ``ifml:NavigationFlow`` to C whose
``ifml:swap`` is ``ifml:Append`` or ``ifml:Prepend``, the response is one new
item of C and the partial is ``<C local name>_item.html``; otherwise it is the
whole component, ``<C local name>.html``. The htmx generator emits exactly the
partials this rule names and the route generator calls them by the same rule,
so a route can never name a partial that was not generated. The rule reads
the model through ``model.operations`` and ``model.interfaces`` (D036).
"""

from __future__ import annotations

from rdflib import RDF, URIRef
from seams import IFML, Flow, Model, Operation, ResolutionError, local_name

from . import GeneratorError
from ._views import only, view_errors

ITEM_SWAPS = (IFML.Append, IFML.Prepend)

COMPONENT = "component"
ITEM = "item"


def fragment_for(model, operation) -> tuple[str, object, str]:
    """(file name, component IRI, kind) of the partial ``operation`` (an IRI or
    an ``Operation`` view) renders.

    kind is ``"component"`` (the component's block body) or ``"item"`` (one
    ``<li>`` of an ``ifml:Details`` item list). No or several
    ``seam:rendersComponent`` targets raise ``GeneratorError(operation,
    seam:rendersComponent)``; an item partial of anything but an
    ``ifml:Details`` raises on the component's ``rdf:type``.
    """
    if not isinstance(model, Model):
        raise TypeError(f"fragment_for needs a seams.Model, got {type(model).__name__}")
    with view_errors():
        op = operation if isinstance(operation, Operation) else model.views.intern(Operation, URIRef(str(operation)))
        component = only(op.renders)
        item = any(
            flow.kind == IFML.NavigationFlow and component.iri in flow.targets.iris() and _swap(flow) in ITEM_SWAPS
            for event in op.submitted_by
            for flow in event.flows
        )
        if item and IFML.Details not in component.types:
            raise GeneratorError(
                component.iri, RDF.type, f"{op.iri} appends an item to it, which needs an ifml:Details item list"
            )
    if item:
        return f"{local_name(component.iri)}_item.html", component.iri, ITEM
    return f"{local_name(component.iri)}.html", component.iri, COMPONENT


def _swap(flow: Flow):
    """The flow's ifml:swap, or None when it has none (or several): such a
    flow appends nothing; ``extract_page`` reports it when it renders the flow."""
    try:
        return flow.swap
    except ResolutionError:
        return None
