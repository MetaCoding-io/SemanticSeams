"""ModelGraph.store_plan with a deploy:SemPKM store (M024/S02, ADR-0025 sections 1, 2, 8, 11).

A runtime container resolves at most one relational store and at most one SemPKM
store. The SemPKM store needs a connecting binding (its base URL) and exactly one
secret binding that deploy:authenticatesTo it (its service token); the shapes
stored in it need a sh:targetClass, as do the sh:node shapes of their nested
fields; and a model naming it imports no gistCore but 14.0.0.
"""

from pathlib import Path

import pytest
import seams
from rdflib import OWL, URIRef
from rdflib.namespace import SH
from seams import (
    DEPLOY,
    SEAM,
    SEMPKM_GIST_VERSION,
    ModelGraph,
    ResolutionError,
    SemPKMPlan,
    StoreFinding,
    StorePlan,
)

T = "https://example.org/sempkm/"

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/sempkm/> .
"""

# A runtime container (:api executes :p and exposes :op, which writes
# :ExpenseShape) with the bindings each case gives it, a SemPKM store and the
# expense shape stored in it.
BASE = """
    :p a proc:Process ; rdfs:label "P" .
    :op a comm:Operation ; rdfs:label "Op" .
    :op seam:writes :ExpenseShape .
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        seam:storedIn :pkm .
    :pkm a arch:Container ; rdfs:label "PKM" ; deploy:storeKind deploy:SemPKM .
    :api a arch:Container ; rdfs:label "API" ;
        seam:executes :p ;
        seam:exposes :op ;
        deploy:configuration [ a deploy:Configuration {bindings} ] .
