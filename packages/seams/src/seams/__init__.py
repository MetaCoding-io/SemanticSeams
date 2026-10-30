"""Semantic Seams library: read and validate Semantic Seams models.

``load`` and ``Model`` read a model. Its views (``model.architecture``,
``model.interfaces``, ``model.processes``, ``model.decisions``,
``model.operations``, ``model.channels``, ``model.shapes``,
``model.lifecycles``, ``model.policies``) answer with ``Many`` collections of
frozen ``Element`` dataclasses across every model of a layer; ``.only()``
asks for exactly one. The views supersede ``ModelGraph``'s one-of-each
resolvers (landmark_page, triggering_operation and the rest), which stay as
transitional methods. Their result types that share a name with a view class
(``Container``, ``Lifecycle``, ``Transition``) are imported from
``seams.graph``; the top-level names are the view classes.

``model.sparql(query, **bindings)`` runs read-only SPARQL with the project
prefixes bound, and ``model.question(name, **bindings)`` runs a bundled
canned question (``question_names()``).
"""

from .errors import ResolutionError, SeamsError
from .graph import (
    ChannelBinding,
    ChannelStart,
    DecisionBinding,
    InputBinding,
    ModelGraph,
    OperationPath,
    OutputBinding,
    PathMapping,
    Permission,
    PolicyFacts,
    ProcessFacts,
    bpmn_start_event_ids,
    dmn_decision_ids,
    dmn_input_types,
)
from .loader import Model, load, model_hash, payload_path
from .namespaces import ARCH, COMM, DEC, DEPLOY, HYDRA, IFML, ODRL, PROC, SEAM, STATE, local_name
from .sparql import PREFIXES, load_question, question_names
from .views import (
    Architecture,
    Channel,
    Component,
    Container,
    Decision,
    DeploymentNode,
    Element,
    Environment,
    Event,
    Field,
    InteractionModel,
    Interfaces,
    Lifecycle,
    Lifecycles,
    Many,
    MessageStart,
    Operation,
    Page,
    PathTemplate,
    Policy,
    Process,
    ProcessElement,
    Processes,
    Shape,
    State,
    System,
    Transition,
)

__all__ = [
    "ARCH",
    "Architecture",
    "COMM",
    "Channel",
    "ChannelBinding",
    "ChannelStart",
    "Component",
    "Container",
    "DEC",
    "DEPLOY",
    "Decision",
    "DecisionBinding",
    "DeploymentNode",
    "Element",
    "Environment",
    "Event",
    "Field",
    "HYDRA",
    "IFML",
    "InputBinding",
    "InteractionModel",
    "Interfaces",
    "Lifecycle",
    "Lifecycles",
    "Many",
    "MessageStart",
    "Model",
    "ModelGraph",
    "ODRL",
    "Operation",
    "OperationPath",
    "OutputBinding",
    "PREFIXES",
    "PROC",
    "Page",
    "PathMapping",
    "PathTemplate",
    "Permission",
    "Policy",
    "PolicyFacts",
    "Process",
    "ProcessElement",
    "ProcessFacts",
    "Processes",
    "ResolutionError",
    "SEAM",
    "STATE",
    "SeamsError",
    "Shape",
    "State",
    "System",
    "Transition",
    "bpmn_start_event_ids",
    "dmn_decision_ids",
    "dmn_input_types",
    "load",
    "load_question",
    "local_name",
    "model_hash",
    "payload_path",
    "question_names",
]
