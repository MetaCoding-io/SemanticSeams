"""seams views (M010/S03): typed, read-only collections over every layer."""

import dataclasses
from pathlib import Path

import pytest
import seams
from rdflib import RDF, Dataset, Literal, URIRef
from seams import ARCH, COMM, HYDRA, IFML, ODRL, PROC, SEAM, STATE, Many, ModelGraph, ResolutionError

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"
CH08 = ROOT / "examples/expenses/chapter-08/expenses.trig"
CH08_DIR = ROOT / "examples/expenses/chapter-08"

C = "https://example.org/chat/"
X = "https://example.org/expenses/"

MODELS = {"chat-app": CHAT, "chapter-08": CH08, "chapter-08-dir": CH08_DIR}


@pytest.fixture(params=sorted(MODELS), scope="module")
def model(request: pytest.FixtureRequest) -> seams.Model:
    return seams.load(MODELS[request.param])


@pytest.fixture(scope="module")
def chat() -> seams.Model:
    return seams.load(CHAT)


@pytest.fixture(scope="module", params=[CH08, CH08_DIR], ids=["file", "dir"])
def ch08(request: pytest.FixtureRequest) -> seams.Model:
    return seams.load(request.param)


def _layers(m: seams.Model) -> dict[str, Many[seams.Element]]:
    a = m.architecture
    return {
        "systems": a.systems(),
        "containers": a.containers(),
        "deployment_nodes": a.deployment_nodes(),
        "environments": a.environments(),
        "operations": m.operations,
        "channels": m.channels,
        "shapes": m.shapes,
        "lifecycles": m.lifecycles,
        "policies": m.policies,
        "interaction_models": m.interfaces.models(),
        "pages": m.interfaces.pages(),
        "processes": m.processes,
        "decisions": m.decisions,
    }


def _copy(m: seams.Model) -> Dataset:
    ds = Dataset(default_union=True)
    for prefix, ns in m.ds.namespaces():
        ds.bind(prefix, ns)
    for quad in m.ds.quads((None, None, None, None)):
        ds.add(quad)
    return ds


# ── the core, on every example ──


def test_every_layer_is_non_empty_and_sorted(model: seams.Model):
    for name, items in _layers(model).items():
        assert items, name
        assert [str(i.iri) for i in items] == sorted(str(i.iri) for i in items), name
        assert items.subject == str(model.subject), name
        if name != "decisions":  # gathered from seam:decidedBy and dec:payloadElement
            assert items.predicate == str(RDF.type), name


def test_elements_are_frozen_and_raw_is_the_iri(model: seams.Model):
    for name, items in _layers(model).items():
        element = items[0]
        assert element.raw is element.iri and isinstance(element.raw, URIRef), name
        assert element.graph is model.ds
        with pytest.raises(dataclasses.FrozenInstanceError):
            element.label = "changed"  # type: ignore[misc]


def test_views_are_built_once_per_model(model: seams.Model):
    assert model.operations is model.operations
    assert model.architecture is model.architecture
    other = seams.load(model.path)
    assert other.operations[0] is not model.operations[0]
    assert other.operations[0] == model.operations[0]


def test_only_on_empty_and_on_two_names_subject_and_predicate(model: seams.Model):
    containers = model.architecture.containers()
    with pytest.raises(ResolutionError) as empty:
        containers.where(lambda c: False).only()
    assert empty.value.subject == str(model.subject)
    assert empty.value.predicate == str(RDF.type)
    assert "expected exactly one, found []" in str(empty.value)

    two = containers.where(lambda c: c.iri in containers.iris()[:2])
    assert len(two) == 2
    with pytest.raises(ResolutionError) as many:
        two.only()
    assert many.value.predicate == str(RDF.type)
    assert all(str(i) in many.value.detail for i in two.iris())


def test_by_iri_accepts_curies_and_misses_raise(model: seams.Model):
    first = model.operations[0]
    assert model.operations.by_iri(first.iri) is first
    assert model.operations.by_iri(str(first.iri)) is first
    with pytest.raises(ResolutionError) as miss:
        model.operations.by_iri(":no_such_operation")
    assert miss.value.predicate == str(RDF.type)
    assert "no_such_operation" in miss.value.detail


