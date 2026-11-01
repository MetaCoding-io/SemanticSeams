"""The IFMLEdit.org JSON exporter (M008/S01, backlog 12).

The export is compared with SPARQL over the model: every IFML view
container, component, event and flow appears once, with its containment,
its events, its flow endpoints, its parameters as fields and its parameter
bindings. Error cases edit a copy of the chat app in tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph
from seams import IFML, load, local_name

from seams_gen import GeneratorError
from seams_gen.__main__ import main
from seams_gen.ifmledit import FILE, UNMAPPED, generate

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "examples" / "chat-app" / "chat-app.trig"
CHAPTER_08 = ROOT / "examples" / "expenses" / "chapter-08" / "expenses.trig"
MODELS = pytest.mark.parametrize("trig", [CHAT, CHAPTER_08], ids=["chat", "ch08"])

PREFIX = "PREFIX ifml: <https://w3id.org/seams/ifml#>\n"
ELEMENT_TYPES = {
    "ifml.ViewContainer": "ifml:ViewContainer",
    "ifml.ViewComponent": "ifml:List ifml:Details ifml:Form",
    "ifml.Event": "ifml:Event",
    "ifml.NavigationFlow": "ifml:NavigationFlow",
    "ifml.DataFlow": "ifml:DataFlow",
}
STEREOTYPES = {"List": "list", "Details": "details", "Form": "form"}


def _export(trig: Path) -> dict:
    return json.loads(generate(load(trig))[FILE])


def _pairs(trig: Path, query: str) -> set[tuple[str, ...]]:
    return {tuple(local_name(v) for v in row) for row in load(trig).ds.query(PREFIX + query)}


def _elements(doc: dict, type_: str) -> dict[str, dict]:
    return {e["id"]: e for e in doc["elements"] if e["type"] == type_}


def _relations(doc: dict, type_: str, *keys: str) -> set[tuple[str, ...]]:
    return {tuple(r[k] for k in keys) for r in doc["relations"] if r["type"] == type_}


@MODELS
@pytest.mark.parametrize("type_", sorted(ELEMENT_TYPES))
def test_every_ifml_element_appears_once(trig, type_):
    ids = [e["id"] for e in _export(trig)["elements"] if e["type"] == type_]
    expected = _pairs(trig, f"SELECT DISTINCT ?e {{ VALUES ?t {{ {ELEMENT_TYPES[type_]} }} ?e a ?t }}")
    assert len(ids) == len(set(ids))
    assert {(i,) for i in ids} == expected


@MODELS
def test_containment_and_events_are_hierarchy_relations(trig):
    contains = _pairs(
        trig,
        """SELECT ?p ?c { ?p a ifml:ViewContainer ; ifml:contains ?c .
                          VALUES ?t { ifml:ViewContainer ifml:List ifml:Details ifml:Form } ?c a ?t }""",
    )
    has_event = _pairs(trig, "SELECT ?o ?e { ?o ifml:hasEvent ?e . ?e a ifml:Event }")
    assert contains and has_event
    assert _relations(_export(trig), "hierarchy", "parent", "child") == contains | has_event


@MODELS
@pytest.mark.parametrize("end", ["source", "target"])
def test_flow_endpoints_are_source_and_target_relations(trig, end):
    expected = _pairs(
        trig, f"SELECT ?f ?x {{ VALUES ?t {{ ifml:NavigationFlow ifml:DataFlow }} ?f a ?t ; ifml:{end} ?x }}"
    )
    assert expected
    assert _relations(_export(trig), end, "flow", end) == expected


@MODELS
def test_containers_carry_their_flags_and_components_their_stereotype(trig):
    doc = _export(trig)
    m = load(trig)
    for cid, e in _elements(doc, "ifml.ViewContainer").items():
        page = m.interfaces.pages().by_iri(m.curie(f":{cid}"))
        assert e["attributes"] == {
            "name": m.label(page.iri),
            "default": page.is_default,
            "landmark": page.is_landmark,
            "xor": page.is_xor,
        }
    kinds = _pairs(trig, "SELECT ?c ?t { VALUES ?t { ifml:List ifml:Details ifml:Form } ?c a ?t }")
    assert {(i, e["attributes"]["stereotype"]) for i, e in _elements(doc, "ifml.ViewComponent").items()} == {
        (c, STEREOTYPES[t]) for c, t in kinds
    }


@MODELS
def test_parameters_are_fields_and_bindings_keep_their_ends(trig):
    doc = _export(trig)
    fields = {(c, f) for c, e in _elements(doc, "ifml.ViewComponent").items() for f in e["attributes"]["fields"]}
    assert fields == _pairs(trig, "SELECT ?c ?p { ?c ifml:hasParameter ?p }")
    flows = {**_elements(doc, "ifml.NavigationFlow"), **_elements(doc, "ifml.DataFlow")}
    bindings = {(f, b["output"], b["input"]) for f, e in flows.items() for b in e["attributes"]["bindings"]}
    assert bindings == _pairs(
        trig, "SELECT ?f ?s ?t { ?f ifml:binds ?b . ?b ifml:sourceParameter ?s ; ifml:targetParameter ?t }"
    )


def test_the_chat_app_binds_the_selected_conversation():
    flow = _elements(_export(CHAT), "ifml.DataFlow")["list_to_thread"]
    assert flow["attributes"]["bindings"] == [{"output": "selected_conversation", "input": "conversation"}]


@MODELS
def test_every_view_element_and_event_has_the_graphics_ifmledit_loads(trig):
    for e in _export(trig)["elements"]:
        graphics = e["metadata"].get("graphics", {})
        if e["type"] in ("ifml.ViewContainer", "ifml.ViewComponent"):
            assert set(graphics) == {"position", "size"}, e["id"]
        elif e["type"] == "ifml.Event":
            assert set(graphics) == {"position", "name"}, e["id"]
        else:
            assert e["metadata"] == {}, e["id"]


@MODELS
def test_children_lie_inside_their_container(trig):
    doc = _export(trig)
    box = {e["id"]: e["metadata"]["graphics"] for e in doc["elements"] if "size" in e["metadata"].get("graphics", {})}
    for parent, child in _relations(doc, "hierarchy", "parent", "child"):
        if child not in box:
            continue
        p, c = box[parent], box[child]
        assert p["position"]["x"] < c["position"]["x"]
        assert c["position"]["x"] + c["size"]["width"] < p["position"]["x"] + p["size"]["width"]
        assert p["position"]["y"] < c["position"]["y"]
        assert c["position"]["y"] + c["size"]["height"] < p["position"]["y"] + p["size"]["height"]


@MODELS
def test_output_is_sorted_and_byte_identical_across_runs(trig):
    text = generate(load(trig))[FILE]
    assert text == generate(load(trig))[FILE]
    doc = json.loads(text)
    ids = [e["id"] for e in doc["elements"]]
    assert ids == sorted(ids)
    assert doc["seams"] == {"generator": "seams_gen ifmledit", "model_hash": load(trig).hash}


def test_unmapped_terms_are_ifml_vocabulary_and_absent_from_the_export():
    vocabulary = {str(s) for s in Graph().parse(ROOT / "ontology" / "ifml.ttl").subjects()}
    terms = [term for term, _ in UNMAPPED]
    assert terms == sorted(terms)
    assert all(str(t).startswith(str(IFML)) and str(t) in vocabulary for t in terms)
    text = generate(load(CHAT))[FILE]
    for t in terms:
        assert local_name(t) not in text


def test_the_cli_writes_the_file_and_names_the_unmapped_terms(tmp_path, capsys):
    assert main(["ifmledit", str(CHAT), "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [FILE]
    assert (tmp_path / FILE).read_text(encoding="utf-8") == generate(load(CHAT))[FILE]
    err = capsys.readouterr().err
    assert "no IFMLEdit counterpart" in err
    assert all(f"ifml:{local_name(t)}" in err for t, _ in UNMAPPED)
    assert "{" not in err


def _edited_chat(tmp_path: Path, old: str, new: str) -> Path:
    text = CHAT.read_text(encoding="utf-8")
    assert old in text
    trig = tmp_path / "chat-app.trig"
    trig.write_text(text.replace(old, new), encoding="utf-8")
    return trig


def test_a_model_without_an_interaction_model_exits_2(tmp_path, capsys):
    trig = _edited_chat(tmp_path, ":chat_ifml a seam:Model , ifml:InteractionModel ;", ":chat_ifml a seam:Model ;")
    out = tmp_path / "out"
    assert main(["ifmledit", str(trig), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "rdf-syntax-ns#type" in err and "ifml:InteractionModel" in err
    assert not out.exists()


def test_a_component_in_two_containers_names_ifml_contains(tmp_path):
    trig = _edited_chat(
        tmp_path,
        ":chat_page a ifml:ViewContainer ;",
        ':side a ifml:ViewContainer ; rdfs:label "Side" ; ifml:contains :compose_form .\n'
        "    :chat_page a ifml:ViewContainer ;",
    )
    with pytest.raises(GeneratorError) as err:
        generate(load(trig))
    assert err.value.subject.endswith("compose_form")
    assert err.value.predicate == str(IFML.contains)


def test_an_event_without_an_owner_names_ifml_has_event(tmp_path):
    trig = _edited_chat(tmp_path, "ifml:hasEvent :send_message ;", "")
    with pytest.raises(GeneratorError) as err:
        generate(load(trig))
    assert err.value.subject.endswith("send_message")
    assert err.value.predicate == str(IFML.hasEvent)


def test_a_flow_with_two_targets_names_ifml_target(tmp_path):
    trig = _edited_chat(
        tmp_path,
        "ifml:source :send_message ; ifml:target :message_thread ;",
        "ifml:source :send_message ; ifml:target :message_thread , :conversation_list ;",
    )
    with pytest.raises(GeneratorError) as err:
        generate(load(trig))
    assert err.value.subject.endswith("send_to_thread")
    assert err.value.predicate == str(IFML.target)
