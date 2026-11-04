"""Compose adds SemPKM's services because the model names them (M024/S02, ADR-0025 section 10).

A deploy:SemPKM store that a contained container reaches through a
deploy:connectsTo or deploy:authenticatesTo binding, and the containers that
store arch:dependsOn, become compose services even when the arch:System does
not arch:contains them. Each takes the image, ports, volumes and healthcheck
its own facts give it. The URL binding renders as an environment entry and
the token binding as a secret, as for PostgreSQL. Nothing about SemPKM is
hard-coded: a missing fact raises GeneratorError naming it.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams import DEPLOY, ModelGraph  # noqa: E402

from seams_gen import GeneratorError, extract_compose, generate_compose_environments  # noqa: E402

T = "https://example.org/pkmcompose/"

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/pkmcompose/> .
"""

# The system contains only :api. Its bindings reach :pkm, a SemPKM store that
# arch:dependsOn :triplestore and :frontend; none of the three is contained.
API = """
    :system a arch:System ; rdfs:label "Pkm Compose" ; arch:contains :api {contains} .
    :api a arch:Container ; rdfs:label "API" ;
        deploy:artifact [ a deploy:Artifact ; deploy:reference "example/api" ; deploy:version "1.0" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ; deploy:publishedPort 8080 ] ;
        deploy:dependsOn :pkm ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8001" ; deploy:connectsTo :pkm ] ;
            deploy:binding [ deploy:key "SEMPKM_TOKEN" ;
                             deploy:secretRef <https://secrets.example.org/pkm-token> ;
                             deploy:secretName "pkm-prod-token" ;
                             deploy:authenticatesTo :pkm ] ] .
    :development a arch:Environment ; rdfs:label "Development" .
    :production a arch:Environment ; rdfs:label "Production" .
"""

PKM = """
    :pkm a arch:Container ; rdfs:label "PKM" ;
        deploy:storeKind deploy:SemPKM ;
        arch:dependsOn :triplestore , :frontend ;
        deploy:dependsOn :triplestore ;
        {pkm_artifact}
        deploy:port [ a deploy:Port ; deploy:containerPort 8001 ] ;
        deploy:volume [ a deploy:Volume ; deploy:volumeName "pkm_data" ; deploy:mountPath "/app/data" ] ;
        deploy:healthcheck [ a deploy:Healthcheck ; deploy:probe "curl -f http://127.0.0.1:8001/api/health" ;
                             deploy:interval "10s" ] .
"""
PKM_ARTIFACT = 'deploy:artifact [ a deploy:Artifact ; deploy:reference "example/sempkm-api" ; deploy:version "2.1" ] ;'

TRIPLESTORE = """
    :triplestore a arch:Container ; rdfs:label "Triplestore" ;
        deploy:artifact [ a deploy:Artifact ; deploy:reference "example/rdf4j" ; deploy:version "5.0" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8080 ] ;
        deploy:volume [ a deploy:Volume ; deploy:volumeName "triplestore_data" ; deploy:mountPath "/var/rdf4j" ] ;
        deploy:healthcheck [ a deploy:Healthcheck ; deploy:probe "wget -q -O /dev/null http://127.0.0.1:8080/" ;
                             deploy:interval "5s" ] .
"""
FRONTEND = """
    :frontend a arch:Container ; rdfs:label "Frontend" ;
        deploy:artifact [ a deploy:Artifact ; deploy:reference "example/sempkm-web" ; deploy:version "2.1" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 3000 ; deploy:publishedPort 3000 ] .
"""


def _trig(tmp_path: Path, *, contains: str = "", pkm_artifact: str = PKM_ARTIFACT, extra: str = "") -> Path:
    body = API.format(contains=contains) + PKM.format(pkm_artifact=pkm_artifact) + TRIPLESTORE + FRONTEND + extra
    path = tmp_path / "model.trig"
    path.write_text(f"{PREFIXES}\n:g {{\n{body}\n}}\n", encoding="utf-8")
    return path


def _docs(trig: Path) -> dict[str, dict]:
    files = generate_compose_environments(trig, base_dir=trig.parent)
    return {name: yaml.safe_load(text) for name, text in files.items()}


def _raises(trig: Path) -> GeneratorError:
    with pytest.raises(GeneratorError) as err:
        generate_compose_environments(trig, base_dir=trig.parent)
    return err.value


# ── the services ────────────────────────────────────────────────────────────


def test_the_store_and_what_it_depends_on_become_services(tmp_path):
    doc = _docs(_trig(tmp_path))["compose.production.yaml"]
    services = doc["services"]
    assert list(services) == ["api", "frontend", "pkm", "triplestore"]
    pkm = services["pkm"]
    assert pkm["image"] == "example/sempkm-api:2.1"
    assert pkm["expose"] == ["8001"]
    assert pkm["volumes"] == ["pkm_data:/app/data"]
    assert pkm["healthcheck"]["test"] == ["CMD-SHELL", "curl -f http://127.0.0.1:8001/api/health"]
    assert pkm["healthcheck"]["interval"] == "10s"
    assert pkm["depends_on"] == {"triplestore": {"condition": "service_healthy"}}
    triplestore = services["triplestore"]
    assert triplestore["image"] == "example/rdf4j:5.0"
    assert triplestore["volumes"] == ["triplestore_data:/var/rdf4j"]
    assert "healthcheck" in triplestore
    frontend = services["frontend"]
    assert frontend["image"] == "example/sempkm-web:2.1"
    assert frontend["ports"] == ["3000:3000"]
    assert "healthcheck" not in frontend  # the model gives it none, so none is invented
    assert sorted(doc["volumes"]) == ["pkm_data", "triplestore_data"]
    assert services["api"]["depends_on"] == {"pkm": {"condition": "service_healthy"}}


