"""Pins the ADR-0007 spike's claims (spikes/adr0007/spike.py): graph-bound
DMN decisions without vendor extensions, streaming inside a service task, and
SQLite-persisted process state with a mid-flight restore."""

import re
import sqlite3
import sys
from pathlib import Path

import pytest
from rdflib import Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.adr0007 import spike  # noqa: E402

CHAT = "https://example.org/chat/"
ROUTE = spike.task_iri("route_to_provider")
SHORT = {"role": "user", "content": "Hello, which provider?"}
LONG = {"role": "user", "content": "x" * 4001}


@pytest.fixture
def graph():
    return spike.load_graph()


# (a) routing outcomes ---------------------------------------------------------

def test_short_message_routes_to_default_provider(tmp_path):
    assert spike.run(SHORT, tmp_path / "s.db").provider == "default-provider"


def test_long_user_message_routes_to_long_context_provider(tmp_path):
    result = spike.run(LONG, tmp_path / "s.db")
    assert result.provider == "long-context-provider"
    assert result.completed


def test_boundary_4000_chars_stays_on_default(tmp_path):
    msg = {"role": "user", "content": "x" * 4000}
    assert spike.run(msg, tmp_path / "s.db").provider == "default-provider"


def test_long_non_user_message_stays_on_default(tmp_path):
    msg = {"role": "system", "content": "x" * 5000}
    assert spike.run(msg, tmp_path / "s.db").provider == "default-provider"


# (b) binding comes from the graph --------------------------------------------

def test_resolver_binds_route_to_provider_to_routing_decision(graph):
    b = spike.decision_for(ROUTE, graph)
    assert b.decision_id == "routing_decision"
    assert b.decision_iri == CHAT + "routing_decision"
    assert b.model_iri == CHAT + "routing_dmn"
    assert b.dmn_path == spike.CHAT_DIR / "routing.dmn"


def test_altered_graph_rebinds_decision(graph, tmp_path):
    """Point seam:decidedBy at a different decision in a different DMN model:
    the task then evaluates that table, with no BPMN change at all."""
    src = (spike.CHAT_DIR / "routing.dmn").read_text()
    alt = re.sub(r'"(long-context|default)-provider"', '"graph-chosen-provider"', src)
    alt = alt.replace('id="routing_decision"', 'id="alt_decision"')
    alt_path = tmp_path / "alt.dmn"
    alt_path.write_text(alt)

    alt_decision, alt_model = URIRef(CHAT + "alt_decision"), URIRef(CHAT + "alt_dmn")
    graph.remove((ROUTE, spike.SEAM.decidedBy, None))
    graph.add((ROUTE, spike.SEAM.decidedBy, alt_decision))
    graph.add((alt_decision, spike.SEAM.inModel, alt_model))
    graph.add((alt_model, spike.SEAM.renderPayload, URIRef(alt_path.as_uri())))

    b = spike.decision_for(ROUTE, graph)
    assert (b.decision_id, b.dmn_path) == ("alt_decision", alt_path)
    result = spike.run(SHORT, tmp_path / "s.db", graph=graph)
    assert result.provider == "graph-chosen-provider"
    route_row = next(r for r in result.trace if r["task"] == "route_to_provider")
    assert route_row["resolved"] == str(alt_decision)


def test_parser_decision_ref_hook_uses_graph(graph):
    parser = spike.make_parser(graph)
    assert "routing_decision" in parser.get_dmn_dependencies()


# (c) no vendor extensions, sources untouched ---------------------------------

