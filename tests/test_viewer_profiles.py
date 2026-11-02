"""Domain profiles (ADR-0018, backlog I5, M019/S06).

viewer/profiles.py resolves the profile a model names by seam:conformsTo from the
profiles/*/profile.ttl packages in the model directory. These tests use
tests/fixtures/ as the model directory, so the sample profile in
tests/fixtures/profiles/expense/ is found, and tmp_path copies for the broken cases.
Expected classes, generators and labels are read from the fixture graph, not repeated.

The viewer tests at the end (M019/S06/T03) copy the expense tutorial's chapter 4 to
tmp_path, add the sample profile and one seam:conformsTo triple to the copy, and
drive the edit-mode viewer through TestClient: the palette, the health merge, the
preview's generator subset, and no change at all for a model with no profile.
"""

import html
import logging
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pyshacl
import pytest
import rdflib
from fastapi.testclient import TestClient
from rdflib import RDF, RDFS, SKOS, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import SEAM, ResolutionError  # noqa: E402

from viewer import app as viewer_app  # noqa: E402
from viewer import editing, validation  # noqa: E402
from viewer.profiles import Profile, resolve_profile  # noqa: E402
from viewer.validation import ONTOLOGY_FILES, SHAPES_FILE  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
PROFILE_DIR = FIXTURES / "profiles" / "expense"
PROFILE_TTL = PROFILE_DIR / "profile.ttl"
MODEL = URIRef("https://example.org/expenses/expenses_model")
SEAMS_GRAPH = URIRef("https://example.org/expenses/seams")


def fixture_graph() -> rdflib.Graph:
    return rdflib.Graph().parse(PROFILE_TTL, format="turtle")


def fixture_iri() -> URIRef:
    (iri,) = set(fixture_graph().subjects(RDF.type, SEAM.Profile))
    assert isinstance(iri, URIRef)
    return iri


def model(*profiles: URIRef) -> rdflib.Dataset:
    """A dataset whose seams graph states seam:conformsTo for each profile."""
    ds = rdflib.Dataset()
    seams_graph = ds.graph(SEAMS_GRAPH)
    seams_graph.add((MODEL, RDF.type, SEAM.Model))
    for profile in profiles:
        seams_graph.add((MODEL, SEAM.conformsTo, profile))
    return ds


def resolved() -> Profile:
    profile = resolve_profile(model(fixture_iri()), FIXTURES)
    assert profile is not None
    return profile


def copy_profile(model_dir: Path, name: str) -> Path:
    target = model_dir / "profiles" / name
    shutil.copytree(PROFILE_DIR, target)
    return target


# ---------------------------------------------------------------- resolution


def test_resolves_the_profile_the_model_conforms_to():
    profile = resolved()
    assert profile.iri == fixture_iri()
    assert (profile.iri, RDF.type, SEAM.Profile) in profile.graph


def test_classes_are_the_offered_classes_sorted():
    profile = resolved()
    offered = set(fixture_graph().objects(fixture_iri(), SEAM.offersClass))
    assert len(offered) > 1
    assert set(profile.classes) == offered
    assert list(profile.classes) == sorted(offered)


def test_generators_are_the_used_generator_names_sorted():
    profile = resolved()
    names = {str(o) for o in fixture_graph().objects(fixture_iri(), SEAM.usesGenerator)}
    assert len(names) > 1
    assert list(profile.generators) == sorted(names)
    assert all(isinstance(name, str) for name in profile.generators)


def test_labels_prefer_skos_pref_label_then_rdfs_label():
    profile = resolved()
    graph = fixture_graph()
    both = [c for c in profile.classes if graph.value(c, SKOS.prefLabel) and graph.value(c, RDFS.label)]
    rdfs_only = [c for c in profile.classes if graph.value(c, RDFS.label) and not graph.value(c, SKOS.prefLabel)]
    neither = [c for c in profile.classes if not graph.value(c, RDFS.label) and not graph.value(c, SKOS.prefLabel)]
    assert both and rdfs_only and neither, "the fixture covers every label case"
    for cls in both:
        assert profile.labels[cls] == str(graph.value(cls, SKOS.prefLabel))
    for cls in rdfs_only:
        assert profile.labels[cls] == str(graph.value(cls, RDFS.label))
    for cls in neither:
        assert cls not in profile.labels


