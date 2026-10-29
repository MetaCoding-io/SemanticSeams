"""Human tasks in seams_runtime (ADR-0009, M009/S04 T02), against the expense
approval fixture: the instance waits on the approve_expense user task, which
only a manager may list and complete. Completion validates the ApprovalShape
payload, persists it, records who completed it, and lets the worker finish.
"""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import (  # noqa: E402
    ContractViolation,
    HeaderAuthenticator,
    Identity,
    ModelGraph,
    PolicyDenied,
    Runtime,
    Store,
    TaskNotOpen,
)

TRIG = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
PROCESS = ":approval_process"
EXPENSE = {"description": "Train to Leeds", "amount": "42.50"}
MANAGER = Identity("manager")
EMPLOYEE = Identity("employee")


def make_runtime(tmp_path) -> Runtime:
    return Runtime(ModelGraph.load(TRIG), Store(tmp_path / "seams.sqlite"),
                   authenticator=HeaderAuthenticator(), templates_dir=tmp_path)


async def _waiting(rt, key="e1"):
    inst = await rt.start_process(PROCESS, EXPENSE, correlation_key=key)
    result = await inst.wait()
    assert result["status"] == "waiting", result["error"]
    return inst


def test_instance_waits_and_stores_the_open_task(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        inst = await _waiting(rt)
        rows = rt.store.list_user_tasks()
        assert [(r["instance_id"], r["task"], r["bpmn_id"], r["correlation_key"], r["process"])
                for r in rows] == [(inst.id, TASK, "approve_expense", "e1", EX + "approval_process")]
        assert inst.result["lifecycle"] == {"Expense": "submitted"}
    asyncio.run(main())


def test_only_the_manager_sees_the_task(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        inst = await _waiting(rt)
        [row] = rt.user_tasks(MANAGER)
        assert row["instance"] == inst.id and row["task"] == TASK
        assert row["label"] == "Approve Expense" and row["correlation_key"] == "e1"
        assert row["form"] == EX + "approve_form" and row["partial"] == "approve_form.html"
        assert row["screen"] == "/approvals"
        assert row["entity"]["description"] == "Train to Leeds"
        assert row["entity"]["status"] == "submitted"
        assert rt.user_tasks(MANAGER, process=PROCESS) == [row]
        assert rt.user_tasks(MANAGER, process=":other_process") == []
        assert rt.user_tasks(EMPLOYEE) == []
        with pytest.raises(PolicyDenied) as err:
            rt.user_tasks(None)
        assert err.value.http_status == 401
    asyncio.run(main())


def test_completion_is_authorized(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt)
        with pytest.raises(PolicyDenied) as err:
            await rt.complete_task(TASK, {"decision": "approved"}, "e1", EMPLOYEE)
        assert err.value.http_status == 403
        assert err.value.policy == EX + "manager_approval_policy"
        with pytest.raises(PolicyDenied) as err:
            await rt.complete_task(TASK, {"decision": "approved"}, "e1", None)
        assert err.value.http_status == 401
        assert len(rt.user_tasks(MANAGER)) == 1
    asyncio.run(main())


@pytest.mark.parametrize("payload", [
    {"decision": "maybe"}, {}, {"decision": "approved", "comment": "x" * 501},
    {"decision": "approved", "extra": "field"},
], ids=["not-in-list", "missing", "too-long", "unknown-field"])
def test_invalid_payload_changes_nothing(tmp_path, payload):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt)
        with pytest.raises(ContractViolation) as err:
            await rt.complete_task(TASK, payload, "e1", MANAGER)
        assert err.value.http_status == 422
        assert len(rt.user_tasks(MANAGER)) == 1
        assert rt.query(":ApprovalShape") == []
    asyncio.run(main())


def test_valid_completion_finishes_the_process(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt)
        inst = await rt.complete_task(TASK, {"decision": "approved", "comment": "fine"}, "e1", MANAGER)
        result = await inst.wait()
        assert result["status"] == "complete", result["error"]
        [approval] = rt.query(":ApprovalShape", expense="e1")
        assert approval["data"] == {"decision": "approved", "comment": "fine"}
        assert approval["instance_id"] == inst.id
        assert result["entities"]["Approval"] == [approval["id"]]
        # The task fires no transition, so the expense stays submitted.
        assert result["lifecycle"] == {"Expense": "submitted"}
        [row] = [r for r in result["trace"] if r["task"] == "approve_expense"]
        assert row["by"] == "manager" and row["writes"] == [approval["id"]]
        assert "by" not in [r for r in result["trace"] if r["task"] == "persist_expense"][0]
        assert rt.user_tasks(MANAGER) == [] and rt.store.list_user_tasks() == []
        assert rt.store.get_instance(inst.id)["status"] == "complete"

        with pytest.raises(TaskNotOpen) as err:
            await rt.complete_task(TASK, {"decision": "rejected"}, "e1", MANAGER)
        assert err.value.http_status == 409
        assert err.value.to_dict()["correlation_key"] == "e1"
        assert len(rt.query(":ApprovalShape")) == 1
    asyncio.run(main())


def test_unknown_correlation_key_is_not_open(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt)
        with pytest.raises(TaskNotOpen) as err:
            await rt.complete_task(TASK, {"decision": "approved"}, "nope", MANAGER)
        assert err.value.http_status == 409 and err.value.task == TASK
    asyncio.run(main())


def test_concurrent_completions_complete_once(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt)
        results = await asyncio.gather(
            rt.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER),
            rt.complete_task(TASK, {"decision": "rejected"}, "e1", MANAGER),
            return_exceptions=True)
        assert sorted(type(r).__name__ for r in results) == ["Instance", "TaskNotOpen"]
        [inst] = [r for r in results if not isinstance(r, Exception)]
        assert (await inst.wait())["status"] == "complete"
        assert len(rt.query(":ApprovalShape")) == 1
    asyncio.run(main())


