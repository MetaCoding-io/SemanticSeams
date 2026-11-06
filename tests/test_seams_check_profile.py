"""``seams check`` validates an attached domain profile's shapes (ADR-0033 section 1).

Each test builds a project in tmp_path from expense chapter 1's model (no generators,
so ``seams generate`` only writes seams.lock), states ``seam:conformsTo`` in its
seams graph and writes the fixture profile below beside it. ``seams generate`` runs
first, so the lock is current and the only findings are the profile's. The fixture
profile has one shape per severity, an unlabelled sh:Info shape (reported) and a pill
shape (a labelled sh:Info shape, ADR-0033 section 4, never reported).
"""

from pathlib import Path

import pytest
import rdflib
import seams
from rdflib import SKOS, URIRef
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01" / "expenses.trig"
PROFILE = "https://example.org/profiles/fixture"
EX = "https://example.org/expenses/"
ARCH = "https://w3id.org/seams/arch#"
CONFORMS = "https://w3id.org/seams/seam#conformsTo"
SHAPES = "https://w3id.org/seams/seam#profileShapes"

PROFILE_TTL = f"""\
@prefix seam: <https://w3id.org/seams/seam#> .
<{PROFILE}> a seam:Profile ; seam:profileShapes "shapes.ttl" .
"""

SHAPES_TTL = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix fx:   <https://example.org/profiles/fixture#> .

fx:DefinedModel a sh:NodeShape ; sh:targetClass seam:Model ;
    sh:property [ sh:path skos:definition ; sh:minCount 1 ;
        sh:message "A model states its skos:definition." ] .

fx:CommentedContainer a sh:NodeShape ; sh:targetClass arch:Container ; sh:severity sh:Warning ;
    sh:property [ sh:path rdfs:comment ; sh:minCount 1 ; sh:severity sh:Warning ;
        sh:message "A container states its rdfs:comment." ] .

fx:SystemTechnology a sh:NodeShape ; sh:targetClass arch:System ; sh:severity sh:Info ;
    sh:property [ sh:path arch:technology ; sh:minCount 1 ; sh:severity sh:Info ;
        sh:message "A system states its arch:technology." ] .

fx:Dependent a sh:NodeShape ; sh:targetClass arch:Container ; sh:severity sh:Info ;
    skos:prefLabel "Dependent" ;
    sh:property [ sh:path arch:dependsOn ; sh:minCount 1 ; sh:severity sh:Info ;
        sh:message "Not a dependent container." ] .
"""


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def project(tmp_path: Path, *, attach: bool, shapes: str | None = SHAPES_TTL) -> Path:
    """A chapter-1 project in tmp_path, attached to the fixture profile when ``attach``."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "seams.toml").write_text('model = "expenses.trig"\n', encoding="utf-8")
    text = CHAPTER_01.read_text(encoding="utf-8")
    if attach:
        text += f"\n<urn:seams:graph:seams> {{ <urn:seams:graph:manifest> seam:conformsTo <{PROFILE}> . }}\n"
    (root / "expenses.trig").write_text(text, encoding="utf-8")
    if shapes is not None:
        profile_dir = root / "profiles" / "fixture"
        profile_dir.mkdir(parents=True)
        (profile_dir / "profile.ttl").write_text(PROFILE_TTL, encoding="utf-8")
        (profile_dir / "shapes.ttl").write_text(shapes, encoding="utf-8")
    # seams generate ignores profiles (ADR-0033 section 1), so it writes the lock either way.
    assert main(["generate", str(root)]) == 0
    return root


def check(root: Path, capsys) -> tuple[int, list[str], str]:
    capsys.readouterr()
    code = main(["check", str(root)])
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_a_model_without_a_profile_keeps_its_output(tmp_path, capsys) -> None:
    # A profile package beside the model is not read unless the model attaches it.
    root = project(tmp_path, attach=False, shapes="this is not turtle")
    assert check(root, capsys) == (0, [], "")


def test_a_violating_profile_fails_the_check_naming_each_fact(tmp_path, capsys) -> None:
    root = project(tmp_path, attach=True)
    assert check(root, capsys) == (
        1,
        [
            f"profile {PROFILE} 4 result(s)",
            f"profile {EX}expense_architecture {SKOS.definition} A model states its skos:definition.",
            f"profile-warning {EX}employee_portal http://www.w3.org/2000/01/rdf-schema#comment"
            " A container states its rdfs:comment.",
            f"profile-warning {EX}expense_api http://www.w3.org/2000/01/rdf-schema#comment"
            " A container states its rdfs:comment.",
            f"profile-warning {EX}expense_system {ARCH}technology A system states its arch:technology.",
        ],
        "seams check: 1 problem(s)\n",
    )


def test_warnings_only_pass_and_the_pill_shape_is_not_reported(tmp_path, capsys) -> None:
    shapes = (
        SHAPES_TTL.split("fx:DefinedModel", 1)[0]
        + "fx:CommentedContainer"
        + SHAPES_TTL.split("fx:CommentedContainer", 1)[1]
    )
    root = project(tmp_path, attach=True, shapes=shapes)
    code, lines, err = check(root, capsys)
    assert (code, lines[0], err) == (0, f"profile {PROFILE} 3 result(s)", "seams check: 3 warning(s)\n")
    assert not [line for line in lines if "Not a dependent container." in line]


def test_a_conforming_model_prints_the_profile_with_no_results(tmp_path, capsys) -> None:
    root = project(tmp_path, attach=True, shapes=SHAPES_TTL.split("fx:DefinedModel", 1)[0])
    assert check(root, capsys) == (0, [f"profile {PROFILE} 0 result(s)"], "")


def test_a_missing_profile_is_a_resolution_error_naming_conforms_to(tmp_path, capsys) -> None:
    root = project(tmp_path, attach=True, shapes=None)
    assert check(root, capsys) == (
        1,
        [
            f"profile urn:seams:graph:manifest {CONFORMS} no profiles/*/profile.ttl in project/ declares {PROFILE}"
            " a seam:Profile"
        ],
        "seams check: 1 problem(s)\n",
    )


def test_a_missing_shapes_file_is_a_resolution_error_naming_profile_shapes(tmp_path, capsys) -> None:
    root = project(tmp_path, attach=True)
    (root / "profiles" / "fixture" / "shapes.ttl").unlink()
    assert check(root, capsys) == (
        1,
        [f"profile {PROFILE} {SHAPES} profiles/fixture/shapes.ttl: no such file"],
        "seams check: 1 problem(s)\n",
    )


def test_the_resolver_names_the_pill_shapes(tmp_path) -> None:
    root = project(tmp_path, attach=True)
    profile = seams.resolve_profile(seams.load(root / "expenses.trig").ds, root)
    assert profile is not None
    assert profile.pills == {URIRef("https://example.org/profiles/fixture#Dependent"): "Dependent"}
    assert isinstance(profile.shapes, rdflib.Graph)
