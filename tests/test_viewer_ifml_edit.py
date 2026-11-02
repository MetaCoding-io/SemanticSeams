"""IFML editing on the diagram (backlog I6, M019/S07): the ops of viewer/ifml_edit.py
and POST /edit/ifml/{model}.

These tests copy the chat app to tmp_path, switch edit mode on with monkeypatch and
configure(), and edit the copy's IFML model through the route: each op is one
seams_edit patch, survives a reload (a fresh seams.load), shows in the htmx output
the viewer's live preview generates (viewer/preview.py), and undoes to the original
bytes. A bad op is a 409 or 400 naming the fact, and nothing is written.

Where the htmx generator needs facts a diagram op does not make (a page's ifml:path
and ifml:title, a component's seam:reads), the test states them with a seams_edit
patch of its own, as the S03 form or a hand edit would.
"""

import logging
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import seams
from fastapi.testclient import TestClient
from rdflib import RDF, Literal, URIRef
from rdflib.namespace import SH
from seams import IFML, SEAM

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import seams_edit  # noqa: E402
from viewer import app as viewer_app  # noqa: E402
from viewer import preview, validation  # noqa: E402

CHAT_APP = ROOT / "examples" / "chat-app"
CHAT = "https://example.org/chat/"
CHAT_IFML = f"{CHAT}chat_ifml"
CHAT_PAGE = f"{CHAT}chat_page"
CONVERSATIONS = f"{CHAT}conversation_list"
THREAD = f"{CHAT}message_thread"
COMPOSE = f"{CHAT}compose_form"
SELECT_CONVERSATION = f"{CHAT}select_conversation"
SELECT_TO_THREAD = f"{CHAT}select_to_thread"
IFML_GRAPH = URIRef("urn:seams:graph:model:chat_ifml")
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
ROUTE = f"/edit/ifml/{quote(CHAT_IFML, safe='')}"


@pytest.fixture
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model, edit mode off, after the test."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(original)


@pytest.fixture
def model(tmp_path, monkeypatch, restore_viewer) -> Path:
    """A copy of the chat app loaded in the viewer with edit mode on."""
    copy = tmp_path / "chat-app"
    shutil.copytree(CHAT_APP, copy, ignore=shutil.ignore_patterns("generated"))
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy)
    return copy


@pytest.fixture
def client(model) -> TestClient:
    return TestClient(viewer_app.app)


def _trig(model: Path) -> Path:
    return model / "chat-app.trig"


def _op(client: TestClient, **op) -> dict:
    response = client.post(ROUTE, json=op)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is True
    return body


def _state(model: Path, *quads) -> None:
    """Facts the diagram does not make, stated through the write path."""
    seams_edit.apply([_trig(model)], seams_edit.Patch(adds=quads))
    viewer_app.reload_model()


def _fresh(model: Path) -> seams.Model:
    return seams.load(_trig(model))


def _outputs(model: Path) -> dict[str, str]:
    """The htmx and fastapi outputs as the live preview generates them."""
    facts = preview.preview(_trig(model), model)
    assert facts["error"] is None
    assert facts["faults"] == []
    return {f["path"]: f["text"] for f in facts["files"]}


def _by_iri(items: list[dict]) -> dict[str, dict]:
    return {i["iri"]: i for i in items}


def _page(model: Path) -> str:
    return _outputs(model)["generated/templates/chat_page.html"]


# --- the slice demo: add a component, wire an event, remove a field ----------


def test_add_a_component_to_a_page(client, model):
    assert 'id="profile_card"' not in _page(model)

    body = _op(client, op="create", kind="Details", name="Profile Card", parent=CHAT_PAGE)

    card = f"{CHAT}profile_card"
    assert body["op"] == "create"
    assert body["element"] == card
    assert body["files"] == [{"file": "chat-app.trig", "adds": 5, "removes": 0}]
    assert body["undo"] == 1
    assert _by_iri(body["ifml"]["components"])[card]["parent"] == CHAT_PAGE
    assert card in str(body["canvas"])
    assert 'id="health-panel"' in body["oob"]
    assert 'id="preview-panel"' in body["oob"]

    ds = _fresh(model).ds
    assert (URIRef(card), RDF.type, IFML.Details) in ds
    assert (URIRef(CHAT_PAGE), IFML.contains, URIRef(card)) in ds
    assert (URIRef(card), SEAM.inModel, URIRef(CHAT_IFML)) in ds
    # The next order after the page's three components (the seam shapes want one).
    assert ds.value(URIRef(card), IFML.order) == Literal(3)

    _state(model, (URIRef(card), SEAM.reads, URIRef(f"{CHAT}ConversationShape"), SEAMS_GRAPH))
    page = _page(model)
    assert "ifml:Details :profile_card" in page
    assert '<section id="profile_card" aria-label="Profile Card">' in page


