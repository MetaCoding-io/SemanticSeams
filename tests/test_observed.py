"""seams.observed: the as-observed named graph and its two questions (ADR-0042)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import seams
from rdflib import RDF, Graph, Literal, URIRef
from seams import NFR, OBS, ObservedRun, ResolutionError, observed_graph, observed_ntriples, observed_question

from seams_runtime.telemetry import element_attributes

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples" / "chat-app" / "chat-app.trig"
TRACE = json.loads((ROOT / "tests" / "fixtures" / "traces" / "chat_send_message.json").read_text(encoding="utf-8"))
ROWS: list[dict[str, object]] = TRACE["trace"]
PROCESS = "https://example.org/chat/send_message_process"
BPMN = "https://example.org/chat/chat_bpmn#"


@pytest.fixture(scope="module")
def model() -> seams.Model:
    return seams.load(CHAT)


def _strs(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    return [{k: str(v) for k, v in row.items()} for row in rows]


def test_graph_holds_one_run_and_a_step_per_row() -> None:
    graph = observed_graph([("run-1", ROWS)])
    assert str(graph.identifier).startswith("urn:seams:observed:")
    run = URIRef("urn:seams:observed:run:run-1")
    assert (run, RDF.type, OBS.Run) in graph
    steps = sorted(graph.objects(run, OBS.step), key=lambda s: int(str(graph.value(s, OBS["index"]))))
    assert [str(graph.value(s, OBS.reached)) for s in steps] == [str(r["iri"]) for r in ROWS]
    assert [str(graph.value(s, OBS.bpmnId)) for s in steps] == [str(r["task"]) for r in ROWS]
    invoke = steps[3]
    assert graph.value(invoke, OBS.channel) == URIRef("https://example.org/chat/stream_events")  # from streamed
    assert graph.value(invoke, OBS.fires) == URIRef("https://example.org/chat/t_stream")
    assert str(graph.value(invoke, OBS.implementation)) == "LLMCompletion"
    assert graph.value(steps[5], OBS.channel) == URIRef("https://example.org/chat/stream_events")  # from published
    assert graph.value(steps[2], OBS.decision) == URIRef("https://example.org/chat/routing_decision")
    # payload values are not carried
    assert not any("default-provider" in str(o) for o in graph.objects())


def test_dead_model_is_empty_when_the_run_reached_every_node(model: seams.Model) -> None:
    assert observed_question(model, observed_graph([("run-1", ROWS)]), "dead-model") == []


def test_dead_model_lists_the_nodes_no_run_reached_sorted(model: seams.Model) -> None:
    graph = observed_graph([("partial", ROWS[:3])])
    rows = _strs(observed_question(model, graph, "dead-model"))
    reached = {str(r["iri"]) for r in ROWS[:3]}
    expected = sorted(str(r["iri"]) for r in ROWS if str(r["iri"]) not in reached)
    assert [r["node"] for r in rows] == expected
    assert {r["process"] for r in rows} == {PROCESS}


def test_dead_model_reports_an_unreached_process_whole(model: seams.Model) -> None:
    rows = _strs(observed_question(model, observed_graph([]), "dead-model"))
    assert [r["node"] for r in rows] == sorted(str(r["iri"]) for r in ROWS)


def test_conformance_is_empty_for_a_run_the_model_explains(model: seams.Model) -> None:
    graph = observed_graph([ObservedRun("run-1", ROWS, process=PROCESS, correlation_key="k")])
    assert observed_question(model, graph, "conformance") == []


def test_conformance_flags_unknown_element_unmapped_step_and_unknown_process(model: seams.Model) -> None:
    rows = [ROWS[0], {"task": "ghost", "iri": f"{BPMN}ghost"}, {"task": "nowhere"}]
    graph = observed_graph(
        [ObservedRun("a", rows), ObservedRun("b", [ROWS[0]], process="https://example.org/chat/no_such_process")]
    )
    found = _strs(observed_question(model, graph, "conformance"))
    assert [(r["run"].rsplit(":", 1)[-1], r["index"], r["reason"], r.get("reached")) for r in found] == [
        ("a", "1", "unknown-element", f"{BPMN}ghost"),
        ("a", "2", "unmapped", None),
        ("b", "0", "unknown-process", str(ROWS[0]["iri"])),
    ]


def test_model_hash_and_dataset_are_untouched(model: seams.Model) -> None:
    before_hash = seams.model_hash(CHAT)
    before = (model.hash, len(model.ds), sorted(str(g.identifier) for g in model.ds.graphs()))
    graph = observed_graph([("run-1", ROWS)])
    for name in seams.OBSERVED_QUESTIONS:
        observed_question(model, graph, name)
    assert (model.hash, len(model.ds), sorted(str(g.identifier) for g in model.ds.graphs())) == before
    assert seams.model_hash(CHAT) == before_hash == model.hash
    assert graph.identifier not in {g.identifier for g in model.ds.graphs()}


def test_same_runs_give_the_same_iri_and_bytes_in_any_order() -> None:
    runs: list[tuple[str, list[dict[str, object]]]] = [("run-1", ROWS), ("run-2", ROWS[:2])]
    one, two = observed_graph(runs), observed_graph(list(reversed(runs)))
    assert one.identifier == two.identifier
    text = observed_ntriples(one)
    assert text == observed_ntriples(two)
    lines = text.splitlines()
    assert lines == sorted(lines) and len(lines) == len(one)
    assert observed_graph([("run-1", ROWS)]).identifier != one.identifier


def test_run_ids_are_percent_encoded() -> None:
    graph = observed_graph([("trace file/a b.json", ROWS[:1])])
    assert URIRef("urn:seams:observed:run:trace%20file%2Fa%20b.json") in set(graph.subjects(RDF.type, OBS.Run))


def _otlp(rows: list[dict[str, object]], instance: str = "run-1") -> dict[str, object]:
    """An OTLP JSON export request with an instance span and one element span per row, reversed."""

    def attrs(values: dict[str, object]) -> list[dict[str, object]]:
        return [{"key": k, "value": {"stringValue": str(v)}} for k, v in values.items()]

    run = {"seams.process.iri": PROCESS, "seams.instance.id": instance, "seams.correlation_key": "k"}
    spans: list[dict[str, object]] = [
        {"spanId": "00", "name": "seams.instance", "startTimeUnixNano": "1", "attributes": attrs(run)}
    ]
    for i, row in enumerate(rows):
        spans.append(
            {
                "spanId": f"s{i:02d}",
                "name": f"seams.element {row['task']}",
                "startTimeUnixNano": str(100 + i),
                "attributes": attrs({**run, **element_attributes(row)}),
            }
        )
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(reversed(spans))}]}]}


def test_spans_give_the_same_steps_as_the_trace() -> None:
    (run,) = seams.spans_to_runs(_otlp(ROWS))
    assert (run.instance, run.process, run.correlation_key) == ("run-1", PROCESS, "k")
    from_spans = observed_graph([ObservedRun(run.instance, run.rows)])
    assert observed_ntriples(from_spans) == observed_ntriples(observed_graph([("run-1", ROWS)]))


def test_spans_read_from_json_lines_text() -> None:
    text = json.dumps(_otlp(ROWS[:2], "a")) + "\n" + json.dumps(_otlp(ROWS[:1], "b")) + "\n"
    runs = seams.spans_to_runs(text)
    assert [(r.instance, len(r.rows)) for r in runs] == [("a", 2), ("b", 1)]


def test_error_rows_carry_code_and_status() -> None:
    row = {**ROWS[1], "error": {"code": 409, "status": "https://example.org/chat/conflict", "operation": "x"}}
    graph = observed_graph([("e", [row])])
    step = URIRef("urn:seams:observed:run:e:step:0")
    assert str(graph.value(step, OBS.errorCode)) == "409"
    assert graph.value(step, OBS.errorStatus) == URIRef("https://example.org/chat/conflict")
    (run,) = seams.spans_to_runs(_otlp([row], "e"))
    assert observed_ntriples(observed_graph([ObservedRun("e", run.rows)])) == observed_ntriples(graph)


# --- refused input ---------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "subject", "predicate"),
    [
        ([ROWS[0], "not a row"], "run r row 1", "obs:Step"),
        ([{**ROWS[1], "fires": 7}], "run r row 0", "fires"),
        ([{**ROWS[1], "iri": "not an iri"}], "run r row 0", "iri"),
        ([{**ROWS[1], "status": ["sending"]}], "run r row 0", "status"),
        ([{**ROWS[3], "streamed": "chan"}], "run r row 0", "streamed"),
        ([{**ROWS[1], "error": {"code": True}}], "run r row 0", "error.code"),
    ],
)
def test_malformed_rows_are_refused_naming_the_row(rows: list[object], subject: str, predicate: str) -> None:
    with pytest.raises(ResolutionError) as info:
        observed_graph([("r", rows)])  # type: ignore[list-item]
    assert (info.value.subject, info.value.predicate) == (subject, predicate)


def test_a_run_given_twice_or_without_id_is_refused() -> None:
    with pytest.raises(ResolutionError, match="given twice"):
        observed_graph([("r", ROWS), ("r", ROWS)])
    with pytest.raises(ResolutionError, match="non-empty string"):
        observed_graph([("", ROWS)])


def test_element_span_without_instance_is_refused_naming_the_span() -> None:
    doc = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "spanId": "abc",
                                "name": "seams.element start",
                                "attributes": [{"key": "bpmn.id", "value": {"stringValue": "start"}}],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    with pytest.raises(ResolutionError) as info:
        seams.spans_to_runs(doc)
    assert info.value.subject == "span abc (seams.element start)"
    assert info.value.predicate == "seams.instance.id"


def test_non_string_span_attribute_and_non_otlp_documents_are_refused() -> None:
    doc = _otlp(ROWS[:1])
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]  # type: ignore[index]
    spans[0]["attributes"].append({"key": "seams.status", "value": {"intValue": "3"}})  # type: ignore[index]
    with pytest.raises(ResolutionError) as info:
        seams.spans_to_runs(doc)
    assert info.value.predicate == "seams.status"
    with pytest.raises(ResolutionError, match="not an OTLP JSON export request"):
        seams.spans_to_runs({"trace": ROWS})
    with pytest.raises(ResolutionError, match="neither JSON nor JSON lines"):
        seams.spans_to_runs("{not json")


def test_spans_of_one_run_naming_two_processes_are_refused() -> None:
    doc = _otlp(ROWS[:2])
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]  # type: ignore[index]
    for attr in spans[0]["attributes"]:  # type: ignore[index]
        if attr["key"] == "seams.process.iri":
            attr["value"] = {"stringValue": "https://example.org/chat/other"}
    with pytest.raises(ResolutionError, match="has 'https://example.org/chat/"):
        seams.spans_to_runs(doc)


def test_unknown_question_is_a_key_error(model: seams.Model) -> None:
    with pytest.raises(KeyError, match="dead-model"):
        observed_question(model, observed_graph([]), "unfired")


# --- durations and latency budgets (ADR-0043) -------------------------------

OP = "https://example.org/chat/send_message_op"
NODE = f"{BPMN}invoke_llm"
EX = "https://example.org/chat/"


def _timed(rows: list[dict[str, object]], instance: str, millis: list[int]) -> dict[str, object]:
    """``_otlp`` with each element span ending ``millis[i]`` ms after it starts."""
    doc = _otlp(rows, instance)
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]  # type: ignore[index]
    elements = sorted((s for s in spans if s["spanId"] != "00"), key=lambda s: s["spanId"])  # type: ignore[index]
    for span, ms in zip(elements, millis, strict=True):
        span["endTimeUnixNano"] = str(int(span["startTimeUnixNano"]) + ms * 1_000_000)  # type: ignore[index]
    return doc


def _budgeted(budgets: list[tuple[str, str, object, object | None]]) -> seams.Model:
    """A fresh chat model with (name, element, max ms, percentile) budgets in its BPMN and architecture graphs."""
    fresh = seams.load(CHAT)
    graphs = {str(g.identifier): g for g in fresh.ds.graphs()}
    for name, element, bound, percentile in budgets:
        graph = graphs[
            "urn:seams:graph:model:chat_architecture" if element == OP else "urn:seams:graph:model:chat_bpmn"
        ]
        budget = URIRef(EX + name)
        graph.add((budget, RDF.type, NFR.LatencyBudget))
        graph.add((budget, NFR.budgetOf, URIRef(element)))
        graph.add((budget, NFR.maxMilliseconds, Literal(bound)))
        if percentile is not None:
            graph.add((budget, NFR.percentile, Literal(percentile)))
    return fresh


def _durations(runs: list[tuple[str, list[int]]]) -> Graph:
    """The as-observed graph of runs over ROWS, each element span lasting the given ms."""
    found = [r for instance, ms in runs for r in seams.spans_to_runs(_timed(ROWS, instance, ms))]
    return observed_graph(found)


def test_spans_carry_durations_as_decimal_milliseconds() -> None:
    doc = _otlp(ROWS[:2])
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]  # type: ignore[index]
    by_id = {s["spanId"]: s for s in spans}  # type: ignore[index]
    by_id["s00"]["endTimeUnixNano"] = str(100 + 1_500_000)
    by_id["s01"]["endTimeUnixNano"] = 101 + 2_000_000
    (run,) = seams.spans_to_runs(doc)
    assert [r.get("duration") for r in run.rows] == ["1.5", "2"]
    graph = observed_graph([run])
    step = URIRef("urn:seams:observed:run:run-1:step:0")
    value = graph.value(step, OBS.duration)
    assert isinstance(value, Literal) and str(value.datatype).endswith("XMLSchema#decimal") and str(value) == "1.5"


def test_trace_rows_carry_no_duration() -> None:
    graph = observed_graph([("run-1", ROWS)])
    assert list(graph.objects(None, OBS.duration)) == []


def test_budgets_met_and_missed_by_operation_and_flow_node() -> None:
    model = _budgeted([("op_fast", OP, 5, None), ("op_slow", OP, 2, None), ("node_ok", NODE, Decimal("4.0"), None)])
    graph = _durations([("a", [1, 3, 1, 4, 1, 1, 1])])
    results = seams.budget_results(model, graph)
    assert [(str(r.budget), str(r.element), r.verdict, r.observed_ms, r.samples) for r in results] == [
        (EX + "node_ok", NODE, "met", Decimal(4), 1),
        (EX + "op_fast", OP, "met", Decimal(3), 1),
        (EX + "op_slow", OP, "missed", Decimal(3), 1),
    ]
    assert results[2].max_ms == Decimal(2) and results[2].percentile == Decimal(100)


def test_budget_is_unobserved_from_trace_rows_or_unreached_elements() -> None:
    model = _budgeted([("op", OP, 5, None), ("ghost", f"{BPMN}ghost", 5, None)])
    for graph in (observed_graph([("run-1", ROWS)]), _durations([("a", [1] * 7)])):
        by_name = {str(r.budget): r for r in seams.budget_results(model, graph)}
        ghost = by_name[EX + "ghost"]
        assert (ghost.verdict, ghost.observed_ms, ghost.samples) == ("unobserved", None, 0)
    traced = {str(r.budget): r for r in seams.budget_results(model, observed_graph([("run-1", ROWS)]))}
    assert (traced[EX + "op"].verdict, traced[EX + "op"].samples) == ("unobserved", 0)


def test_percentile_50_and_100_differ_by_nearest_rank() -> None:
    model = _budgeted([("p50", NODE, 25, 50), ("p100", NODE, 25, None)])
    # invoke_llm (row 3) takes 10, 20, 30 and 40 ms over four runs
    graph = _durations([(f"r{i}", [1, 1, 1, ms, 1, 1, 1]) for i, ms in enumerate([40, 10, 30, 20])])
    results = {str(r.budget).rsplit("/", 1)[-1]: r for r in seams.budget_results(model, graph)}
    assert (results["p50"].observed_ms, results["p50"].verdict, results["p50"].samples) == (Decimal(20), "met", 4)
    assert (results["p100"].observed_ms, results["p100"].verdict) == (Decimal(40), "missed")


def test_budget_results_are_sorted_by_element_then_budget_and_leave_the_model_alone() -> None:
    model = _budgeted([("z", NODE, 5, None), ("a", OP, 5, None), ("b", NODE, 5, 90)])
    before = (model.hash, len(model.ds))
    graph = _durations([("a", [1] * 7)])
    size = len(graph)
    keys = [(str(r.element), str(r.budget)) for r in seams.budget_results(model, graph)]
    assert keys == sorted(keys) == [(NODE, EX + "b"), (NODE, EX + "z"), (OP, EX + "a")]
    assert seams.budget_results(model, graph) == seams.budget_results(model, graph)
    assert (model.hash, len(model.ds), len(graph)) == (*before, size)


def test_a_model_without_budgets_has_no_results(model: seams.Model) -> None:
    assert seams.budget_results(model, _durations([("a", [1] * 7)])) == []


@pytest.mark.parametrize(
    ("end", "predicate", "match"),
    [
        ("99", "endTimeUnixNano", "before startTimeUnixNano"),
        ("1.5", "endTimeUnixNano", "non-negative integer"),
        (True, "endTimeUnixNano", "non-negative integer"),
    ],
)
def test_bad_end_time_is_refused_naming_the_span(end: object, predicate: str, match: str) -> None:
    doc = _otlp(ROWS[:1])
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]  # type: ignore[index]
    spans[0]["endTimeUnixNano"] = end  # type: ignore[index]
    with pytest.raises(ResolutionError, match=match) as info:
        seams.spans_to_runs(doc)
    assert (info.value.subject, info.value.predicate) == ("span s00 (seams.element start)", predicate)


def test_end_time_without_a_start_is_refused() -> None:
    doc = _otlp(ROWS[:1])
    span = doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]  # type: ignore[index]
    del span["startTimeUnixNano"]  # type: ignore[union-attr]
    span["endTimeUnixNano"] = "5"  # type: ignore[index]
    with pytest.raises(ResolutionError) as info:
        seams.spans_to_runs(doc)
    assert info.value.predicate == "startTimeUnixNano"


@pytest.mark.parametrize("duration", [-1, "1e3", True, 1.5, "abc"])
def test_a_bad_row_duration_is_refused(duration: object) -> None:
    with pytest.raises(ResolutionError) as info:
        observed_graph([("r", [{**ROWS[1], "duration": duration}])])
    assert (info.value.subject, info.value.predicate) == ("run r row 0", "duration")


@pytest.mark.parametrize(
    ("bound", "percentile", "predicate"),
    [
        (0, None, "nfr:maxMilliseconds"),
        ("fast", None, "nfr:maxMilliseconds"),
        (5, 0, "nfr:percentile"),
        (5, 150, "nfr:percentile"),
    ],
)
def test_an_out_of_range_budget_is_refused_naming_the_predicate(
    bound: object, percentile: object, predicate: str
) -> None:
    model = _budgeted([("bad", NODE, bound, percentile)])
    with pytest.raises(ResolutionError) as info:
        seams.budget_results(model, observed_graph([]))
    assert (info.value.subject, info.value.predicate) == (EX + "bad", predicate)
