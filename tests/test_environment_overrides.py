"""Environments and overrides (M016/S02 T01, ADR-0015).

ontology/deploy.ttl adds deploy:Override, deploy:override, deploy:environment,
deploy:Build, deploy:build, deploy:context, deploy:dockerfile,
deploy:secretFile and deploy:proxies; ontology/shapes/seam-shapes.ttl
constrains them; ``Container.for_environment`` applies the override rule; and
``ModelGraph.replica_health`` reports the replica cap (backlog A10).

Fixtures are the chat app's shared facts (its own overrides and its
:development environment removed) plus inline TriG in its architecture graph,
so the override rule is tested against the shared facts the real model states.
"""

from pathlib import Path

import pyshacl
import pytest
import rdflib
import seams
from rdflib import RDF, Dataset, URIRef
from seams import ARCH, DEPLOY, ModelGraph, ResolutionError
from seams.views import Artifact, Build, Deployment, Override

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "examples/chat-app/chat-app.trig"
ONTOLOGY_FILES = sorted((ROOT / "ontology").glob("*.ttl"))
SHAPES_FILE = ROOT / "ontology" / "shapes" / "seam-shapes.ttl"
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
SEAMSH = rdflib.Namespace("https://w3id.org/seams/shapes#")
C = rdflib.Namespace("https://example.org/chat/")

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/chat/> .
"""

DEVELOPMENT = """
    :development a arch:Environment ; rdfs:label "Development" ;
        seam:inModel :chat_architecture .
"""

# ADR-0015's development override of :chat_api: a build artifact, the
# connection string from a file (same key, same store), a static user and
# seed data, and one replica.
DEV_OVERRIDE = """
    :chat_api deploy:override [ a deploy:Override ;
        deploy:environment :development ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "seams/chat-api" ;
                          deploy:version "local" ;
                          deploy:build [ a deploy:Build ;
                                         deploy:context "../.." ;
                                         deploy:dockerfile "docker/runtime.Dockerfile" ] ] ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "DB_URL" ;
                             deploy:secretFile "../../docker/local-secrets/db_url" ;
                             deploy:connectsTo :message_db ] ;
            deploy:binding [ deploy:key "SEAMS_DEV_USER" ; deploy:value "builder" ] ;
            deploy:binding [ deploy:key "SEAMS_SEED" ; deploy:value "/app/seed.json" ] ] ;
        deploy:replicas 1 ] .
