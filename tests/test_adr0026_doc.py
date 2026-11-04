"""ADR-0026 (M024/S03): the Mental Model format is recorded before the generator.
The ADR maps each SemPKM manifest key to a model fact, keeps the model's domain IRIs
as objects under SemPKM's archive namespace, states gist 14.0.0, names every fault,
and its manifest and view examples parse and satisfy SemPKM's contract."""

import json
import re
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0026-mental-model.md"
VOCAB = Namespace("urn:sempkm:vocab:")
EX = Namespace("https://example.org/expenses/")


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences", "Open questions"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize(
    "heading",
    [
        "The package: one directory, four files",
        "IRIs: SemPKM's namespace for the package, the model's IRIs for the data",
        "The manifest",
        "The shapes file",
        "gist 14.0.0",
        "The views file",
        "Same model, same bytes",
        "Faults",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}", text, re.MULTILINE), heading


@pytest.mark.parametrize(
    "term",
    [
        "owl:versionInfo",
        "rdfs:label",
        "rdfs:comment",
        "seam:notation seam:Ontology",
        "urn:sempkm:model:<modelId>:",
        "gistCore14.0.0",
        "GeneratorError(subject, predicate, detail)",
        "POST /api/models/install",
        "ifml:Details",
        "ifml:List",
        "seam:reads",
        "prov:wasDerivedFrom",
        "ADR-0025",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


def test_manifest_example_satisfies_sempkm(text: str) -> None:
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    manifest = yaml.safe_load(blocks[0])
    assert list(manifest) == ["modelId", "version", "name", "namespace", "entrypoints"]
    model_id = manifest["modelId"]
    assert re.fullmatch(r"[a-z][a-z0-9-]*", model_id) and 2 <= len(model_id) <= 64
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["namespace"] == f"urn:sempkm:model:{model_id}:"
    assert manifest["entrypoints"] == {kind: f"{kind}/{model_id}.jsonld" for kind in ("ontology", "shapes", "views")}
    assert all(isinstance(v, str) for v in manifest.values() if not isinstance(v, dict))


def test_view_example_is_a_sempkm_table_view(text: str) -> None:
    blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    document = json.loads(blocks[0])
    assert "@context" not in document
    g = Graph().parse(data=blocks[0], format="json-ld")
    view = next(g.subjects(RDF.type, VOCAB.ViewSpec))
    assert isinstance(view, URIRef)
    assert str(view).startswith("urn:sempkm:model:expense-ontology:")
    assert all(str(s).startswith("urn:sempkm:model:expense-ontology:") for s in g.subjects())
    assert (view, VOCAB.targetClass, EX.Expense) in g
    assert (view, VOCAB.rendererType, None) in g
    assert (view, PROV.wasDerivedFrom, EX.expense_list) in g
    assert (view, RDFS.label, None) in g
    columns = str(g.value(view, VOCAB.columns)).split(",")
    query = str(g.value(view, VOCAB.sparqlQuery))
    assert re.match(r"SELECT \?s " + " ".join(rf"\?{c}" for c in columns) + " WHERE", query)
    assert f"?s a <{EX.Expense}>" in query


def test_fault_table_names_subject_and_predicate(text: str) -> None:
    faults = text.split("### 10. Faults", 1)[1].split("\n### ", 1)[0]
    rows = [r for r in faults.splitlines() if r.startswith("| ") and not r.startswith("| Fault")]
    assert len(rows) >= 10
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 3 and all(cells), row


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0026", "Mental Model", "0026-mental-model"]' in config
    assert config.index("0025-sempkm-store") < config.index("0026-mental-model")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "0026-mental-model" in index


def test_adr_0025_points_forward() -> None:
    adr0025 = (ROOT / "docs" / "adr" / "0025-sempkm-store.md").read_text(encoding="utf-8")
    gist = adr0025.split("### 8. gist version", 1)[1].split("\n### ", 1)[0]
    assert "[ADR-0026](./0026-mental-model.md)" in gist
    out_of_scope = adr0025.split("### 12. Out of scope", 1)[1].split("\n## ", 1)[0]
    assert "[ADR-0026](./0026-mental-model.md)" in out_of_scope


def test_backlog_cites_adr_for_o5() -> None:
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    row = next(line for line in backlog.splitlines() if line.startswith("| O5 |"))
    assert "done (M024/S03): decided in [ADR-0026](adr/0026-mental-model.md)" in row
