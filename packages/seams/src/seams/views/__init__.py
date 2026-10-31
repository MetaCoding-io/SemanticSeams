"""Typed, read-only views over a seams model.

Each layer answers with ``Many`` collections of frozen ``Element``
dataclasses, across every model of that layer in the graph. ``seams.Model``
exposes them as properties (``model.architecture``, ``model.operations`` and
the rest); this package builds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib.namespace import SH

from ..namespaces import COMM, HYDRA, ODRL, PROC, STATE, VERIFY
from ._base import Element, HasIri, Many, Views
from .architecture import (
    Architecture,
    Artifact,
    Binding,
    Build,
    Container,
    Deployment,
    DeploymentNode,
    Environment,
    Healthcheck,
    Override,
    Port,
    System,
    Volume,
)
from .decisions import Decision, all_decisions
from .interfaces import Component, Event, Flow, InteractionModel, Interfaces, Page, Parameter, ParameterBinding
from .lifecycles import Lifecycle, Lifecycles, State, Transition
from .operations import Channel, Operation, PathTemplate, Status
from .policies import Policy
from .processes import ErrorBoundary, FlowNode, MessageStart, Process, ProcessElement, Processes
from .shapes import Field, Shape
from .verify import DecisionExample, ExpectedOutput, Given, Scenario, Step

if TYPE_CHECKING:
    from ..loader import Model

__all__ = [
    "Architecture",
    "Artifact",
    "Binding",
    "Build",
    "Channel",
    "Component",
    "Container",
    "Decision",
    "DecisionExample",
    "Deployment",
    "DeploymentNode",
    "Element",
    "Environment",
    "ErrorBoundary",
    "Event",
    "ExpectedOutput",
    "Field",
    "Flow",
    "Given",
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
    "Override",
    "Page",
    "Parameter",
    "ParameterBinding",
    "PathTemplate",
    "Port",
    "Policy",
    "Process",
    "ProcessElement",
    "Processes",
    "Scenario",
    "Shape",
    "State",
    "Status",
    "Step",
    "System",
    "Transition",
    "Views",
    "Volume",
    "architecture",
    "channels",
    "decision_examples",
    "decisions",
    "interfaces",
    "lifecycles",
    "operations",
    "policies",
    "processes",
    "scenarios",
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


def scenarios(model: Model) -> Many[Scenario]:
    views = model.views
    return views.view("scenarios", lambda: views.all(Scenario, VERIFY.Scenario))


def decision_examples(model: Model) -> Many[DecisionExample]:
    views = model.views
    return views.view("decision_examples", lambda: views.all(DecisionExample, VERIFY.DecisionExample))
