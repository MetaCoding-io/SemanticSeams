"""seams_runtime re-exports the read-only core from seams (M010/S02, D034)."""

from pathlib import Path

import pytest
import seams
import seams.graph
from rdflib import URIRef

import seams_runtime
import seams_runtime.errors
import seams_runtime.model

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app/chat-app.trig"
RESOLVER_RESULTS = {"Container", "Lifecycle", "Transition"}


def test_runtime_names_are_the_seams_objects():
    assert seams_runtime.ModelGraph is seams.ModelGraph
    assert seams_runtime.ResolutionError is seams.ResolutionError
    assert seams_runtime.model_hash is seams.model_hash
    assert seams_runtime.RuntimeModelError is seams.SeamsError
    assert issubclass(seams_runtime.ResolutionError, seams_runtime.RuntimeModelError)


@pytest.mark.parametrize(
    "name",
    [
        "COMM",
        "DEC",
        "DEPLOY",
        "HYDRA",
        "IFML",
        "ODRL",
        "PROC",
        "SEAM",
        "STATE",
        "ChannelBinding",
        "ChannelStart",
        "Container",
        "DecisionBinding",
        "InputBinding",
        "Lifecycle",
        "ModelGraph",
        "OperationPath",
        "OutputBinding",
        "PathMapping",
        "Permission",
        "PolicyFacts",
        "ProcessFacts",
        "Transition",
        "bpmn_start_event_ids",
        "dmn_decision_ids",
        "dmn_input_types",
        "local_name",
        "model_hash",
        "payload_path",
    ],
)
def test_model_module_reexports(name):
    # Container, Lifecycle and Transition at the top level of seams are the
    # view classes (M010/S03); the runtime keeps the resolver results.
    source = seams.graph if name in RESOLVER_RESULTS else seams
    assert getattr(seams_runtime.model, name) is getattr(source, name)


def test_runtime_errors_still_subclass_the_one_base():
    for name in ("ContractViolation", "LifecycleViolation", "ModelHashMismatch", "PolicyDenied", "TaskNotOpen"):
        assert issubclass(getattr(seams_runtime.errors, name), seams.SeamsError), name


def test_model_graph_is_a_model_and_resolves():
    graph = seams.ModelGraph(CHAT)
    assert isinstance(graph, seams.Model)
    assert graph.hash == seams.model_hash(CHAT)
    assert isinstance(graph.landmark_page(), URIRef)


def test_resolver_miss_raises_resolution_error_caught_as_runtime_error():
    graph = seams.ModelGraph(CHAT)
    with pytest.raises(seams_runtime.RuntimeModelError) as info:
        graph.invoked_operation(URIRef("https://example.org/no#task"))
    err = info.value
    assert isinstance(err, seams.ResolutionError)
    assert err.to_dict()["type"] == "ResolutionError"
    assert err.to_dict()["subject"] == "https://example.org/no#task"


def test_store_interface_and_backends_are_exported():
    import seams_runtime.store

    for name in ("Store", "SQLiteStore", "PostgresStore"):
        assert name in seams_runtime.__all__, name
        assert getattr(seams_runtime, name) is getattr(seams_runtime.store, name)
