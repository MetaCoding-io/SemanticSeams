"""Typed, read-only views over a seams model.

Each layer answers with ``Many`` collections of frozen ``Element``
dataclasses, across every model of that layer in the graph. ``seams.Model``
exposes them as properties (``model.architecture``, ``model.operations`` and
the rest); this package builds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib.namespace import SH

from ..namespaces import COMM, HYDRA, ODRL, PROC, STATE
from ._base import Element, HasIri, Many, Views
from .architecture import (
    Architecture,
    Artifact,
    Binding,
    Container,
    DeploymentNode,
    Environment,
    Healthcheck,
    Port,
    System,
    Volume,
)
from .decisions import Decision, all_decisions
from .interfaces import Component, Event, Flow, InteractionModel, Interfaces, Page, Parameter, ParameterBinding
from .lifecycles import Lifecycle, Lifecycles, State, Transition
from .operations import Channel, Operation, PathTemplate
from .policies import Policy
from .processes import FlowNode, MessageStart, Process, ProcessElement, Processes
from .shapes import Field, Shape

if TYPE_CHECKING:
    from ..loader import Model

__all__ = [
    "Architecture",
    "Artifact",
    "Binding",
    "Channel",
    "Component",
    "Container",
    "Decision",
    "DeploymentNode",
    "Element",
    "Environment",
    "Event",
    "Field",
    "Flow",
    "FlowNode",
    "HasIri",
    "Healthcheck",
    "InteractionModel",
    "Interfaces",
    "Lifecycle",
    "Lifecycles",
    "Many",
    "MessageStart",
    "Operation",
    "Page",
    "Parameter",
    "ParameterBinding",
    "PathTemplate",
    "Port",
    "Policy",
    "Process",
    "ProcessElement",
    "Processes",
    "Shape",
    "State",
    "System",
    "Transition",
    "Views",
    "Volume",
    "architecture",
    "channels",
    "decisions",
    "interfaces",
    "lifecycles",
    "operations",
    "policies",
    "processes",
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


def interfaces(model: Model) -> Interfaces:
    views = model.views
    return views.view("interfaces", lambda: Interfaces(views))


def processes(model: Model) -> Processes:
    views = model.views

    def build() -> Processes:
        found = views.all(Process, PROC.Process)
        return Processes(found, found.subject, found.predicate, model.curie)

    return views.view("processes", build)


def decisions(model: Model) -> Many[Decision]:
    views = model.views
    return views.view("decisions", lambda: all_decisions(views))
