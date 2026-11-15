"""The as-observed named graph: recorded runs as ``obs:`` triples (ADR-0042).

``observed_graph(runs)`` builds one ``rdflib.Graph`` from recorded runs: each
run is an ``ObservedRun`` or a ``(run id, rows)`` pair, its rows the worker's
trace rows (``workflow.data["seams"]["trace"]``, as
``seams_gen.sequence.read_trace`` reads them). ``spans_to_runs(otlp_json)``
turns an OTLP/JSON span export into ``ObservedRun``s whose rows carry the same
keys, so a span file and the trace of the same run give the same steps.

The graph is never one of the model's graphs: it is not added to
``Model.dataset``, not written anywhere and never enters ``Model.hash``. Its
IRI is ``urn:seams:observed:<hex>``, the SHA-256 of the canonical input (runs
sorted by instance id, each with its carried row keys in trace order, as JSON
with sorted keys); a run is ``urn:seams:observed:run:<instance>`` and its step
``n`` is ``...:step:<n>``, the instance percent-encoded. ``observed_ntriples``
serialises it as sorted N-Triples, the same bytes for the same input.

Only the row keys of ADR-0042's table are carried (``iri``, ``task``,
``fires``, ``decision``, ``invokes``, ``container``, ``implementation``,
``handler``, ``status``, ``by``, ``boundary``, ``caught``, ``timer``, the
``channel`` of ``published``/``streamed`` and ``error.code``/``error.status``);
the rest are payload values or derivable from the model. A row may also hold
``channel`` directly: a span says which channel, not whether the element
published or streamed. A row with no ``iri`` is kept as an unmapped step.
Malformed input raises ``ResolutionError`` naming the row or span; nothing
is returned.

``observed_question(model, graph, name)`` asks one of ``OBSERVED_QUESTIONS``
(``seams/queries/observed/<name>.rq``) over a read-only union of the model's
graphs and ``graph``, with the model's BPMN flow nodes as the element
universe; ``model.ds`` is not mutated. ``dead-model`` lists the flow nodes no
step reached (``?node ?process``), ``conformance`` the steps the model does not
explain (``?run ?index ?step ?reached ?reason``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from rdflib import RDF, XSD, Graph, Literal, URIRef
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.plugins.sparql import prepareQuery
from rdflib.query import ResultRow
from rdflib.term import Node

from .errors import ResolutionError
from .namespaces import OBS
from .sparql import PREFIXES, Row

if TYPE_CHECKING:
    from .loader import Model

#: The questions ``observed_question`` asks, by name (``queries/observed/<name>.rq``).
OBSERVED_QUESTIONS = ("conformance", "dead-model")

#: Prefix of every as-observed graph IRI, then the hex SHA-256 of the canonical input.
GRAPH_PREFIX = "urn:seams:observed:"

#: Trace row keys whose value is an IRI, by obs: property.
_IRI_KEYS = {
    "iri": OBS.reached,
    "fires": OBS.fires,
    "decision": OBS.decision,
    "invokes": OBS.invokes,
    "container": OBS.container,
    "boundary": OBS.boundary,
    "channel": OBS.channel,
}
#: Trace row keys whose value is a string, by obs: property.
_STRING_KEYS = {
    "task": OBS.bpmnId,
    "implementation": OBS.implementation,
    "handler": OBS.handler,
    "status": OBS.status,
    "by": OBS.by,
    "caught": OBS.caught,
    "timer": OBS.timer,
}
#: Span attribute -> carried row key (ADR-0042 section 1; seams_runtime.telemetry writes them).
_SPAN_KEYS = {
    "seams.element.iri": "iri",
    "bpmn.id": "task",
    "seams.fires": "fires",
    "seams.decision": "decision",
    "seams.invokes": "invokes",
    "seams.container": "container",
    "seams.implementation": "implementation",
    "seams.handler": "handler",
    "seams.status": "status",
    "seams.by": "by",
    "seams.boundary": "boundary",
    "seams.caught": "caught",
    "seams.timer.due": "timer",
    "seams.channel": "channel",
}
_SPAN_ERROR_KEYS = {"seams.error.code": "code", "seams.error.status": "status"}
_RUN_ATTRIBUTES = ("seams.instance.id", "seams.process.iri", "seams.correlation_key")

_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+")
_UNIVERSE = re.compile(r"VALUES \(\?process \?node\) \{ \}")

#: A carried step: row key -> string value; ``error`` holds ``{"code", "status"}``.
_Carried = dict[str, object]


@dataclass(frozen=True)
class ObservedRun:
    """One recorded process instance: its id, its trace rows in order, and the
    process and correlation key when the source names them."""

    instance: str
    rows: Sequence[Mapping[str, object]]
    process: str | None = None
    correlation_key: str | None = None


@dataclass(frozen=True)
class _Normalised:
    instance: str
    process: str | None
    correlation_key: str | None
    steps: tuple[_Carried, ...]


def _where(run: str, index: int) -> str:
    return f"run {run} row {index}"


def _iri(value: object, where: str, key: str) -> str:
    if not isinstance(value, str) or not _IRI.fullmatch(value):
        raise ResolutionError(where, key, f"expected an IRI string, got {value!r}")
    return value


def _string(value: object, where: str, key: str) -> str:
    if not isinstance(value, str):
        raise ResolutionError(where, key, f"expected a string, got {value!r}")
    return value


def _step(row: object, where: str) -> _Carried:
    """The carried keys of one trace row, validated (ADR-0042 section 1)."""
    if not isinstance(row, Mapping):
        raise ResolutionError(where, "obs:Step", f"a trace row must be a JSON object, got {row!r}")
    raw = cast(Mapping[str, object], row)
    step: _Carried = {}
    for key in _IRI_KEYS:
        if key != "channel" and raw.get(key) is not None:
            step[key] = _iri(raw[key], where, key)
    for key in _STRING_KEYS:
        if raw.get(key) is not None:
            step[key] = _string(raw[key], where, key)
    channels: list[str] = []
    if raw.get("channel") is not None:
        channels.append(_iri(raw["channel"], where, "channel"))
    for key in ("published", "streamed"):
        sent = raw.get(key)
        if sent is None:
            continue
        if not isinstance(sent, Mapping):
            raise ResolutionError(where, key, f"expected an object, got {sent!r}")
        channel = cast(Mapping[str, object], sent).get("channel")
        if channel is not None:
            channels.append(_iri(channel, where, f"{key}.channel"))
    if len(set(channels)) > 1:
        raise ResolutionError(where, "channel", f"names more than one channel: {sorted(set(channels))}")
    if channels:
        step["channel"] = channels[0]
    error = raw.get("error")
    if error is not None:
        if not isinstance(error, Mapping):
            raise ResolutionError(where, "error", f"expected an object, got {error!r}")
        err = cast(Mapping[str, object], error)
        carried: dict[str, str] = {}
        code = err.get("code")
        if code is not None:
            if isinstance(code, bool) or not isinstance(code, (str, int)):
                raise ResolutionError(where, "error.code", f"expected a string, got {code!r}")
            carried["code"] = str(code)
        if err.get("status") is not None:
            carried["status"] = _iri(err["status"], where, "error.status")
        if carried:
            step["error"] = carried
    return step


def _normalise(run: ObservedRun | tuple[str, Sequence[Mapping[str, object]]]) -> _Normalised:
    if isinstance(run, ObservedRun):
        found = run
    else:
        if not isinstance(run, tuple) or len(run) != 2:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ResolutionError(repr(run), "obs:Run", "expected an ObservedRun or a (run id, rows) pair")
        found = ObservedRun(run[0], run[1])
    instance = found.instance
    if not isinstance(instance, str) or not instance:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ResolutionError(repr(instance), "obs:instance", "a run id must be a non-empty string")
    rows = cast(object, found.rows)
    if not isinstance(rows, (list, tuple)):
        raise ResolutionError(f"run {instance}", "obs:step", f"the rows must be a list, got {type(rows).__name__}")
    process = None if found.process is None else _iri(found.process, f"run {instance}", "obs:process")
    key = found.correlation_key
    if key is not None:
        _string(key, f"run {instance}", "obs:correlationKey")
    steps = tuple(_step(row, _where(instance, i)) for i, row in enumerate(cast("list[object]", rows)))
    return _Normalised(instance, process, key, steps)


def _canonical(runs: Sequence[_Normalised]) -> bytes:
    data = [
        {"instance": r.instance, "process": r.process, "correlation_key": r.correlation_key, "steps": list(r.steps)}
        for r in runs
    ]
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def observed_graph(runs: Iterable[ObservedRun | tuple[str, Sequence[Mapping[str, object]]]]) -> Graph:
    """The as-observed graph of ``runs`` (module docstring). Two runs with the
    same id, a row that is not an object, or a value of the wrong JSON type
    raise ``ResolutionError`` naming the run and row."""
    found = sorted((_normalise(r) for r in runs), key=lambda r: r.instance)
    for a, b in zip(found, found[1:], strict=False):
        if a.instance == b.instance:
            raise ResolutionError(f"run {a.instance}", "obs:instance", "is given twice; load each run once")
    digest = hashlib.sha256(_canonical(found)).hexdigest()
    graph = Graph(identifier=URIRef(GRAPH_PREFIX + digest))
    graph.bind("obs", OBS)
    for run in found:
        subject = URIRef(f"{GRAPH_PREFIX}run:{quote(run.instance, safe='')}")
        graph.add((subject, RDF.type, OBS.Run))
        graph.add((subject, OBS.instance, Literal(run.instance)))
        if run.process is not None:
            graph.add((subject, OBS.process, URIRef(run.process)))
        if run.correlation_key is not None:
            graph.add((subject, OBS.correlationKey, Literal(run.correlation_key)))
        for index, step in enumerate(run.steps):
            node = URIRef(f"{subject}:step:{index}")
            graph.add((subject, OBS.step, node))
            graph.add((node, RDF.type, OBS.Step))
            graph.add((node, OBS["index"], Literal(index, datatype=XSD.integer)))
            for key, prop in _IRI_KEYS.items():
                if key in step:
                    graph.add((node, prop, URIRef(cast(str, step[key]))))
            for key, prop in _STRING_KEYS.items():
                if key in step:
                    graph.add((node, prop, Literal(cast(str, step[key]))))
            error = cast("dict[str, str]", step.get("error", {}))
            if "code" in error:
                graph.add((node, OBS.errorCode, Literal(error["code"])))
            if "status" in error:
                graph.add((node, OBS.errorStatus, URIRef(error["status"])))
    return graph


def observed_ntriples(graph: Graph) -> str:
    """``graph`` as N-Triples, one triple per line, lines sorted: the same
    runs give the same text."""
    text = graph.serialize(format="nt")
    lines = sorted(line for line in text.splitlines() if line.strip())
    return "".join(f"{line}\n" for line in lines)


# --- OTLP JSON spans -------------------------------------------------------


def _list(value: object, where: str, key: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ResolutionError(where, key, f"expected a list, got {type(value).__name__}")
    return cast("list[object]", value)


def _object(value: object, where: str, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResolutionError(where, key, f"expected an object, got {value!r}")
    return cast(Mapping[str, object], value)


def _attributes(span: Mapping[str, object], where: str) -> dict[str, object]:
    """The span's attributes, key -> the JSON value (``stringValue`` and the rest)."""
    out: dict[str, object] = {}
    for attr in _list(span.get("attributes"), where, "attributes"):
        entry = _object(attr, where, "attributes[]")
        key = entry.get("key")
        if not isinstance(key, str):
            raise ResolutionError(where, "attributes[].key", f"expected a string, got {key!r}")
        out[key] = _object(entry.get("value"), where, f"attribute {key}")
    return out