"""


def _drop(ds: Dataset, node) -> None:
    """Remove every quad with subject ``node`` and, recursively, its blank-node objects."""
    for _, _, o, _ in list(ds.quads((node, None, None, None))):
        if isinstance(o, rdflib.BNode):
            _drop(ds, o)
    ds.remove((node, None, None, None))


def _dataset(*extra: str) -> Dataset:
    """The chat app's shared facts with ``extra`` TriG statements added to its
    architecture graph: the model's own deploy:overrides and :development are
    removed, so each test states the environment facts it needs."""
    ds = Dataset(default_union=True)
    ds.parse(CHAT, format="trig")
    for _, _, node, _ in list(ds.quads((None, DEPLOY.override, None, None))):
        _drop(ds, node)
    ds.remove((None, DEPLOY.override, None, None))
    _drop(ds, C.development)
    if extra:
        body = "\n".join(extra)
        ds.parse(data=f"{PREFIXES}\n<urn:seams:graph:model:chat_architecture> {{\n{body}\n}}\n", format="trig")
    return ds


def model(*extra: str) -> ModelGraph:
    return ModelGraph(CHAT, _dataset(*extra))


def env(m: ModelGraph, name: str):
    return m.architecture.environments().by_iri(C[name])


def container(m: ModelGraph, name: str):
    return m.architecture.containers().by_iri(C[name])


def keys(deployment: Deployment) -> list[str]:
    return [b.key for b in deployment.bindings]


def raises(m: ModelGraph, name: str = "chat_api") -> ResolutionError:
    with pytest.raises(ResolutionError) as info:
        container(m, name).for_environment(env(m, "production"))
    return info.value


def violating_shapes(*extra: str) -> set[URIRef]:
    """The named shapes (or the named parent of a property shape) that report on the chat app plus ``extra``."""
    union = rdflib.Graph()
    for p in ONTOLOGY_FILES:
        union.parse(p, format="turtle")
    for s, p, o, _ in _dataset(*extra).quads((None, None, None, None)):
        union.add((s, p, o))
    shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    conforms, results, _ = pyshacl.validate(union, shacl_graph=shapes, inference="none")
    if conforms:
        return set()
    named = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        source = results.value(result, SH.sourceShape)
        parent = shapes.value(predicate=SH.property, object=source)
        named.add(parent if parent is not None else source)
    return named


# ── vocabulary ──────────────────────────────────────────────────────────────


def test_new_terms_are_declared():
    g = rdflib.Graph().parse(ROOT / "ontology/deploy.ttl", format="turtle")
    for cls in (DEPLOY.Override, DEPLOY.Build):
        assert (cls, RDF.type, rdflib.RDFS.Class) in g
    for prop in (
        DEPLOY.override,
        DEPLOY.environment,
        DEPLOY.build,
        DEPLOY.context,
        DEPLOY.dockerfile,
        DEPLOY.secretFile,
        DEPLOY.proxies,
    ):
        assert (prop, RDF.type, rdflib.RDF.Property) in g, prop
    assert g.value(DEPLOY.environment, rdflib.RDFS.range) == ARCH.Environment


def test_overridable_predicates_have_no_rdfs_domain():
    # A container and an override both state them; SHACL states the allowed subjects.
    g = rdflib.Graph().parse(ROOT / "ontology/deploy.ttl", format="turtle")
    for prop in (DEPLOY.artifact, DEPLOY.configuration, DEPLOY.replicas):
        assert g.value(prop, rdflib.RDFS.domain) is None, prop


# ── the override rule ───────────────────────────────────────────────────────


def test_no_override_falls_back_to_every_shared_fact():
    m = model(DEVELOPMENT, DEV_OVERRIDE)
    api = container(m, "chat_api")
    prod = api.for_environment(env(m, "production"))
    assert prod.artifact == api.artifact == Artifact("ghcr.io/example/chat-api", "0.3.1")
    assert prod.bindings == api.bindings
    assert prod.replicas == api.replicas == 3


def test_a_container_without_overrides_is_shared_in_every_environment():
    m = model(DEVELOPMENT, DEV_OVERRIDE)
    gateway = container(m, "llm_gateway")
    assert gateway.overrides == ()
    dev = gateway.for_environment(env(m, "development"))
    assert (dev.artifact, dev.bindings, dev.replicas) == (gateway.artifact, gateway.bindings, gateway.replicas)


def test_override_artifact_and_replicas_replace_whole():
    m = model(DEVELOPMENT, DEV_OVERRIDE)
    dev = container(m, "chat_api").for_environment(env(m, "development"))
    assert dev.artifact == Artifact("seams/chat-api", "local", Build("../..", "docker/runtime.Dockerfile"))
    assert dev.replicas == 1


def test_override_bindings_merge_by_key():
    m = model(DEVELOPMENT, DEV_OVERRIDE)
    dev = container(m, "chat_api").for_environment(env(m, "development"))
    # DB_URL replaced, SEAMS_DEV_USER and SEAMS_SEED added, the rest kept.
    assert keys(dev) == ["DB_URL", "LLM_GATEWAY_URL", "SEAMS_DEV_USER", "SEAMS_SEED"]
    db = next(b for b in dev.bindings if b.key == "DB_URL")
    assert (db.kinds, db.secret_file, db.secret_ref, db.secret_name) == (
        (DEPLOY.secretFile,),
        "../../docker/local-secrets/db_url",
        None,
        None,
    )
    assert db.connects_to == container(m, "message_db")
    gateway = next(b for b in dev.bindings if b.key == "LLM_GATEWAY_URL")
    assert gateway.service_of == container(m, "llm_gateway")


def test_an_override_silent_on_a_predicate_keeps_the_shared_fact():
    m = model(
        DEVELOPMENT,
        ":chat_api deploy:override [ a deploy:Override ; deploy:environment :development ; deploy:replicas 1 ] .",
    )
    api = container(m, "chat_api")
    dev = api.for_environment(env(m, "development"))
    assert (dev.artifact, dev.bindings, dev.replicas) == (api.artifact, api.bindings, 1)
    [override] = api.overrides
    assert (override.artifact, override.bindings, override.replicas) == (None, None, 1)


def test_build_without_a_dockerfile():
    m = model(
        DEVELOPMENT,
        """:chat_api deploy:override [ a deploy:Override ; deploy:environment :development ;
            deploy:artifact [ deploy:reference "seams/chat-api" ; deploy:version "local" ;
                              deploy:build [ deploy:context "." ] ] ] .""",
    )
    dev = container(m, "chat_api").for_environment(env(m, "development"))
    assert dev.artifact is not None and dev.artifact.build == Build(".", None)


def test_overrides_and_bindings_come_back_in_a_deterministic_order():
    staging = """
        :staging a arch:Environment ; rdfs:label "Staging" ; seam:inModel :chat_architecture .
        :chat_api deploy:override [ a deploy:Override ; deploy:environment :staging ; deploy:replicas 2 ] .
    """
    orders = set()
    for extra in ((staging, DEVELOPMENT, DEV_OVERRIDE), (DEV_OVERRIDE, DEVELOPMENT, staging)):
        m = model(*extra)
        api = container(m, "chat_api")
        overrides = api.overrides
        assert all(isinstance(o, Override) for o in overrides)
        orders.add(
            (
                tuple(str(o.environment.iri) for o in overrides),
                tuple(keys(api.for_environment(env(m, "development")))),
            )
        )
    assert orders == {
        (
            (str(C.development), str(C.staging)),
            ("DB_URL", "LLM_GATEWAY_URL", "SEAMS_DEV_USER", "SEAMS_SEED"),
        )
    }


def test_proxies_names_the_proxied_container():
    m = model(":chat_ui deploy:proxies :chat_api .")
    assert container(m, "chat_ui").proxies == container(m, "chat_api")
    assert container(m, "chat_api").proxies is None


def test_the_new_types_are_exported():
    assert seams.Build is Build and seams.Override is Override and seams.Deployment is Deployment


# ── violations: the view raises, the shapes report ──────────────────────────


def test_the_chat_app_with_a_development_override_conforms():
    assert violating_shapes(DEVELOPMENT, DEV_OVERRIDE) == set()


OTHER_PREDICATE = (
    ":chat_api deploy:override [ a deploy:Override ; deploy:environment :production ;"
    " deploy:port [ a deploy:Port ; deploy:containerPort 9000 ] ] ."
)


def test_an_override_with_another_predicate_names_it():
    err = raises(model(OTHER_PREDICATE))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.port))
    assert SEAMSH.OverrideShape in violating_shapes(OTHER_PREDICATE)


TWO_FOR_ONE_ENVIRONMENT = """
    :chat_api deploy:override [ a deploy:Override ; deploy:environment :production ; deploy:replicas 1 ] ,
                              [ a deploy:Override ; deploy:environment :production ; deploy:replicas 2 ] .
