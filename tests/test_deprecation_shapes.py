"""Deprecated vocabulary terms and their sh:Warning shapes (M023/S02, ADR-0021 section 6).

Every owl:deprecated term of a vocabulary dir has exactly one sh:Warning shape in
its shapes/seam-shapes.ttl, targeting a predicate with sh:targetSubjectsOf and a
class with sh:targetClass, and every sh:Warning shape targets a deprecated term.
The shipped ontology/ has no deprecated term yet, so the pairing is checked there
and over the fixture tree tests/fixtures/vocab-v2, whose seam 2.0 deprecates the
predicate seam:inModel (which 1-to-2.ru renames) and the class seam:Model.

Warnings never fail: ``seams check`` reports them, and each migration step, as
advisory findings with exit 0; generator preconditions and seams_gen's parity
helper ignore them.
"""

import functools
import shutil
from pathlib import Path

import pytest
import seams
import seams_cli.__main__ as cli
from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from seams_cli import Finding
from seams_cli.__main__ import main
from seams_cli.check import ADVISORY_KINDS, check_migrations, check_project, check_shapes, model_graph
from seams_cli.generate import shape_warnings

from seams_gen.protocol import Generator
from seams_gen.testing import shape_violations

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
FIXTURE = ROOT / "tests" / "fixtures" / "vocab-v2"
FIXTURE_SHAPES = FIXTURE / "shapes" / "seam-shapes.ttl"
CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01"

SH = Namespace("http://www.w3.org/ns/shacl#")
SEAM = Namespace("https://w3id.org/seams/seam#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")
ARCHITECTURE = "https://example.org/expenses/expense_architecture"
MODEL_DEPRECATED = "seam:Model is deprecated since seam 2.0 and goes in seam 3.0."
# The checkpoints declare the shipped seam, 1.4.
SEAM_V1_IMPORT = "<https://w3id.org/seams/seam/1.4>"
IN_MODEL_DEPRECATED = "seam:inModel is deprecated since seam 2.0 and goes in seam 3.0: write seam:partOfModel instead."
CLASSES = (RDFS.Class, OWL.Class)
PROPERTIES = (RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
TARGETS = (SH.targetClass, SH.targetSubjectsOf, SH.targetObjectsOf, SH.targetNode)


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def deprecated_terms(vocab_dir: Path) -> tuple[Graph, list[URIRef]]:
    vocab = Graph()
    for path in sorted(vocab_dir.glob("*.ttl")):
        vocab.parse(path, format="turtle")
    terms = {s for s, o in vocab.subject_objects(OWL.deprecated) if isinstance(s, URIRef) and o.toPython() is True}
    return vocab, sorted(terms)


def pairing_problems(vocab_dir: Path) -> list[str]:
    """Each way the deprecated terms of ``vocab_dir`` and its sh:Warning shapes fail to pair one to one."""
    vocab, deprecated = deprecated_terms(vocab_dir)
    shapes = Graph().parse(vocab_dir / "shapes" / "seam-shapes.ttl", format="turtle")
    warning_shapes = sorted(set(shapes.subjects(SH.severity, SH.Warning)), key=str)
    problems = []
    for term in deprecated:
        types = set(vocab.objects(term, RDF.type))
        if types.intersection(CLASSES):
            target = SH.targetClass
        elif types.intersection(PROPERTIES):
            target = SH.targetSubjectsOf
        else:
            problems.append(f"{term} is deprecated but neither a class nor a property")
            continue
        found = [shape for shape in warning_shapes if (shape, target, term) in shapes]
        if len(found) != 1:
            problems.append(f"{term} has {len(found)} sh:Warning shapes with {target}")
    for shape in warning_shapes:
        targets = [(p, o) for p in TARGETS for o in shapes.objects(shape, p)]
        if not targets:
            problems.append(f"{shape} targets nothing")
        for p, o in targets:
            if p not in (SH.targetClass, SH.targetSubjectsOf) or o not in deprecated:
                problems.append(f"{shape} targets {o} with {p}, not a deprecated term")
    return problems


def fixture_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "vocab"))


