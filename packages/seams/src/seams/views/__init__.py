"""Typed, read-only views over a seams model.

Each layer answers with ``Many`` collections of frozen ``Element``
dataclasses, across every model of that layer in the graph. ``seams.Model``
exposes them as properties (``model.architecture``, ``model.operations`` and
the rest); this package builds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib.namespace import SH

from ..namespaces import COMM, HYDRA, ODRL, STATE
from ._base import Element, HasIri, Many, Views
from .architecture import Architecture, Container, DeploymentNode, Environment, System
from .lifecycles import Lifecycle, Lifecycles, State, Transition
from .operations import Channel, Operation, PathTemplate
from .policies import Policy
from .shapes import Field, Shape

if TYPE_CHECKING:
    from ..loader import Model

__all__ = [
    "Architecture",
    "Channel",
    "Container",
    "DeploymentNode",
    "Element",
    "Environment",
    "Field",
    "HasIri",
    "Lifecycle",
    "Lifecycles",
    "Many",
    "Operation",
    "PathTemplate",
    "Policy",
    "Shape",
    "State",
    "System",
    "Transition",
    "Views",
    "architecture",
    "channels",
    "lifecycles",
    "operations",
    "policies",
    "shapes",
]


def architecture(model: Model) -> Architecture:
    views = model.views
    return views.view("architecture", lambda: Architecture(views))


def operations(model: Model) -> Many[Operation]:
    views = model.views
    return views.view("operations", lambda: views.all(Operation, HYDRA.Operation))


def channels(model: Model) -> Many[Channel]:
    views = model.views
    return views.view("channels", lambda: views.all(Channel, COMM.Channel))


def shapes(model: Model) -> Many[Shape]:
    views = model.views
    return views.view("shapes", lambda: views.all(Shape, SH.NodeShape))


def lifecycles(model: Model) -> Lifecycles:
    views = model.views

    def build() -> Lifecycles:
        found = views.all(Lifecycle, STATE.StateMachine)
        return Lifecycles(found, found.subject, found.predicate, model.curie)

    return views.view("lifecycles", build)


def policies(model: Model) -> Many[Policy]:
    views = model.views
    return views.view("policies", lambda: views.all(Policy, ODRL.Policy))
