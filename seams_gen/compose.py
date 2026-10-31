"""The docker compose generator (M004/S06, D016, D018; ADR-0015).

The generator writes one compose file per ``arch:Environment`` of the model,
``compose.<environment local name>.yaml``, in IRI order
(``generate_compose_environments``). There is no shared compose.yaml and no
hand-written override: what differs between environments is a model fact.

``extract_compose`` reads the ``arch:Container``s that the model's one
``arch:System`` ``arch:contains`` into frozen dataclasses for one
environment, using only ``deploy:``, ``arch:`` and ``seam:`` facts. Each
container's artifact, bindings and replicas are its facts in that
environment under ADR-0015's override rule (``Container.for_environment``).
From them it renders:

- the image from ``deploy:artifact``; an artifact with a ``deploy:build`` adds
  ``build:`` (context and Dockerfile) and ``pull_policy: build``, so the
  image is built from this checkout rather than pulled;
- ports, ``deploy:dependsOn`` with ``condition: service_healthy`` when the
  target has a healthcheck and ``service_started`` otherwise, named volumes
  and the ``deploy:healthcheck`` with the fixed timeout, retries and start
  period defaults;
- the ``deploy:configuration`` bindings: plain values (``${KEY:-value}`` in
  the development environment, so a host can override them, and the literal
  elsewhere), external secrets, secrets read from a ``deploy:secretFile``
  (``file: ${KEY_FILE:-path}``) and service URLs;
- for a container that ``deploy:proxies`` another, Caddy's reverse-proxy
  command from its own single port to the target's;
- the ``seam:deployedTo`` node's placement constraint, only in the
  environment that ``arch:contains`` the node;
- the project ``name:``, the arch:System's local name lower-cased, and a
  header naming the model, its hash and the environment.

The serving container (``seams_gen.fastapi.serving_containers``: it
``seam:executes`` a process or exposes an operation a UI event submits to,
D026) also gets the TriG and every ``seam:renderPayload`` bind-mounted
read-only under /model, with SEAMS_MODEL/SEAMS_MODEL_HASH pointing the
runtime at them (D018). When an operation that container exposes is
``seam:implementedBy`` a ``comm:PythonHandler`` (ADR-0012), the handlers
package beside the TriG is bind-mounted read-only at /model/handlers too,
where the runtime's default looks for it. It gets the runtime's /healthz
probe unless the model states a healthcheck, the SEAMS_APP_DIR and
SEAMS_ROUTES_FILE build arguments when it is built, and at most one replica
until backlog A10, with a comment naming the declared count.

Bind sources, build contexts and secret files are relative to ``base_dir``,
the directory the compose file is written to; the model states them relative
to the model file's directory. Every collection is sorted by IRI or key, and
a missing or ambiguous required fact raises ``GeneratorError`` naming the
subject IRI and predicate.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rdflib import RDF, RDFS
from seams import (
    ARCH,
    COMM,
    DEPLOY,
    SEAM,
    Binding,
    Container,
    Environment,
    Model,
    ModelGraph,
    ResolutionError,
    load,
    local_name,
)

from . import GeneratorError
from ._views import optional, required, view_errors
from .fastapi import route_file_name, serving_containers
from .htmx import _environment
from .stubs import DEFAULT_HANDLERS

TEMPLATE_NAME = "compose.yaml.j2"

MODEL_MOUNT = "/model"
SECRETS_DIR = "/run/secrets"
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FILE_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

#: The environment whose deploy:value bindings render as ${KEY:-value}, so a
#: host can override them (ADR-0015); every other environment gets the literal.
DEVELOPMENT = "development"
#: The runtime always serves /healthz (ADR-0011's observability contract), so
#: the serving container's probe is a runtime rule, not a model fact.
RUNTIME_PROBE = (
    "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/healthz', timeout=3)\""
)
RUNTIME_PROBE_INTERVAL = "5s"
#: The serving container holds process instances and the live-update stream
#: in its process, so only one replica works until backlog A10.
SERVING_REPLICAS = 1
#: A deploy:proxies container is a code-free Caddy reverse proxy.
PROXY_COMMAND = "caddy reverse-proxy --from :{port} --to {target}:{target_port}"


# ── the compose model ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Healthcheck:
    test: str  # the JSON-quoted probe
    interval: str


@dataclass(frozen=True)
class Build:
    context: str  # YAML scalar, relative to base_dir
    dockerfile: str | None  # YAML scalar, relative to the context
    args: tuple[tuple[str, str], ...]  # (name, YAML scalar)


@dataclass(frozen=True)
class Dependency:
    name: str  # the target's local name
    condition: str  # service_healthy or service_started


@dataclass(frozen=True)
class Service:
    name: str  # the container's local name
    image: str
    ports: tuple[str, ...]  # "published:container"
    expose: tuple[str, ...]  # "container"
    depends_on: tuple[Dependency, ...]
    environment: tuple[tuple[str, str], ...]  # (key, YAML scalar)
    secrets: tuple[str, ...]
    volumes: tuple[str, ...]  # YAML scalars
    healthcheck: Healthcheck | None = None
    replicas: int | None = None
    placement: str | None = None  # the constraint, as a YAML scalar
    build: Build | None = None
    command: str | None = None  # YAML scalar
    declared_replicas: int | None = None  # the model's count when capped


@dataclass(frozen=True)
class Secret:
    key: str  # the lower-cased deploy:key
    name: str | None = None  # deploy:secretName, as a YAML scalar (an external secret)
    file: str | None = None  # ${<KEY>_FILE:-path}, as a YAML scalar (deploy:secretFile)


@dataclass(frozen=True)
class ComposeModel:
    model_stem: str
    model_hash: str
    environment: str  # the arch:Environment IRI
    project: str  # the arch:System's local name, lower-cased
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
    """``path`` relative to ``base_dir``, starting with ./ or ../ so compose reads it as a path."""
    rel = Path(os.path.relpath(Path(path).resolve(), Path(base_dir).resolve())).as_posix()
    return rel if rel.startswith("../") or rel == ".." else "./" + rel


def _model_path(model: Model, path: str, base_dir: Path) -> str:
    """A path the model states relative to its file's directory, relative to ``base_dir``."""
    rel = _posix_relpath(model.path.parent / path, base_dir)
    return "." if rel == "./." else rel


