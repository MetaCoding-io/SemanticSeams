"""seams_runtime: a generic, graph-literate worker for seams models (ADR-0007, D013)."""

from .errors import (
    ContractViolation,
    LifecycleViolation,
    ModelHashMismatch,
    PolicyDenied,
    ResolutionError,
    RuntimeModelError,
)
from .contracts import validate
from .lifecycle import LifecycleGuard
from .model import ModelGraph, model_hash

# Runtime (the facade generated code imports) is added in M004/S03 T05.

__all__ = [
    "ContractViolation",
    "LifecycleGuard",
    "LifecycleViolation",
    "ModelGraph",
    "ModelHashMismatch",
    "PolicyDenied",
    "ResolutionError",
    "RuntimeModelError",
    "model_hash",
    "validate",
]
