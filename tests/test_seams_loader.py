"""seams.load, the model hash and payload resolution (M010/S02, backlog L2, D034)."""

import re
from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from rdflib.compare import isomorphic

import seams_runtime

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"
EXPENSES_DIR = ROOT / "examples/expenses/chapter-08"
EXPENSES = EXPENSES_DIR / "expenses.trig"
CHAT_GENERATED = ROOT / "examples/chat-app/generated/templates/chat_page.html"

TRIG_A = """@prefix : <https://example.org/a#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:g { :alpha rdfs:label "Alpha" . }
"""
TRIG_B = """@prefix : <https://example.org/b#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:g { :beta rdfs:label "Beta" . }
"""
MISSING_PAYLOAD = """@prefix seam: <https://w3id.org/seams/seam#> .
@prefix : <https://example.org/m#> .
:g { :proc seam:renderPayload <gone.bpmn> . }
"""


def _committed_hash(path: Path) -> str:
    match = re.search(r"model-hash: (sha256:[0-9a-f]{64})", path.read_text(encoding="utf-8"))
    assert match, f"no model-hash header in {path}"
    return match.group(1)


@pytest.mark.parametrize("path", [CHAT, EXPENSES], ids=["chat-app", "expenses"])
def test_file_hash_matches_runtime(path):
    assert seams.load(path).hash == seams_runtime.model_hash(path)


def test_file_hash_matches_committed_generated_header():
    assert seams.load(CHAT).hash == _committed_hash(CHAT_GENERATED)
    assert seams.model_hash(CHAT) == _committed_hash(CHAT_GENERATED)


def test_hash_is_cached_per_instance():
    model = seams.load(CHAT)
    assert model.hash is model.hash


def test_file_model_attributes():
    model = seams.load(CHAT)
    assert model.path == CHAT
    assert model.base_dir == CHAT.parent
    assert model.files == (CHAT,)
    assert model.subject == URIRef(CHAT.as_uri())


def test_directory_merges_every_trig(tmp_path):
    (tmp_path / "b.trig").write_text(TRIG_B, encoding="utf-8")
    (tmp_path / "a.trig").write_text(TRIG_A, encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.trig").write_text(TRIG_A.replace("alpha", "gamma"), encoding="utf-8")
    model = seams.load(tmp_path)
    assert model.files == (tmp_path / "a.trig", tmp_path / "b.trig")
    assert model.path == tmp_path and model.base_dir == tmp_path
    assert model.label("https://example.org/a#alpha") == "Alpha"
    assert model.label("https://example.org/b#beta") == "Beta"
    assert model.label("https://example.org/a#gamma") == "gamma"  # not recursive


def test_directory_hash_frames_each_trig(tmp_path):
    (tmp_path / "a.trig").write_text(TRIG_A, encoding="utf-8")
    first = seams.load(tmp_path).hash
    assert first != seams.load(tmp_path / "a.trig").hash
    (tmp_path / "b.trig").write_text(TRIG_B, encoding="utf-8")
    assert seams.load(tmp_path).hash != first


def test_expenses_directory_equals_its_file():
    from_dir = seams.load(EXPENSES_DIR)
    from_file = seams.load(EXPENSES)
    assert from_dir.files == (EXPENSES,)
    # Blank node ids differ per parse, so compare each named graph by isomorphism.
    names = {g.identifier for g in from_file.ds.graphs()}
    assert {g.identifier for g in from_dir.ds.graphs()} == names
    for name in names:
        assert isomorphic(from_dir.ds.graph(name), from_file.ds.graph(name)), name
    assert from_dir.payloads() == from_file.payloads()


def test_env_variable_names_the_model(monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", str(CHAT))
    assert seams.load().path == CHAT


def test_explicit_path_beats_env(monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", str(CHAT))
    assert seams.load(EXPENSES).path == EXPENSES


def test_no_path_and_no_env_raises(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)
    with pytest.raises(ValueError, match="SEAMS_MODEL"):
        seams.load()


def test_empty_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("SEAMS_MODEL", "")
    with pytest.raises(ValueError, match="SEAMS_MODEL"):
        seams.load()


def test_missing_payload_is_a_resolution_error(tmp_path):
    (tmp_path / "m.trig").write_text(MISSING_PAYLOAD, encoding="utf-8")
    model = seams.load(tmp_path / "m.trig")
    with pytest.raises(seams.ResolutionError) as err:
        model.payloads()
    assert err.value.predicate == str(seams.SEAM.renderPayload)
    assert "https://example.org/m#proc" in str(err.value)
    assert "not found" in str(err.value)
    with pytest.raises(seams.ResolutionError):
        model.hash  # noqa: B018
    with pytest.raises(seams.ResolutionError):
        model.payload_path("https://example.org/m#proc")


def test_payload_path_without_render_payload_raises():
    with pytest.raises(seams.ResolutionError) as err:
        seams.load(CHAT).payload_path("https://example.org/nothing")
    assert err.value.predicate == str(seams.SEAM.renderPayload)


def test_directory_without_trig_raises(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=re.escape(str(tmp_path))):
        seams.load(tmp_path)


def test_payloads_are_sorted_and_relative():
    payloads = seams.load(EXPENSES).payloads()
    rels = [rel for rel, _ in payloads]
    assert rels == sorted(rels)
    assert rels == ["approval.bpmn", "approval.dmn", "payout.bpmn", "payout.dmn"]
    for rel, path in payloads:
        assert not Path(rel).is_absolute()
        assert path == EXPENSES_DIR / rel


def test_payload_path_matches_runtime():
    model = seams.load(CHAT)
    graph = seams_runtime.ModelGraph(CHAT)
    for m, _ in model.ds.subject_objects(seams.SEAM.renderPayload):
        assert model.payload_path(m) == graph.payload_path(m)


def test_module_payload_path(tmp_path):
    assert seams.payload_path("https://example.org/x/flow.bpmn", tmp_path) == tmp_path / "flow.bpmn"
    assert seams.payload_path("file:///abs/dir/flow%20a.bpmn", tmp_path) == Path("/abs/dir/flow a.bpmn")


def test_prebuilt_dataset_is_used():
    ds = seams.load(CHAT).ds
    assert seams.Model(CHAT, dataset=ds).ds is ds


def test_curie_and_label():
    model = seams.load(CHAT)
    seam_iri = model.curie("seam:renderPayload")
    assert seam_iri == seams.SEAM.renderPayload
    assert model.curie(seam_iri) is seam_iri
    with pytest.raises(ValueError):
        model.curie("nocolon")
    with pytest.raises(seams.ResolutionError):
        model.curie("unbound:x")
    assert model.label("https://example.org/no#label") == "label"


def test_resolution_error_to_dict():
    err = seams.ResolutionError(URIRef("https://example.org/s"), seams.SEAM.reads, "why")
    assert isinstance(err, seams.SeamsError) and isinstance(err, LookupError)
    assert str(err) == f"cannot resolve https://example.org/s: missing {seams.SEAM.reads} (why)"
    d = err.to_dict()
    assert set(d) == {"type", "message", "http_status", "subject", "predicate", "detail"}
    assert d["type"] == "ResolutionError" and d["http_status"] == 500


def test_local_name():
    assert seams.local_name("https://w3id.org/seams/seam#renderPayload") == "renderPayload"
    assert seams.local_name("http://www.w3.org/ns/odrl/2/use") == "use"
