"""Derived DDD type pills and profile violations in the viewer (ADR-0033 sections 1 and 4,
M029/S02/T04).

The tests copy expense chapter 11, which attaches ``profiles/ddd`` by seam:conformsTo, to
tmp_path and drive the viewer through TestClient. The pill names and the rule messages are
read from the profile's shapes graph, never repeated here: a pill shape is a labelled
sh:NodeShape of severity sh:Info (``Profile.pills``). Validation is cached by id(ds), so
the cache is cleared around every test (MEM010).
"""

import html
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import rdflib
from fastapi.testclient import TestClient
from rdflib import RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402
from viewer.profiles import Profile  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
SEAM = rdflib.Namespace("https://w3id.org/seams/seam#")
STATE = rdflib.Namespace("https://w3id.org/seams/state#")
DDD = rdflib.Namespace("https://example.org/profiles/ddd#")
EXPENSE_SHAPE = "https://example.org/expenses/ExpenseShape"
PILL = re.compile(r'<span class="type-pill profile-pill" data-shape="([^"]+)">([^<]*)</span>')


@pytest.fixture
def restore_viewer():
    """Put the viewer back on its own model after the test."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    viewer_app.configure(original)


@pytest.fixture
def app_dir(tmp_path) -> Path:
    return Path(shutil.copytree(CHAPTER, tmp_path / "chapter-11", ignore=shutil.ignore_patterns("generated")))


def open_viewer(app_dir: Path) -> TestClient:
    viewer_app.configure(app_dir)
    return TestClient(viewer_app.app)


def profile() -> Profile:
    loaded = viewer_app.get_profile()
    assert loaded is not None
    return loaded


def pills_on(client: TestClient, iri: str) -> list[tuple[str, str]]:
    response = client.get(f"/view/{quote(iri, safe='')}")
    assert response.status_code == 200
    return [(shape, html.unescape(label)) for shape, label in PILL.findall(response.text)]


def test_the_aggregate_pill_appears_on_an_aggregate_shape(app_dir, restore_viewer):
    client = open_viewer(app_dir)
    loaded = profile()
    assert pills_on(client, EXPENSE_SHAPE) == [(str(DDD.Aggregate), loaded.pills[DDD.Aggregate])]
    assert viewer_app.profile_pills(EXPENSE_SHAPE) == [
        {"label": loaded.pills[DDD.Aggregate], "shape": str(DDD.Aggregate)}
    ]


def test_pills_are_sorted_and_come_only_from_pill_shapes(app_dir, restore_viewer):
    open_viewer(app_dir)
    loaded = profile()
    pills = validation.get_profile_pills(viewer_app.get_graph(), loaded)
    assert pills, "chapter 11 has aggregates, commands and domain events"
    for entries in pills.values():
        keys = [(e["label"], e["shape"]) for e in entries]
        assert keys == sorted(keys)
        assert len({label for label, _s in keys}) == len(keys)
        assert all(loaded.pills[URIRef(shape)] == label for label, shape in keys)


def test_a_target_that_does_not_conform_gets_no_pill(app_dir, restore_viewer):
    """A pill is shown on a conforming focus node only: a channel with no
    seam:acceptsShape is a target of the published-event shape but gets no pill."""
    channel = "https://example.org/x/bare_channel"
    (app_dir / "extra.trig").write_text(
        f"<urn:seams:graph:model:x> {{ <{channel}> a <https://w3id.org/seams/comm#Channel> . }}\n", "utf-8"
    )
    open_viewer(app_dir)
    assert URIRef(channel) in validation._targets(profile().shapes, DDD.PublishedEvent, viewer_app.get_graph())
    assert viewer_app.profile_pills(channel) == []


def test_no_profile_means_no_pill(app_dir, restore_viewer):
    trig = app_dir / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    attachment = re.compile(r"^.*seam:conformsTo <[^>]+> \.\n", re.MULTILINE)
    assert len(attachment.findall(text)) == 1
    trig.write_text(attachment.sub("", text), encoding="utf-8")
    client = open_viewer(app_dir)
    assert viewer_app.get_profile() is None
    assert pills_on(client, EXPENSE_SHAPE) == []
    assert viewer_app.profile_pills(EXPENSE_SHAPE) == []


def test_a_profile_violation_appears_in_health(app_dir, restore_viewer):
    lifecycle = "https://example.org/expenses/expense_lifecycle"
    transition = "https://example.org/x/t_close"
    (app_dir / "extra.trig").write_text(
        f"<urn:seams:graph:model:x> {{ <{transition}> a <{STATE.Transition}> ; <{SEAM.inModel}> <{lifecycle}> . }}\n",
        "utf-8",
    )
    client = open_viewer(app_dir)
    shapes = profile().shapes
    constraint = shapes.value(DDD.FiredTransitions, SH.sparql)
    template = str(shapes.value(constraint, SH.message))
    message = template.replace("{?lifecycle}", lifecycle)
    health = viewer_app.model_health(viewer_app.get_graph())
    found = [v for v in health["violations"] if v["sourceShape"] == str(DDD.FiredTransitions)]
    assert [(v["focusNode"], v["message"]) for v in found] == [(transition, message)]
    response = client.get("/")
    assert response.status_code == 200
    assert f"<li>{html.escape(message)} — <code>{transition}</code></li>" in response.text


def test_chapter_11_has_no_profile_violation_in_health(app_dir, restore_viewer):
    open_viewer(app_dir)
    health = viewer_app.model_health(viewer_app.get_graph())
    iri = str(profile().iri)
    assert [v for v in health["violations"] if (v["sourceShape"] or "").startswith(iri)] == []
    assert all(v["sourceShape"] not in {str(s) for s in profile().pills} for v in health["warnings"])
    assert (URIRef(EXPENSE_SHAPE), RDF.type, SH.NodeShape) in viewer_app.get_graph()
