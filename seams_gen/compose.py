"""The docker compose generator (M004/S06, D016, D018).

``extract_compose`` reads the ``arch:Container``s that the model's one
``arch:System`` ``arch:contains`` into frozen dataclasses, using only
``deploy:``, ``arch:`` and ``seam:`` facts: the image from ``deploy:artifact``,
ports, ``deploy:dependsOn``, the ``deploy:configuration`` bindings (plain
values, external secrets, and service URLs), named volumes, the healthcheck,
replicas and the ``seam:deployedTo`` node's placement constraint.
``render_compose`` renders it through templates/compose.yaml.j2. The
serving container (``seams_gen.fastapi.serving_containers``: it
``seam:executes`` a process or exposes an operation a UI event submits to,
D026) also gets the TriG and every
``seam:renderPayload`` bind-mounted read-only under /model, with
SEAMS_MODEL/SEAMS_MODEL_HASH pointing the runtime at them (D018). When an
operation that container exposes is ``seam:implementedBy`` a
``comm:PythonHandler`` (ADR-0012), the handlers package beside the TriG is
bind-mounted read-only at /model/handlers too, where the runtime's default
looks for it. Bind
sources are relative to ``base_dir``, the directory the compose file is
written to. Every collection is sorted by IRI or key, and a missing or
ambiguous required fact raises ``GeneratorError`` naming the subject IRI and
predicate.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rdflib import RDFS
from seams import (
    ARCH,
    COMM,
    DEPLOY,
    SEAM,
    Binding,
    Container,
    Model,
    ModelGraph,
    ResolutionError,
    load,
    local_name,
)

from . import GeneratorError
from ._views import optional, required, view_errors
from .fastapi import serving_containers
from .htmx import _environment
from .stubs import DEFAULT_HANDLERS

TEMPLATE_NAME = "compose.yaml.j2"

MODEL_MOUNT = "/model"
SECRETS_DIR = "/run/secrets"
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ── the compose model ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Healthcheck:
    test: str  # the JSON-quoted deploy:probe
    interval: str


@dataclass(frozen=True)
class Service:
    name: str  # the container's local name
    image: str
    ports: tuple[str, ...]  # "published:container"
    expose: tuple[str, ...]  # "container"
    depends_on: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]  # (key, YAML scalar)
    secrets: tuple[str, ...]
    volumes: tuple[str, ...]  # YAML scalars
    healthcheck: Healthcheck | None = None
    replicas: int | None = None
    placement: str | None = None  # the constraint, as a YAML scalar


@dataclass(frozen=True)
class Secret:
    key: str  # the lower-cased deploy:key
    name: str  # deploy:secretName, as a YAML scalar


@dataclass(frozen=True)
class ComposeModel:
    model_stem: str
    model_hash: str
    services: tuple[Service, ...]
    secrets: tuple[Secret, ...]
    volumes: tuple[str, ...]


# ── extraction ──────────────────────────────────────────────────────────────


def _scalar(text: str) -> str:
    """``text`` as a YAML plain scalar when it loads back as the same str,
    otherwise as a JSON (YAML-compatible) double-quoted string."""
    try:
        if yaml.safe_load(text) == text:
            return text
    except yaml.YAMLError:
        pass
    return json.dumps(text)


def _posix_relpath(path: Path, base_dir: Path) -> str:
    return "./" + Path(os.path.relpath(Path(path).resolve(), Path(base_dir).resolve())).as_posix()


def extract_compose(model: Model, base_dir) -> ComposeModel:
    systems = model.architecture.systems()
    if len(systems) != 1:
        raise GeneratorError(model.subject, ARCH.contains, f"expected one arch:System, found {len(systems)}")
    containers = systems[0].containers
    if not containers:
        raise GeneratorError(systems[0].iri, ARCH.contains, "the arch:System contains no arch:Container")

    executing = _executing(model)
    mounts = _model_mounts(model, base_dir, executing) if executing else ()
    with view_errors():
        model_hash = model.hash

    secrets: dict[str, Secret] = {}
    volumes: set[str] = set()
    services = tuple(
        _service(model, c, set(containers), mounts if c in executing else None, secrets, volumes) for c in containers
    )
    return ComposeModel(
        model_stem=model.path.stem,
        model_hash=model_hash,
        services=services,
        secrets=tuple(secrets[k] for k in sorted(secrets)),
        volumes=tuple(sorted(volumes)),
    )


def _executing(model: Model):
    """The serving containers, which get the model mounts and SEAMS_MODEL_HASH; at most one."""
    with view_errors():
        executing = serving_containers(model)
    if len(executing) > 1:
        raise GeneratorError(
            model.subject,
            SEAM.executes,
            f"expected at most one serving container, found {[str(c) for c in executing.iris()]}",
        )
    return executing


def runtime_containers(model: Model) -> tuple[str, ...]:
    """The local names of the containers the compose file gives SEAMS_MODEL_HASH
    (the runtime containers ``seams status`` asks for /healthz, D045), sorted."""
    return tuple(sorted(local_name(c.iri) for c in _executing(model)))


def _model_mounts(model: Model, base_dir, executing) -> tuple[str, ...]:
    """The TriG then every seam:renderPayload and, when a comm:PythonHandler
    needs it, the handlers package, bind-mounted read-only."""
    base_dir = Path(base_dir)
    trig = f"{_posix_relpath(model.path, base_dir)}:{MODEL_MOUNT}/{model.path.name}:ro"
    with view_errors():
        payloads = model.payloads()
    binds = [f"{_posix_relpath(path, base_dir)}:{MODEL_MOUNT}/{rel}:ro" for rel, path in payloads]
    if _runs_handlers(model, executing):
        handlers = model.path.parent / DEFAULT_HANDLERS
        binds.append(f"{_posix_relpath(handlers, base_dir)}:{MODEL_MOUNT}/{DEFAULT_HANDLERS}:ro")
    return tuple(_scalar(m) for m in [trig, *sorted(binds)])


def _runs_handlers(model: Model, executing) -> bool:
    """True when an operation an executing container seam:exposes is
    seam:implementedBy a comm:PythonHandler (ADR-0012)."""
    graph = model if isinstance(model, ModelGraph) else ModelGraph(model.path, model.ds)
    with view_errors():
        for op in graph.operations:
            if not any(c in executing for c in op.exposed_by):
                continue
            impl = graph.operation_implementation(op.iri)
            if impl is not None and impl.kind == COMM.PythonHandler:
                return True
    return False


def _service(model: Model, c: Container, services: set, mounts, secrets: dict, volumes: set) -> Service:
    with view_errors():
        artifact = required(c.artifact, c.iri, DEPLOY.artifact)
        ports_ = c.ports
        named_volumes = c.volumes
        hc = c.healthcheck
        replicas = c.replicas
        node = optional(c.deployed_to)
        depends = c.deploy_depends_on
    image = f"{artifact.reference}:{artifact.version}"

    ports = [f"{p.published_port}:{p.container_port}" for p in ports_ if p.published_port is not None]
    expose = [str(p.container_port) for p in ports_ if p.published_port is None]

    depends_on = []
    for target in depends:
        if target not in services:
            raise GeneratorError(c.iri, DEPLOY.dependsOn, f"{target.iri} is not a container of the arch:System")
        depends_on.append(local_name(target.iri))

    environment, own_secrets = [], []
    if mounts is not None:
        environment += [
            ("SEAMS_MODEL", _scalar(f"{MODEL_MOUNT}/{model.path.name}")),
            ("SEAMS_MODEL_HASH", json.dumps(model.hash)),
        ]
    for key, entry in _bindings(c, services, secrets):
        environment.append(entry)
        if key is not None:
            own_secrets.append(key)

    named = []
    for v in named_volumes:
        named.append(_scalar(f"{v.name}:{v.mount_path}"))
        volumes.add(v.name)

    healthcheck = None
    if hc is not None:
        healthcheck = Healthcheck(test=json.dumps(hc.probe), interval=_scalar(hc.interval))

    placement = None
    if node is not None:
        try:
            node_label = model.label(node.iri, strict=True)
        except ResolutionError as err:
            raise GeneratorError(
                node.iri, RDFS.label, f"the seam:deployedTo node of {c.iri} needs exactly one rdfs:label"
            ) from err
        placement = _scalar(f"node.labels.seams.node == {node_label}")

    return Service(
        name=local_name(c.iri),
        image=_scalar(image),
        ports=tuple(ports),
        expose=tuple(expose),
        depends_on=tuple(sorted(depends_on)),
        environment=tuple(environment),
        secrets=tuple(sorted(own_secrets)),
        volumes=tuple(mounts or ()) + tuple(sorted(named)),
        healthcheck=healthcheck,
        replicas=replicas,
        placement=placement,
    )


def _bindings(c: Container, services: set, secrets: dict) -> list[tuple[str | None, tuple[str, str]]]:
    """[(secret key or None, (env key, YAML scalar))] sorted by deploy:key
    (``Container.bindings``). Bindings are blank nodes, so every error names
    the container."""
    with view_errors():
        bindings = c.bindings
    found: dict[str, Binding] = {}
    for b in bindings:
        if not ENV_KEY.match(b.key):
            raise GeneratorError(c.iri, DEPLOY.key, f"{b.key!r} is not an environment variable name")
        if b.key in found:
            raise GeneratorError(c.iri, DEPLOY.binding, f"deploy:key {b.key!r} is bound twice")
        found[b.key] = b

    entries = []
    for key in sorted(found):
        b = found[key]
        if len(b.kinds) != 1:
            raise GeneratorError(
                c.iri,
                DEPLOY.binding,
                f"binding {key!r} needs exactly one of deploy:value, deploy:secretRef, "
                f"deploy:serviceOf, found {len(b.kinds)}",
            )
        kind = b.kinds[0]
        if kind == DEPLOY.value:
            entries.append((None, (key, _scalar(required(b.value, c.iri, DEPLOY.value, f"binding {key!r}")))))
        elif kind == DEPLOY.secretRef:
            name = required(b.secret_name, c.iri, DEPLOY.secretName, f"binding {key!r}")
            secret = Secret(key=key.lower(), name=_scalar(name))
            if secrets.setdefault(secret.key, secret) != secret:
                raise GeneratorError(
                    c.iri,
                    DEPLOY.secretName,
                    f"binding {key!r}: secret {secret.key} is already named {secrets[secret.key].name}",
                )
            entries.append((secret.key, (f"{key}_FILE", _scalar(f"{SECRETS_DIR}/{secret.key}"))))
        else:
            target = b.service_of
            if target is None or target not in services:
                raise GeneratorError(
                    c.iri, DEPLOY.serviceOf, f"binding {key!r} needs one deploy:serviceOf container of the arch:System"
                )
            with view_errors():
                ports = target.ports
            if len(ports) != 1:
                raise GeneratorError(
                    target.iri,
                    DEPLOY.port,
                    f"binding {key!r} of {c.iri} needs the service's single deploy:port, found {len(ports)}",
                )
            url = f"http://{local_name(target.iri)}:{ports[0].container_port}"
            entries.append((None, (key, _scalar(url))))
    return entries


# ── rendering ───────────────────────────────────────────────────────────────


def render_compose(cm: ComposeModel) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(c=cm)


def generate_compose(trig_path, base_dir=None) -> str:
    """Load the model and render its compose file; bind-mount sources are
    relative to ``base_dir`` (default: the working directory), where the
    file is meant to be written."""
    base_dir = Path.cwd() if base_dir is None else Path(base_dir)
    return render_compose(extract_compose(load(trig_path), base_dir))


__all__ = [
    "ComposeModel",
    "Service",
    "Secret",
    "Healthcheck",
    "extract_compose",
    "generate_compose",
    "render_compose",
    "TEMPLATE_NAME",
]
