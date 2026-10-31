"""The expense tutorial's chapter 8 and 9 compose files are current and need no
hand-written override (ADR-0015, M016/S02).

Each chapter's seams.toml names the compose generator, so
``seams generate --project examples/expenses/chapter-0N`` writes one
compose.<environment>.yaml per arch:Environment in the chapter's model:
compose.development.yaml, which tests/test_expense_e2e.py brings up, and
compose.production.yaml. This checks the committed files equal a fresh run, so
a model edit that changes the model hash (or a deploy fact) cannot leave a
stale compose file behind. It also checks that the development file carries
every setting the deleted compose.override.yaml used to merge in (a local
build, a file secret the dev store's password matches, healthy start order,
the Caddy proxy) and that the production file stays production-shaped. The
files are read as YAML; the ``${KEY:-default}`` values are resolved as compose
would with no host variables set.
"""

import difflib
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import generate_compose_environments  # noqa: E402
from seams_runtime import ModelGraph  # noqa: E402

CHAPTERS = ("chapter-08", "chapter-09")
FILES = ("compose.development.yaml", "compose.production.yaml")
PAYLOADS = ("expenses.trig", "approval.bpmn", "approval.dmn", "payout.bpmn", "payout.dmn")
DEFAULT = re.compile(r"^\$\{[A-Z_]+:-(.*)\}$")


def app(chapter: str) -> Path:
    return ROOT / "examples" / "expenses" / chapter


def load(chapter: str, file: str) -> dict:
    return yaml.safe_load((app(chapter) / file).read_text(encoding="utf-8"))


def default(value: str) -> str:
    """The value compose uses for ``${KEY:-default}`` when KEY is unset."""
    match = DEFAULT.match(value)
    return match.group(1) if match else value


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_chapter_holds_one_generated_file_per_environment(chapter):
    directory = app(chapter)
    generated = generate_compose_environments(directory / "expenses.trig", base_dir=directory)
    assert sorted(generated) == sorted(FILES)
    command = f"seams generate --project examples/expenses/{chapter}"
    for name, content in generated.items():
        committed = (directory / name).read_text(encoding="utf-8")
        diff = "".join(difflib.unified_diff(committed.splitlines(True), content.splitlines(True), "committed", name))
        assert committed == content, f"{chapter}/{name} is stale; rerun `{command}`:\n{diff}"
    assert sorted(p.name for p in directory.glob("compose*.yaml")) == sorted(FILES)
    assert not (directory / "compose.override.yaml").exists()
    assert not (directory / "compose.yaml").exists()


@pytest.mark.parametrize("chapter", CHAPTERS)
@pytest.mark.parametrize("file", FILES)
def test_header_names_the_environment_and_the_model_hash(chapter, file):
    head = (app(chapter) / file).read_text(encoding="utf-8").splitlines()[:3]
    env = file.split(".")[1]
    assert head[1] == f"# model-hash: {ModelGraph.load(app(chapter) / 'expenses.trig').hash}"
    assert head[2] == f"# environment: https://example.org/expenses/{env}"