def test_a_new_components_form_reads_an_iri(client, model):
    """The form fills a new component's seam:reads with an IRI, not a string."""
    _op(client, op="create", kind="Details", name="Profile Card", parent=CHAT_PAGE)
    card = f"{CHAT}profile_card"
    shape = f"{CHAT}ConversationShape"

    response = client.post(f"/edit/{quote(card, safe='')}", data={"field": str(SEAM.reads), "value": shape})

    assert response.status_code == 200, response.text
    assert list(_fresh(model).ds.objects(URIRef(card), SEAM.reads)) == [URIRef(shape)]


def test_wire_an_event_to_another_page(client, model):
    page = f"{CHAT}settings_page"
    _op(client, op="create", kind="ViewContainer", name="Settings Page", parent=CHAT_IFML)
    _state(
        model,
        (URIRef(page), IFML.path, Literal("/settings"), IFML_GRAPH),
        (URIRef(page), IFML.title, Literal("Settings", lang="en"), IFML_GRAPH),
    )
    _op(client, op="create", kind="Event", name="Open Settings", parent=CHAT_PAGE)

    body = _op(client, op="connect", kind="NavigationFlow", source=f"{CHAT}open_settings", target=page)

    flow = f"{CHAT}open_settings_to_settings_page"
    assert body["element"] == flow
    assert {"from": f"{CHAT}open_settings", "to": page, "kind": "navigation"}.items() <= next(
        f for f in body["ifml"]["flows"] if f["iri"] == flow
    ).items()

    (wired,) = [f for f in _fresh(model).interfaces.flows() if str(f.iri) == flow]
    assert wired.kind == IFML.NavigationFlow
    assert str(wired.source.iri) == f"{CHAT}open_settings"
    assert str(wired.target.iri) == page
    assert "ifml:contains :settings_page" in _outputs(model)["generated/templates/settings_page.html"]


def test_rewiring_an_event_changes_the_htmx_link(client, model):
    before = _page(model)
    assert 'hx-target="#message_thread"' in before
    assert 'hx-swap="outerHTML"' in before

    _op(client, op="delete", element=SELECT_TO_THREAD)
    body = _op(
        client,
        op="connect",
        kind="NavigationFlow",
        name="Select Appends",
        source=SELECT_CONVERSATION,
        target=THREAD,
        swap="Append",
    )

    assert body["element"] == f"{CHAT}select_appends"
    ds = _fresh(model).ds
    assert (URIRef(f"{CHAT}select_appends"), IFML.swap, IFML.Append) in ds
    after = _page(model)
    links = after.split("{% block conversation_list %}")[1].split("{% endblock %}")[0]
    assert 'hx-target="#message_thread_items"' in links
    assert 'hx-swap="beforeend"' in links


def test_remove_a_field(client, model):
    timestamp = URIRef(f"{CHAT}timestamp")
    assert "message.timestamp" in _outputs(model)["generated/templates/message_thread_item.html"]

    body = _op(client, op="remove_field", element=COMPOSE, path=str(timestamp))

    assert body["element"] == COMPOSE
    # The sh:property pair and the four triples of its [ ].
    assert body["files"] == [{"file": "chat-app.trig", "adds": 0, "removes": 5}]
    ds = _fresh(model).ds
    assert not list(ds.subjects(SH.path, timestamp))
    fields = _by_iri(body["ifml"]["components"])[COMPOSE]["fields"]
    assert sorted(f["name"] for f in fields) == ["content", "role", "status"]
    assert "timestamp" not in _outputs(model)["generated/templates/message_thread_item.html"]


