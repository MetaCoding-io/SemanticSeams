"""The shared change classification and the vocabulary breaking-change gate (M023/S02, ADR-0021 section 7).

``seams_cli.classification`` holds the verdicts and the ``Change`` record ``seams diff``
uses, plus the rules for vocabulary terms; ``seams_cli.vocabulary_gate`` compares two
vocabulary dirs and fails a breaking change without a major bump or without the step's
migration file. The cases run over temp copies of ``ontology/``, over the fixture tree
tests/fixtures/vocab-v2 (seam 2.0), and, when git can read it, over the ``ontology/``
committed at HEAD against the working tree.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import seams_cli.diff as diff
from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from seams_cli import ProjectError
from seams_cli.classification import BREAKING, COMPATIBLE, VOCABULARY, Change, classify_terms
from seams_cli.vocabulary_gate import diff_vocabularies, gate

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
FIXTURE = ROOT / "tests" / "fixtures" / "vocab-v2"

SH = Namespace("http://www.w3.org/ns/shacl#")
DCT = Namespace("http://purl.org/dc/terms/")
ARCH = Namespace("https://w3id.org/seams/arch#")
IFML = Namespace("https://w3id.org/seams/ifml#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
EX = Namespace("https://w3id.org/seams/ex#")


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Two copies of the shipped ontology/: OLD and NEW."""
    old, new = tmp_path / "old", tmp_path / "new"
    shutil.copytree(ONTOLOGY, old)
    shutil.copytree(ONTOLOGY, new)
    return old, new


def _edit(path: Path, change: Callable[[Graph], object]) -> None:
    graph = Graph().parse(path, format="turtle")
    change(graph)
    path.write_text(graph.serialize(format="turtle"), encoding="utf-8")


def _bump(directory: Path, name: str, version: str) -> None:
    ontology = URIRef(f"https://w3id.org/seams/{name}")

    def change(graph: Graph) -> None:
        graph.set((ontology, OWL.versionIRI, URIRef(f"{ontology}/{version}")))
        graph.set((ontology, OWL.versionInfo, Literal(version)))

    _edit(directory / f"{name}.ttl", change)


def _step(directory: Path, name: str, step: str) -> None:
    path = directory / "migrations" / name / f"{step}.ru"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# no-op step\nDELETE WHERE { GRAPH ?g { ?s <urn:x:none> ?o } }\n", encoding="utf-8")


def _kinds(changes: list[Change]) -> list[tuple[str, str, str]]:
    return [(c.verdict, c.kind, c.subject) for c in changes]


# --- the shared module -----------------------------------------------------------


def test_diff_uses_the_shared_verdicts_and_record():
    assert diff.Change is Change
    assert (diff.COMPATIBLE, diff.BREAKING) == (COMPATIBLE, BREAKING) == ("compatible", "breaking")


def test_identical_dirs_have_no_changes(dirs):
    old, new = dirs
    assert diff_vocabularies(old, new) == {}
    assert gate(old, new) == []


# --- term rules ------------------------------------------------------------------