def edit_shapes(vocab: Path, old: str, new: str) -> None:
    path = vocab / "shapes" / "seam-shapes.ttl"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


# ── pairing ──


@pytest.mark.parametrize("vocab_dir", [ONTOLOGY, FIXTURE], ids=["shipped", "vocab-v2"])
def test_every_deprecated_term_pairs_with_one_warning_shape(vocab_dir: Path) -> None:
    assert pairing_problems(vocab_dir) == []


def test_the_shipped_ontology_deprecates_nothing_yet() -> None:
    assert deprecated_terms(ONTOLOGY)[1] == []
    shapes = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl", format="turtle")
    assert list(shapes.subjects(SH.severity, SH.Warning)) == []


def test_the_fixture_deprecates_a_predicate_and_a_class() -> None:
    assert deprecated_terms(FIXTURE)[1] == [SEAM.Model, SEAM.inModel]


def test_a_deprecated_term_without_a_warning_shape_is_caught(tmp_path: Path) -> None:
    vocab = fixture_copy(tmp_path)
    edit_shapes(
        vocab,
        "seamsh:ModelDeprecatedShape a sh:NodeShape ;\n    sh:targetClass seam:Model ;\n",
        "seamsh:ModelDeprecatedShape a sh:NodeShape ;\n",
    )
    assert pairing_problems(vocab) == [
        f"{SEAM.Model} has 0 sh:Warning shapes with {SH.targetClass}",
        f"{SEAMSH.ModelDeprecatedShape} targets nothing",
    ]


def test_two_warning_shapes_for_one_term_are_caught(tmp_path: Path) -> None:
    vocab = fixture_copy(tmp_path)
    edit_shapes(
        vocab,
        "    sh:not [ sh:class seam:Model ] ;\n",
        "    sh:not [ sh:class seam:Model ] ;\n    sh:targetSubjectsOf seam:inModel ;\n",
    )
    assert pairing_problems(vocab) == [f"{SEAM.inModel} has 2 sh:Warning shapes with {SH.targetSubjectsOf}"]


def test_a_warning_shape_on_a_live_term_is_caught(tmp_path: Path) -> None:
    vocab = fixture_copy(tmp_path)
    edit_shapes(
        vocab,
        "seamsh:ModelDeprecatedShape a sh:NodeShape ;\n    sh:targetClass seam:Model ;",
        "seamsh:ModelDeprecatedShape a sh:NodeShape ;\n    sh:targetClass seam:Model , seam:Notation ;",
    )
    assert pairing_problems(vocab) == [
        f"{SEAMSH.ModelDeprecatedShape} targets {SEAM.Notation} with {SH.targetClass}, not a deprecated term"
    ]


def test_a_predicate_targeted_as_a_class_is_caught(tmp_path: Path) -> None:
    vocab = fixture_copy(tmp_path)
    edit_shapes(vocab, "sh:targetSubjectsOf seam:inModel ;", "sh:targetClass seam:inModel ;")
    assert pairing_problems(vocab) == [f"{SEAM.inModel} has 0 sh:Warning shapes with {SH.targetSubjectsOf}"]


def test_a_warning_shape_targeting_objects_is_caught(tmp_path: Path) -> None:
    vocab = fixture_copy(tmp_path)
    edit_shapes(
        vocab,
        "sh:targetSubjectsOf seam:inModel ;",
        "sh:targetSubjectsOf seam:inModel ; sh:targetObjectsOf seam:inModel ;",
    )
    assert pairing_problems(vocab) == [
        f"{SEAMSH.InModelDeprecatedShape} targets {SEAM.inModel} with {SH.targetObjectsOf}, not a deprecated term"
    ]


# ── seams check ──


def chapter_01_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(CHAPTER_01, tmp_path / "chapter-01", ignore=shutil.ignore_patterns("__pycache__")))


