"""The docker compose generator (M004/S06, D016, D018).

``extract_compose`` reads the ``arch:Container``s that the model's one
``arch:System`` ``arch:contains`` into frozen dataclasses, using only
``deploy:``, ``arch:`` and ``seam:`` facts: the image from ``deploy:artifact``,
ports, ``deploy:dependsOn``, the ``deploy:configuration`` bindings (plain
values, external secrets, and service URLs), named volumes, the healthcheck,
replicas and the ``seam:deployedTo`` node's placement constraint.
``render_compose`` renders it through templates/compose.yaml.j2. The
container that ``seam:executes`` a process also gets the TriG and every
``seam:renderPayload`` bind-mounted read-only under /model, with
SEAMS_MODEL/SEAMS_MODEL_HASH pointing the runtime at them (D018). Bind
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
from rdflib import RDF, RDFS

from seams_runtime import ModelGraph, ResolutionError
from seams_runtime.model import DEPLOY, PROC, SEAM, _payload_files, local_name

from . import GeneratorError
from .facts import Facts
from .fastapi import ARCH
from .htmx import _environment

TEMPLATE_NAME = "compose.yaml.j2"

MODEL_MOUNT = "/model"
SECRETS_DIR = "/run/secrets"
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ── the compose model ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Healthcheck:
    test: str        # the JSON-quoted deploy:probe
    interval: str


@dataclass(frozen=True)
class Service:
    name: str        # the container's local name
    image: str
    ports: tuple[str, ...]        # "published:container"
    expose: tuple[str, ...]       # "container"
    depends_on: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]  # (key, YAML scalar)
    secrets: tuple[str, ...]
    volumes: tuple[str, ...]      # YAML scalars
    healthcheck: Healthcheck | None = None
    replicas: int | None = None
    placement: str | None = None  # the constraint, as a YAML scalar


@dataclass(frozen=True)
class Secret:
    key: str         # the lower-cased deploy:key
    name: str        # deploy:secretName, as a YAML scalar


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


def _value(f: Facts, owner, node, p, what: str) -> str:
    """The single value of ``p`` on a blank ``node``; errors name ``owner``."""
    values = f.objects(node, p)
    if len(values) != 1:
        found = "none" if not values else ", ".join(map(str, values))
        raise GeneratorError(owner, p, f"{what}: expected exactly one, found {found}")
    return str(values[0])


def _port(f: Facts, owner, node) -> int:
    port = f.int_value(node, DEPLOY.containerPort)
    if port is None:
        raise GeneratorError(owner, DEPLOY.containerPort, "a deploy:port needs a deploy:containerPort")
    return port


def extract_compose(model: ModelGraph, base_dir) -> ComposeModel:
    f = Facts(model)
    systems = f.subjects(RDF.type, ARCH.System)
    if len(systems) != 1:
        raise GeneratorError(model.subject, ARCH.contains,
                             f"expected one arch:System, found {len(systems)}")
    containers = [c for c in f.objects(systems[0], ARCH.contains) if (c, RDF.type, ARCH.Container) in f.ds]
    if not containers:
        raise GeneratorError(systems[0], ARCH.contains, "the arch:System contains no arch:Container")

    executing = sorted({c for c, p in f.ds.subject_objects(SEAM.executes)
                        if (c, RDF.type, ARCH.Container) in f.ds
                        and (p, RDF.type, PROC.Process) in f.ds}, key=str)
    if len(executing) > 1:
        raise GeneratorError(model.subject, SEAM.executes,
                             f"expected at most one executing container, found {[str(c) for c in executing]}")
    mounts = _model_mounts(model, base_dir) if executing else ()
    try:
        model_hash = model.hash
    except ResolutionError as err:
        raise GeneratorError(err.subject, err.predicate, err.detail) from err

    secrets: dict[str, Secret] = {}
    volumes: set[str] = set()
    services = tuple(
        _service(f, model, c, set(containers), mounts if c in executing else None, secrets, volumes)
        for c in containers)
    return ComposeModel(
        model_stem=model.path.stem,
        model_hash=model_hash,
        services=services,
        secrets=tuple(secrets[k] for k in sorted(secrets)),
        volumes=tuple(sorted(volumes)),
    )


def _model_mounts(model: ModelGraph, base_dir) -> tuple[str, ...]:
    """The TriG then every seam:renderPayload, bind-mounted read-only."""
    base_dir = Path(base_dir)
    trig = f"{_posix_relpath(model.path, base_dir)}:{MODEL_MOUNT}/{model.path.name}:ro"
    try:
        payloads = _payload_files(model.ds, model.base_dir)
    except ResolutionError as err:
        raise GeneratorError(err.subject, err.predicate, err.detail) from err
    binds = sorted(f"{_posix_relpath(path, base_dir)}:{MODEL_MOUNT}/{rel}:ro" for rel, path in payloads)
    return tuple(_scalar(m) for m in [trig, *binds])


def _service(f: Facts, model: ModelGraph, c, services: set, mounts, secrets: dict, volumes: set) -> Service:
    artifact = f.one(c, DEPLOY.artifact)
    image = (f"{_value(f, c, artifact, DEPLOY.reference, 'deploy:artifact')}:"
             f"{_value(f, c, artifact, DEPLOY.version, 'deploy:artifact')}")

    ports, expose = [], []
    for node in sorted(f.objects(c, DEPLOY.port), key=lambda n: _port(f, c, n)):
        published = f.int_value(node, DEPLOY.publishedPort)
        if published is None:
            expose.append(str(_port(f, c, node)))
        else:
            ports.append(f"{published}:{_port(f, c, node)}")

    depends_on = []
    for target in f.objects(c, DEPLOY.dependsOn):
        if target not in services:
            raise GeneratorError(c, DEPLOY.dependsOn, f"{target} is not a container of the arch:System")
        depends_on.append(local_name(target))

    environment, own_secrets = [], []
    if mounts is not None:
        environment += [("SEAMS_MODEL", _scalar(f"{MODEL_MOUNT}/{model.path.name}")),
                        ("SEAMS_MODEL_HASH", json.dumps(model.hash))]
    for key, entry in _bindings(f, c, services, secrets):
        environment.append(entry)
        if key is not None:
            own_secrets.append(key)

    named = []
    for node in f.objects(c, DEPLOY.volume):
        name = _value(f, c, node, DEPLOY.volumeName, "deploy:volume")
        named.append(_scalar(f"{name}:{_value(f, c, node, DEPLOY.mountPath, 'deploy:volume ' + name)}"))
        volumes.add(name)

    healthcheck = None
    hc = f.optional(c, DEPLOY.healthcheck)
    if hc is not None:
        healthcheck = Healthcheck(
            test=json.dumps(_value(f, c, hc, DEPLOY.probe, "deploy:healthcheck")),
            interval=_scalar(_value(f, c, hc, DEPLOY.interval, "deploy:healthcheck")))

    placement = None
    node = f.optional(c, SEAM.deployedTo)
    if node is not None:
        labels = f.objects(node, RDFS.label)
        if len(labels) != 1:
            raise GeneratorError(node, RDFS.label,
                                 f"the seam:deployedTo node of {c} needs exactly one rdfs:label")
        placement = _scalar(f"node.labels.seams.node == {labels[0]}")

    return Service(
        name=local_name(c),
        image=_scalar(image),
        ports=tuple(ports),
        expose=tuple(expose),
        depends_on=tuple(sorted(depends_on)),
        environment=tuple(environment),
        secrets=tuple(sorted(own_secrets)),
        volumes=tuple(mounts or ()) + tuple(sorted(named)),
        healthcheck=healthcheck,
        replicas=f.int_value(c, DEPLOY.replicas),
        placement=placement,
    )


def _bindings(f: Facts, c, services: set, secrets: dict) -> list[tuple[str | None, tuple[str, str]]]:
    """[(secret key or None, (env key, YAML scalar))] sorted by deploy:key.
    Bindings are blank nodes, so every error names the container."""
    found = {}
    for cfg in f.objects(c, DEPLOY.configuration):
        for b in f.objects(cfg, DEPLOY.binding):
            key = _value(f, c, b, DEPLOY.key, "deploy:binding")
            if not ENV_KEY.match(key):
                raise GeneratorError(c, DEPLOY.key, f"{key!r} is not an environment variable name")
            if key in found:
                raise GeneratorError(c, DEPLOY.binding, f"deploy:key {key!r} is bound twice")
            found[key] = b

    entries = []
    for key in sorted(found):
        b = found[key]
        kinds = [p for p in (DEPLOY.value, DEPLOY.secretRef, DEPLOY.serviceOf) if f.objects(b, p)]
        if len(kinds) != 1:
            raise GeneratorError(c, DEPLOY.binding,
                                 f"binding {key!r} needs exactly one of deploy:value, deploy:secretRef, "
                                 f"deploy:serviceOf, found {len(kinds)}")
        kind = kinds[0]
        if kind == DEPLOY.value:
            entries.append((None, (key, _scalar(_value(f, c, b, DEPLOY.value, f"binding {key!r}")))))
        elif kind == DEPLOY.secretRef:
            _value(f, c, b, DEPLOY.secretRef, f"binding {key!r}")
            name = _value(f, c, b, DEPLOY.secretName, f"binding {key!r}")
            secret = Secret(key=key.lower(), name=_scalar(name))
            if secrets.setdefault(secret.key, secret) != secret:
                raise GeneratorError(c, DEPLOY.secretName,
                                     f"binding {key!r}: secret {secret.key} is already named "
                                     f"{secrets[secret.key].name}")
            entries.append((secret.key, (f"{key}_FILE", _scalar(f"{SECRETS_DIR}/{secret.key}"))))
        else:
            targets = f.objects(b, DEPLOY.serviceOf)
            target = targets[0] if len(targets) == 1 else None
            if target not in services:
                raise GeneratorError(c, DEPLOY.serviceOf,
                                     f"binding {key!r} needs one deploy:serviceOf container of the arch:System")
            ports = f.objects(target, DEPLOY.port)
            if len(ports) != 1:
                raise GeneratorError(target, DEPLOY.port,
                                     f"binding {key!r} of {c} needs the service's single deploy:port, "
                                     f"found {len(ports)}")
            url = f"http://{local_name(target)}:{_port(f, target, ports[0])}"
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
    return render_compose(extract_compose(ModelGraph.load(trig_path), base_dir))


__all__ = ["ComposeModel", "Service", "Secret", "Healthcheck", "extract_compose", "generate_compose",
           "render_compose", "TEMPLATE_NAME"]