def environments(model: Model) -> tuple[Environment, ...]:
    """The model's arch:Environments, by IRI. None raises GeneratorError:
    each compose file is a file of one environment (ADR-0015)."""
    with view_errors():
        found = tuple(sorted(model.architecture.environments(), key=lambda e: str(e.iri)))
    if not found:
        raise GeneratorError(model.subject, RDF.type, "expected at least one arch:Environment, found none (ADR-0015)")
    return found


def compose_file_name(environment: Environment) -> str:
    """compose.<environment local name>.yaml."""
    stem = local_name(environment.iri)
    if not FILE_STEM.match(stem):
        raise GeneratorError(environment.iri, RDF.type, f"local name {stem!r} cannot name a compose file")
    return f"compose.{stem}.yaml"


def _resolve_environment(model: Model, environment) -> Environment:
    """``environment`` as an arch:Environment of the model: the view itself, its IRI or its local name."""
    if isinstance(environment, Environment):
        return environment
    declared = environments(model)
    for env in declared:
        if str(environment) in (str(env.iri), local_name(env.iri)):
            return env
    names = ", ".join(local_name(e.iri) for e in declared)
    raise GeneratorError(model.subject, RDF.type, f"no arch:Environment {environment!r}; the model declares {names}")


def extract_compose(model: Model, base_dir, environment) -> ComposeModel:
    """The compose model of ``environment`` (an ``Environment``, its IRI or its local name)."""
    env = _resolve_environment(model, environment)
    systems = model.architecture.systems()
    if len(systems) != 1:
        raise GeneratorError(model.subject, ARCH.contains, f"expected one arch:System, found {len(systems)}")
    system = systems[0]
    containers = system.containers
    if not containers:
        raise GeneratorError(system.iri, ARCH.contains, "the arch:System contains no arch:Container")

    executing = _executing(model)
    mounts = _model_mounts(model, base_dir, executing) if executing else ()
    with view_errors():
        model_hash = model.hash
        nodes = set(env.nodes)
        healthy = {c for c in containers if c.healthcheck is not None or c in executing}

    context = _Context(model, Path(base_dir), env, set(containers), healthy, nodes)
    secrets: dict[str, Secret] = {}
    volumes: set[str] = set()
    services = tuple(_service(context, c, mounts if c in executing else None, secrets, volumes) for c in containers)
    return ComposeModel(
        model_stem=model.path.stem,
        model_hash=model_hash,
        environment=str(env.iri),
        project=local_name(system.iri).lower(),
        services=services,
        secrets=tuple(secrets[k] for k in sorted(secrets)),
        volumes=tuple(sorted(volumes)),
    )


