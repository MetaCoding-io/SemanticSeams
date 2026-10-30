"""`seams status` compares each runtime container's /healthz model_hash with the current model (M012/S04, D045).

Expenses chapter 8 is copied into tmp_path and, for the git cases, made a git
repository whose seams.lock history holds two older model hashes before the
current one (one of them twice). A threading http.server on 127.0.0.1 plays the runtime's /healthz
with a configurable status, body and delay.
"""

import json
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import seams
from seams_cli import ProjectError, Status, load_project, run_status
from seams_cli.__main__ import main
from seams_cli.status import fetch_health, lock_history, runtime_containers

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "examples/expenses/chapter-08"
MODEL = "expenses.trig"
# seams.lock is committed with OLD_B, OLD_A, OLD_B and then the current hash, so newest
# first the distinct hashes are current, OLD_B (1 back), OLD_A (2 back).
OLD_A, OLD_B = "a" * 64, "b" * 64

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


class _Server(ThreadingHTTPServer):
    block_on_close = False  # do not wait for a deliberately slow handler at teardown
    status = 200
    body: object = {}
    delay = 0.0


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        server = self.server
        time.sleep(server.delay)
        if self.path != "/healthz":
            self.send_error(404)
            return
        payload = server.body if isinstance(server.body, bytes) else json.dumps(server.body).encode()
        self.send_response(server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def closed_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def app(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(CHAPTER, dest, ignore=shutil.ignore_patterns("__pycache__"))
    _environments(dest, "[environments.prod]\n")  # drop chapter 8's own [environments.local]
    return dest


@pytest.fixture
def current(app: Path) -> str:
    return seams.model_hash(app / MODEL)


def _git(app: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-C", str(app), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(app: Path) -> Path:
    """``app`` as a git repository with the seams.lock history described at the top."""
    lock = app / "seams.lock"
    current_text = lock.read_text(encoding="utf-8")
    _git(app, "init", "-q")
    for value in (OLD_B, OLD_A, OLD_B, None):
        if value is None:
            lock.write_text(current_text, encoding="utf-8")
        else:
            data = json.loads(current_text)
            data["model_hash"] = value
            lock.write_text(json.dumps(data) + "\n", encoding="utf-8")
        _git(app, "add", "seams.lock")
        _git(app, "commit", "-q", "-m", f"lock {value or 'current'}")
    return app


def _environments(app: Path, block: str) -> None:
    """Replace every [environments.*] table (the end of the project file) with ``block``."""
    toml = app / "seams.toml"
    text = toml.read_text(encoding="utf-8")
    text = text[: text.index("[environments.")].rstrip("\n")
    toml.write_text(text + "\n\n" + block, encoding="utf-8")


def _local(app: Path, url: str) -> None:
    _environments(app, f'[environments.prod]\n\n[environments.local]\nendpoints = {{ expense_api = "{url}" }}\n')


def _status(app: Path, env: str | None = "local", timeout: float = 5) -> list[Status]:
    return run_status(load_project(app), app / MODEL, env, timeout)


def _main(app: Path, capsys, *extra: str) -> tuple[int, list[str], str]:
    code = main(["status", "--project", str(app), *extra])
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


# ── the containers and the pieces ───────────────────────────────────────────


def test_the_runtime_containers_are_the_ones_compose_gives_the_model_hash():
    assert runtime_containers(CHAPTER / MODEL) == ("expense_api",)
    assert runtime_containers(ROOT / "examples/chat-app/chat-app.trig") == ("chat_api",)
    compose = (CHAPTER / "compose.yaml").read_text(encoding="utf-8")
    assert compose.count("SEAMS_MODEL_HASH") == 1


def test_fetch_health_reads_the_model_hash_and_strips_a_trailing_slash(server):
    server.body = {"status": "ok", "model_hash": "abc"}
    assert fetch_health(server.url + "/", 5) == ("abc", None)


@needs_git
def test_lock_history_is_newest_first(repo, current):
    assert lock_history(load_project(repo)) == [current, OLD_B, OLD_A, OLD_B]


def test_lock_history_outside_git_is_empty(app):
    assert lock_history(load_project(app)) == []


# ── verdicts ────────────────────────────────────────────────────────────────


@needs_git
def test_current(repo, server, current, capsys):
    server.body = {"status": "ok", "model_hash": current}
    _local(repo, server.url)
    assert _main(repo, capsys, "--env", "local") == (
        0,
        [f"expense_api current {current}", f"current model {current}"],
        "",
    )


@needs_git
@pytest.mark.parametrize(("reported", "back"), [(OLD_B, "1 model change behind"), (OLD_A, "2 model changes behind")])
def test_behind_counts_distinct_model_hashes(repo, server, current, capsys, reported, back):
    server.body = {"model_hash": reported}
    _local(repo, server.url)
    code, lines, err = _main(repo, capsys, "--env", "local")
    assert (code, lines, err) == (
        1,
        [f"expense_api behind {reported} {back}", f"current model {current}"],
        "seams status: 1 of 1 not current\n",
    )


@needs_git
def test_an_unknown_hash_is_ahead(repo, server):
    server.body = {"model_hash": "f" * 64}
    _local(repo, server.url)
    assert _status(repo) == [Status("expense_api", "ahead", "f" * 64, "not in the seams.lock history")]


def test_outside_git_an_old_hash_is_ahead(app, server):
    server.body = {"model_hash": OLD_B}
    _local(app, server.url)
    assert [s.verdict for s in _status(app)] == ["ahead"]


# ── unreachable ─────────────────────────────────────────────────────────────


def _unreachable(app: Path, url: str, timeout: float = 5) -> str:
    _local(app, url)
    [status] = _status(app, timeout=timeout)
    assert (status.verdict, status.reported) == ("unreachable", None)
    assert status.detail.startswith(f"{url}/healthz: ")
    return status.detail


def test_a_closed_port_is_unreachable(app, closed_url):
    assert "refused" in _unreachable(app, closed_url).lower()


def test_a_server_error_is_unreachable(app, server):
    server.status, server.body = 500, {"model_hash": "abc"}
    assert _unreachable(app, server.url).endswith("HTTP 500")


@pytest.mark.parametrize(
    "body", [{"status": "ok"}, {"model_hash": 7}, ["model_hash"], b"not json"], ids=["none", "int", "list", "invalid"]
)
def test_a_body_without_a_string_model_hash_is_unreachable(app, server, body):
    server.body = body
    detail = _unreachable(app, server.url)
    assert detail.endswith("invalid JSON" if body == b"not json" else "no string model_hash in the response")


def test_a_slow_server_times_out(app, server):
    server.delay, server.body = 2.0, {"model_hash": "abc"}
    started = time.monotonic()
    assert "timed out" in _unreachable(app, server.url, timeout=0.2)
    assert time.monotonic() - started < 1.5


def test_a_container_with_no_endpoint_is_unreachable(app, current, capsys):
    _environments(app, "[environments.prod]\n\n[environments.local]\nendpoints = {}\n")
    code, lines, err = _main(app, capsys, "--env", "local", "--timeout", "0.5")
    assert lines == ["expense_api unreachable - no endpoint in environments.local", f"current model {current}"]
    assert (code, err) == (1, "seams status: 1 of 1 not current\n")


# ── choosing the environment ────────────────────────────────────────────────


def test_env_defaults_to_the_only_one_with_endpoints(app, server, current):
    server.body = {"model_hash": current}
    _local(app, server.url)
    assert [s.verdict for s in _status(app, env=None)] == ["current"]


def test_two_environments_with_endpoints_need_env(app, server, capsys):
    url = server.url
    _environments(
        app,
        f'[environments.local]\nendpoints = {{ expense_api = "{url}" }}\n\n'
        f'[environments.prod]\nendpoints = {{ expense_api = "{url}" }}\n',
    )
    code, lines, err = _main(app, capsys)
    assert (code, lines) == (2, [])
    assert "pass --env; local, prod have `endpoints`" in err


def test_no_environment_with_endpoints_needs_env(app, capsys):
    code, _, err = _main(app, capsys)
    assert code == 2
    assert "pass --env; none has `endpoints` (environments: prod)" in err


def test_an_unknown_env_exits_2(app, server, capsys):
    _local(app, server.url)
    code, lines, err = _main(app, capsys, "--env", "staging")
    assert (code, lines) == (2, [])
    assert "no environment 'staging'; environments: prod, local" in err


def test_an_endpoint_that_is_not_a_runtime_container_exits_2(app, server, capsys):
    _environments(app, f'[environments.local]\nendpoints = {{ expense_api = "{server.url}", expense_ui = "x" }}\n')
    code, lines, err = _main(app, capsys, "--env", "local")
    assert (code, lines) == (2, [])
    assert "names expense_ui, not a runtime container; runtime containers: expense_api" in err


@pytest.mark.parametrize("value", ['"http://x"', "{ expense_api = 8080 }", '["http://x"]'])
def test_a_malformed_endpoints_table_is_a_project_error(app, value):
    _environments(app, f"[environments.local]\nendpoints = {value}\n")
    with pytest.raises(ProjectError, match=r"`environments\.local\.endpoints` must be a table of strings"):
        load_project(app)


def test_endpoints_are_parsed_and_default_to_empty(app):
    assert load_project(app).endpoints == {}
    _local(app, "http://localhost:8080")
    project = load_project(app)
    assert project.environments == ("prod", "local")
    assert project.endpoints == {"local": {"expense_api": "http://localhost:8080"}}
