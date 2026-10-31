"""seams_runtime's optional OpenTelemetry spans (M013/S04 T03, D049): one
instance span per worker run and one child span per trace row, with graph
element IRIs as attributes. Spans go to an in-memory exporter on a local
TracerProvider injected as ``telemetry=``; the global provider is never set."""

import asyncio
import logging
import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import StatusCode  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_runtime import Runtime, SQLiteStore, Telemetry, tracer_from_env  # noqa: E402
from seams_runtime import telemetry as telemetry_mod  # noqa: E402
from tests.test_runtime_worker import PROCESS, SHORT, TRIG, FakeLLM  # noqa: E402

CHAT = "https://example.org/chat/"


@pytest.fixture
def spans():
    """(Telemetry on a local provider, its in-memory exporter)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield Telemetry(provider.get_tracer("test")), exporter
    provider.shutdown()


def _run(tmp_path, telemetry, llm):
    rt = Runtime.load(
        TRIG,
        store=SQLiteStore(tmp_path / "seams.sqlite"),
        llm_transport=llm.transport,
        llm_base_url="http://llm-gateway.test",
        telemetry=telemetry,
    )
    assert rt.telemetry is telemetry and rt.worker.telemetry is telemetry

    async def main():
        inst = await rt.start_process(PROCESS, SHORT, correlation_key="c1")
        return await inst.wait()

    return asyncio.run(main())


def test_send_message_spans_mirror_the_trace_rows(tmp_path, spans):
    telemetry, exporter = spans
    result = _run(tmp_path, telemetry, FakeLLM())
    assert result["status"] == "complete", result["error"]

    finished = exporter.get_finished_spans()
    roots = [s for s in finished if s.parent is None]
    assert len(roots) == 1
    root = roots[0]
    assert root.name == "send_message_process"
    assert root.status.status_code == StatusCode.UNSET
    assert root.attributes["seams.process.iri"] == CHAT + "send_message_process"
    assert root.attributes["seams.instance.id"] == result["instance"]
    assert root.attributes["seams.correlation_key"] == "c1"

    children = [s for s in finished if s.parent is not None]
    assert all(s.parent.span_id == root.context.span_id for s in children)
    assert all(s.context.trace_id == root.context.trace_id for s in children)
    # one child per trace row, in row order (children end in execution order)
    rows = result["trace"]
    assert [s.name for s in children] == [r["task"] for r in rows]
    assert [s.attributes["seams.element.iri"] for s in children] == [r["iri"] for r in rows]
    for span, row in zip(children, rows, strict=True):
        assert span.attributes["bpmn.id"] == row["task"]
        assert span.attributes["seams.instance.id"] == result["instance"]
        for key, attr in [("fires", "seams.fires"), ("decision", "seams.decision"), ("status", "seams.status")]:
            assert span.attributes.get(attr) == row.get(key)

    invoke_row = next(r for r in rows if r["task"] == "invoke_llm")
    invoke = next(s for s in children if s.name == "invoke_llm")
    assert invoke.attributes["seams.invokes"] == invoke_row["invokes"]
    assert invoke.attributes["seams.container"] == invoke_row["container"]
    assert invoke.attributes["seams.channel"] == invoke_row["streamed"]["channel"]
    assert invoke.attributes["seams.channel"] == CHAT + "stream_events"
    # a decision row carries its DMN decision IRI
    decided = [s for s in children if "seams.decision" in s.attributes]
    assert decided and all(s.attributes["seams.decision"].startswith("https://") for s in decided)


def test_failing_llm_marks_the_instance_span_error(tmp_path, spans):
    telemetry, exporter = spans
    result = _run(tmp_path, telemetry, FakeLLM(fail=httpx.ConnectError("connection refused")))
    assert result["status"] == "failed"

    finished = exporter.get_finished_spans()
    root = next(s for s in finished if s.parent is None)
    assert root.status.status_code == StatusCode.ERROR
    assert root.status.description == result["error"]["type"]
    assert root.attributes["seams.error.type"] == result["error"]["type"]
    # the element that raised records the exception on its own span
    invoke = next(s for s in finished if s.name == "invoke_llm")
    assert invoke.status.status_code == StatusCode.ERROR
    assert any(e.name == "exception" for e in invoke.events)
    assert invoke.attributes["seams.invokes"].startswith(CHAT)


def test_default_telemetry_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(telemetry_mod.ENDPOINT_ENV, raising=False)
    assert not tracer_from_env({}).enabled
    assert not tracer_from_env({telemetry_mod.ENDPOINT_ENV: ""}).enabled
    # Runtime builds the no-op from the environment, and the worker still runs
    result = _run_default(tmp_path)
    assert result["status"] == "complete", result["error"]


def _run_default(tmp_path):
    rt = Runtime.load(
        TRIG,
        store=SQLiteStore(tmp_path / "seams.sqlite"),
        llm_transport=FakeLLM().transport,
        llm_base_url="http://llm-gateway.test",
    )
    assert not rt.telemetry.enabled

    async def main():
        return await (await rt.start_process(PROCESS, SHORT, correlation_key="c1")).wait()

    return asyncio.run(main())


def test_endpoint_without_sdk_logs_one_warning(monkeypatch, caplog):
    import builtins

    real_import = builtins.__import__

    def no_otel_sdk(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk") or name.startswith("opentelemetry.exporter"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_otel_sdk)
    with caplog.at_level(logging.INFO, logger="seams_runtime.telemetry"):
        telemetry = tracer_from_env({telemetry_mod.ENDPOINT_ENV: "http://collector.test:4318"})
    assert not telemetry.enabled
    records = [r for r in caplog.records if r.name == "seams_runtime.telemetry"]
    assert [(r.levelno, r.getMessage()) for r in records] == [(logging.WARNING, telemetry_mod.MISSING_SDK)]


def test_endpoint_with_sdk_builds_a_real_telemetry(caplog):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http")
    env = {telemetry_mod.ENDPOINT_ENV: "http://127.0.0.1:9/", "OTEL_SERVICE_NAME": "chat-api"}
    with caplog.at_level(logging.INFO, logger="seams_runtime.telemetry"):
        telemetry = tracer_from_env(env)
    try:
        assert telemetry.enabled and telemetry.provider is not None
        assert telemetry.provider.resource.attributes["service.name"] == "chat-api"
        messages = [r.getMessage() for r in caplog.records if r.name == "seams_runtime.telemetry"]
        assert len(messages) == 1 and "http://127.0.0.1:9/" in messages[0]
    finally:
        telemetry.shutdown()  # no span was started, so nothing is exported


def test_service_name_defaults_to_seams_runtime():
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http")
    telemetry = tracer_from_env({telemetry_mod.ENDPOINT_ENV: "http://127.0.0.1:9"})
    try:
        assert telemetry.provider.resource.attributes["service.name"] == "seams-runtime"
    finally:
        telemetry.shutdown()


def test_element_attributes_skip_absent_keys():
    row = {"task": "publish_done", "iri": CHAT + "publish_done", "published": {"channel": CHAT + "ch", "event": "x"}}
    assert telemetry_mod.element_attributes(row) == {
        "seams.element.iri": CHAT + "publish_done",
        "bpmn.id": "publish_done",
        "seams.channel": CHAT + "ch",
    }
    assert telemetry_mod.element_attributes({"task": "review", "iri": "i", "by": "alice"})["seams.by"] == "alice"


def test_user_task_continuation_is_another_instance_span(tmp_path, spans):
    """The human-task fixture: the first run waits on approve_expense; the
    completion (with ``seams.by``) and the resumed loop are further instance
    spans with the same instance id."""
    from seams_runtime import HeaderAuthenticator, Identity, ModelGraph

    telemetry, exporter = spans
    approval = ROOT / "tests" / "fixtures" / "human_task" / "approval.trig"
    task = "https://example.org/expenses/approval_bpmn#approve_expense"
    rt = Runtime(
        ModelGraph.load(approval),
        SQLiteStore(tmp_path / "seams.sqlite"),
        authenticator=HeaderAuthenticator(),
        templates_dir=tmp_path,
        telemetry=telemetry,
    )

    async def main():
        inst = await rt.start_process(":approval_process", {"description": "Train", "amount": "4.50"}, "e1")
        assert (await inst.wait())["status"] == "waiting"
        inst = await rt.complete_task(task, {"decision": "approved"}, "e1", Identity("manager"))
        return await inst.wait()

    result = asyncio.run(main())
    assert result["status"] == "complete", result["error"]
    finished = exporter.get_finished_spans()
    roots = [s for s in finished if s.parent is None]
    assert len(roots) == 3
    assert {s.attributes["seams.instance.id"] for s in roots} == {result["instance"]}
    [approve] = [s for s in finished if s.name == "approve_expense"]
    assert approve.attributes["seams.by"] == "manager"
    assert approve.attributes["seams.element.iri"] == task
    assert len([s for s in finished if s.parent is not None]) == len(result["trace"])
