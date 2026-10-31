"""The generated compose.development.yaml runs the chat app on a laptop with no
hand-written override (ADR-0015, M016/S02). It carries every effective setting
the deleted compose.override.yaml used to merge into compose.yaml, and
compose.production.yaml stays production-shaped.

Each docker test renders a file with `docker compose -f <file> config --format json`
from the repository root. It needs only the docker CLI and its compose plugin
(no daemon); those tests skip when either is absent. The file-currency and
Dockerfile checks are plain reads and always run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from seams_gen import generate_compose_environments
from seams_runtime import model_hash

ROOT = Path(__file__).resolve().parents[1]
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
DEVELOPMENT = "compose.development.yaml"
PRODUCTION = "compose.production.yaml"
DOCKERFILE = ROOT / "docker" / "runtime.Dockerfile"


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    return probe.returncode == 0


COMPOSE_AVAILABLE = _compose_available()

# Host variables the development file reads; cleared so the developer's shell cannot change the result.
HOST_KNOBS = (
    "DB_URL_FILE",
    "LLM_API_KEY_FILE",
    "LLM_GATEWAY_STUB",
    "LLM_MODEL_OVERRIDE",
    "UPSTREAM_BASE_URL",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "SEAMS_DEV_USER",
    "SEAMS_SEED",
)


def compose_config(file: str, **env: str) -> dict:
    if not COMPOSE_AVAILABLE:
        pytest.skip("docker CLI or compose plugin not installed")
    environ = {k: v for k, v in os.environ.items() if k not in HOST_KNOBS and not k.startswith("COMPOSE_")}
    environ.update(env)
    result = subprocess.run(
        ["docker", "compose", "-f", file, "config", "--format", "json"],
        cwd=ROOT,
        env=environ,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def key_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("secrets") / "llm_api_key"
    path.write_text("")
    return path


@pytest.fixture(scope="module")
def dev(key_file) -> dict:
    return compose_config(DEVELOPMENT, LLM_API_KEY_FILE=str(key_file))


@pytest.fixture(scope="module")
def prod() -> dict:
    return compose_config(PRODUCTION)


def test_root_holds_one_generated_file_per_environment():
    files = generate_compose_environments(TRIG, base_dir=ROOT)
    assert list(files) == [DEVELOPMENT, PRODUCTION]
    for name, text in files.items():
        assert (ROOT / name).read_text(encoding="utf-8") == text, f"{name} is stale; run seams generate"
    # the hand-written override and the single generated file are gone
    assert not (ROOT / "compose.override.yaml").exists()
    assert not (ROOT / "compose.yaml").exists()


def test_chat_api_is_built_locally_with_one_replica(dev):
    api = dev["services"]["chat_api"]
    assert api["build"]["dockerfile"] == "docker/runtime.Dockerfile"
    assert Path(api["build"]["context"]) == ROOT
    assert api["pull_policy"] == "build"
    assert api["deploy"]["replicas"] == 1
    assert api["environment"]["SEAMS_DEV_USER"] == "builder"
    assert api["environment"]["SEAMS_SEED"] == "/app/seed.json"
    assert "healthz" in " ".join(api["healthcheck"]["test"])
    # the store is message_db (PostgreSQL), so no SQLite volume is mounted
    assert not any(v["target"] == "/data" for v in api["volumes"])
    assert "chat_api_data" not in dev.get("volumes", {})


def test_runtime_build_args_name_the_chat_app(dev):
    # The generator derives these from the model's directory and route module,
    # so another app's generated file names its own (no host knob needed).
    args = dev["services"]["chat_api"]["build"]["args"]
    assert args == {"SEAMS_APP_DIR": "examples/chat-app", "SEAMS_ROUTES_FILE": "chat_api.py"}


def test_runtime_dockerfile_names_the_chat_app_only_as_the_arg_default():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    assert "ARG SEAMS_APP_DIR=examples/chat-app" in lines
    assert "ARG SEAMS_ROUTES_FILE=chat_api.py" in lines
    hard_coded = [line for line in lines if "examples/chat-app/" in line]
    assert hard_coded == [], hard_coded
    # chat_api.py may appear only as the ARG default, never in a COPY or ENV line
    assert [line for line in lines if "chat_api.py" in line] == ["ARG SEAMS_ROUTES_FILE=chat_api.py"]


def test_runtime_dockerfile_declares_args_before_use():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    arg_at = max(i for i, line in enumerate(lines) if line.startswith("ARG SEAMS_"))
    copies = [i for i, line in enumerate(lines) if line.startswith("COPY ${SEAMS_APP_DIR}")]
    assert len(copies) == 3
    assert all(arg_at < i for i in copies)
    routes_env = next(i for i, line in enumerate(lines) if "SEAMS_ROUTES=/app/${SEAMS_ROUTES_FILE}" in line)
    assert arg_at < routes_env


def test_runtime_dockerfile_no_longer_mentions_the_override():
    assert "compose.override" not in DOCKERFILE.read_text(encoding="utf-8")


def test_gateway_is_built_locally_and_reads_the_key_file(dev):
    gw = dev["services"]["llm_gateway"]
    assert gw["build"]["dockerfile"] == "docker/gateway.Dockerfile"
    assert gw["pull_policy"] == "build"
    assert [s["source"] for s in gw["secrets"]] == ["llm_api_key"]
    assert gw["environment"]["LLM_API_KEY_FILE"] == "/run/secrets/llm_api_key"
    # unset host knobs: empty stub flag (key decides), default upstream
    assert gw["environment"]["LLM_GATEWAY_STUB"] == ""
    assert gw["environment"]["LLM_MODEL_OVERRIDE"] == ""
    assert gw["environment"]["UPSTREAM_BASE_URL"] == "https://api.openai.com/v1"
    assert "healthz" in " ".join(gw["healthcheck"]["test"])


def test_gateway_knobs_pass_through_from_the_host(key_file):
    cfg = compose_config(
        DEVELOPMENT,
        LLM_API_KEY_FILE=str(key_file),
        LLM_GATEWAY_STUB="1",
        LLM_MODEL_OVERRIDE="llama3",
        UPSTREAM_BASE_URL="http://host.docker.internal:11434/v1",
    )
    env = cfg["services"]["llm_gateway"]["environment"]
    assert env["LLM_GATEWAY_STUB"] == "1"
    assert env["LLM_MODEL_OVERRIDE"] == "llama3"
    assert env["UPSTREAM_BASE_URL"] == "http://host.docker.internal:11434/v1"


def test_chat_api_no_longer_holds_the_llm_key(dev, prod):
    # The gateway is what uses the key, so the model binds it there (a shared correction).
    for cfg in (dev, prod):
        assert [s["source"] for s in cfg["services"]["chat_api"]["secrets"]] == ["db_url"]


def test_no_development_secret_is_external(dev, key_file):
    secrets = dev["secrets"]
    assert set(secrets) == {"db_url", "llm_api_key"}
    for name, secret in secrets.items():
        assert not secret.get("external"), name
        assert "file" in secret, name
    assert Path(secrets["llm_api_key"]["file"]) == key_file
    assert Path(secrets["db_url"]["file"]) == ROOT / "docker" / "local-secrets" / "db_url"
    assert (ROOT / "docker" / "local-secrets" / "db_url").is_file()


def test_development_secret_file_paths_follow_the_host(tmp_path):
    db_url = tmp_path / "db_url"
    cfg = compose_config(DEVELOPMENT, DB_URL_FILE=str(db_url), LLM_API_KEY_FILE=str(tmp_path / "key"))
    assert Path(cfg["secrets"]["db_url"]["file"]) == db_url


def test_chat_ui_is_a_caddy_proxy_to_chat_api(dev, prod):
    for cfg in (dev, prod):
        ui = cfg["services"]["chat_ui"]
        assert ui["image"].startswith("caddy:")
        assert ui["command"] == ["caddy", "reverse-proxy", "--from", ":8000", "--to", "chat_api:8000"]
        assert [(p["published"], p["target"]) for p in ui["ports"]] == [("8080", 8000)]
        assert ui["depends_on"]["chat_api"]["condition"] == "service_healthy"


def test_message_db_matches_the_local_db_url(dev):
    # The runtime connects through DB_URL_FILE (ADR-0011 binding chat_api -> message_db),
    # so the database name and password must be the ones the committed URL names.
    env = dev["services"]["message_db"]["environment"]
    url = (ROOT / "docker" / "local-secrets" / "db_url").read_text(encoding="utf-8").strip()
    assert url == f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@message_db:5432/{env['POSTGRES_DB']}"
    assert env["POSTGRES_DB"] == "chat"
    assert env["POSTGRES_PASSWORD"] == "seams-dev"


def test_chat_api_waits_for_healthy_dependencies(dev):
    # The runtime opens its store at load; a started-but-not-ready Postgres would fail it.
    depends = dev["services"]["chat_api"]["depends_on"]
    assert depends["message_db"]["condition"] == "service_healthy"
    assert depends["llm_gateway"]["condition"] == "service_healthy"
    assert dev["services"]["message_db"]["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U postgres"]


def test_generated_model_mounts_and_hash(dev):
    api = dev["services"]["chat_api"]
    model_mounts = {v["target"]: v for v in api["volumes"] if v["target"].startswith("/model/")}
    assert set(model_mounts) == {"/model/chat-app.trig", "/model/chat_process.bpmn", "/model/routing.dmn"}
    assert all(v["read_only"] for v in model_mounts.values())
    assert api["environment"]["SEAMS_MODEL_HASH"] == model_hash(TRIG)


def test_production_stays_production_shaped(prod):
    # Negative case: none of the development overrides leak into production.
    assert all(s.get("external") for s in prod["secrets"].values())
    assert set(prod["secrets"]) == {"db_url", "llm_api_key", "postgres_password"}
    api = prod["services"]["chat_api"]
    assert "build" not in api
    assert api["image"].startswith("ghcr.io/example/")
    assert "SEAMS_DEV_USER" not in api["environment"]
    assert "SEAMS_SEED" not in api["environment"]
    assert "build" not in prod["services"]["llm_gateway"]
    db_env = prod["services"]["message_db"]["environment"]
    assert "POSTGRES_PASSWORD" not in db_env
    assert db_env["POSTGRES_PASSWORD_FILE"] == "/run/secrets/postgres_password"


def test_production_caps_the_serving_container_at_one_replica():
    # The model declares 3 replicas; the file holds 1 and says why (backlog A10).
    text = (ROOT / PRODUCTION).read_text(encoding="utf-8")
    assert "The model declares 3 replicas" in text and "A10" in text
