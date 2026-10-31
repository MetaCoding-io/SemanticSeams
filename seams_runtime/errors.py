"""Typed runtime errors.

Every error names the graph terms it is about (as IRI strings), carries the
HTTP status a generated route should answer with, and serialises to a
JSON-safe dict via ``to_dict()`` so handlers can put it straight into a
response body.
"""

from __future__ import annotations

from seams import ResolutionError, SeamsError

__all__ = [
    "ContractViolation",
    "LifecycleViolation",
    "ModelHashMismatch",
    "OperationError",
    "PolicyDenied",
    "ResolutionError",
    "RuntimeModelError",
    "TaskNotOpen",
]


# One base for every error: the seams library's SeamsError. The host's
# exception_handler(RuntimeModelError) and the worker's isinstance checks
# therefore also catch the ResolutionError that seams resolvers raise.
RuntimeModelError = SeamsError


class ModelHashMismatch(RuntimeModelError):
    """The model on disk is not the model the code was generated from."""

    http_status = 500

    def __init__(self, expected: str, actual: str, path):
        self.expected = str(expected)
        self.actual = str(actual)
        self.path = str(path)
        super().__init__(f"model hash mismatch for {self.path}: expected {self.expected}, got {self.actual}")

    def _fields(self) -> dict:
        return {"expected": self.expected, "actual": self.actual, "path": self.path}


class ContractViolation(RuntimeModelError):
    """A payload does not conform to the SHACL shape it crosses a seam with.

    ``results`` is a list of dicts (shape, focus, path, constraint, value,
    message), one per validation result.
    """

    http_status = 422

    def __init__(self, shape, results, focus=None, operation=None):
        self.shape = str(shape)
        self.results = [dict(r) for r in results]
        self.focus = None if focus is None else str(focus)
        self.operation = None if operation is None else str(operation)
        parts = []
        for r in self.results:
            where = r.get("path") or "(node)"
            what = r.get("constraint") or "violation"
            part = f"{where}: {what}"
            if r.get("message"):
                part += f" ({r['message']})"
            parts.append(part)
        via = f" via {self.operation}" if self.operation else ""
        super().__init__(f"payload violates {self.shape}{via}: {len(self.results)} result(s): " + "; ".join(parts))

    def _fields(self) -> dict:
        return {"shape": self.shape, "focus": self.focus, "operation": self.operation, "results": self.results}


class LifecycleViolation(RuntimeModelError):
    """A seam:fires transition is not enabled in the entity's current state."""

    http_status = 409

    def __init__(self, entity, transition, current_state, expected_from):
        self.entity = str(entity)
        self.transition = str(transition)
        self.current_state = None if current_state is None else str(current_state)
        self.expected_from = str(expected_from)
        super().__init__(
            f"transition {self.transition} not allowed for {self.entity}: "
            f"current state {self.current_state!r}, transition requires {self.expected_from!r}"
        )

    def _fields(self) -> dict:
        return {
            "entity": self.entity,
            "transition": self.transition,
            "current_state": self.current_state,
            "expected_from": self.expected_from,
        }


class PolicyDenied(RuntimeModelError):
    """The seam:governedBy policy refused the call (401 no identity, 403 denied)."""

    def __init__(self, policy, operation, status_code: int, reason: str):
        if status_code not in (401, 403):
            raise ValueError(f"PolicyDenied status must be 401 or 403, got {status_code}")
        self.policy = str(policy)
        self.operation = None if operation is None else str(operation)
        self.http_status = status_code
        self.reason = reason
        super().__init__(f"{self.policy} denied {self.operation}: {reason}")

    def _fields(self) -> dict:
        return {"policy": self.policy, "operation": self.operation, "reason": self.reason}


class TaskNotOpen(RuntimeModelError):
    """No open user task matches (already completed, never reached, or an
    unknown correlation key)."""

    http_status = 409

    def __init__(self, task, correlation_key):
        self.task = str(task)
        self.correlation_key = None if correlation_key is None else str(correlation_key)
        super().__init__(f"user task {self.task} is not open for correlation key {self.correlation_key!r}")

    def _fields(self) -> dict:
        return {"task": self.task, "correlation_key": self.correlation_key}


# RFC 9457 members the model states (rdfs:label and hydra:statusCode of the
# status), so a raiser cannot set them.
MODEL_MEMBERS = ("title", "status")


class OperationError(Exception):
    """An error an operation declares, raised by code serving it (ADR-0013).

    ``code`` is one of the operation's ``comm:errorCode``s; ``detail`` and
    ``extensions`` become problem+json members. The status, its title and
    the error shape come from the model, so ``title`` and ``status`` cannot
    be passed. Not a ``RuntimeModelError``: the model is not at fault, and a
    generated route's problem handler answers it with the declared status.
    """

    def __init__(self, code: str, detail: str | None = None, **extensions):
        reserved = sorted(set(extensions) & set(MODEL_MEMBERS))
        if reserved:
            raise ValueError(f"OperationError {code!r}: {reserved} come from the model's hydra:Status, not the raiser")
        self.code = str(code)
        self.detail = detail
        self.extensions = dict(extensions)
        super().__init__(f"{self.code}: {detail}" if detail is not None else self.code)