def test_shapes_are_parsed_from_the_profile_shapes_files():
    profile = resolved()
    (name,) = {str(o) for o in fixture_graph().objects(fixture_iri(), SEAM.profileShapes)}
    expected = rdflib.Graph().parse(PROFILE_DIR / name, format="turtle")
    assert len(profile.shapes) == len(expected) > 0
    assert set(profile.shapes.subjects(RDF.type, rdflib.SH.NodeShape)) == set(
        expected.subjects(RDF.type, rdflib.SH.NodeShape)
    )


def test_a_profile_without_shapes_has_an_empty_shapes_graph(tmp_path):
    target = copy_profile(tmp_path, "expense")
    graph = fixture_graph()
    graph.remove((None, SEAM.profileShapes, None))
    graph.serialize(target / "profile.ttl", format="turtle")
    profile = resolve_profile(model(fixture_iri()), tmp_path)
    assert profile is not None
    assert len(profile.shapes) == 0


def test_resolution_is_deterministic():
    first, second = resolved(), resolved()
    assert (first.iri, first.classes, first.generators, first.labels) == (
        second.iri,
        second.classes,
        second.generators,
        second.labels,
    )


def test_the_profile_is_not_merged_into_the_model():
    ds = model(fixture_iri())
    before = len(ds)
    resolve_profile(ds, FIXTURES)
    assert len(ds) == before


# ---------------------------------------------------------------- no profile


def test_no_conforms_to_gives_none():
    assert resolve_profile(model(), FIXTURES) is None


def test_no_conforms_to_reads_no_profile_file(tmp_path):
    target = copy_profile(tmp_path, "expense")
    (target / "profile.ttl").write_text("this is not turtle {")
    assert resolve_profile(model(), tmp_path) is None


# ---------------------------------------------------------------- errors


def test_a_missing_profile_names_the_predicate(tmp_path):
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri()), tmp_path)
    assert err.value.subject == str(MODEL)
    assert err.value.predicate == str(SEAM.conformsTo)
    assert str(fixture_iri()) in err.value.detail


def test_an_undeclared_profile_iri_is_a_resolution_error():
    other = URIRef(str(fixture_iri()) + "-other")
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(other), FIXTURES)
    assert err.value.predicate == str(SEAM.conformsTo)
    assert str(other) in err.value.detail


def test_two_profiles_declaring_the_iri_are_a_resolution_error(tmp_path):
    copy_profile(tmp_path, "a")
    copy_profile(tmp_path, "b")
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri()), tmp_path)
    assert err.value.predicate == str(SEAM.conformsTo)
    assert "profiles/a/profile.ttl, profiles/b/profile.ttl" in err.value.detail
    assert str(tmp_path) not in err.value.detail


def test_a_model_stating_two_profiles_is_a_resolution_error():
    other = URIRef(str(fixture_iri()) + "-other")
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri(), other), FIXTURES)
    assert err.value.subject == str(MODEL)
    assert err.value.predicate == str(SEAM.conformsTo)
    assert f"{fixture_iri()}, {other}" in err.value.detail


def test_a_literal_profile_is_a_resolution_error():
    ds = model()
    ds.graph(SEAMS_GRAPH).add((MODEL, SEAM.conformsTo, rdflib.Literal(str(fixture_iri()))))
    with pytest.raises(ResolutionError) as err:
        resolve_profile(ds, FIXTURES)
    assert err.value.predicate == str(SEAM.conformsTo)


def test_an_unparseable_profile_names_the_file(tmp_path):
    target = copy_profile(tmp_path, "expense")
    (target / "profile.ttl").write_text("this is not turtle {")
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri()), tmp_path)
    assert err.value.predicate == str(SEAM.conformsTo)
    assert err.value.detail.startswith("profiles/expense/profile.ttl: ")


def test_a_missing_shapes_file_names_profile_shapes(tmp_path):
    target = copy_profile(tmp_path, "expense")
    (name,) = {str(o) for o in fixture_graph().objects(fixture_iri(), SEAM.profileShapes)}
    (target / name).unlink()
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri()), tmp_path)
    assert err.value.subject == str(fixture_iri())
    assert err.value.predicate == str(SEAM.profileShapes)
    assert err.value.detail == f"profiles/expense/{name}: no such file"


def test_an_unparseable_shapes_file_names_profile_shapes(tmp_path):
    target = copy_profile(tmp_path, "expense")
    (name,) = {str(o) for o in fixture_graph().objects(fixture_iri(), SEAM.profileShapes)}
    (target / name).write_text("this is not turtle {")
    with pytest.raises(ResolutionError) as err:
        resolve_profile(model(fixture_iri()), tmp_path)
    assert err.value.subject == str(fixture_iri())
    assert err.value.predicate == str(SEAM.profileShapes)
    assert err.value.detail.startswith(f"profiles/expense/{name}: ")


