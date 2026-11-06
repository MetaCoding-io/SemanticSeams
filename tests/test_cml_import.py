"""``seams cml import FILE [PATH]`` (M029/S03/T03, backlog B5, ADR-0034 sections 3 to 5).

Each test works on a copy of chapter 11 or an inline model. Exporting chapter 11 and
importing the result into a copy without :expense_to_finance gives back the same
relationship triples; importing into an unchanged copy leaves every file's bytes as
they were. An open host service alone, a partnership and an unknown context are
flagged on stderr and not written, with exit 0; a file that does not parse names the
line, exits 1 and writes nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import seams
from rdflib import RDF, URIRef
from seams import ARCH
from seams_cli.__main__ import main
from seams_cli.cml import CmlError, decide, parse

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"
EX = "https://example.org/expenses/"

CHAPTER_RELATIONSHIP = """\
    :expense_to_finance a arch:ContextRelationship ;
        arch:upstream :expense_context ;
        arch:downstream :finance_context ;
        arch:relationshipType arch:Conformist .
"""


def chapter_copy(tmp_path: Path, *, relationship: bool = True) -> Path:
    project = Path(shutil.copytree(CHAPTER, tmp_path / "chapter-11", ignore=shutil.ignore_patterns("__pycache__")))
    if not relationship:
        trig = project / "expenses.trig"
        text = trig.read_text(encoding="utf-8")
        assert CHAPTER_RELATIONSHIP in text
        trig.write_text(text.replace(CHAPTER_RELATIONSHIP, ""), encoding="utf-8")
    return project


def snapshot(project: Path) -> dict[str, bytes]:
    return {str(p.relative_to(project)): p.read_bytes() for p in sorted(project.rglob("*")) if p.is_file()}


def relationship_triples(project: Path) -> set[tuple[object, object, object]]:
    ds = seams.load(project).ds
    return {
        (s, p, o) for r in ds.subjects(RDF.type, ARCH.ContextRelationship) for s, p, o in ds.triples((r, None, None))
    }


def write_cml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "map.cml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_chapter_11_export_imports_back_to_the_same_relationship(tmp_path, capsys):
    exported = tmp_path / "chapter-11.cml"
    assert main(["cml", "export", str(CHAPTER), "--out", str(exported)]) == 0
    project = chapter_copy(tmp_path, relationship=False)
    assert relationship_triples(project) == set()
    capsys.readouterr()

    assert main(["cml", "import", str(exported), str(project)]) == 0
    out = capsys.readouterr()
    assert out.out.splitlines() == ["added expense_to_finance", str((project / "expenses.trig").resolve())]
    assert out.err == ""
    assert relationship_triples(project) == relationship_triples(CHAPTER)
    assert (URIRef(EX + "expense_to_finance"), ARCH.relationshipType, ARCH.Conformist) in relationship_triples(project)


def test_importing_into_an_unchanged_copy_keeps_every_byte(tmp_path, capsys):
    exported = tmp_path / "chapter-11.cml"
    assert main(["cml", "export", str(CHAPTER), "--out", str(exported)]) == 0
    project = chapter_copy(tmp_path)
    before = snapshot(project)
    capsys.readouterr()

    assert main(["cml", "import", str(exported), "--project", str(project)]) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""
    assert snapshot(project) == before


def test_unmapped_constructs_are_flagged_and_not_written(tmp_path, capsys):
    project = chapter_copy(tmp_path, relationship=False)
    before = snapshot(project)
    cml = write_cml(
        tmp_path,
        """\
ContextMap {
  contains expense_context, finance_context
  expense_context [U,OHS]->[D] finance_context
  expense_context [P]<->[P] finance_context : together
  finance_context Partnership expense_context
  expense_context [U]->[D,CF] billing_context
}

BoundedContext expense_context {
  Aggregate Claims {
    Entity Claim { String id }
  }
}

