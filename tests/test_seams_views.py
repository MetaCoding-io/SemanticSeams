"""seams views (M010/S03): typed, read-only collections over every layer."""

import dataclasses
from pathlib import Path

import pytest
import seams
from rdflib import RDF, Dataset, URIRef
from seams import ARCH, COMM, HYDRA, ODRL, SEAM, STATE, Many, ModelGraph, ResolutionError

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
        assert items.subject == str(model.subject) and items.predicate == str(RDF.type), name


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