def _attr_string(attrs: Mapping[str, object], key: str, where: str) -> str | None:
    value = attrs.get(key)
    if value is None:
        return None
    text = cast(Mapping[str, object], value).get("stringValue")
    if not isinstance(text, str):
        raise ResolutionError(where, key, f"expected a stringValue, got {value!r}")
    return text


def _requests(otlp_json: object) -> list[object]:
    if isinstance(otlp_json, (str, bytes)):
        text = otlp_json.decode("utf-8") if isinstance(otlp_json, bytes) else otlp_json
        try:
            return [json.loads(text)]
        except ValueError:
            pass
        try:  # a collector's file exporter writes one export request per line
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError as exc:
            raise ResolutionError("OTLP JSON", "resourceSpans", f"is neither JSON nor JSON lines: {exc}") from exc
    if isinstance(otlp_json, list):
        return cast("list[object]", otlp_json)
    return [otlp_json]


def _start(span: Mapping[str, object], where: str) -> int:
    value = span.get("startTimeUnixNano", 0)
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise ResolutionError(where, "startTimeUnixNano", f"expected a non-negative integer, got {value!r}")
    return int(value)


def spans_to_runs(otlp_json: object) -> list[ObservedRun]:
    """The runs in an OTLP/JSON span export (ADR-0042 section 3), sorted by
    instance id: ``otlp_json`` is an export request (a dict with
    ``resourceSpans``), a list of them, or their JSON or JSON-lines text.

    An element span (one with ``bpmn.id`` or ``seams.element.iri``) is one
    step of the run its ``seams.instance.id`` names, ordered by
    ``startTimeUnixNano`` then ``spanId``; every other span is skipped. A
    run's process and correlation key come from ``seams.process.iri`` and
    ``seams.correlation_key``. A document that is not OTLP JSON, an element
    span with no ``seams.instance.id``, a non-string mapped attribute or
    spans of one run naming two processes raise ``ResolutionError`` naming
    the span."""
    spans: dict[str, list[tuple[int, str, _Carried]]] = {}
    facts: dict[str, dict[str, tuple[str, str]]] = {}
    for r, request in enumerate(_requests(otlp_json)):
        doc = _object(request, f"OTLP JSON request {r}", "resourceSpans")
        if "resourceSpans" not in doc:
            raise ResolutionError(f"OTLP JSON request {r}", "resourceSpans", "is not an OTLP JSON export request")
        for resource in _list(doc["resourceSpans"], f"OTLP JSON request {r}", "resourceSpans"):
            res = _object(resource, f"OTLP JSON request {r}", "resourceSpans[]")
            for scope in _list(res.get("scopeSpans"), f"OTLP JSON request {r}", "scopeSpans"):
                sc = _object(scope, f"OTLP JSON request {r}", "scopeSpans[]")
                for raw in _list(sc.get("spans"), f"OTLP JSON request {r}", "spans"):
                    span = _object(raw, f"OTLP JSON request {r}", "spans[]")
                    span_id = span.get("spanId", "")
                    where = f"span {span_id} ({span.get('name', '?')})"
                    attrs = _attributes(span, where)
                    if "bpmn.id" not in attrs and "seams.element.iri" not in attrs:
                        continue
                    instance = _attr_string(attrs, "seams.instance.id", where)
                    if not instance:
                        raise ResolutionError(where, "seams.instance.id", "an element span must name its instance")
                    row: _Carried = {}
                    for attr, key in _SPAN_KEYS.items():
                        value = _attr_string(attrs, attr, where)
                        if value is not None:
                            row[key] = value
                    error = {k: v for a, k in _SPAN_ERROR_KEYS.items() if (v := _attr_string(attrs, a, where))}
                    if error:
                        row["error"] = error
                    run_facts = facts.setdefault(instance, {})
                    for attr in _RUN_ATTRIBUTES[1:]:
                        value = _attr_string(attrs, attr, where)
                        if value is None:
                            continue
                        seen = run_facts.setdefault(attr, (value, where))
                        if seen[0] != value:
                            raise ResolutionError(
                                where, attr, f"run {instance} has {seen[0]!r} on {seen[1]} and {value!r} here"
                            )
                    spans.setdefault(instance, []).append((_start(span, where), str(span_id), row))
    runs: list[ObservedRun] = []
    for instance in sorted(spans):
        ordered = [row for _, _, row in sorted(spans[instance], key=lambda s: (s[0], s[1]))]
        run_facts = facts.get(instance, {})
        process = run_facts.get("seams.process.iri")
        key = run_facts.get("seams.correlation_key")
        runs.append(
            ObservedRun(
                instance,
                ordered,
                None if process is None else process[0],
                None if key is None else key[0],
            )
        )
    return runs


