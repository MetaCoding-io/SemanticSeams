"""External systems (ADR-0040, M031/S02): the shapes and the typed views.

Every dataset is inline TriG built from ``dataset()``: the expense system, whose API
exposes the SemPKM webhook channel and reaches the knowledge store through bindings that
carry its URL and token, and an external ``:sempkm`` system that contains the store and
its triplestore and exposes one command operation. The dataset conforms; each negative
case breaks one fact and asserts the one violation by focus node, result path and shape,
with the message asserted exactly, so a finding names the subject and the predicate as
``seams check`` prints it. A dataset with no ``arch:external`` triple triggers none of
the shapes. The views are read through ``seams.Model`` from the same text.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
import pytest
import seams
from rdflib import RDF, RDFS, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH
from seams import ARCH, SEAM, ResolutionError

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES = Graph().parse(ONTOLOGY / "shapes" / "seam-shapes.ttl")
EX = Namespace("https://example.org/expenses/")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/expenses/> .
"""

OWN = """
    :expense_system a arch:System ; rdfs:label "Expense Approval" ;
        arch:contains :expense_api .
    :expense_api a arch:Container ; rdfs:label "Expense API" ;
        arch:dependsOn :expense_pkm ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://sempkm.example:8000" ;
                             deploy:connectsTo :expense_pkm ] ] .
    :dev a arch:Environment ; rdfs:label "dev" .
"""

EXTERNAL = """
    :sempkm a arch:System ; rdfs:label "SemPKM" ;
        arch:external true ;
        arch:technology "SemPKM" ;
        arch:contains :expense_pkm , :expense_triplestore .
    :expense_pkm a arch:Container ; rdfs:label "Expense Knowledge Store" ;
        arch:technology "SemPKM" ;
        deploy:storeKind deploy:SemPKM ;
        arch:dependsOn :expense_triplestore .
    :expense_triplestore a arch:Container ; rdfs:label "Expense Triplestore" ;
        arch:technology "RDF4J" .
"""

COMM = """
    :object_changed a comm:Channel ; rdfs:label "object changed" .
    :pkm_command a hydra:Operation ; rdfs:label "SemPKM command" ; hydra:method "POST" .
"""

SEAMS = """
    :expense_api seam:exposes :object_changed .
    :expense_pkm seam:exposes :pkm_command .
"""


def dataset(own: str = OWN, external: str = EXTERNAL, seams_graph: str = SEAMS, extra: str = "") -> str:
    return (
        PREFIXES
        + f"\n<urn:seams:graph:model:expense_architecture> {{{own}{external}{extra}}}\n"
        + f"\n<urn:seams:graph:model:expense_comm> {{{COMM}}}\n"
        + f"\n<urn:seams:graph:seams> {{{seams_graph}}}\n"
    )


def validate(trig: str) -> Graph:
    """The SHACL report for ``trig``'s quads and the vocabularies in one graph, as
    ``seams check`` validates."""
    ds = Dataset()
    ds.parse(data=trig, format="trig")
    data = Graph()
    for vocabulary in sorted(ONTOLOGY.glob("*.ttl")):
        data.parse(vocabulary)
    for s, p, o, _graph in ds.quads((None, None, None, None)):
        data.add((s, p, o))
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=SHAPES, inference="none")
    assert isinstance(report, Graph)
    return report


def _name(term: object) -> str:
    text = "-" if term is None else str(term)
    for namespace in (EX, ARCH, SEAMSH, DEPLOY, SEAM):
        text = text.removeprefix(str(namespace))
    return text