def test_two_instances_are_listed_and_completed_separately(tmp_path):
    rt = make_runtime(tmp_path)

    async def main():
        await _waiting(rt, "e1")
        await _waiting(rt, "e2")
        assert [r["correlation_key"] for r in rt.user_tasks(MANAGER)] == ["e1", "e2"]
        inst = await rt.complete_task(TASK, {"decision": "rejected"}, "e2", MANAGER)
        assert (await inst.wait())["status"] == "complete"
        assert [r["correlation_key"] for r in rt.user_tasks(MANAGER)] == ["e1"]
    asyncio.run(main())


def test_a_restarted_runtime_lists_and_completes_the_task(tmp_path):
    async def first():
        return (await _waiting(make_runtime(tmp_path))).id

    instance_id = asyncio.run(first())

    async def second():
        rt = make_runtime(tmp_path)
        [row] = rt.user_tasks(MANAGER)
        assert row["instance"] == instance_id
        inst = await rt.complete_task(TASK, {"decision": "approved"}, "e1", MANAGER)
        result = await inst.wait()
        assert inst.id == instance_id and result["status"] == "complete", result["error"]
        assert [r["by"] for r in result["trace"] if r["task"] == "approve_expense"] == ["manager"]
        assert rt.user_tasks(MANAGER) == []
    asyncio.run(second())


def test_task_policy_dependency(tmp_path):
    rt = make_runtime(tmp_path)
    app = FastAPI()

    @app.get("/check")
    def check(identity: Identity = Depends(rt.task_policy(TASK))):
        return {"id": identity.id}

    client = TestClient(app)
    assert client.get("/check", headers={"X-Forwarded-User": "manager"}).json() == {"id": "manager"}
    denied = client.get("/check", headers={"X-Forwarded-User": "employee"})
    assert denied.status_code == 403 and denied.json()["detail"]["type"] == "PolicyDenied"
    assert client.get("/check").status_code == 401


def test_policy_hook_allows_ungoverned_elements(tmp_path):
    rt = make_runtime(tmp_path)
    persist = EX + "approval_bpmn#persist_expense"
    assert rt.hook.allows(persist, EMPLOYEE)[0] is True
    assert rt.hook.allows(persist, None)[0] is False
    assert rt.hook.allows(TASK, MANAGER)[0] is True
    allowed, reason = rt.hook.allows(TASK, EMPLOYEE)
    assert allowed is False and "employee" in reason