# --- the questions ---------------------------------------------------------


def _universe(model: Model) -> str:
    """The VALUES rows of every (process, flow node) pair, sorted."""
    pairs = sorted({(p.iri, n.iri) for p in model.processes for n in p.nodes()}, key=lambda t: (str(t[0]), str(t[1])))
    return " ".join(f"({p.n3()} {n.n3()})" for p, n in pairs)


def observed_question(model: Model, graph: Graph, name: str) -> list[Row]:
    """The rows of observed question ``name`` (``OBSERVED_QUESTIONS``) over
    ``model`` and the as-observed ``graph``, in the query's ORDER BY. The
    union is read-only and discarded; neither ``model.ds`` nor ``graph``
    changes. An unknown name raises KeyError."""
    if name not in OBSERVED_QUESTIONS:
        raise KeyError(f"unknown observed question {name!r}; available: {', '.join(OBSERVED_QUESTIONS)}")
    text = (resources.files("seams") / "queries" / "observed" / f"{name}.rq").read_text(encoding="utf-8")
    universe = _universe(model)
    query = _UNIVERSE.sub(lambda _: f"VALUES (?process ?node) {{ {universe} }}", text)
    union = ReadOnlyGraphAggregate([*model.ds.graphs(), graph])
    result = union.query(prepareQuery(query, initNs={**PREFIXES, "obs": OBS}))
    out: list[Row] = []
    for row in result:
        if isinstance(row, ResultRow):
            out.append({str(k): cast(Node, v) for k, v in row.asdict().items()})
    return out
