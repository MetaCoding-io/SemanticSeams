"""The seam:governedBy policy hook (ADR-0007, D014, gaps.md GAP-20).

Authorization in v1 is two pluggable steps. An ``Authenticator`` turns a
request into an ``Identity`` (or ``None``), and a ``PolicyEvaluator`` decides
whether that identity may call the operation an ODRL policy governs.

The default authenticator trusts an identity header (``X-Forwarded-User``)
set by a fronting auth proxy, so generated code never handles credentials.
``SEAMS_DEV_USER`` switches to a static user for local runs; it is opt-in,
so without it a request with no header is refused (fail closed).

``PolicyHook.check`` is the framework-free core. ``PolicyHook.dependency``
wraps it for FastAPI; fastapi is imported only there, so the rest of the
runtime does not depend on it.

This module deliberately avoids ``from __future__ import annotations``:
FastAPI reads the dependency's ``request: Request`` annotation at runtime,
and ``Request`` is only bound inside ``dependency``.
"""

import os
from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from rdflib import URIRef

from .errors import PolicyDenied, ResolutionError
from .model import ODRL, ModelGraph, PolicyFacts, local_name

DEV_USER_ENV = "SEAMS_DEV_USER"
DEFAULT_IDENTITY_HEADER = "X-Forwarded-User"


@dataclass(frozen=True)
class Identity:
    id: str


# ── authentication ──────────────────────────────────────────────────────────


@runtime_checkable
class Authenticator(Protocol):
    def __call__(self, request) -> Identity | None: ...


class HeaderAuthenticator:
    """Trust an identity header set by a fronting auth proxy (the default)."""

    def __init__(self, header: str = DEFAULT_IDENTITY_HEADER):
        self.header = header

    def __call__(self, request) -> Identity | None:
        value = request.headers.get(self.header)
        if value is None or not value.strip():
            return None
        return Identity(value.strip())

    def __repr__(self) -> str:
        return f"HeaderAuthenticator(header={self.header!r})"


class StaticUserAuthenticator:
    """Every request is ``user``. For local tutorial runs only (SEAMS_DEV_USER)."""

    def __init__(self, user: str):
        if not user:
            raise ValueError("StaticUserAuthenticator needs a non-empty user")
        self.identity = Identity(user)

    def __call__(self, request) -> Identity | None:
        return self.identity

    def __repr__(self) -> str:
        return f"StaticUserAuthenticator(user={self.identity.id!r})"


def authenticator_from_env(environ: Mapping[str, str] | None = None) -> Authenticator:
    """StaticUserAuthenticator when SEAMS_DEV_USER is set (non-empty), else the
    fail-closed HeaderAuthenticator."""
    env = os.environ if environ is None else environ
    user = env.get(DEV_USER_ENV, "").strip()
    return StaticUserAuthenticator(user) if user else HeaderAuthenticator()


# ── evaluation ──────────────────────────────────────────────────────────────


@runtime_checkable
class PolicyEvaluator(Protocol):
    def __call__(self, policy: PolicyFacts, operation_iri: URIRef,
                 identity: Identity) -> tuple[bool, str]: ...


class PresenceEvaluator:
    """v1 evaluator: allow when an odrl:permission targets the operation with an
    odrl:action and its assignee matches the identity.

    An odrl:PartyCollection assignee is satisfied by any (authenticated)
    identity; a specific party IRI only by an identity whose id equals that
    IRI or its local name; a permission with no assignee by any identity.

    No odrl:constraint, odrl:duty or odrl:prohibition is evaluated. Full ODRL
    evaluation comes after v1; plug it in as another PolicyEvaluator.
    """

    def __call__(self, policy: PolicyFacts, operation_iri, identity: Identity) -> tuple[bool, str]:
        op = URIRef(str(operation_iri))
        targeting = [p for p in policy.permissions if p.target == op and p.action is not None]
        if not targeting:
            return False, f"no permission in {policy.iri} targets {op} with an odrl:action"
        for perm in targeting:
            if perm.assignee is None or ODRL.PartyCollection in perm.assignee_types:
                return True, f"{perm.action} on {op} permitted to any authenticated identity"
            if identity.id in (str(perm.assignee), local_name(perm.assignee)):
                return True, f"{perm.action} on {op} permitted to {perm.assignee}"
        assignees = ", ".join(sorted(str(p.assignee) for p in targeting))
        return False, f"identity {identity.id!r} is not an assignee ({assignees}) of {policy.iri}"


# ── the hook ────────────────────────────────────────────────────────────────


class PolicyHook:
    def __init__(self, model: ModelGraph, authenticator: Authenticator | None = None,
                 evaluator: PolicyEvaluator | None = None):
        self.model = model
        self.authenticator = authenticator if authenticator is not None else HeaderAuthenticator()
        self.evaluator = evaluator if evaluator is not None else PresenceEvaluator()

    def governed_operations(self, policy: PolicyFacts) -> list[URIRef]:
        """Permission targets of ``policy`` that are seam:governedBy it."""
        ops = []
        for target in sorted({p.target for p in policy.permissions if p.target is not None}, key=str):
            try:
                governing = self.model.policies_for(target)
            except ResolutionError:
                continue
            if any(g.iri == policy.iri for g in governing):
                ops.append(target)
        return ops

    def check(self, policy_curie, operation_iri=None, request=None) -> Identity:
        """Authenticate ``request`` and evaluate the policy; raise PolicyDenied
        (401 no identity, 403 denied) or return the identity.

        ``operation_iri`` defaults to every permission target the policy governs;
        when given, the policy must govern it.
        """
        policy = self.model.policy(policy_curie)
        if operation_iri is None:
            operations = self.governed_operations(policy)
        else:
            op = self.model.curie(operation_iri)
            if all(g.iri != policy.iri for g in self.model.policies_for(op)):
                raise PolicyDenied(policy.iri, op, 403, f"{policy.iri} does not govern {op}")
            operations = [op]
        op_for_error = operations[0] if len(operations) == 1 else (operation_iri or None)

        identity = self.authenticator(request)
        if identity is None:
            raise PolicyDenied(policy.iri, op_for_error, 401,
                               f"no authenticated identity ({self.authenticator!r})")
        if not operations:
            raise PolicyDenied(policy.iri, None, 403,
                               "no permission of this policy targets an operation it governs")
        for op in operations:
            allowed, reason = self.evaluator(policy, op, identity)
            if not allowed:
                raise PolicyDenied(policy.iri, op, 403, reason)
        return identity

    def dependency(self, policy_curie, operation_iri=None):
        """A FastAPI dependency: ``Depends(hook.dependency(":user_send_policy"))``
        yields the Identity or answers 401/403 with PolicyDenied.to_dict()."""
        from fastapi import HTTPException, Request

        def _policy_dependency(request: Request) -> Identity:
            try:
                return self.check(policy_curie, operation_iri, request)
            except PolicyDenied as denied:
                raise HTTPException(status_code=denied.http_status, detail=denied.to_dict()) from denied

        _policy_dependency.__name__ = f"policy_{local_name(self.model.curie(policy_curie))}"
        return _policy_dependency