def test_remove_a_field_takes_its_bound_input(tmp_path, monkeypatch, restore_viewer):
    """A form input ifml:boundTo the removed path goes too, so the htmx still generates."""
    copy = tmp_path / "chapter-08"
    shutil.copytree(ROOT / "examples" / "expenses" / "chapter-08", copy, ignore=shutil.ignore_patterns("generated"))
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(copy)
    expenses = "https://example.org/expenses/"
    route = f"/edit/ifml/{quote(expenses + 'expense_ifml', safe='')}"
    trig = copy / "expenses.trig"
    page = "generated/templates/expenses_page.html"

    def outputs() -> dict[str, str]:
        facts = preview.preview(trig, copy)
        assert facts["error"] is None
        assert facts["faults"] == []
        return {f["path"]: f["text"] for f in facts["files"]}

    assert 'name="description"' in outputs()[page]
    response = TestClient(viewer_app.app).post(
        route, json={"op": "remove_field", "element": f"{expenses}expense_form", "path": f"{expenses}description"}
    )

    assert response.status_code == 200, response.text
    ds = seams.load(trig).ds
    gone = URIRef(f"{expenses}description_input")
    assert not list(ds.quads((gone, None, None, None)))
    assert not list(ds.quads((None, None, gone, None)))
    assert 'name="description"' not in outputs()[page]


# --- move, delete, undo --------------------------------------------------------


def test_move_swaps_the_contains_quad(client, model):
    panel = f"{CHAT}side_panel"
    _op(client, op="create", kind="ViewContainer", name="Side Panel", parent=CHAT_PAGE)

    body = _op(client, op="move", element=CONVERSATIONS, parent=panel)

    assert body["files"] == [{"file": "chat-app.trig", "adds": 1, "removes": 1}]
    ds = _fresh(model).ds
    assert (URIRef(panel), IFML.contains, URIRef(CONVERSATIONS)) in ds
    assert (URIRef(CHAT_PAGE), IFML.contains, URIRef(CONVERSATIONS)) not in ds
    assert ds.value(URIRef(CONVERSATIONS), IFML.order) == Literal(0)
    assert _by_iri(body["ifml"]["components"])[CONVERSATIONS]["parent"] == panel


def test_move_renumbers_a_taken_order(client, model):
    panel = f"{CHAT}side_panel"
    _op(client, op="create", kind="ViewContainer", name="Side Panel", parent=CHAT_PAGE)
    _op(client, op="move", element=CONVERSATIONS, parent=panel)  # keeps order 0
    _op(client, op="create", kind="List", name="Recent", parent=panel)  # takes order 1

    # The thread's order 1 is taken in the panel: it moves in as order 2.
    body = _op(client, op="move", element=THREAD, parent=panel)

    assert body["files"] == [{"file": "chat-app.trig", "adds": 2, "removes": 2}]
    ds = _fresh(model).ds
    orders = {str(c): int(ds.value(c, IFML.order)) for c in ds.objects(URIRef(panel), IFML.contains)}
    assert orders == {CONVERSATIONS: 0, f"{CHAT}recent": 1, THREAD: 2}


def test_delete_cascades_and_leaves_no_dangling_flow(client, model):
    body = _op(client, op="delete", element=THREAD)

    assert body["element"] == THREAD
    ds = _fresh(model).ds
    gone = {
        URIRef(THREAD),
        URIRef(f"{CHAT}conversation"),  # its parameter
        URIRef(SELECT_TO_THREAD),
        URIRef(f"{CHAT}send_to_thread"),
        URIRef(f"{CHAT}list_to_thread"),
    }
    for iri in gone:
        assert (iri, None, None) not in ds, iri
        assert (None, None, iri) not in ds, iri
    assert not list(ds.subjects(RDF.type, IFML.ParameterBinding))
    for end in (IFML.source, IFML.target):
        for flow, node in ds.subject_objects(end):
            assert (node, RDF.type, None) in ds, (flow, end, node)
    assert THREAD not in _by_iri(body["ifml"]["components"])


def test_delete_a_page_takes_its_components_events_and_flows(client, model):
    _op(client, op="delete", element=CHAT_PAGE)

    ds = _fresh(model).ds
    for kind in (
        IFML.ViewContainer,
        IFML.List,
        IFML.Details,
        IFML.Form,
        IFML.Event,
        IFML.NavigationFlow,
        IFML.DataFlow,
    ):
        assert not list(ds.subjects(RDF.type, kind)), kind
    assert (URIRef(CHAT_IFML), RDF.type, IFML.InteractionModel) in ds