def test_edges_are_sorted_and_seam_only(model: seams.Model):
    seen = 0
    for items in _layers(model).values():
        for element in items:
            edges = element.edges
            assert all(str(p).startswith(str(SEAM)) for p, _o in edges)
            assert list(edges) == sorted(edges, key=lambda po: (str(po[0]), str(po[1])))
            seen += len(edges)
    assert seen


def test_cross_layer_edges_resolve_to_the_same_object(model: seams.Model):
    containers = model.architecture.containers()
    for op in model.operations:
        for c in op.exposed_by:
            assert c is containers.by_iri(c.iri)
            assert op in c.exposes
    for shape in model.shapes:
        lc = shape.lifecycle
        if lc is not None:
            assert lc is model.lifecycles.by_iri(lc.iri)
            assert lc.shape is shape


def test_operation_paths_and_policies_match_the_resolvers(model: seams.Model):
    graph = ModelGraph(model.path)
    for op in model.operations:
        path = op.path
        assert path is not None
        expected = graph.operation_path(op.iri)
        assert (path.template, path.mappings) == (expected.template, expected.mappings)
    for policy in model.policies:
        assert policy.permissions == graph.policy(policy.iri).permissions


def test_lifecycle_transitions_match_the_resolvers(model: seams.Model):
    graph = ModelGraph(model.path)
    for lc in model.lifecycles:
        facts = graph.lifecycle_for(lc.shape.iri) if lc.shape else None
        if facts is not None:
            assert lc.initial.label == facts.initial
            assert {s.iri: s.label for s in lc.states()} == facts.states
        for t in lc.transitions():
            assert t.lifecycle is lc
            assert t.from_state in lc.states() and t.to_state in lc.states()
            old = graph._transition(t.iri)  # pyright: ignore[reportPrivateUsage]
            assert (t.from_state.label, t.to_state.label, t.trigger) == (old.from_state, old.to_state, old.trigger)


def test_owning_model_comes_from_in_model(model: seams.Model):
    for c in model.architecture.containers():
        assert c.model is not None and (c.model, RDF.type, SEAM.Model) in model.ds
    # operations live in the seams graph and name no seam:inModel
    assert all(op.model is None for op in model.operations)


# ── chat-app facts ──


def test_chat_architecture(chat: seams.Model):
    a = chat.architecture
    assert a.systems().only().containers.iris() == a.containers().iris()
    api = a.containers().by_iri(":chat_api")
    assert api.label == "Chat API" and api.model == URIRef(C + "chat_architecture")
    assert api.technology == "FastAPI, SSE streaming"
    assert api.exposes.iris() == tuple(
        URIRef(C + n) for n in ["list_conversations_op", "message_thread_op", "send_message_op", "stream_events"]
    )
    assert isinstance(api.exposes.by_iri(":stream_events"), seams.Channel)
    assert isinstance(api.exposes.by_iri(":send_message_op"), seams.Operation)
    assert api.executes.only().iri == URIRef(C + "send_message_process")
    assert api.deployed_to.only() is a.deployment_nodes().by_iri(":app01")
    assert dict(api.service_bindings) == {"LLM_GATEWAY_URL": URIRef(C + "llm_gateway")}
    assert api.depends_on.iris() == (URIRef(C + "llm_gateway"), URIRef(C + "message_db"))
    with pytest.raises(TypeError):
        api.service_bindings["X"] = URIRef(C + "x")  # type: ignore[index]
    assert a.environments().only().nodes.iris() == a.deployment_nodes().iris()
    assert a.deployment_nodes().by_iri(":app01").hosts.iris() == (URIRef(C + "chat_api"), URIRef(C + "llm_gateway"))


def test_chat_operations_and_channels(chat: seams.Model):
    send = chat.operations.by_iri(":send_message_op")
    assert send.method == "POST"
    assert send.media_kind == SEAM.UIFragment
    assert send.request_media_type == "application/x-www-form-urlencoded"
    assert send.accepts is chat.shapes.by_iri(":MessageShape")
    assert send.returns is chat.shapes.by_iri(":MessageShape")
    assert send.exposed_by.only().iri == URIRef(C + "chat_api")
    assert send.consumed_by.only().iri == URIRef(C + "chat_ui")
    assert send.governed_by.only() is chat.policies.only()
    path = send.path
    assert path is not None and path.template == "/conversations/{conversation}/messages"
    assert path.variables == ("conversation",)
    assert chat.operations.by_iri(":list_conversations_op").accepts is None

    stream = chat.channels.only()
    assert stream.transport == COMM.SSE and stream.event_name == "token"
    assert stream.exposed_by.only().iri == URIRef(C + "chat_api")
    assert stream.published_by.only().iri == URIRef(C + "chat_bpmn#stream_complete_event")
    assert not stream.subscribed_by


