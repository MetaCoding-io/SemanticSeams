"""``seams cml export [PATH] [--out FILE]`` (M029/S03/T02, backlog B5, ADR-0034).

Chapter 11 exports the CML ADR-0034 section 2 gives as its example, byte for byte and
the same on every run. An inline model with one relationship of each of ADR-0032's
five types shows each type's bracket form; a relationship with an unknown type or a
missing context exits 2, naming the relationship and the predicate, and writes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from seams_cli.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples" / "expenses" / "chapter-11"

CHAPTER_CML = """\
ContextMap {
  contains expense_context, finance_context
  expense_context [U]->[D,CF] finance_context : expense_to_finance
}

BoundedContext expense_context

BoundedContext finance_context
"""

PREFIXES = """\
@prefix : <https://example.org/cml/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix seam: <https://w3id.org/seams/seam#> .
"""

CONTEXTS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")


def _model(tmp_path: Path, relationships: str) -> Path:
    contexts = "".join(f"    :{c} a arch:BoundedContext .\n" for c in reversed(CONTEXTS))
    trig = tmp_path / "map.trig"
    trig.write_text(
        PREFIXES
        + "\n:architecture {\n    :architecture a seam:Model ; seam:notation seam:C4 .\n"
        + contexts
        + relationships
        + "}\n",
        encoding="utf-8",
    )
    (tmp_path / "seams.toml").write_text('model = "map.trig"\n', encoding="utf-8")
    return trig


def _relationship(name: str, up: str, down: str, kind: str) -> str:
    return (
        f"    :{name} a arch:ContextRelationship ;\n"
        f"        arch:upstream :{up} ; arch:downstream :{down} ;\n"
        f"        arch:relationshipType arch:{kind} .\n"
    )


# Written out of IRI order, so the export's sorting is exercised.
FIVE = "".join(
    [
        _relationship("shared", "echo", "foxtrot", "SharedKernel"),
        _relationship("conform", "bravo", "charlie", "Conformist"),
        _relationship("published", "delta", "echo", "PublishedLanguage"),
        _relationship("acl", "alpha", "delta", "AntiCorruptionLayer"),
        _relationship("supply", "alpha", "bravo", "CustomerSupplier"),
    ]
)


def test_chapter_11_exports_the_adr_example(capsys):
    assert main(["cml", "export", str(CHAPTER)]) == 0
    out = capsys.readouterr()
    assert out.out == CHAPTER_CML
    assert out.err == ""


def test_the_export_is_byte_identical_across_runs(tmp_path, capsys):
    first, second = tmp_path / "first.cml", tmp_path / "second.cml"
    assert main(["cml", "export", "--project", str(CHAPTER), "--out", str(first)]) == 0
    assert main(["cml", "export", "--project", str(CHAPTER), "--out", str(second)]) == 0
    assert capsys.readouterr().out.splitlines() == [str(first.resolve()), str(second.resolve())]
    assert first.read_bytes() == second.read_bytes() == CHAPTER_CML.encode("utf-8")


def test_each_relationship_type_has_its_bracket_form(tmp_path, capsys):
    trig = _model(tmp_path, FIVE)
    assert main(["cml", "export", "--project", str(tmp_path), "--model", str(trig)]) == 0
    assert capsys.readouterr().out == (
        "ContextMap {\n"
        "  contains alpha, bravo, charlie, delta, echo, foxtrot\n"
        "  alpha [U]->[D,ACL] delta : acl\n"
        "  bravo [U]->[D,CF] charlie : conform\n"
        "  delta [U,PL]->[D] echo : published\n"
        "  echo [SK]<->[SK] foxtrot : shared\n"
        "  alpha [U,S]->[D,C] bravo : supply\n"
        "}\n"
        "\nBoundedContext alpha\n"
        "\nBoundedContext bravo\n"
        "\nBoundedContext charlie\n"
        "\nBoundedContext delta\n"
        "\nBoundedContext echo\n"
        "\nBoundedContext foxtrot\n"
    )


def test_a_model_with_no_contexts_exports_an_empty_map(tmp_path, capsys):
    trig = _model(tmp_path, "")
    trig.write_text(PREFIXES + "\n:architecture {\n    :architecture a seam:Model ; seam:notation seam:C4 .\n}\n")
    assert main(["cml", "export", str(trig)]) == 0
    assert capsys.readouterr().out == "ContextMap {\n}\n"


@pytest.mark.parametrize(
    ("broken", "predicate"),
    [
        (_relationship("odd", "alpha", "bravo", "Partnership"), "relationshipType"),
        (
            "    :odd a arch:ContextRelationship ; arch:downstream :bravo ; arch:relationshipType arch:Conformist .\n",
            "upstream",
        ),
        (
            "    :odd a arch:ContextRelationship ; arch:upstream :alpha ;\n"
            "        arch:downstream :bravo , :charlie ; arch:relationshipType arch:Conformist .\n",
            "downstream",
        ),
    ],
)
def test_an_unexportable_relationship_exits_2_and_writes_nothing(tmp_path, capsys, broken, predicate):
    trig = _model(tmp_path, broken)
    out_file = tmp_path / "map.cml"
    assert main(["cml", "export", str(trig), "--out", str(out_file)]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.startswith(
        f"seams cml: cannot resolve https://example.org/cml/odd: missing https://w3id.org/seams/arch#{predicate}"
    )
    assert not out_file.exists()
