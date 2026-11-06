"""seams_runtime: a generic, graph-literate worker for seams models (ADR-0007, D013)."""

from .channels import ChannelBus
from .contracts import validate
from .engine import Engine
from .errors import (
    AggregateRolledBack,
    ContractViolation,
    LifecycleViolation,
    ModelHashMismatch,
    OperationError,
    PolicyDenied,
    ResolutionError,
    RuntimeModelError,
    StoreError,
    StoreReplyInvalid,
    StoreUnavailable,
    TaskNotOpen,
)
from .invariants import Finding, data_health
from .lifecycle import LifecycleGuard
from .llm import LLMClient, LLMError
from .model import ModelGraph, model_hash
from .policy import (
    Authenticator,
    HeaderAuthenticator,
    Identity,
    PolicyEvaluator,
    PolicyHook,
    PresenceEvaluator,
    RoleEvaluator,
    StaticUserAuthenticator,
    authenticator_from_env,
)
from .runtime import Runtime
from .sempkm import SemPKMStore
from .store import PostgresStore, SplitStore, SQLiteStore, Store
from .telemetry import Telemetry, tracer_from_env
from .worker import Instance, Worker

__version__ = "0.1.0"  # must equal [project].version in seams_runtime/pyproject.toml

__all__ = [
    "AggregateRolledBack",
    "Authenticator",
    "ChannelBus",
    "ContractViolation",
    "Engine",
    "Finding",
    "HeaderAuthenticator",
    "Identity",
    "Instance",
    "LLMClient",
    "LLMError",
    "LifecycleGuard",
    "LifecycleViolation",
    "ModelGraph",
    "ModelHashMismatch",
    "OperationError",
    "PolicyDenied",
    "PolicyEvaluator",
    "PolicyHook",
    "PostgresStore",
    "PresenceEvaluator",
    "ResolutionError",
    "RoleEvaluator",
    "Runtime",
    "RuntimeModelError",
    "SQLiteStore",
    "SemPKMStore",
    "SplitStore",
    "StaticUserAuthenticator",
    "Store",
    "StoreError",
    "StoreReplyInvalid",
    "StoreUnavailable",
    "TaskNotOpen",
    "Telemetry",
    "Worker",
    "__version__",
    "authenticator_from_env",
    "data_health",
    "model_hash",
    "tracer_from_env",
    "validate",
]