def test_the_url_is_an_environment_entry_and_the_token_a_secret(tmp_path):
    docs = _docs(_trig(tmp_path))
    prod = docs["compose.production.yaml"]
    api = prod["services"]["api"]
    assert api["environment"] == {"SEMPKM_TOKEN_FILE": "/run/secrets/sempkm_token", "SEMPKM_URL": "http://pkm:8001"}
    assert api["secrets"] == ["sempkm_token"]
    assert prod["secrets"] == {"sempkm_token": {"external": True, "name": "pkm-prod-token"}}
    dev_api = docs["compose.development.yaml"]["services"]["api"]
    assert dev_api["environment"]["SEMPKM_URL"] == "${SEMPKM_URL:-http://pkm:8001}"
    # the token's value never appears: only the secret's name and mount path
    for text in generate_compose_environments(_trig(tmp_path), base_dir=tmp_path).values():
        assert "SEMPKM_TOKEN:" not in text


def test_a_contained_store_is_not_duplicated(tmp_path):
    services = _docs(_trig(tmp_path, contains=", :pkm , :triplestore"))["compose.production.yaml"]["services"]
    assert list(services) == ["api", "frontend", "pkm", "triplestore"]


def test_every_fact_comes_from_the_model(tmp_path):
    """Renamed images, ports and volumes flow through: nothing is hard-coded."""
    trig = _trig(tmp_path)
    text = trig.read_text(encoding="utf-8")
    for old, new in (
        ("example/sempkm-api", "registry.example.org/other-pkm"),
        ("deploy:containerPort 8001", "deploy:containerPort 9001"),
        ('"pkm_data"', '"other_data"'),
    ):
        text = text.replace(old, new)
    trig.write_text(text, encoding="utf-8")
    pkm = _docs(trig)["compose.production.yaml"]["services"]["pkm"]
    assert pkm["image"] == "registry.example.org/other-pkm:2.1"
    assert pkm["expose"] == ["9001"]
    assert pkm["volumes"] == ["other_data:/app/data"]


def test_trace_origins_name_what_brought_each_service_in(tmp_path):
    model = ModelGraph.load(_trig(tmp_path))
    services = {s.name: s for s in extract_compose(model, tmp_path, "production").services}
    assert services["pkm"].origins == (T + "api",)
    assert services["triplestore"].origins == (T + "pkm",)
    assert services["frontend"].origins == (T + "pkm",)
    assert services["api"].origins == (T + "system",)


def test_generation_is_deterministic(tmp_path):
    trig = _trig(tmp_path)
    assert generate_compose_environments(trig, base_dir=tmp_path) == generate_compose_environments(
        trig, base_dir=tmp_path
    )


def test_depends_on_of_a_relational_store_brings_nothing_in(tmp_path):
    """Only a deploy:SemPKM store pulls in what it arch:dependsOn."""
    trig = _trig(tmp_path)
    text = trig.read_text(encoding="utf-8").replace("deploy:SemPKM", "deploy:PostgreSQL")
    text = text.replace("deploy:dependsOn :pkm ;", "")
    trig.write_text(text, encoding="utf-8")
    assert list(_docs(trig)["compose.production.yaml"]["services"]) == ["api"]


# ── missing facts ───────────────────────────────────────────────────────────


def test_a_store_without_an_artifact_names_the_store(tmp_path):
    err = _raises(_trig(tmp_path, pkm_artifact=""))
    assert (err.subject, err.predicate) == (T + "pkm", str(DEPLOY.artifact))


def test_a_dependency_without_an_artifact_names_the_dependency(tmp_path):
    trig = _trig(tmp_path)
    text = trig.read_text(encoding="utf-8")
    text = text.replace(
        'deploy:artifact [ a deploy:Artifact ; deploy:reference "example/rdf4j" ; deploy:version "5.0" ] ;', ""
    )
    trig.write_text(text, encoding="utf-8")
    err = _raises(trig)
    assert (err.subject, err.predicate) == (T + "triplestore", str(DEPLOY.artifact))


def test_start_order_on_a_container_nothing_brings_in_raises(tmp_path):
    extra = ':elsewhere a arch:Container ; rdfs:label "Elsewhere" .\n:pkm deploy:dependsOn :elsewhere .'
    err = _raises(_trig(tmp_path, extra=extra))
    assert (err.subject, err.predicate) == (T + "pkm", str(DEPLOY.dependsOn))
    assert T + "elsewhere" in err.detail


def test_a_service_url_binding_needs_the_stores_single_port(tmp_path):
    trig = _trig(tmp_path)
    text = trig.read_text(encoding="utf-8").replace(
        'deploy:value "http://pkm:8001" ; deploy:connectsTo :pkm',
        "deploy:serviceOf :pkm ; deploy:connectsTo :pkm",
    )
    text = text.replace("deploy:port [ a deploy:Port ; deploy:containerPort 8001 ] ;", "")
    trig.write_text(text, encoding="utf-8")
    err = _raises(trig)
    assert (err.subject, err.predicate) == (T + "pkm", str(DEPLOY.port))


def test_a_service_url_binding_reaches_the_store_by_its_model_port(tmp_path):
    trig = _trig(tmp_path)
    text = trig.read_text(encoding="utf-8").replace(
        'deploy:value "http://pkm:8001" ; deploy:connectsTo :pkm',
        "deploy:serviceOf :pkm ; deploy:connectsTo :pkm",
    )
    trig.write_text(text, encoding="utf-8")
    api = _docs(trig)["compose.production.yaml"]["services"]["api"]
    assert api["environment"]["SEMPKM_URL"] == "http://pkm:8001"