"""

URL = '[ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ]'
TOKEN = (
    '[ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm-token> ; '
    'deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ]'
)
FILE_TOKEN = '[ deploy:key "SEMPKM_TOKEN" ; deploy:secretFile "secrets/pkm-token" ; deploy:authenticatesTo :pkm ]'
PG_URL = '[ deploy:key "DATABASE_URL" ; deploy:value "postgresql://db/x" ; deploy:connectsTo :db ]'
PG = ':db a arch:Container ; rdfs:label "DB" ; deploy:storeKind deploy:PostgreSQL .'


def model(tmp_path: Path, extra: str = "", bindings: tuple[str, ...] = (URL, TOKEN), **load) -> ModelGraph:
    parts = "".join(f" ;\n            deploy:binding {b}" for b in bindings)
    path = tmp_path / "model.trig"
    path.write_text(f"{PREFIXES}\n:g {{\n{BASE.format(bindings=parts)}\n{extra}\n}}\n")
    return ModelGraph(path, **load)


def raises(tmp_path: Path, extra: str = "", bindings: tuple[str, ...] = (URL, TOKEN), **load) -> ResolutionError:
    with pytest.raises(ResolutionError) as info:
        model(tmp_path, extra, bindings, **load).store_plan()
    return info.value


SEMPKM = SemPKMPlan(URIRef(T + "pkm"), URIRef(T + "api"), "SEMPKM_URL", "SEMPKM_TOKEN", (URIRef(T + "ExpenseShape"),))


# ── fixtures that resolve ───────────────────────────────────────────────────


def test_exports():
    assert seams.SemPKMPlan is SemPKMPlan
    assert SEMPKM_GIST_VERSION == URIRef("https://w3id.org/semanticarts/ontology/gistCore14.0.0")


def test_sempkm_alone_keeps_process_state_in_embedded_sqlite(tmp_path: Path):
    plan = model(tmp_path).store_plan()
    assert plan == StorePlan(DEPLOY.SQLite, None, None, None, declared=False, sempkm=SEMPKM)


def test_sempkm_beside_postgres(tmp_path: Path):
    extra = f"{PG}\n:NoteShape a sh:NodeShape ; seam:storedIn :db .\n:op seam:writes :NoteShape ."
    plan = model(tmp_path, extra, (URL, TOKEN, PG_URL)).store_plan()
    assert plan == StorePlan(
        DEPLOY.PostgreSQL, URIRef(T + "db"), URIRef(T + "api"), "DATABASE_URL", declared=True, sempkm=SEMPKM
    )


def test_a_token_read_from_a_file_is_a_secret(tmp_path: Path):
    assert model(tmp_path, bindings=(URL, FILE_TOKEN)).store_plan().sempkm == SEMPKM


def test_unwritten_shapes_stored_in_sempkm_are_listed(tmp_path: Path):
    extra = ":NoteShape a sh:NodeShape ; sh:targetClass :Note ; seam:storedIn :pkm ."
    plan = model(tmp_path, extra).store_plan()
    assert plan.sempkm is not None
    assert plan.sempkm.shapes == (URIRef(T + "ExpenseShape"), URIRef(T + "NoteShape"))


def test_nested_shape_with_a_target_class_resolves(tmp_path: Path):
    plan = model(tmp_path, nested(":Magnitude")).store_plan()
    assert plan.sempkm == SEMPKM


def test_gist_14_import_resolves(tmp_path: Path):
    assert model(tmp_path, ontology("gistCore14.0.0")).store_plan().sempkm == SEMPKM


def test_relational_models_get_no_sempkm_plan():
    chat = Path(__file__).resolve().parent.parent / "examples/chat-app/chat-app.trig"
    assert ModelGraph(chat).store_plan().sempkm is None


def test_the_views_expose_the_token_binding(tmp_path: Path):
    m = model(tmp_path)
    api = m.architecture.containers().by_iri(":api")
    [token] = api.authenticating_bindings
    assert (token.key, token.authenticates_to, token.connects_to) == (
        "SEMPKM_TOKEN",
        m.architecture.containers().by_iri(":pkm"),
        None,
    )
    assert token.kinds == (DEPLOY.secretRef,)  # authenticatesTo is not a value source
    [url] = api.connecting_bindings
    assert url.authenticates_to is None


def test_health_reports_process_state_in_sqlite_beside_sempkm(tmp_path: Path):
    [info] = model(tmp_path).store_health()
    assert (info.severity, info.subject, info.predicate) == ("Info", None, None)
    assert "SEAMS_DB" in info.message and T + "pkm" in info.message


# ── the error contract (ADR-0025 section 11) ────────────────────────────────


def test_no_connecting_binding(tmp_path: Path):
    err = raises(tmp_path, bindings=(TOKEN,))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.connectsTo))
    assert "SemPKM" in err.detail


def test_no_connecting_binding_and_no_runtime_container_names_the_store(tmp_path: Path):
    path = tmp_path / "model.trig"
    path.write_text(
        f"{PREFIXES}\n:g {{\n"
        ":ExpenseShape a sh:NodeShape ; sh:targetClass :Expense ; seam:storedIn :pkm .\n"
        ":pkm a arch:Container ; deploy:storeKind deploy:SemPKM .\n}\n"
    )
    with pytest.raises(ResolutionError) as info:
        ModelGraph(path).store_plan()
    assert (info.value.subject, info.value.predicate) == (T + "pkm", str(DEPLOY.connectsTo))


def test_no_token_binding(tmp_path: Path):
    err = raises(tmp_path, bindings=(URL,))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.authenticatesTo))
    assert "found none" in err.detail


def test_two_token_bindings(tmp_path: Path):
    second = TOKEN.replace('"SEMPKM_TOKEN"', '"SEMPKM_TOKEN_2"')
    err = raises(tmp_path, bindings=(URL, TOKEN, second))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.authenticatesTo))
    assert "'SEMPKM_TOKEN', 'SEMPKM_TOKEN_2'" in err.detail


def test_a_token_that_is_not_a_secret(tmp_path: Path):
    plain = '[ deploy:key "SEMPKM_TOKEN" ; deploy:value "t0ken" ; deploy:authenticatesTo :pkm ]'
    err = raises(tmp_path, bindings=(URL, plain))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.authenticatesTo))
    assert "secret" in err.detail
    assert "t0ken" not in str(err)  # the value is never echoed


def test_a_token_for_another_store_does_not_count(tmp_path: Path):
    extra = ":other a arch:Container ; deploy:storeKind deploy:SemPKM ."
    elsewhere = TOKEN.replace("deploy:authenticatesTo :pkm", "deploy:authenticatesTo :other")
    err = raises(tmp_path, extra, (URL, elsewhere))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.authenticatesTo))


def test_two_sempkm_stores_for_one_container(tmp_path: Path):
    extra = ":other a arch:Container ; deploy:storeKind deploy:SemPKM ."
    second = URL.replace('"SEMPKM_URL"', '"OTHER_URL"').replace(":pkm", ":other")
    err = raises(tmp_path, extra, (URL, TOKEN, second))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.connectsTo))
    assert "several SemPKM stores" in err.detail


def test_two_relational_stores_for_one_container(tmp_path: Path):
    extra = f"{PG}\n:db2 a arch:Container ; deploy:storeKind deploy:PostgreSQL ."
    second = PG_URL.replace('"DATABASE_URL"', '"DATABASE_URL_2"').replace(":db ", ":db2 ")
    err = raises(tmp_path, extra, (URL, TOKEN, PG_URL, second))
    assert (err.subject, err.predicate) == (T + "api", str(DEPLOY.connectsTo))
    assert "several relational stores" in err.detail


def test_two_containers_connecting_to_different_sempkm_stores(tmp_path: Path):
    extra = f"""
    :other a arch:Container ; deploy:storeKind deploy:SemPKM .
    :q a proc:Process ; rdfs:label "Q" .
    :worker a arch:Container ; rdfs:label "Worker" ; seam:executes :q ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding {URL.replace(":pkm", ":other")} ] .
    """
    err = raises(tmp_path, extra)
    assert (err.subject, err.predicate) == (T + "worker", str(DEPLOY.connectsTo))
    assert "one store per model" in err.detail


def test_written_shape_stored_in_neither_store(tmp_path: Path):
    extra = f"{PG}\n:NoteShape a sh:NodeShape .\n:op seam:writes :NoteShape ."
    err = raises(tmp_path, extra, (URL, TOKEN, PG_URL))
    assert (err.subject, err.predicate) == (T + "NoteShape", str(SEAM.storedIn))
    assert "one of" in err.detail


def test_stored_shape_without_a_target_class(tmp_path: Path):
    extra = ":NoteShape a sh:NodeShape ; seam:storedIn :pkm ."
    err = raises(tmp_path, extra)
    assert (err.subject, err.predicate) == (T + "NoteShape", str(SH.targetClass))
    assert T + "pkm" in err.detail


def test_nested_shape_without_a_target_class(tmp_path: Path):
    err = raises(tmp_path, nested(None))
    assert (err.subject, err.predicate) == (T + "MagnitudeShape", str(SH.targetClass))
    assert "amount" in err.detail


def test_another_gist_version(tmp_path: Path):
    err = raises(tmp_path, ontology("gistCore13.0.0"), check_imports=False)
    assert (err.subject, err.predicate) == (T + "expense_ontology", str(OWL.imports))
    assert "gistCore13.0.0" in err.detail and str(SEMPKM_GIST_VERSION) in err.detail


def test_another_gist_version_is_fine_without_sempkm(tmp_path: Path):
    # The gist check is SemPKM's (section 8): a relational model is not asked.
    path = tmp_path / "model.trig"
    path.write_text(f"{PREFIXES}\n:g {{\n{ontology('gistCore13.0.0')}\n}}\n")
    assert ModelGraph(path, check_imports=False).store_plan().sempkm is None


def test_health_reports_a_violation_instead_of_raising(tmp_path: Path):
    findings = model(tmp_path, bindings=(URL,)).store_health()
    assert findings == [
        StoreFinding("Violation", URIRef(T + "api"), DEPLOY.authenticatesTo, findings[0].message),
    ]


# ── fixture pieces ──────────────────────────────────────────────────────────


def nested(target: str | None) -> str:
    """An `amount` field on :ExpenseShape flattened through :MagnitudeShape (ADR-0023 section 4)."""
    target_class = f"sh:targetClass {target} ;" if target else ""
    return f"""
    :MagnitudeShape a sh:NodeShape ; {target_class}
        sh:property [ sh:path :numericValue ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ,
                    [ sh:path :unit ; sh:hasValue :USD ] .
    :ExpenseShape sh:property [ sh:path :amount ; sh:name "amount" ; sh:node :MagnitudeShape ; sh:maxCount 1 ] .
    """


def ontology(version: str) -> str:
    return f"""
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        owl:versionIRI <https://example.org/sempkm/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/{version}> .
    """