@dataclass(frozen=True)
class _Context:
    model: Model
    base_dir: Path
    environment: Environment
    services: set  # the arch:System's containers
    healthy: set  # the containers with a healthcheck
    nodes: set  # the deployment nodes the environment arch:contains

    @property
    def development(self) -> bool:
        return local_name(self.environment.iri) == DEVELOPMENT


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


def _single_port(c: Container, what: str) -> int:
    with view_errors():
        ports = c.ports
    if len(ports) != 1:
        raise GeneratorError(c.iri, DEPLOY.port, f"{what} needs the container's single deploy:port, found {len(ports)}")
    return ports[0].container_port


def _service(ctx: _Context, c: Container, mounts, secrets: dict, volumes: set) -> Service:
    model = ctx.model
    serving = mounts is not None
    with view_errors():
        deployment = c.for_environment(ctx.environment)
        ports_ = c.ports
        named_volumes = c.volumes
        hc = c.healthcheck
        node = optional(c.deployed_to)
        depends = c.deploy_depends_on
        proxied = c.proxies
    artifact = required(deployment.artifact, c.iri, DEPLOY.artifact)
    image = f"{artifact.reference}:{artifact.version}"

    ports = [f"{p.published_port}:{p.container_port}" for p in ports_ if p.published_port is not None]
    expose = [str(p.container_port) for p in ports_ if p.published_port is None]

    depends_on = []
    for target in depends:
        if target not in ctx.services:
            raise GeneratorError(c.iri, DEPLOY.dependsOn, f"{target.iri} is not a container of the arch:System")
        condition = "service_healthy" if target in ctx.healthy else "service_started"
        depends_on.append(Dependency(local_name(target.iri), condition))

    environment, own_secrets = [], []
    if serving:
        environment += [
            ("SEAMS_MODEL", _scalar(f"{MODEL_MOUNT}/{model.path.name}")),
            ("SEAMS_MODEL_HASH", json.dumps(model.hash)),
        ]
    for key, entry in _bindings(ctx, c, deployment.bindings, secrets):
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
    elif serving:
        probe = RUNTIME_PROBE.format(port=_single_port(c, "the runtime's /healthz probe"))
        healthcheck = Healthcheck(test=json.dumps(probe), interval=RUNTIME_PROBE_INTERVAL)

    build = None
    if artifact.build is not None:
        build = _build(ctx, c, artifact.build, serving)

    command = None
    if proxied is not None:
        if proxied not in ctx.services:
            raise GeneratorError(c.iri, DEPLOY.proxies, f"{proxied.iri} is not a container of the arch:System")
        command = _scalar(
            PROXY_COMMAND.format(
                port=_single_port(c, "a deploy:proxies container"),
                target=local_name(proxied.iri),
                target_port=_single_port(proxied, f"the deploy:proxies target of {c.iri}"),
            )
        )

    replicas, declared = deployment.replicas, None
    if serving and replicas is not None and replicas > SERVING_REPLICAS:
        replicas, declared = SERVING_REPLICAS, replicas

    placement = None
    if node is not None and node in ctx.nodes:
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
        depends_on=tuple(sorted(depends_on, key=lambda d: d.name)),
        environment=tuple(environment),
        secrets=tuple(sorted(own_secrets)),
        volumes=tuple(mounts or ()) + tuple(sorted(named)),
        healthcheck=healthcheck,
        replicas=replicas,
        placement=placement,
        build=build,
        command=command,
        declared_replicas=declared,
    )


