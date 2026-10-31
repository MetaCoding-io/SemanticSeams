"""Optional OpenTelemetry spans whose attributes are graph element IRIs (D049).

Tracing is off by default. ``tracer_from_env`` returns a no-op ``Telemetry``
unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and non-empty. With it set, the
``otel`` extra of seams_runtime (opentelemetry-sdk and the OTLP/HTTP
exporter) must be installed; without it one WARNING is logged and tracing
stays off. Otherwise a private ``TracerProvider`` (the global provider is
never touched) exports through ``BatchSpanProcessor(OTLPSpanExporter())``,
which reads the standard ``OTEL_EXPORTER_OTLP_*`` variables itself, under the
resource ``service.name`` of ``OTEL_SERVICE_NAME`` (default "seams-runtime").

The worker opens one instance span per ``Worker.run`` (a resumed instance or
a user-task continuation is another instance span with the same instance id)
and one child span per BPMN element, named after its bpmn id. Attributes are
set when the span ends, from the instance state and the finished trace row:

- instance: ``seams.process.iri``, ``seams.instance.id``,
  ``seams.correlation_key``; status ERROR (described by the error type) when
  the instance failed;
- element: those three plus ``seams.element.iri``, ``bpmn.id`` and, when the
  row has them, ``seams.fires``, ``seams.decision``, ``seams.invokes``,
  ``seams.container``, ``seams.implementation`` (the ADR-0012 kind, or
  "runtime"), ``seams.handler`` (a Python handler's dotted path),
  ``seams.channel`` (from ``streamed`` or
  ``published``), ``seams.status`` and ``seams.by``. An element that raises
  records the exception and ends with status ERROR.

Spans mirror the trace rows; the rows stay the record ``seams sequence
--trace`` renders. Nothing here imports opentelemetry until tracing is on.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
SERVICE_ENV = "OTEL_SERVICE_NAME"
DEFAULT_SERVICE = "seams-runtime"
MISSING_SDK = f"{ENDPOINT_ENV} is set but opentelemetry-sdk is not installed; install the seams_runtime otel extra"

# trace row key -> span attribute, for the plain string values
_ROW_ATTRIBUTES = {
    "fires": "seams.fires",
    "decision": "seams.decision",
    "invokes": "seams.invokes",
    "container": "seams.container",
    "implementation": "seams.implementation",
    "handler": "seams.handler",
    "status": "seams.status",
    "by": "seams.by",
}


class _NoSpan:
    def error(self, type_: str, message: str = "") -> None:
        pass


class Telemetry:
    """Instance and element spans on ``tracer``; with no tracer, every span is
    a no-op. ``provider`` (when Telemetry built it) is shut down by
    ``shutdown``."""

    def __init__(self, tracer=None, provider=None):
        self.tracer = tracer
        self.provider = provider

    @property
    def enabled(self) -> bool:
        return self.tracer is not None

    @contextmanager
    def instance_span(self, instance):
        """The span around one ``Worker.run`` of ``instance``. Yields a handle
        whose ``error(type, message)`` marks the span failed."""
        if self.tracer is None:
            yield _NoSpan()
            return
        name = str(instance.process).rsplit("#", 1)[-1].rsplit("/", 1)[-1] or "instance"
        with self.tracer.start_as_current_span(name) as span:
            handle = _SpanHandle(span)
            try:
                yield handle
            finally:
                span.set_attributes(_instance_attributes(instance))

    @contextmanager
    def element_span(self, instance, row: dict):
        """The span around one BPMN element. ``row`` is the element's trace
        row, read when the span ends (so it carries what the element did)."""
        if self.tracer is None:
            yield
            return
        with self.tracer.start_as_current_span(row.get("task") or "element") as span:
            try:
                yield
            finally:
                span.set_attributes(_instance_attributes(instance) | element_attributes(row))

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()


class _SpanHandle:
    def __init__(self, span):
        self.span = span

    def error(self, type_: str, message: str = "") -> None:
        from opentelemetry.trace import Status, StatusCode

        self.span.set_status(Status(StatusCode.ERROR, type_))
        self.span.set_attribute("seams.error.type", type_)
        if message:
            self.span.set_attribute("seams.error.message", message)


def _instance_attributes(instance) -> dict:
    return {
        "seams.process.iri": str(instance.process),
        "seams.instance.id": instance.id,
        "seams.correlation_key": instance.correlation_key,
    }


def element_attributes(row: dict) -> dict:
    """The element span attributes of a trace row (absent keys are skipped)."""
    attrs = {}
    if row.get("iri"):
        attrs["seams.element.iri"] = row["iri"]
    if row.get("task"):
        attrs["bpmn.id"] = row["task"]
    for key, attr in _ROW_ATTRIBUTES.items():
        if row.get(key) is not None:
            attrs[attr] = str(row[key])
    channel = (row.get("streamed") or row.get("published") or {}).get("channel")
    if channel:
        attrs["seams.channel"] = channel
    return attrs


def _traces_url(env, endpoint: str) -> str:
    return env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or endpoint.rstrip("/") + "/v1/traces"


def tracer_from_env(environ=None) -> Telemetry:
    """A ``Telemetry`` exporting over OTLP when ``OTEL_EXPORTER_OTLP_ENDPOINT``
    is set and the otel extra is installed, else a no-op one."""
    env = os.environ if environ is None else environ
    endpoint = env.get(ENDPOINT_ENV)
    if not endpoint:
        return Telemetry()
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning(MISSING_SDK)
        return Telemetry()
    service = env.get(SERVICE_ENV) or DEFAULT_SERVICE
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    # the exporter reads the OTEL_EXPORTER_OTLP_* variables from os.environ
    # itself; an injected environ names the traces URL explicitly
    exporter = OTLPSpanExporter() if environ is None else OTLPSpanExporter(endpoint=_traces_url(env, endpoint))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    log.info("OpenTelemetry tracing enabled: OTLP endpoint %s, service.name %s", endpoint, service)
    return Telemetry(provider.get_tracer("seams_runtime"), provider)
