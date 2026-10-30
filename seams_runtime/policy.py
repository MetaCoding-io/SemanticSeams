"""The seam:governedBy policy hook (ADR-0007, D014, gaps.md GAP-20).

Authorization in v1 is two pluggable steps. An ``Authenticator`` turns a
request into an ``Identity`` (or ``None``), and a ``PolicyEvaluator`` decides
whether that identity may call the operation an ODRL policy governs.

The default authenticator trusts an identity header (``X-Forwarded-User``)
set by a fronting auth proxy, so generated code never handles credentials.
The proxy's ``X-Forwarded-Groups`` header (comma-separated) gives the
identity's roles. ``SEAMS_DEV_USER`` switches to a static user for local runs,
with ``SEAMS_DEV_ROLES`` as its roles; it is opt-in, so without it a request
with no header is refused (fail closed).

The default evaluator is ``RoleEvaluator`` (backlog E5, D028): a specific
odrl:assignee party admits an identity whose id or one of whose roles names
it. ``PresenceEvaluator`` is the id-only v1 evaluator it supersedes.

``PolicyHook.check`` is the framework-free core. ``PolicyHook.dependency``
wraps it for FastAPI; fastapi is imported only there, so the rest of the
runtime does not depend on it.

A BPMN user task is governed directly (ADR-0009): ``check_element`` and
``allows`` evaluate every seam:governedBy policy of the task with the task
IRI as the odrl:target. An ungoverned task is open to any authenticated
identity; no identity is always 401. ``task_dependency`` is the FastAPI
wrapper.

This module deliberately avoids ``from __future__ import annotations``:
FastAPI reads the dependency's ``request: Request`` annotation at runtime,
and ``Request`` is only bound inside ``dependency``.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rdflib import URIRef

from .errors import PolicyDenied, ResolutionError
from .model import ODRL, SEAM, ModelGraph, PolicyFacts, local_name

DEV_USER_ENV = "SEAMS_DEV_USER"
DEV_ROLES_ENV = "SEAMS_DEV_ROLES"
DEFAULT_IDENTITY_HEADER = "X-Forwarded-User"
DEFAULT_ROLES_HEADER = "X-Forwarded-Groups"


@dataclass(frozen=True)
class Identity:
    id: str
    roles: frozenset[str] = frozenset()


def _split_roles(value: str | None) -> frozenset[str]:
    """The comma-separated, stripped, non-empty items of ``value``."""
    if not value:
        return frozenset()
    return frozenset(item.strip() for item in value.split(",") if item.strip())


# ── authentication ──────────────────────────────────────────────────────────


@runtime_checkable
class Authenticator(Protocol):
    def __call__(self, request) -> Identity | None: ...


class HeaderAuthenticator:
    """Trust an identity header set by a fronting auth proxy (the default).

    The roles are the comma-separated items of ``roles_header``; an absent
    header means no roles."""

    def __init__(self, header: str = DEFAULT_IDENTITY_HEADER, roles_header: str = DEFAULT_ROLES_HEADER):
        self.header = header
        self.roles_header = roles_header

    def __call__(self, request) -> Identity | None:
        value = request.headers.get(self.header)
        if value is None or not value.strip():
            return None
        return Identity(value.strip(), _split_roles(request.headers.get(self.roles_header)))

    def __repr__(self) -> str:
        return f"HeaderAuthenticator(header={self.header!r}, roles_header={self.roles_header!r})"


class StaticUserAuthenticator:
    """Every request is ``user`` with ``roles``. For local tutorial runs only
    (SEAMS_DEV_USER, SEAMS_DEV_ROLES)."""

    def __init__(self, user: str, roles=()):
        if not user:
            raise ValueError("StaticUserAuthenticator needs a non-empty user")
        self.identity = Identity(user, frozenset(roles))

    def __call__(self, request) -> Identity | None:
        return self.identity

    def __repr__(self) -> str:
        return f"StaticUserAuthenticator(user={self.identity.id!r}, roles={sorted(self.identity.roles)!r})"


def authenticator_from_env(environ: Mapping[str, str] | None = None) -> Authenticator:
    """StaticUserAuthenticator when SEAMS_DEV_USER is set (non-empty), with the
    comma-separated SEAMS_DEV_ROLES as its roles, else the fail-closed
    HeaderAuthenticator."""
    env = os.environ if environ is None else environ
    user = env.get(DEV_USER_ENV, "").strip()
    if not user:
        return HeaderAuthenticator()
    return StaticUserAuthenticator(user, _split_roles(env.get(DEV_ROLES_ENV)))


# ── evaluation ──────────────────────────────────────────────────────────────


@runtime_checkable
class PolicyEvaluator(Protocol):
    def __call__(self, policy: PolicyFacts, operation_iri: URIRef, identity: Identity) -> tuple[bool, str]: ...


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


class RoleEvaluator:
    """The default evaluator: allow when an odrl:permission targets the
    operation with an odrl:action and its assignee matches the identity or
    one of its roles (backlog E5, D028).

    An odrl:PartyCollection assignee, or no assignee, is satisfied by any
    (authenticated) identity. A specific party IRI is satisfied when the
    identity's id or any of its roles equals that IRI or its local name, so
    every identity PresenceEvaluator admits is admitted here too.

    No odrl:constraint, odrl:duty or odrl:prohibition is evaluated. Full ODRL
    evaluation comes later; plug it in as another PolicyEvaluator.
    """

    def __call__(self, policy: PolicyFacts, operation_iri, identity: Identity) -> tuple[bool, str]:
        op = URIRef(str(operation_iri))
        targeting = [p for p in policy.permissions if p.target == op and p.action is not None]
        if not targeting:
            return False, f"no permission in {policy.iri} targets {op} with an odrl:action"
        names = {identity.id, *identity.roles}
        for perm in targeting:
            if perm.assignee is None or ODRL.PartyCollection in perm.assignee_types:
                return True, f"{perm.action} on {op} permitted to any authenticated identity"
            if names & {str(perm.assignee), local_name(perm.assignee)}:
                return True, f"{perm.action} on {op} permitted to {perm.assignee}"
        assignees = ", ".join(sorted(str(p.assignee) for p in targeting))
        roles = ", ".join(sorted(identity.roles)) or "none"
        return False, (f"identity {identity.id!r} (roles: {roles}) is not an assignee ({assignees}) of {policy.iri}")


# ── the hook ────────────────────────────────────────────────────────────────


class PolicyHook:
    def __init__(
        self, model: ModelGraph, authenticator: Authenticator | None = None, evaluator: PolicyEvaluator | None = None
    ):
        self.model = model
        self.authenticator = authenticator if authenticator is not None else HeaderAuthenticator()
        self.evaluator = evaluator if evaluator is not None else RoleEvaluator()

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
            raise PolicyDenied(policy.iri, op_for_error, 401, f"no authenticated identity ({self.authenticator!r})")
        if not operations:
            raise PolicyDenied(policy.iri, None, 403, "no permission of this policy targets an operation it governs")
        for op in operations:
            allowed, reason = self.evaluator(policy, op, identity)
            if not allowed:
                raise PolicyDenied(policy.iri, op, 403, reason)
        return identity

    # ── governed elements (user tasks, ADR-0009) ──

    def authenticate(self, request) -> Identity | None:
        return self.authenticator(request)

    def check_element(self, element, identity: Identity | None) -> Identity:
        """Raise PolicyDenied unless ``identity`` passes every seam:governedBy
        policy of ``element`` (evaluated with the element as the target).
        None is 401; an ungoverned element admits any identity."""
        iri = self.model.curie(element)
        policies = [self.model.policy(p) for p in sorted(set(self.model.ds.objects(iri, SEAM.governedBy)))]
        if identity is None:
            policy = policies[0].iri if policies else iri
            raise PolicyDenied(policy, iri, 401, f"no authenticated identity ({self.authenticator!r})")
        for policy in policies:
            allowed, reason = self.evaluator(policy, iri, identity)
            if not allowed:
                raise PolicyDenied(policy.iri, iri, 403, reason)
        return identity

    def allows(self, element, identity: Identity | None) -> tuple[bool, str]:
        """(allowed, reason) of ``check_element``, without raising."""
        try:
            self.check_element(element, identity)
        except PolicyDenied as denied:
            return False, denied.reason
        governed = (self.model.curie(element), SEAM.governedBy, None) in self.model.ds
        return True, (
            "every governing policy permits it" if governed else "ungoverned element: any authenticated identity"
        )

    def task_dependency(self, task_curie):
        """A FastAPI dependency: ``Depends(hook.task_dependency(":approve"))``
        authenticates (401) and checks the task's policies (403), yielding the
        Identity."""
        from fastapi import HTTPException, Request

        def _task_dependency(request: Request) -> Identity:
            try:
                return self.check_element(task_curie, self.authenticate(request))
            except PolicyDenied as denied:
                raise HTTPException(status_code=denied.http_status, detail=denied.to_dict()) from denied

        _task_dependency.__name__ = f"task_policy_{local_name(self.model.curie(task_curie))}"
        return _task_dependency

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
