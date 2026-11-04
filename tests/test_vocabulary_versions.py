"""Tests for vocabulary versions and the load check (M023/S02, ADR-0021).

Every vocabulary in ontology/ carries owl:versionIRI <https://w3id.org/seams/<name>/1.0>,
except seam at 1.2 (ADR-0022 added the seam:Ontology notation, ADR-0023 the shape notation).
A model declares the versions it targets as owl:imports in <urn:seams:graph:manifest>;
no declaration means 1.0. ``seams.load`` refuses a model newer than the tool and migrates
an older one in memory with ontology/migrations/<name>/<from>-to-<to>.ru.

Every shipped vocabulary is at major 1, so the older and newer paths run against the
fixture tree tests/fixtures/vocab-v2 (D060): seam at 2.0, whose 1-to-2.ru renames
seam:inModel to seam:partOfModel, loaded over the real expense chapter-01 checkpoint,
which declares seam 1.2 and arch 1.0. Tests that need a model written before S02, with
no declaration, take the checkpoint with its manifest graph removed.
"""

import re
import shutil
from pathlib import Path

import pytest
import seams
from rdflib import OWL, RDF, Dataset, URIRef
from seams import MANIFEST_GRAPH, SEAM, MigrationStep, ResolutionError

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
FIXTURE = ROOT / "tests" / "fixtures" / "vocab-v2"
CHAPTER_01 = ROOT / "examples" / "expenses" / "chapter-01"
CHAPTER_01_TRIG = CHAPTER_01 / "expenses.trig"
ARCHITECTURE_GRAPH = URIRef("urn:seams:graph:model:expense_architecture")
PART_OF_MODEL = URIRef("https://w3id.org/seams/seam#partOfModel")
SEAM_V1 = URIRef("https://w3id.org/seams/seam/1.0")
# What the checkpoints declare: the shipped seam.
SEAM_V1_2 = URIRef("https://w3id.org/seams/seam/1.2")
SEAM_V2 = URIRef("https://w3id.org/seams/seam/2.0")
ARCH_V1 = "https://w3id.org/seams/arch/1.0"
EXAMPLES = sorted(
    [ROOT / "examples" / "chat-app" / "chat-app.trig", ROOT / "examples" / "checkout.trig"]
    + list((ROOT / "examples" / "expenses").glob("chapter-*/expenses.trig"))
)
MANIFEST_BLOCK = re.compile(r"\n#+\n# Manifest graph[^\n]*\n#+\n\n<urn:seams:graph:manifest> \{.*?\n\}\n", re.S)


def undeclared(trig: Path) -> str:
    """``trig``'s text without its manifest graph: the model as written before S02."""
    text, removed = MANIFEST_BLOCK.subn("", trig.read_text(encoding="utf-8"))
    assert removed == 1, f"{trig} has no manifest graph block"
    return text


def manifest(*imports: str) -> str:
    listed = " , ".join(f"<{iri}>" for iri in imports)
    return (
        "\n<urn:seams:graph:manifest> {\n"
        "    <urn:seams:graph:manifest> a <http://www.w3.org/2002/07/owl#Ontology> ;\n"
        f"        <http://www.w3.org/2002/07/owl#imports> {listed} .\n"
        "}\n"
    )


def chapter_01(tmp_path: Path, *imports: str) -> Path:
    """chapter-01's TriG in tmp_path, its own declaration replaced by a manifest graph
    declaring ``imports`` (none: no manifest graph at all)."""
    model = tmp_path / "model"
    model.mkdir()
    trig = model / "expenses.trig"
    trig.write_text(undeclared(CHAPTER_01_TRIG) + (manifest(*imports) if imports else ""))
    return trig


def vocabularies(tmp_path: Path) -> Path:
    """A writable copy of the fixture vocabulary tree."""
    return Path(shutil.copytree(FIXTURE, tmp_path / "vocab"))


def quads(model: seams.Model) -> list[tuple[str, str, str, str]]:
    return sorted((str(s), str(p), str(o), str(g)) for s, p, o, g in model.ds.quads((None, None, None, None)))