def _build(ctx: _Context, c: Container, build, serving: bool) -> Build:
    """The build section: the context relative to ``base_dir`` and, for the
    serving container, the app directory (the model file's directory,
    relative to the context) and its route module as build arguments."""
    args: list[tuple[str, str]] = []
    if serving:
        context_dir = ctx.model.path.parent / build.context
        app_dir = Path(os.path.relpath(ctx.model.path.parent.resolve(), context_dir.resolve())).as_posix()
        args = [("SEAMS_APP_DIR", _scalar(app_dir)), ("SEAMS_ROUTES_FILE", _scalar(route_file_name(c.iri)))]
    return Build(
        context=_scalar(_model_path(ctx.model, build.context, ctx.base_dir)),
        dockerfile=None if build.dockerfile is None else _scalar(build.dockerfile),
        args=tuple(args),
    )


def _bindings(
    ctx: _Context, c: Container, bindings: tuple[Binding, ...], secrets: dict
) -> list[tuple[str | None, tuple[str, str]]]:
    """[(secret key or None, (env key, YAML scalar))] sorted by deploy:key, for
    the container's bindings in the environment. Bindings are blank nodes, so
    every error names the container."""
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
                f"deploy:secretFile, deploy:serviceOf, found {len(b.kinds)}",
            )
        kind = b.kinds[0]
        if kind == DEPLOY.value:
            value = required(b.value, c.iri, DEPLOY.value, f"binding {key!r}")
            entries.append((None, (key, _scalar(f"${{{key}:-{value}}}" if ctx.development else value))))
        elif kind in (DEPLOY.secretRef, DEPLOY.secretFile):
            if kind == DEPLOY.secretRef:
                name = required(b.secret_name, c.iri, DEPLOY.secretName, f"binding {key!r}")
                secret = Secret(key=key.lower(), name=_scalar(name))
            else:
                path = _model_path(ctx.model, required(b.secret_file, c.iri, DEPLOY.secretFile), ctx.base_dir)
                secret = Secret(key=key.lower(), file=_scalar(f"${{{key}_FILE:-{path}}}"))
            if secrets.setdefault(secret.key, secret) != secret:
                raise GeneratorError(
                    c.iri,
                    kind,
                    f"binding {key!r}: secret {secret.key} is already bound to another source in {ctx.environment.iri}",
                )
            entries.append((secret.key, (f"{key}_FILE", _scalar(f"{SECRETS_DIR}/{secret.key}"))))
        else:
            target = b.service_of
            if target is None or target not in ctx.services:
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


def generate_compose(trig_path, environment, base_dir=None) -> str:
    """Load the model and render the compose file of ``environment`` (its
    local name or IRI); paths are relative to ``base_dir`` (default: the
    working directory), where the file is meant to be written."""
    base_dir = Path.cwd() if base_dir is None else Path(base_dir)
    return render_compose(extract_compose(load(trig_path), base_dir, environment))


def generate_compose_environments(trig_path, base_dir=None) -> dict[str, str]:
    """{compose.<environment local name>.yaml: text} for every arch:Environment
    of the model, in IRI order (ADR-0015). A model without one, or two
    environments with one local name, raises GeneratorError."""
    base_dir = Path.cwd() if base_dir is None else Path(base_dir)
    model = load(trig_path)
    files: dict[str, str] = {}
    for env in environments(model):
        name = compose_file_name(env)
        if name in files:
            raise GeneratorError(env.iri, RDF.type, f"another arch:Environment is also named {local_name(env.iri)!r}")
        files[name] = render_compose(extract_compose(model, base_dir, env))
    return files


__all__ = [
    "Build",
    "ComposeModel",
    "Dependency",
    "Service",
    "Secret",
    "Healthcheck",
    "compose_file_name",
    "environments",
    "extract_compose",
    "generate_compose",
    "generate_compose_environments",
    "render_compose",
    "TEMPLATE_NAME",
]