def test_check_reports_the_migration_and_the_deprecation_and_passes(tmp_path, monkeypatch, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    monkeypatch.setattr(cli, "check_project", functools.partial(check_project, ontology_dir=FIXTURE))
    code = main(["check", "--project", str(project)])
    out, err = capsys.readouterr()
    assert (code, out.splitlines(), err) == (
        0,
        [f"shacl-warning {ARCHITECTURE} - {MODEL_DEPRECATED}", "vocabulary-migrated seam 1.4 2.0"],
        "seams check: 2 warning(s)\n",
    )


def test_check_against_the_shipped_vocabularies_reports_nothing(tmp_path, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    assert main(["check", "--project", str(project)]) == 0
    assert capsys.readouterr() == ("", "")


def test_a_model_on_seam_2_still_writing_the_old_predicate_is_warned_not_migrated(tmp_path) -> None:
    project = chapter_01_copy(tmp_path)
    trig = project / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(SEAM_V1_IMPORT) == 1
    trig.write_text(text.replace(SEAM_V1_IMPORT, "<https://w3id.org/seams/seam/2.0>"), encoding="utf-8")
    assert check_migrations(trig, FIXTURE) == []
    findings = check_shapes(model_graph(trig, FIXTURE), FIXTURE_SHAPES)
    assert {f.kind for f in findings} == {"shacl-warning"}
    in_model = [f.detail for f in findings if f.detail.endswith(f" - {IN_MODEL_DEPRECATED}")]
    assert len(in_model) == 3, findings


def test_warnings_do_not_hide_a_violation(tmp_path, monkeypatch, capsys) -> None:
    project = chapter_01_copy(tmp_path)
    trig = project / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    trig.write_text(
        text + "\n<urn:seams:graph:seams> {\n    <https://example.org/x> seam:detailedBy <https://example.org/y> .\n}\n"
    )
    monkeypatch.setattr(cli, "check_project", functools.partial(check_project, ontology_dir=FIXTURE))
    assert main(["check", "--project", str(project)]) == 1
    out, err = capsys.readouterr()
    kinds = [line.split(" ", 1)[0] for line in out.splitlines()]
    # The edit also leaves seams.lock's model hash behind: lock-out-of-date.
    assert sorted(set(kinds)) == ["lock-out-of-date", "shacl", "shacl-warning", "vocabulary-migrated"]
    assert err == f"seams check: {sum(k not in ADVISORY_KINDS for k in kinds)} problem(s)\n"


def test_check_shapes_splits_by_severity() -> None:
    graph = model_graph(CHAPTER_01 / "expenses.trig", FIXTURE)
    assert check_shapes(graph, FIXTURE_SHAPES) == [Finding("shacl-warning", f"{ARCHITECTURE} - {MODEL_DEPRECATED}")]
    assert check_shapes(graph) == []


# ── generation and the parity helper ──


def test_a_warning_is_never_a_precondition_fault() -> None:
    shapes = Graph().parse(FIXTURE_SHAPES, format="turtle")
    graph = model_graph(CHAPTER_01 / "expenses.trig", FIXTURE)
    import pyshacl

    _conforms, results, _text = pyshacl.validate(graph, shacl_graph=shapes, inference="none")
    gen = Generator(
        name="strict-gen",
        version="1",
        help="",
        extract=lambda _trig, _out: None,
        render=lambda _view: {},
        sources=lambda _trig, _out: {},
        preconditions=(str(SEAMSH.ModelDeprecatedShape),),
    )
    assert gen.precondition_faults(results, shapes) == []
    gen.check_preconditions(results, shapes)
    assert shape_warnings(results) == [f"{ARCHITECTURE} - {MODEL_DEPRECATED}"]


def test_shape_violations_leave_warnings_out() -> None:
    ds = seams.load(CHAPTER_01, ontology_dir=FIXTURE).ds
    ontology = sorted(FIXTURE.glob("*.ttl"))
    assert shape_violations(ds, FIXTURE_SHAPES, ontology) == []