def declarations(model: seams.Model) -> list[str]:
    return sorted(str(o) for o in model.ds.graph(MANIFEST_GRAPH).objects(None, OWL.imports))


def refused(err: pytest.ExceptionInfo[ResolutionError]) -> str:
    assert err.value.subject == str(MANIFEST_GRAPH)
    assert err.value.predicate == str(OWL.imports)
    return err.value.detail


# ── shipped versions ──


# seam 1.1 adds the seam:Ontology notation (ADR-0022) and 1.2 the shape notation of
# ADR-0023 (sh:name, categories, sh:node flattening): compatible widenings.
SHIPPED = {"seam": (1, 2)}


def test_every_shipped_vocabulary_is_at_its_release() -> None:
    names = sorted(p.stem for p in ONTOLOGY.glob("*.ttl"))
    assert seams.shipped_versions(ONTOLOGY) == {name: SHIPPED.get(name, (1, 0)) for name in names}
    for path in sorted(ONTOLOGY.glob("*.ttl")):
        text = path.read_text(encoding="utf-8")
        version = ".".join(map(str, SHIPPED.get(path.stem, (1, 0))))
        assert f"owl:versionIRI <https://w3id.org/seams/{path.stem}/{version}> ;" in text, path.name
        assert f'owl:versionInfo "{version}" ;' in text, path.name


def test_fixture_has_seam_at_2_0_and_the_rest_as_shipped() -> None:
    assert seams.shipped_versions(FIXTURE) == {**seams.shipped_versions(ONTOLOGY), "seam": (2, 0)}
    for path in sorted(ONTOLOGY.glob("*.ttl")):
        if path.stem != "seam":
            assert (FIXTURE / path.name).read_bytes() == path.read_bytes(), f"copy {path.name} into {FIXTURE}"


def test_a_vocabulary_without_a_version_iri_is_refused(tmp_path: Path) -> None:
    vocab = vocabularies(tmp_path)
    arch = vocab / "arch.ttl"
    arch.write_text(re.sub(r"    owl:versionIRI <[^>]+> ;\n", "", arch.read_text(encoding="utf-8")))
    with pytest.raises(ResolutionError) as err:
        seams.load(CHAPTER_01, ontology_dir=vocab)
    assert err.value.subject == "https://w3id.org/seams/arch"
    assert err.value.predicate == str(OWL.versionIRI)


# ── same ──


def test_an_undeclared_model_loads_as_written_against_the_shipped_vocabularies(tmp_path: Path) -> None:
    trig = chapter_01(tmp_path)
    model = seams.load(trig)
    assert model.migrations == ()
    assert quads(model) == quads(seams.load(trig, check_versions=False))


def test_the_checkpoint_declares_the_shipped_versions_and_loads_as_written() -> None:
    model = seams.load(CHAPTER_01)
    assert model.migrations == ()
    assert declarations(model) == [ARCH_V1, str(SEAM_V1_2)]
    assert quads(model) == quads(seams.load(CHAPTER_01, check_versions=False))


