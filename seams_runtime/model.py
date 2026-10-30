"""The TriG model as the runtime's service registry (ADR-0007 rule 2).

``ModelGraph``, ``model_hash``, the namespaces, the resolver results and the
payload XML helpers live in the ``seams`` library (D034) and are re-exported
here, so ``from seams_runtime.model import ...`` keeps working. ``ModelGraph``
answers the questions the worker asks while it runs a process; a missing hop
raises ``ResolutionError`` naming the subject IRI and the predicate.
"""

from __future__ import annotations

from seams import (
    COMM,
    DEC,
    DEPLOY,
    HYDRA,
    IFML,
    ODRL,
    PROC,
    SEAM,
    STATE,
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
    local_name,
    model_hash,
    payload_path,
)

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
    "ModelGraph",
    "ODRL",
    "OperationPath",
    "OutputBinding",
    "PROC",
    "PathMapping",
    "Permission",
    "PolicyFacts",
    "ProcessFacts",
    "SEAM",
    "STATE",
    "Transition",
    "bpmn_start_event_ids",
    "dmn_decision_ids",
    "dmn_input_types",
    "local_name",
    "model_hash",
    "payload_path",
]
