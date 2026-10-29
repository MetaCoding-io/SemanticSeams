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
from .policy import (
    Authenticator,
    HeaderAuthenticator,
    Identity,
    PolicyEvaluator,
    PolicyHook,
    PresenceEvaluator,
    StaticUserAuthenticator,
    authenticator_from_env,
)

# Runtime (the facade generated code imports) is added in M004/S03 T05.

__all__ = [
    "Authenticator",
    "ContractViolation",
    "HeaderAuthenticator",
    "Identity",
    "LifecycleGuard",
    "LifecycleViolation",
    "ModelGraph",
    "ModelHashMismatch",
    "PolicyDenied",
    "PolicyEvaluator",
    "PolicyHook",
    "PresenceEvaluator",
    "ResolutionError",
    "RuntimeModelError",
    "StaticUserAuthenticator",
    "authenticator_from_env",
    "model_hash",
    "validate",
]