SOURCES = [spike.BPMN_FILE, spike.CHAT_DIR / "routing.dmn"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_has_no_vendor_namespace(path):
    text = path.read_text().lower()
    for vendor in ("camunda", "spiffworkflow", "zeebe"):
        assert vendor not in text, f"{path.name} mentions {vendor}"


def test_sources_unchanged_by_run(tmp_path):
    before = {p: p.read_bytes() for p in SOURCES}
    spike.run(LONG, tmp_path / "s.db")
    assert {p: p.read_bytes() for p in SOURCES} == before


def test_bpmn_process_is_executable():
    assert 'isExecutable="true"' in spike.BPMN_FILE.read_text()


# (d) streaming ----------------------------------------------------------------

def test_stream_events_in_token_order_before_completion(tmp_path):
    result = spike.run(SHORT, tmp_path / "s.db")
    tokens = [e for e in result.events if "token" in e]
    assert tokens, "no token events published"
    assert {e["channel"] for e in result.events} == {"stream.events"}
    assert [e["seq"] for e in result.events] == list(range(len(result.events)))
    assert [e["token"] for e in tokens] == result.data["reply_tokens"]
    assert tokens[-1]["token"] == "<eos>"
    # invoke_llm is STARTED while every token is published, COMPLETED after the last
    assert {e["task_state"] for e in tokens} == {"STARTED"}
    assert result.task_states["invoke_llm"] == "COMPLETED"
    # the throw event publishes after the stream, on the same graph-resolved channel
    assert result.events[-1]["event"] == "stream_complete_event"
    llm_row = next(r for r in result.trace if r["task"] == "invoke_llm")
    assert llm_row["events"] == tokens


def test_channel_resolved_from_graph(graph):
    assert spike.channel_for("stream_complete_event", graph) == (CHAT + "stream_events", "stream.events")


# (e) SQLite round trip --------------------------------------------------------

def test_checkpoint_row_then_resume_matches_uninterrupted(tmp_path):
    db = tmp_path / "s.db"
    partial = spike.run(LONG, db, stop_after="route_to_provider")
    assert not partial.completed
    assert partial.checkpoint["after"] == "route_to_provider"

    con = sqlite3.connect(db)
    rows = con.execute("SELECT instance_id, state FROM workflow_state").fetchall()
    con.close()
    assert [r[0] for r in rows] == [partial.instance_id]
    assert '"Provider": "long-context-provider"' in rows[0][1]

    resumed = spike.resume(partial.instance_id, db)
    assert resumed.completed
    assert [r["task"] for r in resumed.trace] == [
        "invoke_llm", "persist_response", "stream_complete_event", "end"]

    baseline = spike.run(LONG, tmp_path / "b.db", restore=False)
    assert baseline.checkpoint is None
    assert resumed.data == baseline.data
    assert spike.run(LONG, tmp_path / "f.db").data == baseline.data


def test_resume_unknown_instance_fails(tmp_path):
    with pytest.raises(LookupError, match="no-such-id"):
        spike.resume("no-such-id", tmp_path / "s.db")


# (f) negative resolution ------------------------------------------------------

def test_missing_decided_by_names_task_iri(graph):
    graph.remove((ROUTE, spike.SEAM.decidedBy, None))
    with pytest.raises(spike.ResolutionError) as exc:
        spike.decision_for(ROUTE, graph)
    assert str(ROUTE) in str(exc.value)
    assert str(spike.SEAM.decidedBy) in str(exc.value)


def test_missing_decided_by_fails_parse(graph):
    graph.remove((ROUTE, spike.SEAM.decidedBy, None))
    with pytest.raises(spike.ResolutionError, match=re.escape(str(ROUTE))):
        spike.make_parser(graph)


def test_missing_render_payload_named(graph):
    graph.remove((URIRef(CHAT + "routing_dmn"), spike.SEAM.renderPayload, None))
    with pytest.raises(spike.ResolutionError) as exc:
        spike.decision_for(ROUTE, graph)
    assert str(spike.SEAM.renderPayload) in str(exc.value)
    assert str(ROUTE) in str(exc.value)


def test_decision_local_name_absent_from_dmn(graph):
    bogus = URIRef(CHAT + "no_such_decision")
    graph.remove((ROUTE, spike.SEAM.decidedBy, None))
    graph.add((ROUTE, spike.SEAM.decidedBy, bogus))
    graph.add((bogus, spike.SEAM.inModel, URIRef(CHAT + "routing_dmn")))
    with pytest.raises(spike.ResolutionError, match="no_such_decision"):
        spike.decision_for(ROUTE, graph)


def test_service_task_wiring_checked_against_graph(graph):
    graph.remove((spike.task_iri("invoke_llm"), spike.SEAM.invokes, None))
    with pytest.raises(spike.ResolutionError, match="invoke_llm"):
        spike.Worker(graph)
