"""`seams secrets` lists each environment's configuration keys and checks that they exist without reading values (M016/S04).

The chat app is copied into ``tmp_path/examples/chat-app`` so its secret files
(``../../docker/local-secrets/db_url``, ``../../.secrets/llm_api_key``) resolve
under ``tmp_path``, where each test creates or leaves out what it needs.
Docker is replaced through ``shutil.which`` and ``subprocess.run`` in the
secrets module, so no test depends on the host's docker.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from seams_cli import Row
from seams_cli.__main__ import main
from seams_cli.secrets import (
    DockerSecretChecker,
    FileChecker,
    collect_rows,
    dotenv_keys,
    load_model,
    render_example,
)

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "examples/chat-app"
CHAPTER = ROOT / "examples/expenses/chapter-08"
SENTINEL = "SENTINEL-do-not-print-7f3a9c"

DEVELOPMENT = [
    ("development", "chat_api", "DB_URL", "secret-file", "../../docker/local-secrets/db_url"),
    ("development", "chat_api", "LLM_GATEWAY_URL", "service", "llm_gateway"),
    ("development", "chat_api", "SEAMS_DEV_USER", "value", None),
    ("development", "chat_api", "SEAMS_SEED", "value", None),
    ("development", "llm_gateway", "LLM_API_KEY", "secret-file", "../../.secrets/llm_api_key"),
    ("development", "llm_gateway", "LLM_GATEWAY_STUB", "value", None),
    ("development", "llm_gateway", "LLM_MODEL_OVERRIDE", "value", None),
    ("development", "llm_gateway", "UPSTREAM_BASE_URL", "value", None),
    ("development", "message_db", "POSTGRES_DB", "value", None),
    ("development", "message_db", "POSTGRES_PASSWORD", "value", None),
]
PRODUCTION = [
    ("production", "chat_api", "DB_URL", "secret-ref", "chat-prod-db-url"),
    ("production", "chat_api", "LLM_GATEWAY_URL", "service", "llm_gateway"),
    ("production", "llm_gateway", "LLM_API_KEY", "secret-ref", "chat-prod-llm-key"),
    ("production", "llm_gateway", "UPSTREAM_BASE_URL", "value", None),
    ("production", "message_db", "POSTGRES_DB", "value", None),
    ("production", "message_db", "POSTGRES_PASSWORD", "secret-ref", "chat-prod-postgres-password"),
]


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def no_docker(monkeypatch):
    monkeypatch.setattr("seams_cli.secrets.shutil.which", lambda name: None)


def _fake_docker(monkeypatch, run):
    monkeypatch.setattr("seams_cli.secrets.shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr("seams_cli.secrets.subprocess.run", run)


@pytest.fixture
def chat(tmp_path) -> Path:
    """A copy of the chat app at tmp_path/examples/chat-app, with neither secret file."""
    target = tmp_path / "examples/chat-app"
    shutil.copytree(CHAT, target, ignore=shutil.ignore_patterns(".env", ".env.example", "__pycache__"))
    return target


def _secret_files(chat: Path) -> None:
    for rel in ("docker/local-secrets/db_url", ".secrets/llm_api_key"):
        path = chat.parent.parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{SENTINEL}\n", encoding="utf-8")


def _table(rows: list[Row]) -> list[tuple]:
    return [(r.environment, r.container, r.key, r.kind, r.source) for r in rows]


def test_rows_for_chat_app_development_and_production():
    model = load_model(CHAT / "chat-app.trig")
    assert _table(collect_rows(model, CHAT)) == DEVELOPMENT + PRODUCTION
    assert _table(collect_rows(model, CHAT, "production")) == PRODUCTION
    literals = {r.key: r.literal for r in collect_rows(model, CHAT, "development") if r.kind == "value"}
    assert literals["SEAMS_DEV_USER"] == "builder" and literals["LLM_GATEWAY_STUB"] == ""


def test_all_present_prints_one_row_per_binding_and_exits_0(chat, no_docker, capsys):
    _secret_files(chat)
    assert main(["secrets", "--project", str(chat), "--env", "development"]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [f"{e} {c} {k} {kind} present {s or '-'}" for e, c, k, kind, s in DEVELOPMENT]
    assert err == ""


def test_a_missing_secret_file_is_missing_and_exits_1(chat, no_docker, capsys):
    assert main(["secrets", "--project", str(chat), "--env", "development"]) == 1
    out, err = capsys.readouterr()
    assert "development chat_api DB_URL secret-file missing ../../docker/local-secrets/db_url" in out.splitlines()
    assert "development llm_gateway LLM_API_KEY secret-file missing ../../.secrets/llm_api_key" in out.splitlines()
    assert err.strip() == "seams secrets: 2 missing"


def test_a_secret_file_is_never_opened(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text(SENTINEL, encoding="utf-8")
    secret.chmod(0)
    try:
        row = Row("production", "api", "KEY", "secret-file", "secret")
        assert FileChecker(tmp_path).check(row) == "present"
        assert FileChecker(tmp_path).check(Row("production", "api", "KEY", "secret-file", "absent")) == "missing"
    finally:
        secret.chmod(0o600)


def test_dotenv_values_never_reach_the_output_and_its_keys_count_as_present(chat, no_docker, capsys):
    _secret_files(chat)
    (chat / ".env").write_text(
        f"# a comment={SENTINEL}\nDB_URL={SENTINEL}\nexport LLM_API_KEY = {SENTINEL}=more\n\nnot a pair {SENTINEL}\n",
        encoding="utf-8",
    )
    assert dotenv_keys(chat / ".env") == {"DB_URL", "LLM_API_KEY"}
    assert main(["secrets", "--project", str(chat), "--write-example"]) == 0
    text, err = capsys.readouterr()
    assert main(["secrets", "--project", str(chat), "--json"]) == 0
    json_out, json_err = capsys.readouterr()
    for stream in (text, err, json_out, json_err, (chat / ".env.example").read_text(encoding="utf-8")):
        assert SENTINEL not in stream
    rows = {(r["environment"], r["key"]): r["verdict"] for r in json.loads(json_out)["rows"]}
    assert rows["production", "DB_URL"] == "present"
    assert rows["production", "LLM_API_KEY"] == "present"
    assert rows["production", "POSTGRES_PASSWORD"] == "unchecked"


def test_no_docker_leaves_secret_refs_unchecked_and_says_why(chat, no_docker, capsys):
    assert main(["secrets", "--project", str(chat), "--env", "production", "--json"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    refs = [r for r in report["rows"] if r["kind"] == "secret-ref"]
    assert {r["verdict"] for r in refs} == {"unchecked"} and len(refs) == 3
    assert report["counts"] == {"present": 3, "missing": 0, "unchecked": 3}
    assert err.strip() == "seams secrets: unchecked: docker is not on PATH"


def test_docker_secret_names_decide_secret_refs(chat, monkeypatch, capsys):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="chat-prod-db-url\nchat-prod-llm-key\n", stderr="")

    _fake_docker(monkeypatch, run)
    assert main(["secrets", "--project", str(chat), "--env", "production"]) == 1
    out, err = capsys.readouterr()
    assert "production chat_api DB_URL secret-ref present chat-prod-db-url" in out.splitlines()
    assert "production message_db POSTGRES_PASSWORD secret-ref missing chat-prod-postgres-password" in out.splitlines()
    assert err.strip() == "seams secrets: 1 missing"
    assert len(calls) == 1  # listed once for all rows
    cmd, kwargs = calls[0]
    assert cmd[1:] == ["secret", "ls", "--format", "{{.Name}}"] and kwargs["timeout"] > 0


@pytest.mark.parametrize(
    ("outcome", "problem"),
    [
        (subprocess.CompletedProcess([], 1, stdout="", stderr="Error: this node is not a swarm manager.\n"), "swarm"),
        (subprocess.TimeoutExpired(["docker"], 10), "timed out"),
        (FileNotFoundError("docker"), "docker secret ls"),
    ],
)
def test_a_failing_docker_is_unchecked_never_missing(monkeypatch, outcome, problem):
    def run(cmd, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    _fake_docker(monkeypatch, run)
    checker = DockerSecretChecker()
    assert checker.check(Row("production", "api", "KEY", "secret-ref", "name")) == "unchecked"
    assert checker.problem is not None and problem in checker.problem


def test_an_unknown_environment_exits_2(chat, capsys):
    assert main(["secrets", "--project", str(chat), "--env", "staging"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "no arch:Environment 'staging'" in err and "development, production" in err


def test_a_binding_with_two_value_sources_exits_2(chat, capsys):
    trig = chat / "chat-app.trig"
    text = trig.read_text(encoding="utf-8")
    old = 'deploy:binding [ deploy:key "SEAMS_DEV_USER" ; deploy:value "builder" ] ;'
    assert old in text
    trig.write_text(
        text.replace(
            old, 'deploy:binding [ deploy:key "SEAMS_DEV_USER" ; deploy:value "builder" ; deploy:secretFile "x" ] ;'
        ),
        encoding="utf-8",
    )
    assert main(["secrets", "--project", str(chat), "--write-example"]) == 2
    _, err = capsys.readouterr()
    assert "SEAMS_DEV_USER" in err and "exactly one" in err
    assert not (chat / ".env.example").exists()


def test_a_missing_project_exits_2(tmp_path, capsys):
    assert main(["secrets", "--project", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("seams secrets: ")


@pytest.mark.parametrize("project", [CHAT, CHAPTER], ids=["chat-app", "chapter-08"])
def test_the_committed_example_is_current_and_blank_for_secrets(project):
    trig = next(project.glob("*.trig"))
    rows = collect_rows(load_model(trig), project)
    text = render_example(rows, "development")
    assert text == render_example(list(reversed(rows)), "development")
    assert text == (project / ".env.example").read_text(encoding="utf-8")
    lines = text.splitlines()
    for row in rows:
        if row.environment == "development" and row.kind in ("secret-file", "secret-ref"):
            assert f"{row.key}=" in lines
            assert lines[lines.index(f"{row.key}=") - 1] == f"# secret: {row.kind} {row.source}"
    assert not any(os.sep + "home" in line or line.startswith("# secret: secret-file /") for line in lines)


def test_write_example_defaults_to_development_and_follows_env(chat, no_docker, capsys):
    main(["secrets", "--project", str(chat), "--write-example"])
    capsys.readouterr()
    development = (chat / ".env.example").read_text(encoding="utf-8")
    assert "environment development" in development and "SEAMS_DEV_USER=builder" in development
    main(["secrets", "--project", str(chat), "--env", "production", "--write-example"])
    out = capsys.readouterr().out
    assert out.splitlines()[-1].endswith(".env.example")
    production = (chat / ".env.example").read_text(encoding="utf-8")
    assert "# secret: secret-ref chat-prod-postgres-password\nPOSTGRES_PASSWORD=\n" in production
    assert "SEAMS_DEV_USER" not in production
