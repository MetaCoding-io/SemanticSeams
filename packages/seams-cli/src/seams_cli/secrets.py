"""``seams secrets``: does every configuration key and secret of each environment exist? (M016/S04, backlog A8)

``collect_rows`` reads the model's architecture view: for each arch:Environment
(by IRI, named by its local name), each container (by IRI) and each binding
of ``Container.for_environment`` (by key), one ``Row``. Its ``kind`` is
``value``, ``secret-ref``, ``secret-file`` or ``service``, and its ``source``
says where the value comes from without being it: the deploy:secretName (or
the deploy:secretRef IRI when no name is given), the deploy:secretFile path
resolved against the model's directory and written relative to the project
root, or the local name of the deploy:serviceOf container.

``check_rows`` gives each row a verdict, ``present``, ``missing`` or
``unchecked``. Plain values and services are present by definition. Every
other row asks the checkers in order, and the first answer that is not
``unchecked`` wins:

- ``FileChecker``: a secret-file row is present when the path exists. The file
  is never opened.
- ``DotenvChecker``: a key named in ``<project root>/.env`` is present. Only
  the key names are kept; everything after the first ``=`` is discarded.
- ``DockerSecretChecker``: a secret-ref row is present when its secret name is
  in ``docker secret ls``, missing when it is not. With no docker, a failing
  command (not a swarm manager, say) or a timeout, it answers ``unchecked``
  and records why in ``problem``.

No checker reads a secret's value, so no value can reach the output.
``render_example`` writes the ``.env.example`` of one environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

import seams
from seams import DEPLOY, ResolutionError, local_name

from .project import Project, ProjectError

Verdict = Literal["present", "missing", "unchecked"]
KINDS = {
    DEPLOY.value: "value",
    DEPLOY.secretRef: "secret-ref",
    DEPLOY.secretFile: "secret-file",
    DEPLOY.serviceOf: "service",
}
SECRET_KINDS = ("secret-ref", "secret-file")
DEVELOPMENT = "development"
DOTENV = ".env"
EXAMPLE = ".env.example"
DOCKER_TIMEOUT = 10.0


@dataclass(frozen=True)
class Row:
    """One binding of one container in one environment. ``source`` is never a
    value, and ``literal`` is the model's own deploy:value for a ``value`` row
    (None otherwise); it is used for ``.env.example`` and never printed."""

    environment: str
    container: str
    key: str
    kind: str
    source: str | None
    verdict: Verdict = "unchecked"
    literal: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {
            "environment": self.environment,
            "container": self.container,
            "key": self.key,
            "kind": self.kind,
            "source": self.source,
            "verdict": self.verdict,
        }


class Checker(Protocol):
    def check(self, row: Row) -> Verdict: ...


def load_model(path: Path) -> seams.Model:
    try:
        return seams.load(path)
    except Exception as err:
        raise ProjectError(f"{path}: cannot load the model: {err}") from err


def environment_names(model: seams.Model) -> tuple[str, ...]:
    """The local names of the model's arch:Environments, by IRI."""
    return tuple(local_name(e.iri) for e in model.architecture.environments())


def _kind(container: seams.Container, binding: seams.Binding) -> str:
    if len(binding.kinds) != 1:
        found = ", ".join(local_name(k) for k in binding.kinds) or "none"
        raise ResolutionError(
            container.iri,
            DEPLOY.binding,
            f"binding {binding.key!r} needs exactly one of deploy:value, deploy:secretRef, "
            f"deploy:secretFile, deploy:serviceOf; found {found}",
        )
    return KINDS[binding.kinds[0]]


def collect_rows(model: seams.Model, root: Path, env: str | None = None) -> list[Row]:
    """Every binding of every container in each environment (or only ``env``),
    unchecked. An unknown ``env`` raises ProjectError; a malformed binding,
    ResolutionError."""
    arch = model.architecture
    environments = list(arch.environments())
    if env is not None:
        environments = [e for e in environments if local_name(e.iri) == env]
        if not environments:
            names = ", ".join(environment_names(model)) or "(none)"
            raise ProjectError(f"{model.path}: no arch:Environment {env!r}; environments: {names}")
    model_dir = model.base_dir
    rows = []
    for environment in environments:
        for container in arch.containers():
            for b in container.for_environment(environment).bindings:
                kind = _kind(container, b)
                source = None
                if kind == "secret-ref":
                    source = b.secret_name or (None if b.secret_ref is None else str(b.secret_ref))
                elif kind == "secret-file" and b.secret_file is not None:
                    source = Path(os.path.relpath((model_dir / b.secret_file).resolve(), root.resolve())).as_posix()
                elif kind == "service" and b.service_of is not None:
                    source = local_name(b.service_of.iri)
                rows.append(
                    Row(
                        environment=local_name(environment.iri),
                        container=local_name(container.iri),
                        key=b.key,
                        kind=kind,
                        source=source,
                        literal=b.value if kind == "value" else None,
                    )
                )
    return rows