# ---------------------------------------------------------------- seam shapes


def seam_shape_messages(data: rdflib.Graph) -> set[str]:
    union = rdflib.Graph()
    for path in ONTOLOGY_FILES:
        union.parse(path, format="turtle")
    union += data
    _conforms, report, _text = pyshacl.validate(union, shacl_graph=str(SHAPES_FILE), inference="none")
    assert isinstance(report, rdflib.Graph)
    return {str(m) for m in report.objects(None, rdflib.SH.resultMessage)}


def test_the_profile_and_its_shapes_pass_the_seam_shapes():
    profile = resolved()
    assert seam_shape_messages(profile.graph + profile.shapes) == set()


def test_profile_shape_rejects_a_literal_offered_class():
    graph = fixture_graph()
    graph.add((fixture_iri(), SEAM.offersClass, rdflib.Literal("ifml:Form")))
    assert seam_shape_messages(graph) == {"A seam:Profile's seam:offersClass values are class IRIs."}


def test_profile_shape_rejects_a_generator_named_by_iri():
    graph = fixture_graph()
    graph.add((fixture_iri(), SEAM.usesGenerator, URIRef("https://example.org/generators/htmx")))
    assert seam_shape_messages(graph) == {"A seam:Profile's seam:usesGenerator values are generator names, as strings."}


def test_profile_shape_rejects_a_shapes_path_given_as_iri():
    graph = fixture_graph()
    graph.add((fixture_iri(), SEAM.profileShapes, URIRef("https://example.org/shapes.ttl")))
    assert seam_shape_messages(graph) == {
        "A seam:Profile's seam:profileShapes values are paths relative to the profile directory, as strings."
    }


def test_offered_class_shape_rejects_two_pref_labels():
    profile = resolved()
    cls = next(c for c in profile.classes if (c, SKOS.prefLabel, None) in profile.graph)
    graph = fixture_graph()
    graph.add((cls, SKOS.prefLabel, rdflib.Literal(profile.labels[cls] + " (second)")))
    assert seam_shape_messages(graph) == {"A class a profile offers has at most one skos:prefLabel."}


def test_offered_class_shape_rejects_two_rdfs_labels():
    profile = resolved()
    cls = next(c for c in profile.classes if (c, RDFS.label, None) in profile.graph)
    graph = fixture_graph()
    graph.add((cls, RDFS.label, rdflib.Literal("second label")))
    assert seam_shape_messages(graph) == {"A class a profile offers has at most one rdfs:label."}


# ---------------------------------------------------------------- the viewer


CHAPTER = ROOT / "examples" / "expenses" / "chapter-04"
SEAMS_BLOCK = "<urn:seams:graph:seams> {\n"


@pytest.fixture
def restore_viewer(monkeypatch):
    """Put the viewer back on its own model, edit mode off, after the test."""
    original = viewer_app.MODEL_PATH
    validation._clear_cache()
    yield
    monkeypatch.delenv(viewer_app.EDIT_ENV, raising=False)
    viewer_app.configure(original)


def chapter_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(CHAPTER, tmp_path / "chapter-04", ignore=shutil.ignore_patterns("generated")))


def attach(app_dir: Path, iri: URIRef) -> None:
    """Add the sample profile package and ``<root model> seam:conformsTo <iri>``."""
    shutil.copytree(PROFILE_DIR, app_dir / "profiles" / PROFILE_DIR.name)
    trig = app_dir / "expenses.trig"
    root = seams_root(trig)
    text = trig.read_text(encoding="utf-8")
    assert text.count(SEAMS_BLOCK) == 1
    trig.write_text(text.replace(SEAMS_BLOCK, f"{SEAMS_BLOCK}    <{root}> seam:conformsTo <{iri}> .\n"), "utf-8")


def seams_root(trig: Path) -> URIRef:
    """The chapter's C4 model, the subject that states the conformance."""
    ds = rdflib.Dataset(default_union=True)
    ds.parse(trig, format="trig")
    (root,) = set(ds.subjects(SEAM.notation, SEAM.C4))
    assert isinstance(root, URIRef)
    return root


