"""``seams status``: is each running runtime container on the current model? (M012/S04, D045)

The containers are the model's runtime containers, the ones the compose
generator gives SEAMS_MODEL_HASH (``runtime_containers``). Their base URLs come
from the ``endpoints`` table of an ``[environments.<name>]`` in seams.toml.
``run_status`` GETs ``<url>/healthz`` from each and compares the reported
``model_hash`` with the current model's:

- ``current``: the same hash.
- ``behind``: a hash that some version of seams.lock in HEAD's git history
  records (``lock_history``); the detail says how many model changes back.
- ``ahead``: any other hash, i.e. a newer or diverged model. With no git, or
  no lock history, every differing hash is ahead.
- ``unreachable``: a connection error, a timeout, a non-2xx response, a body
  with no string ``model_hash``, or no endpoint for the container; the detail
  names the URL and the error.

Only the standard library talks HTTP and runs git, so the CLI gains no
dependency. A missing or ambiguous environment, an endpoint naming a container
that is not a runtime container, or a model that cannot be loaded raises
ProjectError (exit 2).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import seams

from seams_gen.compose import runtime_containers as _runtime_names

from .lockfile import lock_path
from .project import Project, ProjectError

VERDICTS = ("current", "behind", "ahead", "unreachable")
MAX_BODY = 1 << 20  # a /healthz body is a few hundred bytes; never read more than this
MAX_WORKERS = 8


class Status(NamedTuple):
    """One runtime container's verdict. ``reported`` is the /healthz model_hash, or None when unreachable."""

    container: str
    verdict: str
    reported: str | None
    detail: str


class Health(NamedTuple):
    """What ``fetch_health`` got: the reported hash, or an error naming the URL."""

    model_hash: str | None
    error: str | None


def _load(model: Path) -> seams.Model:
    try:
        return seams.load(model)
    except Exception as err:
        raise ProjectError(f"{model}: cannot load the model: {err}") from err


def runtime_containers(model_path: Path) -> tuple[str, ...]:
    """The local names of the model's runtime containers, sorted."""
    return _runtime_names(_load(model_path))


def fetch_health(url: str, timeout: float) -> Health:
    """GET ``<url>/healthz`` and read its ``model_hash``. Every failure is an error, never an exception."""
    target = url.rstrip("/") + "/healthz"
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                return Health(None, f"{target}: HTTP {response.status}")
            body = response.read(MAX_BODY)
    except urllib.error.HTTPError as err:
        return Health(None, f"{target}: HTTP {err.code}")
    except urllib.error.URLError as err:
        return Health(None, f"{target}: {err.reason}")
    except (OSError, ValueError) as err:  # timeouts mid-read, resets, a malformed URL
        return Health(None, f"{target}: {err or type(err).__name__}")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Health(None, f"{target}: invalid JSON")
    reported = data.get("model_hash") if isinstance(data, dict) else None
    if not isinstance(reported, str):
        return Health(None, f"{target}: no string model_hash in the response")
    return Health(reported, None)


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def lock_history(project: Project) -> list[str]:
    """The model_hash of every committed seams.lock version reachable from HEAD,
    newest first. Any git failure, or no git, gives []; unparsable versions are skipped."""
    if shutil.which("git") is None:
        return []
    root = str(project.root)
    top = _git("-C", root, "rev-parse", "--show-toplevel")
    if top is None:
        return []
    lock = lock_path(project).resolve()
    try:
        rel = lock.relative_to(Path(top.strip()).resolve()).as_posix()
    except ValueError:
        return []
    log = _git("-C", root, "log", "--format=%H", "HEAD", "--", str(lock))
    if log is None:
        return []
    hashes = []
    for sha in log.split():
        text = _git("-C", root, "show", f"{sha}:{rel}")
        if text is None:
            continue
        try:
            value = json.loads(text).get("model_hash")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(value, str):
            hashes.append(value)
    return hashes


def resolve_environment(project: Project, env: str | None) -> str:
    """``env`` when the project declares it; with none, the only environment that has endpoints."""
    names = ", ".join(project.environments) or "(none)"
    if env is not None:
        if env not in project.environments:
            raise ProjectError(f"{project.path}: no environment {env!r}; environments: {names}")
        return env
    with_endpoints = [name for name in project.environments if name in project.endpoints]
    if len(with_endpoints) != 1:
        found = "none has" if not with_endpoints else f"{', '.join(with_endpoints)} have"
        raise ProjectError(f"{project.path}: pass --env; {found} `endpoints` (environments: {names})")
    return with_endpoints[0]


def _changes(n: int) -> str:
    return f"{n} model change{'s' if n != 1 else ''} behind"


def verdict(container: str, health: Health, current: str, history: list[str]) -> Status:
    """Compare one container's /healthz result with ``current`` and the lock ``history`` (newest first)."""
    if health.error is not None:
        return Status(container, "unreachable", None, health.error)
    reported = health.model_hash
    if reported == current:
        return Status(container, "current", reported, "")
    chain = [current]
    for value in history:
        if value not in chain:
            chain.append(value)
    if reported in chain:
        return Status(container, "behind", reported, _changes(chain.index(reported)))
    return Status(container, "ahead", reported, "not in the seams.lock history")


def run_status(project: Project, model: Path, env: str | None, timeout: float) -> list[Status]:
    """One Status per runtime container of ``model`` in environment ``env``, sorted by container."""
    name = resolve_environment(project, env)
    loaded = _load(model)
    containers = _runtime_names(loaded)
    endpoints = project.endpoints.get(name, {})
    unknown = sorted(set(endpoints) - set(containers))
    if unknown:
        raise ProjectError(
            f"{project.path}: `environments.{name}.endpoints` names {', '.join(unknown)}, "
            f"not a runtime container; runtime containers: {', '.join(containers) or '(none)'}"
        )
    current = loaded.hash
    history = lock_history(project)
    reachable = [c for c in containers if c in endpoints]
    with ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, len(reachable)))) as pool:
        healths = dict(zip(reachable, pool.map(lambda c: fetch_health(endpoints[c], timeout), reachable), strict=True))
    missing = Health(None, f"no endpoint in environments.{name}")
    return [verdict(c, healths.get(c, missing), current, history) for c in containers]
