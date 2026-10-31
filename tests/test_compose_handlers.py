"""The compose generator mounts the handlers package (M014/S03/T01, ADR-0012).

The runtime finds a comm:PythonHandler's code in ``handlers/`` beside the model
file, and the generated compose file bind-mounts the model files one by one
under /model, so the executing container gets ``./handlers:/model/handlers:ro``
too, but only when an operation it seam:exposes is seam:implementedBy a
comm:PythonHandler. The fixture is the expense tutorial's chapter-08 model with
one implementation fact added in memory.
"""

import sys
from pathlib import Path

import pytest
from rdflib import RDF, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import GeneratorError, extract_compose  # noqa: E402
from seams_gen.fastapi import serving_containers  # noqa: E402
from seams_runtime import ModelGraph  # noqa: E402
from seams_runtime.model import COMM, HYDRA, SEAM  # noqa: E402

APP = ROOT / "examples" / "expenses" / "chapter-08"
TRIG = APP / "expenses.trig"
SEAMS_GRAPH = URIRef("urn:seams:graph:seams")
IMPL = URIRef("https://example.org/expenses/test_impl")
MOUNT = "./handlers:/model/handlers:ro"


def _model(kind=None, *, served_in_process=True, handler="notify.notify_manager") -> ModelGraph:
    """Chapter 8, with one operation seam:implementedBy an ``kind`` node: an
    operation the executing container exposes, or one another container does."""
    model = ModelGraph.load(TRIG)
    if kind is None:
        return model
    executing = serving_containers(model)
    op = next(o for o in model.operations if any(c in executing for c in o.exposed_by) == served_in_process)
    graph = model.ds.graph(SEAMS_GRAPH)
    graph.add((op.iri, SEAM.implementedBy, IMPL))
    graph.add((IMPL, RDF.type, kind))
    if handler is not None:
        graph.add((IMPL, COMM.handler, Literal(handler)))
    return ModelGraph(TRIG, model.ds)


def _volumes(model) -> dict[str, tuple[str, ...]]:
    return {s.name: s.volumes for s in extract_compose(model, APP).services}


def test_a_python_handler_mounts_the_handlers_package_into_the_executing_container():
    model = _model(COMM.PythonHandler)
    (executing,) = serving_containers(model)
    volumes = _volumes(model)
    name = executing.iri.split("/")[-1]
    assert MOUNT in volumes[name]
    assert [v for vs in volumes.values() for v in vs].count(MOUNT) == 1


def test_the_handlers_mount_is_sorted_with_the_payload_mounts():
    (executing,) = serving_containers(_model())
    name = executing.iri.split("/")[-1]
    binds = [v for v in _volumes(_model(COMM.PythonHandler))[name] if v.endswith(":ro")]
    assert binds[0].endswith("/expenses.trig:ro")
    assert binds[1:] == sorted(binds[1:])


def test_without_a_python_handler_there_is_no_handlers_mount():
    assert all(MOUNT not in vs for vs in _volumes(_model()).values())


def test_an_llm_completion_adds_no_handlers_mount():
    model = _model(COMM.LLMCompletion, handler=None)
    assert all(MOUNT not in vs for vs in _volumes(model).values())


def test_a_handler_on_an_operation_another_container_serves_adds_no_mount():
    model = ModelGraph.load(TRIG)
    executing = serving_containers(model)
    (system,) = model.architecture.systems()
    other = next(c for c in system.containers if c not in executing)
    op = URIRef("https://example.org/expenses/test_remote_op")
    graph = model.ds.graph(SEAMS_GRAPH)
    graph.add((op, RDF.type, HYDRA.Operation))
    graph.add((other.iri, SEAM.exposes, op))
    graph.add((op, SEAM.implementedBy, IMPL))
    graph.add((IMPL, RDF.type, COMM.PythonHandler))
    graph.add((IMPL, COMM.handler, Literal("notify.notify_manager")))
    model = ModelGraph(TRIG, model.ds)
    assert op in model.operations.iris()
    assert all(MOUNT not in vs for vs in _volumes(model).values())


def test_without_the_handler_mount_the_volumes_are_unchanged():
    assert _volumes(_model()) == _volumes(_model(COMM.LLMCompletion, handler=None))


def test_a_bad_implementation_kind_names_the_fact():
    with pytest.raises(GeneratorError) as err:
        extract_compose(_model(SEAM.Layer, handler=None), APP)
    assert err.value.subject == str(IMPL)
    assert err.value.predicate == str(RDF.type)


def test_a_handler_path_outside_the_package_names_the_fact():
    with pytest.raises(GeneratorError) as err:
        extract_compose(_model(COMM.PythonHandler, handler="../os.system"), APP)
    assert err.value.subject == str(IMPL)
    assert err.value.predicate == str(COMM.handler)
