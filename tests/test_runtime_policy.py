"""seams_runtime.policy: the seam:governedBy hook behind a FastAPI route (D014, GAP-20)."""

from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from rdflib import URIRef

from seams_runtime import (
    HeaderAuthenticator,
    Identity,
    ModelGraph,
    PolicyDenied,
    PolicyHook,
    PresenceEvaluator,
    RoleEvaluator,
    StaticUserAuthenticator,
    authenticator_from_env,
)
from seams_runtime.model import ODRL, Permission, PolicyFacts

ROOT = Path(__file__).resolve().parent.parent
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
APPROVAL_TRIG = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
CHAT = "https://example.org/chat/"


@pytest.fixture(scope="module")
def model():
    return ModelGraph(TRIG)


@pytest.fixture
def fresh():
    """A private copy for tests that mutate the graph."""
    return ModelGraph(TRIG)


def _client(hook: PolicyHook) -> TestClient:
    app = FastAPI()

    @app.post("/send")
    def send(identity: Annotated[Identity, Depends(hook.dependency(":user_send_policy"))]):
        return {"user": identity.id}

    return TestClient(app)


def test_chat_namespace_matches_model(model):
    assert model.curie(":user_send_policy") == URIRef(CHAT + "user_send_policy")


def test_no_header_is_401_naming_the_policy(model):
    response = _client(PolicyHook(model)).post("/send")
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["type"] == "PolicyDenied"
    assert detail["http_status"] == 401
    assert detail["policy"].endswith("user_send_policy")
    assert "user_send_policy" in detail["message"]
    assert detail["operation"] == CHAT + "send_message_op"


def test_blank_header_is_401(model):
    response = _client(PolicyHook(model)).post("/send", headers={"X-Forwarded-User": "  "})
    assert response.status_code == 401


def test_forwarded_user_is_allowed(model):
    response = _client(PolicyHook(model)).post("/send", headers={"X-Forwarded-User": "alice"})
    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


def test_custom_header_name(model):
    hook = PolicyHook(model, HeaderAuthenticator(header="X-User"))
    client = _client(hook)
    assert client.post("/send", headers={"X-Forwarded-User": "alice"}).status_code == 401
    assert client.post("/send", headers={"X-User": "bob"}).json() == {"user": "bob"}


def test_static_user_needs_no_header(model):
    response = _client(PolicyHook(model, StaticUserAuthenticator("dev"))).post("/send")
    assert response.status_code == 200
    assert response.json() == {"user": "dev"}


def test_authenticator_from_env():
    dev = authenticator_from_env({"SEAMS_DEV_USER": "dev"})
    assert isinstance(dev, StaticUserAuthenticator)
    assert dev(None) == Identity("dev")
    assert isinstance(authenticator_from_env({}), HeaderAuthenticator)
    assert isinstance(authenticator_from_env({"SEAMS_DEV_USER": ""}), HeaderAuthenticator)


def test_authenticator_from_env_defaults_to_os_environ(monkeypatch):
    monkeypatch.delenv("SEAMS_DEV_USER", raising=False)
    assert isinstance(authenticator_from_env(), HeaderAuthenticator)
    monkeypatch.setenv("SEAMS_DEV_USER", "carol")
    assert authenticator_from_env()(None) == Identity("carol")


def test_removed_permissions_are_403_no_permission(fresh):
    policy = fresh.curie(":user_send_policy")
    for node in list(fresh.ds.objects(policy, ODRL.permission)):
        for triple in list(fresh.ds.triples((node, None, None))):
            fresh.ds.remove(triple)
        fresh.ds.remove((policy, ODRL.permission, node))
    assert fresh.policy(":user_send_policy").permissions == ()

    response = _client(PolicyHook(fresh)).post("/send", headers={"X-Forwarded-User": "alice"})
    assert response.status_code == 403
    assert "no permission" in response.json()["detail"]["reason"]


