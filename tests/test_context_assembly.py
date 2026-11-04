"""seams.context (M022/S01, backlog C3): the context of a service task.

Run on Send Now in the expense tutorial's chapter 9: the manifest lists the
model facts and native file fragments its code depends on, each hashed, and a
context hash over them. A change to a fact the task uses changes that item's
hash and the context hash; a change to a fact it does not use changes neither.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDF, RDFS, BNode, Literal, URIRef, namespace
from rdflib.namespace import SH
from seams import PROC, SEAM, ContextItem, Manifest, ModelGraph, ResolutionError, context_for

ROOT = Path(__file__).resolve().parent.parent
CH09_DIR = ROOT / "examples/expenses/chapter-09"
CH09 = CH09_DIR / "expenses.trig"
EX = "https://example.org/expenses/"
SEND_NOW = f"{EX}payout_bpmn#send_now"

EXPECTED = [
    ("bpmn", "payout.bpmn#flow_now"),
    ("bpmn", "payout.bpmn#method_gateway"),
    ("bpmn", "payout.bpmn#send_now"),
    ("container", f"{EX}expense_api"),
    ("decision", f"{EX}payout_method"),
    ("dmn", "payout.dmn#payout_method"),
    ("process", f"{EX}payout_process"),
    ("shape", f"{EX}PaymentShape"),
    ("state", f"{EX}s_scheduled"),
    ("state", f"{EX}s_sent"),
    ("task", SEND_NOW),
    ("transition", f"{EX}t_send"),
]


def _hashes(manifest: Manifest) -> dict[tuple[str, str], str]:
    return {(i.kind, i.ref): i.hash for i in manifest.items}


def _item(manifest: Manifest, kind: str, ref: str) -> ContextItem:
    return next(i for i in manifest.items if (i.kind, i.ref) == (kind, ref))


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return context_for(seams.load(CH09), "send_now")


def test_send_now_lists_the_facts_its_code_depends_on(manifest: Manifest) -> None:
    assert manifest.task == URIRef(SEND_NOW)
    assert [(i.kind, i.ref) for i in manifest.items] == EXPECTED
    for item in manifest.items:
        assert item.hash.startswith("sha256:") and len(item.hash) == len("sha256:") + 64
        assert item.hash == "sha256:" + hashlib.sha256(item.content.encode()).hexdigest()


def test_context_hash_frames_items_sorted_by_kind_and_ref(manifest: Manifest) -> None:
    framed = "".join(f"{i.kind}\0{i.ref}\0{i.hash}\n" for i in sorted(manifest.items, key=lambda i: (i.kind, i.ref)))
    assert manifest.context_hash == "sha256:" + hashlib.sha256(framed.encode()).hexdigest()


def test_items_hold_the_facts_the_rules_name(manifest: Manifest) -> None:
    shape = _item(manifest, "shape", f"{EX}PaymentShape").content
    assert f"<{EX}paidOn>" in shape and f"<{namespace.XSD.date}>" in shape  # down to the property shapes
    assert str(SEAM.storedIn) not in shape and str(SEAM.lifecycle) not in shape
    transition = _item(manifest, "transition", f"{EX}t_send").content
    assert f"<{EX}s_scheduled>" in transition and f"<{EX}s_sent>" in transition
    process = _item(manifest, "process", f"{EX}payout_process").content
    assert f"<{PROC.correlationKey}> <{EX}expense>" in process
    decision = _item(manifest, "decision", f"{EX}payout_method").content
    assert '"method"' in decision
    flow = _item(manifest, "bpmn", "payout.bpmn#flow_now").content
    assert 'method == "now"' in flow
    assert _item(manifest, "dmn", "payout.dmn#payout_method").content.startswith("<decision ")
    task = _item(manifest, "task", SEND_NOW).content
    assert str(SEAM.writes) in task and str(SEAM.fires) in task


def test_container_names_bindings_never_their_values(manifest: Manifest) -> None:
    container = _item(manifest, "container", f"{EX}expense_api").content
    assert '"FastAPI"' in container and '"DATABASE_URL"' in container
    # Every value-bearing fact of expense_api's bindings, shared and overridden.
    secrets = [
        "https://secrets.example.org/expenses/prod/database-url",
        "expenses-prod-database-url",
        "docker/local-secrets/expense_database_url",
        "secretRef",
        "secretName",
        "secretFile",
        "deploy#value",
        "connectsTo",
    ]
    everything = repr(manifest) + "".join(i.content for i in manifest.items)
    for secret in secrets:
        assert secret not in everything
    # Unrelated container facts are left out too.
    assert "seam#exposes" not in container and "deploy#artifact" not in container


def test_two_loads_give_the_same_hash(manifest: Manifest) -> None:
    again = context_for(ModelGraph(CH09), URIRef(SEND_NOW))
    assert again == manifest
    assert [i.content for i in again.items] == [i.content for i in manifest.items]


def test_hash_does_not_depend_on_the_process() -> None:
    script = f"import seams; print(seams.context_for(seams.load({str(CH09)!r}), 'send_now').context_hash)"
    seen = {
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2")
    }
    assert len(seen) == 1


def test_changing_a_shape_datatype_changes_that_item_and_the_context(manifest: Manifest) -> None:
    model = seams.load(CH09)
    ds = model.ds
    prop = next(
        o for o in ds.objects(URIRef(f"{EX}PaymentShape"), SH.property) if (o, SH.path, URIRef(f"{EX}reference")) in ds
    )
    assert isinstance(prop, BNode)
    ds.remove((prop, SH.datatype, namespace.XSD.string))
    ds.add((prop, SH.datatype, namespace.XSD.token))
    changed = context_for(model, "send_now")
    before, after = _hashes(manifest), _hashes(changed)
    assert [k for k in before if before[k] != after[k]] == [("shape", f"{EX}PaymentShape")]
    assert changed.context_hash != manifest.context_hash


def test_an_unrelated_operation_on_the_container_changes_nothing(manifest: Manifest) -> None:
    model = seams.load(CH09)
    op = URIRef(f"{EX}unrelated_op")
    model.ds.add((op, RDF.type, URIRef("http://www.w3.org/ns/hydra/core#Operation")))
    model.ds.add((op, RDFS.label, Literal("Unrelated")))
    model.ds.add((URIRef(f"{EX}expense_api"), SEAM.exposes, op))
    assert context_for(model, "send_now") == manifest


def test_editing_the_gateway_condition_changes_the_flow_fragment(tmp_path: Path, manifest: Manifest) -> None:
    for path in [CH09, *CH09_DIR.glob("*.bpmn"), *CH09_DIR.glob("*.dmn")]:
        shutil.copy(path, tmp_path / path.name)
    bpmn = tmp_path / "payout.bpmn"
    text = bpmn.read_text()
    assert 'method == "now"' in text
    bpmn.write_text(text.replace('method == "now"', 'method == "now" or method == "urgent"', 1))
    changed = context_for(seams.load(tmp_path / "expenses.trig"), "send_now")
    before, after = _hashes(manifest), _hashes(changed)
    assert [k for k in before if before[k] != after[k]] == [("bpmn", "payout.bpmn#flow_now")]


def test_a_service_task_without_a_gateway_has_no_decision() -> None:
    m = context_for(seams.load(CH09), "schedule_payout")
    kinds = {i.kind for i in m.items}
    assert "decision" not in kinds and "dmn" not in kinds
    assert ("transition", f"{EX}t_schedule") in {(i.kind, i.ref) for i in m.items}


@pytest.mark.parametrize(
    ("task", "predicate"),
    [
        ("no_such_task", SEAM.detailedBy),  # no BPMN element has this id
        (f"{EX}nothing_here", RDF.type),  # an IRI the graph does not type
        ("choose_payout", RDF.type),  # a business-rule task
        ("method_gateway", RDF.type),  # a gateway, not lifted into the graph
        ("payout_requested", RDF.type),  # a message catch event
    ],
)
def test_an_unknown_or_non_service_task_raises(task: str, predicate: URIRef) -> None:
    with pytest.raises(ResolutionError) as err:
        context_for(seams.load(CH09), task)
    assert err.value.predicate == str(predicate)


def test_a_process_without_a_correlation_key_raises() -> None:
    model = seams.load(CH09)
    model.ds.remove((URIRef(f"{EX}payout_process"), PROC.correlationKey, None))
    with pytest.raises(ResolutionError) as err:
        context_for(model, "send_now")
    assert (err.value.subject, err.value.predicate) == (f"{EX}payout_process", str(PROC.correlationKey))


def test_a_process_no_container_executes_raises() -> None:
    model = seams.load(CH09)
    model.ds.remove((None, SEAM.executes, URIRef(f"{EX}payout_process")))
    with pytest.raises(ResolutionError) as err:
        context_for(model, "send_now")
    assert (err.value.subject, err.value.predicate) == (f"{EX}payout_process", str(SEAM.executes))