@pytest.mark.parametrize("trig", EXAMPLES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_example_declares_each_vocabulary_it_uses_at_the_shipped_version(trig: Path) -> None:
    shipped = seams.shipped_versions(ONTOLOGY)
    ds = Dataset()
    ds.parse(trig, format="trig")
    used = {
        str(term).removeprefix("https://w3id.org/seams/").split("#")[0]
        for *triple, graph in ds.quads((None, None, None, None))
        if graph != MANIFEST_GRAPH
        for term in triple
        if isinstance(term, URIRef) and str(term).startswith("https://w3id.org/seams/")
    }
    expected = sorted(
        f"https://w3id.org/seams/{name}/{major}.{minor}" for name, (major, minor) in shipped.items() if name in used
    )
    assert sorted(str(o) for o in ds.graph(MANIFEST_GRAPH).objects(MANIFEST_GRAPH, OWL.imports)) == expected
    assert (MANIFEST_GRAPH, RDF.type, OWL.Ontology) in ds.graph(MANIFEST_GRAPH)


def test_a_model_declaring_the_tool_version_loads_as_written(tmp_path: Path) -> None:
    trig = chapter_01(tmp_path, str(SEAM_V2), "https://w3id.org/seams/arch/1.0")
    model = seams.load(trig, ontology_dir=FIXTURE)
    assert model.migrations == ()
    assert quads(model) == quads(seams.load(trig, check_versions=False))


def test_a_lower_minor_of_the_same_major_is_the_same(tmp_path: Path) -> None:
    vocab = vocabularies(tmp_path)
    seam = vocab / "seam.ttl"
    seam.write_text(seam.read_text(encoding="utf-8").replace("seam/2.0>", "seam/2.3>"))
    model = seams.load(chapter_01(tmp_path, str(SEAM_V2)), ontology_dir=vocab)
    assert model.migrations == ()
    assert declarations(model) == [str(SEAM_V2)]


def test_imports_of_other_ontologies_are_not_checked(tmp_path: Path) -> None:
    trig = chapter_01(tmp_path, "https://w3id.org/semanticarts/ontology/gistCore13.0.0")
    assert seams.load(trig).migrations == ()


# ── older ──


def test_an_older_model_is_migrated_in_memory() -> None:
    model = seams.load(CHAPTER_01, ontology_dir=FIXTURE)
    as_written = seams.load(CHAPTER_01, check_versions=False)

    assert model.migrations == (MigrationStep("seam", "1.2", "2.0"),)
    assert not list(model.ds.quads((None, SEAM.inModel, None, None)))
    renamed = sorted(model.ds.quads((None, PART_OF_MODEL, None, None)))
    original = sorted(as_written.ds.quads((None, SEAM.inModel, None, None)))
    assert len(renamed) == len(original) == 3
    # Each renamed triple stays in the named graph it was written in.
    assert [(s, o, g) for s, _p, o, g in renamed] == [(s, o, g) for s, _p, o, g in original]
    assert {g for *_t, g in renamed} == {ARCHITECTURE_GRAPH}
    # The declaration moves to the tool's version; arch is current and stays.
    assert declarations(model) == [ARCH_V1, str(SEAM_V2)]
    # Nothing else changes, and the files on disk are untouched.
    untouched = {q for q in quads(as_written) if q[1] != str(SEAM.inModel) and q[2] != str(SEAM_V1_2)}
    assert untouched <= set(quads(model))
    assert model.hash == as_written.hash


def test_an_undeclared_model_is_migrated_and_gains_the_declaration(tmp_path: Path) -> None:
    model = seams.load(chapter_01(tmp_path), ontology_dir=FIXTURE)
    assert model.migrations == (MigrationStep("seam", "1.0", "2.0"),)
    assert declarations(model) == [str(SEAM_V2)]
    assert (MANIFEST_GRAPH, RDF.type, OWL.Ontology) in model.ds.graph(MANIFEST_GRAPH)


def test_the_same_model_migrates_to_the_same_quads() -> None:
    assert quads(seams.load(CHAPTER_01, ontology_dir=FIXTURE)) == quads(seams.load(CHAPTER_01, ontology_dir=FIXTURE))


def test_steps_run_in_ascending_order(tmp_path: Path) -> None:
    vocab = vocabularies(tmp_path)
    seam = vocab / "seam.ttl"
    seam.write_text(seam.read_text(encoding="utf-8").replace("seam/2.0>", "seam/3.1>"))
    # 2-to-3 renames what 1-to-2 produced, so it only works after it.
    (vocab / "migrations" / "seam" / "2-to-3.ru").write_text(
        "PREFIX seam: <https://w3id.org/seams/seam#>\n"
        "DELETE { GRAPH ?g { ?s seam:partOfModel ?o } } INSERT { GRAPH ?g { ?s seam:memberOf ?o } }\n"
        "WHERE { GRAPH ?g { ?s seam:partOfModel ?o } }\n"
    )
    model = seams.load(CHAPTER_01, ontology_dir=vocab)
    assert model.migrations == (MigrationStep("seam", "1.2", "2.0"), MigrationStep("seam", "2.0", "3.1"))
    assert len(list(model.ds.quads((None, SEAM.memberOf, None, ARCHITECTURE_GRAPH)))) == 3
    assert declarations(model) == [ARCH_V1, "https://w3id.org/seams/seam/3.1"]


def test_check_versions_off_keeps_the_model_as_written() -> None:
    model = seams.load(CHAPTER_01, ontology_dir=FIXTURE, check_versions=False)
    assert model.migrations == ()
    assert len(list(model.ds.quads((None, SEAM.inModel, None, None)))) == 3


# ── refused ──


@pytest.mark.parametrize(("declared", "tool"), [("2.1", "2.0"), ("3.0", "2.0")])
def test_a_newer_model_is_refused(tmp_path: Path, declared: str, tool: str) -> None:
    trig = chapter_01(tmp_path, f"https://w3id.org/seams/seam/{declared}")
    with pytest.raises(ResolutionError) as err:
        seams.load(trig, ontology_dir=FIXTURE)
    assert refused(err) == f"targets seam {declared}; this tool supports seam up to {tool}"


def test_a_newer_minor_than_the_shipped_vocabulary_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ResolutionError) as err:
        seams.load(chapter_01(tmp_path, "https://w3id.org/seams/arch/1.1"))
    assert refused(err) == "targets arch 1.1; this tool supports arch up to 1.0"


