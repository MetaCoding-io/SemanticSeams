"""The viewer's observed Questions (M032/S01, ADR-0042).

SEAMS_OBSERVED names recorded runs (trace JSON files, OTLP span files, runtime
SQLite stores); viewer.app loads them once as an as-observed graph and offers
"dead-model", "observed-conformance" and "latency-budgets" (M032/S02,
ADR-0043) on a proc:Process. Without them the
questions do not apply: no button, no catalog entry, a 404 naming why.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from seams_runtime.telemetry import element_attributes
from viewer import app as viewer_app
from viewer import queries, validation

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "tests" / "fixtures" / "traces" / "chat_send_message.json"
ROWS: list[dict[str, object]] = json.loads(TRACE.read_text(encoding="utf-8"))["trace"]
CHAT = "https://example.org/chat/"
BPMN = CHAT + "chat_bpmn#"
PROCESS = CHAT + "send_message_process"
CHAT_BPMN = CHAT + "chat_bpmn"
HX = {"hx-request": "true"}


@pytest.fixture(autouse=True)
def restore_viewer(monkeypatch):
    """Each test sets its own SEAMS_OBSERVED; the viewer forgets it afterwards."""
    original = viewer_app.MODEL_PATH
    monkeypatch.delenv(viewer_app.OBSERVED_ENV, raising=False)
    validation._clear_cache()
    viewer_app.reset_observed()
    yield
    viewer_app.configure(original)


def _open(monkeypatch, *sources: Path) -> TestClient:
    if sources:
        monkeypatch.setenv(viewer_app.OBSERVED_ENV, os.pathsep.join(str(s) for s in sources))
    viewer_app.reset_observed()
    return TestClient(viewer_app.app)


def _trace(tmp_path: Path, name: str, rows: list[dict[str, object]], instance: str | None = None) -> Path:
    data: dict[str, object] = {"trace": rows}
    if instance is not None:
        data["instance"] = instance
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _url(name: str, focus: str) -> str:
    return f"/queries/{name}/{quote(focus, safe='')}"


def _buttons(client: TestClient) -> list[str]:
    html = client.get(f"/view/{quote(CHAT_BPMN, safe='')}", headers=HX).text
    return [q for q in queries.OBSERVED_ANSWERS if f'data-query-name="{q}"' in html]


# --- without observations ----------------------------------------------------


def test_without_observations_the_questions_do_not_apply(monkeypatch):
    client = _open(monkeypatch)
    assert viewer_app.get_observed() is None
    assert _buttons(client) == []
    names = [entry["name"] for entry in client.get("/queries").json()]
    assert "dead-model" not in names and "observed-conformance" not in names
    resp = client.get(_url("dead-model", PROCESS))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "canned query dead-model needs recorded runs: SEAMS_OBSERVED is not set"
    graph = viewer_app.get_graph()
    assert not queries.is_applicable(graph, PROCESS, queries.QUERIES["dead-model"])


def test_execute_query_refuses_an_observed_question_without_observations():
    with pytest.raises(ValueError, match="needs the model and observations"):
        queries.execute_query(viewer_app.get_graph(), "dead-model", PROCESS, model=viewer_app.get_model())


# --- with observations -------------------------------------------------------


def test_a_partial_run_leaves_the_unreached_nodes_dead(monkeypatch, tmp_path):
    client = _open(monkeypatch, _trace(tmp_path, "partial.json", ROWS[:3], "p"))
    assert _buttons(client) == ["dead-model", "observed-conformance", "latency-budgets"]
    names = [entry["name"] for entry in client.get("/queries").json()]
    assert names[-3:] == ["dead-model", "observed-conformance", "latency-budgets"]
    body = client.get(_url("dead-model", PROCESS)).json()
    assert body["columns"] == ["node", "process"]
    assert body["bindings"] == {"process": PROCESS}
    nodes = [r["node"] for r in body["rows"]]
    assert nodes == sorted(nodes)
    assert set(nodes) >= {str(r["iri"]) for r in ROWS[3:]}
    assert not set(nodes) & {str(r["iri"]) for r in ROWS[:3]}
    assert {r["process"] for r in body["rows"]} == {PROCESS}
    assert client.get(_url("observed-conformance", PROCESS)).json()["rows"] == []


def test_a_full_run_reaches_every_node_of_its_path(monkeypatch):
    client = _open(monkeypatch, TRACE)
    nodes = [r["node"] for r in client.get(_url("dead-model", PROCESS)).json()["rows"]]
    assert not set(nodes) & {str(r["iri"]) for r in ROWS}


def test_runs_from_several_sources_are_one_graph(monkeypatch, tmp_path):
    first = _trace(tmp_path, "a.json", ROWS[:3], "a")
    second = _trace(tmp_path, "b.json", ROWS[3:], "b")
    whole = [r["node"] for r in _open(monkeypatch, TRACE).get(_url("dead-model", PROCESS)).json()["rows"]]
    split = [r["node"] for r in _open(monkeypatch, first, second).get(_url("dead-model", PROCESS)).json()["rows"]]
    assert split == whole


def test_conformance_names_unknown_and_unmapped_steps(monkeypatch, tmp_path):
    rows = [*ROWS[:3], {"task": "ghost", "iri": BPMN + "ghost"}, {"task": "x"}]
    client = _open(monkeypatch, _trace(tmp_path, "odd.json", rows, "odd"))
    body = client.get(_url("observed-conformance", PROCESS)).json()
    assert body["columns"] == ["run", "index", "reached", "reason"]
    assert body["rows"] == [
        {"run": "odd", "index": "3", "reached": BPMN + "ghost", "reason": "unknown-element"},
        {"run": "odd", "index": "4", "reached": "", "reason": "unmapped"},
    ]
    html = client.get(_url("observed-conformance", PROCESS), headers=HX).text
    assert "unknown-element" in html and "unmapped" in html


def test_a_bare_trace_list_is_named_by_its_file(monkeypatch, tmp_path):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps([{"task": "ghost", "iri": BPMN + "ghost"}]), encoding="utf-8")
    rows = _open(monkeypatch, path).get(_url("observed-conformance", PROCESS)).json()["rows"]
    assert [r["run"] for r in rows] == ["bare.json"]


def test_a_store_loads_every_instance(monkeypatch, tmp_path):
    store = tmp_path / "seams.sqlite"
    with sqlite3.connect(store) as con:
        con.execute("CREATE TABLE workflow_state (instance_id TEXT PRIMARY KEY, state TEXT)")
        for instance, rows in (("i2", ROWS[3:]), ("i1", [*ROWS[:3], {"task": "x"}])):
            state = json.dumps({"data": {"seams": {"trace": rows}}})
            con.execute("INSERT INTO workflow_state VALUES (?, ?)", (instance, state))
    con.close()
    client = _open(monkeypatch, store)
    rows = client.get(_url("observed-conformance", PROCESS)).json()["rows"]
    assert rows == [{"run": "i1", "index": "3", "reached": "", "reason": "unmapped"}]
    whole = [r["node"] for r in _open(monkeypatch, TRACE).get(_url("dead-model", PROCESS)).json()["rows"]]
    assert [r["node"] for r in _open(monkeypatch, store).get(_url("dead-model", PROCESS)).json()["rows"]] == whole


def test_an_otlp_span_file_loads_as_runs(monkeypatch, tmp_path):
    spans = [
        {
            "spanId": f"s{i:02d}",
            "startTimeUnixNano": str(100 + i),
            "attributes": [
                {"key": k, "value": {"stringValue": v}}
                for k, v in {
                    "seams.instance.id": "span-run",
                    "seams.process.iri": PROCESS,
                    "seams.element.iri": str(r["iri"]),
                }.items()
            ],
        }
        for i, r in enumerate(ROWS)
    ]
    path = tmp_path / "spans.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}), encoding="utf-8")
    whole = [r["node"] for r in _open(monkeypatch, TRACE).get(_url("dead-model", PROCESS)).json()["rows"]]
    client = _open(monkeypatch, path)
    assert [r["node"] for r in client.get(_url("dead-model", PROCESS)).json()["rows"]] == whole
    assert client.get(_url("observed-conformance", PROCESS)).json()["rows"] == []


def test_a_non_process_focus_gives_no_dead_nodes(monkeypatch):
    client = _open(monkeypatch, TRACE)
    assert client.get(_url("dead-model", CHAT + "db01")).json()["rows"] == []


def test_the_model_and_its_hash_do_not_change(monkeypatch, tmp_path):
    model = viewer_app.get_model()
    before, triples = model.hash, len(model.ds)
    client = _open(monkeypatch, _trace(tmp_path, "partial.json", ROWS[:3], "p"))
    client.get(_url("dead-model", PROCESS))
    client.get(_url("observed-conformance", PROCESS))
    assert viewer_app.get_model() is model
    assert (model.hash, len(model.ds)) == (before, triples)
    observed = viewer_app.get_observed()
    assert observed is not None
    assert observed.identifier not in {g.identifier for g in model.ds.graphs()}


def test_observations_load_once(monkeypatch, tmp_path):
    path = _trace(tmp_path, "partial.json", ROWS[:3], "p")
    _open(monkeypatch, path)
    first = viewer_app.get_observed()
    path.write_text(json.dumps({"instance": "p", "trace": ROWS}), encoding="utf-8")
    assert viewer_app.get_observed() is first


# --- failures ------------------------------------------------------------------


def _refused(client: TestClient) -> str:
    assert _buttons(client) == []
    resp = client.get(_url("dead-model", PROCESS))
    assert resp.status_code == 404
    return resp.json()["detail"]


def test_a_missing_source_is_named(monkeypatch, tmp_path):
    missing = tmp_path / "nope.json"
    detail = _refused(_open(monkeypatch, missing))
    assert (
        detail
        == f"canned query dead-model needs recorded runs: {missing}: observed: no such file (from SEAMS_OBSERVED)"
    )


def test_a_file_that_is_not_json_is_named(monkeypatch, tmp_path):
    path = tmp_path / "junk.json"
    path.write_text("not json", encoding="utf-8")
    detail = _refused(_open(monkeypatch, path))
    assert f"{path}: observed: is neither a SQLite store nor JSON" in detail


def test_a_malformed_row_is_named(monkeypatch, tmp_path):
    detail = _refused(_open(monkeypatch, _trace(tmp_path, "bad.json", [{"task": "t", "iri": 7}], "bad")))
    assert detail == (
        "canned query dead-model needs recorded runs:"
        " cannot resolve run bad row 0: missing iri (expected an IRI string, got 7)"
    )


def test_a_store_without_workflow_state_is_named(monkeypatch, tmp_path):
    store = tmp_path / "empty.sqlite"
    with sqlite3.connect(store) as con:
        con.execute("CREATE TABLE other (x)")
    con.close()
    detail = _refused(_open(monkeypatch, store))
    assert f"{store}: observed: cannot read workflow_state" in detail


def test_the_same_run_twice_is_refused(monkeypatch, tmp_path):
    a = _trace(tmp_path, "a.json", ROWS, "same")
    b = _trace(tmp_path, "b.json", ROWS, "same")
    assert "is given twice" in _refused(_open(monkeypatch, a, b))


# --- latency budgets (M032/S02, ADR-0043) -------------------------------------

OP = CHAT + "send_message_op"
NODE = BPMN + "invoke_llm"
BUDGETS = """
@prefix nfr: <https://w3id.org/seams/nfr#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:seams:graph:model:chat_architecture> {
    <https://example.org/chat/send_message_fast> a nfr:LatencyBudget ;
        nfr:budgetOf <https://example.org/chat/send_message_op> ; nfr:maxMilliseconds "2"^^xsd:decimal .
}
<urn:seams:graph:model:chat_bpmn> {
    <https://example.org/chat/llm_p50> a nfr:LatencyBudget ;
        nfr:budgetOf <https://example.org/chat/chat_bpmn#invoke_llm> ;
        nfr:maxMilliseconds "%s"^^xsd:decimal ; nfr:percentile "50"^^xsd:decimal .
}
"""


def _budgeted(tmp_path: Path, node_bound: str = "5") -> None:
    """Point the viewer at a scratch chat model declaring an operation and a flow-node budget."""
    project = tmp_path / "chat"
    shutil.copytree(ROOT / "examples" / "chat-app", project, ignore=shutil.ignore_patterns("generated"))
    trig = project / "chat-app.trig"
    trig.write_text(trig.read_text(encoding="utf-8") + BUDGETS % node_bound, encoding="utf-8")
    viewer_app.configure(trig)


def _timed_spans(tmp_path: Path, millis: list[int]) -> Path:
    """An OTLP span file of ROWS, span i lasting millis[i] ms."""
    spans = [
        {
            "spanId": f"s{i:02d}",
            "startTimeUnixNano": str(100 + i),
            "endTimeUnixNano": str(100 + i + ms * 1_000_000),
            "attributes": [
                {"key": k, "value": {"stringValue": v}}
                for k, v in {
                    "seams.instance.id": "timed",
                    "seams.process.iri": PROCESS,
                    **element_attributes(r),
                }.items()
            ],
        }
        for i, (r, ms) in enumerate(zip(ROWS, millis, strict=True))
    ]
    path = tmp_path / "timed.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}), encoding="utf-8")
    return path


def test_latency_budgets_render_met_and_missed_rows(monkeypatch, tmp_path):
    _budgeted(tmp_path)
    client = _open(monkeypatch, _timed_spans(tmp_path, [1, 4, 1, 3, 1, 1, 1]))
    body = client.get(_url("latency-budgets", PROCESS)).json()
    assert body["columns"] == ["budget", "element", "max_ms", "percentile", "observed_ms", "samples", "verdict"]
    assert body["rows"] == [
        {
            "budget": CHAT + "llm_p50",
            "element": NODE,
            "max_ms": "5",
            "percentile": "50",
            "observed_ms": "3",
            "samples": "1",
            "verdict": "met",
        },
        {
            "budget": CHAT + "send_message_fast",
            "element": OP,
            "max_ms": "2",
            "percentile": "100",
            "observed_ms": "4",
            "samples": "1",
            "verdict": "missed",
        },
    ]
    html = client.get(_url("latency-budgets", PROCESS), headers=HX).text
    assert "Which latency budgets do the recorded runs meet?" in html
    assert "met" in html and "missed" in html


def test_latency_budgets_from_trace_rows_are_unobserved(monkeypatch, tmp_path):
    _budgeted(tmp_path)
    rows = _open(monkeypatch, TRACE).get(_url("latency-budgets", PROCESS)).json()["rows"]
    assert [(r["verdict"], r["observed_ms"], r["samples"]) for r in rows] == [("unobserved", "", "0")] * 2


def test_the_chat_model_has_no_budgets(monkeypatch):
    assert _open(monkeypatch, TRACE).get(_url("latency-budgets", PROCESS)).json()["rows"] == []


def test_a_malformed_budget_is_named(monkeypatch, tmp_path):
    _budgeted(tmp_path, node_bound="0")
    resp = _open(monkeypatch, TRACE).get(_url("latency-budgets", PROCESS))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.startswith("canned query latency-budgets: ")
    assert CHAT + "llm_p50" in detail and "nfr:maxMilliseconds" in detail