Domain Expenses { Subdomain Approvals }
""",
    )
    assert main(["cml", "import", str(cml), str(project)]) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.splitlines() == [
        "seams cml import: flag BoundedContext expense_context attributes: "
        "BoundedContext attributes are not read (ADR-0034 section 1)",
        "seams cml import: flag Domain Expenses: the graph does not read this from CML (ADR-0034 section 4)",
        "seams cml import: flag expense_context [U,OHS]->[D] finance_context: "
        "an open host service alone has no arch:RelationshipType (ADR-0032 folds it into PL)",
        "seams cml import: flag expense_context [P]<->[P] finance_context : together: "
        "a partnership has no arch:RelationshipType (ADR-0032)",
        "seams cml import: flag finance_context Partnership expense_context: "
        "a partnership has no arch:RelationshipType (ADR-0032)",
        "seams cml import: flag expense_context [U]->[D,CF] billing_context: "
        "billing_context matches no arch:BoundedContext in the model",
    ]
    assert snapshot(project) == before


def test_a_pair_the_model_relates_otherwise_is_flagged(tmp_path, capsys):
    project = chapter_copy(tmp_path)
    before = snapshot(project)
    cml = write_cml(
        tmp_path,
        "ContextMap {\n  finance_context [D,C]<-[U,S] expense_context\n  finance_context [U]->[D,CF] expense_context\n}\n",
    )
    assert main(["cml", "import", str(cml), str(project)]) == 0
    err = capsys.readouterr().err.splitlines()
    reason = "the model already relates expense_context to finance_context as Conformist"
    assert err == [
        f"seams cml import: flag finance_context [D,C]<-[U,S] expense_context: {reason}",
        f"seams cml import: flag finance_context [U]->[D,CF] expense_context: {reason}",
    ]
    assert snapshot(project) == before


@pytest.mark.parametrize(
    ("line", "detail"),
    [
        ("expense_context [U,XX]->[D,CF] finance_context", "line 4: unknown relationship role 'XX'"),
        ("expense_context [U]->[D,CF]", "line 5: expected the context on the right of the relationship, found '}'"),
        ("expense_context = finance_context", "line 4: expense_context: expected a relationship arrow, found '='"),
    ],
)
def test_a_parse_error_names_the_line_and_writes_nothing(tmp_path, capsys, line, detail):
    project = chapter_copy(tmp_path, relationship=False)
    before = snapshot(project)
    # The first relationship is valid, so a partial write would show.
    cml = write_cml(
        tmp_path,
        f"ContextMap {{\n  contains expense_context, finance_context\n"
        f"  expense_context [U]->[D,CF] finance_context\n  {line}\n}}\n",
    )
    assert main(["cml", "import", str(cml), str(project)]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == f"seams cml import: {cml.resolve()}: {detail}\n"
    assert snapshot(project) == before


@pytest.mark.parametrize(
    "text",
    ["ContextMap {\n  contains a\n", "/* open\nContextMap {}\n", 'BoundedContext a {\n  x = "open\n}\n', "42 Map\n"],
)
def test_unreadable_files_raise_cml_error(text):
    with pytest.raises(CmlError):
        parse(text)


@pytest.mark.parametrize(
    ("line", "upstream", "kind"),
    [
        ("a [U,S]->[D,C] b", "a", ARCH.CustomerSupplier),
        ("b Customer-Supplier a", "a", ARCH.CustomerSupplier),
        ("a [U]->[D,CF] b", "a", ARCH.Conformist),
        ("b [D,CF]<-[U] a", "a", ARCH.Conformist),
        ("a [U,OHS,PL]->[D,ACL] b", "a", ARCH.AntiCorruptionLayer),
        ("a [U,PL]->[D] b", "a", ARCH.PublishedLanguage),
        ("a [U,OHS,PL]->[D] b", "a", ARCH.PublishedLanguage),
        ("a [SK]<->[SK] b", "a", ARCH.SharedKernel),
        ("a <-> b", "a", ARCH.SharedKernel),
        ("a Shared-Kernel b", "a", ARCH.SharedKernel),
        ("a [U]->[D] b", "a", None),
        ("a [U,OHS]->[D] b", "a", None),
        ("a [P]<->[P] b", "a", None),
    ],
)
def test_the_roles_decide_the_type(line, upstream, kind):
    (relationship,) = parse(f"ContextMap {{\n  {line}\n}}\n").relationships
    assert relationship.upstream == upstream
    assert decide(relationship)[0] == kind


PREFIXES = """\
@prefix : <https://example.org/cml/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix seam: <https://w3id.org/seams/seam#> .
"""


def test_each_type_imports_with_a_minted_or_named_iri(tmp_path, capsys):
    contexts = "".join(f"    :{c} a arch:BoundedContext .\n" for c in ("alpha", "bravo", "charlie", "delta", "echo"))
    trig = tmp_path / "map.trig"
    trig.write_text(
        PREFIXES + "\n:architecture {\n    :architecture a seam:Model ; seam:notation seam:C4 .\n" + contexts + "}\n",
        encoding="utf-8",
    )
    (tmp_path / "seams.toml").write_text('model = "map.trig"\n', encoding="utf-8")
    cml = write_cml(
        tmp_path,
        "ContextMap {\n"
        "  alpha [U,S]->[D,C] bravo : supply\n"
        "  charlie [D,CF]<-[U] bravo\n"
        "  alpha [U]->[D,ACL] delta\n"
        "  delta [U,PL]->[D] echo\n"
        "  echo [SK]<->[SK] alpha : shared\n"
        "}\n",
    )
    assert main(["cml", "import", str(cml), str(trig)]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    names = ["alpha_to_delta", "bravo_to_charlie", "delta_to_echo", "shared", "supply"]
    assert out.out.splitlines() == [f"added {n}" for n in names] + [str(trig.resolve())]
    ds = seams.load(trig).ds
    cml_ns = "https://example.org/cml/"
    found = {
        (str(r), str(ds.value(r, ARCH.upstream)), str(ds.value(r, ARCH.downstream)), ds.value(r, ARCH.relationshipType))
        for r in ds.subjects(RDF.type, ARCH.ContextRelationship)
    }
    assert found == {
        (cml_ns + "supply", cml_ns + "alpha", cml_ns + "bravo", ARCH.CustomerSupplier),
        (cml_ns + "bravo_to_charlie", cml_ns + "bravo", cml_ns + "charlie", ARCH.Conformist),
        (cml_ns + "alpha_to_delta", cml_ns + "alpha", cml_ns + "delta", ARCH.AntiCorruptionLayer),
        (cml_ns + "delta_to_echo", cml_ns + "delta", cml_ns + "echo", ARCH.PublishedLanguage),
        (cml_ns + "shared", cml_ns + "echo", cml_ns + "alpha", ARCH.SharedKernel),
    }