def test_chat_shapes(chat: seams.Model):
    message = chat.shapes.by_iri(":MessageShape")
    fields = message.fields()
    assert [f.name for f in fields] == ["content", "role", "status", "timestamp"]
    assert [f.order for f in fields] == [0, 1, 2, 3]
    content = fields.by_iri(":content")
    assert (content.min_count, content.max_count, content.required) == (1, 1, True)
    assert str(content.datatype).endswith("#string")
    assert fields.subject == str(message.iri) and fields.predicate.endswith("shacl#property")
    # no sh:order at all: by path IRI
    assert [f.name for f in chat.shapes.by_iri(":ConversationShape").fields()] == ["hasMessage", "id", "title"]
    assert message.lifecycle is chat.lifecycles.only()
    assert URIRef(C + "compose_form") in message.written_by.iris()


def test_chat_lifecycle(chat: seams.Model):
    lc = chat.lifecycles.only()
    assert lc.initial.label == "composing"
    assert [s.label for s in lc.finals()] == ["complete", "failed"]
    assert len(lc.states()) == 5
    send = lc.transitions().by_iri(":t_send")
    assert (send.from_state.label, send.to_state.label, send.trigger) == ("composing", "sending", "send")
    assert send.fired_by.only().iri == URIRef(C + "chat_bpmn#persist_user_msg")
    assert chat.lifecycles.transitions().iris() == lc.transitions().iris()
    assert lc.initial.lifecycle is lc


def test_chat_policy(chat: seams.Model):
    policy = chat.policies.only()
    perm = policy.permissions[0]
    assert (perm.target, perm.action) == (URIRef(C + "send_message_op"), ODRL.use)
    governed = policy.governs
    assert governed.iris() == (URIRef(C + "send_message"), URIRef(C + "send_message_op"))
    assert governed.by_iri(":send_message_op") is chat.operations.by_iri(":send_message_op")


# ── chapter-08 facts (file and directory) ──


def test_ch08_two_processes_run_in_the_api(ch08: seams.Model):
    api = ch08.architecture.containers().by_iri(":expense_api")
    assert api.executes.iris() == (URIRef(X + "approval_process"), URIRef(X + "payout_process"))
    assert ch08.channels.only() in api.exposes
    assert len(api.exposes) == 10


def test_ch08_governed_elements(ch08: seams.Model):
    governed = [op for op in ch08.operations if op.governed_by]
    assert [op.iri for op in governed] == [URIRef(X + "submit_expense_op")]
    assert governed[0].governed_by.only().iri == URIRef(X + "employee_submit_policy")
    assert len(ch08.policies) == 4
    manager = ch08.policies.by_iri(":manager_approval_policy")
    assert manager.governs.only().iri == URIRef(X + "approval_bpmn#approve_expense")
    assert manager.permissions[0].assignee_types == (ODRL.Party,)


def test_ch08_two_lifecycles_each_on_its_shape(ch08: seams.Model):
    lcs = ch08.lifecycles
    assert lcs.iris() == (URIRef(X + "expense_lifecycle"), URIRef(X + "payment_lifecycle"))
    with pytest.raises(ResolutionError) as two:
        lcs.only()
    assert two.value.subject == str(ch08.subject) and two.value.predicate == str(RDF.type)
    assert ch08.shapes.by_iri(":ExpenseShape").lifecycle is lcs.by_iri(":expense_lifecycle")
    assert ch08.shapes.by_iri(":PaymentShape").lifecycle is lcs.by_iri(":payment_lifecycle")
    assert ch08.shapes.by_iri(":ApprovalShape").lifecycle is None
    # t_send exists in the payment lifecycle only; fired by the payout's send_now
    send = lcs.transitions().by_iri(":t_send")
    assert send.lifecycle is lcs.by_iri(":payment_lifecycle")
    assert send.fired_by.only().iri == URIRef(X + "payout_bpmn#send_now")
    assert [f.name for f in ch08.shapes.by_iri(":ExpenseShape").fields()] == [
        "description",
        "amount",
        "date",
        "status",
        "id",
    ]