def violations(trig: str) -> set[tuple[str, str, str]]:
    """(focus node, result path, owning node shape) for every result."""
    report = validate(trig)
    found: set[tuple[str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        shape = report.value(result, SH.sourceShape)
        # A property or SPARQL constraint is a blank node: report the node shape that owns it.
        owner = next(iter(SHAPES.subjects(SH.property, shape)), None) or next(  # type: ignore[arg-type]
            iter(SHAPES.subjects(SH.sparql, shape)),  # type: ignore[arg-type]
            shape,
        )
        found.add(
            (
                _name(report.value(result, SH.focusNode)),
                _name(report.value(result, SH.resultPath)),
                _name(owner),
            )
        )
    return found


def external_findings(trig: str) -> set[tuple[str, str, str]]:
    """The ADR-0040 shapes' findings: a broken fact can break an older rule too."""
    return {v for v in violations(trig) if v[2].startswith("External")}


def messages(trig: str) -> list[str]:
    return sorted(str(m) for m in validate(trig).objects(None, SH.resultMessage))


MARKER = "arch:external is stated at most once, and only as true."
ONLY_SYSTEM = "Only an arch:System is arch:external."
CONTAINMENT = "A container of an external arch:System is arch:contains'ed by no other arch:System."
CONTAINER = (
    "A container of an external arch:System carries no deploy:artifact, deploy:override, deploy:port, "
    "deploy:volume, deploy:healthcheck, deploy:configuration, deploy:placement, deploy:proxies or "
    "deploy:dependsOn, and seam:executes, seam:presents, seam:schedules and seam:deployedTo nothing: "
    "the model neither builds nor runs it."
)
DEPENDS_ON = "No container deploy:dependsOn a container of an external arch:System: it has no service to start first."
SERVICE_OF = (
    "No binding is a deploy:serviceOf a container of an external arch:System: it has no service to "
    "take a URL from, so the binding carries the URL in a deploy:value or a secret."
)


# ── shapes ──────────────────────────────────────────────────────────────────────


def test_an_external_system_with_containers_and_operations_conforms() -> None:
    assert violations(dataset()) == set()


def test_a_model_with_no_external_system_conforms() -> None:
    assert violations(dataset(external=EXTERNAL.replace("arch:external true ;", ""))) == set()


def test_the_shipped_vocabulary_declares_the_marker_at_arch_1_3() -> None:
    vocabulary = Graph().parse(ONTOLOGY / "arch.ttl")
    assert (ARCH.external, RDF.type, RDF.Property) in vocabulary
    assert (ARCH.external, RDFS.domain, ARCH.System) in vocabulary
    assert (ARCH.external, RDFS.range, Literal(True).datatype) in vocabulary
    assert seams.shipped_versions(ONTOLOGY)["arch"] == (1, 3)


@pytest.mark.parametrize("value", ["false", '"true"', '"yes"', "1"])
def test_the_marker_is_only_true(value: str) -> None:
    trig = dataset(external=EXTERNAL.replace("arch:external true", f"arch:external {value}"))
    assert violations(trig) == {("sempkm", "external", "ExternalMarkerShape")}
    assert messages(trig) == [MARKER]


def test_the_marker_is_stated_once() -> None:
    trig = dataset(external=EXTERNAL.replace("arch:external true", "arch:external true , false"))
    assert violations(trig) == {("sempkm", "external", "ExternalMarkerShape")}
    # maxCount and sh:in each report it.
    assert messages(trig) == [MARKER, MARKER]


def test_only_a_system_is_external() -> None:
    trig = dataset(extra="    :expense_api arch:external true .\n")
    assert violations(trig) == {("expense_api", "external", "ExternalMarkerShape")}
    assert messages(trig) == [ONLY_SYSTEM]


def test_no_other_system_contains_an_external_container() -> None:
    trig = dataset(own=OWN.replace("arch:contains :expense_api .", "arch:contains :expense_api , :expense_pkm ."))
    # The store seam:exposes an operation, so the one-system rule for serving containers speaks too.
    assert external_findings(trig) == {("expense_pkm", "contains", "ExternalContainmentShape")}
    assert CONTAINMENT in messages(trig)


DEPLOY_FACTS = {
    "artifact": ':expense_pkm deploy:artifact [ a deploy:Artifact ; deploy:reference "sempkm" ; deploy:version "1" ] .',
    "port": ":expense_pkm deploy:port [ a deploy:Port ; deploy:containerPort 8000 ] .",
    "volume": ':expense_pkm deploy:volume [ deploy:volumeName "pkm" ; deploy:mountPath "/data" ] .',
    "healthcheck": ':expense_pkm deploy:healthcheck [ deploy:probe "true" ; deploy:interval "5s" ] .',
    "configuration": (
        ":expense_pkm deploy:configuration [ a deploy:Configuration ;"
        ' deploy:binding [ deploy:key "MODE" ; deploy:value "dev" ] ] .'
    ),
    "override": ":expense_pkm deploy:override [ a deploy:Override ; deploy:environment :dev ] .",
    "placement": ":expense_pkm deploy:placement [ a deploy:PlacementPolicy ; deploy:targetEnvironment :dev ] .",
    "proxies": ":expense_pkm deploy:proxies :expense_triplestore .",
    "dependsOn": ":expense_pkm deploy:dependsOn :expense_triplestore .",
}


@pytest.mark.parametrize("predicate", sorted(DEPLOY_FACTS))
def test_an_external_container_carries_no_deploy_fact(predicate: str) -> None:
    trig = dataset(extra=f"    {DEPLOY_FACTS[predicate]}\n")
    assert external_findings(trig) == {("expense_pkm", predicate, "ExternalContainerShape")}
    # Only a proxy breaks an older rule as well: its two ends need one deploy:port each.
    others = violations(trig) - external_findings(trig)
    if predicate == "proxies":
        assert others == {
            ("expense_pkm", "port", "SinglePortShape"),
            ("expense_triplestore", "port", "SinglePortShape"),
        }
    else:
        assert others == set()
    assert CONTAINER in messages(trig)


SEAM_FACTS = {
    "executes": (":expense_pkm seam:executes :sync .", '    :sync a proc:Process ; rdfs:label "Sync" .\n'),
    "presents": (
        ":expense_pkm seam:presents :expense_ui_model .",
        "    :expense_ui_model a seam:Model ; seam:notation seam:IFML .\n",
    ),
    "schedules": (":expense_pkm seam:schedules :sync .", '    :sync a proc:Process ; rdfs:label "Sync" .\n'),
    "deployedTo": (":expense_pkm seam:deployedTo :host .", '    :host a arch:DeploymentNode ; rdfs:label "host" .\n'),
}


@pytest.mark.parametrize("predicate", sorted(SEAM_FACTS))
def test_an_external_container_runs_nothing(predicate: str) -> None:
    fact, extra = SEAM_FACTS[predicate]
    trig = dataset(seams_graph=f"{SEAMS}    {fact}\n", extra=extra)
    assert external_findings(trig) == {("expense_pkm", predicate, "ExternalContainerShape")}
    assert CONTAINER in messages(trig)


def test_no_container_of_the_model_deploy_depends_on_an_external_container() -> None:
    trig = dataset(extra="    :expense_api deploy:dependsOn :expense_pkm .\n")
    # ADR-0040 names the predicate; the older same-system rule refuses it as well.
    assert violations(trig) == {
        ("expense_api", "dependsOn", "ExternalReachShape"),
        ("expense_api", "-", "SameSystemShape"),
    }
    assert DEPENDS_ON in messages(trig)


def test_no_shared_binding_is_a_service_of_an_external_container() -> None:
    trig = dataset(own=OWN.replace('deploy:value "http://sempkm.example:8000"', "deploy:serviceOf :expense_pkm"))
    assert external_findings(trig) == {("expense_api", "serviceOf", "ExternalReachShape")}
    assert SERVICE_OF in messages(trig)


def test_no_override_binding_is_a_service_of_an_external_container() -> None:
    override = """    :expense_api deploy:override [ a deploy:Override ; deploy:environment :dev ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:serviceOf :expense_pkm ;
                             deploy:connectsTo :expense_pkm ] ] ] .
"""
    trig = dataset(extra=override)
    assert external_findings(trig) == {("expense_api", "serviceOf", "ExternalReachShape")}
    assert SERVICE_OF in messages(trig)


def test_a_service_binding_to_the_models_own_container_conforms() -> None:
    own = (
        OWN
        + """
    :expense_system arch:contains :expense_worker .
    :expense_api deploy:port [ a deploy:Port ; deploy:containerPort 8000 ] .
    :expense_worker a arch:Container ; rdfs:label "Expense Worker" ;
        deploy:dependsOn :expense_api ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "API_URL" ; deploy:serviceOf :expense_api ] ] .
"""
    )
    assert violations(dataset(own=own)) == set()


# ── typed views ─────────────────────────────────────────────────────────────────


def load(tmp_path: Path, text: str) -> seams.Model:
    path = tmp_path / "model.trig"
    path.write_text(text)
    return seams.Model(path, check_versions=False, check_imports=False)


@pytest.fixture
def model(tmp_path: Path) -> seams.Model:
    return load(tmp_path, dataset())


def test_the_system_says_whether_it_is_external(model: seams.Model) -> None:
    architecture = model.architecture
    assert architecture.systems().by_iri(EX.sempkm).external is True
    assert architecture.systems().by_iri(EX.expense_system).external is False
    assert architecture.external_systems().iris() == (EX.sempkm,)
    assert architecture.own_systems().iris() == (EX.expense_system,)


def test_containers_are_external_by_derivation(model: seams.Model) -> None:
    architecture = model.architecture
    assert architecture.external_containers().iris() == (EX.expense_pkm, EX.expense_triplestore)
    store = architecture.containers().by_iri(EX.expense_pkm)
    assert store.external is True
    system = store.external_system
    assert system is not None and system.iri == EX.sempkm
    api = architecture.containers().by_iri(EX.expense_api)
    assert api.external is False and api.external_system is None


def test_operations_are_external_when_an_external_container_exposes_them(model: seams.Model) -> None:
    store = model.architecture.containers().by_iri(EX.expense_pkm)
    api = model.architecture.containers().by_iri(EX.expense_api)
    assert [e.external for e in store.exposes] == [True]
    # The inbound webhook channel is the model's: its container exposes it.
    assert [e.external for e in api.exposes] == [False]


def test_a_model_with_no_marker_has_no_external_system(tmp_path: Path) -> None:
    model = load(tmp_path, dataset(external=EXTERNAL.replace("arch:external true ;", "")))
    assert model.architecture.external_systems().iris() == ()
    assert model.architecture.external_containers().iris() == ()
    assert len(model.architecture.own_systems()) == 2


@pytest.mark.parametrize(
    ("value", "found"),
    [
        ("false", '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>'),
        ('"yes"', '"yes"'),
        (
            "true , false",
            '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>, "true"^^<http://www.w3.org/2001/XMLSchema#boolean>',
        ),
    ],
)
def test_a_marker_that_is_not_one_true_names_the_system(tmp_path: Path, value: str, found: str) -> None:
    model = load(tmp_path, dataset(external=EXTERNAL.replace("arch:external true", f"arch:external {value}")))
    system = model.architecture.systems().by_iri(EX.sempkm)
    with pytest.raises(ResolutionError) as err:
        _ = system.external
    assert (err.value.subject, err.value.predicate) == (str(EX.sempkm), str(ARCH.external))
    assert err.value.detail == f"expected it once and only as true, found {found}"


def test_an_external_container_in_a_second_system_names_the_container(tmp_path: Path) -> None:
    own = OWN.replace("arch:contains :expense_api .", "arch:contains :expense_api , :expense_pkm .")
    model = load(tmp_path, dataset(own=own))
    store = model.architecture.containers().by_iri(EX.expense_pkm)
    with pytest.raises(ResolutionError) as err:
        _ = store.external
    assert (err.value.subject, err.value.predicate) == (str(EX.expense_pkm), str(ARCH.contains))
    assert err.value.detail == (
        "a container of an external arch:System is contained by no other system, "
        f"found {EX.expense_system}, {EX.sempkm}"
    )


# ── generators and impact (ADR-0040 sections 3 and 4, S02/T03) ─────────────────
#
# Chapter 10 of the expense tutorial models SemPKM as the external :sempkm. The
# generator cases mutate a copy of its dataset in memory and assert, through
# seams_gen.testing.assert_shapes_catch, that the compose generator and the shapes
# refuse the same fact on the same subject (principle 5).

CHAPTER_10 = ROOT / "examples" / "expenses" / "chapter-10" / "expenses.trig"
ARCH_GRAPH = "urn:seams:graph:model:expense_architecture"


def _compose_all(model: seams.Model) -> list:
    from seams_gen.compose import environments, extract_compose

    return [extract_compose(model, model.path.parent, env) for env in environments(model)]


def _chapter_10() -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(str(CHAPTER_10), format="trig")
    return ds


def test_compose_writes_no_service_for_an_external_container() -> None:
    from seams_gen.compose import environments, extract_compose

    model = seams.ModelGraph(CHAPTER_10)
    for env in environments(model):
        compose = extract_compose(model, model.path.parent, env)
        assert [s.name for s in compose.services] == ["employee_portal", "expense_api", "expense_db"]
        assert compose.volumes == ("expense_db_data",)
        # the project is the one system that is not external
        assert (compose.project, compose.origins) == ("expense_system", (str(EX.expense_system),))
        assert all(str(EX.sempkm) not in s.origins for s in compose.services)
        (api,) = (s for s in compose.services if s.name == "expense_api")
        assert [d.name for d in api.depends_on] == ["expense_db"]


def test_compose_refuses_two_systems_the_model_runs() -> None:
    from seams_gen import GeneratorError
    from seams_gen.compose import environments, extract_compose

    ds = _chapter_10()
    ds.graph(URIRef(ARCH_GRAPH)).remove((EX.sempkm, ARCH.external, Literal(True)))
    model = seams.ModelGraph(CHAPTER_10, dataset=ds)
    with pytest.raises(GeneratorError) as raised:
        extract_compose(model, model.path.parent, environments(model)[0])
    assert raised.value.predicate == str(ARCH.contains)
    assert "expected one arch:System that is not arch:external, found 2" in str(raised.value)


def test_compose_and_shapes_refuse_a_depends_on_an_external_container() -> None:
    from seams_gen.testing import assert_shapes_catch

    ds = _chapter_10()
    ds.graph(URIRef(ARCH_GRAPH)).add((EX.expense_api, DEPLOY.dependsOn, EX.expense_pkm))
    assert_shapes_catch(
        _compose_all,
        ds,
        subject=EX.expense_api,
        predicate=DEPLOY.dependsOn,
        focus=EX.expense_api,
        path=DEPLOY.dependsOn,
        match=f"{EX.expense_pkm} is a container of the arch:external system {EX.sempkm}",
        model_path=CHAPTER_10,
    )


def test_compose_and_shapes_refuse_a_service_url_of_an_external_container() -> None:
    from seams_gen.testing import assert_shapes_catch

    ds = _chapter_10()
    g = ds.graph(URIRef(ARCH_GRAPH))
    (binding,) = g.subjects(DEPLOY.key, Literal("SEMPKM_URL"))
    g.remove((binding, DEPLOY.value, None))
    g.add((binding, DEPLOY.serviceOf, EX.expense_pkm))
    assert_shapes_catch(
        _compose_all,
        ds,
        subject=EX.expense_api,
        predicate=DEPLOY.serviceOf,
        focus=EX.expense_api,
        path=DEPLOY.serviceOf,
        match="'SEMPKM_URL': " + f"{EX.expense_pkm} is a container of the arch:external system {EX.sempkm}",
        model_path=CHAPTER_10,
    )


def test_an_external_container_never_serves_routes(tmp_path: Path) -> None:
    # A UI event that submits to the external store's operation calls the third
    # party; it makes no container of the model, and no external one, serving.
    ui = """
    :ui a ifml:InteractionModel .
    :send a ifml:Event ; rdfs:label "send" .
"""
    text = (
        dataset(seams_graph=SEAMS + "\n    :send seam:submitsTo :pkm_command .\n").replace(
            "@prefix :", "@prefix ifml:   <https://w3id.org/seams/ifml#> .\n@prefix :"
        )
        + f"\n<urn:seams:graph:model:expense_ifml> {{{ui}}}\n"
    )
    model = load(tmp_path, text)
    pkm_command = model.operations.by_iri(EX.pkm_command)
    assert [str(e.iri) for e in pkm_command.submitted_by] == [str(EX.send)]
    assert list(model.architecture.serving_containers()) == []


BOUNDARY = (
    "A container of an external arch:System arch:dependsOn only containers of its own system and "
    "seam:consumes nothing: what the third party depends on is not the model's to say."
)

IMPACT = """
    :expense_db a arch:Container ; rdfs:label "Expense Store" ;
        deploy:storeKind deploy:PostgreSQL .
    :expense_system arch:contains :expense_db .
    :db01 a arch:DeploymentNode ; rdfs:label "db01" .
"""

IMPACT_SEAMS = """
    :expense_db seam:deployedTo :db01 .
    :expense_api seam:consumes :pkm_command .
    :ExpenseShape seam:storedIn :expense_pkm .
    :ApprovalShape seam:storedIn :expense_db .
"""


def test_an_external_container_depends_on_nothing_outside_its_system() -> None:
    trig = dataset(extra=IMPACT + "    :expense_triplestore arch:dependsOn :expense_db .\n")
    assert external_findings(trig) == {("expense_triplestore", "dependsOn", "ExternalBoundaryShape")}
    assert BOUNDARY in messages(trig)


def test_an_external_container_consumes_nothing() -> None:
    trig = dataset(seams_graph=SEAMS + "    :expense_pkm seam:consumes :object_changed .\n")
    assert external_findings(trig) == {("expense_pkm", "consumes", "ExternalBoundaryShape")}
    assert BOUNDARY in messages(trig)


def test_an_external_container_depends_on_its_own_system() -> None:
    # :expense_pkm arch:dependsOn :expense_triplestore inside :sempkm (EXTERNAL).
    assert external_findings(dataset(extra=IMPACT, seams_graph=SEAMS + IMPACT_SEAMS)) == set()


def test_impact_never_walks_into_an_external_system(tmp_path: Path) -> None:
    # The API consumes SemPKM's command and depends on its store, and a shape is stored
    # there, but none of them depends on :db01: the walk only reaches what the model runs.
    trig = dataset(extra=IMPACT, seams_graph=SEAMS + IMPACT_SEAMS)
    assert external_findings(trig) == set()
    rows = load(tmp_path, trig).question("impact-of-node", node=":db01")
    assert sorted(str(r["impacted"]) for r in rows) == sorted([str(EX.ApprovalShape), str(EX.expense_db)])


def test_chapter_10_db01_impact_lists_no_external_container() -> None:
    rows = seams.load(CHAPTER_10).question("impact-of-node", node=":db01")
    impacted = {str(r["impacted"]) for r in rows}
    assert str(EX.expense_db) in impacted
    assert not impacted & {str(EX.expense_pkm), str(EX.expense_triplestore), str(EX.ExpenseShape)}