MINI = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://w3id.org/seams/ex#> .
ex:Base a rdfs:Class .
ex:Mid a rdfs:Class ; rdfs:subClassOf ex:Base .
ex:Leaf a rdfs:Class ; rdfs:subClassOf ex:Mid .
ex:Other a rdfs:Class .
ex:p a rdf:Property ; rdfs:domain ex:Mid ; rdfs:range ex:Mid .
"""


def _mini(range_: str) -> Graph:
    return Graph().parse(data=MINI.replace("rdfs:range ex:Mid", range_), format="turtle")


@pytest.mark.parametrize(
    ("range_", "verdict"),
    [
        ("rdfs:range ex:Base", COMPATIBLE),
        ("rdfs:comment 'no range'", COMPATIBLE),
        ("rdfs:range ex:Leaf", BREAKING),
        ("rdfs:range ex:Other", BREAKING),
        ("rdfs:range ex:Mid , ex:Other", BREAKING),
    ],
)
def test_a_looser_range_is_compatible_and_a_narrower_or_unrelated_one_breaking(range_, verdict):
    changes = classify_terms(_mini("rdfs:range ex:Mid"), _mini(range_))
    assert _kinds(changes) == [(verdict, "range-changed", str(EX.p))]
    assert changes[0].scopes == (VOCABULARY,)


def test_adding_a_domain_is_breaking_and_dropping_one_compatible():
    without = Graph().parse(data=MINI.replace("rdfs:domain ex:Mid ;", ""), format="turtle")
    assert _kinds(classify_terms(without, _mini("rdfs:range ex:Mid"))) == [(BREAKING, "domain-changed", str(EX.p))]
    assert _kinds(classify_terms(_mini("rdfs:range ex:Mid"), without)) == [(COMPATIBLE, "domain-changed", str(EX.p))]


def test_added_and_deprecated_terms_are_compatible(dirs):
    old, new = dirs
    _edit(new / "arch.ttl", lambda g: g.add((ARCH.Queue, RDF.type, RDFS.Class)))
    _edit(new / "arch.ttl", lambda g: g.add((ARCH.Person, OWL.deprecated, Literal(True))))
    assert diff_vocabularies(old, new) == {
        "arch": [
            Change(COMPATIBLE, "term-deprecated", str(ARCH.Person), "-", (VOCABULARY,)),
            Change(COMPATIBLE, "term-added", str(ARCH.Queue), "-", (VOCABULARY,)),
        ]
    }
    assert gate(old, new) == [], "a compatible change needs no major bump"


def test_a_removed_term_without_a_major_bump_fails(dirs):
    old, new = dirs
    _edit(new / "arch.ttl", lambda g: g.remove((ARCH.Person, None, None)))
    _bump(new, "arch", "1.1")
    assert _kinds(diff_vocabularies(old, new)["arch"]) == [(BREAKING, "term-removed", str(ARCH.Person))]
    assert gate(old, new) == [
        f"arch: 1 breaking change(s) without a major bump (1.0 -> 1.1): term-removed {ARCH.Person}"
    ]


def test_a_renamed_term_is_breaking(dirs):
    old, new = dirs

    def rename(graph: Graph) -> None:
        for p, o in list(graph.predicate_objects(ARCH.Person)):
            graph.add((ARCH.Actor, p, o))
        graph.remove((ARCH.Person, None, None))
        graph.add((ARCH.Actor, DCT.replaces, ARCH.Person))

    _edit(new / "arch.ttl", rename)
    changes = diff_vocabularies(old, new)["arch"]
    assert changes == [
        Change(BREAKING, "term-renamed", str(ARCH.Actor), f"{ARCH.Person} -> {ARCH.Actor}", (VOCABULARY,))
    ]
    assert len(gate(old, new)) == 1


def test_a_major_bump_needs_the_step_file(dirs):
    old, new = dirs
    _edit(new / "arch.ttl", lambda g: g.remove((ARCH.Person, None, None)))
    _bump(new, "arch", "3.0")
    _step(new, "arch", "1-to-2")
    assert gate(old, new) == ["arch: major bump 2 -> 3 without the migration step migrations/arch/2-to-3.ru"]
    _step(new, "arch", "2-to-3")
    assert gate(old, new) == []


def test_a_narrower_range_in_a_shipped_vocabulary_fails_without_a_major(dirs):
    old, new = dirs
    _edit(new / "ifml.ttl", lambda g: g.set((IFML.order, RDFS.range, XSD.positiveInteger)))
    assert _kinds(diff_vocabularies(old, new)["ifml"]) == [(BREAKING, "range-changed", str(IFML.order))]
    assert gate(old, new)[0].startswith("ifml: 1 breaking change(s) without a major bump (1.0 -> 1.0)")


# --- shapes ----------------------------------------------------------------------


def test_a_tighter_shape_is_breaking_for_the_vocabulary_it_targets(dirs):
    old, new = dirs

    def require(graph: Graph) -> None:
        prop = BNode()
        graph.add((SEAMSH.FormWritesShape, SH.property, prop))
        graph.add((prop, SH.path, IFML.isXOR))
        graph.add((prop, SH.minCount, Literal(1)))

    shipped = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
    assert (SEAMSH.FormWritesShape, SH.targetClass, IFML.Form) in shipped
    _edit(new / "shapes" / "seam-shapes.ttl", require)
    changes = diff_vocabularies(old, new)
    assert list(changes) == ["ifml"]
    assert _kinds(changes["ifml"]) == [(BREAKING, "property-added", str(SEAMSH.FormWritesShape))]
    assert gate(old, new)[0].startswith("ifml: 1 breaking change(s) without a major bump")


def test_a_shape_naming_no_vocabulary_term_belongs_to_seam(dirs):
    old, new = dirs
    _edit(new / "shapes" / "seam-shapes.ttl", lambda g: g.add((SEAMSH.Loose, RDF.type, SH.NodeShape)))
    assert _kinds(diff_vocabularies(old, new)["seam"]) == [(COMPATIBLE, "shape-added", str(SEAMSH.Loose))]


# --- versions and files ----------------------------------------------------------


def test_the_seam_2_fixture_is_a_compatible_major_with_its_step():
    changes = diff_vocabularies(ONTOLOGY, FIXTURE)
    assert list(changes) == ["seam"]
    assert {c.verdict for c in changes["seam"]} == {COMPATIBLE}
    assert gate(ONTOLOGY, FIXTURE) == []


def test_going_back_from_the_fixture_fails():
    assert gate(FIXTURE, ONTOLOGY) == ["seam: version goes down, 2.0 -> 1.2"]


def test_a_removed_vocabulary_fails(dirs):
    old, new = dirs
    (new / "verify.ttl").unlink()
    assert gate(old, new) == ["verify: the vocabulary is removed; a removed vocabulary strands every model using it"]


def test_a_new_vocabulary_without_a_version_iri_fails(dirs):
    old, new = dirs
    _edit(new / "state.ttl", lambda g: g.remove((None, OWL.versionIRI, None)))
    assert gate(old, new) == ["state: no owl:versionIRI <https://w3id.org/seams/state/MAJOR.MINOR>"]


def test_an_old_vocabulary_without_a_version_iri_is_at_1_0(dirs):
    old, new = dirs
    _edit(old / "state.ttl", lambda g: g.remove((None, OWL.versionIRI, None)))
    assert gate(old, new) == []


def test_unreadable_files_raise_project_error(dirs):
    old, new = dirs
    (new / "broken.ttl").write_text("this is not turtle", encoding="utf-8")
    with pytest.raises(ProjectError, match="broken.ttl: cannot parse"):
        gate(old, new)
    (new / "broken.ttl").write_text("<urn:x> a <urn:y> .\n", encoding="utf-8")
    with pytest.raises(ProjectError, match="expected one SemanticSeams owl:Ontology"):
        gate(old, new)
    (new / "broken.ttl").unlink()
    _edit(new / "arch.ttl", lambda g: g.set((URIRef("https://w3id.org/seams/arch"), OWL.versionIRI, URIRef("urn:v1"))))
    with pytest.raises(ProjectError, match="expected one owl:versionIRI"):
        gate(old, new)


# --- the real gate: HEAD's ontology/ against the working tree ---------------------


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


def test_the_working_tree_ontology_passes_the_gate_against_head(tmp_path):
    if shutil.which("git") is None or _git("rev-parse", "--verify", "HEAD").returncode != 0:
        pytest.skip("git or a HEAD commit is not available")
    listed = _git("ls-tree", "-r", "--name-only", "HEAD", "--", "ontology")
    assert listed.returncode == 0, listed.stderr
    # Only files tracked at HEAD are read, so no gitignored path is involved.
    for name in listed.stdout.decode().splitlines():
        shown = _git("show", f"HEAD:{name}")
        assert shown.returncode == 0, shown.stderr
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(shown.stdout)
    assert gate(tmp_path / "ontology", ONTOLOGY) == []
