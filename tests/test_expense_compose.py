"""The expense tutorial's chapter-08 compose file is current (M009/S07/T03).

examples/expenses/chapter-08/compose.yaml is generated from the checkpoint's
deploy facts by ``python -m seams_gen compose
examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08``
and committed; tests/test_expense_e2e.py brings it up with the hand-written
compose.override.yaml. This checks the committed file equals a fresh run, so
a model edit that changes the model hash (or a deploy fact) cannot leave a
stale compose file behind, and that the bind mounts are the TriG plus its
four payloads, relative to the chapter directory.
"""

import difflib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import generate_compose  # noqa: E402
from seams_runtime import ModelGraph  # noqa: E402

APP = ROOT / "examples" / "expenses" / "chapter-08"
TRIG = APP / "expenses.trig"
COMMAND = "python -m seams_gen compose examples/expenses/chapter-08/expenses.trig --out examples/expenses/chapter-08"


def test_committed_compose_file_is_current():
    committed = (APP / "compose.yaml").read_text(encoding="utf-8")
    generated = generate_compose(TRIG, base_dir=APP)
    diff = "".join(
        difflib.unified_diff(committed.splitlines(True), generated.splitlines(True), "committed", "generated")
    )
    assert committed == generated, f"compose.yaml is stale; rerun `{COMMAND}`:\n{diff}"


def test_compose_file_mounts_the_model_and_its_payloads():
    services = yaml.safe_load((APP / "compose.yaml").read_text(encoding="utf-8"))["services"]
    assert set(services) == {"employee_portal", "expense_api", "expense_db"}
    api = services["expense_api"]
    assert api["volumes"] == [
        f"./{name}:/model/{name}:ro"
        for name in ("expenses.trig", "approval.bpmn", "approval.dmn", "payout.bpmn", "payout.dmn")
    ]
    assert api["environment"]["SEAMS_MODEL"] == "/model/expenses.trig"
    assert api["environment"]["SEAMS_MODEL_HASH"] == ModelGraph.load(TRIG).hash
    assert services["employee_portal"]["ports"] == ["8080:8000"]
    assert services["employee_portal"]["depends_on"] == ["expense_api"]


def test_compose_file_declares_the_expense_store():
    """ADR-0011: the store is a PostgreSQL service on db01, and expense_api
    reaches it through the DATABASE_URL secret its binding connectsTo."""
    compose = yaml.safe_load((APP / "compose.yaml").read_text(encoding="utf-8"))
    db = compose["services"]["expense_db"]
    assert db["image"] == "postgres:16"
    assert db["environment"] == {"POSTGRES_DB": "expenses"}
    assert db["volumes"] == ["expense_db_data:/var/lib/postgresql/data"]
    assert db["deploy"]["placement"]["constraints"] == ["node.labels.seams.node == db01"]
    api = compose["services"]["expense_api"]
    assert api["depends_on"] == ["expense_db"]
    assert api["secrets"] == ["database_url"]
    assert api["environment"]["DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert compose["secrets"]["database_url"] == {"name": "expenses-prod-database-url", "external": True}


class _OverrideLoader(yaml.SafeLoader):
    """Compose's !override / !reset merge tags load as their plain value."""


for _tag in ("!override", "!reset"):
    _OverrideLoader.add_constructor(
        _tag,
        lambda loader, node: (
            loader.construct_mapping(node)
            if isinstance(node, yaml.MappingNode)
            else loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_scalar(node)
        ),
    )


def test_override_builds_chapter_8_into_the_runtime_image():
    override = yaml.load((APP / "compose.override.yaml").read_text(encoding="utf-8"), Loader=_OverrideLoader)
    assert override["name"] == "seams-expenses"
    build = override["services"]["expense_api"]["build"]
    assert (APP / build["context"]).resolve() == ROOT
    assert build["args"] == {"SEAMS_APP_DIR": "examples/expenses/chapter-08", "SEAMS_ROUTES_FILE": "expense_api.py"}
    assert (ROOT / build["args"]["SEAMS_APP_DIR"] / "generated" / build["args"]["SEAMS_ROUTES_FILE"]).is_file()
    # no static dev user: identities (and so roles) come from the request headers
    assert "SEAMS_DEV_USER" not in str(override)


def test_override_gives_the_store_a_password_and_a_local_secret_file():
    override = yaml.load((APP / "compose.override.yaml").read_text(encoding="utf-8"), Loader=_OverrideLoader)
    env = override["services"]["expense_db"]["environment"]
    assert env == {"POSTGRES_DB": "expenses", "POSTGRES_PASSWORD": "seams-dev"}
    secret_file = (APP / override["secrets"]["database_url"]["file"]).resolve()
    assert secret_file == ROOT / "docker" / "local-secrets" / "expense_database_url"
    # the runtime connects with this URL (ADR-0011 binding expense_api -> expense_db)
    url = secret_file.read_text(encoding="utf-8").strip()
    assert url == f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@expense_db:5432/{env['POSTGRES_DB']}"


def test_override_waits_for_a_healthy_store_and_drops_the_sqlite_volume():
    override = yaml.load((APP / "compose.override.yaml").read_text(encoding="utf-8"), Loader=_OverrideLoader)
    api = override["services"]["expense_api"]
    # the runtime opens its store at load, so the database must be ready first
    assert api["depends_on"] == {"expense_db": {"condition": "service_healthy"}}
    generated = yaml.safe_load((APP / "compose.yaml").read_text(encoding="utf-8"))
    assert "healthcheck" in generated["services"]["expense_db"]
    # the store is expense_db (PostgreSQL), so nothing mounts a SQLite /data volume
    assert "volumes" not in api
    assert "expense_api_data" not in override.get("volumes", {})