@pytest.mark.parametrize(
    "iri",
    [
        "https://w3id.org/seams/nosuch/1.0",
        "https://w3id.org/seams/seam/0.9",
        "https://w3id.org/seams/seam/1",
        "https://w3id.org/seams/seam",
    ],
)
def test_an_unpublished_version_is_refused(tmp_path: Path, iri: str) -> None:
    with pytest.raises(ResolutionError) as err:
        seams.load(chapter_01(tmp_path, iri))
    assert refused(err) == f"{iri} is not a published SemanticSeams vocabulary version"


def test_disagreeing_declarations_are_refused(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "a.trig").write_text(undeclared(CHAPTER_01_TRIG))
    (model / "b.trig").write_text(manifest(str(SEAM_V1)))
    (model / "c.trig").write_text(manifest(str(SEAM_V2)))
    with pytest.raises(ResolutionError) as err:
        seams.load(model, ontology_dir=FIXTURE)
    assert refused(err) == f"declarations disagree on seam: <{SEAM_V1}>, <{SEAM_V2}>"


def test_agreeing_declarations_in_a_directory_model_load(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "a.trig").write_text(undeclared(CHAPTER_01_TRIG))
    (model / "b.trig").write_text(manifest(str(SEAM_V2)))
    (model / "c.trig").write_text(manifest(str(SEAM_V2)))
    assert seams.load(model, ontology_dir=FIXTURE).migrations == ()


def test_a_missing_step_is_refused(tmp_path: Path) -> None:
    vocab = vocabularies(tmp_path)
    (vocab / "migrations" / "seam" / "1-to-2.ru").unlink()
    with pytest.raises(ResolutionError) as err:
        seams.load(CHAPTER_01, ontology_dir=vocab)
    assert refused(err) == "no migration step seam 1-to-2 (migrations/seam/1-to-2.ru)"


@pytest.mark.parametrize("call", ["NOW()", "rand()", "UUID()", "STRUUID()", 'BNODE("x")', "bnode ()"])
def test_a_non_deterministic_step_is_refused_before_anything_changes(tmp_path: Path, call: str) -> None:
    vocab = vocabularies(tmp_path)
    step = vocab / "migrations" / "seam" / "1-to-2.ru"
    step.write_text(step.read_text(encoding="utf-8").replace("WHERE  {", f"WHERE  {{ BIND({call} AS ?x)"))
    ds = Dataset(default_union=True)
    ds.parse(CHAPTER_01_TRIG, format="trig")
    before = sorted(ds.quads((None, None, None, None)))
    with pytest.raises(ResolutionError) as err:
        seams.check_versions(ds, vocab)
    name = call.split("(")[0].strip().upper()
    assert refused(err) == f"migration migrations/seam/1-to-2.ru calls {name}(), which is not deterministic"
    assert sorted(ds.quads((None, None, None, None))) == before


def test_an_explicit_ontology_dir_must_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        seams.load(CHAPTER_01, ontology_dir=tmp_path / "missing")