"""


def test_two_overrides_for_one_environment():
    err = raises(model(TWO_FOR_ONE_ENVIRONMENT))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.override))
    assert SEAMSH.OverridePerEnvironmentShape in violating_shapes(TWO_FOR_ONE_ENVIRONMENT)


NOT_AN_ENVIRONMENT = ":chat_api deploy:override [ a deploy:Override ; deploy:environment :web01 ; deploy:replicas 1 ] ."


def test_an_override_environment_must_be_an_arch_environment():
    err = raises(model(NOT_AN_ENVIRONMENT))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.environment))
    assert SEAMSH.OverrideShape in violating_shapes(NOT_AN_ENVIRONMENT)


NO_ENVIRONMENT = ":chat_api deploy:override [ a deploy:Override ; deploy:replicas 1 ] ."


def test_an_override_names_an_environment():
    err = raises(model(NO_ENVIRONMENT))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.environment))
    assert SEAMSH.OverrideShape in violating_shapes(NO_ENVIRONMENT)


UNTYPED = ":chat_api deploy:override [ deploy:environment :production ; deploy:replicas 1 ] ."


def test_an_override_is_a_deploy_override():
    err = raises(model(UNTYPED))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(RDF.type))
    assert SEAMSH.OverrideShape in violating_shapes(UNTYPED)


def _store_override(binding: str) -> str:
    return f"""
        :other_db a arch:Container ; rdfs:label "Other" ; deploy:storeKind deploy:PostgreSQL ;
            seam:inModel :chat_architecture .
        :chat_api deploy:override [ a deploy:Override ; deploy:environment :production ;
            deploy:configuration [ a deploy:Configuration ; deploy:binding [ {binding} ] ] ] .
    """


ELSEWHERE = _store_override('deploy:key "DB_URL" ; deploy:secretFile "db_url" ; deploy:connectsTo :other_db')
DROPPED = _store_override('deploy:key "DB_URL" ; deploy:secretFile "db_url"')
ADDED = _store_override('deploy:key "LLM_API_KEY" ; deploy:secretFile "llm" ; deploy:connectsTo :message_db')


@pytest.mark.parametrize("extra", [ELSEWHERE, DROPPED, ADDED], ids=["elsewhere", "dropped", "added"])
def test_an_override_binding_cannot_change_the_store(extra):
    err = raises(model(extra))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.connectsTo))
    assert "cannot change per environment" in str(err)
    assert SEAMSH.OverrideStoreShape in violating_shapes(extra)


def test_an_override_binding_that_keeps_the_store_is_fine():
    keeps = _store_override('deploy:key "DB_URL" ; deploy:secretFile "db_url" ; deploy:connectsTo :message_db')
    m = model(keeps)
    prod = container(m, "chat_api").for_environment(env(m, "production"))
    assert next(b for b in prod.bindings if b.key == "DB_URL").secret_file == "db_url"
    assert violating_shapes(keeps) == set()


def test_an_override_binding_a_key_twice():
    twice = """:chat_api deploy:override [ a deploy:Override ; deploy:environment :production ;
        deploy:configuration [ deploy:binding [ deploy:key "X" ; deploy:value "1" ] ,
                                              [ deploy:key "X" ; deploy:value "2" ] ] ] ."""
    err = raises(model(twice))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.key))


SECRET_FILE_AND_REF = """:llm_gateway deploy:configuration [ deploy:binding [ deploy:key "K" ;
    deploy:secretFile "k" ; deploy:secretRef <https://secrets.example.org/k> ] ] ."""


def test_a_binding_has_a_secret_file_or_a_secret_ref_not_both():
    assert SEAMSH.BindingShape in violating_shapes(SECRET_FILE_AND_REF)
    m = model(SECRET_FILE_AND_REF)
    [binding] = [b for b in container(m, "llm_gateway").bindings if b.key == "K"]
    assert binding.kinds == (DEPLOY.secretRef, DEPLOY.secretFile)  # a generator rejects two kinds


def test_only_a_container_or_an_override_states_replicas():
    extra = ":web01 deploy:replicas 2 ."
    assert SEAMSH.OverridableSubjectShape in violating_shapes(extra)


def test_proxies_must_point_at_a_container():
    extra = ":chat_ui deploy:proxies :web01 ."
    assert SEAMSH.ProxiesShape in violating_shapes(extra)
    with pytest.raises(ResolutionError) as info:
        _ = container(model(extra), "chat_ui").proxies
    assert (info.value.subject, info.value.predicate) == (str(C.chat_ui), str(DEPLOY.proxies))


def test_a_build_needs_a_context():
    extra = """:chat_api deploy:override [ a deploy:Override ; deploy:environment :production ;
        deploy:artifact [ deploy:reference "r" ; deploy:version "v" ;
                          deploy:build [ deploy:dockerfile "Dockerfile" ] ] ] ."""
    assert SEAMSH.BuildShape in violating_shapes(extra)
    err = raises(model(extra))
    assert (err.subject, err.predicate) == (str(C.chat_api), str(DEPLOY.context))


# ── model health: the replica cap (A10) ─────────────────────────────────────


def test_chat_app_warns_that_chat_api_replicas_are_capped():
    [finding] = ModelGraph(CHAT).replica_health()
    assert (finding.severity, finding.subject, finding.predicate) == ("Warning", C.chat_api, DEPLOY.replicas)
    assert f"3 in {C.production}" in finding.message and "A10" in finding.message


def test_the_warning_names_only_the_environments_above_one():
    [finding] = model(DEVELOPMENT, DEV_OVERRIDE).replica_health()
    assert f"3 in {C.production}" in finding.message
    assert str(C.development) not in finding.message


def test_no_warning_when_every_environment_runs_one_replica():
    m = model(":chat_api deploy:override [ a deploy:Override ; deploy:environment :production ; deploy:replicas 1 ] .")
    assert m.replica_health() == []


def test_containers_without_process_state_are_not_capped():
    assert model(":llm_gateway deploy:replicas 4 .").replica_health()[0].subject == C.chat_api
    assert len(model(":llm_gateway deploy:replicas 4 .").replica_health()) == 1


def test_a_model_without_environments_uses_the_shared_count():
    ds = _dataset()
    ds.remove((C.production, None, None, None))
    [finding] = ModelGraph(CHAT, ds).replica_health()
    assert finding.subject == C.chat_api and "3 in " in finding.message


def test_an_unresolvable_override_is_a_violation_not_an_exception():
    [finding] = model(TWO_FOR_ONE_ENVIRONMENT).replica_health()
    assert (finding.severity, finding.subject, finding.predicate) == ("Violation", C.chat_api, DEPLOY.override)
