"""Semantic Seams library: read and validate Semantic Seams models.

``load`` and ``Model`` read a model; ``ModelGraph`` adds the one-of-each
resolvers the runtime and the generators share (landmark_page,
triggering_operation, is_channel_started and the rest). Those resolvers are
transitional: the S03 views supersede them.
"""

from .errors import ResolutionError, SeamsError
from .graph import (
    ChannelBinding,
    ChannelStart,
    Container,
    DecisionBinding,
    InputBinding,
    Lifecycle,
    ModelGraph,
    OperationPath,
    OutputBinding,
    PathMapping,
    Permission,
    PolicyFacts,
    ProcessFacts,
    Transition,
    bpmn_start_event_ids,
    dmn_decision_ids,
    dmn_input_types,
)
from .loader import Model, load, model_hash, payload_path
from .namespaces import COMM, DEC, DEPLOY, HYDRA, IFML, ODRL, PROC, SEAM, STATE, local_name

__all__ = [
    "COMM",
    "ChannelBinding",
    "ChannelStart",
    "Container",
    "DEC",
    "DEPLOY",
    "DecisionBinding",
    "HYDRA",
    "IFML",
    "InputBinding",
    "Lifecycle",
    "Model",
    "ModelGraph",
    "ODRL",
    "OperationPath",
    "OutputBinding",
    "PROC",
    "PathMapping",
    "Permission",
    "PolicyFacts",
    "ProcessFacts",
    "ResolutionError",
    "SEAM",
    "STATE",
    "SeamsError",
    "Transition",
    "bpmn_start_event_ids",
    "dmn_decision_ids",
    "dmn_input_types",
    "load",
    "local_name",
    "model_hash",
    "payload_path",
]
