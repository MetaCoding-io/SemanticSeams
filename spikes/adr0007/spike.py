"""ADR-0007 spike: execute chat_process.bpmn + routing.dmn in SpiffWorkflow.

Throwaway evidence for ADR-0007's four open items; not production code.

Decision binding path taken: **parser hook, no derived copy.**
``GraphBoundBusinessRuleTaskParser`` subclasses SpiffWorkflow's
``bpmn.parser.TaskParser`` and is registered for ``bpmn:businessRuleTask`` in
``OVERRIDE_PARSER_CLASSES`` of a ``SpiffWorkflow.dmn.parser.BpmnDmnParser``
subclass. Its ``get_decision_ref`` (a static method in Spiff 3.2's own
Camunda/Spiff parsers, called on the *class* by
``BpmnDmnParser._find_dependencies``) is a classmethod that looks the task's
bpmn id up in the TriG graph (seam:decidedBy -> seam:inModel ->
seam:renderPayload). The DMN file the parser loads is also the graph-resolved
path. BPMN and DMN are parsed straight from disk, untouched; no vendor
extension attribute exists anywhere.

Join convention (vocabulary gap): the DMN decision id is the local name of the
dec:Decision IRI (``:routing_decision`` -> ``routing_decision``), checked
against the ids actually present in the DMN. ``:routing_decision`` is not a
fragment IRI into routing.dmn, so this join is a naming convention, not a
graph fact.

Service tasks: Spiff's stock ``ServiceTask`` spec returns ``None`` from its run
hook, which leaves the task STARTED. The spike's worker loop picks up STARTED
service tasks, dispatches them by bpmn id to handlers whose wiring is checked
against the graph (seam:invokes / seam:fires), and calls ``task.complete()``
when the handler finishes. For invoke_llm, that happens only after the last
token of the simulated stream has been published. Tokens go to the
comm:Channel that stream_complete_event seam:publishesTo
(``stream.events``). Using the stock specs keeps the default serializer config
valid for everything except the business-rule spec, which gets Spiff's
``BaseBusinessRuleTaskConverter``.

DMN outputs: routing.dmn's ``<output>`` has no ``name``. Spiff 3.2 falls back
to the ``label`` (``Provider``), so the source DMN needed no edit. The FEEL
``-`` wildcard is natively treated as "no input specification".

Persistence: after route_to_provider completes, the workflow is serialized
with ``BpmnWorkflowSerializer`` to JSON and stored in a stdlib sqlite3 table
``workflow_state(instance_id TEXT PRIMARY KEY, state TEXT)``. The in-memory
workflow is dropped, then restored from SQLite and run to the end event.

Run:  .venv/bin/python spikes/adr0007/spike.py [--db PATH] [--long]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree
from rdflib import RDF, RDFS, Dataset, Namespace, URIRef

from SpiffWorkflow.bpmn.parser.TaskParser import TaskParser
from SpiffWorkflow.bpmn.parser.util import full_tag
from SpiffWorkflow.bpmn.serializer import BpmnWorkflowSerializer
from SpiffWorkflow.bpmn.serializer.config import DEFAULT_CONFIG
from SpiffWorkflow.bpmn.serializer.default.task_spec import BpmnTaskSpecConverter
from SpiffWorkflow.bpmn.specs.defaults import ServiceTask
from SpiffWorkflow.bpmn.specs.mixins import BpmnSpecMixin
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.dmn.parser.BpmnDmnParser import BpmnDmnParser
from SpiffWorkflow.dmn.serializer import BaseBusinessRuleTaskConverter
from SpiffWorkflow.dmn.specs import BusinessRuleTaskMixin
from SpiffWorkflow.util.task import TaskState

ROOT = Path(__file__).resolve().parents[2]
CHAT_DIR = ROOT / "examples" / "chat-app"
TRIG = CHAT_DIR / "chat-app.trig"
BPMN_FILE = CHAT_DIR / "chat_process.bpmn"
PROCESS_ID = "send_message_process"
BPMN_NS = "https://example.org/chat/chat_bpmn#"

SEAM = Namespace("https://w3id.org/seams/seam#")
COMM = Namespace("https://w3id.org/seams/comm#")


class ResolutionError(LookupError):
    """A graph hop needed to bind a BPMN element is missing."""

    def __init__(self, subject, predicate, detail: str = ""):
        self.subject = str(subject)
        self.predicate = str(predicate)
        msg = f"cannot resolve {self.subject}: missing {self.predicate}"
        super().__init__(f"{msg} ({detail})" if detail else msg)


@dataclass(frozen=True)
class DecisionBinding:
    task_iri: str
    decision_iri: str
    model_iri: str
    dmn_path: Path
    decision_id: str


# ── graph access ────────────────────────────────────────────────────────────


def load_graph(path: Path = TRIG) -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(path), format="trig")
    return ds


def task_iri(bpmn_id: str) -> URIRef:
    return URIRef(BPMN_NS + bpmn_id)


def _local_name(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _payload_path(payload_iri: str) -> Path:
    parts = urlsplit(payload_iri)
    if parts.scheme == "file":
        return Path(unquote(parts.path))
    # Relative/other IRIs: resolve the last path segment against the model dir.
    return CHAT_DIR / unquote(parts.path).rsplit("/", 1)[-1]


def dmn_decision_ids(dmn_path: Path) -> list[str]:
    root = etree.parse(str(dmn_path)).getroot()
    return [el.get("id") for el in root.iter() if etree.QName(el).localname == "decision"]


def decision_for(iri, graph: Dataset) -> DecisionBinding:
    """task IRI -seam:decidedBy-> dec:Decision -seam:inModel-> model
    -seam:renderPayload-> DMN file; decision id = decision IRI local name."""
    iri = URIRef(str(iri))
    decision = graph.value(iri, SEAM.decidedBy)
    if decision is None:
        raise ResolutionError(iri, SEAM.decidedBy, "business-rule task has no decision")
    model = graph.value(decision, SEAM.inModel)
    if model is None:
        raise ResolutionError(decision, SEAM.inModel, f"via {iri}")
    payload = graph.value(model, SEAM.renderPayload)
    if payload is None:
        raise ResolutionError(model, SEAM.renderPayload, f"via {iri}")
    dmn_path = _payload_path(str(payload))
    if not dmn_path.is_file():
        raise ResolutionError(model, SEAM.renderPayload, f"payload {dmn_path} not found, via {iri}")
    decision_id = _local_name(str(decision))
    ids = dmn_decision_ids(dmn_path)
    if decision_id not in ids:
        raise ResolutionError(
            decision, SEAM.inModel,
            f"local name {decision_id!r} not among DMN decision ids {ids} in {dmn_path.name}, via {iri}",
        )
    return DecisionBinding(str(iri), str(decision), str(model), dmn_path, decision_id)


def channel_for(bpmn_id: str, graph: Dataset) -> tuple[str, str]:
    """(channel IRI, label) of the comm:Channel the element seam:publishesTo."""
    iri = task_iri(bpmn_id)
    for ch in graph.objects(iri, SEAM.publishesTo):
        if (ch, RDF.type, COMM.Channel) in graph:
            return str(ch), str(graph.value(ch, RDFS.label) or _local_name(str(ch)))
    raise ResolutionError(iri, SEAM.publishesTo, "no comm:Channel target")


# ── Spiff parser with graph-bound decision refs ─────────────────────────────


class BusinessRuleTask(BusinessRuleTaskMixin, BpmnSpecMixin):
    """Vendor-neutral business-rule spec (no camunda/spiff extensions)."""


class GraphBoundBusinessRuleTaskParser(TaskParser):
    graph: Dataset = None  # bound per parser by make_parser()

    @classmethod
    def binding(cls, node) -> DecisionBinding:
        return decision_for(task_iri(node.get("id")), cls.graph)

    @classmethod
    def get_decision_ref(cls, node) -> str:
        return cls.binding(node).decision_id

    def create_task(self):
        ref = self.get_decision_ref(self.node)
        engine = self.process_parser.parser.get_engine(ref, self.node)
        return self.spec_class(self.spec, self.bpmn_id, dmnEngine=engine, **self.bpmn_attributes)


class GraphBoundParser(BpmnDmnParser):
    OVERRIDE_PARSER_CLASSES = {}


def make_parser(graph: Dataset) -> GraphBoundParser:
    brt_parser = type(
        "BoundBusinessRuleTaskParser", (GraphBoundBusinessRuleTaskParser,), {"graph": graph}
    )
    parser_cls = type(
        "BoundGraphParser", (GraphBoundParser,),
        {"OVERRIDE_PARSER_CLASSES": {full_tag("businessRuleTask"): (brt_parser, BusinessRuleTask)}},
    )
    parser = parser_cls()
    # Load the DMN files the graph binds — not a glob, not an XML attribute.
    root = etree.parse(str(BPMN_FILE)).getroot()
    ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
    for node in root.xpath(".//bpmn:businessRuleTask", namespaces=ns):
        parser.add_dmn_file(str(brt_parser.binding(node).dmn_path))
    parser.add_bpmn_file(str(BPMN_FILE))
    return parser


def make_serializer() -> BpmnWorkflowSerializer:
    config = dict(DEFAULT_CONFIG)
    config[BusinessRuleTask] = BaseBusinessRuleTaskConverter
    # Spiff 3.2's DEFAULT_CONFIG has no entry for the plain bpmn ServiceTask
    # (only the spiff/camunda flavours register one); it has no extra state.
    config[ServiceTask] = BpmnTaskSpecConverter
    return BpmnWorkflowSerializer(BpmnWorkflowSerializer.configure(config))


# ── worker: service-task handlers chosen via the graph ──────────────────────


@dataclass
class Channel:
    iri: str
    label: str
    events: list = field(default_factory=list)

    def publish(self, event: dict):
        self.events.append(event)


EXPECTED_WIRING = {
    # bpmn id -> (predicate, expected local name) the handler is written for
    "persist_user_msg": (SEAM.invokes, "send_message_op"),
    "invoke_llm": (SEAM.invokes, "completion_op"),
    "persist_response": (SEAM.fires, "t_finish"),
}


def simulated_tokens(prompt: str, provider: str) -> list[str]:
    return [f"[{provider}]", "Echo:", *prompt.split()[:5], "<eos>"]


class Worker:
    def __init__(self, graph: Dataset):
        self.graph = graph
        ch_iri, ch_label = channel_for("stream_complete_event", graph)
        self.channel = Channel(ch_iri, ch_label)
        self.handlers = {
            "persist_user_msg": self.persist_user_msg,
            "invoke_llm": self.invoke_llm,
            "persist_response": self.persist_response,
        }
        for bpmn_id, (pred, local) in EXPECTED_WIRING.items():
            targets = [_local_name(str(o)) for o in graph.objects(task_iri(bpmn_id), pred)]
            if local not in targets:
                raise ResolutionError(task_iri(bpmn_id), pred, f"expected {local}, graph has {targets}")

    def handler_for(self, bpmn_id: str):
        if bpmn_id not in self.handlers:
            raise ResolutionError(task_iri(bpmn_id), SEAM.invokes, "no worker handler for service task")
        return self.handlers[bpmn_id]

    def persist_user_msg(self, task):
        msg = dict(task.data["message"])
        task.data["stored_user_message"] = {"id": "m-user-1", **msg}
        task.data["message_role"] = msg.get("role", "")
        task.data["message_length"] = len(msg.get("content", ""))

    def invoke_llm(self, task):
        provider = task.data["Provider"]
        tokens = simulated_tokens(task.data["message"].get("content", ""), provider)
        for seq, tok in enumerate(tokens):
            self.channel.publish({
                "channel": self.channel.label, "seq": seq, "token": tok,
                "task_state": TaskState.get_name(task.state),
            })
        task.data["reply_tokens"] = tokens

    def persist_response(self, task):
        task.data["stored_reply"] = {
            "id": "m-assistant-1", "role": "assistant",
            "content": " ".join(task.data["reply_tokens"]),
        }


# ── persistence ─────────────────────────────────────────────────────────────


def _db(db_path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS workflow_state(instance_id TEXT PRIMARY KEY, state TEXT)")
    return con


def save_state(db_path, instance_id: str, state: str):
    with _db(db_path) as con:
        con.execute("INSERT OR REPLACE INTO workflow_state VALUES (?, ?)", (instance_id, state))
    con.close()


def load_state(db_path, instance_id: str) -> str:
    con = _db(db_path)
    try:
        row = con.execute("SELECT state FROM workflow_state WHERE instance_id = ?", (instance_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise LookupError(f"no workflow_state row for instance {instance_id}")
    return row[0]


# ── driver ──────────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    instance_id: str
    trace: list
    data: dict
    provider: str
    events: list
    completed: bool
    checkpoint: dict | None
    task_states: dict


def _public(data: dict) -> dict:
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _delta(before: dict, after: dict) -> dict:
    return {k: v for k, v in after.items() if before.get(k, object()) != v}


def _summ(v):
    if isinstance(v, str) and len(v) > 60:
        return v[:57] + "..."
    if isinstance(v, dict):
        return {k: _summ(x) for k, x in v.items()}
    return v


class _Driver:
    """Steps a workflow element by element, with the worker completing service
    tasks, and records one trace row per completed BPMN element."""

    def __init__(self, graph: Dataset, db_path, instance_id: str):
        self.graph = graph
        self.db_path = db_path
        self.instance_id = instance_id
        self.serializer = make_serializer()
        self.worker = Worker(graph)
        self.trace: list = []
        self.task_states: dict = {}
        self.checkpoint = None

    def resolved_iri(self, bpmn_id: str) -> str:
        iri = task_iri(bpmn_id)
        if bpmn_id == "route_to_provider":
            return decision_for(iri, self.graph).decision_iri
        if bpmn_id == "stream_complete_event":
            return self.worker.channel.iri
        for pred in (SEAM.invokes, SEAM.fires):
            target = self.graph.value(iri, pred)
            if target is not None:
                return str(target)
        return str(iri)

    def record(self, task, before: dict, events_from: int):
        bpmn_id = task.task_spec.bpmn_id
        state = TaskState.get_name(task.state)
        self.task_states[bpmn_id] = state
        self.trace.append({
            "task": bpmn_id, "iri": str(task_iri(bpmn_id)), "resolved": self.resolved_iri(bpmn_id),
            "state": state,
            "delta": _delta(before, _public(task.data)),
            "events": self.worker.channel.events[events_from:],
        })

    def step(self, wf: BpmnWorkflow) -> str | None:
        """Advance until the next BPMN element completes; return its bpmn id
        (None when nothing is runnable)."""
        channel = self.worker.channel
        while True:
            started = [t for t in wf.get_tasks(state=TaskState.STARTED)
                       if isinstance(t.task_spec, ServiceTask)]
            if started:
                task = started[0]
                before, n = _public(task.data), len(channel.events)
                self.worker.handler_for(task.task_spec.bpmn_id)(task)
                task.complete()  # only now: after the handler (and the whole stream) finished
                self.record(task, before, n)
                return task.task_spec.bpmn_id
            ready = [t for t in wf.get_tasks(state=TaskState.READY) if not t.task_spec.manual]
            if not ready:
                return None
            task = ready[0]
            before, n = _public(task.data), len(channel.events)
            task.run()
            if task.state == TaskState.STARTED:
                continue  # a service task, handed to the worker on the next pass
            for ev in wf.get_events():
                channel.publish({"channel": channel.label, "seq": len(channel.events),
                                 "event": task.task_spec.bpmn_id,
                                 "definition": ev.event_definition.name})
            if task.task_spec.bpmn_id is not None:  # skip Spiff's internal Start/End.* specs
                self.record(task, before, n)
                return task.task_spec.bpmn_id

    def checkpoint_and_restore(self, wf: BpmnWorkflow, after: str) -> BpmnWorkflow:
        state = self.serializer.serialize_json(wf)
        save_state(self.db_path, self.instance_id, state)
        self.checkpoint = {"after": after, "instance_id": self.instance_id,
                           "db": str(self.db_path), "bytes": len(state)}
        self.trace[-1]["checkpoint"] = self.checkpoint
        return self.serializer.deserialize_json(load_state(self.db_path, self.instance_id))

    def drive(self, wf: BpmnWorkflow, *, stop_after=None, restore=True) -> RunResult:
        while True:
            done = self.step(wf)
            if done is None:
                break
            if done == "route_to_provider" and restore:
                wf = self.checkpoint_and_restore(wf, done)  # old instance is dropped here
            if stop_after is not None and done == stop_after:
                break
        data = _public(wf.last_task.data) if wf.last_task else {}
        return RunResult(self.instance_id, self.trace, data, data.get("Provider"),
                         list(self.worker.channel.events), wf.is_completed(),
                         self.checkpoint, self.task_states)


def run(message: dict, db_path, *, stop_after=None, graph: Dataset | None = None,
        restore: bool = True) -> RunResult:
    """Run the process for one message.

    After route_to_provider the workflow is checkpointed to SQLite, dropped and
    restored (restore=False skips this, as an uninterrupted baseline).
    stop_after: bpmn id after which to stop; resume() continues from SQLite.
    """
    graph = graph if graph is not None else load_graph()
    spec = make_parser(graph).get_spec(PROCESS_ID)
    driver = _Driver(graph, db_path, str(uuid.uuid4()))
    wf = BpmnWorkflow(spec)
    wf.get_tasks(state=TaskState.READY)[0].data["message"] = dict(message)
    return driver.drive(wf, stop_after=stop_after, restore=restore)


def resume(instance_id: str, db_path, *, graph: Dataset | None = None) -> RunResult:
    """Restore a checkpointed instance from SQLite in a fresh driver and run it
    to the end event. No parser is involved: the spec comes from the JSON."""
    graph = graph if graph is not None else load_graph()
    driver = _Driver(graph, db_path, instance_id)
    wf = driver.serializer.deserialize_json(load_state(db_path, instance_id))
    return driver.drive(wf, restore=False)


def print_trace(result: RunResult, out=sys.stdout):
    for i, row in enumerate(result.trace, 1):
        print(f"{i:>2}. {row['task']:<22} [{row['state']}]", file=out)
        print(f"      iri      {row['iri']}", file=out)
        if row["resolved"] != row["iri"]:
            print(f"      resolved {row['resolved']}", file=out)
        if row["delta"]:
            print(f"      delta    {json.dumps(_summ(row['delta']))}", file=out)
        for ev in row["events"]:
            print(f"      event    {json.dumps(ev)}", file=out)
        if "checkpoint" in row:
            print(f"      checkpoint {json.dumps(row['checkpoint'])}", file=out)
    print(f"provider={result.provider} completed={result.completed} events={len(result.events)}", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="SQLite file (default: temp file)")
    ap.add_argument("--long", action="store_true", help="send a >4000-char user message")
    args = ap.parse_args(argv)
    content = ("lorem ipsum " * 400) if args.long else "Hello there, which provider answers me?"
    with tempfile.TemporaryDirectory() as tmp:
        db = args.db or str(Path(tmp) / "spike.sqlite")
        result = run({"role": "user", "content": content}, db)
        print_trace(result)
    return 0 if result.completed else 1


if __name__ == "__main__":
    sys.exit(main())