def test_undo_restores_the_bytes(client, model):
    original = _trig(model).read_bytes()
    _op(client, op="create", kind="ViewContainer", name="Settings Page", parent=CHAT_IFML)
    _op(client, op="create", kind="Form", name="Profile Form", parent=f"{CHAT}settings_page")
    _op(client, op="connect", kind="NavigationFlow", source=SELECT_CONVERSATION, target=f"{CHAT}settings_page")
    _op(client, op="move", element=COMPOSE, parent=f"{CHAT}settings_page")
    _op(client, op="remove_field", element=COMPOSE, path=f"{CHAT}status")
    _op(client, op="delete", element=CONVERSATIONS)
    assert _trig(model).read_bytes() != original

    for remaining in range(5, -1, -1):
        response = client.post("/edit/undo")
        assert response.status_code == 200
        assert response.json()["remaining"] == remaining
    assert _trig(model).read_bytes() == original


# --- refusals ------------------------------------------------------------------


BAD_OPS = [
    ({"op": "rename"}, CHAT_IFML, "op"),
    ({"op": "create", "kind": "Window", "name": "X", "parent": CHAT_PAGE}, "create", "kind"),
    ({"op": "create", "kind": "List", "name": "X", "parent": CHAT_IFML}, CHAT_IFML, str(IFML.contains)),
    ({"op": "create", "kind": "List", "name": "X", "parent": COMPOSE}, COMPOSE, str(IFML.contains)),
    ({"op": "create", "kind": "Event", "name": "X", "parent": SELECT_TO_THREAD}, SELECT_TO_THREAD, str(IFML.hasEvent)),
    ({"op": "create", "kind": "ViewContainer", "name": "Chat Page", "parent": CHAT_IFML}, CHAT_PAGE, str(RDF.type)),
    (
        {"op": "create", "kind": "Form", "name": "!!", "parent": CHAT_PAGE},
        CHAT_PAGE,
        "http://www.w3.org/2000/01/rdf-schema#label",
    ),
    ({"op": "create", "kind": "Form", "name": "", "parent": CHAT_PAGE}, "create", "name"),
    (
        {"op": "create", "kind": "Form", "name": "X", "parent": f"{CHAT}ConversationShape"},
        f"{CHAT}ConversationShape",
        str(SEAM.inModel),
    ),
    (
        {"op": "connect", "kind": "NavigationFlow", "source": CONVERSATIONS, "target": THREAD},
        CONVERSATIONS,
        str(IFML.source),
    ),
    (
        {"op": "connect", "kind": "NavigationFlow", "source": SELECT_CONVERSATION, "target": SELECT_CONVERSATION},
        SELECT_CONVERSATION,
        str(IFML.target),
    ),
    ({"op": "connect", "kind": "Flow", "source": SELECT_CONVERSATION, "target": THREAD}, "connect", "kind"),
    (
        {
            "op": "connect",
            "kind": "NavigationFlow",
            "source": SELECT_CONVERSATION,
            "target": THREAD,
            "name": "Twice",
            "swap": "Sideways",
        },
        f"{CHAT}twice",
        str(IFML.swap),
    ),
    (
        {
            "op": "connect",
            "kind": "DataFlow",
            "source": CONVERSATIONS,
            "target": THREAD,
            "name": "Data",
            "swap": "Append",
        },
        f"{CHAT}data",
        str(IFML.swap),
    ),
    (
        {"op": "connect", "kind": "NavigationFlow", "source": SELECT_CONVERSATION, "target": THREAD},
        f"{CHAT}select_conversation_to_message_thread",
        "",
    ),
    ({"op": "move", "element": CHAT_PAGE, "parent": CHAT_PAGE}, CHAT_PAGE, str(IFML.contains)),
    ({"op": "move", "element": THREAD, "parent": CHAT_PAGE}, CHAT_PAGE, str(IFML.contains)),
    ({"op": "move", "element": SELECT_CONVERSATION, "parent": CHAT_PAGE}, SELECT_CONVERSATION, str(IFML.contains)),
    ({"op": "move", "element": THREAD, "parent": CHAT_IFML}, CHAT_IFML, str(IFML.contains)),
    ({"op": "delete", "element": CHAT_IFML}, CHAT_IFML, str(SEAM.inModel)),
    ({"op": "delete", "element": f"{CHAT}nothing_here"}, f"{CHAT}nothing_here", str(SEAM.inModel)),
    ({"op": "remove_field", "element": THREAD, "path": f"{CHAT}content"}, THREAD, str(RDF.type)),
    ({"op": "remove_field", "element": COMPOSE, "path": f"{CHAT}title"}, COMPOSE, str(SH.path)),
]


