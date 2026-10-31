"""ADR-0013 spike (M014/S04): how SpiffWorkflow routes a service task's error to an
attached error boundary event, kept as a regression test.

The BPMN is inline and vendor-extension-free. It is parsed with the engine's own
``GraphBoundParser`` and serialized with ``make_serializer``, and it is stepped the way
``seams_runtime.worker.Worker._next`` steps it: a STARTED task before a READY one,
and manual tasks never. Each test pins one of the ADR's spike findings.
"""

from pathlib import Path

import pytest
from SpiffWorkflow.bpmn.exceptions import WorkflowTaskException
from SpiffWorkflow.bpmn.specs.event_definitions import ErrorEventDefinition
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.util.task import TaskState

from seams_runtime.engine import GraphBoundParser, make_serializer

CODE = "notify-failed"

BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="spike_defs" targetNamespace="https://example.org/spike">
  <bpmn:error id="notify_failed_error" name="Notification failed" errorCode="notify-failed" />
  <bpmn:process id="spike" name="Spike" isExecutable="true">
    <bpmn:startEvent id="start" />
    <bpmn:sequenceFlow id="f_start" sourceRef="start" targetRef="notify" />
    <bpmn:serviceTask id="notify" name="Notify" />
    <bpmn:sequenceFlow id="f_ok" sourceRef="notify" targetRef="after_notify" />
    <bpmn:intermediateThrowEvent id="after_notify" name="After notify" />
    <bpmn:sequenceFlow id="f_done" sourceRef="after_notify" targetRef="done" />
    <bpmn:endEvent id="done" />
    <bpmn:boundaryEvent id="notify_failed_boundary" attachedToRef="notify">
      <bpmn:errorEventDefinition errorRef="notify_failed_error" />
    </bpmn:boundaryEvent>
    <bpmn:sequenceFlow id="f_err" sourceRef="notify_failed_boundary" targetRef="escalate" />
    <bpmn:intermediateThrowEvent id="escalate" name="Escalate" />
    <bpmn:sequenceFlow id="f_failed" sourceRef="escalate" targetRef="failed" />
    <bpmn:endEvent id="failed" />
  </bpmn:process>
