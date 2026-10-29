"""seams_runtime: a generic, graph-literate worker for seams models (ADR-0007, D013)."""

from .errors import (
    ContractViolation,
    LifecycleViolation,
    ModelHashMismatch,
    PolicyDenied,
    ResolutionError,
    RuntimeModelError,
)
from .channels import ChannelBus
from .contracts import validate
from .engine import Engine
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
from .store import Store

# Runtime (the facade generated code imports) is added in M004/S03 T05.

__all__ = [
    "Authenticator",
    "ChannelBus",
    "ContractViolation",
    "Engine",
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
    "Store",
    "authenticator_from_env",
    "model_hash",
    "validate",
]