@pytest.mark.parametrize(
    ("op", "subject", "predicate"), BAD_OPS, ids=[f"{i}-{o['op']}" for i, (o, _s, _p) in enumerate(BAD_OPS)]
)
def test_a_bad_op_is_refused_and_writes_nothing(client, model, op, subject, predicate, caplog):
    if predicate == "":
        # Wiring the same pair twice mints the same IRI: the second is refused.
        _op(client, **op)
        predicate = str(RDF.type)
    before = _trig(model).read_bytes()
    undo = len(viewer_app._undo_stack)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        response = client.post(ROUTE, json=op)

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["saved"] is False
    assert body["error"]["subject"] == subject
    assert body["error"]["predicate"] == predicate
    assert body["error"]["detail"]
    assert _trig(model).read_bytes() == before
    assert len(viewer_app._undo_stack) == undo
    assert any("ifml edit refused" in r.getMessage() and subject in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"kind": "List"}'])
def test_a_malformed_body_is_400(client, model, body):
    before = _trig(model).read_bytes()
    response = client.post(ROUTE, content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert _trig(model).read_bytes() == before


def test_a_model_that_is_not_ifml_is_404(client, model):
    response = client.post(f"/edit/ifml/{quote(f'{CHAT}chat_bpmn', safe='')}", json={"op": "delete", "element": THREAD})
    assert response.status_code == 404


def test_route_absent_without_seams_edit(tmp_path, monkeypatch, restore_viewer):
    copy = tmp_path / "chat-app"
    shutil.copytree(CHAT_APP, copy, ignore=shutil.ignore_patterns("generated"))
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(copy)
    before = (copy / "chat-app.trig").read_bytes()
    response = TestClient(viewer_app.app).post(ROUTE, json={"op": "delete", "element": THREAD})
    assert response.status_code in (404, 405)
    assert (copy / "chat-app.trig").read_bytes() == before


def test_each_op_logs_its_kind_element_files_and_counts(client, model, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        _op(client, op="create", kind="List", name="Recent", parent=CHAT_PAGE)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ifml edit create")]
    assert f"{CHAT}recent" in line
    assert CHAT_IFML in line
    assert "chat-app.trig (+5 -0)" in line


# --- the modeler on the IFML canvas (T02) --------------------------------------

VIEW = f"/view/{quote(CHAT_IFML, safe='')}"
SAVE_URL = f"/edit/ifml/{quote(CHAT_IFML, safe='')}"
# What edit mode adds to the IFML view: the modeling module (page shell), the
# bar, the canvas's save URL and the edit options the render call passes.
MODELING_HOOKS = (
    "window.seamsIfmlEditing = {",
    "https://esm.sh/diagram-js@15/lib/features/modeling",
    "https://esm.sh/diagram-js@15/lib/features/palette",
)
VIEW_HOOKS = (
    'id="ifml-edit-bar"',
    f'data-save-url="{SAVE_URL}"',
    f'"saveUrl": "{SAVE_URL}"',
    'id="ifml-edit-panel"',
)


def test_ifml_view_has_the_modeling_hook_and_save_url_in_edit_mode(client):
    html = client.get(VIEW).text
    for hook in MODELING_HOOKS + VIEW_HOOKS:
        assert hook in html, hook
    # A form's field rows carry the field IRI that remove_field posts.
    assert '"data-field-iri": f.iri' in html


def test_ifml_fragment_carries_the_save_url_but_not_the_modules(client):
    html = client.get(VIEW, headers={"hx-request": "true"}).text
    for hook in VIEW_HOOKS:
        assert hook in html, hook
    # The modules load once with the shell (MEM009), not with every swap.
    for hook in MODELING_HOOKS:
        assert hook not in html, hook


def test_ifml_view_has_no_modeling_hook_or_save_url_without_seams_edit(tmp_path, monkeypatch, restore_viewer):
    copy = tmp_path / "chat-app"
    shutil.copytree(CHAT_APP, copy, ignore=shutil.ignore_patterns("generated"))
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(copy)
    html = TestClient(viewer_app.app).get(VIEW).text
    assert 'id="ifml-canvas"' in html
    for hook in MODELING_HOOKS + VIEW_HOOKS:
        assert hook not in html, hook
    assert "/edit/ifml/" not in html
    # The read-only canvas is drawn with no edit options.
    assert '", null);' in html


def test_selecting_a_flow_opens_its_form(client):
    """Selecting a flow on the canvas loads its S03 form; the swap field is a
    select over the ifml:SwapStrategy options (a dict field's values, not dict.values)."""
    response = client.get(f"/edit/{quote(f'{CHAT}send_to_thread', safe='')}")
    assert response.status_code == 200, response.text
    assert "<select" in response.text