def test_custom_evaluator_denial_is_403_with_its_reason(model):
    seen = []

    def deny(policy, operation_iri, identity):
        seen.append((policy.iri, operation_iri, identity))
        return False, "mallory is banned"

    response = _client(PolicyHook(model, evaluator=deny)).post("/send", headers={"X-Forwarded-User": "mallory"})
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "mallory is banned"
    assert seen == [(URIRef(CHAT + "user_send_policy"), URIRef(CHAT + "send_message_op"), Identity("mallory"))]


# ── framework-free core ──


class _Req:
    def __init__(self, headers):
        self.headers = headers


def test_check_returns_identity_and_raises_policy_denied(model):
    hook = PolicyHook(model)
    assert hook.check(":user_send_policy", ":send_message_op", _Req({"X-Forwarded-User": "a"})) == Identity("a")
    with pytest.raises(PolicyDenied) as exc:
        hook.check(":user_send_policy", None, _Req({}))
    assert exc.value.http_status == 401


def test_check_rejects_an_operation_the_policy_does_not_govern(model):
    from seams_runtime import ResolutionError

    with pytest.raises(ResolutionError):
        PolicyHook(model).check(":user_send_policy", ":completion_op", _Req({"X-Forwarded-User": "a"}))


def test_presence_evaluator_assignee_rules():
    op = URIRef(CHAT + "send_message_op")
    alice = URIRef(CHAT + "alice")

    def facts(*perms):
        return PolicyFacts(URIRef(CHAT + "p"), "p", tuple(perms))

    ev = PresenceEvaluator()
    party = facts(Permission(op, ODRL.use, alice, ()))
    assert ev(party, op, Identity("alice"))[0]
    assert ev(party, op, Identity(str(alice)))[0]
    allowed, reason = ev(party, op, Identity("bob"))
    assert not allowed and "bob" in reason

    no_action = facts(Permission(op, None, alice, ()))
    assert ev(no_action, op, Identity("alice"))[0] is False

    other_target = facts(Permission(URIRef(CHAT + "other_op"), ODRL.use, None, ()))
    allowed, reason = ev(other_target, op, Identity("alice"))
    assert not allowed and "no permission" in reason

    collection = facts(Permission(op, ODRL.use, URIRef(CHAT + "users"), (ODRL.PartyCollection,)))
    assert ev(collection, op, Identity("anyone"))[0]


# ── roles (backlog E5, D028) ──


def test_identity_roles_default_empty_and_hashable():
    assert Identity("x").roles == frozenset()
    assert Identity("x") == Identity("x", frozenset())
    assert hash(Identity("x", frozenset({"manager"}))) == hash(Identity("x", frozenset({"manager"})))


def test_policy_hook_default_is_role_evaluator(model):
    assert isinstance(PolicyHook(model).evaluator, RoleEvaluator)


def _role_facts():
    op = URIRef(CHAT + "send_message_op")
    employee = URIRef(CHAT + "employee")
    policy = PolicyFacts(URIRef(CHAT + "employee_submit_policy"), "p", (Permission(op, ODRL.use, employee, ()),))
    return op, employee, policy


def test_role_evaluator_matches_role_by_local_name_and_full_iri():
    op, employee, policy = _role_facts()
    ev = RoleEvaluator()
    assert ev(policy, op, Identity("alice", frozenset({"employee"})))[0]
    assert ev(policy, op, Identity("alice", frozenset({str(employee)})))[0]


def test_role_evaluator_still_matches_id_without_roles():
    op, employee, policy = _role_facts()
    ev = RoleEvaluator()
    assert ev(policy, op, Identity("employee"))[0]
    assert ev(policy, op, Identity(str(employee)))[0]