class FileChecker:
    """A secret-file row exists when its path does; relative sources resolve against ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self, row: Row) -> Verdict:
        if row.kind != "secret-file" or row.source is None:
            return "unchecked"
        return "present" if (self.root / row.source).exists() else "missing"


def dotenv_keys(path: Path) -> frozenset[str]:
    """The key names a .env file sets. Each line's text after its first ``=`` is discarded at once."""
    if not path.is_file():
        return frozenset()
    keys = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name = line.split("=", 1)[0].strip() if "=" in line else ""
        name = name.removeprefix("export ").strip()
        if name and not name.startswith("#"):
            keys.add(name)
    return frozenset(keys)


class DotenvChecker:
    """A value or secret-ref key that ``<root>/.env`` names is present; any other row is unchecked."""

    def __init__(self, root: Path) -> None:
        self.keys = dotenv_keys(root / DOTENV)

    def check(self, row: Row) -> Verdict:
        if row.kind in ("value", "secret-ref") and row.key in self.keys:
            return "present"
        return "unchecked"


class DockerSecretChecker:
    """A secret-ref row's secret name against ``docker secret ls``, listed once.
    Any failure makes every answer ``unchecked`` and is kept in ``problem``."""

    def __init__(self, timeout: float = DOCKER_TIMEOUT) -> None:
        self.timeout = timeout
        self.problem: str | None = None
        self._names: frozenset[str] | None = None
        self._listed = False

    def _list(self) -> frozenset[str] | None:
        if self._listed:
            return self._names
        self._listed = True
        docker = shutil.which("docker")
        if docker is None:
            self.problem = "docker is not on PATH"
            return None
        try:
            done = subprocess.run(
                [docker, "secret", "ls", "--format", "{{.Name}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            self.problem = f"docker secret ls timed out after {self.timeout:g}s"
            return None
        except OSError as err:
            self.problem = f"docker secret ls: {err}"
            return None
        if done.returncode != 0:
            detail = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"exit {done.returncode}"
            self.problem = f"docker secret ls: {detail}"
            return None
        self._names = frozenset(line.strip() for line in done.stdout.splitlines() if line.strip())
        return self._names

    def check(self, row: Row) -> Verdict:
        if row.kind != "secret-ref" or row.source is None:
            return "unchecked"
        names = self._list()
        if names is None:
            return "unchecked"
        return "present" if row.source in names else "missing"


def default_checkers(root: Path) -> list[Checker]:
    return [FileChecker(root), DotenvChecker(root), DockerSecretChecker()]


def check_rows(rows: Iterable[Row], checkers: Sequence[Checker]) -> list[Row]:
    """Each row with its verdict: present for values and services, else the
    first checker answer that is not unchecked."""
    checked = []
    for row in rows:
        verdict: Verdict = "unchecked"
        if row.kind in ("value", "service"):
            verdict = "present"
        else:
            for checker in checkers:
                verdict = checker.check(row)
                if verdict != "unchecked":
                    break
        checked.append(replace(row, verdict=verdict))
    return checked


def example_environment(model: seams.Model, env: str | None) -> str:
    """``env``, else development when the model declares it, else its first environment."""
    names = environment_names(model)
    if env is not None:
        return env
    if not names:
        raise ProjectError(f"{model.path}: no arch:Environment to write {EXAMPLE} for")
    return DEVELOPMENT if DEVELOPMENT in names else names[0]


def render_example(rows: Iterable[Row], env: str) -> str:
    """The ``.env.example`` of ``env``: one ``KEY=`` line per key, sorted. A key
    with only plain values keeps the model's literal when every container
    agrees; a secret is always blank, under a ``# secret: <kind> <source>``
    comment per source, and a service under ``# service: <container>``."""
    by_key: dict[str, list[Row]] = {}
    for row in rows:
        if row.environment == env:
            by_key.setdefault(row.key, []).append(row)
    lines = [
        f"# The configuration keys of environment {env}, from the model. Written by `seams secrets --write-example`."
    ]
    for key in sorted(by_key):
        group = by_key[key]
        comments = sorted(
            {f"# secret: {r.kind} {r.source or '-'}" for r in group if r.kind in SECRET_KINDS}
            | {f"# service: {r.source or '-'}" for r in group if r.kind == "service"}
        )
        literals = {r.literal or "" for r in group if r.kind == "value"}
        value = ""
        if not comments and len(literals) == 1:
            value = literals.pop()
        elif not comments and literals:
            containers = ", ".join(sorted({r.container for r in group}))
            comments = [f"# differs per container: {containers}"]
        lines.extend(comments)
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def run_secrets(project: Project, model_path: Path, env: str | None) -> tuple[seams.Model, list[Row], list[str]]:
    """The model, its checked rows (only ``env``'s when given) and each checker problem."""
    model = load_model(model_path)
    checkers = default_checkers(project.root)
    rows = check_rows(collect_rows(model, project.root, env), checkers)
    problems = [c.problem for c in checkers if isinstance(c, DockerSecretChecker) and c.problem]
    if not any(r.verdict == "unchecked" for r in rows):
        problems = []
    return model, rows, problems