def test_ch08_payout_channel(ch08: seams.Model):
    payouts = ch08.channels.only()
    assert payouts.event_name == "payout"
    assert payouts.subscribed_by.only().iri == URIRef(X + "payout_bpmn#payout_requested")
    assert payouts.published_by.only().iri == URIRef(X + "approval_bpmn#approved_end")
    path = payouts.path
    assert path is not None and path.template == "/expenses/{expense}/payouts"


# ── broken graphs ──


def test_missing_initial_state_names_the_lifecycle(chat: seams.Model):
    ds = _copy(chat)
    lc = URIRef(C + "message_lifecycle")
    ds.remove((lc, STATE.initial, None))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.lifecycles.only().initial
    assert (err.value.subject, err.value.predicate) == (str(lc), str(STATE.initial))


def test_missing_transition_target_names_the_transition(chat: seams.Model):
    ds = _copy(chat)
    t = URIRef(C + "t_send")
    ds.remove((t, STATE.to, None))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.lifecycles.transitions().by_iri(t).to_state
    assert (err.value.subject, err.value.predicate) == (str(t), str(STATE.to))


def test_ambiguous_single_edge_raises(chat: seams.Model):
    ds = _copy(chat)
    op = URIRef(C + "send_message_op")
    ds.add((op, SEAM.acceptsShape, URIRef(C + "ConversationShape")))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.operations.by_iri(op).accepts
    assert (err.value.subject, err.value.predicate) == (str(op), str(SEAM.acceptsShape))


def test_path_template_without_template_raises(chat: seams.Model):
    ds = _copy(chat)
    op = URIRef(C + "list_conversations_op")
    node = ds.value(op, COMM.path)
    ds.remove((node, HYDRA.template, None))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.operations.by_iri(op).path
    assert (err.value.subject, err.value.predicate) == (str(op), str(HYDRA.template))


def test_untyped_related_element_is_a_plain_element(chat: seams.Model):
    ds = _copy(chat)
    ds.add((URIRef(C + "mystery"), SEAM.governedBy, URIRef(C + "user_send_policy")))
    broken = seams.Model(CHAT, ds)
    mystery = broken.policies.only().governs.by_iri(":mystery")
    assert type(mystery) is seams.Element
    assert mystery.label == "mystery" and mystery.model is None


def test_arch_namespace_matches_the_trig(chat: seams.Model):
    assert dict(chat.ds.namespaces())["arch"] == URIRef(str(ARCH))


# ── interfaces, processes and decisions (T02) ──


def test_served_pages_match_the_resolvers(model: seams.Model):
    graph = ModelGraph(model.path)
    served = model.interfaces.served_pages()
    assert served[0] is model.interfaces.landmark()
    assert served.iris()[0] == graph.landmark_page()
    for page in model.interfaces.pages():
        assert page.components().iris() == tuple(graph.page_components(page.iri))
        assert page.interaction_model in model.interfaces.models()


def test_process_facts_match_the_resolvers(model: seams.Model):
    graph = ModelGraph(model.path)
    for process in model.processes:
        facts = graph.process_for(process.iri)
        assert (process.bpmn_model, process.bpmn_path) == (facts.model, facts.bpmn_path)
        assert process.executed_by.only().iri == graph.executing_container(process.iri).iri
        assert process.correlation_key == graph.correlation_key(process.iri)
        assert [(s.event.iri, s.channel.iri) for s in process.channel_starts] == [
            (s.event, s.channel)
            for s in graph._start_subscriptions(process.iri)  # pyright: ignore[reportPrivateUsage]
        ]
        for pid in process.bpmn_process_ids:
            assert model.processes.for_bpmn_process(pid).only() is process
        for el in process.elements():
            assert el.process is process
            assert process.element_iri(el.bpmn_id) == el.iri
            assert model.processes.element(el.bpmn_id).only() is el
            assert el.reads.iris() == tuple(graph.read_shapes(el.iri))
            assert el.writes.iris() == tuple(graph.written_shapes(el.iri))