def test_role_evaluator_denies_a_non_matching_role_with_reason():
    op, employee, policy = _role_facts()
    allowed, reason = RoleEvaluator()(policy, op, Identity("bob", frozenset({"manager", "finance"})))
    assert not allowed
    assert reason == (
        f"identity 'bob' (roles: finance, manager) is not an assignee ({employee}) of {CHAT}employee_submit_policy"
    )
    allowed, reason = RoleEvaluator()(policy, op, Identity("bob"))
    assert not allowed and "(roles: none)" in reason


def test_role_evaluator_party_collection_and_no_assignee_admit_anyone():
    op = URIRef(CHAT + "send_message_op")
    ev = RoleEvaluator()
    collection = PolicyFacts(
        URIRef(CHAT + "p"), "p", (Permission(op, ODRL.use, URIRef(CHAT + "users"), (ODRL.PartyCollection,)),)
    )
    assert ev(collection, op, Identity("anyone"))[0]
    open_perm = PolicyFacts(URIRef(CHAT + "p"), "p", (Permission(op, ODRL.use, None, ()),))
    assert ev(open_perm, op, Identity("anyone", frozenset({"x"})))[0]
    no_action = PolicyFacts(URIRef(CHAT + "p"), "p", (Permission(op, None, None, ()),))
    allowed, reason = ev(no_action, op, Identity("anyone", frozenset({"employee"})))
    assert not allowed and "no permission" in reason


def test_role_mismatch_is_403_through_the_dependency(fresh):
    """A specific-party assignee on the chat policy: a role that does not
    match is 403 with the reason, a matching groups header is 200."""
    policy = fresh.curie(":user_send_policy")
    employee = URIRef(CHAT + "employee")
    for node in fresh.ds.objects(policy, ODRL.permission):
        for old in list(fresh.ds.objects(node, ODRL.assignee)):
            fresh.ds.remove((node, ODRL.assignee, old))
        fresh.ds.add((node, ODRL.assignee, employee))
    client = _client(PolicyHook(fresh))
    denied = client.post("/send", headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "manager"})
    assert denied.status_code == 403
    assert "identity 'bob' (roles: manager) is not an assignee" in denied.json()["detail"]["reason"]
    ok = client.post("/send", headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "employee"})
    assert ok.status_code == 200


def test_header_authenticator_parses_groups():
    auth = HeaderAuthenticator()
    identity = auth(_Req({"X-Forwarded-User": "alice", "X-Forwarded-Groups": "employee, manager, , "}))
    assert identity == Identity("alice", frozenset({"employee", "manager"}))
    assert auth(_Req({"X-Forwarded-User": "alice"})).roles == frozenset()
    assert auth(_Req({"X-Forwarded-User": "alice", "X-Forwarded-Groups": " , "})).roles == frozenset()
    assert "X-Forwarded-Groups" in repr(auth)
    custom = HeaderAuthenticator(roles_header="X-Roles")
    assert custom(_Req({"X-Forwarded-User": "a", "X-Roles": "finance"})).roles == frozenset({"finance"})


def test_dev_roles_env_sets_roles():
    dev = authenticator_from_env({"SEAMS_DEV_USER": "dev", "SEAMS_DEV_ROLES": "employee, finance,"})
    assert dev(None) == Identity("dev", frozenset({"employee", "finance"}))
    assert authenticator_from_env({"SEAMS_DEV_USER": "dev"})(None).roles == frozenset()
    assert isinstance(authenticator_from_env({"SEAMS_DEV_ROLES": "employee"}), HeaderAuthenticator)


def test_check_element_admits_manager_role_on_approval_task():
    hook = PolicyHook(ModelGraph(APPROVAL_TRIG))
    task = "https://example.org/expenses/approval_bpmn#approve_expense"
    manager = Identity("alice", frozenset({"manager"}))
    assert hook.check_element(task, manager) == manager
    with pytest.raises(PolicyDenied) as exc:
        hook.check_element(task, Identity("alice", frozenset({"employee"})))
    assert exc.value.http_status == 403
    assert "identity 'alice' (roles: employee) is not an assignee" in exc.value.reason
