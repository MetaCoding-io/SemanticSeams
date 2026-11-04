"""ADR-0027 (M024/S04): SemPKM webhooks as a channel are decided before the code.
The ADR names the transport value and the channel's facts, maps SemPKM's actual
delivery body to start state, authenticates by reading the event back (SemPKM signs
nothing), keeps the runtime's own writes from starting processes, and names every
resolution error and run-time failure."""

import json
import re
from pathlib import Path

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0027-sempkm-webhook-channel.md"
COMM = Namespace("https://w3id.org/seams/comm#")
SEAM = Namespace("https://w3id.org/seams/seam#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
PROC = Namespace("https://w3id.org/seams/proc#")
EX = Namespace("https://example.org/expenses/")


@pytest.fixture(scope="module")
def text() -> str:
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def test_adr_is_accepted(text: str) -> None:
    assert "**Status:** Accepted" in text


@pytest.mark.parametrize("heading", ["Context", "Decision", "Alternatives", "Consequences"])
def test_adr_has_section(text: str, heading: str) -> None:
    assert re.search(rf"^## {heading}\b", text, re.MULTILINE), heading


def test_decision_sections_are_numbered_in_order(text: str) -> None:
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize(
    "heading",
    [
        "A transport value: `comm:SemPKMWebhook`",
        "The facts of a webhook channel",
        "The route: `POST` at the channel's `comm:path`",
        "The payload, and how it maps to start state",
        "Idempotence: one start per process, event and object",
        "Authenticity: read the event back, trust no field",
        "The runtime's own writes do not start processes",
        "Run-time failures",
        "Load",
        "Resolution errors",
        "Open points",
    ],
)
def test_adr_decides(text: str, heading: str) -> None:
    assert re.search(rf"^### \d+\. {re.escape(heading)}$", text, re.MULTILINE), heading


@pytest.mark.parametrize(
    "term",
    [
        "comm:SemPKMWebhook",
        "comm:eventName",
        "seam:acceptsShape",
        "seam:subscribesTo",
        "seam:storedIn",
        "deploy:authenticatesTo",
        "Runtime.start_subscribed",
        "SemPKMStore",
        "sempkm:affectedIRI",
        "urn:sempkm:event:",
        "ResolutionError(subject,",
        "GeneratorError",
        "problem+json",
        "ADR-0010",
        "ADR-0025",
    ],
)
def test_adr_names_term(text: str, term: str) -> None:
    assert term in text


def test_model_example_is_a_webhook_channel(text: str) -> None:
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    g = Graph().parse(data=blocks[0], format="turtle")
    channel = EX.vendor_changes
    assert (channel, RDF.type, COMM.Channel) in g
    assert list(g.objects(channel, COMM.transport)) == [COMM.SemPKMWebhook]
    assert [str(o) for o in g.objects(channel, COMM.eventName)] == ["object.changed"]
    shapes = list(g.objects(channel, SEAM.acceptsShape))
    assert len(shapes) == 1 and (shapes[0], SEAM.storedIn, None) in g
    paths = list(g.objects(channel, COMM.path))
    assert len(paths) == 1 and (paths[0], HYDRA.mapping, None) not in g
    assert list(g.subjects(SEAM.exposes, channel)) == [EX.expense_api]
    starts = list(g.subjects(SEAM.subscribesTo, channel))
    assert len(starts) == 1 and (starts[0], RDF.type, PROC.MessageCatchEvent) in g
    assert (None, SEAM.publishesTo, channel) not in g


def test_payload_example_is_sempkms_delivery_body(text: str) -> None:
    # app/services/webhooks.py posts {"event_type": ..., **payload}; app/commands/router.py
    # passes event_iri, command and timestamp. Nothing else, and no object IRI.
    blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1
    body = json.loads(blocks[0])
    assert list(body) == ["event_type", "event_iri", "command", "timestamp"]
    assert body["event_type"] == "object.changed"
    assert body["event_iri"].startswith("urn:sempkm:event:")


def test_authenticity_states_sempkm_signs_nothing(text: str) -> None:
    section = _section(text, "### 6. Authenticity")
    assert "signs nothing" in section
    assert "No secret is added to the deploy facts" in section
    assert "appears in no log line" in section


def test_failure_table_covers_the_run_time_cases(text: str) -> None:
    section = _section(text, "### 8. Run-time failures")
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Case")]
    assert len(rows) >= 9
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 3 and all(cells), row
    answers = {cells.split("|")[2].strip().split(",")[0] for cells in rows}
    assert {"400", "202", "422", "503", "502"} <= answers
    assert "unverified event" in section


def test_resolution_table_names_subject_and_predicate(text: str) -> None:
    section = _section(text, "### 10. Resolution errors")
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Case")]
    assert len(rows) >= 12
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 3 and all(cells), row
        assert re.fullmatch(r"`[a-z]+:\w+`", cells[2]), row


def test_load_names_the_breakpoint(text: str) -> None:
    section = _section(text, "### 9. Load")
    assert "60 requests a minute" in section
    assert "429" in section


def test_adr_is_in_decisions_nav() -> None:
    config = (ROOT / "docs" / ".vitepress" / "config.ts").read_text(encoding="utf-8")
    assert '["0027", "SemPKM webhooks", "0027-sempkm-webhook-channel"]' in config
    assert config.index("0026-mental-model") < config.index("0027-sempkm-webhook-channel")


def test_adr_is_in_adr_index() -> None:
    index = (ROOT / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    assert "0027-sempkm-webhook-channel" in index


def test_adr_0025_points_forward() -> None:
    adr0025 = (ROOT / "docs" / "adr" / "0025-sempkm-store.md").read_text(encoding="utf-8")
    out_of_scope = adr0025.split("### 12. Out of scope", 1)[1].split("\n## ", 1)[0]
    assert "[ADR-0027](./0027-sempkm-webhook-channel.md)" in out_of_scope