def test_decisions_match_the_resolvers(model: seams.Model):
    graph = ModelGraph(model.path)
    assert model.decisions
    for decision in model.decisions:
        for task in decision.decides_for:
            assert task.decided_by is decision
            binding = graph.decision_binding(task.iri)
            assert (decision.decision_id, decision.dmn_model, decision.dmn_path) == (
                binding.decision_id,
                binding.model,
                binding.dmn_path,
            )
            assert (decision.inputs, decision.outputs) == (binding.inputs, binding.outputs)


def test_forward_references_are_typed(model: seams.Model):
    for c in model.architecture.containers():
        assert all(p is model.processes.by_iri(p.iri) for p in c.executes)
    for t in model.lifecycles.transitions():
        assert all(isinstance(e, seams.ProcessElement) and e.fires is t for e in t.fired_by)


def test_chat_interfaces_and_process(chat: seams.Model):
    i = chat.interfaces
    landmark = i.landmark()
    assert landmark.iri == URIRef(C + "chat_page") and landmark.path == "/"
    assert i.served_pages() == (landmark,)
    assert not landmark.hosts_task_form
    ifml = i.models().only()
    assert ifml.pages() == (landmark,)
    assert ifml.presented_by is chat.architecture.containers().by_iri(":chat_ui")
    assert [c.kind for c in landmark.components()] == ["List", "Details", "Form"]
    form = landmark.components().by_iri(":compose_form")
    assert form.writes.only() is chat.shapes.by_iri(":MessageShape")
    assert form.parameters() == ("message input",)
    assert form.page is landmark and not form.completes
    send = form.events().only()
    process = chat.processes.only()
    assert send.triggers is process and send.trigger == "submit"
    assert send.submits_to is chat.operations.by_iri(":send_message_op")
    assert send.navigates_to is None
    assert send.updates.only().iri == URIRef(C + "message_thread")
    assert process.triggered_by.only() is send
    thread = landmark.components().by_iri(":message_thread")
    assert [s.label for s in thread.visible_when] == ["complete", "composing", "sending", "streaming"]
    assert process.bpmn_process_ids == ("send_message_process",)
    assert not process.channel_starts


def test_chat_route_to_provider_decision(chat: seams.Model):
    task = chat.processes.element("route_to_provider").only()
    assert task.kind == "BusinessRuleTask"
    decision = task.decided_by
    assert decision is not None and decision is chat.decisions.only()
    binding = ModelGraph(CHAT).decision_binding("route_to_provider")
    assert decision.decision_id == binding.decision_id == "routing_decision"
    assert [b.variable for b in decision.inputs] == ["message_length", "message_role"]
    assert decision.outputs[0].process_variable == "provider"
    assert decision.reads.only() is chat.shapes.by_iri(":MessageShape")
    persist = chat.processes.element("persist_user_msg").only()
    assert persist.invokes is chat.operations.by_iri(":send_message_op")
    assert persist.fires is chat.lifecycles.transitions().by_iri(":t_send")
    assert chat.processes.element("stream_complete_event").only().publishes_to.only() is chat.channels.only()


def test_ch08_two_processes_two_bpmn_models(ch08: seams.Model):
    procs = ch08.processes
    assert procs.iris() == (URIRef(X + "approval_process"), URIRef(X + "payout_process"))
    assert procs.all() == tuple(procs)
    approval = procs.for_bpmn_process("approval_process").only()
    payout = procs.for_bpmn_process("payout_process").only()
    assert approval.bpmn_model == URIRef(X + "approval_bpmn") and approval.bpmn_path.name == "approval.bpmn"
    assert payout.bpmn_model == URIRef(X + "payout_bpmn") and payout.bpmn_path.name == "payout.bpmn"
    assert approval.triggered_by.only().iri == URIRef(X + "submit_expense")
    assert not payout.triggered_by
    start = payout.channel_starts.only()
    assert isinstance(start.channel, seams.Channel) and start.channel is ch08.channels.only()
    assert start.event.bpmn_id == "payout_requested" and start.event.kind == "MessageCatchEvent"
    assert start.event.subscribes_to.only() is start.channel
    assert not approval.channel_starts
    with pytest.raises(ResolutionError) as none:
        procs.for_bpmn_process("no_such_process").only()
    assert (none.value.subject, none.value.predicate) == (str(ch08.subject), str(SEAM.detailedBy))
    assert ch08.processes.element("send_now").only().fires is ch08.lifecycles.transitions().by_iri(":t_send")