def open_viewer(app_dir: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv(viewer_app.EDIT_ENV, "1")
    viewer_app.configure(app_dir / "expenses.trig")
    return TestClient(viewer_app.app)


@pytest.fixture
def app_dir(tmp_path) -> Path:
    return chapter_copy(tmp_path)


@pytest.fixture
def profiled(app_dir, monkeypatch, restore_viewer) -> TestClient:
    attach(app_dir, fixture_iri())
    return open_viewer(app_dir, monkeypatch)


@pytest.fixture
def plain(app_dir, monkeypatch, restore_viewer) -> TestClient:
    return open_viewer(app_dir, monkeypatch)


def root_page(client: TestClient) -> str:
    response = client.get(f"/view/{quote(viewer_app.root_iri(), safe='')}")
    assert response.status_code == 200
    return response.text


def palette_section(page: str) -> str:
    match = re.search(r'<section class="edit-palette".*?</section>', page, re.DOTALL)
    assert match is not None
    return match.group(0)


def instance_of(cls: URIRef) -> str:
    """The first element of the loaded model typed ``cls``, by IRI."""
    found = sorted(str(s) for s in viewer_app.get_graph().subjects(RDF.type, cls))
    assert found, cls
    return found[0]


def test_resolving_the_model_logs_the_profile_counts(app_dir, monkeypatch, restore_viewer, caplog):
    attach(app_dir, fixture_iri())
    open_viewer(app_dir, monkeypatch)
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        viewer_app.get_model()
    profile = resolved()
    line = f"profile {profile.iri}: {len(profile.classes)} class(es), {len(profile.generators)} generator(s)"
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("profile ")] == [line]


def test_palette_offers_only_the_profile_classes_with_its_labels(profiled):
    section = palette_section(root_page(profiled))
    profile = resolved()
    offered = re.findall(r'data-class="([^"]+)"', section)
    assert offered == [str(c) for c in profile.classes]
    for cls, label in profile.labels.items():
        assert f">{html.escape(label)}</li>" in section, cls
    assert [e["label"] for e in editing.palette(profile)] == [
        html.unescape(t) for t in re.findall(r"<li [^>]*>([^<]*)</li>", section)
    ]


def test_an_unlabelled_class_keeps_the_editors_label():
    profile = resolved()
    (entry,) = [e for e in editing.palette(profile) if URIRef(e["iri"]) not in profile.labels]
    assert entry["label"] not in profile.labels.values()
    assert entry["label"] in (entry["qname"], str(editing._ontology_graph().value(URIRef(entry["iri"]), RDFS.label)))


def test_health_names_the_profile(profiled):
    page = root_page(profiled)
    assert f'data-profile="{fixture_iri()}"' in page
    health = viewer_app.model_health(viewer_app.get_graph())
    assert health["profile"]["iri"] == str(fixture_iri()) and health["profile"]["error"] is None


def test_out_of_profile_classes_are_flagged_not_refused(profiled):
    profile = resolved()
    health = viewer_app.model_health(viewer_app.get_graph())
    flagged = {(w["focusNode"], w["path"]) for w in health["warnings"] if str(profile.iri) in w["message"]}
    ds = viewer_app.get_graph()
    typed = {(str(s), c) for s, c in ds.subject_objects(RDF.type) if isinstance(s, URIRef)}
    offered_elements = {s for s, c in typed if c in profile.classes}
    others = {s for s, c in typed if s not in offered_elements}
    assert flagged, "chapter 4 uses classes the sample profile does not offer"
    assert all(path == str(RDF.type) for _s, path in flagged)
    assert {s for s, _p in flagged} <= others
    assert not {s for s, _p in flagged} & (offered_elements - others)


def test_a_profile_shape_violation_is_saved_and_flagged(profiled, app_dir):
    profile = resolved()
    shape = next(iter(profile.shapes.subjects(RDF.type, rdflib.SH.NodeShape)))
    cls = profile.shapes.value(shape, rdflib.SH.targetClass)
    prop = profile.shapes.value(shape, rdflib.SH.property)
    path = str(profile.shapes.value(prop, rdflib.SH.path))
    message = str(profile.shapes.value(prop, rdflib.SH.message))
    assert isinstance(cls, URIRef)
    element = instance_of(cls)
    assert message not in root_page(profiled)

    form = profiled.get(f"/edit/{quote(element, safe='')}")
    assert f'data-path="{path}"' in form.text, "the profile's shape adds its field to the form"

    trig = app_dir / "expenses.trig"
    before = trig.read_text(encoding="utf-8")
    response = profiled.post(f"/edit/{quote(element, safe='')}", data={"field": path, "value": ""})
    assert response.status_code == 200
    assert 'class="edit-saved"' in response.text
    assert trig.read_text(encoding="utf-8") != before
    assert viewer_app.get_graph().value(URIRef(element), URIRef(path)) is None
    assert 'id="health-panel" hx-swap-oob="true"' in response.text
    assert html.escape(message) in response.text
    health = viewer_app.model_health(viewer_app.get_graph())
    assert health["conforms"] is False
    assert any(v["focusNode"] == element and v["message"] == message for v in health["violations"])


