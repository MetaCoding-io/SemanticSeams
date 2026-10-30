"""Semantic Seams library: read and validate Semantic Seams models.

``load`` and ``Model`` read a model. Its views (``model.architecture``,
``model.operations``, ``model.channels``, ``model.shapes``,
``model.lifecycles``, ``model.policies``) answer with ``Many`` collections of
frozen ``Element`` dataclasses across every model of a layer; ``.only()``
asks for exactly one. The views supersede ``ModelGraph``'s one-of-each
resolvers (landmark_page, triggering_operation and the rest), which stay as
transitional methods. Their result types that share a name with a view class
(``Container``, ``Lifecycle``, ``Transition``) are imported from
``seams.graph``; the top-level names are the view classes.
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
from .views import (
    Architecture,
    Channel,
    Container,
    DeploymentNode,
    Element,
    Environment,
    Field,
    Lifecycle,
    Lifecycles,
    Many,
    Operation,
    PathTemplate,
    Policy,
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
    "Container",
    "DEC",
    "DEPLOY",
    "DecisionBinding",
    "DeploymentNode",
    "Element",
    "Environment",
    "Field",
    "HYDRA",
    "IFML",
    "InputBinding",
    "Lifecycle",
    "Lifecycles",
    "Many",
    "Model",
    "ModelGraph",
    "ODRL",
    "Operation",
    "OperationPath",
    "OutputBinding",
    "PROC",
    "PathMapping",
    "PathTemplate",
    "Permission",
    "Policy",
    "PolicyFacts",
    "ProcessFacts",
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
    "local_name",
    "model_hash",
    "payload_path",
]
