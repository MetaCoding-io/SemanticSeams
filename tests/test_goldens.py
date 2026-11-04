"""The committed chapter 9 outputs survive the ADR-0023 shape notation.

``examples/expenses/chapter-09`` is copied to a temporary directory and its
shapes are rewritten to the notation of ADR-0023: ``sh:targetClass``,
``sh:name``, the expense's states as members of the ``:ExpenseState``
category, the approval outcomes as ``:ApprovalOutcome`` members, the
payment's states as an ``sh:in`` of state IRIs, and the ``:paid_on`` path
renamed ``:paidOn`` with ``sh:name "paid_on"``. Each generator that reads
shapes then renders exactly the committed files (ADR-0023 section 7: every
line but the model hash), and the runtime answers a bad payload with the
same 422 results as the committed model.

A rewrite whose old text is gone is skipped: once T04 migrates chapter 9
itself, the test checks the migrated model the same way.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rdflib  # noqa: E402
from validate_chat_app import ONTOLOGY_FILES, check_shacl, union_graph  # noqa: E402

from seams_gen.__main__ import main  # noqa: E402
from seams_runtime.contracts import validate  # noqa: E402
from seams_runtime.errors import ContractViolation  # noqa: E402
from seams_runtime.model import ModelGraph  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-09"
TRIG = "expenses.trig"
# The generators that read shapes, and where chapter 9's seams.toml writes them.
OUTPUTS = {
    "fastapi": "generated",
    "htmx": "generated/templates",
    "tests": "generated/tests",
    "smoke": "generated/smoke",
    "acceptance": "generated/acceptance",
    "jsonld": "generated/contexts",
}
TRACE_SUFFIX = ".trace.json"
HAND_WRITTEN = {"README.md"}

EXPENSE_STATES = ("draft", "submitted", "approved", "rejected", "paid")

# (old text, new text): each rewrite moves one fact to the ADR-0023 notation.
REWRITES = (
    (
        ':ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;\n',
        ':ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ; sh:targetClass :Expense ;\n',
    ),
    (
        ':ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ;\n',
        ':ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ; sh:targetClass :Approval ;\n',
    ),
    (
        ':PaymentShape a sh:NodeShape ; rdfs:label "Payment" ;\n',
        ':PaymentShape a sh:NodeShape ; rdfs:label "Payment" ; sh:targetClass :Payment ;\n',
    ),
    (
        "sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 3 ;\n"
        '                      sh:in ( "draft" "submitted" "approved" "rejected" "paid" ) ] ;',
        'sh:property [ sh:path :status ; sh:name "status" ; sh:class :ExpenseState ; sh:maxCount 1 ;\n'
        "                      sh:order 3 ] ;",
    ),
    (
        "sh:property [ sh:path :decision ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;\n"
        '                      sh:in ( "approved" "rejected" ) ; sh:order 0 ] ;',
        'sh:property [ sh:path :decision ; sh:name "decision" ; sh:class :ApprovalOutcome ;\n'
        "                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;",
    ),
    (
        "sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 2 ;\n"
        '                      sh:in ( "recorded" "scheduled" "batched" "sent" ) ] ;',
        "sh:property [ sh:path :status ; sh:maxCount 1 ; sh:order 2 ;\n"
        "                      sh:in ( :s_recorded :s_scheduled :s_batched :s_sent ) ] ;",
    ),
    (
        "sh:property [ sh:path :paid_on ; sh:datatype xsd:date ;",
        'sh:property [ sh:path :paidOn ; sh:name "paid_on" ; sh:datatype xsd:date ;',
    ),
    ("ifml:boundTo :paid_on ;", "ifml:boundTo :paidOn ;"),
    ("verify:field :paid_on ;", "verify:field :paidOn ;"),
    (
        "    :ApprovalOutcome a owl:Class ;\n",
        '    :outcome_approved a :ApprovalOutcome ; rdfs:label "approved" ; seam:inModel :expense_ontology .\n'
        '    :outcome_rejected a :ApprovalOutcome ; rdfs:label "rejected" ; seam:inModel :expense_ontology .\n'
        "\n"
        "    :ApprovalOutcome a owl:Class ;\n",
    ),
) + tuple(
    (
        f':s_{state}{" " * (9 - len(state))} a state:State ; rdfs:label "{state}"',
        f':s_{state}{" " * (9 - len(state))} a state:State , :ExpenseState ; rdfs:label "{state}"',
    )
    for state in EXPENSE_STATES
)


def migrate(text: str) -> str:
    """``text`` with every rewrite applied; a rewrite applies once or not at all."""
    for old, new in REWRITES:
        assert text.count(old) <= 1, f"{old!r} is ambiguous in {TRIG}"
        text = text.replace(old, new)
    return text


def _hash_line(line: str) -> bool:
    """A line that records the model's hash: a module's MODEL_HASH, or the
    ``model-hash:`` header comment of a module (``#``) or a template (``{#``)."""
    return line.startswith(("MODEL_HASH = ", "# model-hash: sha256:", "{# model-hash: sha256:"))


def rendered(directory: Path) -> dict[str, list[str]]:
    """{relative path: lines but the model hash} of the generated files under ``directory``."""
    return {
        p.relative_to(directory).as_posix(): [
            line for line in p.read_text(encoding="utf-8").splitlines() if not _hash_line(line)
        ]
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(TRACE_SUFFIX)
    }


@pytest.fixture(scope="module")
def migrated(tmp_path_factory) -> Path:
    """A copy of chapter 9 (without its outputs) with its shapes in the ADR-0023 notation."""
    copy = tmp_path_factory.mktemp("chapter-09") / "chapter-09"
    shutil.copytree(CHAPTER, copy, ignore=shutil.ignore_patterns("generated", "__pycache__"))
    trig = copy / TRIG
    trig.write_text(migrate(trig.read_text(encoding="utf-8")), encoding="utf-8")
    return copy


def test_migrated_chapter_uses_the_adr_0023_notation(migrated):
    text = (migrated / TRIG).read_text(encoding="utf-8")
    assert 'sh:in ( "draft"' not in text
    assert 'sh:in ( "approved"' not in text
    assert 'sh:in ( "recorded"' not in text
    assert "sh:targetClass :Expense" in text


def test_migrated_chapter_conforms_to_the_seam_shapes(migrated):
    ds = rdflib.Dataset()
    for p in ONTOLOGY_FILES:
        ds.default_graph.parse(p, format="turtle")
    ds.parse(migrated / TRIG, format="trig")
    assert check_shacl(union_graph(ds)) == []


@pytest.mark.parametrize("generator", sorted(OUTPUTS))
def test_migrated_chapter_renders_the_committed_files(generator, migrated, tmp_path):
    assert main([generator, str(migrated / TRIG), "--out", str(tmp_path)]) == 0
    committed_dir = CHAPTER / OUTPUTS[generator]
    committed = rendered(committed_dir)
    if generator == "fastapi":
        # The route module's directory also holds the other generators' outputs.
        committed = {k: v for k, v in committed.items() if "/" not in k and k.endswith(".py")}
    generated = rendered(tmp_path)
    committed = {k: v for k, v in committed.items() if k not in HAND_WRITTEN}
    assert sorted(generated) == sorted(committed)
    for name, lines in generated.items():
        assert lines == committed[name], f"{OUTPUTS[generator]}/{name} differs from the committed copy"


@pytest.mark.parametrize(
    ("shape", "payload"),
    [
        (":ApprovalShape", {"decision": "maybe"}),
        (":ApprovalShape", {"decision": "approved", "comment": "x" * 501}),
        (":PaymentShape", {"reference": "R1", "paid_on": "2026-10-05", "status": "lost"}),
        (":PaymentShape", {"reference": "R1"}),
        (":ExpenseShape", {"description": "Train", "amount": "42.50", "date": "2026-10-01", "status": "late"}),
    ],
)
def test_migrated_chapter_answers_a_bad_payload_with_the_same_results(shape, payload, migrated):
    def results(trig: Path) -> list[dict]:
        with pytest.raises(ContractViolation) as caught:
            validate(ModelGraph(trig), shape, payload)
        # pySHACL's message names the focus node and the RDF path; the path
        # is renamed on purpose, while the wire name ("path") stays
        out = []
        for r in caught.value.results:
            message = (r["message"] or "").replace(r["focus"], "<focus>").replace(":paidOn", ":paid_on")
            out.append({**{k: v for k, v in r.items() if k != "focus"}, "message": message})
        return out

    assert results(migrated / TRIG) == results(CHAPTER / TRIG)


@pytest.mark.parametrize(
    ("shape", "payload"),
    [
        (":ApprovalShape", {"decision": "rejected"}),
        (":PaymentShape", {"reference": "R1", "paid_on": "2026-10-05", "status": "scheduled"}),
        (":ExpenseShape", {"description": "Train", "amount": "42.50", "date": "2026-10-01", "status": "paid"}),
    ],
)
def test_migrated_chapter_accepts_the_same_payload(shape, payload, migrated):
    assert validate(ModelGraph(migrated / TRIG), shape, payload) == validate(ModelGraph(CHAPTER / TRIG), shape, payload)
