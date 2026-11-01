"""A third-party generator tested with the public kit (M018/S03, backlog K4).

The generator below stands for one written outside this repository: a YAML
variant of the review checklist in docs/guide/write-your-own-generator.md, one
entry per process with the model's hash. Its tests import only seams,
seams_gen.protocol and seams_gen.testing, as a generator in another
distribution would: the golden comparison, the determinism check, the YAML
output check and one K1 parity case (a fault the generator rejects is also a
shape violation).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import seams
from rdflib import Dataset, Namespace, URIRef

from seams_gen import GeneratorError
from seams_gen.protocol import Generator
from seams_gen.testing import (
    MARKER,
    assert_deterministic,
    assert_matches_golden,
    assert_shapes_catch,
    check_output,
)

ROOT = Path(__file__).resolve().parent.parent
CHAT_TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
GOLDEN = ROOT / "tests" / "fixtures" / "generator_kit" / "checklist.yaml"

CHAT = Namespace("https://example.org/chat/")
SEAM = Namespace("https://w3id.org/seams/seam#")


# ── the generator under test ────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    process: str
    bpmn: str
    tasks: tuple[str, ...]


@dataclass(frozen=True)
class Checklist:
    model: str
    model_hash: str
    entries: tuple[Entry, ...]


def extract_checklist(model: seams.Model) -> Checklist:
    """Every process with its BPMN model and its tasks in flow order. A process
    that is not seam:detailedBy exactly one BPMN model raises GeneratorError."""
    entries = []
    for process in sorted(model.processes, key=lambda p: p.label):
        try:
            bpmn = process.bpmn_model
        except seams.ResolutionError as err:
            raise GeneratorError(err.subject, err.predicate, err.detail) from None
        tasks = []
        for task in process.tasks():
            line = f"{task.kind}: {task.name}"
            if task.invokes is not None and task.invokes.path is not None:
                line += f" -> {task.invokes.method} {task.invokes.path.template}"
            if task.decided_by is not None:
                line += f" (decision: {task.decided_by.label})"
            tasks.append(line)
        entries.append(Entry(process.label, str(bpmn), tuple(tasks)))
    return Checklist(model.path.name, model.hash, tuple(entries))


def render_checklist(view: Checklist) -> dict[str, str]:
    q = json.dumps  # a JSON string is a YAML double-quoted scalar
    lines = [f"model: {q(view.model)}", f"model_hash: {q(view.model_hash)}", "processes:"]
    for entry in view.entries:
        lines += [f"  - process: {q(entry.process)}", f"    bpmn: {q(entry.bpmn)}", "    tasks:"]
        lines += [f"      - {q(task)}" for task in entry.tasks]
    return {"checklist.yaml": "\n".join(lines) + "\n"}


def sources(trig: Path, out: Path) -> dict[str, tuple[str, ...]]:
    model = seams.load(trig)
    return {"checklist.yaml": tuple(sorted(str(p.iri) for p in model.processes))}


checklist = Generator(
    name="checklist-yaml",
    version="0.1.0",
    help="a YAML review checklist of every process",
    extract=lambda trig, out: extract_checklist(seams.load(trig)),
    render=render_checklist,
    sources=sources,
)


# ── its tests, on the public kit ────────────────────────────────────────────


def test_output_matches_golden(tmp_path):
    files = checklist.generate(CHAT_TRIG, tmp_path)
    assert sorted(files) == ["checklist.yaml"]
    assert_matches_golden(files["checklist.yaml"], GOLDEN, seams.load(CHAT_TRIG).hash)


def test_output_is_deterministic(tmp_path):
    assert_deterministic(checklist, CHAT_TRIG, tmp_path)


def test_output_is_valid_yaml(tmp_path):
    for name, text in checklist.generate(CHAT_TRIG, tmp_path).items():
        check_output(name, text)


def test_sources_name_the_generated_files(tmp_path):
    assert set(checklist.sources(CHAT_TRIG, tmp_path)) == set(checklist.generate(CHAT_TRIG, tmp_path))


def test_golden_graph_terms_exist_in_the_model():
    """Each `:name` term in a [graph: ...] marker is an IRI of the chat-app model."""
    ds = Dataset(default_union=True)
    ds.parse(CHAT_TRIG, format="trig")
    iris = {str(t) for quad in ds.quads((None, None, None, None)) for t in quad[:3] if isinstance(t, URIRef)}
    lines = [line for line in GOLDEN.read_text().splitlines() if line.strip()]
    for line in lines:
        marker = MARKER.search(line)
        assert marker, f"{GOLDEN}: line without a marker: {line!r}"
        for term in re.findall(r"(?<![\w:]):([\w#]+)", marker.group(1)):
            assert str(CHAT[term]) in iris, f"{GOLDEN}: {CHAT[term]} is not in {CHAT_TRIG.name}: {line!r}"


def test_process_without_bpmn_model_is_a_shape_violation():
    ds = Dataset(default_union=True)
    ds.parse(CHAT_TRIG, format="trig")
    fact = (CHAT.send_message_process, SEAM.detailedBy, CHAT.chat_bpmn)
    assert fact in ds
    for graph in ds.graphs():
        graph.remove(fact)

    assert_shapes_catch(
        extract_checklist,
        ds,
        subject=CHAT.send_message_process,
        predicate=SEAM.detailedBy,
        focus=CHAT.send_message_process,
        path=SEAM.detailedBy,
        match="expected one BPMN model",
        model_path=CHAT_TRIG,
    )
