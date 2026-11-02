"""Domain profiles (ADR-0018, backlog I5, M019/S06).

viewer/profiles.py resolves the profile a model names by seam:conformsTo from the
profiles/*/profile.ttl packages in the model directory. These tests use
tests/fixtures/ as the model directory, so the sample profile in
tests/fixtures/profiles/expense/ is found, and tmp_path copies for the broken cases.
Expected classes, generators and labels are read from the fixture graph, not repeated.
"""

import shutil
import sys
from pathlib import Path

import pyshacl
import pytest
import rdflib
from rdflib import RDF, RDFS, SKOS, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import SEAM, ResolutionError  # noqa: E402

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
