"""compose.override.yaml turns the generated, prod-shaped compose.yaml into a
stack that runs on a laptop, without editing the generated file.

Each test renders the merged config with `docker compose config --format json`
from the repository root. It needs only the docker CLI and its compose plugin
(no daemon); those tests skip when either is absent. The Dockerfile checks are
plain text reads and always run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from seams_gen import generate_compose
from seams_runtime import model_hash

ROOT = Path(__file__).resolve().parents[1]
TRIG = ROOT / "examples" / "chat-app" / "chat-app.trig"
COMPOSE = ROOT / "compose.yaml"
DOCKERFILE = ROOT / "docker" / "runtime.Dockerfile"


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    return probe.returncode == 0


COMPOSE_AVAILABLE = _compose_available()

# Host variables the override reads; cleared so the developer's shell cannot change the result.
HOST_KNOBS = (
    "LLM_API_KEY_FILE",
    "LLM_GATEWAY_STUB",
    "LLM_MODEL_OVERRIDE",
    "UPSTREAM_BASE_URL",
    "SEAMS_APP_DIR",
    "SEAMS_ROUTES_FILE",
)


def compose_config(*files: str, **env: str) -> dict:
    if not COMPOSE_AVAILABLE:
        pytest.skip("docker CLI or compose plugin not installed")
    environ = {k: v for k, v in os.environ.items() if k not in HOST_KNOBS and not k.startswith("COMPOSE_")}
    environ.update(env)
    args = ["docker", "compose"]
    for f in files:
        args += ["-f", f]
    result = subprocess.run(
        args + ["config", "--format", "json"], cwd=ROOT, env=environ, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def key_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("secrets") / "llm_api_key"
    path.write_text("")
    return path


@pytest.fixture(scope="module")
def merged(key_file) -> dict:
    return compose_config("compose.yaml", "compose.override.yaml", LLM_API_KEY_FILE=str(key_file))


def test_chat_api_is_built_locally_with_one_replica(merged):
    api = merged["services"]["chat_api"]
    assert api["build"]["dockerfile"] == "docker/runtime.Dockerfile"
    assert api["pull_policy"] == "build"
    assert api["deploy"]["replicas"] == 1
    assert api["environment"]["SEAMS_DEV_USER"] == "builder"
    assert api["environment"]["SEAMS_SEED"] == "/app/seed.json"
    assert "healthz" in " ".join(api["healthcheck"]["test"])
    # the store is message_db (PostgreSQL), so no SQLite volume is mounted
    assert not any(v["target"] == "/data" for v in api["volumes"])
    assert "chat_api_data" not in merged.get("volumes", {})


def test_runtime_build_args_default_to_the_chat_app(merged):
    args = merged["services"]["chat_api"]["build"]["args"]
    assert args == {"SEAMS_APP_DIR": "examples/chat-app", "SEAMS_ROUTES_FILE": "chat_api.py"}


def test_runtime_build_args_pass_through_from_the_host(key_file):
    cfg = compose_config(
        "compose.yaml",
        "compose.override.yaml",
        LLM_API_KEY_FILE=str(key_file),
        SEAMS_APP_DIR="examples/other-app",
        SEAMS_ROUTES_FILE="other_api.py",
    )
    args = cfg["services"]["chat_api"]["build"]["args"]
    assert args == {"SEAMS_APP_DIR": "examples/other-app", "SEAMS_ROUTES_FILE": "other_api.py"}


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


def test_gateway_is_built_locally_and_reads_the_key_file(merged):
    gw = merged["services"]["llm_gateway"]
    assert gw["build"]["dockerfile"] == "docker/gateway.Dockerfile"
    assert gw["pull_policy"] == "build"
    assert [s["source"] for s in gw["secrets"]] == ["llm_api_key"]
    assert gw["environment"]["LLM_API_KEY_FILE"] == "/run/secrets/llm_api_key"
    # unset host knobs: empty stub flag (key decides), default upstream
    assert gw["environment"]["LLM_GATEWAY_STUB"] == ""
    assert gw["environment"]["UPSTREAM_BASE_URL"] == "https://api.openai.com/v1"


def test_gateway_knobs_pass_through_from_the_host(key_file):
    cfg = compose_config(
        "compose.yaml",
        "compose.override.yaml",
        LLM_API_KEY_FILE=str(key_file),
        LLM_GATEWAY_STUB="1",
        LLM_MODEL_OVERRIDE="llama3",
        UPSTREAM_BASE_URL="http://host.docker.internal:11434/v1",
    )
    env = cfg["services"]["llm_gateway"]["environment"]
    assert env["LLM_GATEWAY_STUB"] == "1"
    assert env["LLM_MODEL_OVERRIDE"] == "llama3"
    assert env["UPSTREAM_BASE_URL"] == "http://host.docker.internal:11434/v1"


def test_no_secret_is_external(merged, key_file):
    secrets = merged["secrets"]
    assert set(secrets) == {"db_url", "llm_api_key"}
    for name, secret in secrets.items():
        assert not secret.get("external"), name
        assert "file" in secret, name
    assert Path(secrets["llm_api_key"]["file"]) == key_file
    assert Path(secrets["db_url"]["file"]) == ROOT / "docker" / "local-secrets" / "db_url"
    assert (ROOT / "docker" / "local-secrets" / "db_url").is_file()


def test_chat_ui_is_a_caddy_proxy_to_chat_api(merged):
    ui = merged["services"]["chat_ui"]
    assert ui["image"].startswith("caddy:")
    assert ui["command"] == ["caddy", "reverse-proxy", "--from", ":8000", "--to", "chat_api:8000"]
    assert [(p["published"], p["target"]) for p in ui["ports"]] == [("8080", 8000)]
    assert ui["depends_on"]["chat_api"]["condition"] == "service_healthy"


def test_message_db_has_a_password(merged):
    assert merged["services"]["message_db"]["environment"]["POSTGRES_PASSWORD"]


def test_message_db_matches_the_local_db_url(merged):
    # The runtime connects through DB_URL_FILE (ADR-0011 binding chat_api -> message_db),
    # so the database name and password must be the ones the committed URL names.
    env = merged["services"]["message_db"]["environment"]
    url = (ROOT / "docker" / "local-secrets" / "db_url").read_text(encoding="utf-8").strip()
    assert url == f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@message_db:5432/{env['POSTGRES_DB']}"
    assert env["POSTGRES_DB"] == "chat"


def test_chat_api_waits_for_a_healthy_message_db(merged):
    # The runtime opens its store at load; a started-but-not-ready Postgres would fail it.
    depends = merged["services"]["chat_api"]["depends_on"]
    assert depends["message_db"]["condition"] == "service_healthy"
    assert merged["services"]["message_db"]["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U postgres"]


def test_generated_model_mounts_and_hash_survive(merged):
    api = merged["services"]["chat_api"]
    model_mounts = {v["target"]: v for v in api["volumes"] if v["target"].startswith("/model/")}
    assert set(model_mounts) == {"/model/chat-app.trig", "/model/chat_process.bpmn", "/model/routing.dmn"}
    assert all(v["read_only"] for v in model_mounts.values())
    assert api["environment"]["SEAMS_MODEL_HASH"] == model_hash(TRIG)


def test_generated_compose_is_untouched():
    assert COMPOSE.read_text(encoding="utf-8") == generate_compose(TRIG, base_dir=ROOT)


def test_without_the_override_the_secrets_stay_external():
    # Negative case: the generated file alone is prod-shaped, so the override
    # is what makes the stack local.
    cfg = compose_config("compose.yaml")
    assert all(s.get("external") for s in cfg["secrets"].values())
    api = cfg["services"]["chat_api"]
    assert "build" not in api
    assert api["deploy"]["replicas"] == 3
    assert cfg["services"]["chat_ui"]["image"].startswith("ghcr.io/example/")
    assert "POSTGRES_PASSWORD" not in cfg["services"]["message_db"]["environment"]