def test_preview_runs_only_the_profile_generators(app_dir, monkeypatch, restore_viewer):
    attach(app_dir, fixture_iri())
    target = app_dir / "profiles" / PROFILE_DIR.name / "profile.ttl"
    graph = rdflib.Graph().parse(target, format="turtle")
    kept = sorted(str(o) for o in graph.objects(fixture_iri(), SEAM.usesGenerator))[0]
    unconfigured = "not-in-the-project"
    graph.remove((fixture_iri(), SEAM.usesGenerator, None))
    graph.add((fixture_iri(), SEAM.usesGenerator, rdflib.Literal(kept)))
    graph.add((fixture_iri(), SEAM.usesGenerator, rdflib.Literal(unconfigured)))
    graph.serialize(target, format="turtle")
    client = open_viewer(app_dir, monkeypatch)

    response = client.get("/edit/preview")
    assert response.status_code == 200
    generators = set(re.findall(r"<summary><code>[^<]+</code> \(([^)]+)\)</summary>", response.text))
    assert generators == {kept}
    assert f'data-generators="{" ".join(sorted([kept, unconfigured]))}"' in response.text
    assert f'class="preview-unconfigured" data-generator="{unconfigured}"' in response.text
    assert 'class="preview-error"' not in response.text


def test_preview_with_every_profile_generator_matches_no_profile(app_dir, tmp_path, monkeypatch, restore_viewer):
    plain_dir = chapter_copy(tmp_path / "plain")
    client = open_viewer(plain_dir, monkeypatch)
    plain_paths = re.findall(r'data-path="([^"]+)"', client.get("/edit/preview").text)

    attach(app_dir, fixture_iri())
    client = open_viewer(app_dir, monkeypatch)
    profiled_paths = re.findall(r'data-path="([^"]+)"', client.get("/edit/preview").text)
    assert plain_paths and profiled_paths == plain_paths


def test_a_resolution_error_is_a_health_fact(app_dir, monkeypatch, restore_viewer, caplog):
    missing = URIRef(str(fixture_iri()) + "-missing")
    attach(app_dir, missing)
    client = open_viewer(app_dir, monkeypatch)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        page = root_page(client)
    error = viewer_app.model_health(viewer_app.get_graph())["profile"]["error"]
    assert error["subject"] == str(seams_root(app_dir / "expenses.trig"))
    assert error["predicate"] == str(SEAM.conformsTo)
    assert str(missing) in error["detail"]
    assert f'class="health-profile-error" role="alert" data-subject="{error["subject"]}"' in page
    assert f'data-predicate="{SEAM.conformsTo}"' in page
    assert html.escape(error["detail"]) in page
    assert 'class="edit-palette"' not in page
    assert any("profile not resolved" in r.getMessage() for r in caplog.records)
    # The viewer carries on as if no profile were attached.
    assert viewer_app.get_profile() is None
    assert "data-generators=" not in client.get("/edit/preview").text


def test_no_profile_means_no_change(plain, app_dir, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        page = root_page(plain)
    assert viewer_app.get_profile() is None
    assert not any(r.getMessage().startswith("profile") for r in caplog.records)
    assert 'class="edit-palette"' not in page
    assert 'class="health-profile' not in page
    health = viewer_app.model_health(viewer_app.get_graph())
    assert "profile" not in health
    assert health == {
        **validation.get_model_conformance(viewer_app.get_graph()),
        "liftedIris": validation.get_lifted_iri_health(viewer_app.get_graph(), app_dir),
    }
    preview = plain.get("/edit/preview").text
    assert "data-generators=" not in preview and 'class="preview-error"' not in preview
    shape_cls = next(iter(resolved().shapes.objects(None, rdflib.SH.targetClass)))
    assert isinstance(shape_cls, URIRef)
    element = instance_of(shape_cls)
    assert editing.form_fields(viewer_app.get_graph(), element) == viewer_app._form_fields(element)