def test_ch08_served_pages_and_task_forms(ch08: seams.Model):
    i = ch08.interfaces
    assert i.served_pages().iris() == (URIRef(X + "expenses_page"), URIRef(X + "payouts_page"))
    approvals = i.pages().by_iri(":approvals_page")
    assert approvals.hosts_task_form and approvals.path == "/approvals"
    assert approvals not in i.served_pages()
    task = ch08.processes.element("approve_expense").only()
    assert task.kind == "UserTask"
    form = task.completed_on
    assert isinstance(form, seams.Component) and form.kind == "Form"
    assert form.page is approvals and form.completes.only() is task
    assert [c.iri for c in i.models().by_iri(":finance_console").pages()] == [URIRef(X + "payouts_page")]
    assert i.models().by_iri(":finance_console").presented_by is ch08.architecture.containers().by_iri(
        ":employee_portal"
    )
    governed = ch08.policies.by_iri(":manager_approval_policy").governs.only()
    assert governed is task


def test_ch08_decisions(ch08: seams.Model):
    assert ch08.decisions.iris() == (URIRef(X + "approval_routing"), URIRef(X + "payout_method"))
    payout = ch08.decisions.by_iri(":payout_method")
    assert payout.dmn_path.name == "payout.dmn"
    assert payout.decides_for.only() is ch08.processes.element("choose_payout").only()
    assert payout.inputs[0].type_ref == "number"


# ── broken graphs (T02) ──


def test_second_landmark_names_is_landmark(chat: seams.Model):
    ds = _copy(chat)
    ds.add((URIRef(C + "other_page"), RDF.type, IFML.ViewContainer))
    ds.add((URIRef(C + "other_page"), IFML.isLandmark, Literal(True)))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        broken.interfaces.landmark()
    assert (err.value.subject, err.value.predicate) == (str(broken.subject), str(IFML.isLandmark))
    assert "expected one ifml:ViewContainer with ifml:isLandmark true" in err.value.detail
    assert "other_page" in err.value.detail
    with pytest.raises(ResolutionError):
        broken.interfaces.served_pages()


def test_no_landmark_raises(chat: seams.Model):
    ds = _copy(chat)
    ds.remove((None, IFML.isLandmark, None))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        broken.interfaces.landmark()
    assert err.value.predicate == str(IFML.isLandmark) and "found []" in err.value.detail


def test_bpmn_id_in_two_models_is_ambiguous(ch08: seams.Model):
    ds = _copy(ch08)
    clash = URIRef(X + "payout_bpmn#persist_expense")
    ds.add((clash, RDF.type, PROC.ServiceTask))
    broken = seams.Model(ch08.path, ds)
    found = broken.processes.element("persist_expense")
    assert found.iris() == (URIRef(X + "approval_bpmn#persist_expense"), clash)
    with pytest.raises(ResolutionError) as err:
        found.only()
    assert (err.value.subject, err.value.predicate) == (str(broken.subject), str(SEAM.detailedBy))
    assert str(clash) in err.value.detail


def test_process_without_bpmn_model_names_detailed_by(chat: seams.Model):
    ds = _copy(chat)
    process = URIRef(C + "send_message_process")
    ds.remove((process, SEAM.detailedBy, None))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.processes.only().bpmn_model
    assert (err.value.subject, err.value.predicate) == (str(process), str(SEAM.detailedBy))


def test_unknown_decision_id_names_payload_element(chat: seams.Model):
    ds = _copy(chat)
    decision = URIRef(C + "routing_decision")
    ds.remove((decision, seams.DEC.payloadElement, None))
    ds.add((decision, seams.DEC.payloadElement, Literal("no_such_decision")))
    broken = seams.Model(CHAT, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.decisions.only().decision_id
    assert (err.value.subject, err.value.predicate) == (str(decision), str(seams.DEC.payloadElement))
    assert "no_such_decision" in err.value.detail


def test_task_with_two_forms_raises(ch08: seams.Model):
    ds = _copy(ch08)
    task = URIRef(X + "approval_bpmn#approve_expense")
    ds.add((task, SEAM.completedOn, URIRef(X + "payment_form")))
    broken = seams.Model(ch08.path, ds)
    with pytest.raises(ResolutionError) as err:
        _ = broken.processes.element("approve_expense").only().completed_on
    assert (err.value.subject, err.value.predicate) == (str(task), str(SEAM.completedOn))