</bpmn:definitions>
"""

# The same process with a catch-all boundary: no errorRef, so no code.
CATCH_ALL = BPMN.replace(
    '<bpmn:errorEventDefinition errorRef="notify_failed_error" />', "<bpmn:errorEventDefinition />"
)


def workflow(tmp_path: Path, xml: str = BPMN) -> BpmnWorkflow:
    path = tmp_path / "spike.bpmn"
    path.write_text(xml, encoding="utf-8")
    parser = GraphBoundParser()
    parser.add_bpmn_file(str(path))
    return BpmnWorkflow(parser.get_spec("spike"), parser.get_subprocess_specs("spike"))


def next_task(wf: BpmnWorkflow):
    """Worker._next: the first STARTED task, else the first READY non-manual one."""
    started = wf.get_tasks(state=TaskState.STARTED)
    if started:
        return started[0]
    ready = [t for t in wf.get_tasks(state=TaskState.READY) if not t.task_spec.manual]
    return ready[0] if ready else None


def run_until_started_service_task(wf: BpmnWorkflow):
    """Step like the worker until the service task is STARTED (its handler would run)."""
    while (task := next_task(wf)) is not None:
        if task.state == TaskState.STARTED:
            if task.task_spec.bpmn_id == "notify":
                return task
            task.complete()
        else:
            task.run()
    raise AssertionError("the service task never started")


def run_to_end(wf: BpmnWorkflow) -> None:
    while (task := next_task(wf)) is not None:
        if task.state == TaskState.STARTED:
            task.complete()
        else:
            task.run()


def state(wf: BpmnWorkflow, bpmn_id: str) -> str:
    (task,) = [t for t in wf.get_tasks() if t.task_spec.bpmn_id == bpmn_id]
    return TaskState.get_name(task.state)


def completed_ids(wf: BpmnWorkflow) -> set:
    return {t.task_spec.bpmn_id for t in wf.get_tasks(state=TaskState.COMPLETED)} - {None}


def test_boundary_waits_while_the_service_task_is_started(tmp_path):
    wf = workflow(tmp_path)
    run_until_started_service_task(wf)
    assert state(wf, "notify") == "STARTED"
    assert state(wf, "notify_failed_boundary") == "WAITING"


@pytest.mark.parametrize("raise_it", ["exception", "task_error"])
def test_an_exception_never_reaches_the_boundary(tmp_path, raise_it):
    """Finding 1: Spiff does not map an exception to an error event."""
    wf = workflow(tmp_path)
    task = run_until_started_service_task(wf)
    if raise_it == "exception":
        with pytest.raises(WorkflowTaskException):
            raise WorkflowTaskException(CODE, task=task)
    task.error()
    assert state(wf, "notify") == "ERROR"
    assert state(wf, "notify_failed_boundary") == "WAITING"


def test_a_matching_code_readies_the_boundary_and_leaves_the_task_started(tmp_path):
    """Findings 2 and 4: the throw readies the boundary; the task is not yet cancelled."""
    wf = workflow(tmp_path)
    task = run_until_started_service_task(wf)
    ErrorEventDefinition("name is not matched", CODE).throw(task)
    assert state(wf, "notify_failed_boundary") == "READY"
    assert state(wf, "notify") == "STARTED"
    # The worker's loop would pick the STARTED task again, not the boundary.
    assert next_task(wf) is task


def test_running_the_boundary_cancels_the_task_and_takes_the_error_path(tmp_path):
    """Findings 4 and 5: the boundary cancels the task; data flows down the error path."""
    wf = workflow(tmp_path)
    task = run_until_started_service_task(wf)
    task.data["problem"] = {"title": "Notification failed", "status": 502}
    ErrorEventDefinition("Notification failed", CODE).throw(task)
    (boundary,) = [t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.bpmn_id == "notify_failed_boundary"]
    boundary.run()
    assert state(wf, "notify") == "CANCELLED"
    run_to_end(wf)
    assert wf.is_completed()
    assert {"notify_failed_boundary", "escalate", "failed"} <= completed_ids(wf)
    assert not {"notify", "after_notify", "done"} & completed_ids(wf)
    (escalate,) = [t for t in wf.get_tasks() if t.task_spec.bpmn_id == "escalate"]
    assert escalate.data["problem"] == {"title": "Notification failed", "status": 502}


def test_an_undeclared_code_changes_nothing(tmp_path):
    """Finding 3: the worker can tell an uncaught throw and fail the instance."""
    wf = workflow(tmp_path)
    task = run_until_started_service_task(wf)
    ErrorEventDefinition("Other", "some-other-code").throw(task)
    assert state(wf, "notify") == "STARTED"
    assert state(wf, "notify_failed_boundary") == "WAITING"
    assert not [t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.bpmn_id is not None]


def test_a_catch_all_boundary_catches_any_code(tmp_path):
    """Finding 2: no errorRef means no code, which matches every thrown code."""
    wf = workflow(tmp_path, CATCH_ALL)
    task = run_until_started_service_task(wf)
    ErrorEventDefinition("Other", "some-other-code").throw(task)
    assert state(wf, "notify_failed_boundary") == "READY"


def test_the_happy_path_is_unchanged(tmp_path):
    wf = workflow(tmp_path)
    run_until_started_service_task(wf).complete()
    run_to_end(wf)
    assert wf.is_completed()
    assert {"notify", "after_notify", "done"} <= completed_ids(wf)
    assert not {"notify_failed_boundary", "escalate", "failed"} & completed_ids(wf)


def test_a_serialized_started_task_still_routes_its_error(tmp_path):
    """Finding 6: checkpointing between start and throw keeps the boundary waiting."""
    serializer = make_serializer()
    wf = workflow(tmp_path)
    run_until_started_service_task(wf)
    wf = serializer.deserialize_json(serializer.serialize_json(wf))
    (task,) = wf.get_tasks(state=TaskState.STARTED)
    assert state(wf, "notify_failed_boundary") == "WAITING"
    ErrorEventDefinition("Notification failed", CODE).throw(task)
    assert state(wf, "notify_failed_boundary") == "READY"