@pytest.mark.parametrize("chapter", CHAPTERS)
@pytest.mark.parametrize("file", FILES)
def test_compose_file_mounts_the_model_and_its_payloads(chapter, file):
    compose = load(chapter, file)
    # the project name is the arch:System's local name, so the stack never collides with the chat app's
    assert compose["name"] == "expense_system"
    services = compose["services"]
    assert set(services) == {"employee_portal", "expense_api", "expense_db"}
    api = services["expense_api"]
    names = sorted(PAYLOADS[1:] + (("handlers",) if chapter == "chapter-09" else ()))
    assert api["volumes"] == [f"./{name}:/model/{name}:ro" for name in ("expenses.trig", *names)]
    assert api["environment"]["SEAMS_MODEL"] == "/model/expenses.trig"
    assert api["environment"]["SEAMS_MODEL_HASH"] == ModelGraph.load(app(chapter) / "expenses.trig").hash
    assert api["environment"]["DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert api["secrets"] == ["database_url"]
    # the store is expense_db (PostgreSQL), so nothing mounts a SQLite /data volume
    assert set(compose["volumes"]) == {"expense_db_data"}
    if chapter == "chapter-09":
        assert (app(chapter) / "handlers" / "__init__.py").is_file()


@pytest.mark.parametrize("chapter", CHAPTERS)
@pytest.mark.parametrize("file", FILES)
def test_portal_is_a_caddy_proxy_that_waits_for_a_healthy_api(chapter, file):
    services = load(chapter, file)["services"]
    portal = services["employee_portal"]
    assert portal["image"] == "caddy:2-alpine"
    assert portal["command"] == "caddy reverse-proxy --from :8000 --to expense_api:8000"
    assert portal["ports"] == ["8080:8000"]
    assert portal["depends_on"] == {"expense_api": {"condition": "service_healthy"}}
    assert "/healthz" in " ".join(portal["healthcheck"]["test"])
    api = services["expense_api"]
    assert "/healthz" in " ".join(api["healthcheck"]["test"])
    # the runtime opens its store at load, so the database must accept connections first
    assert api["depends_on"] == {"expense_db": {"condition": "service_healthy"}}
    assert "healthcheck" in services["expense_db"]
    for service in services.values():
        check = service["healthcheck"]
        assert (check["timeout"], check["retries"], check["start_period"]) == ("5s", 12, "5s")


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_development_builds_the_chapter_into_the_runtime_image(chapter):
    api = load(chapter, "compose.development.yaml")["services"]["expense_api"]
    assert api["image"] == "seams/expense-api:local"
    assert api["pull_policy"] == "build"
    build = api["build"]
    assert (app(chapter) / build["context"]).resolve() == ROOT
    assert build["dockerfile"] == "docker/runtime.Dockerfile"
    assert build["args"] == {"SEAMS_APP_DIR": f"examples/expenses/{chapter}", "SEAMS_ROUTES_FILE": "expense_api.py"}
    assert (ROOT / build["args"]["SEAMS_APP_DIR"] / "generated" / build["args"]["SEAMS_ROUTES_FILE"]).is_file()
    # no static dev user: identities (and so roles) come from the request headers
    assert "SEAMS_DEV_USER" not in api["environment"]
    # placement is swarm-only; development contains no nodes, and one replica is the default
    assert "deploy" not in api


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_development_store_password_matches_the_local_secret_file(chapter):
    compose = load(chapter, "compose.development.yaml")
    env = {key: default(value) for key, value in compose["services"]["expense_db"]["environment"].items()}
    assert env == {"POSTGRES_DB": "expenses", "POSTGRES_PASSWORD": "seams-dev"}
    secret = compose["secrets"]["database_url"]
    assert set(secret) == {"file"}
    assert secret["file"].startswith("${DATABASE_URL_FILE:-")
    secret_file = (app(chapter) / default(secret["file"])).resolve()
    assert secret_file == ROOT / "docker" / "local-secrets" / "expense_database_url"
    # the runtime connects with this URL (ADR-0011 binding expense_api -> expense_db)
    url = secret_file.read_text(encoding="utf-8").strip()
    assert url == f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@expense_db:5432/{env['POSTGRES_DB']}"


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_production_stays_production_shaped(chapter):
    compose = load(chapter, "compose.production.yaml")
    services = compose["services"]
    api = services["expense_api"]
    assert api["image"] == f"ghcr.io/example/expense-api:0.{chapter[-1]}.0"
    assert "build" not in api and "pull_policy" not in api
    db = services["expense_db"]
    assert db["environment"] == {"POSTGRES_DB": "expenses", "POSTGRES_PASSWORD_FILE": "/run/secrets/postgres_password"}
    assert db["secrets"] == ["postgres_password"]
    assert compose["secrets"] == {
        "database_url": {"name": "expenses-prod-database-url", "external": True},
        "postgres_password": {"name": "expenses-prod-postgres-password", "external": True},
    }
    nodes = {"employee_portal": "web01", "expense_api": "app01", "expense_db": "db01"}
    for name, node in nodes.items():
        assert services[name]["deploy"]["placement"]["constraints"] == [f"node.labels.seams.node == {node}"]
    assert "${" not in (app(chapter) / "compose.production.yaml").read_text(encoding="utf-8")
